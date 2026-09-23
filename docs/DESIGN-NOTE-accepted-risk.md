# Design note — accepted risk: a third state, without rewriting evidence

**Status:** not built — **deferred until a real case is blocked** (Daniel,
2026-09-23: build it when a stuck FAIL actually stops work, not before; let
v2.12 prove itself in the field first). Scoped from a field report (2026-09-17) after a real
L3 run on a financial project, and checked against `bin/coverloop`. First
written 2026-09-17 against `725d630`; that commit was never pushed and the
checkout holding it was lost, so this is a **restoration (2026-09-23)**,
re-verified against `1cc1adc` (v2.12). What changed since the original is
marked *(2026-09-23)*. This note is the Task Card for slice 1; slice 2 is
listed and deliberately deferred.

## The defect, located in code

The gate treats an evidence record as one boolean:

```python
# bin/coverloop  reviewer_check()
ok = entry.get("status") == "pass" and entry.get("findings_open") == 0
```

and `attest` replaces the record wholesale:

```python
# bin/coverloop  cmd_attest()
report[name] = entry          # the previous codex/glm/mutation entry is gone
```

So after a reviewer returns `fail / 6 findings`, four are fixed, regression
tests are added, and a human judges the remaining two non-blocking, the
report has exactly two ways forward — and both are wrong:

* re-attest the reviewer as `pass / 0` — the gate goes green **by deleting
  the original review**; or
* leave it — the gate stays `FAIL` although the milestone is, in fact,
  approved with two named residual risks.

Observed in the field: the Alex grace-billing fix (GLM: 9 open P2/P3, gate ✘,
operator correctly refused to disposition them to turn it green), the
financial project in the report, and Gal-Nadlan-OS, where 34 of 63 L3 reports
still record a Codex FAIL *(2026-09-23 fleet measurement)*. The tool forces a
choice between a lie and a false alarm. That is the whole defect.

## The invariant this note serves

Coverloop does not exist to produce PASS. It exists to produce a faithful
record of what was checked, what failed, what was fixed, what remains, who
accepted the remainder, and on which exact code. A green result with
undisclosed open findings is worth less than a red one.

Every mechanism below is judged by one test: **can it only make the gate
stricter or more honest?** Anything that can make it looser is out of slice 1.

## Decision *(2026-09-23)*: build on the existing trust level, not on report/v2

Verified at `1cc1adc`: `bin/coverloop_report_v2.py` (signed L3 authorization)
exists but is not wired into the gate. Wiring it was considered and **rejected**:

- A signature only adds security if the builder cannot produce it. On the
  operator's Mac the agent can read the SSH key and load its passphrase from
  the keychain unattended, so an ordinary SSH key would be ceremony, not
  authority. Real separation needs a presence-bound key (Touch ID / security
  key), which ends phone approvals for every L3 change — a daily manual cost
  paid against a risk (an agent recording an approval nobody gave) that has
  never occurred and that the contract already forbids.
