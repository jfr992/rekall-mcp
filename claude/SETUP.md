# Memento MCP — Setup Guide

This document is for **Claude Code** to follow when a user asks to install or set up Memento MCP. Read and execute these steps — do not just display them.

## Prerequisites

- Docker and Docker Compose installed
- Claude Code CLI installed (`claude` available in PATH)
- `jq` installed (for skill shell commands)

## Installation Steps

### 1. Start services

```bash
cd <repo-root>
docker compose up -d
```

Wait for healthy:

```bash
curl -s http://localhost:8000/health | jq .
```

Expected: `{"status": "ok"}`. If not, wait 10s and retry once.

### 2. Register MCP server with Claude Code

```bash
claude mcp add --transport http memory http://localhost:8000/mcp
```

This registers the server globally so all projects can use memory tools.

### 3. Install skills

Copy all memory skills to the global Claude Code skills directory:

```bash
cp -r <repo-root>/claude/skills/memory-* ~/.claude/skills/
```

Verify:

```bash
ls ~/.claude/skills/ | grep memory
```

Expected: 7 directories (memory-restore, memory-observe, memory-recall, memory-stats, memory-rebuild, memory-consolidate, memory-skills).

### 4. Install hooks (per-project)

For any project where you want automatic memory restoration on session start, copy the hooks config into that project's `.claude/` directory:

```bash
mkdir -p <project-dir>/.claude
cp <repo-root>/claude/hooks.json <project-dir>/.claude/hooks.json
```

If the project already has a `.claude/hooks.json`, merge the `user-prompt-submit` entry manually rather than overwriting.

### 5. Verify end-to-end

```bash
# Server health
curl -s http://localhost:8000/health | jq .

# Memory stats
curl -s http://localhost:8000/api/memory/stats | jq .

# Dashboard (optional)
echo "Dashboard: http://localhost:8000/dashboard"
```

## Uninstall

```bash
# Stop services
cd <repo-root> && docker compose down

# Remove MCP registration
claude mcp remove memory

# Remove skills
rm -rf ~/.claude/skills/memory-{restore,observe,recall,stats,rebuild,consolidate,skills}

# Remove hooks (per-project, only if memento is the only hook)
rm <project-dir>/.claude/hooks.json
```

## Updating

After pulling new changes:

```bash
cd <repo-root>
docker compose down
docker compose build --no-cache mcp
docker compose up -d
cp -r claude/skills/memory-* ~/.claude/skills/
```

## Available Skills After Install

| Command | Purpose |
|---------|---------|
| `/memory-restore` | Load memories at session start |
| `/memory-recall <query>` | Graph-enhanced semantic search |
| `/memory-observe <note>` | Save an observation to memory |
| `/memory-stats` | System health and graph metrics |
| `/memory-rebuild` | Rebuild knowledge graph |
| `/memory-consolidate` | Find duplicates and conflicts |
| `/memory-skills` | Show learned capabilities |

## Available MCP Tools After Install

| Tool | Purpose |
|------|---------|
| `observe()` | Auto-classify and save memory |
| `recall_memories()` | Graph-enhanced semantic search |
| `save_memory()` | Manual save with explicit type |
| `get_cached_context()` | Flat context (prompt-cache optimized) |
| `get_hierarchical_context()` | Topic-grouped context tree |
| `skill_context()` | Extracted skills from memory clusters |
| `memory_stats()` | System health and statistics |
| `consolidate_memories()` | Detect duplicates and conflicts |
| `proactive_context_summary()` | Top signals ranked by importance*recency |
| `rebuild_knowledge_graph()` | Rebuild graph from all existing memories |
