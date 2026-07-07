#!/usr/bin/env bash
# claude/hooks/memory-prune.sh — SessionStart. Fires the GATED superseded-prune
# at most once per day. Server-side gates do the real safety work; this is a
# thin, debounced trigger. Kill switch: REKALL_AUTOSAVE=0.
set -euo pipefail

API="${REKALL_API_URL:-http://localhost:8000}"
[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

MARKER="${REKALL_MARKER_DIR:-/tmp}/rekall-prune-$(date +%Y%m%d)"
[[ -f "$MARKER" ]] && exit 0
touch "$MARKER"

resp=$(curl -sf --max-time 10 -X POST "$API/api/memory/prune/superseded" \
  -H 'Content-Type: application/json' \
  -d "{\"confirm_date\": \"$(date +%Y-%m-%d)\"}" 2>/dev/null) || exit 0

deleted=$(echo "$resp" | jq -r '.deleted | length' 2>/dev/null || echo 0)
if [[ "$deleted" != "0" ]]; then
  echo "Rekall prune: $deleted superseded memories removed (backup taken). $(echo "$resp" | jq -c '.deleted')"
fi
exit 0
