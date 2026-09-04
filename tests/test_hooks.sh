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

# 7) CRLF + surrounding whitespace in a trust entry is tolerated (still trusted)
d="$(newrepo 'TEST_CMD="true"\n')"; cfg="$(mktemp -d)"; mkdir -p "$cfg/coverloop"
printf '  %s \r\n' "$(cd "$d" && pwd -P)" > "$cfg/coverloop/trusted-repos"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ "$?" = 0 ] && ok "CRLF/whitespace trust entry: still trusted" || bad "CRLF/whitespace entry not matched"

# 8) A RELATIVE XDG_CONFIG_HOME must NOT let a repo-local trust file self-trust
d="$(newrepo 'TEST_CMD="touch $d/PWNED"\n')"
mkdir -p "$d/coverloop"; printf '.\n' > "$d/coverloop/trusted-repos"   # repo ships its own list w/ "."
h="$(mktemp -d)"                                                       # clean HOME so real config isn't read
( cd "$d" && HOME="$h" XDG_CONFIG_HOME=. bash "$HOOK" ) >/dev/null 2>&1
[ ! -f "$d/PWNED" ] && ok "relative XDG_CONFIG_HOME: repo cannot self-trust" || bad "relative XDG self-trust executed TEST_CMD"

# 9) A group/world-writable allowlist is refused (shared-host tamper guard)
d="$(newrepo 'TEST_CMD="touch $d/RAN_ANYWAY"\n')"; cfg="$(mktemp -d)"; trust "$d" "$cfg"
chmod 0666 "$cfg/coverloop/trusted-repos"
( cd "$d" && XDG_CONFIG_HOME="$cfg" bash "$HOOK" ) >/dev/null 2>&1
[ ! -f "$d/RAN_ANYWAY" ] && ok "world-writable trust file: refused (TEST_CMD not run)" || bad "honored a world-writable trust file"

# ---------------------------------------------------------------------------
# SessionStart contract + protocol-selftest comparison. Both are executables
# this release changes, and neither had coverage: CI would not have caught a
# broken marker set, a lost line, or a comparison that stopped comparing.
# ---------------------------------------------------------------------------
echo "== SessionStart contract tests =="
SC="$HERE/hooks/session-contract.sh"

# 1) silent outside a protocol project
d="$(mktemp -d)"
out="$( cd "$d" && bash "$SC" 2>/dev/null )"
[ -z "$out" ] && ok "no protocol marker: silent" || bad "spoke outside a protocol project"

# 2) each marker triggers it, and the output is exactly the promised three lines
for marker in CLAUDE.md docs/OPERATING_CONTRACT.md docs/MULTI_MODEL_PROTOCOL.md; do
  d="$(mktemp -d)"; mkdir -p "$d/docs"
  if [ "$marker" = CLAUDE.md ]; then printf 'PROTOCOL_VERSION: v0\n' > "$d/$marker"
  else : > "$d/$marker"; fi
  n="$( cd "$d" && bash "$SC" 2>/dev/null | wc -l | tr -d ' ' )"
  [ "$n" = 3 ] && ok "marker $marker: three lines" || bad "marker $marker: $n lines, expected 3"
done

# 3) a CLAUDE.md without the protocol markers must NOT trigger it
d="$(mktemp -d)"; printf 'just a readme\n' > "$d/CLAUDE.md"
out="$( cd "$d" && bash "$SC" 2>/dev/null )"
[ -z "$out" ] && ok "unmarked CLAUDE.md: silent" || bad "spoke for an unmarked CLAUDE.md"

