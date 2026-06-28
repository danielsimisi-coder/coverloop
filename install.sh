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
echo "Done. Inside Claude Code, always call helpers by ABSOLUTE path."
