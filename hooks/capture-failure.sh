#!/usr/bin/env bash
# Metadata-only diagnostic capture; no raw command/error/event retention.
set -u
HERE="$(cd -- "$(dirname -- "$0")" && pwd)" || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
python3 -B "$HERE/capture_failure.py" || true
exit 0
