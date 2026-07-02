#!/usr/bin/env bash
# Stop the Rekall stack cleanly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "→ Stopping UI…"
pkill -f "next dev -p 3333" 2>/dev/null || true

echo "→ Stopping backend…"
# Match the actual python process (the resolved interpreter runs `-m server`),
# not the `uv run` wrapper string — the wrapper pattern never matched and left zombies.
pkill -f "python -m server" 2>/dev/null || true

echo "→ Stopping Qdrant…"
docker-compose stop qdrant 2>/dev/null || true

echo "✓ Rekall stopped. Qdrant volume at ~/.claude/qdrant preserved."
