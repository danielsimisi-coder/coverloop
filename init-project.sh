#!/usr/bin/env bash
set -euo pipefail
# init-project.sh — scaffold the v2.3 PER-PROJECT artifacts into the current repo.
# Idempotent: never overwrites an existing file. Run from your project repo root:
#   /path/to/coverloop/init-project.sh
# (Machine-level tooling — bin/skills/hooks + hook wiring — is installed once by install.sh.)

SRC="$(cd -- "$(dirname -- "$0")" && pwd)"   # the protocol repo (template source)
PROJ="$(pwd)"
echo "== v2.3 project init -> $PROJ =="
[ -d "$PROJ/.git" ] || echo "  (note: this is not a git repo root — continuing anyway)"
mkdir -p "$PROJ/.claude" "$PROJ/docs"

# 1) test-green completion gate config (cheap, change-aware typecheck by default)
if [ -e "$PROJ/.claude/loop.conf" ]; then
  echo "  skip .claude/loop.conf (exists)"
else
  cp "$SRC/docs/loop.conf.example" "$PROJ/.claude/loop.conf"
  echo "  + .claude/loop.conf  (TEST_CMD defaults to 'npx tsc --noEmit' — edit for your stack)"
fi

# 2) gitignore the livelock counter so it never gets committed
GI="$PROJ/.claude/.gitignore"; touch "$GI"
if grep -qxF ".loop-stop-blocks" "$GI"; then :; else echo ".loop-stop-blocks" >> "$GI"; echo "  + .claude/.gitignore (.loop-stop-blocks)"; fi

# 3) false-positive ledger (injected at session start; auditors check it first)
if [ -e "$PROJ/docs/REVIEW_LEDGER.md" ]; then
  echo "  skip docs/REVIEW_LEDGER.md (exists)"
else
  cp "$SRC/docs/REVIEW_LEDGER.md" "$PROJ/docs/REVIEW_LEDGER.md"
  echo "  + docs/REVIEW_LEDGER.md"
fi

# 4) project risk map (delete this file if you keep the map in Obsidian instead)
if [ -e "$PROJ/docs/RISK_MAP.md" ]; then
  echo "  skip docs/RISK_MAP.md (exists)"
else
  cp "$SRC/docs/RISK_MAP.example.md" "$PROJ/docs/RISK_MAP.md"
  echo "  + docs/RISK_MAP.md  (template — fill in, or delete if you use Obsidian)"
fi

# 5) portable memory (git-tracked — travels with the repo; loaded at Session Start)
if [ -e "$PROJ/docs/MEMORY.md" ]; then
  echo "  skip docs/MEMORY.md (exists)"
else
  cp "$SRC/docs/MEMORY.example.md" "$PROJ/docs/MEMORY.md"
  echo "  + docs/MEMORY.md  (portable memory — reflect-and-save appends here; commit it)"
fi

# 6) Operating Contract template (you inline it into CLAUDE.md yourself — see note below).
#    Skip if the contract is ALREADY inlined in CLAUDE.md (avoids a redundant file).
if [ -e "$PROJ/docs/OPERATING_CONTRACT.md" ]; then
  echo "  skip docs/OPERATING_CONTRACT.md (exists)"
elif [ -f "$PROJ/CLAUDE.md" ] && grep -q "Operating Contract" "$PROJ/CLAUDE.md" 2>/dev/null; then
  echo "  skip docs/OPERATING_CONTRACT.md (already inlined in CLAUDE.md)"
else
  cp "$SRC/docs/OPERATING_CONTRACT.md" "$PROJ/docs/OPERATING_CONTRACT.md"
  echo "  + docs/OPERATING_CONTRACT.md  (TEMPLATE — inline into CLAUDE.md manually)"
fi

# 7) AGENTS.md -> CLAUDE.md symlink so Codex/other agents read ONE source of truth
if [ -e "$PROJ/CLAUDE.md" ] && [ ! -e "$PROJ/AGENTS.md" ]; then
  if ln -s CLAUDE.md "$PROJ/AGENTS.md" 2>/dev/null; then
    echo "  + AGENTS.md -> CLAUDE.md"
  else
    echo "  (could not symlink AGENTS.md — add a one-line pointer to CLAUDE.md manually)"
  fi
fi

echo "Done. Per-project v2.3 scaffolding is in place — NEW files only; your CLAUDE.md was NOT modified."
echo "MANUAL STEP (yours): inline docs/OPERATING_CONTRACT.md at the TOP of CLAUDE.md so the loop loads into active context. A pointer-only CLAUDE.md = the protocol won't engage."
echo "Reminder: the Stop hook runs only when .claude/loop.conf exists (it does now) AND the hooks are wired (install.sh)."
