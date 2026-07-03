# `coverloop gate` — the enforceable evidence gate

The hooks in this repo remind; **the gate blocks.** `coverloop gate` is a
fail-closed CLI that verifies the required review evidence exists for a
change — bound to the exact commit — and exits non-zero when anything is
missing. Wire it into CI as a **required PR check** and "the loop ran" stops
being a claim and becomes a status check.

It never sends code anywhere and never calls a model. It only reads local
files and git metadata.

## The three commands

```bash
coverloop init                      # once per repo: .coverloop/config.json + reports/
coverloop attest [...]              # record evidence for the current HEAD commit
coverloop gate  [--tier L0..L3]     # verify; exit 0 = pass, 1 = missing/failing evidence
```

## Recording evidence (`attest`)

Evidence lives in `.coverloop/reports/<HEAD-sha>.json` — one report per
commit, **committed with the change** so it is visible in the PR.

```bash
coverloop attest --tier L2 --tests            # runs config's test_command, records pass/fail
coverloop attest --codex pass                  # record the independent diff-review verdict
coverloop attest --codex fail --codex-findings 3
coverloop attest --glm pass                    # record the red-team/audit verdict (L3)
coverloop attest --approve --approver daniel   # record the human gate (L3)
```

`attest --tests` is the only subcommand that executes anything: it runs the
`test_command` from `.coverloop/config.json` (the repo owner's own config —
same trust model as `package.json` scripts) and records the result honestly,
including failures.

## What each tier requires

| Tier | tests pass | Codex pass, 0 open | GLM pass, 0 open | human approval |
|:---:|:---:|:---:|:---:|:---:|
| **L0** | – | – | – | – |
| **L1** | ✔ (waived for docs-only diffs) | – | – | – |
| **L2** | ✔ | ✔ | – | – |
| **L3** | ✔ | ✔ | ✔ | ✔ (named approver) |

**Committing the evidence (how the CI flow works).** Attesting writes the
report, and committing the report necessarily creates a new HEAD — so the
gate accepts a report bound to an ancestor commit **only when the diff from
that ancestor to HEAD touches nothing but `.coverloop/reports/` files**.
An evidence-only commit rides safely; the moment any *code* changes after
attestation, the evidence is stale and the gate fails. `attest` applies the
same rule in reverse: later attestations (e.g. recording the human approval
after committing the test evidence) inherit the ancestor's record instead of
losing it.

Two deliberate limits: the ancestor search follows **first parents only and
stops after 20 commits** (an evidence chain longer than that fails closed —
re-attest at HEAD), and diffs are computed with `--no-renames`, so renaming a
code file into `docs/` or `.coverloop/reports/` cannot smuggle it past the
evidence-only / docs-only checks.

Fail-closed rules:

- **No usable report for HEAD → FAIL** (except L0). Absence of evidence is failure.
- **Any code change after attestation invalidates the evidence** (see above);
  a "small fix after approval" must re-run the loop.
- **Corrupt/forged reports (bad JSON, SHA mismatch, unknown schema) fail
  EVERY tier — including L0.**
- **Missing or corrupt `.coverloop/config.json` fails every non-L0 tier** —
  the gate refuses to run in a repo that never onboarded.
- The docs-only waiver (L1 only) applies when every changed file is
  documentation or a report file. Changing `.coverloop/config.json` is
  **never** waived — it alters gate behavior.
- `--approve` requires `--approver <name>`: approval must be attributable.

## Enforce it in CI (GitHub Actions)

```yaml
# .github/workflows/coverloop.yml
name: coverloop
on: pull_request
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # REQUIRED: check out the real PR head, not GitHub's synthetic
          # merge commit — evidence reports live on the PR branch, and the
          # merge commit's first-parent chain walks the BASE branch instead.
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
      - name: Coverloop gate
        run: |
          curl -fsSL -o coverloop \
            https://raw.githubusercontent.com/danielsimisi-coder/coverloop/main/bin/coverloop
          chmod +x coverloop
          # tier comes from the report the PR carries; add --tier to pin it
          ./coverloop gate --ci --base "origin/${{ github.base_ref }}"
```

Then in the repo settings: **Branches → branch protection → require the
`coverloop / gate` status check.** From that moment, an L3 change physically
cannot merge without committed evidence of tests, both reviews, and a named
human approval.

(If the repo vendors `bin/coverloop` — which this one does — replace the
`curl` with `./bin/coverloop`, pinning the gate's version to the repo.)

## Honest threat model

The gate verifies that evidence **exists, passes, and is bound to the commit
under review**. It cannot stop someone from hand-writing a lying report —
nothing local can. What it changes is the failure mode: silent drift
("the loop probably ran") becomes an explicit, committed, PR-visible
artifact that a human reviewer can audit. Forging it is no longer an
accident; it's a choice that leaves a trail.

`--json` emits a machine-readable verdict on stdout; `--ci` adds GitHub
error annotations on **stderr** so failures show inline on the PR — the two
flags compose (stdout stays pure JSON).
