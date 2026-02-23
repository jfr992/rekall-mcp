---
name: memory-consolidate
description: Detect duplicate and contradictory memories. Shows superseded pairs (near-identical) and conflicts (opposing content). Use to clean up memory drift or after bulk imports.
user-invocable: true
allowed-tools: Bash(curl *)
---

# Memory Consolidation Report

!`curl -s 'http://localhost:8000/api/memory/consolidate?limit=50' 2>/dev/null | jq -r '.summary // "No consolidation data"' 2>/dev/null || echo "Consolidation unavailable"`

Review the superseded and conflicting pairs above. To clean up, manually remove stale YAML entries from `~/.claude/memory/` and rebuild the graph with `/memory-rebuild`.
