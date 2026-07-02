---
name: memory-observe
description: Record important information when user explicitly requests it (e.g., "remember this", "save this"). Only auto-save for major refactors or significant features - be conservative.
user-invocable: true
allowed-tools: Bash(*)
---

Policy: See rekall-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for save/skip rules.

# Record Observation: $ARGUMENTS

Save this to memory with auto-classification:

!`jq -n --arg summary "$ARGUMENTS" '{"summary": $summary, "type": "auto"}' | curl -s http://localhost:8000/api/memory/observe -X POST -H "Content-Type: application/json" -d @- 2>/dev/null | jq -r '.status' 2>/dev/null || echo "Failed to save"`

✓ Observation recorded and available for future sessions.
