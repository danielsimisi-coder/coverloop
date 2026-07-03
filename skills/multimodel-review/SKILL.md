---
name: multimodel-review
description: Review a focused diff or snippet with the multi-model loop — GLM (full-ZDR) red-team + MiniMax M3 (data_collection:deny) second auditor — then reconcile by convergence/divergence. Use when reviewing a non-trivial diff before Codex/merge, or to sanity-check the loop. Never send secrets or whole-repo context.
---

# Multi-model review (GLM + M3)

Reusable recipe for the cross-model review step. Use on a FOCUSED diff/snippet only.

## Steps
1. Stage focused text (`git diff -- <paths>` or a snippet). No `.env`/secrets/whole-repo (the CLIs also hard-block, but check).
   - **Give reviewers enough CONTEXT, not just the raw diff (v2.5).** A diff-only view is the #1 source of false positives — a model sees a call to `confirmClock()` in the diff, can't see its definition, and reports "undefined function." When a finding could hinge on code outside the hunk (a helper/type/import defined elsewhere), attach the FULL relevant file(s) alongside the diff — still T0–T2 only, still no secrets/whole-repo. Cost is a few tokens; it removes a whole class of phantom P0/P1s.
2. GLM red-team (full-ZDR):
   `git diff -- src | <glm-bin>/glm-redteam "Find concrete P0/P1 bugs. Be concise."`
3. M3 second auditor — L2/L3 only; M3 is a reasoning model so raise the budget:
   `git diff -- src | M3_MAX_TOKENS=12000 <glm-bin>/m3-audit "Find concrete bugs/risks. Be concise."`
   On L0/L1, skip M3 (one reviewer + tests is enough).
4. Reconcile (cross-model agreement): CONVERGENCE (both flag) = high-confidence must-fix; DIVERGENCE (only one) = verify against the code, that is where the 2nd model earns its keep — don't discard it.
5. Every finding is a hypothesis — verify against actual code before acting.
6. Confirm the audit trail: `tail -n 4 ~/.config/openrouter/egress.log` (hash only, privacy-routed).
7. **Log the review (v2.5, mandatory):** append ONE line to the project's `docs/REVIEW_LEDGER.md` under `## Review log`:
   `| YYYY-MM-DD | L<tier> | <reviewers used> | <N raised> | <accepted/rejected/needs-test counts> |`
   This feeds the quarterly right-size read (§10c) — a reviewer that can't show accepted findings gets subtracted.

## Rules
- Execution/tests are the PRIMARY gate; these auditors are secondary.
- Codex stays the mandatory independent diff reviewer; Daniel is the final gate.
- `<glm-bin>` = resolved helper dir (Arcade VPS: `/home/actdev/bin`; Mac: `/Users/danielsimantov/bin`). Resolve actual paths on other machines.

## v2.3 signal handling
- Agreement is a TRIAGE HINT, not a correctness oracle (models co-hallucinate). Verify any finding against the code / a failing test before it blocks.
- Every finding must cite file:line; bare agreement with no evidence = no signal.
- Check `docs/REVIEW_LEDGER.md` first; do NOT re-raise findings already marked rejected/won't-fix.
- Run `dep-check <pkg>` before suggesting/installing any new dependency.
- M3 is L3-only; on L0/L1 run Codex + tests only.
