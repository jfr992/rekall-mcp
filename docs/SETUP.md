# Setup Guide

Give Claude a memory that persists across conversations.

---

## What This Does

When you chat with Claude, it normally forgets everything when you close the conversation. This tool gives Claude:

- **Persistent memory** - Remembers preferences, decisions, and project context
- **Knowledge graph** - Typed relationships between memories (led_to, depends_on, supersedes, etc.)
- **Graph-enhanced search** - Finds memories by meaning AND structural relationships
- **Project awareness** - Knows which project you're working on

Before configuring behavior, see `docs/CLAUDE_MEMORY_SETTINGS.md` for the canonical policy and tuning knobs.

---

## Quick Start with Docker (Recommended)

Everything runs in containers. No Python install needed.

### Step 1: Start the Services

```bash
git clone <repo>
cd rekall-mcp
docker compose up -d
```

This starts:
- **Qdrant** - Vector database for semantic search
- **MCP Server** - Memory tools with embeddings + knowledge graph

### Step 2: Tell Claude About It

```bash
claude mcp add --transport http rekall http://localhost:8000
```

Verify:
```bash
claude mcp list  # Should show: memory (http) - http://localhost:8000
```

### Step 3: Verify It's Working

```bash
# Check services are running
docker compose ps

# Check health
curl http://localhost:8000/health

# Cockpit UI is part of the stack — browse http://localhost:3333
# (for UI dev only: cd ui && npm run dev -- -p 3333)
```

### Step 4: Build the Knowledge Graph

If you already have memories from a previous version, rebuild the graph to create relationships:

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

This processes all existing memories and creates typed edges between them. Only needed once after initial setup or upgrade.

**Done.** Claude can now save and recall memories with graph-enhanced retrieval.

---

## Teaching Claude to Use Memory

Once the MCP server is running, add instructions to your project:

### Option A: Project-level (recommended)

Create `CLAUDE.md` at your project root (or `.claude/CLAUDE.md` if you prefer the dotfile layout — Claude Code reads either):

```markdown
## Memory System

At session start:
1. Call `get_cached_context(project="my-project")` for flat context
2. Or `get_hierarchical_context(project="my-project")` for topic-grouped context

When working, save important context:
- `observe("Chose PostgreSQL for JSON support")` — auto-classifies and auto-links
- `save_memory("Must use Python 3.11+", type="requirement")` — explicit type

Memory types: requirement, decision, preference, fact, learning, note

For maintenance:
- `memory_stats()` — check graph health (node/edge counts)
- `rebuild_knowledge_graph()` — if graph shows 0 edges
- `consolidate_memories()` — find duplicates/conflicts
```

### Option B: Global

Add to `~/.claude/CLAUDE.md` to use memory in all projects.

### Memory Tools Available

| Tool | Purpose |
|------|---------|
| `observe(summary)` | Auto-classify, save, and auto-link |
| `recall_memories(query, ...)` | Graph-enhanced semantic search |
| `save_memory(content, type, project)` | Manual save with explicit type |
| `get_cached_context(project)` | Flat context (prompt-cache optimized) |
| `get_hierarchical_context(project)` | Topic-grouped context tree |
| `skill_context()` | Extracted skills from memory clusters |
| `memory_stats()` | Health + graph metrics |
| `consolidate_memories()` | Detect duplicates/conflicts |
| `proactive_context_summary()` | Top signals by importance x recency |
| `rebuild_knowledge_graph()` | Rebuild graph from all memories |

---

## Quick Start without Docker

If you prefer running locally:

### Step 1: Install

```bash
git clone <repo>
cd rekall-mcp
pip install -e .
```

### Step 2: Start Qdrant

You still need Qdrant (easiest in Docker):

```bash
docker compose up -d qdrant
```

### Step 3: Tell Claude About It

```bash
# Run from src/ (the CLI has no --cwd flag; the working dir is where you invoke it)
cd /path/to/rekall-mcp/src
claude mcp add rekall -- python -m server
```

Or manually edit `~/.claude/claude_code_config.json` (lets you pin `cwd`):
```json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "/path/to/rekall-mcp/src"
    }
  }
}
```

### Step 4: Test It

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/memory/stats
```

---

## How It Works

```
You tell Claude something
        |
Claude saves it as a memory
        |
Memory gets embedded + stored in YAML + Qdrant
        |
Knowledge graph node created, auto-linked to related memories
        |
Later: Claude recalls by meaning + follows graph relationships
```

**Your memories are stored in three places:**
1. **YAML files** (`~/.claude/memory/`) - Human-readable, source of truth
2. **Qdrant** - Searchable vector database for semantic search
3. **Knowledge graph** (`~/.claude/memory/_graph.json`) - Typed relationships

---

## Choosing an Embedding Provider

The "embedding" converts text into searchable vectors. Three options:

> **Important:** Switching providers requires a migration step. See [Switching Providers](#switching-providers-important) below.

### Option A: sentence-transformers (Default)

- Runs on your computer, free, fast, just works

### Option B: Ollama

- Better quality, still free and local
- Requires: `brew install ollama && ollama pull nomic-embed-text`

### Option C: Gemini

- Best quality, free tier (1,500 req/day)
- Requires: API key from https://ai.google.dev/

Set via environment variable:
```bash
EMBEDDING_PROVIDER=sentence-transformers  # or ollama, gemini
```

---

## Switching Providers (Important!)

Each embedding provider creates vectors in its own "language." After switching:

```bash
# Run the migration tool
cd src && python -m memory.migrate

# Then rebuild the knowledge graph
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

---

## Data Safety & Backups

```
~/.claude/
├── memory/
│   ├── *.yaml          # Your memories (source of truth)
│   └── _graph.json     # Knowledge graph (rebuildable)
└── qdrant/             # Search index (rebuildable)
```

### Backup

```bash
cp -r ~/.claude ~/claude-backup-$(date +%Y%m%d)
```

### Lost Qdrant data?

Rebuild from YAML:
```bash
cd src && python -m memory.migrate
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

### Lost the graph?

Rebuild from Qdrant:
```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

### Lost the YAML files?

That's the real data. **Back them up.** Qdrant and graph alone aren't enough.

---

## Storage Management

### Check current usage

```bash
curl http://localhost:8000/api/memory/stats
```

### Find duplicates

```bash
curl http://localhost:8000/api/memory/consolidate
```

Review superseded pairs, then manually remove stale entries from `~/.claude/memory/*.yaml` and rebuild:

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

---

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `MEMORY_STORAGE_PATH` | `~/.claude/memory` | YAML storage path |
| `EMBEDDING_PROVIDER` | `sentence-transformers` | Embedding backend |
| `EMBEDDING_API_KEY` | (none) | For cloud providers |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `MCP_TRANSPORT` | `streamable-http` | Protocol (stdio or streamable-http) |
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `8000` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Troubleshooting

**"Connection refused" to Qdrant** - Start it: `docker compose up -d qdrant`

**Memories not found** - Rebuild the search index: `cd src && python -m memory.migrate`

**Graph has 0 edges** - Rebuild: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`

**"Rate limit exceeded" (Gemini)** - Switch to sentence-transformers, run migrate, rebuild graph

**Debug logging:** `LOG_LEVEL=DEBUG python -m server`
