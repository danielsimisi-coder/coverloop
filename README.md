<div align="center">

<img src="assets/coverloop-banner.svg" alt="Coverloop — cover every angle before you ship" width="100%">

<h3>Never let the model that wrote the code be the one that approves it.</h3>

**AI writes your production code in minutes — and can ship a production outage just as fast.**
Coverloop is the **safety layer** that lets founders keep AI's speed without betting the company on it.

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-34E0B4?style=flat-square)](LICENSE)
[![For AI-coding founders](https://img.shields.io/badge/for-AI--coding%20founders-7C7CFF?style=flat-square)](#who-its-for)
[![Built for Claude Code](https://img.shields.io/badge/built%20for-Claude%20Code-D97757?style=flat-square)](https://claude.com/claude-code)
[![Reviewers](https://img.shields.io/badge/reviewers-Codex%20·%20GLM%20·%20M3-22C7E6?style=flat-square)](#why-it-works)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-34E0B4?style=flat-square)](#contributing)

[**Install**](#-install-in-60-seconds) · [**See it catch a bug**](#-watch-it-catch-a-bug) · [**Why it works**](#why-it-works) · [**The clever bits**](#-the-clever-bits)

</div>

---

## The 3am question

> *"Did the AI just open a security hole, drop a column, or break checkout — and I won't find out until a customer does?"*

You shipped fast because AI wrote most of it. But **one model reviewing its own work is a model grading its own exam.** Coverloop makes a change earn its way to production: one model builds it, **independent** models attack it from every angle, your tests get the deciding vote, and **you** hold the gate on anything that can hurt.

|  | 😬 Without Coverloop | ✅ With Coverloop |
|---|---|---|
| **Path to prod** | `AI writes code → deploy → 🤞 hope` | `AI writes → Codex → GLM → tests → you → deploy` |
| **Who reviews** | the model that wrote it | independent models + your tests + you |
| **You find bugs** | from an angry customer | before merge |
| **Secrets** | pasted into calls by accident | blocked at the tool layer |
| **At 3am** | you're awake | you're asleep |

---

## ⚡ Install in 60 seconds

```bash
git clone https://github.com/danielsimisi-coder/coverloop.git
cd coverloop && ./install.sh
```

✅ **Done.** Add your model key, then verify everything in one command:

```bash
printf '%s' 'sk-or-...' > ~/.config/openrouter/api_key && chmod 600 ~/.config/openrouter/api_key
~/bin/protocol-selftest
```

> **What you need:** [Claude Code](https://claude.com/claude-code) · Python 3 + git · an [OpenRouter](https://openrouter.ai) key (a few ¢/review) · [Codex CLI](https://developers.openai.com/codex/cli) recommended. **Mac/Linux** (Windows → [WSL](https://learn.microsoft.com/windows/wsl/install)). **No server or VPS.**
> Full walkthrough (machine → project → session): [`docs/SESSION_BOOTSTRAP.md`](docs/SESSION_BOOTSTRAP.md)

### 🔒 Make it unskippable — `coverloop gate`

Reminders are for people who already behave. For everyone else there's an **enforceable, fail-closed gate**: every review records evidence into `.coverloop/reports/<commit>.json` (committed with the change, visible in the PR), and `coverloop gate` exits non-zero unless the evidence governing that commit is complete — tests green, reviews passed, and for dangerous changes a *named* human approval. Evidence-only commits ride along; **any code change after attestation invalidates the evidence by construction.**

```bash
coverloop init                                  # once per repo
coverloop attest --tier L2 --tests              # run + record tests
coverloop attest --codex pass                   # record the independent review
coverloop gate                                  # exit 0 only if the tier's evidence is complete
```

Add `--codex-run "<cmd>"` and the tool **runs the reviewer and commits its hashed output** as evidence — or, for the review you **already ran interactively**, `--codex-log <file>` attaches its transcript (redacted, hashed, committed) with **no re-run**. The gate labels each verdict `[captured <hash>]` / `[attached <hash>]` vs `[self-attested]`, so a reviewer can tell a real transcript from a bare claim. Wire it as a **required GitHub check** ([copy-paste workflow](examples/github-actions-coverloop.yml), SHA+checksum-pinned) — and once you also turn on branch protection, a change with missing evidence can't merge without either the evidence or a human explicitly overriding the check (the honest ceiling — see the limits note below and [`docs/GATE.md`](docs/GATE.md)).

**Here's the whole idea in one real session** — captured verbatim from Coverloop gating its own repo (only long paths elided). The gate blocks an unreviewed change, the loop earns the evidence (real test run + a GPT-5.6 cross-vendor review, hashed), and the same command opens:

<p align="center"><img src="assets/coverloop-gate-demo.svg" width="880" alt="Real coverloop session: gate FAILs an unreviewed change (tests + codex NO RECORD, exit 1) → attest runs the tests and captures a gpt-5.6-sol review → the same gate PASSes with a hashed transcript (exit 0)"></p>

<details>
<summary><b>…and the same change, seen by the other two reviewers (also real transcripts)</b></summary>

<br/>

Different training lineages catch different things — that's the whole point of a multi-model loop. Here is the *same code*, red-teamed by **GLM-5.2** (full zero-data-retention) and audited by **MiniMax M3** (a fourth-lineage divergence voice), captured verbatim:

<p align="center"><img src="assets/coverloop-glm-review.svg" width="880" alt="Real GLM-5.2 red-team transcript: REQUEST CHANGES, flags a path-traversal risk, and independently recommends the exact captured-execution-fields fix that GPT-5.6 Sol also reached — two different labs, same catch"></p>

<p align="center"><img src="assets/coverloop-m3-review.svg" width="880" alt="Real MiniMax M3 audit transcript: its egress filter refuses a hunk containing secret names (fail-closed), then on a clean hunk it produces a severity-ranked audit table — divergence findings that are then verified against the full code"></p>

**Two things these show that a single reviewer can't:** GLM independently reached the *exact* fix GPT-5.6 Sol did (cross-lineage convergence is a strong signal a finding is real), and M3's egress filter *refused to send* a hunk containing secret names — the privacy layer failing closed, not on prompt discipline. No model is an authority: every finding is then checked against the real code.

</details>

> **Honest about the limits** (full detail in [`docs/GATE.md`](docs/GATE.md)): a bare `attest --codex pass` is a committed *claim* — back it with a transcript (`--codex-run` executes and captures; `--codex-log` attaches an existing one, honest label included), and `gate --require-transcript` makes CI **reject** anything less (`--require-executed` is stricter: coverloop must have run the reviewer itself; `--require-captured` remains as a deprecated alias). The risk tier is self-declared unless CI pins a floor (`--min-tier L2`). Human approval is *named*, not GitHub-authenticated (that's on the roadmap) — but `gate --require-signed-commit` adds **cryptographic provenance**: it demands HEAD carry a git-verifiable signature from a *trusted* key (checked against your git trust, or a **repo-committed signer policy** read from the committed tree), so evidence can't be replayed onto a forged or unsigned commit. Transcript redaction covers **known secret + PII patterns** (keys, tokens, DB creds, home-dir usernames, emails, session UUIDs) — a tripwire, not a full DLP guarantee. The gate raises the cost and visibility of lying; it doesn't make lying impossible. That's the honest ceiling for a tool that runs on your machine.

---

## 🎬 Watch it catch a bug

You ask for a routine change. It touches the database → Coverloop treats it as **dangerous (L3)** and the full loop kicks in:

> **You:** *"Rename the `status` column to `state` and migrate the data."*
>
> **🤖 Builder** writes a migration — but it **drops** the old column instead of renaming it.
>
> **🔍 Codex:** *"Wait — this migration is destructive and has no rollback."*
>
> **🧠 GLM:** *"That rollback is impossible. Once this runs, the data is gone."*
>
> **✅ Tests:** ❌ the migration test fails in a prod-like run.
>
> **🛑 Coverloop:** stops the loop and asks **you** to approve before anything touches the database.
>
> **You:** never even saw the bug.

Claude didn't save you. Codex didn't save you. GLM didn't save you. **The loop saved you** — because every bug has to find a gap, and Coverloop covers every gap.

---

## 🐛 Real bugs it caught — in its own code

Coverloop was **built using Coverloop.** Its reviewers caught real bugs in its own tooling *before* they ever merged — a few:

> **The self-audit that says it best:** on an already-public, 80-test release, a full multi-lineage pass (Claude + GPT-5.6 Sol + GLM-5.2, 42 agents, every finding verified against the code) found **0 critical and 4 real high-severity bugs** — including one where a *failed* review could be laundered into a passing one by editing a single digit. The fixes were then reviewed by GPT-5.6, which caught **3 more bugs in the fixes themselves.** All closed, all regression-locked (90 tests). *This is what "no model is an authority" looks like in practice.*

| The bug | Who caught it | What it would've done |
|---|---|---|
| **Two rival labs, one catch:** GPT-5.6 Sol **and** GLM-5.2 *independently* reached the exact same fix on the gate's own evidence code — a forged reviewer entry could otherwise pass the strictest check | **Sol + GLM** (cross-lineage) | The strongest signal a finding is real: convergence across training lineages, not a shared hallucination ([transcripts above](#-watch-it-catch-a-bug)) |
| The privacy tool was **committing your home-directory username** (and emails, session IDs) into review transcripts in git — secrets were redacted, personal identifiers weren't | **Codex/Sol** (parity audit) | A "privacy" tool quietly leaking PII into your public history |
| **A P0 in `coverloop gate` itself:** committing the evidence report creates a new commit, so CI could never find the evidence for the commit carrying it — the documented flow was impossible. The builder missed it. **All 17 tests that existed then were green.** | **Codex** (diff review) | The flagship enforcement feature would have shipped broken — every CI run failing forever ([see CHANGELOG v2.6](CHANGELOG.md)) |
| A model call **sent your data before** the privacy guard's failure-check ran; and an exported env var could **silently override** the zero-data-retention routing | **Codex** (diff review) | A payload leaving your machine even when it should've been blocked — routed to a non-ZDR endpoint without you knowing |

*(Have Coverloop caught something in **your** codebase? [Open a PR](#contributing) and I'll feature it here.)*

---

## Why it works

<p align="center"><img src="assets/coverloop-how-it-works.svg" width="100%" alt="How Coverloop works: you request a change → an AI builder writes the diff → independent models (Codex for correctness, GLM·M3 for security/audit) and your tests attack it, findings verified against the real code → the fail-closed Coverloop gate opens only on complete, hashed, commit-bound evidence → you hold the final gate on dangerous changes → ship. Findings or red tests loop back to a fix. Review scales to risk from L0 (trivial) to L3 (money/auth/DB → full loop + your gate)."></p>

**No model is an authority.** Every finding is a *claim* — verified against real code, tests, and runtime before it can block anything. Two models agreeing can just mean two models hallucinating the same thing, so **execution beats opinion**: when a test can settle it, you run the test.

**Right-sized, never bloated.** A typo doesn't get a committee. Coverloop scales the review to the blast radius:

| Risk | Example | What it gets |
|:---:|---|---|
| **L0** trivial | copy, CSS | quick check |
| **L1** normal | isolated fix | tests + typecheck |
| **L2** product flow | onboarding, admin UX | ➕ mandatory independent review |
| **L3** dangerous | money, auth, migrations, deploy, secrets | full suite + red-team + 2nd auditor + **your gate** |

---

## 🧠 The clever bits

The non-obvious decisions — each born from a real failure — that make Coverloop actually work instead of just sounding good:

- 🎭 **Agreement isn't proof.** Two models agreeing can mean two models hallucinating the *same* thing — so agreement is a triage hint, never a verdict. Findings are checked against real code and tests.
- 📍 **Every finding must cite `file:line`.** Vague "this looks risky" with no evidence is discarded as noise — killing the over-reporting that makes solo AI reviewers exhausting.
- 📒 **A false-positive ledger.** Once a finding is judged wrong, it's logged and **never re-raised**. Reviewers stop re-litigating settled points.
- ✂️ **"Split, don't grind."** If the same real issues keep resurfacing past a round cap, that's a signal the change is **too big** — it tells you to split the PR instead of looping forever.
- 🎨 **Cosmetic carve-out.** A fix touching only comments/strings/docs (tests provably unaffected) is noted, not pushed through a fresh paid review round.
- 🧬 **Batch-merge integration gate.** After you merge a stack of PRs, the combined `main` is a state **no single PR's CI ever tested** — so it runs one cumulative review on the union.
- ✌️ **Two-strikes rule.** If the AI makes you do the same manual workaround twice, it must **stop and fix the root cause** — no death by a thousand papercuts.
- 🔐 **The agent can't weaken its own safety.** If a sandbox blocks it, it fixes the environment at the root — it's *forbidden* from granting itself a bypass.
- 🛡️ **Even reading your own database is privacy-bound.** It pulls only the non-personal columns it needs — your customers' data doesn't get swept into a model call.
- 💸 **Cheap work goes to cheap models.** Bulk reads and sweeps route to cheaper models; the frontier model is saved for the hard parts. Lower bill, same quality.
- 🧩 **Reviewers get full context, not just the diff** — the #1 cause of false alarms is a reviewer judging 5 lines with no surrounding code.
- 🔗 **One source of truth, zero drift.** `AGENTS.md` is a symlink to `CLAUDE.md`, so every tool reads the exact same rules.
- 🧾 **Audit trail with zero exposure.** Every model call is logged as a **hash** — a provable record of what left your machine, without the log ever containing your code or secrets.
- 🔏 **Provenance, not just claims.** `gate --require-signed-commit` binds the evidence to a git-verifiable signature from a *trusted* key — your git trust, or a **repo-committed signer policy read from the committed tree** — so a report can't be replayed onto a forged or unsigned commit.
- ⚛️ **Evidence writes are atomic and race-safe.** Reports are written to a temp file and atomically renamed into place, and concurrent `attest`s are serialized by a lock — so a gate reading mid-write never sees a torn report, and two attests never silently lose each other's evidence.
- 🧪 **The privacy filter is fuzz-tested against itself.** Property tests and adversarial corpora hammer the secret/PII filter across thousands of seeded inputs — they've already caught real catastrophic-backtracking (ReDoS) holes in the egress path *before* they shipped.
- 🥶 **Reviews are "cold reads" — by design.** The reviewer sees the change as a fresh artifact in a fresh session, never inside the conversation that wrote it. 2026 research measured this as the single strongest anti-bias lever in AI code review (an evaluator's catch-rate rises sharply when the work isn't in its own context) — cross-vendor review adds a second, independent layer on top.
- 🎚️ **The judge's thinking dial is never left on "low".** Reviewer reasoning effort is routed by risk tier — high for normal changes, extra-high for money/auth/migrations, maximum for deadlock-breaking — and auto-delegating "ultra" modes are banned for gates: a judge doesn't outsource judgment.
- 🕳️ **Evidence can't silently vanish into `.gitignore`.** If a repo's `*.log` rule would swallow a review transcript, `attest` refuses to record it — and `init` writes the negation rules so it can't happen in the first place.
- 🧼 **Committed transcripts are scrubbed twice.** Secrets (keys, tokens, DB URLs) *and* personal identifiers (home-directory usernames, emails, session IDs) are redacted before any transcript touches git — honestly documented as a tripwire, not a DLP guarantee.
- 🆓 **Upgrades are free.** A versioning split means improving Coverloop never forces your projects to re-sync.

---

## ♻️ It stops forgetting — and gets smarter

- **Anti-drift:** the rules are inlined in the auto-loaded `CLAUDE.md` and re-injected by a hook **after every context compaction** — so a long session never quietly abandons your standards.
- **Self-improving memory:** durable lessons are saved to **git-tracked memory** that travels with the repo, so every new session — on any machine — starts smarter than the last.
- **Privacy at the tool layer:** known **secret** shapes (keys, tokens, DB creds, `.env` assignments) are blocked *before* any send; **PII** shapes (home-dir usernames, emails, session ids) are scrubbed from committed transcripts (a redaction tripwire, not egress-blocked); the most sensitive reviews route only to a zero-data-retention endpoint; a slopsquatting gate blocks hallucinated dependencies.

<details>
<summary><b>See the mechanics (anti-drift, privacy, memory, versioning)</b></summary>

<br/>

**Anti-drift.** Long sessions "forget" instructions because automatic **context compaction** summarizes away anything read once, and attention decays as the window fills. Coverloop inlines the Operating Contract in the auto-loaded `CLAUDE.md` (re-read after every compaction), a `SessionStart` hook re-injects the standing rules at every start and after every compaction, and a `PreToolUse` hook re-states the gate checklist right before `git push` / `merge` / migration / deploy.

**Privacy.** Tiered egress (public → proprietary → sensitive → secrets/PII, never sent). The most sensitive packets route only to a verified zero-data-retention endpoint; a boundary-aware filter blocks `.env`/keys/tokens/DB URLs before any send; an append-only egress log records a hash of every payload (never the body). Review transcripts committed as evidence are additionally scrubbed of PII shapes — home-directory usernames, emails, session UUIDs — before they touch git (a pattern tripwire, not a full DLP pass, and the docs say exactly that).

**Self-improving memory.** Durable lessons live in a git-tracked `docs/MEMORY.md` (capped and consolidated, not hoarded); recurring workflows are captured as reusable `SKILL.md` recipes; every review logs one line to a ledger so you can **subtract** any reviewer that isn't catching real bugs.

**Versioning.** `PROTOCOL_VERSION` (doc + tooling) bumps freely; `CONTRACT_VERSION` (the block in each project) bumps only when its content changes — so tooling updates cost your repos zero resyncs.

</details>

---

## 📦 What's in the box

```
bin/coverloop               the enforceable evidence gate (init / attest / gate)
CLAUDE.md                 the canonical rules (drop into any project root)
docs/GATE.md                gate docs: schema, tiers, CI wiring, threat model
docs/OPERATING_CONTRACT.md the block you inline into a project's CLAUDE.md
docs/SESSION_BOOTSTRAP.md   what to install + what to paste, in order
docs/MEMORY.example.md      template for git-tracked portable memory
docs/REVIEW_LEDGER.md       false-positive ledger + review log
bin/protocol-selftest       one-command wiring + drift check
bin/glm-* / m3-*            privacy-routed, secret-filtered reviewers
bin/dep-check               slopsquatting / hallucinated-dependency gate
hooks/                      SessionStart re-injection, pre-push gate, test gate
skills/                     reusable recipes (multi-model review, reflect-and-save)
examples/                   copy-paste GitHub Actions workflow
install.sh · init-project.sh  machine + per-repo setup
tests/                      the gate's own suite — 128 cases (unit + property/fuzz + concurrency), stdlib-only, CI on Linux·macOS·Windows
CHANGELOG.md                the story of how it got here
```

---

## Who it's for

- 🧑‍🚀 **Solo founders shipping real products with AI** — who can't afford a bug in billing or auth, but also can't afford enterprise ceremony.
- 🎨 **"Vibe coders"** who want the speed of AI coding **without** the "it looked fine, then prod broke" tax.
- 🔧 Anyone running **more than one AI coding tool** who wants them to check each other instead of each rubber-stamping its own work.

## Design philosophy

> **No model is an authority.** Findings are claims; code, tests, and runtime are the truth.
> **Execution beats opinion.** Run the test instead of stacking another reviewer.
> **Subtract, don't add.** New machinery has to earn its keep — and gets removed when it doesn't.
> **Privacy is a property of the tools, not the prompt.**
> **Every rule was born from a real failure**, not a whiteboard — that's what [`CHANGELOG.md`](CHANGELOG.md) is.

---

## 🙋 FAQ

<details><summary><b>Is this actually enforced, or just conventions?</b></summary><br/>Both layers exist, honestly labeled. Inside the session, hooks re-inject the rules (advisory — they keep the agent on-protocol). At the boundary, <a href="docs/GATE.md"><code>coverloop gate</code></a> is <b>fail-closed enforcement</b>: it exits non-zero unless commit-bound evidence of tests + reviews + human approval exists, and you can make it a required GitHub check so an unreviewed change cannot merge. Evidence is a committed JSON artifact in the PR, not a claim in a chat log.</details>

<details><summary><b>Do I need a VPS or a server?</b></summary><br/>No. Coverloop runs on your normal laptop or desktop. A server only matters if you <i>already</i> run your AI agent on one.</details>

<details><summary><b>Does it cost money to run?</b></summary><br/>The tooling is free and open source. The reviewer models run through OpenRouter (pay-as-you-go, usually a few cents per review). You decide which change tiers trigger the paid reviewers — trivial changes don't call them at all.</details>

<details><summary><b>Which AI coding tool does it work with?</b></summary><br/>Built for <b>Claude Code</b> (auto-loaded <code>CLAUDE.md</code> + hooks), with <b>Codex CLI</b> as the independent diff reviewer. Other agents that read <code>AGENTS.md</code> and support hooks can be adapted.</details>

<details><summary><b>Is my code / are my secrets safe?</b></summary><br/>Privacy is a core design goal, with honest limits. Known <b>secret</b> shapes (keys, tokens, DB credentials, <code>.env</code>-style assignments) are blocked at the tool layer <i>before</i> any model call; <b>personal identifiers</b> (usernames, emails, session ids) are redacted from committed transcripts but are not egress-blocked — it's a pattern-based tripwire, not a full DLP guarantee. The most sensitive reviews route only to a zero-data-retention endpoint. The gate itself never sends code anywhere — it only reads local files and git metadata.</details>

<details><summary><b>Can I use different models?</b></summary><br/>Yes. The reviewer CLIs route through OpenRouter, so you can swap the models by editing the helper scripts. The <i>roles</i> (builder · diff-gate · red-team · auditor · human gate) matter more than the exact models.</details>

<details><summary><b>Windows?</b></summary><br/>The <code>coverloop</code> gate and its full test suite are stdlib-only Python and run <b>natively on Windows</b> — CI proves the suite green on Linux · macOS · Windows every push. The <i>shell hooks</i> (session re-injection, test gate) are bash, so run those under <a href="https://learn.microsoft.com/windows/wsl/install">WSL</a> or Git Bash.</details>

---

## Contributing

Issues and PRs welcome — especially new reviewer adapters and risk-map templates for other stacks, and **real bugs Coverloop caught for you** (I'll feature them). Fork it, swap the roster for your own models, and tell me what broke. Licensed under [MIT](LICENSE).

<div align="center">
<br/>

### Cover every angle before you ship.

*Coverloop started as one founder's answer to a simple question:*
**how do I let AI write most of my code without letting a single bug reach a paying customer?**

<br/>

⭐ **If that question keeps you up too, star it** — it helps other builders sleep.

</div>
