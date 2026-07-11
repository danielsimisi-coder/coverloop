"""Canonical secret-pattern filter for the operator's GLM/M3 advisory CLIs and
the coverloop gate. Single source of truth — imported by glm-review, m3-review
(egress gate, use scan()) and bin/coverloop (transcript redaction, use redact()).
Bump FILTER_VERSION on any change; Mac and VPS copies must match (verify via --version).
"""
import re

FILTER_VERSION = "2026-07-11b"

# Literal substrings that flag "this text likely references a secret" — used by
# scan() as a heuristic egress tripwire. NOT redacted (they are variable names,
# not values; redacting them would corrupt legitimate review prose).
LITERAL_PATTERNS = [
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "SUPABASE_SERVICE_ROLE", "service_role", "DATABASE_URL", "VERCEL_TOKEN",
    "PRIVATE KEY",
]

# VALUE patterns — actual secret SHAPES. Used by BOTH scan() (detect) and
# redact() (replace). Each is (label, compiled-regex). Boundaries keep ordinary
# kebab tokens (risk-based, task-start) from matching the sk- rule.
VALUE_PATTERNS = [
    ("sk-key",       re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"(?<![A-Za-z0-9])(?:ghp|gho|ghs|ghu|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("aws-key",      re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])")),
    ("slack-token",  re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google-key",   re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("jwt",          re.compile(r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}")),
    ("bearer",       re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("db-url-cred",  re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb)(?:\+[a-z]+)?://[^\s:/@]+:[^\s@]+@")),
    # Bounded inter-marker span (.{0,10000}?) — a real PEM body is <~3.2KB, and
    # an unbounded .*? under DOTALL rescans to EOF from every BEGIN candidate
    # when no END marker exists (quadratic ReDoS). 10KB caps each start's scan.
    ("private-key",  re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.{0,10000}?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
]

# Assignment of a secret-NAMED variable to ANY value (even an unrecognized
# shape): `VERCEL_TOKEN=...`, `DB_PASSWORD: ...`, `X_API_KEY=...`. redact()
# strips the value but keeps the name, so a config/env dump can't leak a secret
# just because its value isn't one of the known token shapes above.
ASSIGN_RE = re.compile(
    # Leading `\b` is the ReDoS guard: a secret name starts at a word boundary,
    # and a long word-char run (the attack input) has NO interior boundaries, so
    # the engine skips those millions of offsets in O(1) instead of re-expanding
    # the variable prefix at every one. The `{0,64}` bound (env var names are
    # short) caps per-boundary work as defense-in-depth. Without `\b`, an
    # unbounded `[A-Za-z0-9_]*` before a required suffix backtracks O(n^2) and
    # hangs scan() — the egress path — on a pathological input (ReDoS; found by
    # the R2 timing test).
    r"(?i)(\b(?:OPENROUTER_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|SUPABASE_SERVICE_ROLE"
    # `[_-]KEY` catches the bare _KEY family (AWS_SECRET_ACCESS_KEY, SECRET_KEY,
    # ENCRYPTION_KEY, SIGNING_KEY, PRIVATE_KEY) that `API[_-]?KEY` alone missed;
    # the separator requirement still skips MONKEY=/HOTKEY=.
    r"|service_role|DATABASE_URL|VERCEL_TOKEN|[A-Za-z0-9_]{0,64}(?:API[_-]?KEY|[_-]KEY|SECRET|TOKEN|PASSWORD|PASSWD))"
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

# Back-compat: some callers referenced KEY_RE directly.
KEY_RE = VALUE_PATTERNS[0][1]

# Kept for --version display / parity reporting (NOT used for matching directly).
SECRET_PATTERNS = LITERAL_PATTERNS + [label for label, _ in VALUE_PATTERNS]


def scan(text):
    """Return list of matched secret indicators (empty = clean)."""
    hits = [p for p in LITERAL_PATTERNS if p in text]
    for label, rx in VALUE_PATTERNS:
        if rx.search(text):
            hits.append(label)
    if ASSIGN_RE.search(text):
        hits.append("secret-assignment")
    return hits


def redact(text):
    """Replace actual secret VALUES with [REDACTED:<label>]; return the result.
    Known token shapes are removed anywhere; the value of a secret-NAMED
    assignment is removed regardless of shape (keeping the name). Legitimate
    prose survives — only values are touched, never bare name mentions."""
    out = text
    for label, rx in VALUE_PATTERNS:
        out = rx.sub(f"[REDACTED:{label}]", out)
    out = ASSIGN_RE.sub(lambda m: m.group(1) + (m.group(2) or "") + "[REDACTED:secret-value]", out)
    # PII pass (committed-transcript hygiene, v2.7.2): keep the path prefix
    # readable, drop the identifying username; emails/UUIDs replaced whole.
    out = PII_PATTERNS[0][1].sub(r"\1[REDACTED:user]", out)
    out = PII_PATTERNS[1][1].sub("[REDACTED:email]", out)
    out = PII_PATTERNS[2][1].sub("[REDACTED:uuid]", out)
    return out
