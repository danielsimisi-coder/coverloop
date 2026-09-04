# Protocol changelog

Operational history of the Coverloop Multi-Model Production Protocol. The live doc (`CLAUDE.md`) carries only the current version; the story lives here.

## 2026-09-04 — one command at the boundary (PROTOCOL v2.11.0)

An evidence-driven review of the fleet's own logs asked whether Coverloop had
become too heavy to follow. It had, in four specific ways — each fixed here,
and none by weakening a gate.

- **The tier is derived, not declared.** `attest` no longer takes the tier from
  the caller: it classifies the same paths `gate` would, with the same floor
  semantics, and records `tier_source`, the computed `floor` and its reasons.
  Below the floor is refused (exit 2). `--raise-tier <T> --reason "<why>"`
  elevates **upward only** and writes the reason into the report, for risk the
  path classifier cannot see (a milestone gate covering many migrations, a
  config file that steers auth). The legacy `--tier` pin still works above the
  floor — recorded as an elevation with an explicit "no reason given" marker,
  plus a migration note on stderr — so every pre-2.11 caller, including the four
  SHA-pinned CI workflows, keeps passing unchanged.

- **Verification is not authorization.** The gate's baseline walk used to demand
  a human signature before it would trust an ancestor's evidence. In the fleet
  that dropped 238 fully reviewed L3 commits from the baseline: their files fell
  back into every later change's floor, so docs-only commits inherited L3 from
  the repo root and the gate's floors were systematically inflated. The walk now
  asks the *verification* question — tier covers the segment, tests passed,
  required reviews passed — via an explicit `EVIDENCE_VERIFICATION` scope. The
  human gate is unchanged where it decides anything: `gate` and `check` still
  fail on it at HEAD, and an ancestor with missing or failing tests or reviews
  still stops the baseline dead (both directions are regression-locked).

- **`coverloop check` — one command at the merge boundary.** Refuse a dirty tree
  → derive the tier → run the tests → run the reviews that tier requires and
  capture their transcripts → bind to HEAD → run the real `gate`. It prints
  `SAFE TO MERGE` or exactly **one** `STOP: <reason>`, and it is a wrapper over
  the existing primitives with no new authority: `classify`, `attest` and `gate`
  are untouched and still what CI runs. The reviewer lineage is configuration,
  not architecture — `"reviewers": {"primary": "codex", "secondary": "glm"}`
  with `"reviewer_commands"` — so Codex is a default, not an assumption. A
  missing reviewer command is a STOP that names the role; a transcript that does
  not end in an unambiguous pass marker is a `fail`, persisted as one.

- **The session hook is now seven lines of invariants.** The SessionStart hook
  ran on every session and after every compaction, and at 6 KB it turned the
  builder into a process manager: classify every task, pick a model, run two
  reviewers, re-attest, keep a ledger, end every reply with a model line —
  measured at **1% compliance** for the last of those. It now says: build
  normally, run the relevant tests, run `coverloop check` before merge/deploy,
  never lower the floor, never self-approve, never bypass red, never send
  secrets or PII. Enforcement lives in code, where it is fail-closed; prose is
  reserved for what no command can enforce.

This release was itself elevated to **L3**. The path classifier reads it as L2,
but the diff changes the attestation authority itself — baseline validation,
reviewer execution, verdict parsing, and what `SAFE TO MERGE` means — which is
exactly the intent-level risk `--raise-tier --reason` exists for.

Seven cold review rounds ran against this change; the gate stopped its own merge
every time. 35 findings, all verified against the code, and the pattern in them
decided the shape of the release:

**Item 2 — "verification is not authorization" — is DEFERRED, not shipped.**
Letting a reviewed-but-uncountersigned commit advance the gate's baseline needs
an obligation to be carried forward instead, and that mechanism produced a
fail-open in **every one of the five rounds**: shed by stacking a commit on top
(round 1), shed under `--human-gate-scope irreversible` (round 2), shed by an L0
successor and by `scope` going retroactively sticky (round 3), lost through
`--base` (round 4), and finally carrying only the human approval while dropping
the reviewer requirement entirely (round 5). Each fix created the next finding.
The baseline therefore stays exactly as released: it advances only under the
full authorization requirements. The fleet's inflated floors remain — that is
over-strictness, which is the safe direction to be wrong in — and item 2 returns
later as an isolated design problem with this history attached.

What the rounds did close, in what did ship:

- **The reviewer is named outside the repo, and runs outside it.** Roles and
  commands come from `~/.config/coverloop/reviewers.json` (or
  `$COVERLOOP_REVIEWERS`), never the worktree; `check` refuses a policy that
  resolves inside the repo under review (symlinks included), a
  group/world-writable one, and a `.coverloop/config.json` that defines
  reviewers at all. Token checks alone could not hold — `python3 -m reviewer`
  picks up a planted `reviewer.py`, `sh <scripts/reviewer` hides the path in a
  redirect token — so the command now executes from a scratch directory with
  `PYTHONPATH` dropped and every repo-reachable `PATH` entry filtered out. What
  it needs arrives explicitly: `$COVERLOOP_REPO`, `$COVERLOOP_DIFF`,
  `$COVERLOOP_BASE`. The packet covers the same span the floor was computed
  over, a `git` failure while producing it stops the run rather than handing a
  reviewer an empty diff, and the scratch copy is cleaned up on every path.
- **The verdict is a machine protocol.** Exactly `VERDICT: PASS`, as the
  reviewer's closing word (only a CLI footer may follow), with no other
  `VERDICT:` line anywhere in the transcript — matched case-insensitively so a
  lowercase `verdict: fail` is caught and rejected rather than skipped.
  `PASS WITH RISKS`, `APPROVE`, `LGTM`, a truncated log and silence all fail.
- **`check` holds its own boundary.** It refuses a dirty tree, re-checks the
  tree and HEAD after the tests and reviewers have run (a test that repairs the
  code it tests must not earn `SAFE TO MERGE` for the broken commit being
  shipped), honours attest's exit status so evidence git would ignore stops the
  run, reports exactly one `STOP:` and exit 1 — and in `--json` owns file
  descriptor 1, not just Python's `sys.stdout`, since the test command and the
  reviewers are subprocesses that inherit it.
- **An elevation cannot claim the classifier's exemption.** Under
  `--human-gate-scope irreversible` the exemption reads the classified paths,
  and `--raise-tier` exists precisely because the classifier under-reads the
  change. An elevation's recorded reason also survives the ordinary
  `check` -> `attest --approve` flow instead of being folded back into
  "derived".
- **CI was running 102 of 264 tests.** `unittest.main()` sat above classes
  appended later in `tests/test_properties.py`, and CI invokes that file
  directly — so every regression added in this release was invisible to it. The
  entry point now lives at the end of the file, where what it collects cannot
  silently shrink.
