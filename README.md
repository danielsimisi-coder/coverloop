# Daniel's Master Coding Loop — Claude · Codex · GLM · M3

The multi-model AI development protocol I use across projects, plus the advisory helper CLIs.

**`CLAUDE.md` is the canonical protocol** (v2.4). Drop it into a project root (Claude Code auto-loads it); symlink `AGENTS.md -> CLAUDE.md` so Codex reads the same source.

> 👉 **New here / setting up a machine, a project, or a session? Start with [`docs/SESSION_BOOTSTRAP.md`](docs/SESSION_BOOTSTRAP.md)** — it spells out exactly what to install and what to paste, in order: **machine** (`install.sh`) → **project** (`init-project.sh`, then inline `docs/OPERATING_CONTRACT.md` into that project's `CLAUDE.md`) → **every session** (paste the Session-Start prompt). The single most important step is inlining the Operating Contract into the project's `CLAUDE.md` — without it the loop never loads into the agent's context.

## Roles
- **Claude Code** builds & coordinates (not final authority).
- **Codex CLI** independently reviews diffs (line-level correctness) — the gate.
- **GLM-5.2** (full-ZDR) red-teams architecture/implementation and audits consistency.
- **MiniMax M3** (optional, L2/L3, `data_collection:deny` — no-training, NOT full ZDR) — a diverse second auditor; value is in divergence.
- **Daniel** is the human gate for risky actions.

Principles: **execution/tests are the primary correctness gate**; LLM auditors are secondary. Privacy is enforced at the TOOL layer — ZDR/no-training provider routing, a hard secret filter, and an append-only egress log — not by prompt discipline.

## Install — turnkey, two steps
**1) Once per machine** — installs the CLIs, skills, hooks, and **auto-wires the hooks** in `settings.json`:
```bash
git clone https://github.com/danielsimisi-coder/Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-.git
cd Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-
./install.sh                       # bin/*→~/bin; skills+hooks→~/.claude; wires Stop+PostToolUseFailure (backup kept)
printf '%s' 'sk-or-...' > ~/.config/openrouter/api_key && chmod 600 ~/.config/openrouter/api_key
~/bin/glm-audit --zdr-selftest     # confirms live full-ZDR routing (fail-closed if not)
```
**2) Once per project** — scaffolds the per-repo v2.3 artifacts:
```bash
cd /path/to/your-project
/path/to/Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-/init-project.sh
# creates .claude/loop.conf (cheap typecheck gate), docs/REVIEW_LEDGER.md, docs/RISK_MAP.md, AGENTS.md->CLAUDE.md
```
> Both scripts are **idempotent** — re-run any time; they never clobber an existing file or config (always back up first).
> Optional root hardening (egress allowlist / OS sandbox) lives in [`docs/EGRESS_SANDBOX.md`](docs/EGRESS_SANDBOX.md) — it's the one tripwire the scripts can't apply for you (needs root).
> **Never export `OPENROUTER_API_KEY` in your shell rc** — `glm-review` prefers the env var over the file, so a stale export silently overrides a rotated key. Keep the key only in `~/.config/openrouter/api_key`.
> Inside Claude Code, call helpers by **absolute path** (it doesn't inherit your terminal `~/bin` PATH).

## What's in `bin/`
- `glm-review` — core (OpenRouter→GLM, text-only, `{zdr:true,allow_fallbacks:false,data_collection:deny}` routing, 15-pattern secret filter, append-only `egress.log`, `--version`, `--zdr-selftest`).
- `glm-{ask,scout,tests,audit,redteam,code}` + `-xhigh` variants (audit/redteam/code) — mode wrappers.
- `m3-review` + `m3-{ask,audit,deploy-audit}` — MiniMax M3 second auditor, routed `{data_collection:deny,allow_fallbacks:false}` (no-training; NOT full ZDR), `--privacy-selftest`. M3 is a reasoning model — raise `M3_MAX_TOKENS` (12000+) for real audits.
- `dep-check` — slopsquatting gate: refuses npm packages that don't exist, are brand-new, or have ~no downloads (blocks hallucinated dependencies). Exit 1 on a bad package.

## Self-improving loop & mechanical gates (v2.2–v2.3)
- **`skills/`** → installed to `~/.claude/skills/`: `multimodel-review` (GLM+M3 review recipe) and `reflect-and-save` (persist durable lessons to file-based memory at the end of a task — the "periodic nudge").
- **`hooks/`** → flat Claude Code hooks, **auto-wired by `install.sh`** (manual schema in `hooks/README.md`):
  - `session-contract.sh` (`SessionStart`) — **anti-drift re-injection**: re-states the standing rules into context at every session start **and after every compaction**, so long sessions stop "forgetting" the protocol. Scoped to protocol projects; short (token economy).
  - `pre-risky-git.sh` (`PreToolUse`/`Bash`) — injects the **gate checklist** right before `git push`/`merge`/migration/deploy. Advisory, non-blocking.
  - `loop-stop-check.sh` — **test-green completion gate**. OPT-IN per repo via `.claude/loop.conf` (`TEST_CMD`), **change-aware** (instant no-op when no tracked files changed — clean/chat stops cost nothing), livelock-guarded (`MAX_BLOCKS`, default 3). Uses a **cheap** `TEST_CMD` (a typecheck like `npx tsc --noEmit`, not a slow full suite) so it runs on every code-change stop without burning the token/compute budget — the full suite still runs before a PR/CI. `init-project.sh` writes `.claude/loop.conf` and gitignores the counter for you.
  - `capture-failure.sh` — appends tool failures to `~/.claude/reflect-staging.md` for `reflect-and-save` to curate.
- **`init-project.sh`** — run in a project root to scaffold `.claude/loop.conf`, `docs/REVIEW_LEDGER.md`, `docs/RISK_MAP.md`, `docs/MEMORY.md` (portable memory), `docs/OPERATING_CONTRACT.md`, and the `AGENTS.md → CLAUDE.md` symlink. **New files only — never edits your existing `CLAUDE.md`.** Idempotent.
- **`docs/OPERATING_CONTRACT.md`** — the loop's binding contract (roster incl. GLM/M3 + Decision Card + Session-Start ritual) to **inline at the top of a project's `CLAUDE.md`** so the protocol loads into active context. A pointer-only `CLAUDE.md`, or one whose roster omits GLM/M3, is the #1 reason "the protocol didn't work."
- **`docs/MEMORY.example.md`** — template for `docs/MEMORY.md`: **git-tracked, portable** memory so lessons travel between the Mac and each VPS (machine-local Claude memory does not). `reflect-and-save` appends here and commits.
- **`docs/SESSION_BOOTSTRAP.md`** — what to install + paste-ready prompts (machine install · project init · per-session Session-Start · "is it wired?" self-check · end-of-task reflect).
- **`docs/REVIEW_LEDGER.md`** — false-positive ledger so reviewers stop re-raising rejected findings.
- **`docs/EGRESS_SANDBOX.md`** — optional root-level egress allowlist / OS sandbox (defense-in-depth; the tool layer already enforces core privacy).
- **`docs/CODEX_SANDBOX_LINUX.md`** — fix for Codex's `bwrap` sandbox failing on Linux (Ubuntu 24.04 unprivileged-userns clamp): a persistent root sysctl so Codex runs **sandboxed** without the `--dangerously-bypass` flag. `install.sh` auto-detects and points here.

Current version: **v2.4** (2026-07-01) — "wired + anti-drift": inlined Operating Contract + SessionStart/PreToolUse re-injection hooks, §7a env parity, background-task hygiene, Codex Linux sandbox prerequisite, portable `docs/MEMORY.md`, turnkey install.
