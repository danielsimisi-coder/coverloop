#!/usr/bin/env bash
set -euo pipefail
# init-project.sh — scaffold the v2.3 PER-PROJECT artifacts into the current repo.
# Idempotent: never overwrites an existing file. Run from your project repo root:
#   /path/to/coverloop/init-project.sh
# (Machine-level tooling — bin/skills/hooks + hook wiring — is installed once by install.sh.)

SRC="$(cd -- "$(dirname -- "$0")" && pwd)"   # the protocol repo (template source)
PROJ="$(pwd)"
TRUST=0
case "${1:-}" in
  --trust) TRUST=1 ;;
  "") ;;
  --help|-h) echo 'usage: init-project.sh [--trust] — scaffold; --trust explicitly authorizes running the reviewed TEST_CMD'; exit 0 ;;
  *) echo 'unknown argument' >&2; exit 2 ;;
esac
# Refuse symlinked destinations before writing any project configuration.
python3 - "$PROJ" <<'CHECK'
import os, pathlib, stat, sys
root=pathlib.Path(sys.argv[1]).resolve()
for rel in ('.claude', '.claude/loop.conf', '.claude/.gitignore', 'docs', 'docs/REVIEW_LEDGER.md', 'docs/RISK_MAP.md', 'docs/MEMORY.md', 'docs/OPERATING_CONTRACT.md'):
    path=root/rel
    if path.is_symlink():
        sys.exit('Project setup refused: symlinked destination.')
    if path.exists():
        st=path.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o022 or not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)) or (stat.S_ISREG(st.st_mode) and st.st_nlink != 1):
            sys.exit('Project setup refused: unsafe destination.')
CHECK
echo "== v2.3 project init -> $PROJ =="
[ -d "$PROJ/.git" ] || echo "  (note: this is not a git repo root — continuing anyway)"
mkdir -p "$PROJ/.claude" "$PROJ/docs"

# 1) test-green completion gate config (cheap, change-aware typecheck by default)
if [ -e "$PROJ/.claude/loop.conf" ]; then
  echo "  skip .claude/loop.conf (exists)"
else
  cp "$SRC/docs/loop.conf.example" "$PROJ/.claude/loop.conf"
  echo "  + .claude/loop.conf  (TEST_CMD defaults to 'false' until configured — edit for your stack)"
fi

# 2) gitignore the livelock counter so it never gets committed
GI="$PROJ/.claude/.gitignore"; touch "$GI"
if grep -qxF ".loop-stop-blocks" "$GI"; then :; else echo ".loop-stop-blocks" >> "$GI"; echo "  + .claude/.gitignore (.loop-stop-blocks)"; fi

# 3) false-positive ledger (injected at session start; auditors check it first)
if [ -e "$PROJ/docs/REVIEW_LEDGER.md" ]; then
  echo "  skip docs/REVIEW_LEDGER.md (exists)"
else
  cp "$SRC/docs/REVIEW_LEDGER.example.md" "$PROJ/docs/REVIEW_LEDGER.md"
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

# 8) Trust THIS repo for the Stop-hook test gate on THIS machine. The allowlist
#    lives OUTSIDE any repo, so a cloned repo can't trust itself; the Stop hook
#    refuses to run a repo's TEST_CMD unless its resolved path is listed here.
# Resolve the allowlist at an ABSOLUTE path, identical to the Stop hook: a
# relative $XDG_CONFIG_HOME is ignored (per the XDG spec) so init never writes
# the list inside a repo and always writes the file the hook actually reads.
case "${XDG_CONFIG_HOME:-}" in
  /*) _xdg="$XDG_CONFIG_HOME" ;;
  *)  _xdg="$HOME/.config" ;;
esac
TRUST_FILE="$_xdg/coverloop/trusted-repos"
# Record the SAME path the Stop hook resolves (git top-level via pwd -P), not
# raw CWD: running init from a subdir would otherwise record the subdir while
# the hook checks the git root — a permanent trust mismatch (M3 R2). Falls back
# to the resolved CWD when the project isn't a git repo.
PROJ_REAL="$(cd "$PROJ" && cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" 2>/dev/null && pwd -P)"
if [ "$TRUST" = 1 ]; then
  python3 - "$TRUST_FILE" "$PROJ_REAL" <<'TRUSTCHECK'
import os, pathlib, stat, sys
p=pathlib.Path(sys.argv[1])
if any(c in sys.argv[2] for c in "\r\n") or sys.argv[2] != sys.argv[2].strip():
    sys.exit("Trust setup refused: project path cannot be represented safely in the allowlist.")
for q in (p, *p.parents):
    if q.is_symlink(): sys.exit('Trust setup refused: symlinked destination.')
    if q.exists() and q != pathlib.Path('/'):
        st=q.stat()
        if st.st_mode & 0o022 and q not in (pathlib.Path('/tmp'), pathlib.Path('/private/tmp')):
            sys.exit('Trust setup refused: writable ancestor.')
if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
    sys.exit('Trust setup refused: unsafe file.')
TRUSTCHECK
  mkdir -p "$(dirname "$TRUST_FILE")"
fi
if [ "$TRUST" != 1 ]; then
  echo "  NOT trusted: inspect .claude/loop.conf, then explicitly run init-project.sh --trust."
elif [ -f "$TRUST_FILE" ] && grep -qxF "$PROJ_REAL" "$TRUST_FILE" 2>/dev/null; then
  echo "  skip trust marker (already trusted for the Stop-hook gate)"
else
  printf '%s\n' "$PROJ_REAL" >> "$TRUST_FILE"
  chmod 600 "$TRUST_FILE"
  echo "  + trusted this repo for the Stop-hook gate ($TRUST_FILE)"
fi

echo "Done. Per-project scaffolding is in place — NEW files only; your CLAUDE.md was NOT modified."
echo "MANUAL STEP (yours): inline docs/OPERATING_CONTRACT.md at the TOP of CLAUDE.md so the loop loads into active context. A pointer-only CLAUDE.md = the protocol won't engage."
echo "Reminder: the Stop hook runs only when .claude/loop.conf exists (it does now), the hooks are wired (install.sh), AND this repo is explicitly trusted."
