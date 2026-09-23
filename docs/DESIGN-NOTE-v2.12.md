# Design note — v2.12: guard-break evidence replaces post-code GLM at L3

**Status:** acceptance criteria fixed BEFORE implementation (2026-09-23).

## Why (measured, 2026-06 → 2026-09, ~6,200 operator messages, ~2,400 Codex
and ~1,700 GLM runs, ~1,700 Coverloop reports across the fleet)

- GLM failed operationally on roughly one run in five (truncated output,
  secret-filter refusals, quota/rate) versus ~2% for Codex; where its P0/P1
  findings were adjudicated in a REVIEW_LEDGER they were mostly false
  positives caused by code outside the packet. It did contribute minor
  (P2/P3, test-rigor) items.
- The long review tails (7–16 Codex rounds) were design errors discovered late
  — the place GLM historically helped is the PLAN, before code exists.
- The check that caught what no reviewer caught was execution: building,
  running, and deliberately breaking each safety guard to prove a test fails.
  Projects already doing it (reviewer-built mutants) had it outside the gate.

## What changes

1. New evidence record `mutation` (guard-break): same shape and same transcript
   rules as a reviewer record. `findings_open` = guards whose deliberate
   breakage NO test caught (surviving mutants). Recorded with
   `attest --mutation pass|fail [--mutation-findings N] [--mutation-log FILE | --mutation-run CMD]`.
2. At L3 the gate requires `mutation` (pass, 0 surviving) instead of `glm`.
3. `glm`, when present, is printed as ADVISORY at L2/L3 — never hidden, never
   failing the verdict. Its role moves to reviewing the plan before L3 code.
4. Codex, tests and the human gate are unchanged. L0/L1/L2 requirements are
   unchanged.
5. Operating contract gains two rules (text only, no tool counter):
   execution before review (build + tests + guard-break, then Codex), and the
   two-round rule (a P1 still open after two Codex rounds → stop and redesign).

## Acceptance criteria (fixed in advance; the release is done when all hold)

- C1. L3 with tests pass + codex pass/0 + mutation pass/0 + human approval →
  PASS, with no `glm` record present.
- C2. L3 with everything except `mutation` → FAIL; the failing check is named
  `mutation`.
- C3. `mutation` fail, or pass with findings_open > 0 → FAIL.
- C4. `mutation` claiming `attached`/`captured` with a missing, tampered or
  replayed transcript → FAIL (identical rigor to Codex).
- C5. A `glm` record that fails or has open findings does not change the
  verdict; the gate output still prints it, labelled advisory, with its status
  and count.
- C6. L0/L1/L2 behaviour unchanged: L2 needs Codex only; neither `mutation` nor
  `glm` is required below L3.
- C7. `--require-transcript/--require-captured` and `--require-executed` apply
  to `mutation` at L3.
- C8. Report validation: `mutation.status` ∈ {pass, fail};
  `mutation.findings_open` a non-negative int (bool rejected).
  `<sha>.mutation.log` is an exact evidence-artifact shape (same exemption and
  same whitespace-smuggling defence as `.codex.log`/`.glm.log`).
- C9. Every existing test passes; tests that asserted GLM is mandatory at L3
  are changed deliberately and listed in the CHANGELOG.
- C10. The change is itself guard-broken: removing the L3 `mutation`
  requirement, accepting a surviving mutant, or letting `glm` fail the verdict
  each makes at least one test fail. Results recorded as this release's own
  `mutation` evidence.

## Review budget

Codex (GPT-5.6 Sol, xhigh), at most two rounds. After round two only defects
that let the gate pass WITHOUT the required evidence are fixed; everything
else is recorded and deferred. No GLM round on this change (consistent with
the change itself).

## v2.12.1 — close the vacuous-pass gap (criteria fixed before implementation, 2026-09-23)

Found by the plan-review pilot (all four models): nothing says how many guards
a guard-break run covered, so `mutation pass, 0 surviving` is satisfiable by
breaking nothing. Smallest fail-closed fix: the record states the count.

**What this does and does not do (Codex r1, narrowed on purpose):** the count
is an ATTESTED claim, at the same trust level as `findings_open` and every
other value the attester writes — the gate cannot read a free-form transcript
and verify it. It turns a SILENT empty pass into an EXPLICIT statement ("I
broke N guards"): a sloppy session can no longer pass by omission, only by
writing a false number, and the number sits next to the transcript a reviewer
can check. It does not make the count verified.

- G1. `attest --mutation pass` without `--mutation-guards N` (N ≥ 1) is refused.
- G2. The gate passes `mutation` only if status is pass, `findings_open` is 0,
  and `guards_broken` is an int ≥ 1 (bool rejected). A pass record without
  `guards_broken` (e.g. written by v2.12.0) FAILS, and says to re-attest with
  `--mutation-guards`.
- G3. `findings_open` > `guards_broken` is malformed → FAIL (can't have more
  survivors than guards broken).
- G4. `--mutation fail` does not require `--mutation-guards`; if given it is
  validated the same way.
- G5. The gate prints the count: `N guards broken, surviving (uncaught) breaks: M`.
- G6. Codex/GLM records and L0–L2 are unaffected.
- G7. Every existing test passes (tests that attest `--mutation pass` gain
  `--mutation-guards`, listed in the CHANGELOG).
- G8. Guard-broken: removing each new check makes a test fail.

Also in this release: the reviewer helpers' default model becomes Kimi K3
(`GLM_MODEL` still overrides), per the same pilot.
