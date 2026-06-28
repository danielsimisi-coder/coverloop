#!/usr/bin/env bash
# v2.3 test-green completion gate (Stop hook). OPT-IN + change-aware + livelock-guarded.
# - No-op unless the repo has .claude/loop.conf with TEST_CMD set (never blocks
#   a project that hasn't opted in).
# - CHANGE-AWARE: if the working tree has no tracked modifications, there is
#   nothing new to verify -> allow stop instantly with no test run (cheap on
#   clean/chat stops; the gate only spends time when you actually edited code).
# - Livelock-guarded: after MAX_BLOCKS consecutive red checks it lets you stop
#   anyway, so a broken gate can never trap the session.
set -u
CONF=".claude/loop.conf"
[ -f "$CONF" ] || exit 0
# shellcheck disable=SC1090
. "$CONF"
[ -n "${TEST_CMD:-}" ] || exit 0
STATE=".claude/.loop-stop-blocks"
MAX_BLOCKS="${MAX_BLOCKS:-3}"

# Change-aware short-circuit: only verify when tracked files changed.
# Untracked files (state files, build artifacts) are ignored on purpose.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    rm -f "$STATE"; exit 0
  fi
fi

if eval "$TEST_CMD" >/dev/null 2>&1; then
  rm -f "$STATE"; exit 0
fi
n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STATE"
if [ "$n" -ge "$MAX_BLOCKS" ]; then
  rm -f "$STATE"
  echo "check still RED after $n tries — allowing stop (livelock guard). FIX BEFORE MERGE." >&2
  exit 0
fi
echo "STOP BLOCKED: check RED ($TEST_CMD). Fix or commit WIP, then stop. (block $n/$MAX_BLOCKS)" >&2
exit 2
