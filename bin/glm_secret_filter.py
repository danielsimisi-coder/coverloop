"""Canonical secret-pattern filter for the operator's GLM/M3 advisory CLIs and
the coverloop gate. Single source of truth — imported by glm-review, m3-review
(egress gate, use scan()) and bin/coverloop (transcript redaction, use redact()).
Bump FILTER_VERSION on any change; Mac and VPS copies must match (verify via --version).
"""
import re

FILTER_VERSION = "2026-07-15h"

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

# ---- scan()-side false-positive gate for ASSIGN_RE (2026-07-15f, operator-directed) ----
# ASSIGN_RE's name family (…TOKEN/…SECRET/…PASSWORD/…KEY) also matches everyday AUTH-CODE idioms:
# `autoRefreshToken: true`, test fixtures like `access_token: 'at-1'`, code references like
# `storageKey: platformStorageKey(url)` — which made scan() structurally unable to review
# supabase-client code. The gate below narrows ONLY scan() (the egress block): redact() is
# deliberately unchanged (over-redacting a transcript is safe; over-blocking an egress packet
# breaks legitimate L3 reviews).
#
# Two layers (Sol r1-r5 hardened — trust CONTENT, never "expression shape"):
#   1. Per-match VALUE rules (_val_level_verdict): `=` assignments (env/config dumps — the rule's
#      original target) keep FULL strictness; a value that is EXACTLY a [REDACTED:<label>] marker
#      is clean (scan∘redact marker-idempotency; any suffix/prefix voids it); boolean/null
#      literals are clean; YAML block scalars (|/> incl. indentation indicators) block — the
#      payload lives on lines no assignment match would scan; a QUOTED captured value of
#      >= _MIN_OPAQUE_LEN blocks outright (quote pairing is ambiguous — fail closed, Sol r5).
#   2. Per-LINE content scan (_line_block_max) for every match the value rules leave undecided:
#      the whole physical line is lexed ONCE from LINE START with a parity-aware sequential
#      string lexer (an escaped quote — odd backslash run — never opens/closes a literal;
#      an unterminated literal runs to end-of-line, fail closed). Blocking signals and their
#      positions: a string literal with >= _MIN_OPAQUE_LEN chars of content; a bareword run
#      >= 16 chars not immediately followed by a call `(` (with optional space / `?.`); any `=`.
#      A match leaks iff ANY blocking signal sits at/after its value start — one O(line) pass
#      per line, one integer (max blocking position) answers every match on it (linear overall;
#      Sol r2/r4 measured the per-match rescans quadratic, and Sol r3/r5 showed every
#      mid-line-cap / stateful-deferral variant splits or shifts literal pairing).
#   3. PLAIN-SCALAR rule (Sol r6): a match whose tail sits in the line's trailing zone with NO
#      code punctuation at all (env/YAML dumps, prose — never real code, which always carries
#      , ; ) } etc.) blocks when the value zone holds >= 2 words (multiword passphrase) or one
#      word of >= _MIN_OPAQUE_LEN (an unquoted opaque token below the bareword threshold).
#      This restores main's strictness for `DB_PASSWORD: correct horse battery staple` and
#      `AUTH_TOKEN: abcdefghijklmno` while code idioms (`refresh_token: currentRt,`) stay clean
#      via their punctuation.
# There is NO env/flag escape hatch, by design.
_REDACTED_MARKER_RE = re.compile(r"^\[REDACTED:[a-z-]+\]$")
_BOOL_NULL_RE = re.compile(r"(?i)^(?:true|false|null|none|nil|undefined)$")
_YAML_BLOCK_RE = re.compile(r"^[|>][0-9+-]*$")  # incl. indentation indicators |2 >+2 (Sol r2)
_BAREWORD_RE = re.compile(r"[A-Za-z0-9_+/@#$%^&*!-]{16,}")
_CALL_AFTER_RE = re.compile(r"[ \t]*(?:\?\.)?\(")
# A bareword is a code IDENTIFIER (object key / call name), not an opaque literal, only when it is
# a pure identifier shape AND immediately begins a call `(` or a key `:` (Sol r8: a `:`-lookahead
# alone let a pure-alnum SECRET used as a map key escape — an opaque secret carries +/@#!%^&*- which
# the identifier shape rejects).
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*$")
_CODE_AFTER_RE = re.compile(r"[ \t]*(?:\?\.)?\(|[ \t]*:")
_MIN_OPAQUE_LEN = 8
_CODE_PUNCT = set("()[]{};,=<>`|&")
_WORD_RE = re.compile(r"\S+")
# YAML fold/block continuation: after `KEY: true` the real scalar can continue on MORE-indented
# following lines (`true correct horse battery staple`). Bounded to a few lines to stay linear.
_MAX_FOLD_LINES = 8


