"""Canonical secret-pattern filter for the operator's GLM/M3 advisory CLIs and
the coverloop gate. Single source of truth — imported by glm-review, m3-review
(egress gate, use scan()) and bin/coverloop (transcript redaction, use redact()).
Bump FILTER_VERSION on any change; Mac and VPS copies must match (verify via --version).
"""
import re

FILTER_VERSION = "2026-07-15j"

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

# ---- scan()-side false-positive gate for ASSIGN_RE (2026-07-15i, operator-directed) ----
# ASSIGN_RE's name family (...TOKEN/...SECRET/...PASSWORD/...KEY) also matches everyday AUTH-CODE
# idioms: `autoRefreshToken: true`, test fixtures like `access_token: 'at-1'`, code references like
# `storageKey: platformStorageKey(url)` -- which made scan() structurally unable to review
# supabase-client code. The gate below narrows ONLY scan() (the egress block); redact() is unchanged
# (over-redacting a transcript is safe; over-blocking an egress packet breaks legitimate reviews).
#
# The clean model (Sol r1-r9 converged): a secret-family assignment is CLEAN only when it is
# unambiguously code carrying a benign value; anything that reads as a config/env/YAML dump line, or
# carries an opaque literal, BLOCKS.
#   * `=` form (env/config dumps -- the rule's original target)                         -> BLOCK.
#   * value is EXACTLY a [REDACTED:<label>] marker (scan-of-redact idempotency)          -> CLEAN.
#   * CODE-STRUCTURED line (a code-punctuation char ,;(){}[]=<>`|& at/after the value): the line is
#     lexed once (parity-aware string lexer; escaped quotes never open/close; unterminated literal
#     runs to EOL). BLOCK iff a string literal with >= 8 chars of non-marker content, or a >=16
#     opaque bareword that is NOT a pure-identifier key/call, appears at/after the value start.
#     Benign code values (bool/null, short literals, identifiers, calls) stay CLEAN.
#   * NON-code line (no code punctuation after the value = a YAML/env/prose plain line): the value is
#     the REST of the line (and a plain scalar may fold onto the immediately-following more-indented
#     line -- YAML forbids a blank line inside a plain scalar, so only the next line matters). CLEAN
#     only if that whole remaining value is a lone bool/null with no fold; otherwise BLOCK (fail
#     closed -- this is where env dumps, multiword passphrases, opaque tokens, colon-bearing scalars
#     and folds all live).
# RESIDUAL (documented, operator-accepted): a pure `[A-Za-z0-9_$]` >=16 secret used as a map KEY in a
# code-punctuation-bearing line (`{ Abcdefghijklmnop: v }`) is structurally identical to a legitimate
# long identifier key (`detectSessionInUrl:`) and cannot be told apart without semantics -- blocking
# it would reinstate the exact FP this gate removes. scan() is an egress TRIPWIRE, not a DLP; redact()
# still strips every KNOWN secret SHAPE. There is NO env/flag escape hatch.
_REDACTED_MARKER_RE = re.compile(r"^\[REDACTED:[a-z-]+\]$")
_BOOL_NULL_RE = re.compile(r"(?i)^(?:true|false|null|none|nil|undefined)$")
_YAML_BLOCK_RE = re.compile(r"^[|>][0-9+-]*$")  # YAML block scalar indicator |, >, |2, >+ ...
_BAREWORD_RE = re.compile(r"[A-Za-z0-9_+/@#$%^&*!-]{16,}")
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*$")           # pure code identifier (key/call name)
_CALL_OR_KEY_RE = re.compile(r"[ \t]*(?:\?\.)?\(|[ \t]*:")     # bareword followed by a call or a key ':'
_MIN_OPAQUE_LEN = 8
_CODE_PUNCT = set("()[]{};,=<>`|&")


def _line_block_max(line):
    """Max offset in a CODE line of an opaque-literal / opaque-bareword blocking signal, else -1.
    One parity-aware pass from LINE START, so quote pairing is position-independent (Sol r5)."""
    max_pos = -1
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
        # a pure-identifier bareword that begins a call `(` or a key `:` is code, not a literal
        # (platformStorageKey(url) / detectSessionInUrl:); an OPAQUE secret carries +/@#!%^&*- and
        # fails _IDENT_RE, so it still blocks (the pure-alnum-key residual is documented above).
        if bm.start() <= max_pos:
            continue
        word = line[bm.start():bm.end()]
        if _CALL_OR_KEY_RE.match(line, bm.end()) and _IDENT_RE.match(word):
            continue
        max_pos = bm.start()
    return max_pos