- So the acceptance object below lives **next to the existing human-gate
  record, at the same trust level as today's approval**: the operator names
  the accepted findings in the same message that approves ("approved; F5 and
  F6 accepted as risk"), and the session records exactly that. No additional
  manual step. Everything else in this note is unchanged.

If presence-bound approval is ever wanted, it is an opt-in gate flag on top of
this design, never a prerequisite for it.

## Slice 1 — what to build

Four changes, one release, one authority boundary.

### 1. Evidence records become append-only

Every evidence record — `codex`, `glm`, and since v2.12 `mutation` — becomes a
list of rounds. A new `attest --codex` **appends** `codex[n]`; nothing ever
overwrites `codex[0]`. The gate reads the **latest** round for its verdict and
prints every earlier round's verdict as history. Schema bump to
`coverloop-report/v3` (v1/v2 unchanged, no fallback).

### 2. Findings get identities and a status

A round carries `findings: [{id, severity, title}]` (ids are the reviewer's own
tags, e.g. `SEC-TAG-HISTORY`; for `mutation`, the guard that survived);
`findings_open` becomes derived, not stated. Each finding's status is exactly
one of:

```
OPEN · FIXED · RETESTED · REJECTED_AS_INVALID · DEFERRED · ACCEPTED_RISK
```

`FIXED`/`RETESTED` are claimed by a **later round**, never by the builder.
`REJECTED_AS_INVALID`, `DEFERRED`, `ACCEPTED_RISK` are claimed only by the
acceptance object (below). A builder cannot move a finding's status.

### 3. The acceptance object — recorded with the human gate

Recorded by `attest` next to the human-gate approval, only from an operator
message that names the findings (same rule as recording an approval today):

```json
{
  "decision": "APPROVE_WITH_ACCEPTED_RISK",
  "approver": "Daniel",
  "sha": "<source commit>",
  "accepted_findings": [
    {"id": "SEC-TAG-HISTORY", "severity": "P1",
     "reason": "fails closed to MISSING; cannot emit a wrong number",
     "reopen_if": ["production-deploy", "multi-user"]}
  ],
  "timestamp": "..."
}
```

Rules: `decision` ∈ {`APPROVE`, `APPROVE_WITH_ACCEPTED_RISK`, `REJECT`};
`APPROVE` with any open finding is **invalid** (fail closed); every open
finding must appear in `accepted_findings` with a non-empty `reason` for
`APPROVE_WITH_ACCEPTED_RISK` to validate; the object is bound to the source
SHA — any change to a non-exempt path invalidates it (existing evidence-only
ancestry rules apply unchanged).

### 4. The gate speaks the truth it already knows

```
COVERLOOP L3 — <sha>
  tests        PASS (npx vitest run)
  codex        round 1 FAIL (6)  →  round 2 PASS (0)          [attached]
  mutation     round 1 PASS (0 surviving)                     [captured]
  glm          advisory — round 1 FAIL (9): 1 P2, 8 P3        [attached]
  acceptance   APPROVE_WITH_ACCEPTED_RISK by Daniel — 2 findings accepted,
               reopen_if: production-deploy
  human gate   approved by 'Daniel'
DISPOSITION: APPROVED_WITH_ACCEPTED_RISK
```

The historical FAIL line is **always printed**. There is no flag to hide it.

## What slice 1 deliberately excludes

| Report § | Item | Why not now |
|---|---|---|
| 7 | Delta review (A..B) | Valid, but only as an **additional** round with `base_sha` = last full-review SHA; gate must refuse a delta whose base is not that. Needs its own note. |
| 8–9 | Source fingerprint / docs-only exemption | The gate already exempts evidence-only ancestors by exact path shape (`.coverloop/reports/<sha>.json`, `<sha>.<record>.log`); the comments in `bin/coverloop` record the smuggling attacks that forced that rigor. A `docs/` exemption is a `.md` carrying a migration. If widened at all: an exact-shape allowlist, never a hash of `src/`. |
| 10 | `MAX_REVIEW_ROUNDS` | A counter in the tool is gamed on round N+1. *(2026-09-23)* Done the right way in v2.12: the two-round rule is operating-contract text (a P1 open after two Codex rounds → stop and redesign), not a gate counter. |
| 12 | `failure_mode` auto-affecting blocking | The reviewer stating `FAIL_CLOSED` about its own finding and the gate downgrading on it is self-grading by the party that wants green. Keep it as free text inside the acceptance `reason`; a human weighs it. |
| 13 | Milestone state machine | Descriptive, not enforceable; the disposition line in §4 is the observable output. Revisit after slice 1 has one real use. |
| 16 | Inner loop vs boundary | Agreed, and **not yet written down** — `OPERATING_CONTRACT.md` has no such section (re-checked at `1cc1adc`). A one-paragraph contract addition ("Coverloop is the milestone boundary, not the inner dev loop"), no tool change. Separate docs PR. |

## Acceptance criteria for slice 1 (contract-based, fixed in advance)

1. A v3 report with `codex: [fail(6), pass(0)]` gates **green** at L3 with
   `APPROVE`; the output contains the round-1 FAIL line.
2. A v3 report with a failing record (`codex` or `mutation`) and no acceptance
   gates **red**.
3. Same report + a valid acceptance naming every open id → **green**,
   disposition `APPROVED_WITH_ACCEPTED_RISK`; naming all but one → **red**,
   names the missing id.
4. `APPROVE` (not `_WITH_ACCEPTED_RISK`) with any open finding → **red**.
5. An acceptance whose `sha` ≠ HEAD and HEAD is not an evidence-only
   descendant → **red**.
6. `attest --codex pass` on a report that already has `codex[0].status=fail`
   appends; the file diff shows `codex[0]` byte-identical. Same for `mutation`.
7. An acceptance that names a finding id not present in any round, or that
   has an empty `reason`, is **rejected as malformed** (fail closed).
8. Every existing test in `tests/` passes; `bin/coverloop` on a v1/v2 report
   behaves byte-identically to the release this builds on.
9. *(2026-09-23, per v2.12)* The release is guard-broken: removing each new
   check makes at least one test fail, recorded as its own `mutation` evidence.

## Authority

Every item in slice 1 can only add a required condition or add printed
history. Nothing removes a check. That is why it can ship as one L3 release;
the excluded items each carry a way to loosen the gate, which is why they
cannot ride along.
