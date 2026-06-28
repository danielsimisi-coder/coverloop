# Daniel's Master Coding Loop — Claude · Codex · GLM · M3

The multi-model AI development protocol I use across projects.
**`CLAUDE.md` is the canonical protocol** — drop it into a project root (Claude Code
auto-loads it); symlink `AGENTS.md -> CLAUDE.md` so Codex reads the same source.

Roles:
- **Claude Code** builds & coordinates (not final authority).
- **Codex CLI** independently reviews diffs (line-level correctness).
- **GLM-5.2** (full-ZDR) red-teams architecture/implementation and audits consistency.
- **MiniMax M3** (optional, L2/L3, `data_collection:deny`) — a diverse second auditor.
- **Daniel** is the human gate for risky actions.

Principles: **execution/tests are the primary correctness gate**; LLM auditors are
secondary. Privacy is enforced at the tool level (ZDR / secret filter / egress log).
Risk tiers L0–L3 scale how heavy the loop is.

Current version: **v2.1** (2026-06-28). The `glm-*`/`m3-*` helper CLIs + installer are
not yet in this repo — pending a final review pass.
