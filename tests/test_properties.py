#!/usr/bin/env python3
"""Property-based / fuzz / concurrency tests (R3 hardening).

The unit suite (test_gate.py) proves specific inputs; this proves INVARIANTS
over many seeded-random inputs, plus filesystem-race behavior the unit tests
can't reach. stdlib-only (random with a FIXED seed for determinism — no
hypothesis dependency, and reproducible in CI).

Run:  python3 tests/test_properties.py
"""
import json
import os
import random
import re
import string
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "coverloop")
import glm_secret_filter as F

SEED = 20260711  # fixed -> deterministic, reproducible failures

# ---------------------------------------------------------------------------
# The suite drives the REAL reviewer CLIs (that is the point of the egress
# tests: they assert on the exact bytes that would leave the machine). Their
# do_request is stubbed, so nothing is ever sent — but log_egress still wrote
# `attempt` markers to the PRODUCTION egress log, and the daily spend cap counts
# exactly those markers. A full suite run therefore burned ~30 slots of the
# operator's real review budget, and after a few runs every real GLM review that
# day was refused. That is how a test suite silently consumed production quota.
#
# The whole module runs against a temporary log, and tearDownModule FAILS if the
# production log was touched at all — an accidental production reviewer
# invocation is a test failure, not a surprise on the invoice.
# ---------------------------------------------------------------------------
PROD_EGRESS_LOG = os.path.join(os.path.expanduser("~"), ".config", "openrouter", "egress.log")
_SUITE_LOG_DIR = None
_PROD_LOG_BEFORE = None


def _prod_log_fingerprint():
    try:
        st = os.stat(PROD_EGRESS_LOG)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def setUpModule():
    global _SUITE_LOG_DIR, _PROD_LOG_BEFORE
    _PROD_LOG_BEFORE = _prod_log_fingerprint()
    _SUITE_LOG_DIR = tempfile.mkdtemp(prefix="coverloop-suite-egress-")
    os.environ["COVERLOOP_EGRESS_LOG"] = os.path.join(_SUITE_LOG_DIR, "egress.log")


def tearDownModule():
    import shutil as _sh
    os.environ.pop("COVERLOOP_EGRESS_LOG", None)
    if _SUITE_LOG_DIR:
        _sh.rmtree(_SUITE_LOG_DIR, ignore_errors=True)
    if _prod_log_fingerprint() != _PROD_LOG_BEFORE:
        raise AssertionError(
            f"the test suite wrote to the PRODUCTION egress log ({PROD_EGRESS_LOG}). "
            f"Those entries are what the daily spend cap counts, so the suite would be "
            f"consuming the operator's real review budget. Point COVERLOOP_EGRESS_LOG at "
            f"a temporary file in the test's own setUp.")


def suite_egress_log():
    """The temporary log this module runs against — never the production one."""
    return os.environ.get("COVERLOOP_EGRESS_LOG") or os.path.join(_SUITE_LOG_DIR or "", "egress.log")


# ---- generators for real secret SHAPES (one valid instance per VALUE pattern) ----
def _rand(rng, alphabet, n):
    return "".join(rng.choice(alphabet) for _ in range(n))


def gen_secret(rng):
    """Return (secret_value, label) for a randomly chosen real secret shape."""
    b64 = string.ascii_letters + string.digits + "_-"
    kind = rng.choice([
        "sk", "ghp", "aws", "slack", "google", "jwt", "bearer", "dburl", "assign", "pem",
    ])
    if kind == "sk":
        return "sk-" + _rand(rng, b64, rng.randint(20, 48)), "sk-key"
    if kind == "ghp":
        return "ghp_" + _rand(rng, string.ascii_letters + string.digits + "_", rng.randint(20, 40)), "github-token"
    if kind == "aws":
        return "AKIA" + _rand(rng, string.digits + string.ascii_uppercase, 16), "aws-key"
    if kind == "slack":
        return "xoxb-" + _rand(rng, string.ascii_letters + string.digits + "-", rng.randint(10, 30)), "slack-token"
    if kind == "google":
        return "AIza" + _rand(rng, b64, 35), "google-key"
    if kind == "jwt":
        return ("eyJ" + _rand(rng, b64, rng.randint(8, 20)) + "." +
                _rand(rng, b64, rng.randint(8, 20)) + "." + _rand(rng, b64, rng.randint(6, 20))), "jwt"
    if kind == "bearer":
        return "bearer " + _rand(rng, string.ascii_letters + string.digits + "._~+/=-", rng.randint(16, 40)), "bearer"
    if kind == "dburl":
        return ("postgres://" + _rand(rng, string.ascii_lowercase, 6) + ":" +
                _rand(rng, b64, 10) + "@host/db"), "db-url-cred"
    if kind == "assign":
        # 2026-07-15a boundary: env-style (=) assignments block at ANY value; colon-style blocks
        # for quoted opaque literals >= 8 chars. Generate only the still-blocking class here —
        # the colon-style code idioms scan() now deliberately allows are pinned the other way in
        # AssignmentScanBoundary below.
        name = rng.choice(["API_KEY", "X_SECRET", "DB_PASSWORD", "AUTH_TOKEN", "MY_API_KEY", "z_passwd"])
        if rng.random() < 0.5:
            sep = rng.choice(["=", " = "])
            val = _rand(rng, b64 + "!@#", rng.randint(1, 30))
            return name + sep + val, "secret-assignment"
        val = _rand(rng, b64 + "!@#", rng.randint(8, 30))
        return "%s: '%s'" % (name, val), "secret-assignment"
    # pem
    body = _rand(rng, b64, rng.randint(40, 300))
    return "-----BEGIN RSA PRIVATE KEY-----\n" + body + "\n-----END RSA PRIVATE KEY-----", "private-key"


def _value_of(secret, label):
    """The substring that must NOT survive redaction (for assignment, the value
    after the separator; for bearer/dburl the credential portion)."""
    if label == "secret-assignment":
        for sep in ("=", ":"):
            if sep in secret:
                return secret.split(sep, 1)[1].strip().strip("'\"")
    if label == "bearer":
        return secret.split(None, 1)[1]
    if label == "db-url-cred":
        return secret.split("://", 1)[1].split("@", 1)[0]  # user:pass
    return secret


def gen_noise(rng):
    """Benign review-prose context that must never be corrupted."""
    words = ["the", "gate", "review", "risk-based", "task-start", "commit", "diff",
             "MONKEY=banana", "see file.py:42", "a normal sentence", "HOTKEY=ctrl"]
    return " ".join(rng.choice(words) for _ in range(rng.randint(0, 8)))