- **A repo could weaken its own test gate.** `test_command` is what
  "tests: pass" *means*, and reviewers only run at L2/L3, so a commit rewriting
  it to `true` was ordinary L1 source by path: no meaningful tests, no review,
  `SAFE TO MERGE`. Classifying the config FILE as L2 was tried first and
  reverted — it sits in the first span of every repo after `init`, so it raised
  the floor fleet-wide on adoption, which is the over-classification this tool
  warns about. `check` now compares the current command against the one the
  last ancestor report actually ran, and raises to L2 when it changed. (Reading
  the baseline's config, or the last report's command, would never fire:
  rewriting the command invalidates that evidence by construction and drops the
  baseline to the root, and a deleted report is indistinguishable from
  first-time setup. It reads the config file's OWN git history instead — one
  commit touching it means adoption, two or more means it changed, and git
  failing to answer fails closed. The promotion is written into the report, not
  just used locally: evaluating L2 while recording L1 left CI's gate reading L1
  and never asking for the transcript.)
- **The review packet shows everything the floor judged.** Excluding all of
  `.coverloop/reports/` hid `.coverloop/reports/evil.sql` — which classifies L3
  like any other path, since only the exact SHA-shaped artifacts are evidence.
  The floor said L3 while both reviewers read a packet without the cause.
- **The test suite no longer spends production review budget.** It drives the
  real reviewer CLIs with a stubbed transport — nothing is sent — but
  `log_egress` still wrote `attempt` markers to the operator's production egress
  log, and the daily cap counts exactly those. A full run burned ~30 slots, so
  after a few runs every real review that day was refused; that is why the GLM
  red-team failed closed in four of the five rounds. The suite now runs against
  a temporary log and FAILS if the production one is touched at all.

Explicitly **not** done in this release, and still open: a signed
`approvers` allowlist, the lineage refactor that would drop the fixed
`codex`/`glm` report keys, item 2 above, and any change to `human_gate_scope`,
`STALE`, or the L3 GLM requirement.

## 2026-08-22 — the baseline earns its trust, and the loop closes (PROTOCOL v2.10.8)

A scoped review of v2.10.7's own fix commit found five defects in it. All five
verified and closed:

- **A migration in a repo's FIRST commit was never classified.** A two-dot diff
  from the root excludes the files the root itself introduced, so the very first
  commit's content escaped the floor entirely. The root's own files are now part
  of whichever segment first accounts for them.
- **A tier claim is not evidence.** The baseline walk accepted a planted L3
  report with no tests, no reviewers, no approval — the tier covered the floor,
  so the baseline advanced past a migration. A report now advances the baseline
  only if it would pass its own evidence evaluation.
- **Only exact artifact shapes are exempt** in `.coverloop/reports/` —
  `evil.sql` parked there classifies like any other path.
- **Shallow history fails closed.** A shallow boundary looks exactly like a root
  commit; everything at or before it silently vanished from the floor. Fetch
  full history (CI: `fetch-depth: 0`) or pass `--base`.
- **The walk is capped** at 100 evidence commits; older spans fold into the
  pre-baseline segment, which only ever enlarges what the gate classifies.

This entry closes the audit sequence: nine rounds, 45+ verified defects, every
one regression-locked. The stopping rule was honest non-convergence — later
rounds increasingly found defects in the fixes themselves, which is the
strongest argument this tool's own README makes for why no author, human or
model, should review their own work.

## 2026-08-22 — existence is not validity (PROTOCOL v2.10.7)

Round eight targeted the newest code — all three defects were in fixes from the
two rounds before it, each verified end-to-end before being fixed:

- **A planted under-tier report became a trusted baseline.** The ancestor walk
  accepted any commit whose report FILE existed. A hand-written (or pre-v2.10.6,
  never-floor-checked) L0 report on a migration commit put the migration outside
  every later `prior..sha` diff, and gate PASSED at L0. Baselines are now
  re-validated oldest-first: a report whose tier under-declares the deterministic
  floor of its own segment simply does not advance the baseline, so its segment
  stays inside what the gate classifies. The `origin_commit` shortcut is dropped
  from floor computation for the same reason — it trusted a rebound report's own
  word for where its coverage began.
- **The evidence-directory exclusion was unanchored.** Every occurrence of the
  substring matched, so `nested/.coverloop/reports/evil.sql` — and even
  `x.coverloop/reports/…` via the unescaped-dot lookalike — was exempt from
  classification entirely. Now anchored to the repo root.
- **`attest` failed open when the floor was unknowable.** With `git diff` broken
  the check was skipped and an L0 report was saved over a migration, exit 0. It
  now refuses before writing; `--force` remains, and gate still computes its own
  floor independently.

Note for existing repos: baselines recorded before v2.10.6 were never
floor-checked at record time, so the validated walk may now classify further
back than before and raise floors on the next gate run. That is the fix working,
not a regression — those segments were never actually validated.

## 2026-08-22 — attest enforces its own floor (PROTOCOL v2.10.6)

The remaining round-7 items exposed a structural gap: only `gate` ever validated
the deterministic floor. `attest` recorded whatever `--tier` was declared,
unchecked — so a migration attested L0, then covered by a later, separately
committed evidence file, could pass gate forever after: gate trusted the nearest
ancestor's report as a legitimate baseline without anyone ever having actually
checked it against the floor.

- **`attest` now enforces the same deterministic floor `gate` does**, and
  refuses to record a tier below it. This closes the gap at its root: any report
  that reaches disk already satisfies tier >= floor(baseline..that commit), so
  gate can safely trust committed evidence as an incremental baseline instead of
  re-walking full history on every call.
- Two defects surfaced only by re-running the full suite after that change —
  both introduced by this session's own edits, caught before either shipped: a
  stray `return` left `paths += out` as dead code, so the floor silently saw
  only uncommitted changes again; and the evidence report file itself
  classified as "L1: unrecognized source," so a repo's own audit trail
  re-flagged itself as unreviewed.
- `.coverloop/reports/` is now excluded from risk classification — it holds the
  tool's generated output, not application code; its integrity is defended
  separately (hash binding, forgery checks), not by the path classifier.

## 2026-08-22 — round six, and why the loop stopped here (PROTOCOL v2.10.5)

Two of this round's six defects were introduced by the PREVIOUS round's fixes, and
one of them was worse than the bug it replaced. That is the reason this sequence
stopped at seven rounds rather than running until a clean verdict.

- **The 4096-character cap made long secrets leak COMPLETELY.** Past the cap the
  whole match failed, so `redact()` replaced nothing and `scan()` saw no
  assignment: a 4097-character quoted secret went out whole. The cap now sits
  beside a line-scoped fallback, so it degrades to over-redaction instead of to
  silence. The test that had blessed the old behaviour asserted the wrong
  property and was rewritten.
- **Irreversibility depended on rule ORDER.** `is_irreversible()` returned on the
  first matching rule, so `workers/models/user.py` matched the worker rule (L3,
  reversible) before the schema rule and the human stop was waived for a schema
  change because of where the file lived. It now asks every rule.
- **`--signers-ref` was an option-injection surface**, the same class as
  `--base`: `git show` takes options positionally, so an option-shaped ref could
  materialise attacker-chosen commit text as the allowed-signers policy.
