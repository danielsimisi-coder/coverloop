---
name: multimodel-review
description: Review a focused diff or snippet with the multi-model loop — GLM (full-ZDR) red-team + MiniMax M3 (data_collection:deny) second auditor — then reconcile by convergence/divergence. Use when reviewing a non-trivial diff before Codex/merge, or to sanity-check the loop. Never send secrets or whole-repo context.
---

# Multi-model review (GLM + M3)

Reusable recipe for the cross-model review step. Use on a FOCUSED diff/snippet only.

## Steps
1. Stage focused text (`git diff -- <paths>` or a snippet). No `.env`/secrets/whole-repo (the CLIs also hard-block, but check).
2. GLM red-team (full-ZDR):
   `git diff -- src | <glm-bin>/glm-redteam "Find concrete P0/P1 bugs. Be concise."`
3. M3 second auditor — L2/L3 only; M3 is a reasoning model so raise the budget:
   `git diff -- src | M3_MAX_TOKENS=12000 <glm-bin>/m3-audit "Find concrete bugs/risks. Be concise."`
   On L0/L1, skip M3 (one reviewer + tests is enough).
4. Reconcile (cross-model agreement): CONVERGENCE (both flag) = high-confidence must-fix; DIVERGENCE (only one) = verify against the code, that is where the 2nd model earns its keep — don't discard it.
5. Every finding is a hypothesis — verify against actual code before acting.
6. Confirm the audit trail: `tail -n 4 ~/.config/openrouter/egress.log` (hash only, privacy-routed).

## Rules
- Execution/tests are the PRIMARY gate; these auditors are secondary.
- Codex stays the mandatory independent diff reviewer; Daniel is the final gate.
- `<glm-bin>` = resolved helper dir (Arcade VPS: `/home/actdev/bin`; Mac: `/Users/danielsimantov/bin`). Resolve actual paths on other machines.
