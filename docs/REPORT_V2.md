# CoverLoop report/v2 — external-authority L3 approval

`coverloop-report/v2` introduces an explicit authority boundary for L3 approval.
It exists to remove a structural flaw in report/v1: a report travelling inside a
PR can currently contain the same `human_gate` object that the L3 gate later
accepts.  Attribution is useful audit text, but PR-authored attribution is not
an authorization primitive.

## Protocol invariant

A v2 report represents approval as a **closed sum type**:

```text
approval = human | delegated_policy
```

The variants are mutually exclusive.  Unknown keys are rejected.  There is no
fallback from malformed v2 authority to v1 `human_gate`, no opaque
`delegated_policy` extension, and no synthetic owner-approval compatibility
path.

The report contains only an authorization reference and the SHA-256 digest of
the exact signed authorization bytes.  A `delegated_policy` variant additionally
binds the policy id, version, and digest.

The authoritative material is deliberately **not in the PR**:

- OpenSSH signature: external file, required to resolve outside the repository;
- OpenSSH `allowed_signers`: external trust root, required to resolve outside the
  repository;
- expected signer principal: supplied by the trusted caller, never selected by
  report JSON;
- expected task id: supplied by the trusted caller, never inferred from the PR.

The fixed OpenSSH signature namespace is `coverloop-l3-approval/v2`.

## Signed authorization

The exact UTF-8 bytes of the authorization JSON are signed.  The verifier first
checks that their SHA-256 matches `approval.authorization_sha256`, then validates
all semantic bindings, and only then verifies the signature against the external
trust root.

Both variants bind:

- authorization reference;
- approval kind;
- exact subject commit SHA;
- exact subject task id;
- decision (`approve` only);
- expected signer principal;
- issued-at and expires-at timestamps;
- nonce.

`delegated_policy` additionally binds `policy_id`, `policy_version`, and
`policy_digest` in both the report and the signed authorization.

## Why the signature is over exact bytes

The verifier does not invent a second JSON canonicalization protocol.  The
report hash binds the exact authorization bytes, and OpenSSH signs those same
bytes.  Reformatting, editing, or replacing the authorization changes the hash
and invalidates the signature.  This keeps the authority preimage unambiguous
without claiming RFC 8785 semantics that this feature does not implement.

## CLI

```bash
python3 bin/coverloop_report_v2.py .coverloop/reports/<sha>.json \
  --authorization /trusted/authorizations/<id>.json \
  --signature /trusted/signatures/<id>.sig \
  --allowed-signers /trusted/roots/l3_allowed_signers \
  --repo-root "$PWD" \
  --principal coverloop-owner \
  --subject-task-id T-E0
```

The signature and trust-root paths must be absolute and external to
`--repo-root`.  Failure is closed and returns exit 1 with a JSON reason.

## Scope and migration

This is the upstream **report/v2 authority kernel**.  It intentionally does not
silently change the behavior of the legacy report/v1 CLI.  Consumers opt into
v2 and must call this verifier from their trusted attestation boundary.  A later
migration may make v2 the default report format only after compatibility and
qualification work proves that doing so does not weaken existing gates.

That separation is intentional: representation and cryptographic authority are
implemented here; broad rollout, adversarial qualification, revocation policy,
and default migration are separate lifecycle decisions rather than hidden side
effects of this protocol change.

## Threat model

This verifier prevents a PR author from creating authority merely by editing the
report.  A PR author can still copy or reference an authorization, but cannot
make it valid for another commit/task, change its delegated policy identity,
extend its expiry, choose another trusted principal, or replace its signing key
without a valid signature from an externally trusted signer.

The trusted environment remains responsible for protecting the external
signature/trust-root files, selecting the expected principal and task id, and
for any higher-level revocation/one-shot consumption policy.  Those controls are
not represented as PR-authored data by design.
