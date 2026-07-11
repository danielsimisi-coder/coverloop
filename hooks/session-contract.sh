#!/usr/bin/env bash
# SessionStart hook — RE-INJECT the protocol's standing rules into context.
# Fires at every session start AND after every compaction (Claude Code re-runs
# SessionStart with source "compact"). Anything printed to stdout is added to
# Claude's context, so this re-states the binding rules as FRESH, high-attention
# context — fighting the drift where a long/compacted session "forgets" the protocol.
#
# Scoped: only fires in a protocol project (so it never injects noise into unrelated
# repos). Kept short on purpose (token economy) — the full contract lives in
# CLAUDE.md / docs/OPERATING_CONTRACT.md, which survive compaction on their own.
set -u

# Only speak up inside a project that uses this protocol.
in_protocol_project() {
  { [ -f CLAUDE.md ] && grep -q "PROTOCOL_VERSION\|Operating Contract" CLAUDE.md 2>/dev/null; } \
    || [ -f docs/OPERATING_CONTRACT.md ] || [ -f docs/MULTI_MODEL_PROTOCOL.md ]
}
in_protocol_project || exit 0

cat <<'EOF'
[v2.7.3 PROTOCOL — STANDING RULES reloaded into context; obey, do not drift]
- Code-review roster: Claude builds · Codex (GPT-5.6 Sol) gates diffs · GLM-5.2 (full-ZDR) red-teams+audits · M3 (data_collection:deny, L3 only) optional 2nd auditor · the human operator gates risk. Browser/UX-QA agents (e.g. Antigravity) are complementary, not substitutes.
- Execution/tests are the PRIMARY gate. No model is an authority — verify every finding against code/tests/runtime.
- Risk gates: L2 -> Codex MANDATORY. L3 (money/auth·RLS/migration/deploy/secrets/worker) -> Codex + GLM MANDATORY + the operator gate before merge/apply/deploy (M3 optional). Lightest safe row; tie -> heavier.
- ENFORCE, don't just claim (v2.7.2): if this repo has .coverloop/, record evidence with 'coverloop attest' and verify with 'coverloop gate' (fail-closed; exit 1 on missing tests/reviews/approval). Attach the review transcript you ALREADY produced with --codex-log/--glm-log (no re-run; a bare self-attested verdict is the WEAK path). RE-ATTEST AT HEAD after post-review fix commits — stale evidence fails the gate. Wire it as a required CI check. See docs/GATE.md.
- OFF-POLICY REVIEW (the verified anti-bias rule): the reviewer sees the change as a COLD ARTIFACT — a diff/files packet in a FRESH reviewer session (codex exec / a new subagent) — NEVER "review what you just wrote" inside the builder's own conversation. Fresh-context removes most self-review bias; cross-lineage (builder and gate from different model families) adds a second, smaller layer — prudent default for L2/L3, not proven law.
- Sol gate routing: codex exec -m gpt-5.6-sol --sandbox read-only with effort EXPLICIT every time (Sol defaults to LOW — a lazy judge): L2 gate -c model_reasoning_effort=\"high\" · L3 gate \"xhigh\" · design red-team / 2-round deadlock-break \"max\" · NEVER \"ultra\" for a gate (it auto-delegates to subagents; a judge must not outsource judgment, and it burns quota). Demand file:line-substantiated findings — a bare verdict is noise.
- L3 human-gate discipline: record 'attest --approve' ONLY when the operator named THIS specific action; a generic "go ahead"/"do what's best" is NOT an L3 approval — ask for the named gate.
- Privacy: NEVER send .env/secrets/keys/PII (T3) to any model. Reading your own DB is PII-bound — select only non-PII columns; if a read is blocked for PII, reshape the query, don't bounce it to the human.
- End each meaningful task with reflect-and-save -> append a durable lesson to git-tracked docs/MEMORY.md and commit it.
- Two-strikes: if you tell the human to repeat the same manual workaround twice, STOP and fix the root cause.
- Sandbox/env failure (e.g. Codex bwrap) -> fix the environment at root; never disable a tool's safety; never self-grant a sandbox/approval bypass.
- Background-task hygiene: don't leave background processes running once you've read their output. Keep AT MOST ONE dev/preview server and reuse it (kill the old one before starting a new one). Reap one-shot background jobs (Codex/GLM/M3/tests) when done, and clean up before you pause or declare done — don't let them pile up.
- Verify wiring once per session: run \$HOME/bin/protocol-selftest from the project root and report GREEN/FAILs.
- After each multi-model review, append one line to docs/REVIEW_LEDGER.md "## Review log" (date · tier · reviewers · findings · verdicts) — the quarterly right-size read depends on it.
- Re-read CLAUDE.md now. If it does not carry the Operating Contract (roster incl. GLM/M3 + this gate table), that's a WIRING BUG — flag it to the human operator.
EOF

# Dynamic wiring warnings — cheap local checks only (no git/network), surfacing
# the gaps that silently disarm the loop at the moment work starts.
if [ -d .coverloop ] && [ ! -f .claude/loop.conf ]; then
  echo "[WIRING GAP] .coverloop/ exists but .claude/loop.conf is missing — the Stop-hook test gate is OFF in this repo. Run the protocol repo's init-project.sh to finish wiring (new-repo bootstrap)."
fi
if [ -f docs/MEMORY.md ]; then
  N=$(grep -c '^- ' docs/MEMORY.md 2>/dev/null || echo 0)
  if [ "${N:-0}" -gt 30 ] 2>/dev/null; then
    echo "[WIRING GAP] docs/MEMORY.md has $N entries (cap ~30) — consolidate (merge/retire stale) before starting new work."
  fi
fi
exit 0
