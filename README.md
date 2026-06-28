# Daniel's Master Coding Loop — Claude · Codex · GLM · M3

The multi-model AI development protocol I use across projects, plus the advisory helper CLIs.

**`CLAUDE.md` is the canonical protocol** (v2.3). Drop it into a project root (Claude Code auto-loads it); symlink `AGENTS.md -> CLAUDE.md` so Codex reads the same source.

## Roles
- **Claude Code** builds & coordinates (not final authority).
- **Codex CLI** independently reviews diffs (line-level correctness) — the gate.
- **GLM-5.2** (full-ZDR) red-teams architecture/implementation and audits consistency.
- **MiniMax M3** (optional, L2/L3, `data_collection:deny` — no-training, NOT full ZDR) — a diverse second auditor; value is in divergence.
- **Daniel** is the human gate for risky actions.

Principles: **execution/tests are the primary correctness gate**; LLM auditors are secondary. Privacy is enforced at the TOOL layer — ZDR/no-training provider routing, a hard secret filter, and an append-only egress log — not by prompt discipline.

## Install
```bash
git clone https://github.com/danielsimisi-coder/Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-.git
cd Daniel-Master-Coding-Loop-CLAUDE-CODEX-GLM-M3-
./install.sh                       # bin/* → ~/bin, skills → ~/.claude/skills, hooks → ~/.claude/hooks
printf '%s' 'sk-or-...' > ~/.config/openrouter/api_key && chmod 600 ~/.config/openrouter/api_key
~/bin/glm-review --version
~/bin/glm-audit --zdr-selftest     # confirms live full-ZDR routing (fail-closed if not)
```
> **Never export `OPENROUTER_API_KEY` in your shell rc** — `glm-review` prefers the env var over the file, so a stale export silently overrides a rotated key. Keep the key only in `~/.config/openrouter/api_key`.
> Inside Claude Code, call helpers by **absolute path** (it doesn't inherit your terminal `~/bin` PATH).

## What's in `bin/`
- `glm-review` — core (OpenRouter→GLM, text-only, `{zdr:true,allow_fallbacks:false,data_collection:deny}` routing, 15-pattern secret filter, append-only `egress.log`, `--version`, `--zdr-selftest`).
- `glm-{ask,scout,tests,audit,redteam,code}` + `-xhigh` variants (audit/redteam/code) — mode wrappers.
- `m3-review` + `m3-{ask,audit,deploy-audit}` — MiniMax M3 second auditor, routed `{data_collection:deny,allow_fallbacks:false}` (no-training; NOT full ZDR), `--privacy-selftest`. M3 is a reasoning model — raise `M3_MAX_TOKENS` (12000+) for real audits.
- `dep-check` — slopsquatting gate: refuses npm packages that don't exist, are brand-new, or have ~no downloads (blocks hallucinated dependencies). Exit 1 on a bad package.

## Self-improving loop & mechanical gates (v2.2–v2.3)
- **`skills/`** → installed to `~/.claude/skills/`: `multimodel-review` (GLM+M3 review recipe) and `reflect-and-save` (persist durable lessons to file-based memory at the end of a task — the "periodic nudge").
- **`hooks/`** → flat Claude Code hooks (wire in `settings.json`; see `hooks/README.md`):
  - `loop-stop-check.sh` — **test-green completion gate**. OPT-IN per repo via `.claude/loop.conf` (`TEST_CMD`), **change-aware** (instant no-op when no tracked files changed — clean/chat stops cost nothing), livelock-guarded (`MAX_BLOCKS`, default 3). Use a **cheap** `TEST_CMD` (a typecheck like `npx tsc --noEmit`, not a slow full suite) so it can run on every code-change stop without burning the token/compute budget — the full suite still runs before a PR/CI. Copy `docs/loop.conf.example` → `.claude/loop.conf` to enable, and gitignore `.claude/.loop-stop-blocks`.
  - `capture-failure.sh` — appends tool failures to `~/.claude/reflect-staging.md` for `reflect-and-save` to curate.
- **`docs/REVIEW_LEDGER.md`** — false-positive ledger so reviewers stop re-raising rejected findings.

Current version: **v2.3** (2026-06-28).
