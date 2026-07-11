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
        name = rng.choice(["API_KEY", "X_SECRET", "DB_PASSWORD", "AUTH_TOKEN", "MY_API_KEY", "z_passwd"])
        sep = rng.choice(["=", ": ", " = "])
        val = _rand(rng, b64 + "!@#", rng.randint(1, 30))
        return name + sep + val, "secret-assignment"
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
