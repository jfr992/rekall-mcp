---
name: memory-restore
description: Manually restore proactive context (importance-ranked) into the current session. User-invocable only — no auto-trigger. Use when you want to surface historical project knowledge, past decisions, or learnings.
user-invocable: true
allowed-tools: Bash(*)
---

Policy: See memento-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for session-start and recall defaults.

# Session Memory Restoration

## Hierarchical Context (topic-grouped)
!`curl -s 'http://localhost:8000/api/memory/context/hierarchy?max_topics=8' 2>/dev/null | jq -r '.context // empty' || echo ""`

## Flat Context (fallback)
!`curl -s http://localhost:8000/api/memory/context 2>/dev/null | jq -r '.context // "No memories available"'`

Synthesize the above memories naturally into your understanding. Don't list them explicitly.

## Stats
!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq '{total: .total_memories, files: .memory_files}' || echo "Stats unavailable"`
