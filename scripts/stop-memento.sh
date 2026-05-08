#!/usr/bin/env bash
# Stop the Memento stack cleanly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "→ Stopping UI…"
pkill -f "next dev -p 3333" 2>/dev/null || true

echo "→ Stopping backend…"
pkill -f "uv run python -m server" 2>/dev/null || true

echo "→ Stopping Qdrant…"
docker-compose stop qdrant 2>/dev/null || true

echo "✓ Memento stopped. Qdrant volume at ~/.claude/qdrant preserved."
