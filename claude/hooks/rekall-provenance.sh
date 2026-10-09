#!/usr/bin/env bash
# ~/.claude/hooks/rekall-provenance.sh
# PreToolUse on Rekall MCP tools. Fills cwd, session_id, agent when the model
# omitted them, so saves land in the caller's project and recalls attribute.
# Never gates: no permissionDecision, every failure path exits 0.
#
# Kill switch: REKALL_AUTOSAVE=0
set -uo pipefail

[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

payload="$(cat 2>/dev/null || true)"
[[ -z "$payload" ]] && exit 0

tool="$(jq -r '.tool_name // empty' <<<"$payload" 2>/dev/null || true)"
[[ -z "$tool" ]] && exit 0

case "$tool" in
  mcp__memory__recall_memories|mcp__rekall__recall_memories) ;;
  mcp__memory__observe|mcp__rekall__observe) ;;
  mcp__memory__save_memory|mcp__rekall__save_memory) ;;
  *) exit 0 ;;
esac

jq -c '
  .tool_input as $ti
  | ($ti // {}) as $in
  | ($in
     + (if ($in.cwd // "") == "" and (.cwd // "") != "" then {cwd: .cwd} else {} end)
     + (if ($in.session_id // "") == "" and (.session_id // "") != "" then {session_id: .session_id} else {} end)
     + (if ($in.agent // "") == "" then {agent: "claude-code"} else {} end)) as $out
  | {hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: $out}}
' <<<"$payload" 2>/dev/null || exit 0

exit 0