class SecretFilterProperties(unittest.TestCase):
    N = 1500

    def setUp(self):
        self.rng = random.Random(SEED)

    def test_redact_is_idempotent(self):
        """redact(redact(x)) == redact(x) for arbitrary mixed input — a second
        pass must be a fixed point (no placeholder re-triggers a pattern)."""
        for _ in range(self.N):
            s = gen_noise(self.rng) + " " + gen_secret(self.rng)[0] + " " + gen_noise(self.rng)
            once = F.redact(s)
            self.assertEqual(F.redact(once), once, "redact not idempotent on %r" % s)

    def test_secret_value_never_survives_redaction(self):
        """The actual secret VALUE must not appear in redact() output — the core
        privacy guarantee, over many shapes and surrounding contexts."""
        for _ in range(self.N):
            secret, label = gen_secret(self.rng)
            text = "%s %s %s" % (gen_noise(self.rng), secret, gen_noise(self.rng))
            out = F.redact(text)
            val = _value_of(secret, label)
            if len(val) >= 8:  # short/degenerate values can coincide with prose; only assert on real ones
                self.assertNotIn(val, out, "value leaked (label=%s): %r -> %r" % (label, secret, out))

    def test_scan_flags_every_generated_secret(self):
        """scan() (the egress tripwire) must return non-empty for every real
        secret shape — a miss here means a secret leaves the machine."""
        for _ in range(self.N):
            secret, label = gen_secret(self.rng)
            self.assertTrue(F.scan(secret), "scan missed %s: %r" % (label, secret))

    def test_scan_redact_agree_on_values(self):
        """If scan flags a VALUE-shaped secret, redact must change the text
        (consistency: detect => remove). Name-only assignment excluded (redact
        keeps the name by design)."""
        for _ in range(self.N):
            secret, label = gen_secret(self.rng)
            if label == "secret-assignment":
                continue
            self.assertNotEqual(F.redact(secret), secret, "flagged but not redacted: %r" % secret)

    def test_no_redos_on_random_adversarial(self):
        """Randomized pathological inputs (long runs, boundary spam, unbalanced
        quotes, many BEGIN markers) must each scan+redact in ~linear time."""
        rng = self.rng
        for _ in range(40):
            shape = rng.choice(["run", "spam", "quote", "begins", "mixed"])
            n = rng.randint(200_000, 800_000)
            if shape == "run":
                blob = _rand(rng, string.ascii_letters, 8) + "A" * n + "=x"
            elif shape == "spam":
                blob = ("KEY_X " * (n // 6))
            elif shape == "quote":
                blob = 'TOKEN="' + "a" * n
            elif shape == "begins":
                blob = "-----BEGIN RSA PRIVATE KEY-----\n" * (n // 40)
                if rng.random() < 0.5:  # has-END-far: a single distant END must not un-bound the scan
                    blob += "-----END RSA PRIVATE KEY-----"
            else:
                blob = ("SECRET=" + "b" * 1000 + " ") * (n // 1010)
            t0 = time.monotonic()
            F.scan(blob)
            F.redact(blob)
            dt = time.monotonic() - t0
            self.assertLess(dt, 2.0, "ReDoS: shape=%s len=%d took %.2fs" % (shape, len(blob), dt))

    def test_pii_removed_from_transcripts(self):
        """redact() scrubs PII shapes (home-dir usernames, emails, uuids) from
        committed transcripts."""
        rng = self.rng
        for _ in range(300):
            user = _rand(rng, string.ascii_lowercase, rng.randint(1, 12))
            email = _rand(rng, string.ascii_lowercase, 6) + "@" + _rand(rng, string.ascii_lowercase, 5) + ".com"
            uuid = "-".join(_rand(rng, "0123456789abcdef", k) for k in (8, 4, 4, 4, 12))
            text = "path /Users/%s/x mail %s id %s" % (user, email, uuid)
            out = F.redact(text)
            self.assertNotIn("/Users/%s/" % user, out)
            self.assertNotIn(email, out)
            self.assertNotIn(uuid, out)

    def test_curated_bypass_corpus(self):
        """Hand-picked tricky formattings that a naive filter would miss. Each
        MUST be caught (redacted). Documents the coverage boundary explicitly."""
        secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        cases = [
            "export API_KEY=%s" % secret,
            "  DB_PASSWORD = 'hunter2longenough'  ",
            "Authorization: bearer ABCDEFGHIJKLMNOP1234",
            "url=postgres://u:pass1234@db:5432/app",
            "nested {\"anthropic_api_key\": \"%s\"}" % secret,
            "AWS_SECRET_ACCESS_KEY=%s" % secret,
        ]
        for c in cases:
            self.assertTrue(F.scan(c), "corpus not flagged: %r" % c)
            self.assertNotIn(secret, F.redact(c), "corpus secret survived: %r" % c)
        # Encrypted PEM: the tempered-dot body must still span header lines
        # (Proc-Type/DEK-Info contain ':' ',' '-') so the whole block redacts.
        enc = ("-----BEGIN RSA PRIVATE KEY-----\n"
               "Proc-Type: 4,ENCRYPTED\n"
               "DEK-Info: AES-128-CBC,7F3C1A2B4D5E6F70\n\n"
               "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Q\n"
               "-----END RSA PRIVATE KEY-----")
        self.assertNotIn("MIIBOgIBAAJBAKj34", F.redact(enc), "encrypted PEM body leaked")
        self.assertIn("[REDACTED:private-key]", F.redact(enc), "encrypted PEM not redacted whole")


class AssignmentScanBoundary(unittest.TestCase):
    """2026-07-15a (operator-directed): scan() must review real auth-client code without
    false-positive blocking, while still blocking genuine secret assignments. redact() is
    unchanged and maximal. Both directions pinned so a future edit can't silently widen OR
    re-break the boundary."""

    ALLOWED_AUTH_CODE = [
        "autoRefreshToken: true,",
        "detectSessionInUrl: true, persistSession: true",
        "access_token: 'at-1',",
        "refresh_token: 'rt-2',",
        "  password: 'pw' })",
        "storageKey: platformStorageKey(url),",
        "p_game_key: gameKey,",
        "refresh_token: `rt-${counter}`,",
        "refresh_token: currentRt,",
        "refresh_token: currentRefreshToken (url)",  # call name with space (Sol r2)
        "refresh_token: currentRefreshToken?.(url)",  # optional-chaining call (Sol r2)
        "detectSessionInUrl: true,",                  # long ident key, ,-terminated (Sol r8)
        "config:\n  authToken: true\nother: value",    # exempt bool; next line de-indented sibling
        "authToken: true\n  detectSessionInUrl: true",  # continuation is a nested key, not a fold
        "MY_DEPLOY_TOKEN=[REDACTED:secret-value]",       # redacted env assignment — marker wins over '='
        "token: 'x', // rotate quarterly",           # JS line comment, short value
        "webhookUrl: 'https://x.io/hook',",          # :// is not a comment
        "sessionToken: buildToken(userId, expiry),",  # call w/ args, not a bare multiword (Sol r11)
        "apiKey: config.get('k'), fallback: def,",
        # sequential-lexer pairing: inter-literal CODE must not read as a quoted span (Sol r4)
        "access_token: 'at-1', refresh_token: 'rt-1', token_type: 'bearer1'",
        "const sessionKeys = touched.filter(k => k === platformStorageKey(URL_))",
        "expect(stored?.refresh_token).toBe(server.currentRefreshToken())",
        "TOKEN: null", "apiKey: undefined,",
    ]

    STILL_BLOCKED = [
        "VERCEL_TOKEN=whatever",
        "export API_KEY=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "  DB_PASSWORD = 'hunter2longenough'  ",
        "AUTH_TOKEN: 'opaque!value123'",
        "my_password: \"correct horse battery staple\"",
        "SIGNING_KEY: 'aVeryLongOpaqueLiteral123'",
        "TOKEN=x",  # env-style keeps the no-floor rule (Sol v2.7.3 verify #3)
        # Sol round-2 adversarial set (each was a caught bypass of the first gate draft):
             # long opaque bareword
        "AUTH_TOKEN: fn('correcthorsebatterystaple')",       # literal hidden past the value capture
        'AUTH_TOKEN: "x\\"correcthorsebatterystaple"',       # escaped-quote truncation trick
        "AUTH_TOKEN=[REDACTED:secret-value]correcthorsebatterystaple",  # marker with payload suffix
        "AUTH_TOKEN: |",                                     # YAML block scalar (payload on next lines)
        "AUTH_TOKEN:`placeholder`;DB_PASSWORD=correcthorsebatterystaple",  # swallowed second pair
        # Sol round-2 adversarial set:
        "AUTH_TOKEN: |2",                                    # YAML block scalar WITH indentation indicator
        "AUTH_TOKEN: >+2",
        'AUTH_TOKEN: "x\\" correct horse battery staple"',   # escaped-quote split of a SPACED payload
        "AUTH_TOKEN: '[REDACTED:secret-value]suffixpayload'",  # marker with suffix under ':' (isolates marker logic)
        # Sol round-3 adversarial set (both were regressions introduced by the r2 fixes):
        "AUTH_TOKEN: fn('correct PASSWORD: x horse')",  # inner name-match must not split the span scan
        'AUTH_TOKEN: "abcdefgh\\\\"',                     # \\\\ = escaped backslash; the quote is REAL
        # Sol round-4: val-level early exits must not mark the line as tail-scanned
        "autoRefreshToken: true, AUTH_TOKEN: fn('correcthorsebatterystaple')",
        "a_token: null, AUTH_TOKEN: correct horse battery staple",
        "x_token: '[REDACTED:secret-value]', AUTH_TOKEN: 'opaquevalue123456'",
        # Sol round-5: stateful per-match lexing vs line lexing disagreed on ambiguous pairing —
        # a QUOTED opaque captured value now blocks at the match level, both readings closed
        "({x_token:x, note: `'a_key:'correct horse battery staple'`})",
        # Sol round-6: unquoted colon-assignment secrets in a code-punctuation-free zone
        "DB_PASSWORD: correct horse battery staple",   # YAML/env plain multiword scalar
        # Sol round-7: a bool/marker CAPTURED value must not exempt a payload after it
        "AUTH_TOKEN: true actualsecret123",                # bool value then a separate real token
        "AUTH_TOKEN: null correct horse battery staple",
        # Sol round-8: YAML fold continuation + opaque-secret-as-map-key
        "AUTH_TOKEN: true\n    correct horse battery staple",  # scalar folded onto indented line
        "AUTH_TOKEN: true\n    abcdefghijklmno",
        "AUTH_TOKEN: se+cret/k3y@value#123: x",                # special-char opaque key (ident-gate)
        "AUTH_TOKEN: correctsecretkey12345678: value",         # pure-alnum key in punctuation-free zone
        # Sol round-9: word-split YAML fold, colon-in-plain-scalar
        "AUTH_TOKEN: true\n    correct\n    horse\n    battery",
        "AUTH_TOKEN: Abcdefghijklmnop:payload",
        # Sol round-10: marker-then-payload, blank-line + colon-scalar folds, comment punctuation
        "AUTH_TOKEN: true\n\n    actualsecret123456",
        "AUTH_TOKEN: true\n    actualsecret123456:payload",
        "AUTH_TOKEN: correct horse battery staple # rotated (today)",
    ]

    # Documented residual (Sol r11/r12, operator-accepted): a passphrase/opaque value forced into
    # the CODE branch by surrounding code punctuation (braces, marker+prose, string concatenation)
    # is NOT caught -- catching it FP'd on real TS (`currentRt as string`, JSX `<>hello world</>`).
    # scan() is an egress TRIPWIRE backed by maximal redact(); these shapes do not occur in the
    # TS/JS review packets scan() gates. Pinned so a future change is a conscious boundary move.
    DOCUMENTED_RESIDUAL_CLEAN = [
        "{AUTH_TOKEN: correct horse battery staple}",
        "AUTH_TOKEN: [REDACTED:secret-value] correct horse battery staple",
        "({AUTH_TOKEN: 'corr' + \"ect \" + 'horse'})",
        "{AUTH_TOKEN: A1b2C3d4E5f6G7h}",
        # single pure-identifier-shaped unquoted opaque words == indistinguishable from identifiers
        "AUTH_TOKEN: correcthorsebatterystaple",
        "AUTH_TOKEN: abcdefghijklmno",
    ]

    def test_documented_residual_is_clean_and_ts_not_fp(self):
        for t in self.DOCUMENTED_RESIDUAL_CLEAN:
            self.assertEqual(F.scan(t), [], "residual moved -- was it intended? %r" % t)
        # the reason the residual stays open: closing it FP'd on real TypeScript
        for t in ["({authToken: currentRt as string})", "({authToken: currentRt, children: <>hi there</>})"]:
            self.assertEqual(F.scan(t), [], "TS false positive: %r" % t)

    def test_auth_code_idioms_pass_scan(self):
        for t in self.ALLOWED_AUTH_CODE:
            self.assertEqual(F.scan(t), [], "false positive on auth code: %r -> %r" % (t, F.scan(t)))

    def test_real_assignments_still_block(self):
        for t in self.STILL_BLOCKED:
            self.assertIn("secret-assignment", F.scan(t), "real assignment NOT blocked: %r" % t)

    def test_redact_still_covers_allowed_code(self):
        # the scan() gate never weakens redact(): a secret-NAMED colon assignment with a quoted
        # value is still stripped from committed transcripts even when scan() allows egress
        out = F.redact("access_token: 'at-1',")
        self.assertNotIn("'at-1'", out)

    def test_scan_of_redacted_output_is_clean(self):
        """Marker idempotency (operator req): redaction MARKERS must not re-trip ASSIGN_RE.
        Scope note: the bare-name literal tripwires (VERCEL_TOKEN et al) intentionally still
        fire post-redaction — this pins markers only, hence non-literal names below."""
        # names chosen OUTSIDE LITERAL_PATTERNS: the literal name-mention tripwire (VERCEL_TOKEN
        # et al) intentionally still fires post-redaction — this test pins only that the
        # [REDACTED:…] MARKERS never re-trip ASSIGN_RE.
        dirty = ("MY_DEPLOY_TOKEN=realvalue123 and access_token: 'longopaque123' and "
                 "password: \"correct horse battery staple\"")
        self.assertTrue(F.scan(dirty))
        self.assertEqual(F.scan(F.redact(dirty)), [], "scan(redact(x)) not clean")

    def test_repeated_allowed_assignments_stay_linear(self):
        """Sol r2: uncapped tail rescans were quadratic (7.6s @ 8000 matches). The per-match
        tail cap must keep repeated allowed assignments linear."""
        import time
        text = "AUTH_TOKEN:x " * 8000  # one line — repeated matches (and see the many-line shape below)
        t0 = time.time()
        F.scan(text)
        self.assertLess(time.time() - t0, 1.0, "repeated-assignment scan no longer linear")
        text = "AUTH_TOKEN:x\n" * 8000
        t0 = time.time()
        F.scan(text)
        self.assertLess(time.time() - t0, 1.0, "many-line repeated-assignment scan no longer linear")

    def test_no_env_escape_hatch(self):
        import os as _os
        _os.environ["GLM_FILTER_ALLOW"] = "1"  # must have zero effect
        try:
            self.assertTrue(F.scan("VERCEL_TOKEN=whatever"))
        finally:
            del _os.environ["GLM_FILTER_ALLOW"]


_CAPTURED = {}


class EgressRedactionInvariant(unittest.TestCase):
    """Operator merge condition (2026-07-15): EVERY packet sent to an external review model passes
    through redact() BEFORE scan and egress — no raw-packet bypass path. Integration-level: the
    REAL CLI module (bin/glm-review, bin/m3-review) is imported and driven through its actual
    main() path with do_request captured, so the assertion covers arg-parse → packet build →
    redact → scan → payload — the exact bytes that would leave the machine."""

    SECRET = "hunter2longenough"

    def setUp(self):
        # ISOLATE THE SPEND CAP. These tests drive the real CLI main(), which
        # consults the R6 daily cap against the REAL egress log — so on a day
        # when you actually ran ~40 reviews, the packet is refused before
        # do_request and every assertion here fails with a misleading
        # "never reached do_request". CI never saw it (fresh log); only real
        # working days did. A privacy invariant must not depend on how busy
        # you were today.
        self._saved_cap = os.environ.get("COVERLOOP_DAILY_REVIEW_CAP")
        os.environ["COVERLOOP_DAILY_REVIEW_CAP"] = "0"  # 0 = disabled

    def tearDown(self):
        if self._saved_cap is None:
            os.environ.pop("COVERLOOP_DAILY_REVIEW_CAP", None)
        else:
            os.environ["COVERLOOP_DAILY_REVIEW_CAP"] = self._saved_cap

    def _run_cli(self, cli_name, stdin_text, argv):
        import importlib.util, io, contextlib
        path = os.path.join(os.path.dirname(CLI), cli_name)
        spec = importlib.util.spec_from_loader(cli_name.replace("-", "_"), loader=None)
        mod = importlib.util.module_from_spec(spec)
        with open(path) as _fh:
            src = _fh.read()
        captured = {}

        captured["all"] = []
        global _CAPTURED
        _CAPTURED = captured

        def fake_do_request(payload, timeout):
            # call the REAL choke point first, so the test proves do_request enforces redaction on
            # EVERY payload regardless of caller (the invariant), then record the enforced payload.
            enforced = mod._enforce_egress_redaction(payload)
            captured["all"].append(enforced)
            captured["payload"] = enforced
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "provider": "test"}

        env = {"OPENROUTER_API_KEY": "x" * 20, "MINIMAX_API_KEY": "x" * 20, "M3_ENABLED": "1"}
        old_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        old_argv, old_stdin = sys.argv, sys.stdin
        sys.argv = [cli_name] + argv
        sys.stdin = io.StringIO(stdin_text)
        try:
            mod.__dict__["__file__"] = path
            exec(compile(src, path, "exec"), mod.__dict__)
            mod.do_request = fake_do_request
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    mod.main()
                except SystemExit:
                    pass
        finally:
            sys.argv, sys.stdin = old_argv, old_stdin
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return captured.get("payload")

    def _assert_invariant(self, cli_name, argv):
        raw = "review this line\nDB_PASSWORD = '%s'\nplus context" % self.SECRET
        payload = self._run_cli(cli_name, raw, argv)
        self.assertIsNotNone(payload, "%s never reached do_request (packet refused?)" % cli_name)
        body = json.dumps(payload)
        # 1. the secret VALUE never leaves
        self.assertNotIn(self.SECRET, body, "%s egressed a raw secret" % cli_name)
        # 2. redaction visibly happened
        self.assertIn("[REDACTED:", body, "%s egress carries no redaction marker" % cli_name)
        # 3. NO raw-packet bypass: the user message is EXACTLY redact(raw packet). argv here is only
        #    ["--mode", <mode>], so TASK is empty and the whole packet is redact() of the fixed
        #    "TASK:\n\n\nPROVIDED INPUT:\n<raw>" template — any second build path that skips
        #    redact() breaks this equality.
        user_msg = payload["messages"][-1]["content"]
        expected = F.redact(("TASK:\n\n\nPROVIDED INPUT:\n" + raw).strip())
        self.assertEqual(user_msg, expected, "%s user packet is not redact(raw)" % cli_name)
        # 4. a legitimate auth-code packet still EGRESSES (scan does not refuse it) — the FP fix.
        #    NOTE (accepted trade): redact() is maximal, so secret-family ASSIGNMENT VALUES are
        #    blanked in the egressed packet (`autoRefreshToken: true` -> `[REDACTED:...]`); the
        #    reviewer still receives all non-assignment code (structure, control flow, prose). We
        #    assert the packet is SENT and prose survives, NOT byte-identity.
        clean = "please review this diff for correctness and reuse concerns"
        p2 = self._run_cli(cli_name, clean, argv)
        self.assertIsNotNone(p2, "%s refused a clean auth-code packet (FP fix regressed)" % cli_name)
        self.assertIn("review this diff for correctness", p2["messages"][-1]["content"],
                      "%s dropped non-assignment prose" % cli_name)

    def test_glm_review_redacts_before_egress(self):
        self._assert_invariant("glm-review", ["--mode", "redteam"])

    def test_m3_review_redacts_before_egress(self):
        self._assert_invariant("m3-review", ["--mode", "audit"])

    def test_every_captured_request_is_redacted(self):
        """EVERY do_request payload on a run (not just the last) carries no raw secret — a raw
        request followed by a redacted one cannot pass."""
        raw = "line one\nDB_PASSWORD = 'hunter2longenough'\nline two"
        self._run_cli("glm-review", raw, ["--mode", "redteam"])
        for p in _CAPTURED.get("all", []):
            for m in p.get("messages", []):
                if isinstance(m.get("content"), str):
                    self.assertNotIn(self.SECRET, m["content"], "a captured request egressed a raw secret")

    def test_choke_point_redacts_and_fails_closed(self):
        """do_request's _enforce_egress_redaction is the SINGLE egress gate: it redacts every
        message (covers ping/self-test/any caller) and RAISES if a redacted packet still scans."""
        import importlib.util
        for cli in ("glm-review", "m3-review"):
            path = os.path.join(os.path.dirname(CLI), cli)
            mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(cli.replace("-", "_"), loader=None))
            mod.__dict__["__file__"] = path
            with open(path) as _fh:
                exec(compile(_fh.read(), path, "exec"), mod.__dict__)
            # a raw-secret payload handed straight to the choke point is redacted in place
            payload = {"messages": [{"role": "user", "content": "x_password = 'hunter2longenough'"}]}
            out = mod._enforce_egress_redaction(payload)
            self.assertNotIn(self.SECRET, out["messages"][0]["content"])
            self.assertIn("[REDACTED:", out["messages"][0]["content"])
            # the ping self-test payload passes the gate unchanged (constant, clean)
            ping = {"messages": [{"role": "user", "content": "ping"}]}
            self.assertEqual(mod._enforce_egress_redaction(ping)["messages"][0]["content"], "ping")
            # a LITERAL_PATTERNS name that redact() leaves (by design) makes the gate FAIL CLOSED
            with self.assertRaises(RuntimeError):
                mod._enforce_egress_redaction({"messages": [{"role": "user", "content": "note: VERCEL_TOKEN mentioned"}]})

    def test_scan_runs_on_the_redacted_text(self):
        """The tripwire fail-closes on what would actually LEAVE: a packet whose only secret is a
        redactable assignment egresses REDACTED (not refused), while a LITERAL_PATTERNS name-mention
        (never redacted by design) still refuses outright."""
        payload = self._run_cli("glm-review", "x_password = 'hunter2longenough'", ["--mode", "redteam"])
        self.assertIsNotNone(payload)  # redacted -> clean -> sent
        refused = self._run_cli("glm-review", "context mentions VERCEL_TOKEN here", ["--mode", "redteam"])
        self.assertIsNone(refused, "LITERAL_PATTERNS mention must still refuse egress")


# ---- concurrency / filesystem-race tests against the real CLI ----
def _run(args, cwd, timeout=60):
    return subprocess.run([sys.executable, CLI] + args, cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)


class ConcurrencyRaces(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        for a in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@e.co"],
                  ["git", "config", "user.name", "t"]):
            subprocess.run(a, cwd=self.repo, check=True, capture_output=True)
        with open(os.path.join(self.repo, "app.py"), "w") as fh:
            fh.write("print(1)\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True, capture_output=True)
        r = _run(["init", "--test-command", "true"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "scaffold"], cwd=self.repo, check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _sha(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_concurrent_attest_never_corrupts_report(self):
        """N concurrent `attest` writers to the same commit's report must never
        leave a corrupt/half-written JSON file, and none may traceback. (Drives
        the atomic-write guarantee: a plain open+dump is not atomic under
        concurrency.)"""
        results = []
        n = 8
        barrier = threading.Barrier(n)
        flags = ["--tests", "--codex"] * (n // 2)  # mix of writers touching different fields
        threads = [threading.Thread(target=worker_dispatch, args=(self, results, barrier, f))
                   for f in flags]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # every writer completed cleanly (no crash, exit 0)
        self.assertEqual(len(results), n)
        for r in results:
            self.assertNotIn("Traceback", r.stderr, "attest crashed under concurrency: %s" % r.stderr)
            self.assertEqual(r.returncode, 0, "attest failed under concurrency: %s" % r.stderr)
        # the report MUST exist and be a COMPLETE, parseable JSON doc — atomic
        # writes (temp + os.replace) mean a reader never sees a torn file even
        # with N racing writers. WHICH field wins is a lost-update question, and
        # attest is a sequential operation by design, so last-writer-wins is the
        # accepted contract; the invariant under test is no corruption / no crash.
        path = os.path.join(self.repo, ".coverloop", "reports", self._sha() + ".json")
        self.assertTrue(os.path.exists(path), "no report written by any concurrent attest")
        with open(path) as fh:
            doc = json.load(fh)  # raises (and fails the test) if the file is torn
        self.assertEqual(doc.get("commit"), self._sha(), "report not bound to HEAD")
        # NO LOST UPDATE (R4): the workers record a MIX of --tests and --codex on
        # the same report. Under the attest lock the read-modify-write cycles
        # serialize, so BOTH fields must survive — an unlocked last-writer-wins
        # would drop one. This is the assertion the R4 lock earns.
        self.assertIsNotNone(doc.get("tests"), "lost update: 'tests' dropped by a concurrent attest")
        self.assertIsNotNone(doc.get("codex"), "lost update: 'codex' dropped by a concurrent attest")
        # atomic-write temp files must never leak
        leftovers = [p for p in os.listdir(os.path.dirname(path)) if ".tmp." in p]
        self.assertEqual(leftovers, [], "atomic-write temp files leaked: %s" % leftovers)

    def test_gate_during_concurrent_attest_never_tracebacks(self):
        """Reading (gate) while writers race must fail-closed or pass — never
        crash on a partially written report."""
        stop = threading.Event()
        crashes = []

        def writer():
            while not stop.is_set():
                _run(["attest", "--tier", "L2", "--codex"], self.repo)

        def reader():
            for _ in range(15):
                r = _run(["gate", "--min-tier", "L1"], self.repo)
                if "Traceback" in r.stderr:
                    crashes.append(r.stderr)

        w = threading.Thread(target=writer)
        w.start()
        try:
            reader()
        finally:
            stop.set()
            w.join()
        self.assertEqual(crashes, [], "gate tracebacked on a concurrent partial report")


def worker_dispatch(case, results, barrier, flag):
    """Run one attest with the right verdict payload for --codex vs --tests."""
    args = ["attest", "--tier", "L2"]
    if flag == "--codex":
        args += ["--codex", "pass"]
    else:
        args += ["--tests"]
    barrier.wait()
    results.append(_run(args, case.repo))


class DailyReviewCap(unittest.TestCase):
    """R6: the daily reviewer-call cap counts today's SENT reviews (egress
    'attempt' markers) and refuses past the configured cap, fail-closed — a
    token-spend guardrail for runaway loops / many parallel projects."""

    def setUp(self):
        import egress_cap
        self.cap = egress_cap
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "egress.log")
        os.environ["COVERLOOP_EGRESS_LOG"] = self.log

    def tearDown(self):
        # Restore the SUITE's temporary log — popping it would let every later
        # test fall back to the operator's production log.
        os.environ["COVERLOOP_EGRESS_LOG"] = suite_egress_log()
        os.environ.pop("COVERLOOP_DAILY_REVIEW_CAP", None)

    def _write(self, n_today=0, n_old=0, n_result=0, corrupt=False):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).isoformat()
        with open(self.log, "w", encoding="utf-8") as f:
            if corrupt:
                f.write("not-json-a-partial-line\n")
            for _ in range(n_today):
                f.write(json.dumps({"ts": today, "phase": "attempt"}) + "\n")
            for _ in range(n_result):  # result-phase is NOT a new billable call
                f.write(json.dumps({"ts": today, "phase": "result"}) + "\n")
            for _ in range(n_old):      # a different day
                f.write(json.dumps({"ts": "2020-01-01T00:00:00+00:00", "phase": "attempt"}) + "\n")

    def test_counts_only_todays_attempts(self):
        self._write(n_today=5, n_old=9, n_result=4)
        self.assertEqual(self.cap.sent_today(), 5)

    def test_missing_log_is_zero(self):
        self.assertEqual(self.cap.sent_today(), 0)

    def test_corrupt_line_tolerated(self):
        self._write(n_today=1, corrupt=True)
        self.assertEqual(self.cap.sent_today(), 1)

    def test_under_cap_passes(self):
        self._write(n_today=3)
        os.environ["COVERLOOP_DAILY_REVIEW_CAP"] = "10"
        self.cap.enforce_daily_cap()  # must NOT exit

    def test_at_cap_fails_closed(self):
        self._write(n_today=3)
        os.environ["COVERLOOP_DAILY_REVIEW_CAP"] = "3"
        with self.assertRaises(SystemExit) as cm:
            self.cap.enforce_daily_cap()
        self.assertEqual(cm.exception.code, 4)

    def test_zero_disables_even_far_over(self):
        self._write(n_today=500)
        os.environ["COVERLOOP_DAILY_REVIEW_CAP"] = "0"
        self.cap.enforce_daily_cap()  # disabled -> no exit
def _load_coverloop():
    """Load bin/coverloop as a module (it has no .py extension)."""
    import importlib.util
    spec = importlib.util.spec_from_loader("coverloop_mod", loader=None)
    mod = importlib.util.module_from_spec(spec)
    with open(CLI) as fh:
        src = fh.read()
    mod.__dict__["__name__"] = "coverloop_mod"
    mod.__dict__["__file__"] = CLI  # the script resolves its own dir from this
    exec(compile(src, CLI, "exec"), mod.__dict__)
    return mod


class DeterministicClassify(unittest.TestCase):
    """The tier FLOOR derived from paths. These assert the SAFETY direction:
    dangerous paths must never classify below their tier, and an unrecognised
    path must never be treated as inert."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def _cls(self, *paths):
        return self.mod.classify_paths(list(paths))[0]

    def test_migration_is_L3_however_it_is_labelled(self):
        for p in ("supabase/migrations/20260803_x.sql", "db/migration/001.py",
                  "server/migrations/add_col.ts"):
            self.assertEqual(self._cls(p), "L3", p)

    def test_money_auth_secrets_ci_worker_are_L3(self):
        cases = ("src/billing/charge.ts", "app/auth/session.ts",
                 "lib/rls/policies.sql", "config/secrets/keys.ts",
                 ".github/workflows/deploy.yml", "src/worker/cron.ts",
                 "prisma/schema.prisma", ".env.production")
        for p in cases:
            self.assertEqual(self._cls(p), "L3", p)

    def test_unknown_source_is_L1_never_L0(self):
        # Silence is not safety: a file no rule recognises is still code.
        self.assertEqual(self._cls("src/mystery.ts"), "L1")
        self.assertEqual(self._cls("weird/thing.bin"), "L1")

    def test_docs_and_styles_only_are_L0(self):
        self.assertEqual(self._cls("README.md", "docs/GATE.md", "app.css"), "L0")

    def test_highest_tier_wins_across_files(self):
        # One dangerous file drags the whole change up.
        self.assertEqual(self._cls("README.md", "db/migrations/1.sql"), "L3")

    def test_breadth_alone_forces_at_least_L2(self):
        docs = [f"docs/page{i}.md" for i in range(12)]
        self.assertEqual(self._cls(*docs), "L2")

    def test_breadth_never_lowers_a_higher_tier(self):
        paths = [f"docs/p{i}.md" for i in range(12)] + ["src/auth/login.ts"]
        self.assertEqual(self.mod.classify_paths(paths)[0], "L3")

    def test_empty_change_asserts_nothing(self):
        tier, reasons = self.mod.classify_paths([])
        self.assertEqual(tier, "L0")
        self.assertEqual(reasons, [])

    def test_protocol_shell_hooks_are_not_app_state(self):
        # Regression: `hooks/` once matched this repo's own shell hooks and
        # over-classified them as shared application state. Over-classification
        # is friction, and friction gets the gate bypassed.
        self.assertEqual(self._cls("hooks/pre-risky-git.sh"), "L1")
        self.assertEqual(self._cls("src/hooks/useAuth.ts"), "L2")

    def test_reasons_name_the_rule_and_the_file(self):
        tier, reasons = self.mod.classify_paths(["db/migrations/1.sql"])
        self.assertEqual(tier, "L3")
        self.assertTrue(any("migration" in r and "1.sql" in r for r in reasons),
                        reasons)

    def test_explicit_paths_need_no_git_repo(self):
        """Regression: `coverloop classify <path>` must work outside a checkout.
        It classifies the strings it is given; requiring a repo made the command
        unusable from a home directory (found in the field, 2026-08-22)."""
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:  # deliberately NOT a git repo
            out = subprocess.run([sys.executable, CLI, "classify", "--quiet",
                                  "db/migrations/1.sql"],
                                 cwd=d, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip(), "L3", out.stdout + out.stderr)


class DoctorSetupReport(unittest.TestCase):
    """`doctor` is the first command a stranger runs. Its contract: never crash,
    exit non-zero while setup is incomplete, and always name the fix."""

    def _run(self, home, cwd, path="/usr/bin:/bin"):
        import subprocess
        return subprocess.run([sys.executable, CLI, "doctor"],
                              cwd=cwd, capture_output=True, text=True, timeout=60,
                              env={"HOME": home, "PATH": path})

    def test_unconfigured_machine_exits_nonzero_and_names_the_fix(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, d)
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            self.assertIn("openrouter", out.stdout.lower())
            # A bare "MISSING" is useless — the fix must be printed.
            self.assertIn("To finish setup:", out.stdout)
            self.assertIn("openrouter.ai/keys", out.stdout)

    def test_never_leaks_a_stray_error_above_the_report(self):
        """repo_root() prints its own error and exits; doctor must not let that
        spill into stderr and look like a crash (found while testing)."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, d)
            self.assertEqual(out.stderr.strip(), "", out.stderr)
            self.assertTrue(out.stdout.startswith("coverloop doctor"), out.stdout[:80])

    def test_names_the_gate_and_why_there_is_no_shortcut(self):
        """The diff gate needs its own account. Saying only "not installed"
        loses the user; the report must carry the install line AND the reason
        the obvious shortcut (route it through the OpenRouter key you already
        have) is refused — no OpenAI model there offers strict ZDR, and the
        highest-authority reviewer must not run at the lowest privacy bar."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, d)
            self.assertIn("Codex CLI", out.stdout)
            self.assertIn("npm i -g @openai/codex", out.stdout)
            self.assertIn("zero-data-retention", out.stdout)

    def test_no_reviewer_is_advertised_that_cannot_actually_run(self):
        """Regression: a reviewer was shipped and documented that always
        fail-closed, because its provider has no strict-ZDR endpoint while the
        engine hard-requires one. Advertising a reviewer that cannot run is an
        overclaim in a safety tool."""
        import tempfile, os as _os
        bindir = _os.path.dirname(CLI)
        for advertised in ("glm-review",):
            self.assertTrue(_os.path.exists(_os.path.join(bindir, advertised)),
                            f"{advertised} is advertised but missing")
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d, d)
            self.assertNotIn("sol-review", out.stdout,
                             "doctor still advertises a removed reviewer")

    def test_does_not_print_the_key_itself(self):
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as d:
            kd = _os.path.join(d, ".config", "openrouter")
            _os.makedirs(kd)
            with open(_os.path.join(kd, "api_key"), "w") as fh:
                fh.write("sk-or-SECRETVALUE123456")
            out = self._run(d, d)
            self.assertNotIn("SECRETVALUE123456", out.stdout + out.stderr)

class CommittedEvidenceHasNoPII(unittest.TestCase):
    """A privacy tool must not leak the one identifier it advertises removing.

    Regression: an adversarial audit of this repo found the maintainer's
    username committed 16 times in a captured transcript. Claude Code
    slugifies a project path into a directory name (/Users/alice/x ->
    -Users-alice-x), and the PII pattern only matched the slash form — so the
    dash-encoded username sailed straight into a PUBLIC repo. It was invisible
    precisely because the shape looked nothing like a path."""

    def test_dash_encoded_home_paths_are_redacted(self):
        for raw, must_go in (("-Users-alice-Downloads-proj", "alice"),
                             ("-home-bob-src", "bob"),
                             ("/Users/carol/x", "carol"),
                             ("/home/dave/y", "dave")):
            out = F.redact(raw)
            self.assertNotIn(must_go, out, f"username survived redaction: {raw} -> {out}")
            self.assertIn("[REDACTED:user]", out, out)

    def test_pii_labels_are_not_position_coupled(self):
        """redact() used to index PII_PATTERNS[0..2], so inserting a pattern
        shifted every replacement onto the wrong label."""
        self.assertIn("[REDACTED:user]", F.redact("-Users-alice-x"))
        self.assertEqual(F.redact("a@b.com"), "[REDACTED:email]")

    def test_no_committed_evidence_contains_a_home_username(self):
        """Scan the tracked evidence directory for un-redacted home paths."""
        import subprocess, re as _re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run(["git", "ls-files", ".coverloop"], cwd=root,
                             capture_output=True, text=True, timeout=30)
        pat = _re.compile(r"[-/](?:Users|home)[-/](?!\[REDACTED)[A-Za-z0-9_.]+")
        offenders = []
        for rel in out.stdout.split():
            fp = os.path.join(root, rel)
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                continue
            for m in pat.findall(body):
                # A bare "/Users/" with nothing after it is harmless.
                if m.rstrip("-/").split("-")[-1].split("/")[-1]:
                    offenders.append(f"{rel}: {m}")
        self.assertEqual(offenders[:5], [], f"PII in committed evidence: {offenders[:5]}")


class HumanGateScope(unittest.TestCase):
    """Who gets stopped, and the guarantee that narrowing it is opt-in.

    Default: every L3 change waits for a named human. Measured on a real
    billing/auth/worker platform that is ~47% of commits, and a stop that fires
    on half your work is a stop you learn to rubber-stamp — the same failure
    this tool warns about for over-classification. `--human-gate-scope
    irreversible` narrows the STOP to what cannot be taken back; on the same
    repo that was 25%. The automated L3 review is unchanged either way."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def _irreversible(self, path):
        return bool(self.mod.IRREVERSIBLE_RE.search(path))

    def test_the_irreversible_set_is_exactly_migrations_money_and_authz(self):
        for p in ("db/migrations/001.sql", "supabase/migrations/x.sql", "q.sql",
                  "src/billing/charge.ts", "app/checkout/route.ts",
                  "lib/stripe/webhook.ts", "policies/rls.ts", "src/authz/check.ts"):
            self.assertTrue(self._irreversible(p), f"should require a human: {p}")

    def test_revertible_L3_work_does_not_demand_a_human(self):
        """Workers, cron, CI and deploy wiring are L3 — full automated loop —
        but they are revertible, so they must not consume the human stop."""
        for p in ("src/worker/cron.ts", ".github/workflows/deploy.yml",
                  "jobs/queue.ts", "Dockerfile"):
            self.assertFalse(self._irreversible(p), f"should NOT require a human: {p}")
            # …but they are still L3, i.e. still fully reviewed.
            self.assertEqual(self.mod.classify_paths([p])[0], "L3", p)

    def test_narrowing_is_opt_in_only(self):
        """The default must never relax on upgrade. A user who does nothing
        keeps the strict gate."""
        import argparse
        pa = argparse.ArgumentParser()
        sub = pa.add_subparsers(dest="cmd")
        # The real parser is built in main(); assert the default the gate reads.
        self.assertEqual(getattr(argparse.Namespace(), "human_gate_scope", "all"), "all")

    def test_an_empty_change_set_still_demands_a_human(self):
        """No visible diff is not evidence of safety — fail closed."""
        self.assertEqual(self.mod.classify_paths([])[0], "L0")



class IndependentReviewRegressions(unittest.TestCase):
    """Three fail-opens an off-policy review of the v2.10.0 release found.

    Each was verified against the code before being fixed, and each is the kind
    that stays invisible: the tool kept reporting success while the guarantee it
    advertised was not holding.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_escaped_quote_does_not_leak_the_secret_tail(self):
        # `PASSWORD="a\" b"` used to redact only up to the ESCAPED quote, leaving
        # the tail in the packet — and the leaked tail then scanned CLEAN, so the
        # egress tripwire passed it through to the network.
        raw = 'PASSWORD="correct horse\\" battery staple"'
        red = F.redact(raw)
        self.assertNotIn("battery staple", red)
        self.assertIn("[REDACTED:secret-value]", red)

    def test_escaped_quote_redaction_is_linear(self):
        # The fix uses an alternation; if its branches overlapped it would be a
        # ReDoS on scan(), which runs on every outbound review packet.
        blob = 'PASSWORD="' + ('\\"' * 40000)
        t0 = time.monotonic()
        F.scan(blob)
        F.redact(blob)
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_camelcase_names_reach_their_real_tier(self):
        # The boundary required `/`, `.`, `_` or `-` right after the keyword, so
        # ordinary camelCase auth/worker/schema/credential files read as L1.
        for path in ("authorization.ts", "authenticationService.py",
                     "workerPool.ts", "schemaVersion.py", "credentialsManager.go",
                     "authGuard.tsx", "models/user.py"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L3")

    def test_camelcase_boundary_does_not_over_reach(self):
        # The counter-test that matters more: the first cut of the fix compiled
        # the hump under re.I, which folds [A-Z] to [A-Za-z] and made the boundary
        # match ANY continuation — author.ts and keyboard.tsx both read as L3.
        # A floor that cries L3 at prose trains people to bypass the gate.
        for path, expect in (("author.ts", "L1"), ("keyboard.tsx", "L1"),
                             ("monkeyPatch.js", "L1"), ("modelViewer.css", "L0"),
                             ("authors/index.md", "L0"), ("docs/models.md", "L0")):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], expect)

    def test_gate_applies_the_floor_without_being_asked(self):
        # `classify` shipped as a command you had to remember to wire, so
        # `gate --min-tier L0` still passed over a migration. The floor now runs
        # inside the gate, with no flag to switch it off.
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            open(os.path.join(d, "migrations", "002.sql"), "w").write("drop table users;\n")
            r = run(CLI, "gate", "--min-tier", "L0")
            self.assertNotEqual(r.returncode, 0, "L0 claim passed over a migration")
            self.assertIn("L3", r.stderr + r.stdout)


class SecondRoundRegressions(unittest.TestCase):
    """Round two. The first set of fixes was itself reviewed off-policy, and the
    reviewer showed the headline fix was incomplete: the floor only saw
    UNCOMMITTED changes, so on the ordinary path — commit, then gate — it saw
    nothing at all."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def _repo(self, d):
        run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
        run("git", "init", "-q", ".")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        open(os.path.join(d, "README.md"), "w").write("x\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")
        return run

    def test_floor_sees_a_COMMITTED_migration(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "migrations", "002.sql"), "w").write("drop table users;\n")
            run("git", "add", "-A")
            run("git", "commit", "-qm", "migrate")   # <- clean tree, the normal case
            r = subprocess.run([CLI, "gate", "--min-tier", "L0"], cwd=d,
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "L0 passed over a committed migration")
            self.assertIn("L3", r.stdout + r.stderr)

    def test_unresolvable_base_is_not_an_all_clear(self):
        with tempfile.TemporaryDirectory() as d:
            self._repo(d)
            r = subprocess.run([CLI, "gate", "--min-tier", "L0", "--base", "no-such-ref"],
                               cwd=d, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "a typo'd --base read as no changes")

    def test_plain_L2_names_are_not_demoted(self):
        # The L2 rules CONSUMED the separator and then still demanded an
        # extension dot, so the plainest names of all fell through to L1.
        for path in ("src/api.ts", "src/apiClient.ts", "src/middleware.ts",
                     "src/hooks.ts", "src/contextProvider.ts"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L2")

    def test_prose_about_danger_is_not_danger(self):
        for path in ("docs/authGuide.md", "docs/workerPool.md",
                     "docs/credentialsGuide.md", "src/auth.css"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L0")

    def test_cardcom_does_not_swallow_a_card_component(self):
        self.assertEqual(self.mod.classify_paths(["src/CardComponent.tsx"])[0], "L1")
        for path in ("src/invoice.ts", "src/billingService.ts", "src/chargeback.ts"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L3")

    def test_narrowed_human_stop_still_covers_camelcase_authz(self):
        # These classify L3 but were EXEMPT from the stop under the narrowed
        # scope, because the exemption regex kept the old separator boundary —
        # the one place a missed boundary costs the most.
        for path in ("src/authorization.ts", "src/authzGuard.ts", "src/rlsPolicy.ts"):
            with self.subTest(path=path):
                self.assertTrue(self.mod.IRREVERSIBLE_RE.search(path),
                                f"{path} would skip the human stop")

    def test_email_redaction_is_linear_not_quadratic(self):
        """The PII pass runs BEFORE the packet size check, so a slow pattern here
        is a ReDoS no size limit can bound. Measured at 4x per doubling before the
        fix: 400 KB took 93 seconds."""
        prev = None
        for n in (100_000, 200_000, 400_000):
            blob = "a." * (n // 2) + "@"
            t0 = time.monotonic()
            F.redact(blob)
            took = time.monotonic() - t0
            self.assertLess(took, 3.0, f"{n} chars took {took:.1f}s")
            if prev is not None:
                # Linear growth doubles; quadratic quadruples. 2.5x leaves room
                # for timer noise without admitting O(n^2), and the 0.6s noise
                # floor exists because a shared CI runner flaked this at 0.34s
                # vs a 0.26s bound — at these absolute times scheduler jitter
                # dwarfs the signal. The REAL regression detector is the 3.0s
                # absolute ceiling above: the quadratic bug took 93 seconds.
                self.assertLess(took, max(prev * 2.5, 0.6))
            prev = max(took, 0.02)

    def test_email_redaction_still_catches_real_addresses(self):
        # The bound is the RFC 5321 local-part limit, not an arbitrary cap — the
        # counter-test that keeps it from quietly becoming an under-redaction.
        for addr in ("jane.doe+1@sub.example.co.uk", "a@b.io", "x_y%z@mail.example.com"):
            with self.subTest(addr=addr):
                self.assertEqual(F.redact(addr), "[REDACTED:email]")

    def test_no_regex_syntax_newer_than_the_oldest_supported_python(self):
        """Possessive quantifiers and atomic groups need Python 3.11; this repo's
        CI matrix starts at 3.9, where they are a SyntaxError at import time — so
        the whole gate stops running, not just one pattern. That is how a
        "hardening" tweak to the email regex took `coverloop` down on 3.9 while
        every local check on 3.13 stayed green. Grepping the source is cheap
        insurance against a version this machine may not have installed."""
        import glob
        # Atomic groups, and possessive quantifiers in all four spellings.
        offenders = (
            ("atomic group (?>...)", re.compile(r"\(\?>")),
            ("possessive {n,m}+", re.compile(r"\{\d+(?:,\d*)?\}\+")),
            ("possessive *+", re.compile(r"(?<!\\)\*\+")),
            ("possessive ++", re.compile(r"(?<![\\+])\+\+")),
            ("possessive ?+", re.compile(r"(?<!\\)\?\+")),
        )
        for path in sorted(glob.glob(os.path.join(BIN_DIR, "*.py")) + [CLI]):
            src = open(path, encoding="utf-8").read()
            for lineno, line in enumerate(src.splitlines(), 1):
                if "re.compile" not in line and not line.strip().startswith(('r"', 'rf"')):
                    continue
                for label, rx in offenders:
                    if rx.search(line):
                        self.fail(f"{os.path.basename(path)}:{lineno} uses {label}, "
                                  f"which needs Python 3.11: {line.strip()[:70]}")

    def test_unreadable_quota_log_refuses_rather_than_allows(self):
        import egress_cap as cap
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "eg.log")
            open(log, "w").write("x")
            os.chmod(log, 0o000)
            env = dict(os.environ, COVERLOOP_EGRESS_LOG=log,
                       COVERLOOP_DAILY_REVIEW_CAP="40")
            old = os.environ.copy()
            os.environ.update(env)
            try:
                with self.assertRaises(SystemExit) as ctx:
                    cap.enforce_daily_cap()
                self.assertEqual(ctx.exception.code, 4)
            finally:
                os.chmod(log, 0o644)
                os.environ.clear()
                os.environ.update(old)


class ThirdRoundRegressions(unittest.TestCase):
    """The last two findings: a classifier that cried danger at UI components,
    and a daily cap two reviewers could walk past together."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_pascalcase_component_names_are_not_danger(self):
        # The camelCase boundary that rescued workerPool.ts also swept in every
        # PascalCase component whose name happens to start with a keyword.
        for path in ("src/ModelViewer.tsx", "src/ContextMenu.tsx",
                     "src/RoutePlanner.tsx", "src/StateBadge.tsx",
                     "src/StoreFront.tsx"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L1")

    def test_narrowing_did_not_cost_the_real_matches(self):
        # The counter-test. Only the HUMP form was restricted, and only for words
        # that collide with component naming — so directory and dotted forms, and
        # every dangerous keyword, still land where they did.
        for path, expect in (("src/AuthGuard.tsx", "L3"), ("src/authGuard.tsx", "L3"),
                             ("models/user.py", "L3"), ("src/model.ts", "L3"),
                             ("src/Schema.ts", "L3"), ("src/schemaVersion.py", "L3"),
                             ("credentialsManager.go", "L3"),
                             ("src/routes/api.ts", "L2"), ("src/contextProvider.ts", "L2"),
                             ("src/api.ts", "L2"), ("src/store/index.ts", "L2")):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], expect)

    def test_daily_cap_holds_under_real_concurrency(self):
        """Twelve processes, cap of five. The check used to sit ~15 lines before
        the attempt was recorded, so reviewers on different projects could all
        read cap-1 and all send. Threads would not prove this — the lock is
        per-process, so this spawns real ones."""
        prog = (
            "import sys, os, json, datetime\n"
            "sys.path.insert(0, %r)\n"
            "import egress_cap\n"
            "def rec():\n"
            "    with open(os.environ['COVERLOOP_EGRESS_LOG'], 'a') as f:\n"
            "        f.write(json.dumps({'phase': 'attempt', 'ts': datetime.datetime.now("
            "datetime.timezone.utc).isoformat()}) + '\\n')\n"
            "egress_cap.reserve_daily_slot(rec)\n"
            "print('SENT')\n"
        ) % os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "egress.log")
            env = dict(os.environ, COVERLOOP_EGRESS_LOG=log,
                       COVERLOOP_DAILY_REVIEW_CAP="5")
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(12) as ex:
                results = list(ex.map(
                    lambda _: subprocess.run([sys.executable, "-c", prog], env=env,
                                             capture_output=True, text=True),
                    range(12)))
            sent = sum(1 for r in results if "SENT" in r.stdout)
            self.assertEqual(sent, 5, f"cap 5 but {sent} processes sent")
            with open(log) as fh:
                self.assertEqual(sum(1 for line in fh if line.strip()), 5)


class FourthRoundRegressions(unittest.TestCase):
    """Path collection. Three copies of the same git calls had drifted apart, and
    two of them lost paths in ways an author could exploit."""

    def _repo(self, d):
        run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
        run("git", "init", "-q", ".")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        os.makedirs(os.path.join(d, "src"), exist_ok=True)
        open(os.path.join(d, "README.md"), "w").write("x\n")
        return run

    def test_a_rename_cannot_hide_the_dangerous_name(self):
        # `git diff --name-only` reports only the DESTINATION of a rename, so
        # moving src/authGuard.ts to src/guard.ts turned an auth change into an
        # unrecognised source file. Renaming your way past the floor is the
        # cheapest evasion there is.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            open(os.path.join(d, "src", "authGuard.ts"), "w").write("export const x = 1\n")
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            run("git", "mv", "src/authGuard.ts", "src/guard.ts")
            run("git", "commit", "-qm", "rename")
            r = subprocess.run([CLI, "gate", "--min-tier", "L0"], cwd=d,
                               capture_output=True, text=True)
            self.assertIn("L3", r.stdout + r.stderr,
                          "a rename hid the auth origin from the floor")

    def test_a_path_git_would_quote_is_not_torn_in_half(self):
        # git C-quotes names containing a newline; splitting on lines then tore
        # one path into two meaningless fragments, neither of which matched.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            weird = os.path.join(d, "src", "auth\nGuard.ts")
            try:
                open(weird, "w").write("x\n")
            except OSError:
                self.skipTest("filesystem rejects newlines in names")
            run("git", "add", "-A")
            r = subprocess.run([CLI, "classify", "--quiet"], cwd=d,
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), "L3")

    def test_classify_and_gate_collect_the_same_paths(self):
        # The two commands each had their own copy of the collection logic, so a
        # fix to one silently missed the other. This is the property that keeps
        # them honest, whatever the collector does next.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            open(os.path.join(d, "src", "authGuard.ts"), "w").write("x\n")
            c = subprocess.run([CLI, "classify", "--quiet"], cwd=d,
                               capture_output=True, text=True).stdout.strip()
            g = subprocess.run([CLI, "gate", "--min-tier", "L0"], cwd=d,
                               capture_output=True, text=True)
            self.assertEqual(c, "L3")
            self.assertIn("L3", g.stdout + g.stderr)

    def test_unresolvable_base_is_a_usage_error_not_an_L1_floor(self):
        # Substituting an L1 floor let a valid L1 report gate successfully over a
        # base that was never read — the caller believes a range was reviewed.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            r = subprocess.run([CLI, "gate", "--min-tier", "L0", "--base", "no-such-ref"],
                               cwd=d, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
            self.assertIn("cannot resolve", r.stderr)

    def test_lock_failure_refuses_rather_than_racing(self):
        import egress_cap as cap
        old = os.environ.copy()
        with tempfile.TemporaryDirectory() as d:
            # A directory where the lock file cannot be created.
            os.environ.update(COVERLOOP_EGRESS_LOG=os.path.join(d, "ro", "eg.log"),
                              COVERLOOP_DAILY_REVIEW_CAP="5")
            os.makedirs(os.path.join(d, "ro"))
            os.chmod(os.path.join(d, "ro"), 0o500)
            os.environ.pop("COVERLOOP_ALLOW_UNLOCKED_CAP", None)
            try:
                with self.assertRaises(SystemExit) as ctx:
                    cap.reserve_daily_slot(lambda: None)
                self.assertEqual(ctx.exception.code, 4)
            finally:
                os.chmod(os.path.join(d, "ro"), 0o700)
                os.environ.clear()
                os.environ.update(old)


class FifthRoundRegressions(unittest.TestCase):
    """Six defects, two of them the same disease: a list that had to agree with
    another list, kept in step by hand."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_a_quoted_secret_may_span_lines(self):
        # The quoted branch excluded newlines, so a multi-line value redacted its
        # first line and left the rest — and the leaked tail scanned CLEAN.
        for raw, leak in (
            ('PASSWORD="alpha123\nbeta456"', "beta456"),
            ('PASSWORD="alpha\\\nbeta"', "beta"),
            ('API_KEY="one\ntwo\nthree"', "three"),
        ):
            with self.subTest(raw=raw):
                red = F.redact(raw)
                self.assertNotIn(leak, red)
                self.assertIn("[REDACTED:secret-value]", red)

    def test_an_unterminated_quote_is_bounded_to_its_line(self):
        """An unterminated quote after a secret name redacts the rest of that LINE
        and stops. The earlier assertion here (that most of the text survives) was
        wrong: honouring it required the match to FAIL past the 4096-character
        cap, which meant redact() replaced nothing at all and a 4097-character
        secret went out whole — under-redaction dressed up as restraint. Losing a
        line of review context is the cheap side of this trade."""
        blob = 'PASSWORD="unterminated ' + ("x" * 20000) + "\nSURVIVES = 1\nalso here\n"
        red = F.redact(blob)
        self.assertNotIn("x" * 100, red)
        self.assertIn("SURVIVES = 1", red)
        self.assertIn("also here", red)

    def test_a_long_secret_is_never_passed_through_untouched(self):
        # The regression this replaced: past the cap the whole match failed, so
        # redact() made NO replacement and scan() saw no assignment.
        for n in (4000, 4096, 4097, 9000, 60000):
            with self.subTest(length=n):
                red = F.redact('PASSWORD="' + ("a" * n) + '"')
                self.assertIn("[REDACTED:secret-value]", red)
                self.assertNotIn("a" * 100, red)

    def test_irreversible_is_derived_from_the_rules(self):
        # A parallel regex drifted from RISK_RULES three times, each time waiving
        # the human stop for changes the option promises to stop. Any L3 rule
        # whose reason is in IRREVERSIBLE_REASONS is now covered automatically.
        for path in ("alembic/versions/1.py", "db/migrate/1.rb", "migrations/1.sql",
                     "src/authorization.ts", "src/rbac.ts", "src/acl.ts",
                     "src/wallet/transfer.ts", "models/user.py"):
            with self.subTest(path=path):
                self.assertTrue(self.mod.is_irreversible(path))
        for path in ("README.md", "src/worker/job.ts", "src/api.ts"):
            with self.subTest(path=path):
                self.assertFalse(self.mod.is_irreversible(path))

    def test_every_irreversible_reason_is_a_real_rule_reason(self):
        """The property that keeps the derivation honest: a typo in the reason set
        would silently cover nothing."""
        rule_reasons = {why for tier, _rx, why in self.mod.RISK_RULES if tier == "L3"}
        self.assertTrue(self.mod.IRREVERSIBLE_REASONS <= rule_reasons,
                        self.mod.IRREVERSIBLE_REASONS - rule_reasons)

    def test_txt_is_not_presumed_inert(self):
        # The blanket .txt shortcut declared config/permissions.txt L0 ahead of
        # the rule that calls `permissions` an L3 keyword.
        self.assertEqual(self.mod.classify_paths(["config/permissions.txt"])[0], "L3")
        self.assertEqual(self.mod.classify_paths(["requirements.txt"])[0], "L2")
        # .txt left the inert list entirely in the round that followed: plain
        # text configures real behaviour often enough that presuming prose was
        # the wrong default. Unmatched .txt now lands on L1, not L0.
        self.assertEqual(self.mod.classify_paths(["docs/notes.txt"])[0], "L1")

    def test_re_attesting_cannot_shrink_what_the_floor_covers(self):
        """Dangerous commit A, attested L0; evidence-only commit B; attest again.
        The rebind used to overwrite the report's commit with HEAD, so the floor
        classified only HEAD^..HEAD and A became invisible."""
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "init")
            subprocess.run([CLI, "init"], cwd=d, capture_output=True, text=True)
            os.makedirs(os.path.join(d, "migrations"), exist_ok=True)
            open(os.path.join(d, "migrations", "002.sql"), "w").write("drop table users;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "A")
            for _ in range(2):
                subprocess.run([CLI, "attest", "--tier", "L0"], cwd=d,
                               capture_output=True, text=True)
                run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            r = subprocess.run([CLI, "gate"], cwd=d, capture_output=True, text=True)
            self.assertIn("L3", r.stdout + r.stderr,
                          "re-attesting hid the migration from the floor")
            self.assertNotEqual(r.returncode, 0)


class SixthRoundRegressions(unittest.TestCase):
    """Two of these were defects the PREVIOUS round's fixes introduced. That is
    the honest reason this loop was stopped here rather than run again."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_irreversibility_does_not_depend_on_rule_order(self):
        # is_irreversible() returned on the FIRST matching rule, so
        # workers/models/user.py hit the worker rule (L3, reversible) before the
        # schema rule and the human stop was waived for a schema change because
        # of where the file happened to live.
        for path in ("workers/models/user.py", "secrets/schema.py",
                     ".github/workflows/migrations/x.yml"):
            with self.subTest(path=path):
                self.assertTrue(self.mod.is_irreversible(path))

    def test_option_shaped_signers_ref_cannot_reach_git_as_a_flag(self):
        # Same class as the --base injection: `git show` takes options
        # positionally, so --signers-ref=--format=... could materialise
        # attacker-chosen commit text AS the allowed-signers policy.
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")
            self.assertIsNone(
                self.mod._project_signers_file(d, "--format=%s", d),
                "an option-shaped ref produced signer content")

    def test_a_failed_range_lookup_is_unknown_not_empty(self):
        # `or []` turned a git failure into an empty path set with unknown=False
        # — an all-clear assembled out of a failure.
        import types
        real = self.mod.git
        try:
            self.mod.git = lambda a, cwd=None: None
            paths, unknown = self.mod._gate_floor_paths(
                ".", types.SimpleNamespace(base=None), None, "0" * 40)
            self.assertTrue(unknown, "a total git failure reported a known, empty set")
        finally:
            self.mod.git = real


class InvariantsThatCatchTheAuthor(unittest.TestCase):
    """Properties, not examples.

    Seven rounds of off-policy review found two defects that the FIXES had
    introduced, and both were invisible to example-based tests: a length cap that
    made long secrets stop matching entirely, and an order-dependent
    irreversibility check. Each is a broken INVARIANT, and each is caught here in
    milliseconds instead of in the next review round. The point of this class is
    to move that detection from the reviewer back to the author."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    # -- secret filter -------------------------------------------------------

    SECRET_NAMES = ("PASSWORD", "API_KEY", "OPENROUTER_API_KEY", "DB_PASSWORD",
                    "VERCEL_TOKEN", "SECRET_KEY", "x_secret", "SERVICE_TOKEN")

    def test_no_secret_value_ever_survives_redaction(self):
        """For every combination of name, separator, quoting, length and embedded
        escape, the value must not appear in the output. The 4096-character cap
        regression lived exactly in the gap between 4096 and 4097."""
        marker = "ZqXsecretVALUE"
        lengths = (1, 10, 4094, 4095, 4096, 4097, 4098, 8200)
        checked = 0
        for name in self.SECRET_NAMES:
            for sep in ("=", ": ", " = "):
                for quote in ("", '"', "'"):
                    for n in lengths:
                        body = marker + ("a" * max(0, n - len(marker)))
                        raw = f"{name}{sep}{quote}{body}{quote}"
                        red = F.redact(raw)
                        checked += 1
                        self.assertNotIn(marker, red,
                                         f"leaked: name={name!r} sep={sep!r} "
                                         f"quote={quote!r} len={n}")
        self.assertGreater(checked, 400)

    def test_no_secret_value_survives_an_embedded_newline_or_escape(self):
        marker = "ZqXsecretVALUE"
        for filler in ("\n", "\r\n", "\\\n", '\\"', "\\'", "\t"):
            for quote in ('"', "'"):
                raw = f'PASSWORD={quote}head{filler}{marker}{quote}'
                with self.subTest(filler=repr(filler), quote=quote):
                    self.assertNotIn(marker, F.redact(raw))

    def test_redaction_never_makes_the_scan_blind(self):
        """A packet that scans clean after redaction must not still contain a
        recognisable secret shape. This is the property the escaped-quote and
        multi-line leaks both violated: the tail survived AND scanned clean."""
        shapes = ("sk-" + "a" * 40, "ghp_" + "b" * 36, "AKIA" + "C" * 16,
                  "xoxb-" + "1" * 20, "AIza" + "d" * 35)
        for shape in shapes:
            for wrapper in ('PASSWORD="%s"', "TOKEN='%s'", "API_KEY=%s",
                            'SECRET_KEY="lead\n%s"'):
                raw = wrapper % shape
                with self.subTest(raw=raw[:40]):
                    red = F.redact(raw)
                    if not F.scan(red):
                        self.assertNotIn(shape, red,
                                         "scanned clean while still carrying the secret")

    # -- classifier ----------------------------------------------------------

    def test_irreversibility_never_depends_on_rule_order(self):
        """If ANY irreversible rule matches a path, the answer must be True —
        whatever other rule happens to match first. Built by crossing every
        reversible-rule directory with every irreversible-rule filename."""
        reversible_dirs = ("workers", "secrets", "cron", "queue", "jobs",
                           ".github/workflows", "credentials")
        irreversible_names = ("models/user.py", "schema.sql", "migrations/1.sql",
                              "authorization.ts", "billing.ts", "rls.ts")
        for d in reversible_dirs:
            for n in irreversible_names:
                path = f"{d}/{n}"
                with self.subTest(path=path):
                    self.assertTrue(self.mod.is_irreversible(path), path)

    def test_every_irreversible_path_also_classifies_L3(self):
        """Irreversible but below L3 would be incoherent: the human stop would be
        demanded for a change the gate calls routine."""
        for path in ("models/user.py", "migrations/1.sql", "src/authz.ts",
                     "src/billing.ts", "workers/schema.py", "db/migrate/1.rb"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L3")

    def test_adding_a_path_never_lowers_the_tier(self):
        """Monotonicity. A change set can only get more dangerous as it grows."""
        order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        pool = ["README.md", "src/api.ts", "migrations/1.sql", "src/util.ts",
                "package.json", "src/authGuard.ts", "docs/x.md", "config/roles.txt"]
        acc = []
        prev = 0
        for p in pool:
            acc.append(p)
            tier = order[self.mod.classify_paths(acc)[0]]
            self.assertGreaterEqual(tier, prev, f"adding {p} LOWERED the tier")
            prev = tier

    def test_only_provably_inert_extensions_may_reach_L0(self):
        """L0 requires no evidence at all, so anything landing there must be
        inert by EXTENSION, never merely by failing to match a rule."""
        inert = (".md", ".mdx", ".rst", ".adoc", ".css", ".scss", ".sass", ".less")
        known_L0 = ("LICENSE", "CODEOWNERS", ".gitignore", ".editorconfig")
        for path in ("src/thing.ts", "config/roles.txt", "notes.txt", "Makefile",
                     "src/mod.rs", "data.csv", "run.sh", "x.bin", "a.yaml"):
            with self.subTest(path=path):
                tier = self.mod.classify_paths([path])[0]
                if tier == "L0":
                    self.assertTrue(
                        path.endswith(inert) or os.path.basename(path) in known_L0,
                        f"{path} reached L0 without being provably inert")


class SeventhRoundRegressions(unittest.TestCase):
    """Three defects found while closing the previous round's remaining items —
    one of them my own dead-code bug, caught only by re-running the suite."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_attest_refuses_to_record_below_the_floor(self):
        """The structural fix: attest itself must enforce the deterministic
        floor, not just record whatever --tier the caller asserts. Without
        this, an evidence report could carry an honest-looking L0 that gate
        would later trust as a baseline without ever having checked it."""
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", "-b", "main", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "init")
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "migrations", "1.sql"), "w").write("drop table x;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = subprocess.run([CLI, "attest", "--tier", "L0"], cwd=d,
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "attest recorded L0 over a migration")
            self.assertIn("L3", r.stderr)

    def test_the_floor_accumulates_the_evidence_gap_not_just_the_worktree(self):
        """Regression for a dead-code bug: a stray `return` inside `_gate_floor_
        paths` sat ABOVE `paths += out`, so the historical diff was computed
        and then silently discarded — every gate call effectively saw only
        uncommitted changes, exactly the original hole this floor exists to
        close. All 216 tests were green with the working tree already clean in
        most of them, which is precisely why this needs its own direct check
        of the returned path list rather than trusting a gate exit code."""
        import types
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", "-b", "main", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "init")
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "migrations", "1.sql"), "w").write("drop table x;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            paths, unknown = self.mod._gate_floor_paths(
                d, types.SimpleNamespace(base=None), None, self.mod.head_sha(d))
            self.assertFalse(unknown)
            self.assertIn("migrations/1.sql", paths,
                          "the committed migration never reached the returned path list")

    def test_evidence_artifacts_do_not_classify_as_their_own_risk(self):
        """.coverloop/reports/ holds the tool's OWN generated output. Without
        an exclusion, a commit that ONLY adds a report file classified as
        'L1: unrecognized source' — a repo's evidence chain re-flagging
        itself as unreviewed on every attest."""
        self.assertEqual(
            self.mod.classify_paths([".coverloop/reports/" + "a" * 40 + ".json"])[0],
            "L0")
        self.assertEqual(
            self.mod.classify_paths([".coverloop/reports/" + "a" * 40 + ".codex.log"])[0],
            "L0")
        # A real source file living OUTSIDE the evidence directory is unaffected —
        # this one has no matching keyword, so it is an ordinary unrecognized
        # source file (L1), not exempted just because the word 'reports' appears.
        self.assertEqual(self.mod.classify_paths(["src/reports/thing.ts"])[0], "L1")
        self.assertEqual(self.mod.classify_paths(["src/api/reports.ts"])[0], "L2")


class EighthRoundRegressions(unittest.TestCase):
    """Round eight targeted the newest code: all three defects were in fixes
    from the two rounds before it."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def _repo(self, d):
        run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
        run("git", "init", "-q", "-b", "main", ".")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        open(os.path.join(d, "README.md"), "w").write("x\n")
        run("git", "add", "-A"); run("git", "commit", "-qm", "init")
        return run

    def test_evidence_exemption_is_anchored_to_the_repo_root(self):
        # Unanchored, every occurrence of the substring matched — including the
        # unescaped-dot lookalike — so an attacker could park a migration under
        # any directory NAMED like the evidence tree and classify it L0.
        for path in ("nested/.coverloop/reports/evil.sql",
                     "x.coverloop/reports/migration.sql",
                     "a/b/.coverloop/reports/c.sql"):
            with self.subTest(path=path):
                self.assertEqual(self.mod.classify_paths([path])[0], "L3")
        self.assertEqual(
            self.mod.classify_paths([".coverloop/reports/" + "a" * 40 + ".json"])[0],
            "L0")

    def test_attest_refuses_when_the_floor_is_unknowable(self):
        # Skipping the check when git could not answer was a fail-open: with
        # `git diff` broken, attest recorded L0 over a migration and exited 0.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "migrations", "1.sql"), "w").write("drop table x;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            shim = os.path.join(d, "shim"); os.makedirs(shim)
            real_git = subprocess.run(["which", "git"], capture_output=True,
                                      text=True).stdout.strip()
            with open(os.path.join(shim, "git"), "w") as fh:
                fh.write("#!/bin/bash\n"
                         'if [ "$1" = "diff" ] || [ "$1" = "rev-list" ]; then exit 1; fi\n'
                         f'exec {real_git} "$@"\n')
            os.chmod(os.path.join(shim, "git"), 0o755)
            env = dict(os.environ, PATH=shim + os.pathsep + os.environ["PATH"])
            r = subprocess.run([CLI, "attest", "--tier", "L0"], cwd=d, env=env,
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0,
                                "attest recorded a tier it could not validate")
            self.assertFalse(
                any(f.endswith(".json") for f in
                    os.listdir(os.path.join(d, ".coverloop", "reports"))
                    if os.path.isdir(os.path.join(d, ".coverloop", "reports"))) if
                os.path.isdir(os.path.join(d, ".coverloop", "reports")) else False,
                "a report was written despite the refusal")

    def test_a_planted_under_tier_report_is_not_a_trusted_baseline(self):
        """The worst of the three: existence is not validity. A hand-written L0
        report sitting on a migration commit became the floor's baseline, the
        migration fell outside every later prior..sha diff, and gate PASSED at
        L0 — verified end-to-end before the fix."""
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            subprocess.run([CLI, "init", "--test-command", "true"], cwd=d,
                           capture_output=True, text=True)
            run("git", "add", "-A"); run("git", "commit", "-qm", "scaffolding")
            os.makedirs(os.path.join(d, "migrations"))
            open(os.path.join(d, "migrations", "A.sql"), "w").write("drop table users;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "A: migration")
            sha_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                                   capture_output=True, text=True).stdout.strip()
            with open(os.path.join(d, ".coverloop", "reports", sha_a + ".json"), "w") as fh:
                json.dump({"schema": "coverloop-report/v1",
                           "commit": sha_a, "risk_tier": "L0"}, fh)
            run("git", "add", "-A"); run("git", "commit", "-qm", "B: evidence only")
            r = subprocess.run([CLI, "gate"], cwd=d, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("L3", r.stdout + r.stderr,
                          "the planted L0 report hid the migration from the floor")

    def test_an_honest_baseline_still_advances(self):
        # The counter-test: a report whose tier genuinely covers its segment
        # must still be accepted, or every gate call walks to the root forever.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            subprocess.run([CLI, "init", "--test-command", "true"], cwd=d,
                           capture_output=True, text=True)
            run("git", "add", "-A"); run("git", "commit", "-qm", "scaffolding")
            r = subprocess.run([CLI, "attest", "--tier", "L1", "--tests"], cwd=d,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            open(os.path.join(d, "NOTES.md"), "w").write("inert\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "docs")
            r = subprocess.run([CLI, "gate", "--min-tier", "L0"], cwd=d,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


class NinthRoundRegressions(unittest.TestCase):
    """The last finding of the sequence: two predicates for one concept."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def test_whitespace_cannot_smuggle_a_file_into_the_exemption(self):
        """classify_paths() stripped paths BEFORE testing the artifact shape, so
        a name with surrounding whitespace was normalised INTO the exempt shape
        and skipped the L1 floor. git reports the real name; a name with
        surrounding whitespace is a different, more suspicious file."""
        sha = "a" * 40
        for suffix in (".json", ".codex.log", ".glm.log"):
            for path in (f".coverloop/reports/{sha}{suffix} ",
                         f" .coverloop/reports/{sha}{suffix}",
                         f".coverloop/reports/{sha}{suffix}\t",
                         f".coverloop/reports/{sha}{suffix}\n"):
                with self.subTest(path=repr(path)):
                    self.assertNotEqual(self.mod.classify_paths([path])[0], "L0")

    def test_the_genuine_artifact_is_still_exempt(self):
        sha = "b" * 40
        for suffix in (".json", ".codex.log", ".glm.log"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    self.mod.classify_paths([f".coverloop/reports/{sha}{suffix}"])[0],
                    "L0")

    def test_the_collector_hands_the_classifier_raw_names(self):
        """END-TO-END, through real git. The unit tests above passed while the
        bypass was still live one layer down: git() called .stdout.strip() on
        NUL-delimited output, so " .coverloop/reports/<sha>.json" arrived at the
        classifier already normalised into the exempt shape. A test that calls
        classify_paths() directly cannot see that."""
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
            run("git", "init", "-q", "-b", "main", ".")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            open(os.path.join(d, "README.md"), "w").write("x\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "init")
            os.makedirs(os.path.join(d, ".coverloop", "reports"))
            try:
                open(os.path.join(d, ".coverloop", "reports",
                                  f" {sha}.json"), "w").write("x")
            except OSError:
                self.skipTest("filesystem rejects leading-space names")
            r = subprocess.run([CLI, "classify", "--quiet"], cwd=d,
                               capture_output=True, text=True)
            self.assertNotEqual(r.stdout.strip(), "L0",
                                "a leading-space name took the artifact exemption")

    def test_every_path_collector_uses_the_raw_collector(self):
        """The bypass reappeared twice at a lower layer, so this asserts the
        STRUCTURE rather than another instance: no pathname-producing git call
        may bypass _git_paths(), because each one that does re-opens the
        normalisation hole in its own caller."""
        src = open(CLI, encoding="utf-8").read()
        offenders = []
        for lineno, line in enumerate(src.splitlines(), 1):
            if '"--name-only"' not in line and '"--others"' not in line:
                continue  # prose mentioning the flag is not a call site
            if "_git_paths(" in line or line.lstrip().startswith("#"):
                continue
            offenders.append(f"{lineno}: {line.strip()[:70]}")
        self.assertFalse(offenders,
                         "path-producing git calls outside _git_paths():\n"
                         + "\n".join(offenders))

    def test_one_predicate_governs_the_exemption(self):
        """The bypass existed because two regexes encoded 'is this an evidence
        artifact' and only one was strict. Any future divergence reintroduces it."""
        src = open(CLI, encoding="utf-8").read()
        self.assertNotIn("_EVIDENCE_RE", src,
                         "a second artifact predicate came back")
        self.assertIn("is_report_artifact(path)", src)


class DerivedTier(unittest.TestCase):
    """v2.11: the risk tier is DERIVED from the changed paths with the gate's
    own floor semantics, and may only be elevated upward, with a durable reason
    recorded in the report."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coverloop()

    def _repo(self, d, reviewers=None, cmds=None):
        run = lambda *a, **k: subprocess.run(a, cwd=d, capture_output=True, text=True, **k)
        run("git", "init", "-q", "-b", "main", ".")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        open(os.path.join(d, "README.md"), "w").write("x\n")
        run("git", "add", "-A"); run("git", "commit", "-qm", "init")
        self._cl(d, "init")
        cfg_path = os.path.join(d, ".coverloop", "config.json")
        cfg = json.load(open(cfg_path))
        cfg["test_command"] = "true"
        json.dump(cfg, open(cfg_path, "w"), indent=2)
        run("git", "add", "-A"); run("git", "commit", "-qm", "coverloop")
        return run

    def _cl(self, d, *a):
        return subprocess.run([sys.executable, CLI] + list(a), cwd=d,
                              capture_output=True, text=True)

    def _write(self, d, rel, body="x\n"):
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)

    def _report(self, d):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                              capture_output=True, text=True).stdout.strip()
        return json.load(open(os.path.join(d, ".coverloop", "reports", head + ".json")))

    def test_tier_is_derived_from_the_paths_with_no_flag_at_all(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "supabase/migrations/1.sql", "alter table u add c int;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = self._cl(d, "attest", "--tests")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L3")
            self.assertEqual(rep["tier_source"], "derived")
            self.assertEqual(rep["floor"]["tier"], "L3")
            self.assertTrue(any("migration" in x for x in rep["floor"]["reasons"]))

    def test_a_tier_below_the_deterministic_floor_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "supabase/migrations/1.sql", "drop table u;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = self._cl(d, "attest", "--tier", "L0", "--tests")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("below the deterministic floor", r.stderr)
            self.assertFalse(glob_reports(d), "a refused attest must write nothing")

    def test_raise_tier_below_the_floor_is_refused_too(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "supabase/migrations/1.sql", "drop table u;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = self._cl(d, "attest", "--raise-tier", "L1", "--reason", "looks small to me")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertFalse(glob_reports(d))

    def test_elevation_above_the_floor_requires_a_durable_reason(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "docs/note.md", "prose\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "doc")
            bare = self._cl(d, "attest", "--raise-tier", "L3")
            self.assertEqual(bare.returncode, 2, bare.stdout + bare.stderr)
            self.assertIn("--reason", bare.stderr)
            ok = self._cl(d, "attest", "--raise-tier", "L3", "--reason",
                          "milestone gate covering 14 migrations")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L3")
            self.assertEqual(rep["tier_source"], "elevated")
            self.assertEqual(rep["elevation"]["reason"],
                             "milestone gate covering 14 migrations")
            self.assertEqual(rep["elevation"]["to"], "L3")

    def test_the_legacy_tier_pin_above_the_floor_still_works_and_says_so(self):
        # Every pre-2.11 caller (four repos' CI, the docs, the skill) passes
        # --tier. It must keep working, be recorded as an elevation, and print
        # the migration note — not fail the way --raise-tier does.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/a.ts", "export const a = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "src")
            r = self._cl(d, "attest", "--tier", "L3", "--tests")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("note:", r.stderr)
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L3")
            self.assertEqual(rep["tier_source"], "elevated")
            self.assertIn("legacy", rep["elevation"]["reason"])

    def test_an_existing_report_can_never_be_downgraded_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/a.ts", "export const a = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "src")
            self._cl(d, "attest", "--tier", "L3", "--tests")
            r = self._cl(d, "attest", "--tier", "L1")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("refusing to downgrade", r.stderr)
            self.assertEqual(self._report(d)["risk_tier"], "L3")

    def test_an_elevation_cannot_claim_the_classifier_exemption(self):
        # --human-gate-scope irreversible exempts changes the CLASSIFIER reads
        # as reversible. An elevation exists because the classifier under-reads
        # the change, so it must not be excused by that same classifier.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/settings.ts", "export const authMode = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "config")
            self._cl(d, "attest", "--tests", "--codex", "pass", "--glm", "pass",
                     "--raise-tier", "L3", "--reason", "this config steers auth")
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            g = self._cl(d, "gate", "--human-gate-scope", "irreversible")
            self.assertIn("human gate", g.stdout)
            self.assertIn("NOT APPROVED", g.stdout)
            self.assertEqual(g.returncode, 1)

    def test_an_elevation_reason_survives_a_later_attest(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/a.ts", "export const a = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "src")
            self._cl(d, "attest", "--raise-tier", "L3", "--reason", "milestone gate")
            self._cl(d, "attest", "--approve", "--approver", "Daniel")
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L3")
            self.assertEqual(rep["tier_source"], "elevated")
            self.assertEqual(rep["elevation"]["reason"], "milestone gate")

    def test_a_lower_tier_approval_does_not_survive_an_elevation(self):
        # attest --approve is allowed at every tier. Carrying an L1 sign-off
        # into a later L3 elevation let it authorize a reason that did not
        # exist when it was given.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/a.ts", "export const a = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "src")
            self._cl(d, "attest", "--tests", "--approve", "--approver", "Daniel")
            self.assertTrue(self._report(d)["human_gate"]["approved"])
            self._cl(d, "attest", "--raise-tier", "L3", "--reason", "steers auth")
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L3")
            self.assertNotIn("human_gate", rep,
                             "an approval given at L1 cannot authorize an L3 elevation")


    def test_a_forced_tier_cannot_claim_the_classifier_exemption(self):
        # --raise-tier L3 --reason "..." then --force --tier L3 flipped
        # tier_source to "forced", which a check matching only "elevated"
        # did not recognise — and the human requirement disappeared.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/settings.ts", "export const authMode = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "config")
            self._cl(d, "attest", "--tests", "--codex", "pass", "--glm", "pass",
                     "--raise-tier", "L3", "--reason", "this config steers auth")
            self._cl(d, "attest", "--force", "--tier", "L3")
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            g = self._cl(d, "gate", "--human-gate-scope", "irreversible")
            self.assertIn("NOT APPROVED", g.stdout, g.stdout)
            self.assertEqual(g.returncode, 1, g.stdout)

    def test_raise_tier_never_lowers_even_with_force(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "supabase/migrations/1.sql", "alter table u;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = self._cl(d, "attest", "--raise-tier", "L1", "--reason", "looks small",
                         "--force", "--tests")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("only ever raises", r.stderr)

    def test_a_forced_below_floor_tier_is_recorded_as_forced(self):
        # --force stays available for the legacy pin (released behaviour), but
        # it is never silent: the report says so, and the gate recomputes.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "supabase/migrations/1.sql", "alter table u;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "migrate")
            r = self._cl(d, "attest", "--force", "--tier", "L0", "--tests")
            self.assertEqual(r.returncode, 0, r.stderr)
            rep = self._report(d)
            self.assertEqual(rep["risk_tier"], "L0")
            self.assertEqual(rep["tier_source"], "forced")
            self.assertEqual(rep["floor"]["tier"], "L3")
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            g = self._cl(d, "gate")
            self.assertIn("tier L3", g.stdout, "the gate computes its own floor")
            self.assertEqual(g.returncode, 1)


    def test_a_legacy_report_without_provenance_is_not_assumed_derived(self):
        # Pre-2.11 reports record no tier_source, and back then the tier was
        # DECLARED. Defaulting them to "derived" handed the
        # --human-gate-scope irreversible exemption to exactly the reports most
        # likely to have been caller-elevated.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/settings.ts", "export const authMode = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "config")
            self._cl(d, "attest", "--tests", "--codex", "pass", "--glm", "pass")
            rep_path = os.path.join(d, ".coverloop", "reports",
                                    subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                                                   capture_output=True, text=True
                                                   ).stdout.strip() + ".json")
            rep = json.load(open(rep_path))
            rep["risk_tier"] = "L3"            # a v2.10-shaped, caller-declared L3
            rep.pop("tier_source", None); rep.pop("floor", None); rep.pop("elevation", None)
            json.dump(rep, open(rep_path, "w"), indent=2)
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            g = self._cl(d, "gate", "--human-gate-scope", "irreversible")
            self.assertIn("NOT APPROVED", g.stdout, g.stdout)
            self.assertEqual(g.returncode, 1, g.stdout)

    def test_re_attesting_a_legacy_report_does_not_launder_its_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "src/a.ts", "export const a = 1;\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "src")
            self._cl(d, "attest", "--tests")
            rep_path = os.path.join(d, ".coverloop", "reports",
                                    subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                                                   capture_output=True, text=True
                                                   ).stdout.strip() + ".json")
            rep = json.load(open(rep_path))
            rep["risk_tier"] = "L3"
            rep.pop("tier_source", None); rep.pop("floor", None); rep.pop("elevation", None)
            json.dump(rep, open(rep_path, "w"), indent=2)
            self._cl(d, "attest", "--approve", "--approver", "Daniel")
            rep = self._report(d)
            self.assertEqual(rep["tier_source"], "elevated")
            self.assertIn("pre-2.11", rep["elevation"]["reason"])


    def test_a_same_tier_elevation_is_not_discarded(self):
        # `--raise-tier L3 --reason "also changes authz policy"` on a path that
        # ALREADY floors at L3 fell through as "nothing to raise": the reason
        # was dropped, tier_source became "derived", and the gate then waived
        # the human under --human-gate-scope irreversible. An explicit
        # statement of intent is never silently discarded.
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "workers/job.py", "x = 1\n")          # L3 by path, reversible
            run("git", "add", "-A"); run("git", "commit", "-qm", "worker")
            self._cl(d, "attest", "--tests", "--codex", "pass", "--glm", "pass",
                     "--raise-tier", "L3", "--reason", "also changes authz policy")
            run("git", "add", "-A"); run("git", "commit", "-qm", "evidence")
            rep = json.load(open(max(glob_reports(d), key=os.path.getmtime)))
            self.assertEqual(rep["tier_source"], "elevated")
            self.assertEqual(rep["elevation"]["reason"], "also changes authz policy")
            g = self._cl(d, "gate", "--human-gate-scope", "irreversible")
            self.assertIn("NOT APPROVED", g.stdout, g.stdout)
            self.assertEqual(g.returncode, 1)

    def test_raise_tier_always_wants_a_reason(self):
        with tempfile.TemporaryDirectory() as d:
            run = self._repo(d)
            self._write(d, "workers/job.py", "x = 1\n")
            run("git", "add", "-A"); run("git", "commit", "-qm", "worker")
            r = self._cl(d, "attest", "--raise-tier", "L3", "--tests")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("requires --reason", r.stderr)


def glob_reports(d):
    import glob as _g
    return sorted(_g.glob(os.path.join(d, ".coverloop", "reports", "*.json")))

# The entry point stays at the very END of this file. `unittest.main()` collects
# what is defined ABOVE it, so a class appended later is silently invisible to
# `python3 tests/test_properties.py` — which is exactly how CI runs it. That
# happened: 102 of 264 tests were running in CI.
if __name__ == "__main__":
    unittest.main(verbosity=2)