- **A failed range lookup became an empty path set**, an all-clear assembled out
  of a git failure. It now reports unknown, which the gate refuses.

Known limitation, unfixed and documented: without `--base`, the floor covers the
commit being gated plus everything the recorded evidence does not cover. A FIRST
attestation taken after an intervening safe commit can therefore miss an earlier
dangerous one. CI passes `--base` and is unaffected; local runs should too.

## 2026-08-22 — round five: stop maintaining two lists (PROTOCOL v2.10.4)

Two of the six defects this round were the same disease, and it had already bitten
twice before: `IRREVERSIBLE_RE` was a second regex that had to agree with
`RISK_RULES`, and it drifted every time a rule was added — camelCase authz, then
`acl`, then the alembic and db/migrate directories. Each drift silently waived the
human stop for exactly the changes `--human-gate-scope irreversible` promises to
stop. Irreversibility is now DERIVED from the rule that matched, and a property test
asserts every reason in the set is a reason some rule actually emits.

- **A quoted secret may span lines.** `PASSWORD="alpha\nbeta"` redacted the first
  line and left the rest — which then scanned clean and would have been sent. The
  span is capped at 4096 characters so a stray quote cannot swallow a document.
- **`.txt` is no longer presumed inert.** The shortcut added to stop documentation
  false positives ran ahead of the risk rules, so `config/permissions.txt` was L0
  despite `permissions` being an L3 keyword.
- **Re-attesting can no longer shrink what the floor covers.** Rebinding evidence to
  a new HEAD overwrote the commit it originally bound to, so a dangerous commit
  attested L0 became invisible after one evidence-only commit.
- **An unreadable change set rejects instead of softening to L1.** A git timeout
  could hide an L3 path while a valid L1 report passed on green tests.
- **An attest that cannot lock refuses.** Warning loudly and running anyway left the
  "two attests never lose each other's evidence" guarantee false, with no trace.

## 2026-08-22 — round four: path collection (PROTOCOL v2.10.3)

The floor is only as good as the list of paths it is handed, and that list was
being built three separate times by three copies of the same git calls. The
copies drifted, and two of them lost paths in ways an author could exploit.

- **A rename hid the dangerous name.** `git diff --name-only` reports only the
  destination, so moving `src/authGuard.ts` to `src/guard.ts` turned an auth
  change into an unrecognised source file. Collection now passes `--no-renames`
  and both sides are seen.
- **A path git would quote was torn in half.** Names containing a newline or tab
  are C-quoted, and splitting on lines produced two fragments that matched
  nothing. Collection is now NUL-separated. Whitespace also counts as a keyword
  boundary, so a weird name can only classify higher, never lower.
- **classify and gate now share one collector.** They had drifted to the point
  where the same repo reported different paths depending on which command ran,
  and a test now asserts they agree.
- **An unresolvable `--base` is a usage error.** It used to soften to an L1
  floor, so a valid L1 report gated successfully over a range that was never
  read.
- **The narrowed human stop judges the committed range.** It was reading the
  worktree only, so after an attestation the sole visible path was the untracked
  report — which matches nothing irreversible, waving a committed authz change
  through without ever looking at it.
- **A cap that cannot lock now refuses.** The fallback silently recreated the
  race at the exact moment the guarantee mattered. `COVERLOOP_ALLOW_UNLOCKED_CAP=1`
  opts back in, deliberately.

## 2026-08-22 — rounds three and four (PROTOCOL v2.10.2)

- **The floor stopped crying danger at UI components.** The camelCase boundary that
  rescued `workerPool.ts` also swept in every PascalCase component whose name starts
  with a keyword: `ModelViewer.tsx` read as a data model, `ContextMenu.tsx` as React
  context, `RoutePlanner.tsx` as a router. Keywords are now split — the dangerous ones
  (auth, credentials, billing, worker) still accept any casing, so `AuthGuard.tsx`
  stays L3, while the ones that collide with component naming accept the hump only in
  lowercase. Directory and dotted forms are untouched.
- **The daily cap is genuinely safe in parallel now.** The check sat about fifteen
  lines before the attempt was recorded, so two reviewers on different projects could
  both read cap-1 and both send. Reserving the slot and writing the preflight audit
  record are now one step under an exclusive lock. Verified with twelve concurrent
  processes against a cap of five: exactly five sent.
- **The gate stopped importing on Python 3.9.** The ReDoS fix reached for a possessive
  quantifier, which needs 3.11 — on the 3.9 job in this repo's own CI it is a syntax
  error at import time, so `coverloop` did not start at all. The `{1,64}` bound was
  what made the pattern linear; the possessive added nothing. A guard now greps the
  shipped sources for regex syntax newer than the oldest supported Python, because
  every local check ran on 3.13 and stayed green.

## 2026-08-22 — the release reviews itself, and the review found five fail-opens (PROTOCOL v2.10.1)

v2.10.0 shipped `classify` and the claim that the risk tier is no longer the author's
to declare. Running this repo's own protocol against that release — a cold diff, a fresh
session, a reviewer with no stake in the answer — showed the claim was not yet true, and
turned up four more holes. Every one was verified against the code before it was fixed,
and every one now has a regression test.

- **The gate did not apply its own floor.** `classify` was a command you had to remember
  to wire, so `gate --min-tier L0` still passed over a migration. The floor now runs
  inside `gate`, unconditionally. There is deliberately no flag to switch it off — a
  switch is the hole.
- **camelCase names fell through to L1.** The boundary required `/`, `.`, `_` or `-`
  right after the keyword, so `authorization.ts`, `credentialsManager.go`,
  `workerPool.ts` and `schemaVersion.py` — ordinary auth, credential, worker and schema
  files — classified as routine. The boundary now also accepts a camelCase hump, and
  because the rules compile case-insensitively that hump is matched case-sensitively on
  purpose: without that, `author.ts` and `keyboard.tsx` read as L3, and a floor that
  cries danger at prose teaches people to bypass the gate.
- **An escaped quote leaked the tail of a secret.** `PASSWORD="a\" b"` redacted only up
  to the escaped quote; the remainder stayed in the packet and then scanned *clean*, so
  the egress tripwire passed it to the network. The value pattern now consumes an escaped
  pair as a unit, with disjoint branches so the egress path stays linear.
- **The daily cap could stop counting.** `egress_cap` honoured `COVERLOOP_EGRESS_LOG`
  while the reviewer CLIs hardcoded the default, so relocating the log left the cap
  reading a file nobody wrote to — zero usage, every request allowed. Both now resolve
  through one helper.
- **The contract promised more than the code did.** The L3 row still read as an
  unconditional human stop after `--human-gate-scope irreversible` shipped. The row now
  says what the flag does, what it does not touch (the review, and the tier), and that
  choosing it is a recorded loosening rather than the default.

The uncomfortable part is the shape of this list: the drift it describes is the same
attest-then-drift failure this repo's own field audit documents, committed by the person
who wrote the audit, in the week he wrote it. That is the argument for the gate, not
against it — the findings came from a reviewer that could not be talked out of them.

