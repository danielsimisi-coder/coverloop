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

# Extract the command (prefer jq). Without jq, DON'T try to precisely parse the
# JSON — the old grep/sed truncated at the first escaped quote, so a risky
# command preceded by any quoted string silently missed the reminder. This is
# an advisory hook, so fail LOUD: match risky keywords against the raw input
# (an extra reminder is harmless; a silently-missing one defeats the hook).
if command -v jq >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
else
  CMD="$INPUT"
fi

case "$CMD" in
  *"git push"*|*"git merge"*|*"git rebase"*|*"db push"*|*"supabase"*migration*|*"migrate"*|*"deploy"*)
    REMINDER="GATE CHECK before this action (v2.11.0). What risk tier is this change? L3 = money/auth·RLS/migration/schema/deploy/secrets/worker -> requires: tests green, a Codex diff review recorded, GLM red-team+audit, and an operator gate BEFORE you push/merge/apply/deploy. L2 -> Codex mandatory. Reviews are OFF-POLICY: the reviewer gets a cold diff in a FRESH session (never 'review your own work' in this conversation), and Sol gates need EXPLICIT effort (high for L2 / xhigh for L3, never ultra). If this repo has .coverloop/, DON'T rely on this reminder — run 'coverloop gate' (fail-closed, exit 1 on missing evidence) and record it with 'coverloop attest', attaching the review transcript you already have (--codex-log/--glm-log). If the gate says evidence is STALE, commits landed after the attest — RE-ATTEST AT HEAD, never push stale. L3 '--approve' only when the operator named THIS action (a generic 'go ahead' is not an approval). If any required gate is missing for this tier, STOP and obtain it — do not merge/deploy unreviewed. (This message is a reminder; coverloop gate is the enforcement.)"
    if command -v jq >/dev/null 2>&1; then
      jq -n --arg c "$REMINDER" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
    else
      # No jq: surface via stderr (non-blocking, exit 0).
      printf '%s\n' "$REMINDER" >&2
    fi
    ;;
esac
exit 0
