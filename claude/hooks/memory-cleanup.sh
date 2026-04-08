#!/bin/bash
set -euo pipefail
# SessionStart hook — fire-and-forget memory cleanup.
# Prunes graph-superseded memories. No TTL — autoDream handles consolidation.
# Runs in background so it doesn't block session startup.

MEMENTO_API="http://127.0.0.1:8000"
CURL="/usr/bin/curl"

# Guard: only run if memento is reachable
$CURL -sf --max-time 2 "${MEMENTO_API}/health" >/dev/null 2>&1 || exit 0

# Fire cleanup in background
$CURL -sf --max-time 15 \
  -X POST "${MEMENTO_API}/api/memory/cleanup" \
  -H "Content-Type: application/json" \
  -d '{"prune_superseded":true}' \
  >/dev/null 2>&1 &

exit 0
