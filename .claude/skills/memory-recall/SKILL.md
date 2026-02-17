---
name: memory-recall
description: Search memories using semantic search. Use when stuck, needing historical context, or looking for past solutions to similar problems. Triggers on questions about past work.
user-invocable: true
allowed-tools: Bash(*)
context: fork
agent: Explore
---

Policy: See memento-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for recall limits and project scoping.

# Search Results: $ARGUMENTS

!`echo "{\"query\": \"$ARGUMENTS\", \"limit\": 5}" | curl -s http://localhost:8000/api/memory/recall -X POST -H "Content-Type: application/json" -d @- 2>/dev/null | jq -r '.memories[] | "[\(.type)] \(.content) (score: \(.score))"' 2>/dev/null || echo "No results found"`

Analyze and synthesize the above memories into your response.