def _val_level_verdict(m):
    """Per-match value rules. True = leaks; False = the CAPTURED value is clean (the line layers
    still run from the value's END — a payload after `true` / a marker is not exempt, Sol r7);
    None = undecided (line layers run from the value START). Split from the line scan so a
    bool/marker early exit can never stand in for a scan that was skipped (Sol r4)."""
    val = (m.group("val") or "").rstrip(",;")
    if _REDACTED_MARKER_RE.match(val):
        return False  # exactly a redaction marker — scan(redact(x)) idempotency
    if "=" in m.group(1):
        return True  # env-style assignment: the rule's original target, full strictness
    if _BOOL_NULL_RE.match(val):
        return False
    if _YAML_BLOCK_RE.match(val):
        return True  # YAML block scalar: the payload lives on following lines — stay closed
    if m.group("q") and len(val) >= _MIN_OPAQUE_LEN:
        # A QUOTED literal of opaque length directly assigned to a secret-family name blocks at
        # the match level, independent of line lexing — quote pairing is genuinely ambiguous
        # (`'a_key:'x y'` reads both ways; Sol r5 reproducer), so the fail-closed reading wins.
        return True
    return None


def _line_block_max(line):
    """Max offset (in `line`) of any blocking content signal, or -1 when the line is clean.
    Single pass, positions monotonic and independent of any match position — the lexer starts at
    LINE START, so quote pairing can never differ between two matches on the same line (Sol r5:
    a per-match tail lexer was stateful and a skipped later match could see different pairing)."""
    max_pos = line.rfind("=")
    run = 0
    quote = None
    lit_open = -1
    for i, c in enumerate(line):
        if c == "\\":
            run += 1
            continue
        escaped = (run % 2) == 1
        run = 0
        if quote is None:
            if (c == "'" or c == '"') and not escaped:
                quote, lit_open = c, i
        elif c == quote and not escaped:
            content = line[lit_open + 1:i]
            if len(content) >= _MIN_OPAQUE_LEN and lit_open > max_pos and not _REDACTED_MARKER_RE.match(content):
                max_pos = lit_open
            quote = None
    if quote is not None and len(line) - lit_open - 1 >= _MIN_OPAQUE_LEN and lit_open > max_pos:
        max_pos = lit_open  # unterminated literal: fail closed
    for bm in _BAREWORD_RE.finditer(line):
        # call names and pure-identifier object KEYS are code, not literals: platformStorageKey(url)
        # / fn (x) / fn?.(x) / detectSessionInUrl: (long camelCase option names — Sol r7). An OPAQUE
        # secret (has +/@#!%^&*-) fails _IDENT_RE, so a secret-as-map-key still blocks (Sol r8).
        if bm.start() <= max_pos:
            continue
        word = line[bm.start():bm.end()]
        if _CODE_AFTER_RE.match(line, bm.end()) and _IDENT_RE.match(word):
            continue
        max_pos = bm.start()
    return max_pos


def _line_plain_zone(line):
    """(zone_start, word_starts, word_lens) for the trailing code-punctuation-free zone of the
    line — the region where an unquoted value reads as an env/YAML plain scalar, not code."""
    zone_start = 0
    for i, c in enumerate(line):
        if c in _CODE_PUNCT:
            zone_start = i + 1
    starts, lens = [], []
    for wm in _WORD_RE.finditer(line, zone_start):
        starts.append(wm.start())
        lens.append(wm.end() - wm.start())
    return zone_start, starts, lens


