#!/usr/bin/env bash
# PreToolUse(Bash) hook — when a risky git/migration command is about to run, inject the
# gate checklist so the protocol is reinforced at the exact moment forgetting is costly.
# Advisory only: it injects context (additionalContext), it does NOT block — the human
# gate + the model's own judgment still apply. Scoped to protocol projects.
set -u

# Read the tool-call JSON from stdin.
INPUT="$(cat 2>/dev/null)"

# Only reinforce inside a protocol project.
{ [ -f CLAUDE.md ] && grep -q "PROTOCOL_VERSION\|Operating Contract" CLAUDE.md 2>/dev/null; } \
  || [ -f docs/OPERATING_CONTRACT.md ] || [ -f docs/MULTI_MODEL_PROTOCOL.md ] || exit 0

# Extract the command (prefer jq; fall back to a tolerant grep).
if command -v jq >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
else
  CMD="$(printf '%s' "$INPUT" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')"
fi

case "$CMD" in
  *"git push"*|*"git merge"*|*"git rebase"*|*"db push"*|*"supabase"*migration*|*"migrate"*|*"deploy"*)
    REMINDER="GATE CHECK before this action (v2.4). What risk tier is this change? L3 = money/auth·RLS/migration/schema/deploy/secrets/worker -> requires: tests green, a Codex diff review recorded, GLM red-team+audit, and an operator gate BEFORE you push/merge/apply/deploy. L2 -> Codex mandatory. If any required gate is missing for this tier, STOP and obtain it — do not merge/deploy unreviewed. (This is a reminder, not a block.)"
    if command -v jq >/dev/null 2>&1; then
      jq -n --arg c "$REMINDER" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
    else
      # No jq: surface via stderr (non-blocking, exit 0).
      printf '%s\n' "$REMINDER" >&2
    fi
    ;;
esac
exit 0
