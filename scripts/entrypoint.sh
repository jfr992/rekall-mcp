#!/bin/sh
set -e

# Embedded fallback: only when no external Qdrant is configured. Compose sets
# QDRANT_URL; exporting QDRANT_PATH unconditionally would trip the
# mutual-exclusion guard in VectorStore.
if [ -z "${QDRANT_URL:-}" ] && [ -z "${QDRANT_PATH:-}" ]; then
  QDRANT_PATH=/data/qdrant
  export QDRANT_PATH
fi

if [ "$(id -u)" = "0" ]; then
  MCP_UID=$(id -u mcp)
  # Recursive chown only when ownership is wrong — unconditional chown -R
  # scales with volume size.
  [ "$(stat -c %u /data)" = "$MCP_UID" ] || chown -R mcp:mcp /data || {
    echo "FATAL: cannot chown /data" >&2
    exit 1
  }
  exec gosu mcp "$@"
fi
exec "$@"
