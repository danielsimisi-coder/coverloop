#!/usr/bin/env bash
# v2.3 test-green completion gate (Stop hook). OPT-IN + change-aware + livelock-guarded.
# - No-op unless the repo has .claude/loop.conf with TEST_CMD set (never blocks
#   a project that hasn't opted in).
# - CHANGE-AWARE: if the working tree has no changes at all (no tracked diffs
#   AND no non-ignored untracked files), there is nothing new to verify -> allow
#   stop instantly with no test run (cheap on clean/chat stops; the gate only
#   spends time when you actually edited code). NOTE untracked files ARE counted:
#   AI-written source is untracked by default (the Write tool never git-adds), so
#   ignoring them was a fail-open — a whole new file skipped the gate entirely.
# - Livelock-guarded: after MAX_BLOCKS consecutive red checks it lets you stop
#   anyway, so a broken gate can never trap the session.
set -u
CONF=".claude/loop.conf"
[ -f "$CONF" ] || exit 0
# Parse loop.conf as DATA — never `source`/`.` it. This hook is wired globally,
# so it fires in ANY repo that has a .claude/loop.conf; sourcing would let a
# cloned untrusted repo run arbitrary code the instant a session stops inside
# it. We read only the TEST_CMD + MAX_BLOCKS values (bash parameter expansion,
# no eval at parse time). TEST_CMD itself is still executed below — that is the
# feature, and the same trust model as a package.json script or Makefile: the
# repo's own declared test command. (full audit + Sol grade 2026-07-11)
_line=$(grep -E '^[[:space:]]*TEST_CMD=' "$CONF" | tail -1)
_line=${_line%$'\r'}                         # strip a trailing CR (Windows/CRLF-authored conf) — M3 review
TEST_CMD=${_line#*=}
TEST_CMD=${TEST_CMD%\"}; TEST_CMD=${TEST_CMD#\"}
TEST_CMD=${TEST_CMD%\'}; TEST_CMD=${TEST_CMD#\'}
TEST_CMD=${TEST_CMD%$'\r'}                    # and any CR that survived unquoted
_mb=$(grep -E '^[[:space:]]*MAX_BLOCKS=' "$CONF" | tail -1)
_mb=${_mb#*=}; _mb=${_mb//[^0-9]/}
MAX_BLOCKS="${_mb:-3}"
[ -n "$TEST_CMD" ] || exit 0
STATE=".claude/.loop-stop-blocks"

# Change-aware short-circuit: verify when tracked files changed OR a non-ignored
# untracked file exists. --exclude-standard honors .gitignore, so state/build
# artifacts (e.g. .claude/.loop-stop-blocks) stay ignored per the original
# intent while a brand-new untracked source file now forces the test run.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null \
     && [ -z "$(git ls-files --others --exclude-standard 2>/dev/null)" ]; then
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