## 2026-08-22 — `coverloop classify`: the risk tier stops being self-declared (PROTOCOL v2.10.0, CONTRACT v2.8)

Every gate keys off the risk tier, but the tier was **declared** at `init`. A change mislabelled L1
skipped the L3 gates **silently** — no alarm, no evidence that anything was skipped. That was the one
place the whole chain could be defeated by a typo or by optimism, and `docs/GATE.md` had always been
honest that the tier is self-declared unless CI supplies a floor.

**New `coverloop classify`** derives a FLOOR from the paths that actually changed:
migrations/`.sql`/schema, auth·authz·RLS·permissions, billing·payments·checkout, secrets·`.env`,
CI/deploy config, workers·cron·queues -> **L3**; API/routes/middleware, shared state, dependency
manifests -> **L2**; docs/styles/repo metadata -> **L0**; **anything unrecognised -> L1, never L0**
(silence is not evidence of safety); **10+ files -> at least L2** (breadth is itself a risk signal).
`--base REF` classifies a branch, `--quiet` prints just the tier for
`coverloop gate --min-tier "$(coverloop classify --quiet)"`. Reasons are printed with the matching
file, so the verdict is auditable rather than asserted.

**Direction is one-way.** `classify` emits a floor; `gate` already takes the MAX over every floor and
the report's tier, and `attest --tier` already refuses to downgrade. AI or human may **raise** a tier;
neither may lower a deterministic floor.

**Two deliberate design choices.** (1) **Path-based, not content-sniffing**: paths are cheap, stable and
reviewable, and dodging L3 by renaming a migration out of `migrations/` requires something *visible in
the diff*; content heuristics are easy to defeat with formatting and yield false negatives that read
like safety. (2) **App-code rules are scoped to source extensions** — unscoped, `hooks/` matched this
repo's own shell hooks and over-classified them L2. Over-classification is not free: a floor that cries
L2 at a shell script trains people to bypass the gate, and a bypassed gate protects nothing. That
false positive was caught while building the rules and is pinned by a regression test.

Wired into the contract (§2a), the Session Start ritual, and `hooks/session-contract.sh` so it survives
compaction. 10 new tests (163 total, green).

