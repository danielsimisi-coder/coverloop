#!/usr/bin/env python3
"""Tests for `coverloop` (init/attest/gate) against real temporary git repos.

Run from the repo root:  python3 -m unittest discover -s tests -v
No third-party dependencies.
"""
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
        # committed report file rides along with a docs change -> still waivable
        self.commit(".coverloop/reports/old.json", "{}", "carry an old report")
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
        self.init_project()
        self.commit("README.md", "# docs\n")
        run(["attest", "--tier", "L2"], self.repo)
        code, out = self.gate_json(["--tier", "L2", "--base", self.base_sha])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
