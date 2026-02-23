---
name: memory-rebuild
description: Rebuild the knowledge graph from all existing memories. Creates typed relationships (led_to, depends_on, supersedes, contradicts, related_to) between memories. Run after upgrades, to fix corrupted graph, or when graph stats show 0 edges.
user-invocable: true
allowed-tools: Bash(curl *)
---

# Rebuild Knowledge Graph

!`curl -s -X POST http://localhost:8000/api/memory/graph/rebuild 2>/dev/null | jq . || echo "Rebuild failed — is the server running?"`

Graph rebuilt. New memories saved via `observe()` will auto-link going forward.
