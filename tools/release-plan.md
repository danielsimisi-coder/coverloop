# Agensi release preparation — authorized local work only

Base: local v2.12.3 73e6dc4a03c6047f699318213fe11ddfacdfdbde.
Public v2.12.1: 469ca9055b0555b580422d538e8b8e688cc9ad03.
Six local commits preserve failed-review status across evidence commits and
reject malformed exit codes. Their complete implementation is retained in this
sanitary publication replay; original commits remain in a private local backup.
Risk: L3 (privacy, test execution consent, CI controls). No gate weakening.

Scope: metadata-only failure capture; explicit setup consent and offline install;
consistent current contract; one commercial orchestration skill using the MIT
engine by immutable commit+gate checksum, no embedded engine. Synthetic tests only.
Release version: 2.12.4 candidate. Product: Coverloop — Review to Merge, 1.0.0 candidate.

Validation: existing suites, synthetic clean install+project flow, fail-closed
review/evidence/L3 scenarios, logger privacy/filesystem regressions, real targeted
guard breaks, independent security review and independent skill forward test.
Never confuse fixture approval/fixture reviewers with actual release approval.
No secret-bearing or paid model call is authorized for this preparation. Kimi
live plan review, actual provider qualification, remote CI and platform validation
remain external checks; a local review is labelled with its actual provenance.

Launch remains blocked pending Joeri's delivery/OSS confirmation, approved push
of pinned engine, remote CI, named release approval, and actual Agensi testing.
Do not create a human approval record. No push, merge, production or purchase.

## Updated authorization — 2026-10-18
The operator authorized pushing only release/agensi-launch-prep after a full-history
privacy review and running GitHub CI. No main merge or publication is authorized.
Existing subscription CLI accounts may be tested with synthetic data; no re-login,
new account, paid API or purchase. Human L3 approval is still explicitly pending.
Private unpublished incident references and historical logs must be removed from
the publication ancestry, preserving the original work locally.
