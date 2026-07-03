# Coverloop

### The multi-agent coding loop that covers every angle — so nothing slips through.

**One model builds. Independent AI models review it from every direction. Tests decide. You hold the final gate.**
Execution-first · privacy-enforced · self-improving · sized for a solo dev, not an enterprise.

> **Protocol v2.5** · works with [Claude Code](https://claude.com/claude-code) + [Codex CLI](https://developers.openai.com/codex/cli) today, model-agnostic by design. History → [`CHANGELOG.md`](CHANGELOG.md).

---

## Why this exists

AI writes code fast. The problem is everything *after* the code:

- **One reviewer misses bugs.** A single model (even a great one) rubber-stamps its own blind spots. Real defects hide in the gaps between what any one model checks.
- **Long sessions forget the rules.** As context fills up and compacts, the agent quietly drops your standards — and starts "vibing" past the guardrails you set an hour ago.
- **Privacy leaks by accident.** Secrets, `.env` files, and customer data get pasted into model calls without anyone noticing.
- **"It passed"** is not the same as **"it's correct, migrated, deployed, and safe."**

Coverloop turns AI-assisted development into a **disciplined, gated pipeline** where a builder model, several independent reviewer models, your test suite, and *you* each close a different angle — and a change only ships when they agree.

It's not a framework you install into your app. It's a **protocol + a few small scripts** that drop into any repo and run inside the AI coding tools you already use.

---

## What you get

| | Benefit |
|---|---|
| 🧩 **Multi-model review** | A **builder** proposes; independent **reviewers** (line-level + architecture + a second auditor) attack it from different angles. A bug has to get past all of them *and* your tests. |
| ✅ **Execution is the primary gate** | Tests/typecheck outrank any model opinion. When a test can settle a question, you run the test — not stack more LLM guesses. |
| 🧠 **It stops forgetting** | The rules live **inlined in the auto-loaded instructions** (they survive context compaction) and a `SessionStart` hook re-injects them every session and after every compaction. No more mid-session drift. |
| 🔒 **Privacy at the tool layer** | Secrets never leave, enforced by a hard filter + zero-data-retention provider routing + an append-only egress log — not by "please be careful" prompting. |
| ♻️ **Self-improving** | Durable lessons are saved to **git-tracked memory** that travels with the repo, so every new session — on any machine — starts smarter than the last. |
| ⚖️ **Right-sized, not bloated** | Risk tiers (L0–L3) decide how much review a change earns. Trivial changes stay fast; money/auth/migrations get the full treatment. The protocol actively **subtracts** machinery that isn't earning its keep. |
| 🩺 **One-command health check** | `protocol-selftest` verifies the whole wiring — versions, hooks, tools, privacy routing, memory — in a single command. |
| 🚀 **Turnkey** | `install.sh` (machine) + `init-project.sh` (repo) and you're wired. Built and battle-tested on live production apps, not a whiteboard. |

---

## The loop in 30 seconds

```
        you: the task + the final gate on anything risky
         │
   ┌─────▼─────┐   builds & coordinates (never the authority)
   │  BUILDER  │
   └─────┬─────┘
         │ diff
   ┌─────▼───────────────────────────────────────────┐
   │  REVIEWERS  (each covers a different angle)       │
   │   • line-level diff correctness                   │
   │   • architecture / implementation red-team        │
   │   • a second auditor — value is in *divergence*   │
   └─────┬───────────────────────────────────────────┘
         │ findings (claims, not verdicts)
   ┌─────▼─────┐   the highest-confidence signal
   │   TESTS   │   execution beats opinion
   └─────┬─────┘
         │ green + reviewers satisfied
   ┌─────▼─────┐
   │ YOU: gate │   merge / deploy / migrate — human call on L2+
   └───────────┘
```

**No model is an authority.** Every finding is a *claim*, verified against real code, tests, and runtime before it blocks anything.

### Risk tiers decide the rigor

| Risk | Example | Gets |
|------|---------|------|
| **L0** trivial | copy, CSS | quick check |
| **L1** normal | isolated fix/refactor | relevant tests + typecheck |
| **L2** product flow | onboarding, admin UX | + a mandatory independent diff review |
| **L3** dangerous | money, auth, migrations, deploy, secrets | full suite + red-team + second auditor + **your explicit gate** |

Default to the lightest safe row; when unsure, go heavier.

---

## Quickstart

**1) Once per machine** — installs the helper CLIs, skills, and hooks, and auto-wires them:

```bash
git clone https://github.com/danielsimisi-coder/coverloop.git
cd coverloop
./install.sh
# add your model-provider API key to the single source of truth (never your shell rc):
printf '%s' 'sk-...' > ~/.config/openrouter/api_key && chmod 600 ~/.config/openrouter/api_key
~/bin/protocol-selftest      # verify the whole wiring in one command
```

**2) Once per project** — scaffold the per-repo artifacts (creates new files only, never edits your existing `CLAUDE.md`):

```bash
cd /path/to/your-project
/path/to/coverloop/init-project.sh
```

**3) The one manual step that makes it stick** — inline `docs/OPERATING_CONTRACT.md` at the top of your project's `CLAUDE.md`. That's what loads the loop into the agent's context and keeps it there.

