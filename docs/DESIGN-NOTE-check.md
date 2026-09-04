# Design note — `coverloop check`, deferred to its own release

**Status:** not shipped. Built, reviewed twelve times, and pulled out
deliberately. The branch is preserved at `followup/coverloop-check-audit`
(tag `audit/check-12-rounds`), including every fix and every regression test.

## What it was

One command at the merge boundary, replacing the sequence a builder otherwise
orchestrates by hand:

```
coverloop check
  → refuse a dirty tree
  → derive the tier from the changed paths
  → run the independent reviews that tier requires, capturing transcripts
  → run the tests
  → bind the evidence to HEAD
  → run the real gate
  → print SAFE TO MERGE, or exactly one STOP: <reason>
```

The idea is still right. The measured problem it answers is real: the fleet's
session hook was followed 1% of the time for its model-line rule, and the
eight-step ceremony around `attest` was what people skipped.

## Why it is not in this release

Twelve cold review rounds (Codex at xhigh, GLM red-team), **52 verified
findings**, and **zero rounds with no new P0/P1**. `CHANGELOG.md` here carries a summary; the
round-by-round detail lives in the preserved branch — its own version of
`CHANGELOG.md` and, findings-by-round, its commit messages.

Two patterns decided it.

**One mechanism ate its own fixes.** Letting reviewed-but-uncountersigned
evidence advance the gate's baseline requires the owed human signature to be
carried forward to HEAD. That obligation was shed five different ways across
five consecutive rounds — by stacking a commit on top, under
`--human-gate-scope irreversible`, by an L0 successor, by the scope going
retroactively sticky, through `--base`, and finally by carrying the approval
while dropping the reviewer requirement. That part was cut first and stays cut.

**One guard could not be completed.** "The reviewer command must not be
repository-controlled" was extended five separate times — a bare token, a
script suffix, an `sh <file` redirect, a `PATH` symlink, a pipeline's second
half. No static check of a shell string is complete, and each round found the
next instance.

Neither is an argument that the feature is wrong. Both are arguments that its
**trust model has to be designed up front**, in a change small enough to reason
about, rather than assembled from guards inside a release whose purpose was to
make the system simpler.

## The trust model the next attempt starts from

Everything below was learned the expensive way and should be treated as settled
input, not re-litigated:

- **The reviewer policy is TRUSTED input, not a security boundary.** It lives
  outside the worktree (`~/.config/coverloop/reviewers.json`) so the change
  under review cannot alter it — that guarantee is real and worth keeping. The
  in-repo command check is a *tripwire*: useful, never complete. Document it as
  something to write with sudoers-level care.
- **Repository-controlled tests are not sandboxed.** The configured test
  command is arbitrary code running with the operator's privileges. Reviewers
  must therefore run *before* it, and even then a gate is not a sandbox. Say so
  rather than implying otherwise.
- **Secrets in the reviewed span stop the review.** Redacting a credential out
  of the packet is not enough when the reviewer is handed the working tree and
  expected to read it — the value stays one `cat` away. Stop; do not launder.
- **Reviewer evidence must cover exactly the span the risk floor judged.**
  Anything narrower (HEAD only, the reports directory excluded wholesale, a
  bare root commit's own files) means the reviewers approved something other
  than what the gate classified.
- **The verdict is a machine protocol.** Exactly `VERDICT: PASS`, exactly once,
  as the reviewer's closing word. Everything else — `PASS WITH RISKS`,
  `APPROVE`, lowercase, truncated, absent — fails closed.
- **One critical section.** Capture, verdict parsing and evaluation have to be
  under a single lock, or two concurrent runs on one commit read each other's
  transcripts.
- **A gate that fires on adoption is a gate people route around.** Two fixes
  had to be reverted for exactly this: classifying `.coverloop/config.json` as
  L2 (it is in the first span of every repo after `init`), and requiring a
  reviewer policy before the tier is even derived.

## What shipped instead

Only the shortened session contract, plus test-harness and CI-coverage fixes.
The derived tier was pulled too, for its own reasons — see
[`DESIGN-NOTE-derived-tier.md`](DESIGN-NOTE-derived-tier.md). `classify`,
`attest` and `gate` are byte-identical to the previous release.
