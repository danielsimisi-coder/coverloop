#!/usr/bin/env bash
# SessionStart hook — the invariant rules, and nothing else.
#
# Fires at every session start and after every compaction. Anything printed to
# stdout lands in the builder's context, so this text is read on every single
# session — which is exactly why it used to be the problem. The previous version
# was 6 KB and mentioned "gate" nineteen times: it told the builder to classify
# every task, pick a model, run two reviewers, re-attest, keep a ledger, run a
# self-test, and end every reply with a model line. Measured against real
# sessions, the model line was followed in about 1 reply in 100, and the rest
# turned the builder into a process manager. Coverloop's enforcement lives in
# `coverloop gate` (fail-closed, in code), not here. What remains is a pointer
# at that enforcement plus the handful of rules no command can enforce — never
# self-approve, never send secrets, irreversible actions are the operator's.
#
# The marker set is unchanged from the version this replaces — narrowing or
# widening WHICH projects get the contract is a separate decision from what the
# contract says.
set -u

in_protocol_project() {
  { [ -f CLAUDE.md ] && grep -q "PROTOCOL_VERSION\|Operating Contract" CLAUDE.md 2>/dev/null; } \
    || [ -f docs/OPERATING_CONTRACT.md ] || [ -f docs/MULTI_MODEL_PROTOCOL.md ]
}
in_protocol_project || exit 0

cat <<'EOF'
[coverloop] Build normally. Run the relevant tests as you go.
Before merge/deploy: `coverloop gate` must pass at HEAD. It fails closed on missing evidence — record that evidence with `coverloop attest` (tests, the independent reviews the tier requires, and a named human approval where one is required). Resolve what the gate names; do not work around it.
Never lower the deterministic risk floor. Never record an approval on a human's behalf. Never bypass a red test or a red review. Never send secrets, .env contents, keys, or PII to any model. Irreversible production actions — migrations, money paths, auth/RLS — are the operator's call, not yours.
EOF
exit 0
