# Session Bootstrap — what to install & what to paste into a session

How to take a new machine, a project, or a fresh Claude/Codex session and get it **actually running** the v2.3 loop — not just "having the docs nearby." Three layers, in order.

> These are templates + prompts. Applying them to a specific project (editing its `CLAUDE.md`, etc.) is **your call** — nothing here edits a project repo on its own.

## 1) Machine (once per machine — Mac / each VPS)
Installs the CLIs, skills, hooks, and **auto-wires the hooks**.

> **On a VPS / remote box, authenticate `gh` FIRST** — as the OS user the agent runs as (e.g. `su - actdev` → `gh auth login` → GitHub.com → HTTPS → "Login with a web browser" → enter the device code). This **private** repo won't clone otherwise, and gh auth is also what lets that box **open its own PRs**. A box's git *deploy key* usually reaches only its one project repo, so it's `gh` auth — not the deploy key — that unblocks the protocol repo. (Credential lands in `~/.config/gh`, chmod 600; "saved in plain text" is normal on a headless box.)

```bash
gh repo clone danielsimisi-coder/Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-   # (or git clone https://… on an already-authed box)
cd Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-
./install.sh                             # <-- RUN THIS YOURSELF (see note below)
printf '%s' 'sk-or-...' > ~/.config/openrouter/api_key && chmod 600 ~/.config/openrouter/api_key
~/bin/glm-audit --zdr-selftest          # must print OK (full-ZDR)
# On a VPS where M3 is approved:
#   touch ~/.config/openrouter/m3_enabled && ~/bin/m3-review --privacy-selftest
```
> **Run `install.sh` YOURSELF** — in the box's terminal, or with the `!` prefix inside a session (`! ./install.sh`). Do NOT ask the agent to run it: it wires hooks into `~/.claude/settings.json`, and the harness **correctly blocks an agent from modifying its own hook config** (self-modification guard). The right split is: the *agent clones + inspects* `install.sh` and the hook scripts; the *human runs it*.
> **Linux:** `install.sh` preflights Codex's sandbox (unprivileged user namespaces). If it prints a WARNING, the Codex gate won't run until you apply the one-line **root** fix from [`docs/CODEX_SANDBOX_LINUX.md`](CODEX_SANDBOX_LINUX.md) — do **not** use the `--dangerously-bypass` flag.

## 2) Project (once per repo — creates NEW files only, never edits your CLAUDE.md)
```bash
cd /path/to/your-project
/path/to/Daniel-Master-Coding-Loop-.../init-project.sh
```
`init-project.sh` scaffolds (idempotent, never overwrites): `.claude/loop.conf`, `docs/REVIEW_LEDGER.md`, `docs/RISK_MAP.md`, **`docs/MEMORY.md`** (portable git-tracked memory), and **`docs/OPERATING_CONTRACT.md`**.

Then **you** do the one manual wiring step it deliberately won't do for you: **inline the Operating Contract at the top of the project's `CLAUDE.md`** (copy from `docs/OPERATING_CONTRACT.md`). This is the step that makes the loop load into active context — a `CLAUDE.md` that only points to `docs/`, or whose roster omits GLM/M3, means the protocol never loads. (`init-project.sh` skips writing `docs/OPERATING_CONTRACT.md` if `CLAUDE.md` already carries the contract.)

**Also enable auto-delete of merged branches** (once per repo): `gh api -X PATCH repos/<owner>/<repo> -f delete_branch_on_merge=true`. Otherwise a lingering merged branch can be re-merged into empty **duplicate PRs** — we hit exactly this (the `#87`/`#88` no-op merges).

## 3) Every session — paste this FIRST to a fresh Claude/Codex session
```
Session Start (v2.3 protocol). Before any work, do this and report it:
1. State PROTOCOL_VERSION and the roster (Claude build · Codex diff-gate · GLM-5.2 full-ZDR red-team+audit · M3 data_collection:deny L3-only · Daniel gate).
2. Read docs/MEMORY.md (git-tracked memory) and summarize what's relevant to today's task.
3. Read the Risk Map + docs/REVIEW_LEDGER.md; skip findings already marked rejected.
4. Resolve the ABSOLUTE paths of glm-*/m3-* and record them in the Risk Map (you do NOT inherit the ~/bin PATH).
5. Restate the Task Card + risk tier (L0–L3) before touching code.
If the Operating Contract is not present in your loaded CLAUDE.md/AGENTS.md, say so — that's a wiring bug.
```

## Quick "is it actually wired?" self-check — paste to verify a running session
```
Answer from your LOADED context only (don't open files): (a) what PROTOCOL_VERSION are you on? (b) name the 5 roster members. (c) where is durable memory stored for this project? (d) what is the cheap per-stop test gate? If you can't answer (a) and (b) from loaded context, the protocol isn't wired — stop and flag it.
```

## End of every meaningful task — paste to close the loop
```
Run reflect-and-save: did anything durable happen (a correction/preference, a non-obvious infra fact, a decision + why, a recurring workflow)? If yes, append one concise entry to docs/MEMORY.md and commit it with the work. If nothing durable, say "nothing to save" — don't save noise.
```
