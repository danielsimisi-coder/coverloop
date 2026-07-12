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
coverloop gate  [--min-tier L0..L3]     # verify; exit 0 = pass, 1 = missing/failing evidence
```

## Recording evidence (`attest`)

Evidence lives in `.coverloop/reports/<HEAD-sha>.json` — one report per
commit, **committed with the change** so it is visible in the PR.

```bash
coverloop attest --tier L2 --tests            # runs config's test_command, records pass/fail
coverloop attest --codex pass                  # record the diff-review verdict (self-attested)
coverloop attest --codex pass \                # STRONGER: run the reviewer and capture its
  --codex-run "codex exec --sandbox read-only '...'"   # output (hashed, committed as evidence)
coverloop attest --codex pass \                # SAME STRENGTH CLASS, ZERO RE-RUN: attach the
  --codex-log /tmp/codex-review.txt            # transcript of a review you ALREADY ran
coverloop attest --glm pass --glm-run "glm-audit '...'"
coverloop attest --approve --approver daniel   # record the human gate (L3)
```

**Self-attested vs. captured vs. attached.** `--codex pass` on its own records
a *claim* — honest as an audit trail, but nothing ran. Add `--codex-run "<cmd>"`
and the tool executes the reviewer, writes its full output to
`.coverloop/reports/<sha>.codex.log` (committed with the change), and records
the log's **sha256** in the report. The verdict is still yours to state
(reviewer output is prose, not a status), but now it's backed by a hashed,
inspectable transcript rather than thin air.

In the real workflow the review usually ran *interactively first* — re-running
it through `--codex-run` doubles the cost, which is exactly how evidence ends
up self-attested in practice. **`--codex-log <file>` / `--glm-log <file>`
attach the transcript you already have**: redacted through the same secret
filter, copied to the canonical `<sha>.<reviewer>.log`, hash-bound, committed.
Recorded as `source: "attached"` — one honesty notch below `captured` (the
tool didn't execute the command, so there's no exit-code/execution binding)
but the same binding, tamper, and replay rules apply. `coverloop gate` labels
every verdict `[captured <hash>]`, `[attached <hash>]`, or `[self-attested]`
so a reviewer, or a stricter CI policy, can tell them apart. `attest --tests`
likewise actually runs the `test_command` (same trust model as `package.json`
scripts) and records the real result, failures included.

**Transcripts are redacted before they touch git.** Before a captured or
attached log (or the reviewer command string) is written, it runs through the
shared secret filter: key/token/DB-credential/private-key **values** are
replaced with `[REDACTED:…]`, and (v2.7.2) so are **PII shapes** — home-dir
usernames (`/Users/<name>`, `/home/<name>`), email addresses, and UUID-shaped
session ids. A **failed** reviewer run (nonzero exit — expired auth, a hang) is
withheld entirely rather than committing its error/env dump, and `attest`
exits non-zero for it. Honesty note: this is pattern-based redaction — a
tripwire against the common leaks, not a full DLP pass; unrecognized secrets
or free-form personal data are not detected.

**Enforce transcript-backed evidence in CI.** `coverloop gate
--require-transcript` makes L2/L3 **fail** on any reviewer verdict that is
merely self-attested — the report must carry a committed transcript (captured
OR attached) for Codex (L2+) and GLM (L3). `--require-executed` is stricter:
the transcript must come from a coverloop-EXECUTED run (`source: "captured"`,
exit 0) — attached transcripts are rejected. `--require-captured` is kept as a
deprecated alias of `--require-transcript`. Pair with the risk floor
(`--min-tier L2 --require-transcript`) and a bare "codex pass" no longer
merges; only a committed, hash-bound reviewer transcript does.

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
- The docs-only waiver (L1 only) applies when every changed file is **real
  documentation** (an exact root-level `LICENSE`/`README.md`/`CHANGELOG[.md]`,
  or a `.md`/`.txt`/`.rst` file *under `docs/`*) or an exact committed report
  artifact (`<sha>.json` / `<sha>.<reviewer>.log`). Executable code cannot
  masquerade as docs: a basename collision (`src/CHANGELOG`), an executable
  under `docs/` (`docs/deploy.sh`), or a non-artifact file under `reports/`
  (`reports/backdoor.py`) all count as code and require the test gate. The
  waiver also applies **only when a base is passed on the command line**
  (`--base origin/<base_ref>`); the base is never read from in-repo config.
- Changing `.coverloop/config.json` is **never** waived — it alters gate behavior.
- **`--min-tier` is a floor, not an override:** the effective tier is
  `max(--min-tier, the report's self-declared tier)`, so a pin can only RAISE
  requirements, never downgrade an L3 change. `attest` tier is monotonic — it
  won't silently downgrade an existing report (`--force` to override). The
  recorded test command must match the project's current `test_command`.
- `--approve` requires `--approver <name>`: approval must be attributable.

## Enforce it in CI (GitHub Actions)

The copy-paste-ready file is [`examples/github-actions-coverloop.yml`](../examples/github-actions-coverloop.yml). It pins everything to **immutable commit SHAs** and **verifies the gate's checksum** before running it — a moved tag or a tampered CDN response can't slip modified gate code into your CI:

```yaml
# .github/workflows/coverloop.yml
name: coverloop
on: pull_request
permissions:
  contents: read              # least-privilege job token
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4 (SHA-pinned)
        with:
          # the real PR head SHA (a validated commit id, no ref-injection
          # surface), not GitHub's synthetic merge commit — evidence reports
          # live on the PR branch, and the merge commit's first-parent chain
          # walks the BASE branch instead.
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
      - name: Coverloop gate
        env:
          # Bump BOTH together on every upgrade to a release you vetted:
          COVERLOOP_SHA: e6b3a4dabfcf24724ff314a4d520540c81b74b06        # v2.8.0 release commit (immutable)
          COVERLOOP_SHA256: 27caf03a2faef295e0a6d6735937bc2204b93b206213e481de424ea2b8bb35fe  # shasum -a 256 bin/coverloop @ that commit
          # base_ref via env, never interpolated into the shell (a ref name can
          # carry shell metacharacters).
          BASE_REF: ${{ github.base_ref }}
        run: |
          curl -fsSL -o coverloop \
            "https://raw.githubusercontent.com/danielsimisi-coder/coverloop/${COVERLOOP_SHA}/bin/coverloop"
          echo "${COVERLOOP_SHA256}  coverloop" | shasum -a 256 -c - \
            || { echo "::error::checksum mismatch — refusing unverified gate"; exit 1; }
          chmod +x coverloop
          # --min-tier is a risk FLOOR so a PR can't dodge review by declaring a
          # lower tier; drop it only if a human reviews the tier per PR.
          ./coverloop gate --ci --min-tier L2 --require-transcript --base "origin/${BASE_REF}"
```

Then in the repo settings: **Branches → branch protection → require the
`coverloop / gate` status check.** From that moment a change can't merge without
either the evidence its tier requires (tests, the reviews, a named approval) or
a maintainer explicitly overriding a required check. Two honest caveats: the
**tier is self-declared** unless CI pins a floor (so pin `--min-tier` to the
lowest tier that must always be met — the example uses L2), and branch
protection's override is a human decision, not something the gate can prevent.
What the gate removes is *silent* merges of unreviewed code.

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
symlinked transcripts, and checks the sha256 — so `--require-transcript` can't be
satisfied by pointing at an old or off-tree file. It still does **not**
cryptographically prove the real reviewer ran: a **committer** can always run a
fake command that emits "CLEAN". Integrity here assumes a non-adversarial
filesystem and that PR review catches an obviously bogus transcript; defeating
it requires commit access and leaves a committed, readable trail. That is the
honest ceiling for a tool that runs on your machine — raise it further only
with a server-side/GitHub-App check (roadmap).

**"Attached" is one honesty notch below that.** `--codex-log` skips even the
"ran the fake command" step — the tool never executed anything, so the
transcript's provenance is entirely the attester's word. Everything else holds
(same redaction, same commit+reviewer binding, same tamper/replay rejection,
same PR-readable log), which is why `--require-transcript` accepts it: the
property that flag actually enforces is *a committed transcript a human can
audit*, and both sources deliver it. The gate's `[attached]` label keeps the
distinction visible instead of pretending attachment is execution. The
mechanical failure modes are closed: `--*-log` refuses sources inside
`.coverloop/reports/` (no one-command laundering of a withheld failed-run log
or replay of an old commit's artifact), refuses withheld-placeholder content
anywhere, and an entry claiming `attached` while carrying a captured run's
`exit_code` is rejected as inconsistent.

**Known residuals (by design, until a GitHub App exists):**
- **Tier is self-declared** unless CI pins it. A PR could label an L3 change L0
  to dodge gates; defense is the committed, reviewable tier field plus a pinned
  floor — `coverloop gate --ci --min-tier L2` forces ≥L2 evidence on every PR
  regardless of what the report claims. Pin it to your repo's risk appetite.
- **Human approval is *named*, not *authenticated*.** `--approver daniel`
  records who approved, but doesn't verify it was really them via a GitHub
  review/environment approval. Treat the approver field as attributable intent,
  and lean on branch protection's own required-reviews for identity until the
  planned `--require-github-approval` lands.
- **`test_command` and reviewer commands come from in-repo config/flags** — a
  PR that changes them is high-signal and must be reviewed as such.
- **`--require-executed` is best-effort, not proof of execution.** It prefers a
  coverloop-*captured* run over an *attached* transcript, but `command`,
  `exit_code`, and `ran_at` are unauthenticated JSON and the log's bytes+hash
  are attester-authored, so a committer who controls the working tree can still
  hand-craft a captured-shaped entry. It filters honestly-attached evidence (a
  useful policy signal), it does not cryptographically prove coverloop ran the
  reviewer — the same non-adversarial-filesystem ceiling as the rest of the
  tool. (A genuine *failed* capture cannot be laundered, though: its log carries
  a withheld-run marker the gate rejects for both sources.)
- **Dirty-worktree drift is caught only with `--require-clean-tree`.** Evidence
  binds to HEAD, so uncommitted code edited *after* a passing attest would gate
  green while HEAD is unchanged. CI is immune (it checks out the clean PR head
  SHA); for **local** pre-push/pre-deploy gating pass `--require-clean-tree`,
  which fails on uncommitted non-evidence changes (report artifacts carved out).
  It is opt-in because a legitimate untracked scratch file would otherwise block
  the gate.

`--json` emits a machine-readable verdict on stdout; `--ci` adds GitHub
error annotations on **stderr** so failures show inline on the PR — the two
flags compose (stdout stays pure JSON).
