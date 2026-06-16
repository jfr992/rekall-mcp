---
name: memory-stats
description: Check memory system health and statistics including knowledge graph metrics. Use for diagnostics or understanding what's been stored.
user-invocable: true
allowed-tools: Bash(*)
---

Policy: See memento-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for drift-fix checklist.

# Memory System Status

!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq . || echo "Server not responding"`

## Knowledge Graph
!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq '.knowledge_graph // "Graph unavailable"' 2>/dev/null || echo "Graph unavailable"`

**Troubleshooting:**
- Check: `docker compose ps`
- Start: `docker compose up -d`
- Health: `curl http://localhost:8000/health`
- Rebuild graph: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`
