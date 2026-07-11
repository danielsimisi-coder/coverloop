#!/usr/bin/env bash
# Behavioral tests for the Stop hook (loop-stop-check.sh). The Python suite
# (test_gate.py) covers the gate CLI; this covers the shell hooks, which have
# their own security surface (repo-controlled config, global wiring).
# Run:  bash tests/test_hooks.sh
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$HERE/hooks/loop-stop-check.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

newrepo() {  # $1 = TEST_CMD line contents (raw, may include CRLF)
  d="$(mktemp -d)"; ( cd "$d" && git init -q . && git config user.email t@t && git config user.name t
    mkdir -p .claude; printf '%b' "$1" > .claude/loop.conf
    git add -A && git commit -q -m base && echo new > src_file.ts ) >/dev/null 2>&1
  echo "$d"
}
trust() { mkdir -p "$2/coverloop"; (cd "$1" && pwd -P) > "$2/coverloop/trusted-repos"; }

echo "== Stop-hook behavioral tests =="

# 1) UNTRUSTED repo must NOT run TEST_CMD (even a malicious one), even with changes
d="$(newrepo 'TEST_CMD="touch $d/PWNED"\n')"; cfg="$(mktemp -d)"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ ! -f "$d/PWNED" ] && ok "untrusted repo: TEST_CMD not executed" || bad "untrusted repo executed TEST_CMD"

# 2) TRUSTED repo runs TEST_CMD (green test -> allow stop, exit 0)
d="$(newrepo 'TEST_CMD="true"\n')"; cfg="$(mktemp -d)"; trust "$d" "$cfg"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ "$?" = 0 ] && ok "trusted repo, green test: allows stop (exit 0)" || bad "trusted green test did not exit 0"

# 3) TRUSTED repo, RED test, first strike -> BLOCK (exit 2)
d="$(newrepo 'TEST_CMD="false"\n')"; cfg="$(mktemp -d)"; trust "$d" "$cfg"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ "$?" = 2 ] && ok "trusted repo, red test: blocks stop (exit 2)" || bad "trusted red test did not block"

# 4) loop.conf is DATA, never sourced (injected command must not run at parse)
d="$(newrepo 'TEST_CMD=true\ntouch $d/SOURCED\n')"; cfg="$(mktemp -d)"; trust "$d" "$cfg"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ ! -f "$d/SOURCED" ] && ok "loop.conf not sourced (parse-time injection blocked)" || bad "loop.conf was sourced"

# 5) CRLF-authored conf: TEST_CMD parses clean (no trailing CR breaking it)
d="$(newrepo 'TEST_CMD="true"\r\nMAX_BLOCKS=2\r\n')"; cfg="$(mktemp -d)"; trust "$d" "$cfg"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ "$?" = 0 ] && ok "CRLF conf: TEST_CMD parsed clean" || bad "CRLF conf corrupted TEST_CMD"

# 6) Fully clean tree (all committed, no untracked): instant no-op, TEST_CMD not run
d="$(mktemp -d)"; cfg="$(mktemp -d)"
( cd "$d" && git init -q . && git config user.email t@t && git config user.name t
  mkdir -p .claude; printf 'TEST_CMD="touch %s/RAN"\n' "$d" > .claude/loop.conf
  git add -A && git commit -q -m base ) >/dev/null 2>&1
trust "$d" "$cfg"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ ! -f "$d/RAN" ] && ok "clean tree: short-circuits without running TEST_CMD" || bad "clean tree ran TEST_CMD"

echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" = 0 ]
