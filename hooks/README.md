# v2.3 hooks — wiring

These are flat shell hooks for Claude Code. Copy them to `~/.claude/hooks/` (install.sh does this) and wire them in `settings.json` (user-level `~/.claude/settings.json` or project `.claude/settings.json`):

```jsonc
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/loop-stop-check.sh" }] }],
    "PostToolUseFailure": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/capture-failure.sh" }] }]
  }
}
```

- **loop-stop-check.sh** — OPT-IN per repo: no-op unless the repo has `.claude/loop.conf` with e.g. `TEST_CMD="npm test"`. Blocks "stop" while tests are red; livelock-guarded (MAX_BLOCKS, default 3) so it can never trap you.
- **capture-failure.sh** — appends failures to `~/.claude/reflect-staging.md` for `reflect-and-save` to curate.

> Verify the exact hook event names + schema against YOUR Claude Code version's docs before wiring — schemas change between versions. Wiring is per-machine/per-project and is a Daniel-gated config change.