**Honesty fix in the same release.** The README claimed *"every bug has to find a gap, and Coverloop
covers every gap."* That is false and, in a safety tool, actively harmful — it manufactures the exact
confidence the protocol exists to withhold. Replaced with the honest claim: **Coverloop does not make
AI coding safe; it makes unsafe assumptions harder to ship unnoticed** — cited against
[c-CRAB](https://arxiv.org/abs/2603.23448), which found leading review agents solve only ~40% of review
tasks between them. `docs/EGRESS_SANDBOX.md` likewise softened "the core privacy guarantee" to "the core
privacy controls", pointing at `redact()` and its documented residual false-negatives.

## 2026-07-27 — §9b next-task model recommendation (PROTOCOL v2.9.0, CONTRACT v2.7)

Operator-directed. Every response that ends with a next task must now close with ONE line naming the
Claude Code **model + reasoning effort** to run that task on, so a task is never spent on a model that
costs far more than it needs (or a cheap one on an L3).

**New §9b** — format `▸ Next: <task> → <model> · <effort> effort — <why>`, with a routing table tied to
the §2 risk tiers: L0 mechanical → Haiku 4.5/low · L1 → Sonnet 5/medium · L2 → Sonnet 5/high ·
L3 (money/auth·RLS, migrations, schema, concurrency, architecture, hard debugging) → Opus 5/high→xhigh ·
deadlock → Opus 5/max (one shot, then escalate). Binding rules: classify risk FIRST (tie → heavier) and
read the model off the tier — **never downgrade a real L3 to save tokens**; effort is a dial, not a
default; **recommend only, never self-switch the model** (the operator runs `/model`); no next task ⇒ no
line. It also flags the inverse case — a scary-sounding task that is really L0/L1 — since surfacing that
gap is the point of the rule.

**Fable 5 deprecated for routine work:** capped at ~50% of the weekly limit and draws down faster than
Opus; the fleet moved to `claude-opus-5` on 2026-07-27 after a live session hit a hard
"You've reached your Fable 5 limit" wall (Fable sessions were degraded, not merely "a different model").

CONTRACT_VERSION v2.6 → **v2.7** (contract content changed ⇒ one-time per-project resync).
Wired into `hooks/session-contract.sh` so it re-injects at session start **and after every compaction** —
the anti-drift path, since a rule that lives only in a doc read once is exactly what compaction discards.

## 2026-07-15 — secret-filter: scan()-side FP gate so review models can read auth code (v2026-07-15q)

Operator-directed maintenance (MusicArcademy PR-21 gate). `scan()` structurally could not review
Supabase auth-client code: `ASSIGN_RE` blocked `autoRefreshToken: true`, fixtures like
`access_token: 'at-1'`, references like `storageKey: platformStorageKey(url)`, and even its own
`[REDACTED:…]` markers, so every packet containing auth code was refused egress.

**Fix — scan() ONLY; `redact()` unchanged; no env/flag escape hatch.** A secret-family assignment is
CLEAN only when it is unambiguously code carrying a benign value; anything that reads as an
env/YAML/config dump, or carries an opaque literal, BLOCKS:
- `=` form, YAML block scalars (`|`/`>`), quoted opaque values (≥8), and every KNOWN secret SHAPE
  (`VALUE_PATTERNS`) → block; an exact `[REDACTED:…]` marker value → clean (scan∘redact idempotency,
  wins over `=` so a redacted env line never re-trips).
- A CODE-structured line (code punctuation at/after the value) is lexed once (parity-aware,
  quote/backtick-aware comment strip) for opaque quoted literals and non-identifier opaque barewords;
  a swallowed `;NAME=secret` env pair is caught (no `=>`/`===` false positive).
- A NON-code (env/YAML/prose) line blocks unless the value is a lone bool/null/identifier with no
  folded continuation. Linear (cached per-line signals), verified on word- and blank-storms.

**Hardened across 14 Codex (Sol) rounds** against: marker suffixes, `fn('…')` / backtick /
escaped-quote span tricks, YAML indentation indicators + folds (word-split, blank-line, colon-in-
scalar), swallowed `;NAME=` pairs, quadratic rescans, stateful pairing, val-level exits skipping
payloads, identifier-vs-secret map keys, and arrow-function `=>` / comment false positives.

**Accepted residual (operator decision, 2026-07-15).** `scan()` does NOT catch an unquoted
identifier-shaped value, or a value forced into the code branch by surrounding code punctuation
(braces / marker+prose / concatenation). Closing it re-introduces false positives on legitimate
TypeScript (`access_token: currentAccessToken`, `refreshToken: AuthenticationToken`,
`currentRt as string`, JSX). This is the inherent false-negative ↔ false-positive frontier of a
heuristic tripwire; the primary requirement (do not block real auth code) wins. `scan()` is an
egress TRIPWIRE, not a DLP — `redact()` is the primary data-protection layer, is unchanged, and
still strips these values shape-independently.

**Egress invariant (operator merge condition).** Both review CLIs (`bin/glm-review`, `bin/m3-review`)
now `redact()` every packet BEFORE scan and egress — there is no raw-packet path to any external
model. Enforced by `tests/test_properties.py::EgressRedactionInvariant` (integration-level: the real
CLI `main()` is driven with `do_request` captured; asserts the secret value never leaves, a redaction
marker is present, the egressed message equals `redact(raw)`, and a clean auth-code packet still
egresses). Trade recorded: because `redact()` is maximal, secret-family assignment VALUES are blanked
in the packet the reviewer sees (e.g. `autoRefreshToken: true` → `[REDACTED:…]`); all non-assignment
code (structure, control flow, prose) remains visible, which is sufficient for logic/structure review.

Tests: full suite green with the new boundary + invariant coverage. CONTRACT_VERSION unchanged
(tooling/code only, no project resync).

## v2.7.3 (2026-07-11) — full multi-lineage audit hardening
A professional whole-repo audit run through the loop itself — 5 Claude dimension reviewers + 3 real GPT-5.6 Sol passes + 2 real GLM red-teams (42 agents), 31 candidate findings, **each adversarially verified against the code** (18 real, 4 already-guarded, 2 false-positive). Verdict: architecture is frontier-grade, **no P0s**, but 4 real P1s (two defeating headline controls) put it just below a high professional bar — now fixed. **Cross-lineage convergence** was the highest-signal theme: Claude and Sol independently hit the same captured/attached trust-boundary from two angles; Claude and Sol independently hit the same secret-filter value-leak.
- **P1 — laundered failed capture (forged-evidence bypass):** a genuinely FAILED `--codex-run` (its committed log is the withheld-run placeholder) passed `verify_capture` — even `--require-executed` — after a single hand-edit of the un-hashed `exit_code` 1→0, because the withheld-marker content check was scoped to `source=="attached"`. Now **source-agnostic**: a withheld-marker log is rejected for captured too (no re-hash possible), closing the one-integer forge. Regression added.
- **P1 — `--require-executed` overclaimed:** an attached entry relabeled `source:"captured"` + `command`/`exit_code`/`ran_at` passed it, because those are unauthenticated attester JSON and the log is attester-authored — no on-disk field can PROVE execution against a committer who controls the tree. Resolved **honestly**: `--require-executed` is now documented (help + GATE.md threat model) as a best-effort policy filter, not proof; the misleading "a relabel keeps only attached fields" comment is corrected.
- **P1 — secret filter missed the `_KEY` family:** `AWS_SECRET_ACCESS_KEY`, `SECRET_KEY`, `ENCRYPTION_KEY`, `SIGNING_KEY`, `PRIVATE_KEY` matched no pattern, so `scan()` egressed them and `redact()` left them verbatim in committed transcripts. Added `[_-]KEY` to `ASSIGN_RE` (still skips `MONKEY=`); FILTER_VERSION → `2026-07-11a`.
- **P1 — Stop-hook fail-open on untracked files:** the change-aware short-circuit saw only tracked diffs, so a session with brand-new **untracked** source files (the default state of AI-written files) skipped the test gate entirely. Now also verifies when `git ls-files --others --exclude-standard` is non-empty (gitignored state/build files still skip).
- **P2 hardening:** quoted multi-word secrets now redact to the closing quote (was leaking the tail); all four evidence writers use `open_write` (`O_NOFOLLOW` — a pre-planted destination symlink can no longer redirect an evidence write off-tree — **and** `newline=""` so the byte-level sha256 matches on Windows); tier floors are monotonic (`--min-tier`/`--tier` are `action="append"`, folded through `tier_max` — a coexisting/repeated lower floor can't win); new opt-in `--require-clean-tree` for local pre-push drift; `load_report` shape-guards non-dict sub-objects (clean malformed FAIL, not an `AttributeError`); private-key regex bounded (`.{0,10000}?`) to kill quadratic ReDoS.
- **Hygiene:** `protocol-selftest` validates hook wiring DEPTH (non-empty arrays, real commands, a PreToolUse Bash matcher) not just key presence, and fixes a `grep -c` zero-match stderr leak; `install.sh` matches the parsed `command` field exactly (a `.disabled` hook no longer counts as wired); the jq-absent `pre-risky-git` branch matches raw input (was silently missing quoted commands); `CLAUDE.md` secret-filter description corrected (8 literal + 9 regex = 17 labels; parity anchored on FILTER_VERSION, not a bogus count).
- **Dogfood round 2 — Sol reviewed the fixes themselves and caught 3, all fixed:** the source-agnostic withheld-marker check false-rejected a genuine review that *quotes* the marker (now matches the whole placeholder LINE, not the substring — a self-review passes); `O_NOFOLLOW` silently no-ops where absent (Windows), so `open_write` gained a portable `os.path.islink` pre-check; the quoted-secret value group stopped at *either* quote type, leaking `PASSWORD="horse's staple"` — now spans to the *matching* delimiter via a backreference.
- Tests: 81 → **90**. CONTRACT_VERSION unchanged (v2.6) — this is tooling/code, no project resync.

## v2.7.2 (2026-07-10) — off-policy review + Sol routing (encode what the research verified)
Two adversarially-verified deep-research passes (one benchmarking the loop against the 2026 state of the art, one on GPT-5.6 Sol seat-by-seat) plus a Codex parity self-assessment produced this release. The verified headline: the strongest anti-bias lever is **off-policy packaging** — a reviewer that sees the change as a cold artifact in a fresh session misses far less (monitor code-correctness AUROC 0.99 off-policy vs 0.89–0.92 in-context); cross-lineage adds a smaller, directionally-supported layer. Independent SWE-bench (vals.ai, 2026-07-09) keeps the BUILD seat Anthropic (Fable 5 95.0 / Opus 4.8 88.6 vs best-listed-OpenAI 82.6), while Sol's own system card (more over-eagerness and severity-3 actions than its predecessor) argues for giving Sol the JUDGE seats, not the keys.
- **Off-policy review encoded** in the contract template, `CLAUDE.md`, and both hooks: the reviewer gets a COLD diff packet in a FRESH session — never "review what you just wrote" inside the builder's conversation. "Two same-vendor models aren't independent" is now honestly labeled a design assumption (its supporting mechanism was refuted in verification), not an evidence-backed law.
- **Sol gate routing:** canonical reviewer = `codex exec -m gpt-5.6-sol --sandbox read-only` with effort EXPLICIT per tier — `high` L2 · `xhigh` L3 · `max` design-red-team/deadlock-break · **never `ultra` for a gate** (it auto-delegates to subagents and burns quota; Sol's default is `low`, a lazy judge).
- **PII redaction (FILTER_VERSION `2026-07-10a`):** committed transcripts now also strip home-dir usernames (`/Users/<name>`, `/home/<name>`), emails, and UUID session ids — `redact()` only; `scan()`/egress unchanged by design. Docs downgraded from "never carries a secret" to the honest "tripwire, not DLP". (Trigger: a live captured transcript had committed a real home path — Codex parity-assessment finding.)
- **Honest flags:** `--require-transcript` replaces `--require-captured` (kept as a deprecated alias so pinned CI keeps working); new stricter `--require-executed` demands a coverloop-EXECUTED capture (attached rejected). **Fail-closed exit:** `attest` now returns non-zero when a `--*-run` reviewer command fails — the evidence was already fail-closed, but the exit code lied to automation.
- **CONTRACT_VERSION v2.5 → v2.6** (Sol v2.7.2 review #3 caught this): the roster + mechanics are contract CONTENT, so per §13 the label must bump — otherwise `protocol-selftest` in each project sees "v2.5 == v2.5" and the new off-policy/Sol rules silently never reach the inlined contracts. v2.6 is the FIRST genuine content change since the v2.5 version-agnostic decoupling; it triggers a one-time fleet contract-swap PR per project.
- **Wiring:** `AGENTS.md -> CLAUDE.md` symlink committed in this repo (a fresh Codex session here now auto-loads the contract); the advisor CLIs answer `--help`/`-h` before any parsing (previously `--help` was treated as review text); stale "currently v2.4" contract label fixed.
- **Dogfood — Sol (GPT-5.6, xhigh) cross-lineage review of this diff, off-policy, caught 4 real issues pre-release, all fixed + regression-locked:** (1) `--require-executed` accepted an attached entry hand-relabeled `source:captured`+`exit_code:0` → `verify_capture` now requires a captured entry to carry its execution fields (command/exit_code/ran_at); (2) PII home-path regex missed single-char/underscore usernames and leaked a long name's tail past its length cap → now matches the whole path component; (3) the CONTRACT_VERSION bump above; (4) an incomplete `--require-captured`→`--require-transcript` doc migration.
- **Field report folded in (a live Alex-project session's 14 lessons, same day):** (a) evidence-gitignore trap FIXED in code — `coverloop init` now writes negation rules (`!reports/*.log` …) so a repo-root `*.log` can't swallow committed transcripts, and `attest` FAILS when git ignores the evidence it just wrote (in the field, a captured transcript silently never reached the PR); (b) auth-tier reality documented — `gpt-5.6-sol` works on ChatGPT auth (verified Mac + VPS), the bare `gpt-5.6`/`-fast` tiers 400 without API-key auth; probe, don't chase CLI updates; (c) contract additions: audits cross-check `DECISIONS.md`/`STATE.md` before ranking (already-decided vs new), batch PRs BY TIER (standing "keep going" never covers L3), reflect-and-save keeps NEGATIVE results, evidence provenance (local vs CI vs manual) stated everywhere, branch-fresh-from-main after squash-merges + verify `origin/main` moved, prod-matches-design control-plane check before L3 conclusions; (d) review checklist: half-open interval math for time/money windows (a builder-vs-reviewer divergence caught a real money bug), privacy removals ship with a failing-if-it-returns guard.
- Tests: 72 → **81**.

## v2.7.1 (2026-07-08) — attached evidence (close the gap the field audit found)
A field audit of three real deployments (session transcripts + repos) showed the loop is genuinely USED — hundreds of attest/gate runs, evidence reports committed — but **every reviewer verdict was self-attested** (even L3s) and all three repos sat at `VERDICT: FAIL` on HEAD (evidence attested per-PR, then post-review fix commits landed unattested). Root cause of the first: reviews run interactively FIRST, and `--codex-run` means paying for the same review twice — so nobody took the strong path.
- **`attest --codex-log <file>` / `--glm-log <file>`** — attach the transcript of a review you ALREADY ran: redacted (same shared secret filter), copied to the canonical `.coverloop/reports/<sha>.<reviewer>.log`, hash-bound, committed. Recorded as `source: "attached"` — one honesty notch below `captured` (no execution/exit-code binding; documented in GATE.md), far above a bare claim. `gate --require-captured` accepts **captured OR attached**; the label-never-lies rule (missing/tampered/replayed transcript → evidence rejected outright) and the inheritance re-bind apply identically. Symlink, empty, and oversized (>5MB) sources are rejected; mutually exclusive with `--*-run`; the verdict stays caller-stated.
- **Hooks surface silent wiring gaps** (each one observed in the audit): SessionStart warns when `.coverloop/` exists without `.claude/loop.conf` (the Stop-hook gate silently OFF — the new-repo bootstrap gap) and when `docs/MEMORY.md` exceeds ~30 entries; the contract injection + pre-push reminder now say: attach transcripts via `--*-log`, **RE-ATTEST AT HEAD** when the gate reports stale evidence, and record an L3 `--approve` only for an operator-**named** action (a generic "go ahead" is not an approval).
- Clearer `gate` guidance when no report exists (attest at HEAD first, or state a `--min-tier` floor).
- **Dogfooded: TWO Codex rounds on this diff caught 7 real holes pre-release, all closed + regression-tested.** Round 1: (1) attaching the gate's OWN artifacts (`--codex-log .coverloop/reports/<sha>.codex.log`) could launder a withheld failed-run placeholder or replay an old commit's log → sources under `reports/` refused; (2) hand-editing a failed captured entry's `source` to `"attached"` dodged the exit-code check → execution fields on an attached entry rejected; (3) `errors="replace"` decoding could 3x a 5MB source into a 15MB committed artifact → size re-checked after decode+redaction; (4) `--require-captured` help/detail text contradicted the new semantics. Round 2 (on the fixed diff): (5) deleting the execution fields too still laundered the placeholder → withheld-marker CONTENT is rejected at attach and at gate; (6) the reports-dir guard was string-prefix only — `.COVERLOOP/REPORTS/…` bypassed it on case-insensitive filesystems → ancestor-directory inode comparison; (7) the inheritance re-bind trusted a forged ancestor report pointing at any OLD clean log → transcripts now verify against the ANCESTOR commit before re-binding.
- Tests: 56 → **72** (every hole above encoded as an invariant, plus: require-captured acceptance, redaction, tamper, symlink source, empty/oversize, verdict required, run/log exclusivity, inheritance re-bind).

## v2.7 (2026-07-05) — trustworthy gate (whole-system audit)
A 7-lens, 63-agent adversarial audit (keyed off the DOCS, not the diff) found the gate was **not trustworthy as shipped** — its own copy-paste CI recipe `gate --tier L2` silently *downgraded* a self-declared L3 change and merged it with no GLM and no human approval. 40 findings survived adversarial verification; v2.7 closes every confirmed fail-open and the privacy leak. **The lesson:** every prior review was diff-scoped ("is this hunk correct?"); these defects live in the *gap* between a prose promise and the code, which diff review never holds in one frame. The fix is **promise-vs-code auditing** — every doc guarantee is now encoded as a test invariant.
- **A — fail-opens (2 P0 + 4 P1):** (1) `--tier` was an OVERRIDE → now **`--min-tier` is a FLOOR**: `effective = max(pin, report_tier)`, so a pin can only RAISE requirements (`--tier` kept as a floor alias). (2) any file under `.coverloop/reports/` counted as evidence-only (`reports/backdoor.py` rode through) → now only exact `<sha>.json`/`<sha>.<reviewer>.log` artifacts. (3) `attest --tier` could silently downgrade a report → now **monotonic** (`--force` to override). (4) docs-only waiver matched doc names by basename anywhere / bare suffix (`src/CHANGELOG`, `docs/deploy.sh` waived tests) → now only real docs. (5) forged `tests: pass` gated green → the recorded test command must equal the project's current `test_command`.
- **B — privacy (the leak in a privacy tool):** captured transcripts, the reviewer command string, and failed-run output were committed to git **unscanned**. Now `capture_run` **redacts secret values** (via the shared `glm_secret_filter`) before writing, **withholds** a failed run's dump entirely, and the filter's patterns were extended from just `sk-` to GitHub/AWS/Slack/Google/bearer/JWT/DB-URL/private-key (FILTER_VERSION `2026-07-05a`). Non-UTF-8 reviewer output no longer crashes attest.
- **D — robustness:** a report JSON reached through a **symlink** is rejected (mirrors the transcript guard); the weakest test now asserts the *specific* check so a waiver-leak regression can't ship green.
- **Tests:** 39 → **51**, each closed hole encoded as a regression invariant. Deferred to **v2.8** (ergonomics, not trust): `coverloop classify` + `coverloop run`, and git-tracked-evidence enforcement (#13, already fails-closed in real CI).

## v2.6.2 (2026-07-05) — enforce captured evidence
Follows a review noting that capture existed but wasn't *enforceable*, plus a stale docstring.
- **`coverloop gate --require-captured`** — at L2/L3, a reviewer verdict that is merely self-attested now **fails** the gate; the report must carry a captured (hashed) transcript for Codex (L2+) and GLM (L3). The CI example enables it (`--tier L2 --require-captured`), so a bare "codex pass" can no longer merge — only a committed, hashed reviewer run does. Reviewer checks refactored into one `reviewer_check()` helper.
- **Codex caught FOUR fail-opens in `--require-captured` across four dogfooded review rounds** — the enforcement feature got the enforcement it preaches: (1) the first cut only checked the string `source == "captured"`; (2) a committed transcript **symlink** could point outside `reports/`; (3) **replay** — a new commit could cite an *older* CLEAN transcript; (4) a **failed reviewer run** (nonzero exit — expired auth, missing binary, a hang) was captured and accepted as valid evidence. All fixed in `verify_capture()`: a `captured` verdict is accepted only if the reviewer command **exited 0**, `output_file` is **exactly** `.coverloop/reports/<this-commit>.<reviewer>.log` (binds commit + reviewer → no replay), no component of the reports path is a **symlink** and the log resolves inside `reports/` (no escape), and the bytes hash to the recorded digest (no tampering). Any violation fails the gate even without `--require-captured`; `attest` warns when a captured command exits nonzero; inheritance re-binds captured logs so the evidence-only flow still works. Regression-tested (forged / tampered / traversal / replay / symlink / reports-dir-symlink / failed-exit / inheritance); suite 31 → **39 cases**. The remaining ceiling is documented honestly in `docs/GATE.md`: a committer can still run a fake reviewer that emits "CLEAN" — that needs a server-side/GitHub-App check (roadmap).
- **Docstring fix** — the top-of-file design note claimed `attest` never runs reviewers except tests; corrected to describe `--codex-run`/`--glm-run` capture (the code already did this — a doc/code mismatch a sharp reader would catch).
- CI example + docs pinned to `v2.6.2`.

## v2.6.1 (2026-07-03) — captured evidence + honest limits
From a second external review of the v2.6 gate whose core point was right: the evidence was still *self-attested*. This release makes it capturable and pins the supply chain.
- **Captured (tool-produced) evidence** — `coverloop attest --codex pass --codex-run "<cmd>"` (and `--glm-run`) executes the reviewer, writes its full output to `.coverloop/reports/<sha>.<reviewer>.log` (committed with the change), and records the log's **sha256** in the report. The verdict is still caller-stated (reviewer output is prose), but it is now backed by a hashed, PR-visible transcript instead of a bare claim. `coverloop gate` labels every verdict `[captured <hash>]` or `[self-attested]` so reviewers/CI can tell them apart.
- **Pinned CI** — the GitHub Actions example now pins `coverloop` to a **release tag** (`v2.6.0`), not `main` (don't run live external code in CI), and pins a **risk floor** (`--tier L2`) so a PR can't dodge review by self-declaring a lower tier.
- **Honest limits documented** in README + `docs/GATE.md`: capture raises the cost/visibility of lying but isn't cryptographic proof; tier is self-declared unless pinned; human approval is *named*, not GitHub-authenticated (planned `--require-github-approval`). Fixed a stale "17 cases" README line (suite is now **29 cases**).

## v2.6 (2026-07-03) — enforcement ("a gate, not a sticky note")
No contract change — **projects need NO resync**; machines just `git pull && ./install.sh`.
Born from an outside review whose sharpest line was *"this is not a safety layer yet — it's a disciplined local workflow with good taste."* Correct: the hooks remind, nothing blocked. v2.6 adds the blocking layer:
- **`bin/coverloop`** — a fail-closed evidence gate (`init` / `attest` / `gate`). Evidence lives in `.coverloop/reports/<sha>.json`, committed with the change (PR-visible artifact, not a chat-log claim). `gate` exits non-zero unless the tier's required evidence governs HEAD: L1 tests (docs-only diffs waived), L2 + Codex pass with 0 open findings, L3 + GLM pass + **named** human approval. Evidence-only commits ride along (a report bound to an ancestor is accepted ONLY when the diff to HEAD touches nothing but report files); any code change after attestation invalidates the evidence; corrupt/forged/SHA-mismatched reports fail EVERY tier. The gate never sends code anywhere and never calls a model.
- **The gate's own review rounds proved the loop (dogfood):** Codex reviewed the gate's diff over **three rounds** before merge, and every round caught real defects the builder + green tests missed — the enforcement code got the enforcement it preaches:
  - **Round 1 — P0** the evidence-commit paradox: `attest` binds to HEAD, but committing the report creates a NEW head, so CI could never find the evidence for the commit carrying it — the documented flow was *impossible*. (+ P1 config didn't fail non-L0, P2 malformed reports passed at L0, P2 `--ci` ignored with `--json`.)
  - **Round 2 — P0** the round-1 fix checked out GitHub's synthetic merge commit, whose first-parent chain walks the *base* branch where the evidence doesn't exist; **P1** a code file renamed into `docs/`/`reports/` could smuggle past the waivers (fixed with `--no-renames`); + 2 doc/code mismatches.
  - **Round 3 — P1** the L1 docs-only waiver trusted `default_base` from `.coverloop/config.json`, but that file ships *inside the PR* — set `default_base=HEAD~1` and the waiver diff skips your own code change. Fixed: the waiver trusts ONLY a `--base` passed by the caller (CI), never in-repo config; `default_base` removed from config entirely.
  - Each round's fixes were regression-tested; the suite grew 17 → 26 cases. Remaining honest residual (documented in `docs/GATE.md`): the tier is self-declared unless CI pins `--tier`.
- **CI enforcement** — `coverloop gate --ci` + a copy-paste GitHub Actions workflow (`examples/github-actions-coverloop.yml`); make `coverloop / gate` a required check and an unreviewed change physically cannot merge. Docs + honest threat model: `docs/GATE.md`.
- **Waiver semantics** (caught by the gate's own test suite): report files are waivable in docs-only diffs (they ARE the evidence and ride along with every change); `.coverloop/config.json` is NEVER waivable — it alters gate behavior.
- **Tests**: `tests/test_gate.py` — 17 cases on real temporary git repos, stdlib only.
- Language rule going forward: hooks are described as *advisory*; "enforceable" refers to the gate.

## v2.5 (2026-07-02) — efficiency + measurement ("prove it, cheaply")
No contract change — **projects need NO resync**; machines just `git pull && ./install.sh`.
- **v2.5 refinements (2026-07-02, from a live L3 review loop):** (a) `skills/multimodel-review` — give reviewers full cross-file CONTEXT, not just the raw diff (the #1 false-positive source: M3 flagged `confirmClock` as undefined because it only saw the diff). (b) §9a — **cosmetic-change carve-out**: a post-review fix whose diff touches only comments/strings/docs (tsc+tests provably unaffected) is fixed-and-noted, NOT sent through a fresh review round. Both born from the loop catching its own over-application in real time.
- **v2.5 refinements #2 (2026-07-02, from a live multi-PR merge train):** (c) §9a — repeated REAL findings past the round cap = a SIZE signal → split the PR, don't grind (one PR needed 5 Codex rounds). (d) §9a — **batch-merge integration gate**: after serial-merging a sweep of PRs with rebases, the unified `main` is a state no single PR's CI validated → run full suite + typecheck + one cumulative-diff review on the union.
- **Contract/Protocol decoupling (§13):** `CONTRACT_VERSION` (the block inlined in each project's `CLAUDE.md`, currently v2.4) now bumps ONLY when the contract's content changes; `PROTOCOL_VERSION` bumps freely. Ends the fleet-resync tax on every doc release.
- **`bin/protocol-selftest`** — ONE command that mechanizes the §12 install checklist + drift detection: version consistency (repo doc / hook banner / project contract), hooks wired, CLIs + filter parity, gh auth, loop.conf cheapness, project artifacts (MEMORY/RISK_MAP/REVIEW_LEDGER). Session Start step 1 is now "run it and report".
- **Measurement loop (§10c):** every multi-model review appends one line to the project's `docs/REVIEW_LEDGER.md` "Review log" (tier · reviewers · findings · verdicts); quarterly, read the log and SUBTRACT any reviewer/gate that isn't earning its keep. Mechanizes "M3 must prove its keep".
- **Memory hygiene (§10a):** `docs/MEMORY.md` capped (~30 entries — consolidate, don't hoard); `reflect-staging.md` auto-rotates (hook keeps the newest ~300 lines).
- **Model tiering (§9):** route mechanical sub-tasks (bulk reads, sweeps, formatting) to cheaper models/subagents; reserve the frontier model + high effort for design/build/debug of the hard parts.
- Header history moved to this file (was ~4.7KB re-read by every session).

## v2.4 (2026-07-01) — wired + anti-drift
Every item is a failure mode we actually hit in production sessions, promoted to a rule: **(1) Anti-drift wiring** — the Operating Contract must be **INLINED in the auto-loaded `CLAUDE.md`** (project-root CLAUDE.md is re-read after every context compaction; a `docs/` side-file read once is summarized away — THE root cause of sessions "forgetting" the protocol). A `SessionStart` hook re-injects the standing rules at start + after each compaction; a `PreToolUse` hook re-states the gate checklist right before push/merge/migration/deploy. **(2) §7a Environment & test-harness parity** — per-env matrix, friction-free local auth, seeded admin/customer fixtures, the two-strikes rule, PII-safe own-DB reads. **(3) Background-task hygiene** (§9.6) — reap finished background jobs, one dev server max (long sessions had piled up 50+ stale tasks). **(4) Codex Linux sandbox prerequisite** — Ubuntu 23.10+/24.04's userns clamp breaks Codex's bwrap; fix the OS at root (`docs/CODEX_SANDBOX_LINUX.md`), NEVER bypass a tool's sandbox, an agent NEVER self-grants a bypass (Model-unreachable rule (f)). **(5) Portable memory** — durable lessons live in git-tracked `docs/MEMORY.md`, not machine-local stores. **(6) Turnkey install** — `install.sh` auto-wires all 4 hooks (the HUMAN runs it; the agent clones + inspects); `init-project.sh` scaffolds per-repo artifacts; on a VPS authenticate `gh` FIRST; enable `delete_branch_on_merge`.

## v2.3 (2026-06-28) — enforce + subtract
Two research tracks (frontier sources + the 11 top-starred OSS agent repos) independently agreed v2.2 is already frontier-grade for a solo founder — so v2.3 ENFORCES existing gates and SUBTRACTS rarely-firing parts rather than adding models. New: a mechanical test-gate, auto-failure-capture, and a false-positive ledger (§10b); the agreement signal demoted to a triage hint (models co-hallucinate); security tripwires (egress allowlist/sandbox, `dep-check` slopsquatting gate, MCP-untrust, memory provenance guard); explicit right-sizing (audit M3 — drop below L3 / if it fires on <~10% of work) (§10c).

## v2.2 (2026-06-28) — self-improving loop
Hermes-style loop: (a) **reflect & save** — at the end of each meaningful task, persist durable lessons to memory (the model isn't retrained; it keeps better notes); (b) **skills** — capture recurring workflows as reusable `SKILL.md` recipes. Ships `reflect-and-save` and `multimodel-review`.

## v2.1 (2026-06-28) — evidence-backed refinement (from v2.0)
Driven by a cited deep-research pass + a real GLM-vs-M3 bake-off on live code: **(1)** Execution/tests are the PRIMARY correctness gate; LLM auditors are secondary, used where execution can't verify (architecture, schema/deploy consistency, security, invariants). **(2)** The second wide-context auditor (M3) is reserved for L2/L3 and must *prove its keep* — measured data shows ~93% of real findings come from a SINGLE auditor, so agreement is rare-but-strong and a single-tool finding is the norm (verify it, don't discard it). **(3)** Reviewers flag correctness/requirement gaps ONLY (standalone LLM reviewers over-report; ~6–16% precision). **(4)** M3 un-parked on your VPS under `data_collection:deny` (NOT full ZDR; GLM stays the full-ZDR path). Mac M3 stays parked.
