#!/usr/bin/env bash
# ~/.claude/hooks/rekall-restore.sh
# Fires on UserPromptSubmit. Loads memory context ONCE per session,
# then silently exits on subsequent prompts to avoid wasting tokens.
#
# Kill switch: REKALL_AUTOSAVE=0
# Backend URL: REKALL_API_URL (default http://localhost:8000)
set -euo pipefail

API="${REKALL_API_URL:-http://localhost:8000}"
[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

# Session marker — skip if we already restored in this session.
# Uses $CLAUDE_SESSION_ID if available, falls back to PID-based marker.
SESSION_ID="${CLAUDE_SESSION_ID:-$$}"
MARKER="${REKALL_MARKER_DIR:-/tmp}/rekall-restored-${SESSION_ID}"

if [[ -f "$MARKER" ]]; then
  # Already restored this session. Exit silently — no output = no tokens.
  exit 0
fi

# Backend alive? Capture the body — /health carries the zero-vector tripwire.
health=$(curl -sf --max-time 1 "$API/health" 2>/dev/null) || exit 0

# Vector-corruption tripwire: two prod incidents sat undetected for days
# because this line only showed counts. Absent vectors block → no indicator.
vectors=$(jq -r 'if .vectors == null then ""
  elif .vectors.zero_vectors == 0 then " · vectors OK"
  else " · ⚠ \(.vectors.zero_vectors) dead vectors" end' <<< "$health" 2>/dev/null || true)

# Zero-injection mode: check backend is alive, print a one-liner with
# memory count, done. Model uses recall_memories() / mcp__rekall__recall
# on demand instead of burning tokens on a dump every session.
stats=$(curl -sf --max-time 2 "$API/api/memory/stats" 2>/dev/null \
  | jq -r '"\(.total_memories // 0) memories · \(.knowledge_graph.nodes // 0) nodes · \(.knowledge_graph.edges // 0) edges"' 2>/dev/null || true)

touch "$MARKER"

if [[ -n "$stats" ]]; then
  # Imperative wording measured: soft "on demand" left agents skipping memory on
  # ~45% of memory-dependent questions (eval run 8); check-first closes the gap.
  echo "Rekall ready — ${stats}${vectors}. Before answering anything about prior decisions, current values, or past work: check memory first with recall_memories()."
fi

exit 0
