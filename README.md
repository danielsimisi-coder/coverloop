# Daniel's Master Coding Loop — Claude · Codex · GLM · M3

The multi-model AI development protocol I use across projects, plus the advisory helper CLIs.

**`CLAUDE.md` is the canonical protocol** (v2.1). Drop it into a project root (Claude Code auto-loads it); symlink `AGENTS.md -> CLAUDE.md` so Codex reads the same source.

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
./install.sh                       # copies bin/* into ~/bin
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

Current version: **v2.1** (2026-06-28).
