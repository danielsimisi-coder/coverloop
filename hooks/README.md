# v2.3 hooks — wiring

These are flat shell hooks for Claude Code. **`install.sh` installs them to `~/.claude/hooks/` AND auto-wires them** in `~/.claude/settings.json` (idempotent, keeps a backup; opt out with `INSTALL_WIRE_HOOKS=0`). The schema below is the reference / manual fallback (user-level `~/.claude/settings.json` or project `.claude/settings.json`):

```jsonc
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/session-contract.sh" }] }],
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/pre-risky-git.sh" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/loop-stop-check.sh" }] }],
    "PostToolUseFailure": [{ "hooks": [{ "type": "command", "command": "<ABS>/.claude/hooks/capture-failure.sh" }] }]
  }
}
```

- **session-contract.sh** (`SessionStart`) — **anti-drift re-injection.** `SessionStart` fires at every session start AND after every automatic compaction; whatever this prints to stdout is injected into context. So it re-states the protocol's standing rules as FRESH, high-attention context, fixing the drift where a long/compacted session "forgets" the protocol. Scoped (only fires in a protocol project) and short (token economy); the full contract lives in `CLAUDE.md`/`docs/OPERATING_CONTRACT.md`, which survive compaction on their own.
- **pre-risky-git.sh** (`PreToolUse`, matcher `Bash`) — reads the command from stdin JSON; when it's a risky op (`git push`/`merge`/`rebase`, `db push`/migration/deploy) it injects the **gate checklist** (`additionalContext`) at the exact moment it matters. **Advisory only — it does not block.** Scoped to protocol projects.
- **loop-stop-check.sh** (`Stop`) — OPT-IN per repo: no-op unless the repo has `.claude/loop.conf` with a `TEST_CMD`. Blocks "stop" while that check is red; livelock-guarded (MAX_BLOCKS, default 3) so it can never trap you. **Change-aware:** it short-circuits to an instant no-op only when the tree is fully clean — no tracked diffs AND no non-ignored **untracked** files (`git ls-files --others --exclude-standard`), so a brand-new untracked source file still forces the check (AI-written files are untracked by default), while gitignored state/build artifacts stay ignored. Pick a **cheap** `TEST_CMD` (a typecheck like `npx tsc --noEmit`, NOT a slow full suite) so it can run on every code-change stop without burning budget; the full suite still runs before a PR/CI. **Trust-gated:** the hook is wired at user scope, so it fires in any repo with a `loop.conf`. To stop a cloned untrusted repo from getting its `TEST_CMD` executed just because a session stopped in it, `loop.conf` is parsed as data (never sourced) **and** the hook runs `TEST_CMD` only if the repo's resolved path is in a machine-local allowlist (`${XDG_CONFIG_HOME:-~/.config}/coverloop/trusted-repos`, which lives outside any repo so a repo can't trust itself). `init-project.sh` adds the repo; until then the gate no-ops. Gitignore `.claude/.loop-stop-blocks` (the livelock counter). See `docs/loop.conf.example`.
- **capture-failure.sh** (`PostToolUseFailure`) — appends failures to `~/.claude/reflect-staging.md` for `reflect-and-save` to curate.

> **When hooks take effect (verified live):** the **event** hooks — `PreToolUse`, `Stop`, `PostToolUseFailure` — activate as soon as `install.sh` wires `settings.json`, **mid-session, no restart** (observed: `pre-risky-git.sh` fired on the very next `git push` in the same session it was installed). Only **`SessionStart`** waits for the next session start (and fires again after each compaction) — that's by nature: it runs *at* session start. So after `install.sh`, the gate reminders are live immediately; the standing-rules re-injection shows up on your next fresh session.

> Verify the exact hook event names + schema against YOUR Claude Code version's docs before wiring — schemas change between versions. Wiring is per-machine/per-project and is a operator-gated config change.