# 3b) the marker SET is closed. Proving three markers activate it does not stop
#     a FOURTH being added; `.coverloop/` is the exact drift this repo has
#     already had once (it triggered one hook and not the other). Widening the
#     set is a decision, not a side effect — this test makes it visible.
for nonmarker in .coverloop .claude docs/RISK_MAP.md coverloop.json; do
  d="$(mktemp -d)"; mkdir -p "$d/docs"
  case "$nonmarker" in */*) : > "$d/$nonmarker" ;; .*) mkdir -p "$d/$nonmarker" ;; *) : > "$d/$nonmarker" ;; esac
  out="$( cd "$d" && bash "$SC" 2>/dev/null )"
  [ -z "$out" ] && ok "not a marker: $nonmarker" || bad "$nonmarker became a trigger"
done

# 4) the contract text itself, locked verbatim. Substring checks let any
#    unlisted invariant be dropped, and any name other than one hard-coded
#    example be added. The text IS the deliverable, so changing it should
#    require changing this expectation deliberately.
d="$(mktemp -d)"; printf 'PROTOCOL_VERSION: v0\n' > "$d/CLAUDE.md"
body="$( cd "$d" && bash "$SC" 2>/dev/null )"
expected="$(cat <<'EXPECTED'
[coverloop] Build normally. Run the relevant tests as you go.
Before merge/deploy: `coverloop gate` must pass at HEAD (use its absolute path if it is not on PATH). It fails closed on missing evidence — record that evidence with `coverloop attest` (tests, the independent reviews the tier requires, and a named human approval where one is required). Resolve what the gate names; do not work around it.
Never lower the deterministic risk floor. Never record an approval on a human's behalf. Never bypass a red test or a red review. Never send secrets, .env contents, keys, or PII to any model. Irreversible production actions — migrations, raw SQL, schema/data-model changes, money paths, auth/RLS — are the operator's call, not yours.
EXPECTED
)"
[ "$body" = "$expected" ] && ok "contract text matches verbatim" \
  || { bad "contract text changed — update tests/test_hooks.sh deliberately"; diff <(printf '%s\n' "$expected") <(printf '%s\n' "$body") | head -6; }

echo "== protocol-selftest hook comparison =="
ST="$HERE/bin/protocol-selftest"
mkhome() {  # $1 = file to install AS session-contract.sh
  h="$(mktemp -d)"; mkdir -p "$h/.claude/hooks"
  for f in session-contract.sh pre-risky-git.sh loop-stop-check.sh capture-failure.sh; do
    printf '#!/bin/sh\n' > "$h/.claude/hooks/$f"
  done
  # cp, not "$(cat ...)": command substitution strips the trailing newline and
  # the copy would differ from the source by exactly one byte.
  cp "$1" "$h/.claude/hooks/session-contract.sh"
  echo "$h"
}
h="$(mkhome "$SC")"
out="$( HOME="$h" bash "$ST" 2>&1 )"
case "$out" in *"PASS  session-contract.sh matches the repo"*) ok "identical installed hook: PASS" ;;
               *) bad "identical installed hook not reported as PASS" ;; esac
stale="$(mktemp)"; printf '#!/bin/sh\necho stale\n' > "$stale"
h="$(mkhome "$stale")"
out="$( HOME="$h" bash "$ST" 2>&1 )"
case "$out" in *"WARN  installed session-contract.sh"*"differs from the repo's"*)
    ok "stale installed hook: WARN" ;;
  *) bad "stale installed hook not reported as WARN" ;; esac

# A clone this script cannot locate must WARN, never PASS. Exercised for real:
# the self-test is copied to a standalone bin/ whose parent is not a checkout,
# with a HOME that has neither ~/protocol-loop nor ~/coverloop — so SRC really
# is empty. Running the repo copy would not reach this path, because its own
# parent directory IS a clone.
h="$(mkhome "$stale")"; mkdir -p "$h/bin"; cp "$ST" "$h/bin/protocol-selftest"
out="$( cd / && HOME="$h" bash "$h/bin/protocol-selftest" 2>&1 )"
case "$out" in *"WARN  no protocol repo clone found"*"cannot verify the installed session-contract.sh"*)
    ok "no locatable clone: WARN, not PASS" ;;
  *) bad "no locatable clone: did not WARN" ;; esac
case "$out" in *"PASS  session-contract.sh matches"*)
    bad "claimed a match with no clone to compare against" ;;
  *) ok "no locatable clone: claims no match" ;; esac

echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" = 0 ]
