<!-- ===================== MULTI-MODEL PROTOCOL — OPERATING CONTRACT (v2.5) =====================
     Inlined so the loop loads into ACTIVE context every session. This contract is AUTHORITATIVE
     for the code-review roster and supersedes any older/partial roster elsewhere in this repo
     (including AGENTS.md and docs/). Full protocol + depth: docs/MULTI_MODEL_PROTOCOL.md. -->

## ⚙️ Operating Contract — multi-model loop (READ & ENGAGE FIRST)

This project runs the **Coverloop Multi-Model Production Protocol** (current `PROTOCOL_VERSION` lives in `CLAUDE.md` / run `~/bin/protocol-selftest` — this contract stays version-agnostic so protocol bumps never require a project resync). **No model is an authority** — every finding is a claim, verified against code/tests/runtime. **Execution/tests are the PRIMARY correctness gate.**

**Roster (authoritative for CODE REVIEW):** Claude builds & coordinates · **Codex** gates diffs (line-level correctness) · **GLM-5.2 (full-ZDR)** red-teams architecture/implementation + audits consistency · **MiniMax M3 (`data_collection:deny`, L3 only)** optional 2nd auditor — value is in *divergence* · **the operator** gates risky actions. Browser/UX-QA agents (e.g. Antigravity) are *complementary* (mobile/RTL/a11y/screenshots) — never substitutes for this review loop.

**Session Start — run FIRST and report it:**
1. State the current `PROTOCOL_VERSION` (from `CLAUDE.md`, or run `~/bin/protocol-selftest`) + `CONTRACT_VERSION` v2.5 + the roster above.
2. **Load memory:** read `docs/MEMORY.md` (git-tracked — machine-local Claude memory does NOT travel between the Mac / VPS sessions).
3. Read the Risk Map + `docs/REVIEW_LEDGER.md` (skip findings already marked rejected).
4. Resolve helper absolute paths (`glm-*` / `m3-*`) and record them in the Risk Map — Claude Code does NOT inherit the terminal `~/bin` PATH.
5. Restate the Task Card + risk tier before touching code.

**Risk → gates** (pick the lightest safe row; on a tie pick the heavier):

| Risk | Tests (primary) | Codex | GLM | M3 | the operator |
|------|-----------------|-------|-----|----|--------|
| **L0** trivial (copy/CSS) | quick check | – | – | – | – |
| **L1** normal (isolated fix/refactor) | relevant tests + typecheck | if behavior changed | – | – | – |
| **L2** product flow (no money/auth/migration) | + acceptance | **mandatory** | if subtle | – | if launch-critical |
| **L3** money / auth·RLS / migration / deploy / secrets / worker | full suite | **mandatory** | **mandatory** (pre + post) | optional (VPS) | **mandatory** |

**Privacy (tool-enforced, not prompt discipline):** NEVER send `.env` / secrets / keys / PII (T3) to any model. Reading your OWN database is still PII-bound — project only the non-PII columns you need (filter by PII in `WHERE`, never `SELECT` it); if a read is blocked for PII, reshape the query, don't bounce it back to the human. Route the most sensitive packets to GLM (full-ZDR) only.

**Mechanics that must actually fire (not optional):**
- End every meaningful task with **reflect-and-save** → write durable lessons to git-tracked `docs/MEMORY.md` and **commit them** (the loop's #1 reliability gap — easy to forget).
- Use the **`multimodel-review`** skill when reviewing an L2/L3 diff.
- **Two-strikes rule:** if you instruct the human to repeat the same manual workaround twice (host-swapping a link, re-requesting an email, hand-running a blocked query), STOP and fix the root cause.
- **Background-task hygiene:** don't leave background jobs running once you've read their output — reap them; keep AT MOST ONE dev/preview server and reuse it; clean up before you pause or declare done. (Long sessions piled up 50+ stale tasks.)
- **Sandbox/env failures** (e.g. Codex bwrap): fix the environment at root — never disable a tool's safety, never self-grant a sandbox/approval bypass.
- If this Operating Contract is ever missing from the loaded instructions, that is a **wiring bug** — flag it to the human operator.

<!-- ===================== END OPERATING CONTRACT ===================== -->
