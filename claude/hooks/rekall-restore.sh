#!/usr/bin/env bash
# ~/.claude/hooks/rekall-restore.sh
# Fires on UserPromptSubmit. Loads memory context ONCE per session,
# then silently exits on subsequent prompts to avoid wasting tokens.
#
# Kill switch: MEMENTO_AUTOSAVE=0
# Backend URL: MEMENTO_API_URL (default http://localhost:8000)
set -euo pipefail

API="${MEMENTO_API_URL:-http://localhost:8000}"
[[ "${MEMENTO_AUTOSAVE:-1}" == "0" ]] && exit 0

# Session marker — skip if we already restored in this session.
# Uses $CLAUDE_SESSION_ID if available, falls back to PID-based marker.
SESSION_ID="${CLAUDE_SESSION_ID:-$$}"
MARKER="/tmp/rekall-restored-${SESSION_ID}"

if [[ -f "$MARKER" ]]; then
  # Already restored this session. Exit silently — no output = no tokens.
  exit 0
fi

# Backend alive?
curl -sfo /dev/null --max-time 1 "$API/health" 2>/dev/null || exit 0

# Zero-injection mode: check backend is alive, print a one-liner with
# memory count, done. Model uses recall_memories() / mcp__rekall__recall
# on demand instead of burning tokens on a dump every session.
stats=$(curl -sf --max-time 2 "$API/api/memory/stats" 2>/dev/null \
  | jq -r '"\(.total_memories // 0) memories · \(.knowledge_graph.nodes // 0) nodes · \(.knowledge_graph.edges // 0) edges"' 2>/dev/null || true)

touch "$MARKER"

if [[ -n "$stats" ]]; then
  echo "Rekall ready — $stats. Use recall_memories() on demand."
fi

exit 0
