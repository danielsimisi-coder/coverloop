#!/usr/bin/env python3
"""Adversarial tests for coverloop-report/v2 approval authority."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import coverloop_report_v2 as v2  # noqa: E402


NOW = "2026-08-21T08:00:00+00:00"
ISSUED = "2026-08-21T07:00:00+00:00"
EXPIRES = "2026-08-21T09:00:00+00:00"
SHA = "a" * 40
TASK = "T-E0-fixture"
PRINCIPAL = "coverloop-owner"
POLICY_ID = "deliveryos-l3"
POLICY_VERSION = "2026-08-21"
POLICY_DIGEST = hashlib.sha256(b"delegated-policy-fixture").hexdigest()


def _write_json(path, obj):
    raw = (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(raw)
    return raw


def _run(args, **kwargs):
    return subprocess.run(args, capture_output=True, **kwargs)


class ReportV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssh = shutil.which("ssh-keygen")
        if not cls.ssh:
            raise unittest.SkipTest("ssh-keygen not installed")

    def setUp(self):
        self.repo_tmp = tempfile.TemporaryDirectory(prefix="coverloop-v2-repo-")
        self.authority_tmp = tempfile.TemporaryDirectory(prefix="coverloop-v2-authority-")
        self.repo = self.repo_tmp.name
        self.authority = self.authority_tmp.name
        self.key = os.path.join(self.authority, "authority_key")
        made = _run([self.ssh, "-q", "-t", "ed25519", "-N", "", "-f", self.key])
        if made.returncode != 0:
            self.skipTest("ssh-keygen cannot create ed25519 keys on this runner")
        pub = _run([self.ssh, "-y", "-f", self.key], text=True)
        self.assertEqual(pub.returncode, 0, pub.stderr)
        self.allowed = os.path.join(self.authority, "allowed_signers")
        with open(self.allowed, "w", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (PRINCIPAL, pub.stdout.strip()))

    def tearDown(self):
        self.authority_tmp.cleanup()
        self.repo_tmp.cleanup()

    def _authorization(self, kind="human", **updates):
        obj = {
            "schema": v2.AUTH_SCHEMA,
            "authorization_ref": "authz:%s:001" % kind,
            "kind": kind,
            "subject_task_id": TASK,
            "subject_sha": SHA,
            "decision": "approve",
            "principal": PRINCIPAL,
            "issued_at": ISSUED,
            "expires_at": EXPIRES,
            "nonce": "0123456789abcdef0123456789abcdef",
        }
        if kind == "delegated_policy":
            obj.update({
                "policy_id": POLICY_ID,
                "policy_version": POLICY_VERSION,
                "policy_digest": POLICY_DIGEST,
            })
        obj.update(updates)
        return obj

    def _report(self, auth, auth_raw, **updates):
        approval = {
            "kind": auth["kind"],
            "authorization_ref": auth["authorization_ref"],
            "authorization_sha256": hashlib.sha256(auth_raw).hexdigest(),
        }
        if auth["kind"] == "delegated_policy":
            approval.update({
                "policy_id": auth["policy_id"],
                "policy_version": auth["policy_version"],
                "policy_digest": auth["policy_digest"],
            })
        obj = {
            "schema": v2.REPORT_SCHEMA,
            "commit": SHA,
            "risk_tier": "L3",
            "created_at": NOW,
            "tests": None,
            "codex": None,
            "glm": None,
            "approval": approval,
        }
        obj.update(updates)
        return obj

    def _sign(self, auth_path, key=None):
        key = key or self.key
        sig_path = auth_path + ".sig"
        try:
            os.unlink(sig_path)
        except FileNotFoundError:
            pass
        signed = _run([
            self.ssh, "-Y", "sign", "-f", key,
            "-n", v2.SIGNATURE_NAMESPACE, auth_path,
        ], text=True)
        if signed.returncode != 0:
            self.skipTest("ssh-keygen -Y sign unavailable: %s" % signed.stderr)
        self.assertTrue(os.path.isfile(sig_path))
        return sig_path

    def _case(self, kind="human", auth_updates=None):
        auth = self._authorization(kind, **(auth_updates or {}))
        auth_path = os.path.join(self.authority, "authorization.json")
        auth_raw = _write_json(auth_path, auth)
        report = self._report(auth, auth_raw)
        report_path = os.path.join(self.repo, "report.json")
        _write_json(report_path, report)
        sig = self._sign(auth_path)
        return report, report_path, auth, auth_path, sig

    def _verify(self, report_path, auth_path, sig, **kwargs):
        return v2.verify(
            report_path,
            auth_path,
            sig,
            kwargs.pop("allowed_signers", self.allowed),
            self.repo,
            kwargs.pop("principal", PRINCIPAL),
            kwargs.pop("task_id", TASK),
            kwargs.pop("now", NOW),
        )

    def test_human_signed_external_authority_passes(self):
        _, report_path, _, auth_path, sig = self._case("human")
        out = self._verify(report_path, auth_path, sig)
        self.assertEqual(out["verdict"], "pass")
        self.assertEqual(out["approval_kind"], "human")
        self.assertEqual(out["trust_root_source"], "external")

    def test_delegated_policy_signed_external_authority_passes(self):
        _, report_path, _, auth_path, sig = self._case("delegated_policy")
        out = self._verify(report_path, auth_path, sig)
        self.assertEqual(out["verdict"], "pass")
        self.assertEqual(out["approval_kind"], "delegated_policy")

    def test_human_variant_cannot_smuggle_delegated_fields(self):
        report, report_path, _, auth_path, sig = self._case("human")
        report["approval"]["policy_id"] = POLICY_ID
        _write_json(report_path, report)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_report_cannot_embed_trust_root_or_signature(self):
        report, report_path, _, auth_path, sig = self._case("human")
        report["trust_root"] = "attacker-controlled"
        _write_json(report_path, report)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

        del report["trust_root"]
        report["approval"]["signature"] = "synthetic"
        _write_json(report_path, report)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_signature_from_untrusted_key_is_rejected(self):
        _, report_path, _, auth_path, _ = self._case("human")
        rogue = os.path.join(self.authority, "rogue")
        made = _run([self.ssh, "-q", "-t", "ed25519", "-N", "", "-f", rogue])
        self.assertEqual(made.returncode, 0)
        rogue_sig = self._sign(auth_path, rogue)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, rogue_sig)

    def test_authorization_for_other_sha_is_rejected(self):
        _, report_path, _, auth_path, sig = self._case(
            "human", {"subject_sha": "b" * 40})
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_authorization_for_other_task_is_rejected(self):
        _, report_path, _, auth_path, sig = self._case(
            "human", {"subject_task_id": "T-OTHER"})
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_expired_authorization_is_rejected(self):
        _, report_path, _, auth_path, sig = self._case(
            "delegated_policy", {"expires_at": "2026-08-21T07:59:59+00:00"})
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_policy_binding_is_exact(self):
        report, report_path, _, auth_path, sig = self._case("delegated_policy")
        report["approval"]["policy_version"] = "attacker-version"
        _write_json(report_path, report)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_changed_authorization_bytes_break_report_digest(self):
        _, report_path, auth, auth_path, sig = self._case("human")
        auth["nonce"] = "fedcba9876543210fedcba9876543210"
        _write_json(auth_path, auth)
        sig = self._sign(auth_path)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig)

    def test_signature_and_trust_root_must_be_outside_repo(self):
        _, report_path, _, auth_path, sig = self._case("human")
        in_repo_allowed = os.path.join(self.repo, "allowed_signers")
        shutil.copyfile(self.allowed, in_repo_allowed)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig, allowed_signers=in_repo_allowed)

        in_repo_sig = os.path.join(self.repo, "authorization.sig")
        shutil.copyfile(sig, in_repo_sig)
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, in_repo_sig)

    def test_missing_signature_fails_closed(self):
        _, report_path, _, auth_path, _ = self._case("human")
        missing = os.path.join(self.authority, "missing.sig")
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, missing)

    def test_pr_cannot_choose_a_different_principal(self):
        _, report_path, _, auth_path, sig = self._case("human")
        with self.assertRaises(v2.VerificationError):
            self._verify(report_path, auth_path, sig, principal="somebody-else")


if __name__ == "__main__":
    unittest.main(verbosity=2)