Full, copy-paste walkthrough (machine → project → every session): [`docs/SESSION_BOOTSTRAP.md`](docs/SESSION_BOOTSTRAP.md).

---

## How it works

<details>
<summary><b>Anti-drift — why it doesn't forget the rules</b></summary>

Long AI sessions "forget" instructions for two mechanical reasons: automatic **context compaction** summarizes away anything read only once, and attention decays as the window fills. Coverloop fixes both:

- The **Operating Contract** (roster + risk gates + session-start ritual) is **inlined in the auto-loaded `CLAUDE.md`**, which the tool re-reads after every compaction — a `docs/` side-file read once does *not* survive.
- A `SessionStart` hook re-injects the standing rules as fresh, high-attention context at every start **and after every compaction**.
- A `PreToolUse` hook re-states the gate checklist right before `git push` / `merge` / migration / deploy.
</details>

<details>
<summary><b>Privacy — enforced by tools, not by prompting</b></summary>

- **Tiered egress:** public → proprietary-non-secret → sensitive identifiers → **secrets/PII (never sent, no exceptions)**.
- The most sensitive packets route only to a **verified zero-data-retention** endpoint; a hard, boundary-aware secret filter blocks `.env`/keys/tokens/DB URLs *before* any send; an append-only **egress log** records a hash of every payload (never the body) for audit.
- A **slopsquatting gate** (`dep-check`) blocks hallucinated / typosquatted dependencies before they're installed.
</details>

<details>
<summary><b>Self-improving memory — the Hermes loop</b></summary>

The loop improves the way a good engineer does — by keeping **notes** and **reusable recipes**, not by retraining a model:

- **Portable memory:** durable lessons live in a **git-tracked `docs/MEMORY.md`** that travels with the repo, so a lesson learned on one machine reaches every session on every machine (kept capped and consolidated, not hoarded).
- **Skills:** recurring workflows (the multi-model review, reflect-and-save) are captured as reusable `SKILL.md` recipes.
- **Measurement:** every review logs one line to a ledger; periodically you read it and **subtract** any reviewer/gate that isn't catching real bugs. "Prove your keep" is mechanical, not a hunch.
</details>

<details>
<summary><b>Versioning — decoupled so upgrades are free</b></summary>

`PROTOCOL_VERSION` (the doc + tooling) bumps freely; `CONTRACT_VERSION` (the block inlined in each project) bumps only when the contract's *content* changes. So a docs/tooling release costs your projects **zero resyncs** — machines just `git pull && ./install.sh`.
</details>

---

## What's in the box

```
CLAUDE.md                 the canonical protocol (drop into any project root)
docs/
  OPERATING_CONTRACT.md   the block you inline into a project's CLAUDE.md
  SESSION_BOOTSTRAP.md    what to install + what to paste, in order
  MEMORY.example.md       template for git-tracked portable memory
  RISK_MAP.example.md     per-project risk map (envs, fixtures, helper paths)
  REVIEW_LEDGER.md        false-positive ledger + review log
bin/
  protocol-selftest       one-command wiring + drift check
  <model helper CLIs>     privacy-routed, secret-filtered advisory reviewers
  dep-check               slopsquatting / hallucinated-dependency gate
hooks/                    SessionStart re-injection, PreToolUse gate reminder,
                          test-green Stop gate, failure auto-capture
skills/                   reusable recipes (multi-model review, reflect-and-save)
install.sh                machine setup (auto-wires hooks)
init-project.sh           per-repo scaffolding
CHANGELOG.md              the story of how it got here
```

---

## Who it's for

- **Solo founders & indie devs** shipping real products with AI, who can't afford a bug in billing or auth — but also can't afford enterprise ceremony.
- **"Vibe coders"** who want the speed of AI coding **without** the "it looked fine and then prod broke" tax.
- Anyone running **more than one AI coding tool** who wants them to check each other instead of each rubber-stamping its own work.

## Design philosophy

- **No model is an authority.** Findings are claims; code, tests, and runtime are the truth.
- **Execution beats opinion.** Run the test instead of stacking another reviewer.
- **Subtract, don't add.** The dominant risk at this scale is over-engineering. New machinery has to earn its keep — and gets removed when it doesn't.
- **Privacy is a property of the tools, not the prompt.**
- **Every rule here was born from a real failure**, not a whiteboard — that's what `CHANGELOG.md` is.

## Requirements

An AI coding tool that auto-loads `CLAUDE.md` and supports command hooks (built for **Claude Code**; **Codex CLI** as the independent diff reviewer). The advisory reviewer CLIs route through [OpenRouter](https://openrouter.ai) and are model-swappable. Linux/macOS.

---

## Status & license

Actively used in production. Semantic-ish versioning via `PROTOCOL_VERSION` — run `protocol-selftest` to see what any machine/project is on.

Released for the community — use it, fork it, adapt the roster to your own models. Attribution appreciated. See [`LICENSE`](LICENSE).

> Coverloop started as one founder's answer to a simple question: *how do I let AI write most of my code without letting a single bug reach a paying customer?* This is that answer, hardened over real shipping days.
