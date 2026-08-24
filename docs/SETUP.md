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

> **Just trying it out?** The trial tier needs no Docker: `claude mcp add rekall -- uvx rekall-mcp` runs over stdio with an embedded vector store at `~/.rekall/qdrant`. See the [README quickstart](../README.md#install) for the tier table and trade-offs.

---

## Quick Start with Docker (Recommended)

Everything runs in containers. No Python install needed.

### Step 1: Start the Services

```bash
git clone https://github.com/jfr992/rekall-mcp.git
cd rekall-mcp
docker compose up -d
```

This starts three containers:
- **Qdrant** (:6333) - Vector database for semantic search
- **MCP Server** (:8000) - Memory tools with embeddings + knowledge graph
- **Cockpit UI** (:3333) - Next.js web cockpit

### Step 2: Tell Claude About It

```bash
claude mcp add --transport http rekall http://localhost:8000
```

Verify:
```bash
claude mcp list  # Should show: rekall (http) - http://localhost:8000
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

> **Coming from an older version?** See [docs/MIGRATION.md](MIGRATION.md) — notably
> `python -m memory.migrate_hybrid` for v1.7 → v1.8 and `scripts/migrate_repr_v2.py` for v1.10.

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
git clone https://github.com/jfr992/rekall-mcp.git
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

Or manually edit `~/.claude.json` (user scope — use `.mcp.json` in a project root for project scope; lets you pin `cwd`):
```json
{
  "mcpServers": {
    "rekall": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "/path/to/rekall-mcp/src"
    }
  }
}
```

### Step 4: Test It

Step 3 registered a stdio server, which Claude Code spawns on demand — nothing listens on :8000 yet. Start an HTTP instance to test the REST API:

```bash
MCP_TRANSPORT=streamable-http HOST=127.0.0.1 uv run python -m server &
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

The "embedding" converts text into searchable vectors. Four options:

> **Important:** Switching providers requires a migration step. See [Switching Providers](#switching-providers-important) below. Exception: fastembed ↔ sentence-transformers produce identical vectors — no migration.

### Option A: fastembed (Default)

- Runs on your computer, free, fast, no torch (ONNX runtime)
- Vector-identical to sentence-transformers (fp32 ONNX export of the same `all-MiniLM-L6-v2` model)

### Option B: sentence-transformers (optional `[torch]` extra)

- Same vectors as fastembed, but pulls in torch
- Install: `uv sync --extra torch` or `pip install 'rekall-mcp[torch]'`

### Option C: Ollama

- Better quality, still free and local
- Requires: `brew install ollama && ollama pull nomic-embed-text`

### Option D: Gemini

- Best quality, free tier (1,500 req/day)
- Requires: API key from https://ai.google.dev/

Set via environment variable:
```bash
EMBEDDING_PROVIDER=fastembed  # or sentence-transformers, ollama, gemini
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
│   ├── <project>/
│   │   └── <date>.yaml # Your memories (source of truth, nested per-project since v1.5)
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

## Storage

See [`docs/example-memory.yaml`](example-memory.yaml) for what a stored memory file looks like. Management

### Check current usage

```bash
curl http://localhost:8000/api/memory/stats
```

### Find duplicates

```bash
curl http://localhost:8000/api/memory/consolidate
```

Review superseded pairs, then manually remove stale entries from `~/.claude/memory/<project>/*.yaml` and rebuild:

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

---

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `QDRANT_PATH` | (none) | Embedded (local-path) Qdrant storage dir — mutually exclusive with `QDRANT_URL` |
| `REKALL_DIR` | `~/.rekall` | Rekall home for the uvx/serve tiers (embedded store, active-backend record) |
| `MEMORY_STORAGE_PATH` | `~/.claude/memory` | YAML storage path |
| `EMBEDDING_PROVIDER` | `fastembed` | Embedding backend (`sentence-transformers` needs the `[torch]` extra) |
| `GEMINI_API_KEY` | (none) | Gemini provider API key |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `MCP_TRANSPORT` | `stdio` | Protocol (stdio or streamable-http; Docker and start scripts set `streamable-http`) |
| `HOST` | `127.0.0.1` | Listen address (Docker sets `0.0.0.0` for port-mapping) |
| `PORT` | `8000` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Troubleshooting

**"Connection refused" to Qdrant** - Start it: `docker compose up -d qdrant`

**Memories not found** - Rebuild the search index: `cd src && python -m memory.migrate`

**Graph has 0 edges** - Rebuild: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`

**"Rate limit exceeded" (Gemini)** - Switch to fastembed, run migrate, rebuild graph

**Debug logging:** `LOG_LEVEL=DEBUG python -m server`

## Codex setup and native-memory coexistence

Rekall supports Codex as a first-class client. Start the local HTTP server (for example with `docker compose up -d`), then install the adapter from a checkout:

```bash
bash codex/setup/install.sh
# or, for MCP only:
codex mcp add rekall --url http://localhost:8000
```

The adapter backs up and merges Codex hook configuration, preserves unrelated hooks, and installs `SessionStart`, `PreToolUse`, `PreCompact`, `PostCompact`, `PostToolUse`, and `SessionEnd`. It fails open when the server is unavailable and supports `REKALL_AUTOSAVE=0` and `REKALL_REFLEX=0` kill switches. Read [`codex/INSTALL.md`](../codex/INSTALL.md) before changing a live profile.

The installer pins the validated REST base into lifecycle hooks as `REKALL_API_URL`. A root MCP URL uses the same origin automatically. If the MCP transport URL has a path such as `/mcp`, pass its REST base separately with `--api-url`; the installer refuses to guess. Remote MCP or API URLs require `--allow-remote-mcp`. Re-run the installer if either endpoint changes.

If the server uses `REKALL_API_TOKEN`, make it available in Codex's launch environment and run `bash codex/setup/install.sh --bearer-token-env-var REKALL_API_TOKEN`. Codex configuration and hooks retain only the variable name, never the token. Remove an existing unauthenticated `rekall` MCP registration before switching it to authenticated mode; the installer refuses the mismatch rather than silently changing security behavior.

Codex native memory at `~/.codex/memories/` is independent of Rekall. Rekall never reads, writes, creates, deletes, or edits that directory. Restart Codex after installation so it reloads the MCP and hook configuration.
