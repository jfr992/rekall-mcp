---
name: memory-recall
description: Search memories using semantic search with graph-enhanced ranking. Returns results boosted by relationship graph (importance, recency, graph proximity). Use when stuck, needing historical context, or looking for past solutions.
user-invocable: true
allowed-tools: Bash(*)
context: fork
agent: Explore
---

Policy: See memento-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for recall limits and project scoping.

# Search Results: $ARGUMENTS

!`jq -n --arg query "$ARGUMENTS" '{"query": $query, "limit": 8}' | curl -s http://localhost:8000/api/memory/recall -X POST -H "Content-Type: application/json" -d @- 2>/dev/null | jq -r '.memories[] | "[\(.type)] (score: \(.score), vector: \(.vector_score // "n/a")) \(.content)"' 2>/dev/null || echo "No results found"`

Recall is graph-enhanced: results include memories found via relationship traversal (not just cosine similarity). The `score` is a composite of vector similarity (50%), importance (20%), recency (15%), and graph proximity (15%).

Analyze and synthesize the above memories into your response.
