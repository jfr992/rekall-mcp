---
name: memory-skills
description: Show extracted skills from memory clusters. Skills are capabilities Claude has learned across sessions, synthesized from multiple related memories. Use to understand what knowledge is available.
user-invocable: true
allowed-tools: Bash(curl *)
---

# Extracted Skills

!`curl -s 'http://localhost:8000/api/memory/context/skills?max_skills=10' 2>/dev/null | jq -r '.summary // "No skills extracted"' 2>/dev/null || echo "Skills unavailable"`

Skills are auto-extracted from memory clusters. Each skill represents a capability backed by multiple memories (decisions, learnings, preferences).
