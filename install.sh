#!/usr/bin/env bash
# Offline plan by default. --apply authorizes file copies; --wire-hooks is separate.
set -euo pipefail
command -v python3 >/dev/null || { echo 'python3 required; install it yourself before continuing.' >&2; exit 1; }
SRC="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 -B "$SRC/tools/install_local.py" "$@"
