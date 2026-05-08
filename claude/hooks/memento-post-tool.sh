#!/usr/bin/env bash
# ~/.claude/hooks/memento-post-tool.sh
# Fires after Bash tool calls. Captures git commits as session memories.
#
# Kill switch: MEMENTO_AUTOSAVE=0
# Backend URL: MEMENTO_API_URL (default http://localhost:8000)
set -euo pipefail

API="${MEMENTO_API_URL:-http://localhost:8000}"
[[ "${MEMENTO_AUTOSAVE:-1}" == "0" ]] && exit 0

# Silent exit if backend is down
curl -sfo /dev/null --max-time 1 "$API/health" 2>/dev/null || exit 0

# Read the hook payload from stdin
payload=$(cat 2>/dev/null || true)
[[ -z "$payload" ]] && exit 0

# Extract tool input (the command that was run)
tool_input=$(echo "$payload" | jq -r '.tool_input.command // .input.command // ""' 2>/dev/null || true)
tool_output=$(echo "$payload" | jq -r '.tool_result // .output // ""' 2>/dev/null | head -c 500 || true)

# Only care about git commits
if echo "$tool_input" | grep -qE 'git commit'; then
  # Extract the commit SHA and subject from the output
  sha=$(echo "$tool_output" | grep -oE '[0-9a-f]{7,12}' | head -1 || true)
  subject=$(echo "$tool_output" | grep -oE '\] .+' | head -1 | sed 's/^\] //' || true)

  if [[ -n "$sha" && -n "$subject" ]]; then
    jq -n \
      --arg summary "Committed $sha: $subject" \
      --arg context "git commit autosave" \
      '{"summary": $summary, "type": "auto", "context": $context}' \
    | curl -sf --max-time 2 \
        -X POST \
        -H "Content-Type: application/json" \
        --data @- \
        "$API/api/memory/observe" >/dev/null 2>&1 || true
  fi
fi

exit 0
