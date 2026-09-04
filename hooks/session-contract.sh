#!/usr/bin/env bash
# SessionStart hook — the invariant rules, and nothing else.
#
# Fires at every session start and after every compaction. Anything printed to
# stdout lands in the builder's context, so this text is read on every single
# session — which is exactly why it used to be the problem. The previous version
# was 6 KB and mentioned "gate" nineteen times: it told the builder to classify
# every task, pick a model, run two reviewers, re-attest, keep a ledger, run a
# self-test, and end every reply with a model line. Measured against real
# sessions, the model line was followed 1% of the time and the rest turned the
# builder into a process manager. Coverloop's enforcement lives in `coverloop
# check` (fail-closed, in code), not in prose. Prose here is only for the rules
# that no command can enforce.
set -u

in_protocol_project() {
  { [ -f CLAUDE.md ] && grep -q "PROTOCOL_VERSION\|Operating Contract" CLAUDE.md 2>/dev/null; } \
    || [ -f docs/OPERATING_CONTRACT.md ] || [ -d .coverloop ]
}
in_protocol_project || exit 0

cat <<'EOF'
[coverloop] Build normally. Run the relevant tests as you go.
Before merge/deploy: `coverloop check` — it derives the risk tier, runs tests and the required independent reviews, binds the evidence to HEAD, and prints SAFE TO MERGE or one STOP reason. Resolve the STOP; do not work around it.
Never lower the deterministic risk floor. Never record an approval on a human's behalf. Never bypass a red test or a red review. Never send secrets, .env contents, keys, or PII to any model. Irreversible production actions (migrations, money, auth/RLS, deploys) are Daniel's call.
EOF
exit 0
