"""Canonical secret-pattern filter for the operator's GLM/M3 advisory CLIs and
the coverloop gate. Single source of truth — imported by glm-review, m3-review
(egress gate, use scan()) and bin/coverloop (transcript redaction, use redact()).
Bump FILTER_VERSION on any change; Mac and VPS copies must match (verify via --version).
"""
import re

FILTER_VERSION = "2026-07-15c"

# Literal substrings that flag "this text likely references a secret" — used by
# scan() as a heuristic egress tripwire. NOT redacted (they are variable names,
# not values; redacting them would corrupt legitimate review prose).
LITERAL_PATTERNS = [
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "SUPABASE_SERVICE_ROLE", "service_role", "DATABASE_URL", "VERCEL_TOKEN",
    "PRIVATE KEY",
]

# VALUE patterns — actual secret SHAPES. Used by BOTH scan() (detect) and
# redact() (replace). Each is (label, compiled-regex, guard): GUARD is an
# optional cheap substring that MUST be present for the regex to have any chance
# of matching; when set, scan()/redact() skip the regex entirely if the guard is
# absent (an O(1)-per-call `in` check instead of running the engine). This is a
# ReDoS floor: for the private-key pattern, thousands of `-----BEGIN` markers
# with NO `-----END` made the engine do a bounded forward scan PER marker
# (~O(markers x bound)); the guard makes a no-END input skip the pattern
# outright (R3 fuzz test caught 2.9s on 0.6 MB of bare BEGIN markers).
# Boundaries keep ordinary kebab tokens (risk-based, task-start) off the sk- rule.
VALUE_PATTERNS = [
    ("sk-key",       re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"), "sk-"),
    ("github-token", re.compile(r"(?<![A-Za-z0-9])(?:ghp|gho|ghs|ghu|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "gh"),
    ("aws-key",      re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])"), None),
    ("slack-token",  re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}"), "xox"),
    ("google-key",   re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"), "AIza"),
    ("jwt",          re.compile(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}"), "eyJ"),
    ("bearer",       re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), None),
    ("db-url-cred",  re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb)(?:\+[a-z]+)?://[^\s:/@]+:[^\s@]+@"), "://"),
    # Inter-marker span is a TEMPERED dot `(?:(?!-----).)` — any char that does
    # not begin a `-----` marker run. A real PEM body (base64 + whitespace, plus
    # `Proc-Type:`/`DEK-Info:` headers on encrypted keys) never contains five
    # consecutive dashes, so this matches every real key, but a BEGIN can no
    # longer scan ACROSS the next marker: thousands of bare `-----BEGIN` markers
    # (with or without a distant END) each fail in O(1). Because the tempered dot
    # ALREADY bounds the scan at the next marker, the span is UNBOUNDED on
    # purpose — a fixed `{0,N}` cap was a secret-leak cliff (Sol R3 P2: a
    # 16384-bit RSA key's ~10.5KB body exceeded a 10K cap and stopped redacting),
    # the same class of regression as the R2 name-prefix bound. Each character is
    # scanned by at most one BEGIN, so it stays linear. The "-----END" GUARD
    # skips the pattern entirely when no END marker exists at all. (R3 fuzz test:
    # 0.6 MB of BEGIN markers went 2.9s -> instant.)
    ("private-key",  re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?!-----).)*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "-----END"),
]

# Assignment of a secret-NAMED variable to ANY value (even an unrecognized
# shape): `VERCEL_TOKEN=...`, `DB_PASSWORD: ...`, `X_API_KEY=...`. redact()
# strips the value but keeps the name, so a config/env dump can't leak a secret
# just because its value isn't one of the known token shapes above.
ASSIGN_RE = re.compile(
    # Leading `\b` is the ReDoS guard AND the whole guarantee: a secret name
    # starts at a word boundary, and a long word-char run (the attack input) has
    # NO interior boundaries, so re.search skips those millions of offsets in
    # O(1) instead of re-expanding the variable prefix at each. With `\b` in
    # place the prefix `*` backtracks only at the O(1) run-start boundaries, so
    # the pattern is linear even UNBOUNDED (measured: 2 MB adversarial input
    # ~0.1s). The prefix is therefore left unbounded on purpose: a `{0,N}` cap
    # would silently stop redacting a name whose prefix exceeds N (Sol/GLM R2
    # caught `A*65 + _KEY=secret` leaking under a {0,64} cap) — a real
    # secret-leak regression — while buying no ReDoS safety `\b` doesn't already
    # give. Without `\b`, unbounded `*` before a required suffix is O(n^2) and
    # hangs scan() (the egress path) on a pathological input.
    r"(?i)(\b(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|SUPABASE_SERVICE_ROLE"
    # `[_-]KEY` catches the bare _KEY family (AWS_SECRET_ACCESS_KEY, SECRET_KEY,
    # ENCRYPTION_KEY, SIGNING_KEY, PRIVATE_KEY) that `API[_-]?KEY` alone missed;
    # the separator requirement still skips MONKEY=/HOTKEY=.
    r"|service_role|DATABASE_URL|VERCEL_TOKEN|[A-Za-z0-9_]*(?:API[_-]?KEY|[_-]KEY|SECRET|TOKEN|PASSWORD|PASSWD))"
    # value: when QUOTED, span to the MATCHING closing quote (a backreference —
    # so an inner apostrophe in "horse's staple" doesn't cut it short); when
    # unquoted, a bare token. No {3,} floor — TOKEN=x must redact too.
    # (Sol v2.7.3 verify #3)
    r"\s*[=:]\s*)(?P<q>['\"])?(?P<val>(?(q)[^\r\n]*?(?=(?P=q)|[\r\n]|$)|[^\s'\"]+))")

# PII shapes (v2.7.2) — redacted from transcripts before they are COMMITTED to
# git (redact() only). Deliberately NOT part of scan(): scan() is the egress
# tripwire for secrets, and blocking every email/path-shaped string would break
# legitimate review packets. This is targeted transcript hygiene — home-dir
# usernames, emails, UUID-shaped session ids — a tripwire, NOT a full DLP pass.
PII_PATTERNS = [
    # Match the WHOLE path component after /Users// /home/ (up to the next
    # slash or whitespace), so single-char and underscore-leading usernames are
    # caught and a long name can't leak its tail past a fixed length cap
    # (Sol v2.7.2 review #2). Slightly over-redacts real dir names like
    # /Users/Shared — acceptable for transcript hygiene (drop a dir, never leak
    # a username).
    ("pii-user",  re.compile(r"(?<![A-Za-z0-9_])(/(?:Users|home)/)([^/\s]+)")),
    ("pii-email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("pii-uuid",  re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                             r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
]

# ---- scan()-side false-positive gate for ASSIGN_RE (2026-07-15b, operator-directed) ----
# ASSIGN_RE's name family (…TOKEN/…SECRET/…PASSWORD/…KEY) also matches everyday AUTH-CODE idioms:
# `autoRefreshToken: true`, test fixtures like `access_token: 'at-1'`, code references like
# `storageKey: platformStorageKey(url)` — which made scan() structurally unable to review
# supabase-client code. The gate below narrows ONLY scan() (the egress block): redact() is
# deliberately unchanged (over-redacting a transcript is safe; over-blocking an egress packet
# breaks legitimate L3 reviews).
#
# Rules (Sol round-2 hardened — trust CONTENT, never "expression shape"):
#   * `=` assignments (env/config dumps — the rule's original target) keep FULL strictness.
#   * A value that is EXACTLY one of this filter's own [REDACTED:<label>] markers is clean
#     (scan∘redact marker-idempotency). A marker with ANY suffix/prefix or left unclosed is NOT
#     exempt (smuggling a payload behind a marker still blocks).
#   * `:` assignments are exempt for boolean/null literals; EVERYTHING else is decided by
#     scanning the REST OF THE LINE from the value start (so nested-quote tricks, fn('…')
#     arguments the regex's value capture never reaches, backtick templates, and minified
#     `;NAME=…` tails are all examined — a "short captured value" alone proves nothing):
#       - any QUOTED span with >= _MIN_OPAQUE_LEN chars of content  -> blocks
#       - any bareword run >= _MIN_BAREWORD_LEN not immediately followed by '(' (call names like
#         platformStorageKey( are code, not literals)               -> blocks
#       - any '=' anywhere in the tail (a swallowed env-style pair) -> blocks
#       - a YAML block-scalar indicator (| or >) as the value       -> blocks (payload is on the
#         next lines where no assignment match would look)
# There is NO env/flag escape hatch, by design.
_REDACTED_MARKER_RE = re.compile(r"^\[REDACTED:[a-z-]+\]$")
_BOOL_NULL_RE = re.compile(r"(?i)^(?:true|false|null|none|nil|undefined)$")
_YAML_BLOCK_RE = re.compile(r"^[|>][0-9+-]*$")  # incl. indentation indicators |2 >+2 (Sol r2)
_QUOTED_SPAN_RE = re.compile(r"['\"]([^'\"\r\n]{8,})['\"]")
_BAREWORD_RE = re.compile(r"[A-Za-z0-9_+/@#$%^&*!-]{16,}")
_MIN_OPAQUE_LEN = 8
_MIN_BAREWORD_LEN = 16  # enforced by _BAREWORD_RE's quantifier


def _assignment_leaks(m, text, tail_cap=None):
    """True when an ASSIGN_RE match can actually leak secret material (see gate note above).
    tail_cap bounds the content scan at the NEXT assignment match (linearity: each character is
    scanned by at most one match — Sol r2 measured the uncapped version quadratic on repeated
    matches; the union of capped segments still covers the whole line, and anything past the cap
    belongs to the next match's own scan)."""
    val = (m.group("val") or "").rstrip(",;")
    if _REDACTED_MARKER_RE.match(val):
        return False  # exactly a redaction marker — scan(redact(x)) idempotency
    if "=" in m.group(1):
        return True  # env-style assignment: the rule's original target, full strictness
    if _BOOL_NULL_RE.match(val):
        return False
    if _YAML_BLOCK_RE.match(val):
        return True  # YAML block scalar: the payload lives on following lines — stay closed
    # Content scan over the rest of the physical line from the value start. NOTE: no standalone
    # short-value exemption — the regex's value capture stops at the first quote (`fn('secret')`
    # captures only `fn(`), so ONLY the tail rules below may clear a match (Sol r1 catch).
    # Starts at the OPENING quote when the value is quoted, so the quoted-span rule sees the pair.
    start = m.start("q") if m.group("q") else m.start("val")
    tail_end = text.find("\n", start)
    if tail_end == -1:
        tail_end = len(text)
    if tail_cap is not None:
        tail_end = min(tail_end, max(tail_cap, m.end()))
    tail = text[start:tail_end]
    if "=" in tail:
        return True  # a swallowed env-style pair hides in the same match's shadow
    # escaped quotes are stripped BEFORE span pairing, so \" truncation tricks can't split a
    # long literal into two short-looking spans (Sol r2)
    tail_spans = tail.replace('\\"', "").replace("\\'", "")
    if _QUOTED_SPAN_RE.search(tail_spans):
        return True  # an opaque quoted literal the value capture may not have reached
    for bm in _BAREWORD_RE.finditer(tail):
        # call names are code, not literals: platformStorageKey(url) / fn (x) / fn?.(x)
        if not _CALL_AFTER_RE.match(tail, bm.end()):
            return True  # long opaque bareword that is not a call name
    return False


_CALL_AFTER_RE = re.compile(r"[ \t]*(?:\?\.)?\(")


# Back-compat: some callers referenced KEY_RE directly.
KEY_RE = VALUE_PATTERNS[0][1]

# Kept for --version display / parity reporting (NOT used for matching directly).
SECRET_PATTERNS = LITERAL_PATTERNS + [t[0] for t in VALUE_PATTERNS]


def scan(text):
    """Return list of matched secret indicators (empty = clean)."""
    hits = [p for p in LITERAL_PATTERNS if p in text]
    for label, rx, guard in VALUE_PATTERNS:
        if guard and guard not in text:
            continue
        if rx.search(text):
            hits.append(label)
    assign_matches = list(ASSIGN_RE.finditer(text))
    for i, m in enumerate(assign_matches):
        nxt = assign_matches[i + 1].start() if i + 1 < len(assign_matches) else None
        if _assignment_leaks(m, text, tail_cap=nxt):
            hits.append("secret-assignment")
            break
    return hits


def redact(text):
    """Replace actual secret VALUES with [REDACTED:<label>]; return the result.
    Known token shapes are removed anywhere; the value of a secret-NAMED
    assignment is removed regardless of shape (keeping the name). Legitimate
    prose survives — only values are touched, never bare name mentions."""
    out = text
    for label, rx, guard in VALUE_PATTERNS:
        if guard and guard not in out:
            continue
        out = rx.sub(f"[REDACTED:{label}]", out)
    out = ASSIGN_RE.sub(lambda m: m.group(1) + (m.group(2) or "") + "[REDACTED:secret-value]", out)
    # PII pass (committed-transcript hygiene, v2.7.2): keep the path prefix
    # readable, drop the identifying username; emails/UUIDs replaced whole.
    out = PII_PATTERNS[0][1].sub(r"\1[REDACTED:user]", out)
    out = PII_PATTERNS[1][1].sub("[REDACTED:email]", out)
    out = PII_PATTERNS[2][1].sub("[REDACTED:uuid]", out)
    return out
