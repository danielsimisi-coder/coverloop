# v2.3 hooks — wiring

These are flat shell hooks for Claude Code. **`install.sh` installs them to `~/.claude/hooks/` AND auto-wires them** in `~/.claude/settings.json` (idempotent, keeps a backup; opt out with `INSTALL_WIRE_HOOKS=0`). The schema below is the reference / manual fallback (user-level `~/.claude/settings.json` or project `.claude/settings.json`):

```jsonc
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/loop-stop-check.sh" }] }],
    "PostToolUseFailure": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/capture-failure.sh" }] }]
  }
}
```

- **loop-stop-check.sh** — OPT-IN per repo: no-op unless the repo has `.claude/loop.conf` with a `TEST_CMD`. Blocks "stop" while that check is red; livelock-guarded (MAX_BLOCKS, default 3) so it can never trap you. **Change-aware:** it short-circuits to an instant no-op when no tracked files changed (untracked ignored), so clean/chat stops cost nothing — the check only runs when you actually edited code. Pick a **cheap** `TEST_CMD` (a typecheck like `npx tsc --noEmit`, NOT a slow full suite) so it can run on every code-change stop without burning budget; the full suite still runs before a PR/CI. Gitignore `.claude/.loop-stop-blocks` (the livelock counter). See `docs/loop.conf.example`.
- **capture-failure.sh** — appends failures to `~/.claude/reflect-staging.md` for `reflect-and-save` to curate.

> Verify the exact hook event names + schema against YOUR Claude Code version's docs before wiring — schemas change between versions. Wiring is per-machine/per-project and is a Daniel-gated config change.
