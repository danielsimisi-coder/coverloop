<!-- ===================== MULTI-MODEL PROTOCOL — OPERATING CONTRACT (v2.6 base + v2.9 L3 evidence rows; v2.7–v2.8 content not yet resynced — see CLAUDE.md §13) =====================
     Inlined so the loop loads into ACTIVE context every session. This contract is AUTHORITATIVE
     for the code-review roster and supersedes any older/partial roster elsewhere in this repo
     (including AGENTS.md and docs/). Full protocol + depth: docs/MULTI_MODEL_PROTOCOL.md. -->

## ⚙️ Operating Contract — multi-model loop (READ & ENGAGE FIRST)

This project runs the **Coverloop Multi-Model Production Protocol** (current `PROTOCOL_VERSION` lives in `CLAUDE.md` / run `~/bin/protocol-selftest` — this contract stays version-agnostic so protocol bumps never require a project resync). **No model is an authority** — every finding is a claim, verified against code/tests/runtime. **Execution/tests are the PRIMARY correctness gate.**

**Roster (authoritative for CODE REVIEW):** Claude builds & coordinates · **Codex (GPT-5.6 Sol)** gates diffs (line-level correctness; effort EXPLICIT — high for L2, xhigh for L3, max for design red-team/deadlocks, never ultra for a gate) · **Kimi K3 (full-ZDR route, via the `glm-*` helpers; GLM-5.2 before 2026-09-23)** red-teams the **plan** before L3 code (advisory; not a gate on finished code since v2.12 — see `docs/DESIGN-NOTE-v2.12.md` for the measurements) · **MiniMax M3 (`data_collection:deny`, L3 only)** optional 2nd auditor — value is in *divergence* · **the operator** gates risky actions. Browser/UX-QA agents (e.g. Antigravity) are *complementary* (mobile/RTL/a11y/screenshots) — never substitutes for this review loop.

**Session Start — run FIRST and report it:**
1. State the current `PROTOCOL_VERSION` (from `CLAUDE.md`, or run `~/bin/protocol-selftest`) + `CONTRACT_VERSION` (this template: v2.6 base + v2.9 L3 evidence rows) + the roster above.
2. **Load memory:** read `docs/MEMORY.md` (git-tracked — machine-local Claude memory does NOT travel between the Mac / VPS sessions).
3. Read the Risk Map + `docs/REVIEW_LEDGER.md` (skip findings already marked rejected) and, where present, cross-check `docs/DECISIONS.md` / `STATE.md` before ranking any audit finding — "not in the file I happened to read" ≠ "not done"; mark findings **already-decided** vs **new**.
4. Resolve helper absolute paths (`glm-*` / `m3-*`) and record them in the Risk Map — Claude Code does NOT inherit the terminal `~/bin` PATH.
5. Restate the Task Card + risk tier before touching code.

**Risk → gates** (pick the lightest safe row; on a tie pick the heavier):

| Risk | Tests (primary) | Guard-break | Codex | GLM | M3 | the operator |
|------|-----------------|-------------|-------|-----|----|--------|
| **L0** trivial (copy/CSS) | quick check | – | – | – | – | – |
| **L1** normal (isolated fix/refactor) | relevant tests + typecheck | – | if behavior changed | – | – | – |
| **L2** product flow (no money/auth/migration) | + acceptance | if it adds a guard | **mandatory** | – | – | if launch-critical |
| **L3** money / auth·RLS / migration / deploy / secrets / worker | full suite | **mandatory** | **mandatory** | plan review, before code | optional (VPS) | **mandatory** |

**Guard-break (mandatory at L3):** for every safety guard the change adds or relies on — a permission check, a fail-closed branch, an idempotency key, a lock, a validation — break it on purpose and show that a test fails; restore it. A guard no test notices is not protected. Record the transcript: `coverloop attest --mutation pass --mutation-guards N --mutation-log <file>` (N = guards broken, ≥ 1 — a pass that broke nothing proves nothing) (`--mutation-findings N` = breaks nothing caught).

**Execute before review:** build, run the tests and the guard-break BEFORE sending the diff to Codex. The reviewer then reads code that already survived what a machine can check — in the field, a build caught what typecheck and tests missed, and a real run refuted what two cold reviewers had approved.

**Two-round rule:** if a P1 is still open after two Codex rounds, stop and redesign instead of starting a third round. The measured 7–16-round review tails were each a design error found late, not a review problem.

**Batch BY TIER:** a PR inherits its highest-tier item — never bundle a copy fix with a billing migration. Standing authorization ("keep going") covers L0–L2 product work; it never extends to L3 merges/applies.

**Privacy (tool-enforced, not prompt discipline):** NEVER send `.env` / secrets / keys / PII (T3) to any model. Reading your OWN database is still PII-bound — project only the non-PII columns you need (filter by PII in `WHERE`, never `SELECT` it); if a read is blocked for PII, reshape the query, don't bounce it back to the human. Route the most sensitive packets to GLM (full-ZDR) only.

**Mechanics that must actually fire (not optional):**
- **Off-policy review (the verified anti-bias rule):** the reviewer gets the change as a **cold artifact** (diff/files packet) in a **fresh session** — never "review your own work" inside the builder's conversation. Cross-lineage review (builder and gate from different model families) is the prudent L2/L3 default — a design assumption, not a proven requirement.
- End every meaningful task with **reflect-and-save** → write durable lessons to git-tracked `docs/MEMORY.md` and **commit them** (the loop's #1 reliability gap — easy to forget). **Negative results included** — "tried X, it's a no-op here, because Y" saves the next session real time.
- **Evidence provenance:** every "verified" claim states WHERE it ran — local vitest vs CI-only suites (pgTAP) vs a manual dashboard check. Ledger lines carry it too.
- **Git hygiene after squash-merges:** branch fresh from `main` after each merge (never stack on an unmerged branch), and verify `origin/main` actually advanced before trusting any background merge job.
- **Prod-matches-design check (L3 lanes):** prod infra that lives outside the repo (Fly/Vercel scale, env, machine count) drifts silently — before an L3 deploy/audit conclusion, LOOK at the control plane, don't assume the committed config is prod.
- Use the **`multimodel-review`** skill when reviewing an L2/L3 diff.
- **Two-strikes rule:** if you instruct the human to repeat the same manual workaround twice (host-swapping a link, re-requesting an email, hand-running a blocked query), STOP and fix the root cause.
- **Background-task hygiene:** don't leave background jobs running once you've read their output — reap them; keep AT MOST ONE dev/preview server and reuse it; clean up before you pause or declare done. (Long sessions piled up 50+ stale tasks.)
- **Sandbox/env failures** (e.g. Codex bwrap): fix the environment at root — never disable a tool's safety, never self-grant a sandbox/approval bypass.
- If this Operating Contract is ever missing from the loaded instructions, that is a **wiring bug** — flag it to the human operator.

<!-- ===================== END OPERATING CONTRACT ===================== -->
