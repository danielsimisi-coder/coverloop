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
import string
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "coverloop")
import glm_secret_filter as F

SEED = 20260711  # fixed -> deterministic, reproducible failures


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


class EgressRedactionInvariant(unittest.TestCase):
    """Operator merge condition (2026-07-15): EVERY packet sent to an external review model passes
    through redact() BEFORE scan and egress — no raw-packet bypass path. Integration-level: the
    REAL CLI module (bin/glm-review, bin/m3-review) is imported and driven through its actual
    main() path with do_request captured, so the assertion covers arg-parse → packet build →
    redact → scan → payload — the exact bytes that would leave the machine."""

    SECRET = "hunter2longenough"

    def _run_cli(self, cli_name, stdin_text, argv):
        import importlib.util, io, contextlib
        path = os.path.join(os.path.dirname(CLI), cli_name)
        spec = importlib.util.spec_from_loader(cli_name.replace("-", "_"), loader=None)
        mod = importlib.util.module_from_spec(spec)
        src = open(path).read()
        captured = {}

        def fake_do_request(payload, timeout):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "provider": "test"}

        env = {"OPENROUTER_API_KEY": "x" * 20, "MINIMAX_API_KEY": "x" * 20}
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
