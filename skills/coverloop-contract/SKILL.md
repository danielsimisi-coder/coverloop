---
name: coverloop-contract
description: The Coverloop operating contract — how much verification a change must earn before it ships. Load this BEFORE writing or reviewing code in a repo that uses Coverloop (has a .coverloop/ directory or a CLAUDE.md carrying PROTOCOL_VERSION), and whenever deciding a risk tier, choosing reviewers, or about to push/merge/migrate/deploy.
---

# The Coverloop contract

**One model reviewing its own work is a model grading its own exam.** This contract says how much independent verification a change has to earn before it ships — scaled to what the change can actually break.

Two rules override everything below:

1. **No model is an authority.** Every finding — yours or a reviewer's — is a *claim* to be checked against real code, tests, and runtime. When a test can settle it, run the test instead of adding another opinion.
2. **Never send secrets or PII to any model.** No `.env`, keys, tokens, credentials, customer data. Reading your own DB is PII-bound: select non-PII columns only.

## 1. Classify first — the tier is derived, not declared

```bash
coverloop classify          # explains the floor and why
```

Take the **MAX** of what it reports and your own judgement. It reads the paths that actually changed:

| Change touches | Floor |
|---|---|
| migrations · `.sql` · schema · auth/RLS · billing/payments · secrets/`.env` · CI-deploy config · workers/cron | **L3** |
| API routes · handlers · middleware · shared state · dependency manifests | **L2** |
| docs · stylesheets · repo metadata | **L0** |
| **anything unrecognised** | **L1 — never L0** |
| 10+ files changed | **at least L2** |

You may **raise** a tier — `attest --raise-tier <T> --reason "<why>"` records the reason in the report. **You may never lower a deterministic floor** — not to save tokens, not because it "looks fine". Unsure between two tiers? Take the heavier one.

## 2. What each tier must earn

| | Build | Tests (the deciding vote) | Independent diff gate | GLM red-team | Human gate |
|---|---|---|---|---|---|
| **L0** | direct | quick check | – | – | – |
| **L1** | focused | relevant tests + typecheck + lint + build | if behaviour changed | – | – |
| **L2** | plan first | + acceptance tests | **required** | if subtle or the gate flags | if launch-critical |
| **L3** | design first | full suite + the right *kind* of test | **required** (before *and* after fixes) | **required** | **required** before merge/apply/deploy |

**Execution is the primary correctness gate. Model review is secondary.** A reviewer's "looks good" never outranks a failing test.

## 3. Review must be off-policy

The reviewer sees the change as a **cold artifact** — a diff/files packet in a **fresh** session — never "review what you just wrote" inside the builder's own conversation. Fresh context removes most self-review bias; a **different model lineage** adds a second, smaller layer.

- **Diff gate:** the Codex CLI in a fresh session (`codex exec -m gpt-5.6-sol --sandbox read-only`), with reasoning effort set explicitly — high for L2, xhigh for L3. It defaults to low on its own; a lazy judge is worse than none.
- **Red-team / consistency audit:** `glm-redteam` / `glm-audit` (full ZDR).
- Demand **file:line** evidence. A bare verdict is noise.

**Privacy differs by reviewer, and it matters:** GLM is the only reviewer here on a strict zero-data-retention endpoint. M3 routes under `data_collection: deny` — a weaker promise — which is why it is optional and L3-only. Codex keeps the diff inside your own OpenAI account and never transits OpenRouter.

## 4. Record evidence, then let the gate decide

```bash
coverloop attest --tests                      # run + record the tests (tier derived)
coverloop attest --codex-log review.txt       # attach the review you already ran
coverloop gate --min-tier "$(coverloop classify --quiet)"
```

- Evidence is bound to the **commit**. Any code change after attesting invalidates it — **re-attest at HEAD**, never push stale evidence.
- Attach the real transcript (`--codex-log` / `--glm-log`). A bare self-attested verdict is the weak path and the gate labels it as such.
- **L3 `--approve` only when the operator named THIS action.** A generic "go ahead" is not an approval — ask for the named gate.

## 5. Stop conditions

- **Converged** when: tests green · zero unresolved P0/P1 · every finding classified · the last review pass found nothing new. Then stop — remaining P2s become follow-ups.
- **Round cap:** 2 gate rounds and 2 red-team rounds per task. Repeated *real* findings past the cap means the change is **too big to review well** — split it, don't grind a fifth round.
- The cap **never** converts an open P0/P1 into a pass. Cap reached with a blocker = **STOP and escalate to the operator**.

## 6. Close the loop

End a meaningful task with a short report: what changed, what did **not**, tests run, reviewer verdicts, what's still risky, what gate is still required, and whether it is safe to pause. Never leave the reader thinking something is live when it is only merged.

**If the reply ends with a next task, close with one line:** `▸ Next: <task> → <model> · <effort> effort — <why>`. L0 → Haiku/low · L1 → Sonnet/medium · L2 → Sonnet/high · L3 → Opus/high–xhigh. Classify the risk first, then read the model off the tier.

---

**Depth:** the full contract (roster detail, deployment/migration safety, environment parity, token discipline, hard boundaries) lives in this plugin's `CLAUDE.md`, and the gate's threat model in `docs/GATE.md`. Read them when a decision actually turns on the detail — this page is what governs day to day.

**Honest limit:** Coverloop does not make AI coding safe. It makes unsafe assumptions harder to ship unnoticed. Every reviewer here misses things; what changes is how many independent checks a bug must defeat, and whether the evidence that it was checked is still true at the commit you ship.
