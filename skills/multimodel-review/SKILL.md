---
name: multimodel-review
description: Review a focused diff or snippet with the multi-model loop — Kimi plan review through glm-* (ZDR) and optional MiniMax M3 (data_collection:deny) audit — then reconcile by convergence/divergence. Use for L3 design review before implementation, or a focused advisory audit, or to sanity-check the loop. Never send secrets or whole-repo context.
---

# Multi-model review (plan review + optional audit)

Reusable recipe for the cross-model review step. Use on a FOCUSED diff/snippet only.

## Steps
1. Stage focused text (`git diff -- <paths>` or a snippet). No `.env`/secrets/whole-repo (the CLIs also hard-block, but check).
   - **Give reviewers enough CONTEXT, not just the raw diff (v2.5).** A diff-only view is the #1 source of false positives — a model sees a call to `confirmClock()` in the diff, can't see its definition, and reports "undefined function." When a finding could hinge on code outside the hunk (a helper/type/import defined elsewhere), attach the FULL relevant file(s) alongside the diff — still T0–T2 only, still no secrets/whole-repo. Cost is a few tokens; it removes a whole class of phantom P0/P1s.
2. Before L3 implementation, review a sanitized DESIGN PACKET with the glm-* helper (currently Kimi K3; verify the ZDR route). A finished-code audit is advisory:
   `<glm-bin>/glm-redteam "Review this approved design for concrete risks and missing tests." < /absolute/path/to/approved-sanitized-plan.txt`
3. OPTIONAL M3 second auditor — L3 only, after explicit machine/privacy opt-in; M3 is a reasoning model so raise the budget:
   `git diff -- src | M3_MAX_TOKENS=12000 <glm-bin>/m3-audit "Find concrete bugs/risks. Be concise."`
   On L0/L1, skip M3 (one reviewer + tests is enough).
4. Reconcile (cross-model agreement): CONVERGENCE (both flag) = priority for verification, not proof; DIVERGENCE (only one) = verify against the code, that is where the 2nd model earns its keep — don't discard it.
5. Every finding is a hypothesis — verify against actual code before acting.
6. Confirm the audit trail: `tail -n 4 ~/.config/openrouter/egress.log` (hash only, privacy-routed).
7. **Log the review (v2.5, mandatory):** append ONE line to the project's `docs/REVIEW_LEDGER.md` under `## Review log`:
   `| YYYY-MM-DD | L<tier> | <reviewers used> | <N raised> | <accepted/rejected/needs-test counts> |`
   This feeds the quarterly right-size read (§10c) — a reviewer that can't show accepted findings gets subtracted.

## Evidence order
Run tests and the relevant guard-break experiments BEFORE the independent Codex
diff review. Capture the actual reviews and test results; never turn an unavailable
reviewer into a pass. At L3 the gate requires tests, Codex, guard-break and named
human approval. GLM/Kimi is advisory on completed code. M3 stays parked unless
explicitly approved; an unavailable optional auditor is disclosed, not required.

## Rules
- Execution/tests are the PRIMARY gate; these auditors are secondary.
- Codex stays the mandatory independent diff reviewer; the operator is the final gate.
- `<glm-bin>` = resolved helper dir (your VPS: `~/bin`; Mac: `~/bin`). Resolve actual paths on other machines.

## v2.3 signal handling
- Agreement is a TRIAGE HINT, not a correctness oracle (models co-hallucinate). Verify any finding against the code / a failing test before it blocks.
- Every finding must cite file:line; bare agreement with no evidence = no signal.
- Check `docs/REVIEW_LEDGER.md` first; do NOT re-raise findings already marked rejected/won't-fix.
- Run `dep-check <pkg>` before suggesting/installing any new dependency.
- M3 is optional and L3-only. Codex is required by the gate at L2+, not L0/L1.