def _plain_line_leaks(text, line_start, line_end, value_start_abs):
    """NON-code (plain) line: the value is the rest of the line from value_start_abs. CLEAN only for
    a lone bool/null with no folded continuation; else BLOCK (env dumps / passphrases / opaque tokens
    / colon-bearing scalars / folds)."""
    rest = text[value_start_abs:line_end].strip()
    # a lone quoted value: unwrap one layer for the bool/marker checks
    if len(rest) >= 2 and rest[0] in "'\"" and rest[-1] == rest[0]:
        inner = rest[1:-1]
        if _REDACTED_MARKER_RE.match(inner):
            return False  # a lone marker literal (idempotency)
        if len(inner) >= _MIN_OPAQUE_LEN:
            return True   # opaque quoted literal on a plain line
        rest = inner
    if _REDACTED_MARKER_RE.match(rest):
        return False
    if not _BOOL_NULL_RE.match(rest):
        return True       # not a lone bool/null -> fail closed
    # lone bool/null: a YAML plain scalar folds ONLY onto the IMMEDIATELY following more-indented
    # non-blank line (a blank line terminates a plain scalar); such a fold carries the real value.
    if line_end < len(text) and text[line_end] == "\n":
        nxt = line_end + 1
        nend = text.find("\n", nxt)
        if nend == -1:
            nend = len(text)
        cline = text[nxt:nend]
        if cline.strip():
            key_line = text[line_start:line_end]
            key_indent = len(key_line) - len(key_line.lstrip())
            cindent = len(cline) - len(cline.lstrip())
            cstrip = cline.strip()
            is_nested_key = ":" in cstrip and _IDENT_RE.match(cstrip.split(":", 1)[0])
            if cindent > key_indent and not is_nested_key:
                return True  # folded scalar continuation (not a nested mapping) -> BLOCK
    return False


def _match_leaks(m, text, line_start, line_end, block_max, last_punct):
    """Whole verdict for one ASSIGN match. True = block. block_max/last_punct are precomputed once
    per physical line (O(1) per match -> linear over a many-match line, Sol r2/r4)."""
    val = (m.group("val") or "").rstrip(",;")
    if _REDACTED_MARKER_RE.match(val):
        return False  # value is EXACTLY our own marker -> scan(redact(x)) idempotency (wins over
        #               the `=` rule: a redacted env assignment must not re-trip)
    if "=" in m.group(1):
        return True  # env-style assignment: full strictness
    if _YAML_BLOCK_RE.match(val):
        return True  # YAML block scalar (|, >): the real payload lives on the following lines
    if m.group("q") and len(val) >= _MIN_OPAQUE_LEN:
        # a QUOTED opaque literal directly assigned to a secret-family name -> block at the match
        # level (quote pairing is genuinely ambiguous, `'a_key:'x y'` reads both ways; Sol r5).
        return True
    value_start_abs = m.start("q") if m.group("q") else m.start("val")
    vstart = value_start_abs - line_start
    if last_punct >= vstart:
        # code line: the marker itself is benign (idempotency); block_max flags a quoted opaque
        # literal / opaque bareword at/after the value; a trailing opaque payload still trips it.
        return block_max >= vstart
    return _plain_line_leaks(text, line_start, line_end, value_start_abs)  # plain/config/YAML line


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
    # One verdict per ASSIGN match; incremental line-bounds tracking keeps a many-match line linear.
    line_start = 0
    search_from = 0
    cached_line_start = -1
    cached_line_end = -1
    cached_block_max = -1
    cached_last_punct = -1
    for m in ASSIGN_RE.finditer(text):
        nl = text.rfind("\n", search_from, m.start())
        if nl != -1:
            line_start = nl + 1
        search_from = m.start()
        if line_start != cached_line_start:
            cached_line_start = line_start
            cached_line_end = text.find("\n", line_start)
            if cached_line_end == -1:
                cached_line_end = len(text)
            line = text[line_start:cached_line_end]
            cached_block_max = _line_block_max(line)
            cached_last_punct = max((i for i, c in enumerate(line) if c in _CODE_PUNCT), default=-1)
        if _match_leaks(m, text, line_start, cached_line_end, cached_block_max, cached_last_punct):
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
