#!/usr/bin/env bash
set -euo pipefail
# install.sh — install the GLM/M3 advisory helper CLIs into ~/bin. Idempotent.
# Never prompts for or prints a secret. The API key lives ONLY in
# ~/.config/openrouter/api_key (chmod 600) — never in this repo or your shell rc
# (an exported OPENROUTER_API_KEY can silently override a rotated file key).

BIN_DIR="${BIN_DIR:-$HOME/bin}"
SRC="$(cd -- "$(dirname -- "$0")" && pwd)/bin"

echo "== GLM/M3 helper installer =="
[ -d "$SRC" ] || { echo "ERROR: $SRC not found"; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 required"; exit 1; }

mkdir -p "$BIN_DIR"
n=0
for f in "$SRC"/*; do [ -f "$f" ] || continue; cp "$f" "$BIN_DIR/"; chmod 700 "$BIN_DIR/$(basename "$f")"; n=$((n+1)); done
echo "Installed $n helpers to $BIN_DIR"

mkdir -p "$HOME/.config/openrouter"; chmod 700 "$HOME/.config/openrouter"
KEY="$HOME/.config/openrouter/api_key"
if [ -f "$KEY" ]; then
  chmod 600 "$KEY"
  echo "-- glm-review --version --"; "$BIN_DIR/glm-review" --version || true
  echo "-- glm-audit --zdr-selftest --"; "$BIN_DIR/glm-audit" --zdr-selftest || echo "(ZDR self-test failed — do NOT send proprietary code until it passes)"
else
  echo "NEXT: add your OpenRouter key (single source of truth; do NOT export it in your shell rc):"
  echo "  printf '%s' 'sk-or-...' > \"$KEY\" && chmod 600 \"$KEY\""
fi

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "NOTE: add $BIN_DIR to PATH for interactive use (Claude Code uses absolute paths regardless).";; esac
SK="$HOME/.claude/skills"
if [ -d "$(dirname "$0")/skills" ]; then mkdir -p "$SK"; cp -R "$(dirname "$0")/skills/." "$SK/"; echo "Installed skills to $SK"; fi
HK="$HOME/.claude/hooks"
if [ -d "$(dirname "$0")/hooks" ]; then mkdir -p "$HK"; cp "$(dirname "$0")/hooks/"*.sh "$HK/" 2>/dev/null; chmod +x "$HK/"*.sh 2>/dev/null; echo "Installed hooks to $HK"; fi

# Auto-wire the hooks into ~/.claude/settings.json (idempotent, keeps a backup).
# Opt out with INSTALL_WIRE_HOOKS=0. Never clobbers existing config; on any doubt it no-ops.
if [ "${INSTALL_WIRE_HOOKS:-1}" = "1" ] && command -v python3 >/dev/null; then
  python3 - "$HK" <<'PY'
import json, os, sys, shutil, time
hk = sys.argv[1]
p  = os.path.expanduser("~/.claude/settings.json")
# (event, hook-script, matcher-or-None). Matcher is only set where it matters (PreToolUse->Bash).
want = [
    ("Stop",              os.path.join(hk, "loop-stop-check.sh"),  None),
    ("PostToolUseFailure",os.path.join(hk, "capture-failure.sh"),  None),
    ("SessionStart",      os.path.join(hk, "session-contract.sh"), None),
    ("PreToolUse",        os.path.join(hk, "pre-risky-git.sh"),    "Bash"),
]
d = {}
if os.path.exists(p):
    try:
        with open(p) as f: d = json.load(f)
    except Exception as e:
        print("  settings.json present but unreadable (%s) — NOT modifying; wire manually per hooks/README.md" % e)
        sys.exit(0)
hooks = d.setdefault("hooks", {})
changed = False
for ev, cmd, matcher in want:
    arr = hooks.setdefault(ev, [])
    if not any(cmd in json.dumps(x) for x in arr):
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher: entry["matcher"] = matcher
        arr.append(entry)
        changed = True
if changed:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p): shutil.copy(p, p + ".bak.%d" % int(time.time()))
    with open(p, "w") as f: json.dump(d, f, indent=2)
    print("  wired Stop + PostToolUseFailure + SessionStart + PreToolUse hooks in %s (backup kept)" % p)
else:
    print("  hooks already wired in settings.json (no change)")
PY
else
  echo "  (skipped hook auto-wiring — needs python3 and INSTALL_WIRE_HOOKS=1; see hooks/README.md)"
fi

# Codex (Linux) sandbox preflight — Codex's bundled bwrap needs unprivileged user+net namespaces.
# Ubuntu 23.10+/24.04 clamp these via AppArmor, so Codex's sandbox fails. Detect (non-root) and
# print the persistent ROOT remedy; we do NOT apply it (it needs root).
if [ "$(uname -s)" = "Linux" ] && command -v unshare >/dev/null 2>&1; then
  if unshare -Urn true 2>/dev/null; then
    echo "Codex sandbox preflight: unprivileged user+net namespaces OK."
  else
    echo "WARNING: unprivileged user+net namespaces are BLOCKED — Codex's bundled bwrap sandbox will fail on this host."
    echo "  Likely cause: Ubuntu 23.10+/24.04 AppArmor clamp (kernel.apparmor_restrict_unprivileged_userns=1)."
    echo "  Persistent fix (run as ROOT, then re-test 'unshare -Urn true'):"
    echo "    echo 'kernel.apparmor_restrict_unprivileged_userns = 0' > /etc/sysctl.d/60-unpriv-userns.conf && sysctl -p /etc/sysctl.d/60-unpriv-userns.conf"
    echo "  Do NOT work around it with 'codex --dangerously-bypass-approvals-and-sandbox'. See docs/CODEX_SANDBOX_LINUX.md."
  fi
fi

echo "PER-PROJECT setup: run ./init-project.sh from a project repo root"
echo "  -> creates .claude/loop.conf (cheap typecheck gate), docs/REVIEW_LEDGER.md, docs/RISK_MAP.md, AGENTS.md symlink."
echo "Optional root hardening: docs/EGRESS_SANDBOX.md."
echo "Done. Inside Claude Code, always call helpers by ABSOLUTE path."
