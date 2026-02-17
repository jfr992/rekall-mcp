---
name: memory-restore
description: Restore cached memories from previous sessions automatically at session start or when resuming work. Use when you need historical project knowledge, past decisions, or learnings.
user-invocable: true
allowed-tools: Bash(*)
---

Policy: See memento-mcp/docs/CLAUDE_MEMORY_SETTINGS.md for session-start and recall defaults.

# Session Memory Restoration

!`curl -s http://localhost:8000/api/memory/context 2>/dev/null | jq -r '.context // "No memories available"'`

Synthesize the above memories naturally into your understanding. Don't list them explicitly.

## Stats
!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq '{total: .total_memories, files: .memory_files}' || echo "Stats unavailable"`
