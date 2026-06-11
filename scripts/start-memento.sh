#!/usr/bin/env bash
# Start the Memento stack: Qdrant (via docker-compose), backend, UI.
# Idempotent — safe to run multiple times.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# --- Qdrant ---
if curl -sfo /dev/null http://localhost:6333/healthz; then
  echo "✓ Qdrant already running"
else
  echo "→ Starting Qdrant…"
  docker-compose up -d qdrant
  until curl -sfo /dev/null http://localhost:6333/healthz; do
    sleep 1
  done
  echo "✓ Qdrant UP"
fi

# --- Backend ---
if curl -sfo /dev/null http://localhost:8000/health; then
  echo "✓ Backend already running on :8000"
else
  echo "→ Starting backend on :8000…"
  # 0.0.0.0 so Claude Code can reach the server through port-mapped/namespaced
  # networks (Docker, WSL, devcontainer). Set MEMENTO_HOST=127.0.0.1 on untrusted nets.
  nohup env \
    MCP_TRANSPORT=streamable-http \
    HOST="${MEMENTO_HOST:-0.0.0.0}" \
    PORT=8000 \
    QDRANT_URL=http://localhost:6333 \
    uv run python -m server \
    > /tmp/memento-backend.log 2>&1 &
  until curl -sfo /dev/null http://localhost:8000/health; do
    sleep 1
  done
  echo "✓ Backend UP (PID $!)"
fi

# --- UI ---
if curl -sfo /dev/null --max-time 3 http://localhost:3333; then
  echo "✓ UI already running on :3333"
else
  echo "→ Starting UI on :3333…"
  cd ui
  nohup npx next dev -p 3333 > /tmp/memento-ui.log 2>&1 &
  UI_PID=$!
  cd ..
  # UI takes longer to compile — give it up to 30s
  for _ in {1..30}; do
    if curl -sfo /dev/null --max-time 2 http://localhost:3333; then break; fi
    sleep 1
  done
  echo "✓ UI UP (PID $UI_PID)"
fi

echo ""
echo "Memento stack is up:"
echo "  Qdrant:  http://localhost:6333"
echo "  Backend: http://localhost:8000"
echo "  Cockpit: http://localhost:3333"
echo ""
curl -sf http://localhost:8000/api/memory/stats 2>/dev/null | python3 -c "
import sys, json
s = json.load(sys.stdin)
kg = s.get('knowledge_graph', {})
print(f\"  Memories: {s.get('total_memories', 0)}  |  Graph: {kg.get('nodes', 0)} nodes, {kg.get('edges', 0)} edges\")
" 2>/dev/null || true
