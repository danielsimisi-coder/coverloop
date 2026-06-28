#!/usr/bin/env bash
# v2.3 test-green completion gate (Stop hook). OPT-IN + livelock-guarded.
# No-op unless the repo has .claude/loop.conf with TEST_CMD set, so it never
# blocks a project that hasn't opted in, and never traps you (MAX_BLOCKS cap).
set -u
CONF=".claude/loop.conf"
[ -f "$CONF" ] || exit 0
# shellcheck disable=SC1090
. "$CONF"
[ -n "${TEST_CMD:-}" ] || exit 0
STATE=".claude/.loop-stop-blocks"
MAX_BLOCKS="${MAX_BLOCKS:-3}"
if eval "$TEST_CMD" >/dev/null 2>&1; then
  rm -f "$STATE"; exit 0
fi
n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STATE"
if [ "$n" -ge "$MAX_BLOCKS" ]; then
  rm -f "$STATE"
  echo "tests still RED after $n checks — allowing stop (livelock guard). FIX BEFORE MERGE." >&2
  exit 0
fi
echo "STOP BLOCKED: tests RED ($TEST_CMD). Fix or commit WIP, then stop. (block $n/$MAX_BLOCKS)" >&2
exit 2
