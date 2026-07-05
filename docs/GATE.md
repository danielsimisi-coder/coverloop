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
coverloop attest --codex pass                  # record the diff-review verdict (self-attested)
coverloop attest --codex pass \                # STRONGER: run the reviewer and capture its
  --codex-run "codex exec --sandbox read-only '...'"   # output (hashed, committed as evidence)
coverloop attest --glm pass --glm-run "glm-audit '...'"
coverloop attest --approve --approver daniel   # record the human gate (L3)
```

**Self-attested vs. captured evidence.** `--codex pass` on its own records a
*claim* — honest as an audit trail, but nothing ran. Add `--codex-run "<cmd>"`
and the tool executes the reviewer, writes its full output to
`.coverloop/reports/<sha>.codex.log` (committed with the change), and records
the log's **sha256** in the report. The verdict is still yours to state
(reviewer output is prose, not a status), but now it's backed by a hashed,
inspectable transcript rather than thin air — and `coverloop gate` labels each
verdict `[captured <hash>]` or `[self-attested]` so a reviewer, or a stricter
CI policy, can tell them apart. `attest --tests` likewise actually runs the
`test_command` (same trust model as `package.json` scripts) and records the
real result, failures included.

**Enforce captured evidence in CI.** `coverloop gate --require-captured` makes
L2/L3 **fail** on any reviewer verdict that is merely self-attested — the
report must carry a captured transcript for Codex (L2+) and GLM (L3). Pair it
with the risk floor (`--tier L2 --require-captured`) and a bare "codex pass"
no longer merges; only a committed, hashed reviewer run does.

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
  documentation or a report file — **and only when a base is passed on the
  command line** (`--base origin/<base_ref>`, as the CI workflow does). The
  base is never read from `.coverloop/config.json`, because that file ships
  inside the PR and could be set to hide a code change. No trusted base →
  no waiver → tests required.
- Changing `.coverloop/config.json` is **never** waived — it alters gate behavior.
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
          COVERLOOP_REF=v2.6.2   # pin to a release tag, never main
          curl -fsSL -o coverloop \
            "https://raw.githubusercontent.com/danielsimisi-coder/coverloop/${COVERLOOP_REF}/bin/coverloop"
          chmod +x coverloop
          # Pin --tier to a risk FLOOR so a PR can't dodge review by declaring
          # a lower tier; drop it only if a human reviews the tier per PR.
          ./coverloop gate --ci --tier L2 --require-captured --base "origin/${{ github.base_ref }}"
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

**What "captured" does and doesn't buy you.** `--codex-run` upgrades a verdict
from a bare claim to a hashed transcript committed in the PR — forging it now
means fabricating a plausible reviewer log *and* running the fake command, and
the log is right there for a human to read. `verify_capture()` binds each
captured verdict to *this* commit's / *this* reviewer's log
(`.coverloop/reports/<commit>.<reviewer>.log`), rejects replayed, tampered, or
symlinked transcripts, and checks the sha256 — so `--require-captured` can't be
satisfied by pointing at an old or off-tree file. It still does **not**
cryptographically prove the real reviewer ran: a **committer** can always run a
fake command that emits "CLEAN". Integrity here assumes a non-adversarial
filesystem and that PR review catches an obviously bogus transcript; defeating
it requires commit access and leaves a committed, readable trail. That is the
honest ceiling for a tool that runs on your machine — raise it further only
with a server-side/GitHub-App check (roadmap).

**Known residuals (by design, until a GitHub App exists):**
- **Tier is self-declared** unless CI pins it. A PR could label an L3 change L0
  to dodge gates; defense is the committed, reviewable tier field plus a pinned
  floor — `coverloop gate --ci --tier L2` forces ≥L2 evidence on every PR
  regardless of what the report claims. Pin it to your repo's risk appetite.
- **Human approval is *named*, not *authenticated*.** `--approver daniel`
  records who approved, but doesn't verify it was really them via a GitHub
  review/environment approval. Treat the approver field as attributable intent,
  and lean on branch protection's own required-reviews for identity until the
  planned `--require-github-approval` lands.
- **`test_command` and reviewer commands come from in-repo config/flags** — a
  PR that changes them is high-signal and must be reviewed as such.

`--json` emits a machine-readable verdict on stdout; `--ci` adds GitHub
error annotations on **stderr** so failures show inline on the PR — the two
flags compose (stdout stays pure JSON).
