# Design note — the derived risk tier, deferred to its own release

**Status:** not shipped. Built, reviewed five times on a reduced diff after
twelve rounds on a larger one, and stopped deliberately at a pre-agreed
condition. Preserved on `followup/derived-tier-audit`
(tag `audit/derived-tier-5-rounds`) with its regression tests.

## What it was

`attest` would stop accepting a tier from its caller. Instead it would classify
the same paths `gate` does, with the same baseline semantics, record where the
tier came from (`tier_source`: `derived` / `elevated` / `forced`), the `floor`
it computed and why — and refuse anything below that floor.
`--raise-tier <T> --reason "..."` would elevate **upward only**, for risk a path
classifier cannot see, writing the reason into the report.

Compatibility was kept, and matters for reading the branch: the legacy `--tier`
pin still works at or above the floor (recorded as a caller-declared tier), and
`--force` can still record a tier below it (recorded as `forced`), with `gate`
recomputing the real floor either way.

The motivation is measured and still stands: across nine repos hand-declared
tiers were wrong in both directions — 35% too high on validated baselines, and
**47% of one repo's reports declared L2 on segments whose floor was L3**. A tier
nobody derives is a tier that drifts toward whatever is convenient.

## Why it is not shipped

Five review rounds on the reduced diff, after twelve on the combined one. The
stop condition was met when **three consecutive rounds each found a real P1 in
the same conceptual boundary**: *what counts as caller-influenced provenance.*

| round | the case that leaked | fix attempted |
|---|---|---|
| 3 | `--raise-tier L3 --reason` at the derived floor | include same-tier raises |
| 4 | legacy `--tier L3 --reason` at the floor; re-attesting a pre-2.11 report | one rule: above floor **or** asserted |
| 5 | bare legacy `--tier L3` at the floor | `asserted` widened to any explicit flag |

Each fix was correct, each held, and each round found the boundary drawn one
case too narrow. The pattern is the point: every miss had the **same
consequence** — a report recording `tier_source: derived` when a caller had in
fact named the tier, after which `gate --human-gate-scope irreversible` waived
the named human approval on a path the classifier reads as reversible.

## What the next attempt should start from

- **`derived` is a claim about causation, not a default.** It means *the paths
  alone produced this tier.* Anything else — an explicit flag of any spelling, a
  supplied reason, a tier above the floor, a tier inherited from a report
  written before provenance existed, a forced tier — is not derived. Model it
  as one predicate computed in one place, and prove it by enumeration rather
  than by adding a case per review round.
- **The consumer is the real specification.** Only one AUTHORIZATION decision
  reads `tier_source`: the `--human-gate-scope irreversible` exemption. (The
  preserved branch also reads it for provenance reconstruction and status
  output; those report, they do not decide.) Write that
  exemption's precondition first — "the tier is exactly what the paths justify,
  and no human has been asked to think about it" — and derive the producer from
  it.
- **The dangerous direction is a false `derived`, never a false `elevated`.**
  Over-marking costs a human approval nobody needed. Under-marking silently
  removes the only human in the loop. When in doubt, mark elevated.
- **Provenance has precedence, and it must be explicit:** a supplied reason,
  then a preserved prior elevation, then an inference about pre-2.11 or forced
  reports, then the legacy "no reason given" marker. Getting this order wrong
  laundered a genuine elevation reason into boilerplate (found in round 4).
- **Two consumers of "is this a protocol project?" drifted apart** while this
  work was in flight (`session-contract.sh` vs `pre-risky-git.sh`). Any release
  touching one should check the other.

## What did ship instead

Only the shortened session contract, plus test-harness and CI-coverage fixes.
`classify`, `attest` and `gate` are byte-identical to the previous release —
see the release commit, where `git diff -- bin/coverloop` is empty.
