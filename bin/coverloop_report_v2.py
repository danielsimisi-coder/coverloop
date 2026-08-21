#!/usr/bin/env python3
"""CoverLoop report/v2 L3 approval verifier.

This module is deliberately separate from the legacy report/v1 gate.  It
implements the authority representation needed for delegated L3 without
pretending that a PR-authored string is approval.

Authority model:
  * report/v2 contains a CLOSED approval sum type: human | delegated_policy.
  * the report carries only a reference + digest of an authorization document.
  * the authorization is verified byte-for-byte with OpenSSH signatures.
  * the signature and allowed-signers trust root MUST live outside the repo.
  * the trusted caller supplies the expected signer principal and task id.

No field inside the PR selects a public key, trust root, or signer identity.
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


REPORT_SCHEMA = "coverloop-report/v2"
AUTH_SCHEMA = "coverloop-l3-authorization/v1"
SIGNATURE_NAMESPACE = "coverloop-l3-approval/v2"
TIERS = ("L0", "L1", "L2", "L3")
KINDS = ("human", "delegated_policy")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_REPORT_KEYS = {
    "schema", "commit", "risk_tier", "created_at",
    "tests", "codex", "glm", "approval",
}
_HUMAN_APPROVAL_KEYS = {
    "kind", "authorization_ref", "authorization_sha256",
}
_DELEGATED_APPROVAL_KEYS = _HUMAN_APPROVAL_KEYS | {
    "policy_id", "policy_version", "policy_digest",
}
_AUTH_COMMON_KEYS = {
    "schema", "authorization_ref", "kind", "subject_task_id", "subject_sha",
    "decision", "principal", "issued_at", "expires_at", "nonce",
}
_AUTH_DELEGATED_KEYS = _AUTH_COMMON_KEYS | {
    "policy_id", "policy_version", "policy_digest",
}


class VerificationError(ValueError):
    """Fail-closed protocol rejection with a user-readable reason."""


def _require(condition, message):
    if not condition:
        raise VerificationError(message)


def _is_nonempty_string(value, max_len=512):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= max_len


def _require_exact_keys(obj, expected, where):
    _require(isinstance(obj, dict), "%s must be an object" % where)
    got = set(obj.keys())
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    _require(not missing, "%s missing keys: %s" % (where, ", ".join(missing)))
    _require(not extra, "%s has unknown keys: %s" % (where, ", ".join(extra)))


def _parse_time(value, field):
    _require(_is_nonempty_string(value, 64), "%s must be a timestamp string" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise VerificationError("%s is not RFC3339/ISO-8601" % field)
    _require(parsed.tzinfo is not None, "%s must include a timezone" % field)
    return parsed.astimezone(_dt.timezone.utc)


def _load_json_bytes(path, label):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise VerificationError("cannot read %s: %s" % (label, exc))
    _require(bool(raw), "%s is empty" % label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise VerificationError("%s must be UTF-8 JSON" % label)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerificationError("%s is invalid JSON: %s" % (label, exc))
    _require(isinstance(data, dict), "%s root must be an object" % label)
    return raw, data


def _inside(path, root):
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _external_regular_file(path, repo_root, label):
    _require(os.path.isabs(path), "%s path must be absolute" % label)
    _require(not os.path.islink(path), "%s may not be a symlink" % label)
    _require(os.path.isfile(path), "%s is not a regular file" % label)
    _require(not _inside(path, repo_root),
             "%s must live outside the repository/PR trust boundary" % label)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise VerificationError("cannot read %s: %s" % (label, exc))


def validate_report(report):
    _require_exact_keys(report, _REPORT_KEYS, "report")
    _require(report.get("schema") == REPORT_SCHEMA,
             "report.schema must be %r" % REPORT_SCHEMA)
    _require(bool(_HEX40.match(str(report.get("commit", "")))),
             "report.commit must be a lowercase 40-hex git SHA")
    _require(report.get("risk_tier") in TIERS, "report.risk_tier is invalid")
    _require(report.get("risk_tier") == "L3",
             "report/v2 delegated approval verifier is only authoritative for L3")

    approval = report.get("approval")
    _require(isinstance(approval, dict), "report.approval must be an object")
    kind = approval.get("kind")
    _require(kind in KINDS, "report.approval.kind must be human or delegated_policy")
    expected = _HUMAN_APPROVAL_KEYS if kind == "human" else _DELEGATED_APPROVAL_KEYS
    _require_exact_keys(approval, expected, "report.approval[%s]" % kind)
    _require(_is_nonempty_string(approval.get("authorization_ref"), 256),
             "approval.authorization_ref must be a non-empty string")
    _require(bool(_HEX64.match(str(approval.get("authorization_sha256", "")))),
             "approval.authorization_sha256 must be lowercase 64-hex")

    if kind == "delegated_policy":
        _require(_is_nonempty_string(approval.get("policy_id"), 128),
                 "delegated approval.policy_id must be non-empty")
        _require(_is_nonempty_string(approval.get("policy_version"), 128),
                 "delegated approval.policy_version must be non-empty")
        _require(bool(_HEX64.match(str(approval.get("policy_digest", "")))),
                 "delegated approval.policy_digest must be lowercase 64-hex")
    return approval


def validate_authorization(auth, expected_kind, expected_sha, expected_task_id,
                           expected_principal, now):
    _require(isinstance(auth, dict), "authorization must be an object")
    _require(auth.get("kind") in KINDS,
             "authorization.kind must be human or delegated_policy")
    expected_keys = (_AUTH_COMMON_KEYS if auth.get("kind") == "human"
                     else _AUTH_DELEGATED_KEYS)
    _require_exact_keys(auth, expected_keys, "authorization[%s]" % auth.get("kind"))
    _require(auth.get("schema") == AUTH_SCHEMA,
             "authorization.schema must be %r" % AUTH_SCHEMA)
    _require(auth.get("kind") == expected_kind,
             "authorization kind does not match report approval variant")
    _require(auth.get("decision") == "approve",
             "authorization.decision must be exactly 'approve'")
    _require(auth.get("subject_sha") == expected_sha,
             "authorization subject_sha does not match report commit")
    _require(auth.get("subject_task_id") == expected_task_id,
             "authorization subject_task_id does not match trusted caller context")
    _require(auth.get("principal") == expected_principal,
             "authorization principal does not match trusted caller context")
    _require(_is_nonempty_string(auth.get("authorization_ref"), 256),
             "authorization_ref must be non-empty")
    _require(_is_nonempty_string(auth.get("nonce"), 256)
             and len(auth.get("nonce")) >= 16,
             "authorization.nonce must contain at least 16 characters")

    issued = _parse_time(auth.get("issued_at"), "authorization.issued_at")
    expires = _parse_time(auth.get("expires_at"), "authorization.expires_at")
    _require(expires > issued, "authorization.expires_at must be after issued_at")
    _require(issued <= now, "authorization is not valid yet")
    _require(expires > now, "authorization is expired")

    if expected_kind == "delegated_policy":
        _require(_is_nonempty_string(auth.get("policy_id"), 128),
                 "authorization.policy_id must be non-empty")
        _require(_is_nonempty_string(auth.get("policy_version"), 128),
                 "authorization.policy_version must be non-empty")
        _require(bool(_HEX64.match(str(auth.get("policy_digest", "")))),
                 "authorization.policy_digest must be lowercase 64-hex")
    return auth


def _verify_ssh_signature(payload, signature_bytes, allowed_signers_bytes, principal):
    ssh_keygen = shutil.which("ssh-keygen")
    _require(bool(ssh_keygen), "ssh-keygen is required for report/v2 signature verification")
    with tempfile.TemporaryDirectory(prefix="coverloop-v2-verify-") as td:
        sig = os.path.join(td, "authorization.sig")
        allowed = os.path.join(td, "allowed_signers")
        with open(sig, "wb") as fh:
            fh.write(signature_bytes)
        with open(allowed, "wb") as fh:
            fh.write(allowed_signers_bytes)
        try:
            proc = subprocess.run(
                [ssh_keygen, "-Y", "verify", "-f", allowed,
                 "-I", principal, "-n", SIGNATURE_NAMESPACE, "-s", sig],
                input=payload, capture_output=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerificationError("signature verifier failed to execute: %s" % exc)
    _require(proc.returncode == 0,
             "authorization signature is invalid or signer is not in the external trust root")


def verify(report_path, authorization_path, signature_path, allowed_signers_path,
           repo_root, expected_principal, expected_task_id, now=None):
    repo_root = os.path.realpath(repo_root)
    _require(os.path.isdir(repo_root), "repo_root must be an existing directory")
    _require(_is_nonempty_string(expected_principal, 256),
             "expected_principal must be supplied by the trusted caller")
    _require(_is_nonempty_string(expected_task_id, 256),
             "expected_task_id must be supplied by the trusted caller")

    _, report = _load_json_bytes(report_path, "report")
    approval = validate_report(report)
    auth_bytes, auth = _load_json_bytes(authorization_path, "authorization")

    digest = hashlib.sha256(auth_bytes).hexdigest()
    _require(digest == approval.get("authorization_sha256"),
             "authorization bytes do not match approval.authorization_sha256")
    _require(auth.get("authorization_ref") == approval.get("authorization_ref"),
             "authorization_ref does not match report")

    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    elif isinstance(now, str):
        now = _parse_time(now, "now")
    else:
        _require(isinstance(now, _dt.datetime) and now.tzinfo is not None,
                 "now must be timezone-aware")
        now = now.astimezone(_dt.timezone.utc)

    validate_authorization(
        auth, approval["kind"], report["commit"], expected_task_id,
        expected_principal, now,
    )

    if approval["kind"] == "delegated_policy":
        for field in ("policy_id", "policy_version", "policy_digest"):
            _require(auth.get(field) == approval.get(field),
                     "%s does not match signed authorization" % field)

    # These two artifacts are the authority boundary.  Copy their bytes only
    # after proving their real paths are outside the repository.  The verifier
    # never reads a public key, signer identity, or trust root from report JSON.
    signature_bytes = _external_regular_file(
        signature_path, repo_root, "signature")
    allowed_signers_bytes = _external_regular_file(
        allowed_signers_path, repo_root, "allowed_signers trust root")
    _require(bool(signature_bytes), "signature file is empty")
    _require(bool(allowed_signers_bytes), "allowed_signers trust root is empty")

    _verify_ssh_signature(
        auth_bytes, signature_bytes, allowed_signers_bytes, expected_principal)

    return {
        "schema": "coverloop-l3-verification/v1",
        "verdict": "pass",
        "report_schema": REPORT_SCHEMA,
        "commit": report["commit"],
        "approval_kind": approval["kind"],
        "authorization_ref": approval["authorization_ref"],
        "authorization_sha256": digest,
        "principal": expected_principal,
        "subject_task_id": expected_task_id,
        "signature_namespace": SIGNATURE_NAMESPACE,
        "trust_root_source": "external",
    }


def _main(argv=None):
    p = argparse.ArgumentParser(
        description="Verify report/v2 L3 human/delegated approval against external SSH authority")
    p.add_argument("report", help="coverloop-report/v2 JSON file")
    p.add_argument("--authorization", required=True,
                   help="signed authorization JSON whose exact bytes are hash-bound by the report")
    p.add_argument("--signature", required=True,
                   help="ABSOLUTE path to OpenSSH signature outside the repository")
    p.add_argument("--allowed-signers", required=True,
                   help="ABSOLUTE path to OpenSSH allowed_signers trust root outside the repository")
    p.add_argument("--repo-root", required=True,
                   help="repository root used to enforce the external-authority boundary")
    p.add_argument("--principal", required=True,
                   help="expected signer principal supplied by the trusted caller")
    p.add_argument("--subject-task-id", required=True,
                   help="expected task id supplied by the trusted caller")
    p.add_argument("--now",
                   help="verification time for deterministic tests (RFC3339); default current UTC")
    args = p.parse_args(argv)
    try:
        result = verify(
            args.report, args.authorization, args.signature, args.allowed_signers,
            args.repo_root, args.principal, args.subject_task_id, args.now,
        )
    except VerificationError as exc:
        print(json.dumps({
            "schema": "coverloop-l3-verification/v1",
            "verdict": "fail",
            "reason": str(exc),
        }, indent=2), file=sys.stdout)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