def _plain_zone_leaks(zone, value_start):
    """Plain-scalar rule (layer 3): >= 2 words, or one word >= _MIN_OPAQUE_LEN, at/after the
    value start inside the punctuation-free zone."""
    zone_start, starts, lens = zone
    if value_start < zone_start:
        return False  # code punctuation follows the value — it's code, layers 1-2 own it
    from bisect import bisect_left
    i = bisect_left(starts, value_start)
    n = len(starts) - i
    if n >= 2:
        return True
    return n == 1 and lens[i] >= _MIN_OPAQUE_LEN


def _fold_continuation_leaks(text, line_start, line_end):
    """When an exempt (bool/null/marker) value ENDS its physical line, a YAML fold/block can carry
    the real scalar onto MORE-indented following lines (`AUTH_TOKEN: true\\n  correct horse …`).
    Scan those continuation lines with the plain-scalar rule. Bounded to _MAX_FOLD_LINES (linear).
    Returns True if a continuation line holds >= 2 words or one word >= _MIN_OPAQUE_LEN (Sol r8)."""
    key_indent = len(text[line_start:line_end]) - len(text[line_start:line_end].lstrip())
    pos = line_end
    for _ in range(_MAX_FOLD_LINES):
        if pos >= len(text) or text[pos] != "\n":
            break
        nxt = pos + 1
        nend = text.find("\n", nxt)
        if nend == -1:
            nend = len(text)
        cline = text[nxt:nend]
        if not cline.strip():
            pos = nend
            continue  # blank line inside a block scalar
        indent = len(cline) - len(cline.lstrip())
        if indent <= key_indent:
            break  # de-indent ends the continuation
        # a continuation line that is a nested `key:` mapping is structure, not a folded scalar
        stripped = cline.strip()
        if _IDENT_RE.match(stripped.split(":", 1)[0]) and ":" in stripped:
            break
        words = stripped.split()
        if len(words) >= 2 or (words and len(words[0]) >= _MIN_OPAQUE_LEN):
            return True
        pos = nend
    return False


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
    # Line tracking is INCREMENTAL (each rfind covers only the span since the previous match) so
    # a single line with many matches stays linear (Sol r4 P3). The line's content verdict is one
    # cached integer (max blocking position) — every undecided match on the line compares its own
    # value start against it (Sol r5: position-independent, lexer-safe).
    line_start = 0
    search_from = 0
    cached_line_start = -1
    cached_block_max = -1
    cached_zone = (0, [], [])
    for m in ASSIGN_RE.finditer(text):
        nl = text.rfind("\n", search_from, m.start())
        if nl != -1:
            line_start = nl + 1
        search_from = m.start()
        verdict = _val_level_verdict(m)
        if verdict is True:
            hits.append("secret-assignment")
            break
        if line_start != cached_line_start:
            cached_line_start = line_start
            cached_line_end = text.find("\n", line_start)
            if cached_line_end == -1:
                cached_line_end = len(text)
            line = text[line_start:cached_line_end]
            cached_block_max = _line_block_max(line)
            cached_zone = _line_plain_zone(line)
        # False (bool/marker): the CAPTURED value is exempt but anything after it is not — the
        # line layers run from the value's END (Sol r7: `AUTH_TOKEN: true actualsecret123`).
        if verdict is False:
            check_from = m.end() - line_start
        else:
            check_from = (m.start("q") if m.group("q") else m.start("val")) - line_start
        if cached_block_max >= check_from or _plain_zone_leaks(cached_zone, check_from):
            hits.append("secret-assignment")
            break
        # An exempt value that ENDS its line may be a YAML fold whose scalar continues indented
        # below (Sol r8). Only bool/null/marker exempt values can reach here at line-end.
        if verdict is False and m.end() >= cached_line_end and _fold_continuation_leaks(
            text, line_start, cached_line_end
        ):
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
