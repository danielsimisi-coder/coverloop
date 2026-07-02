#!/usr/bin/env bash
# v2.3 auto-capture (Stop / PostToolUseFailure hook). Appends a compact line to
# ~/.claude/reflect-staging.md for reflect-and-save to curate later. Never blocks.
set -u
STAGE="$HOME/.claude/reflect-staging.md"
mkdir -p "$HOME/.claude"
TS="$(date -u +%FT%TZ 2>/dev/null || date)"
EVENT="$(cat 2>/dev/null | tr '\n\t' '  ' | cut -c1-300)"
printf '%s | %s\n' "$TS" "${EVENT:-session-stop}" >> "$STAGE"
# rotation (v2.5): keep the newest 300 lines so the staging file never grows unbounded
if [ "$(wc -l < "$STAGE" 2>/dev/null || echo 0)" -gt 500 ]; then
  tail -n 300 "$STAGE" > "$STAGE.tmp" && mv "$STAGE.tmp" "$STAGE"
fi
exit 0
