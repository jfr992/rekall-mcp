# Memento MCP - Project Context

## What This Is

Memento MCP is a persistent memory system for AI assistants with a **knowledge graph** layer. It gives Claude associative memory — typed relationships between memories, graph-enhanced retrieval, and hierarchical context — using:
- Local YAML files (`~/.claude/memory/`) for human-editable storage
- Qdrant vector database for semantic search (384-dim, all-MiniLM-L6-v2)
- Knowledge graph (`~/.claude/memory/_graph.json`) for typed relationships (networkx)
- Sentence-transformers embeddings (local, free)

## Running the Server

```bash
cd /Users/jfr9044/Repos/memento-mcp
docker compose up -d
```

Verify:
```bash
curl http://localhost:8000/health
```

## API Endpoints

### Core

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/memory/save` | POST | Save a memory |
| `/api/memory/recall` | POST | Graph-enhanced semantic search |
| `/api/memory/stats` | GET | Get statistics |
| `/api/memory/context` | GET | Get flat project context (cacheable) |
| `/api/memory/observe` | POST | Auto-classify and save |

### Knowledge Graph

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/memory/graph` | GET | Graph visualization data (nodes + edges) |
| `/api/memory/graph/rebuild` | POST | Rebuild knowledge graph from all memories |
| `/api/memory/context/hierarchy` | GET | Topic-grouped hierarchical context |
| `/api/memory/context/proactive` | GET | Top signals + conflict check |
| `/api/memory/consolidate` | GET | Detect superseded/contradictory memory pairs |

### MCP Tools (native, via claude_code_config.json)

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

## Project Structure

```
src/
├── server.py               # MCP server with REST API endpoints + dashboard
├── core/                   # Embedder, VectorStore, Telemetry, utils
│   └── utils.py            # stable_hash_id() — single source for string→int64 hashing
├── memory/
│   ├── manager.py          # MemoryManager (save, recall, get_stats)
│   ├── knowledge_graph.py  # KnowledgeGraph — persistent directed graph (networkx)
│   ├── linker.py           # Auto-linking: classify relations on save
│   ├── graph.py            # Visualization graph builder
│   ├── cache_context.py    # Stable cacheable context + hierarchical variant
│   ├── topics.py           # Topic auto-classification (agglomerative clustering)
│   └── skills.py           # Skill extraction from memory clusters
├── crawler/                # Documentation crawler (Scrapy)
├── indexer/                # Document chunker + Qdrant indexer
└── tools/                  # MCP tool definitions
```

## Knowledge Graph

### How It Works

Every `save()` / `observe()` call:
1. Saves to YAML + Qdrant (as before)
2. Adds a node to the knowledge graph
3. Auto-links to related memories with typed edges

### Relation Types

| Relation | Meaning | Example |
|----------|---------|---------|
| `related_to` | Semantically similar (default) | Two PostgreSQL facts |
| `led_to` | Temporal causation | Decision → Learning it caused |
| `depends_on` | Structural dependency | Decision → Requirement it needs |
| `supersedes` | Newer replaces older | Updated decision overwrites old |
| `contradicts` | Opposing content | Conflicting memories |
| `part_of` | Belongs to topic cluster | Memory → Topic |

### Graph-Enhanced Recall

`recall_memories()` uses a 3-phase pipeline:
1. **SEED** — vector search (top K × 2 candidates)
2. **EXPAND** — traverse 1-hop graph neighbors of seed results
3. **RANK** — composite score: `vector(50%) + importance(20%) + recency(15%) + graph_proximity(15%)`

Falls back to pure vector search when graph is empty.

### Maintenance

- **Rebuild graph**: `POST /api/memory/graph/rebuild` or MCP tool `rebuild_knowledge_graph()`
- **Check health**: `GET /api/memory/stats` includes graph node/edge counts
- **Clean duplicates**: `GET /api/memory/consolidate` shows superseded pairs
- **Dashboard**: `http://localhost:8000/dashboard` — force-directed graph visualization

## Memory System

Memory restoration is automatic via `.claude/hooks.json` → `/memory-restore` skill.

**SAVE MEMORIES IMMEDIATELY WHEN:**
- User states a preference → `observe()` as preference
- User corrects you → `observe()` as learning
- Bug fixed / gotcha discovered → `observe()` as learning
- Architecture/tool decision made → `observe()` as decision
- Project constraint identified → `observe()` as requirement

**DO NOT SAVE:**
- Obvious/generic info (e.g., "Python uses indentation")
- Temporary context (e.g., "working on file X")
- Speculative/uncertain conclusions
- Anything already in the codebase or docs

**DO NOT** batch saves for end of session - context may be lost.
**DO NOT** wait for user to remind you.

## Running Tests

**IMPORTANT:** Tests are now isolated and won't affect production data.

```bash
# Run all tests (fast, local)
uv run --extra dev pytest -v

# Run all tests (isolated Docker environment)
docker compose --profile test run --rm test

# Run specific test file
docker compose --profile test run --rm test pytest tests/test_memory.py -v

# Cleanup test containers
docker compose --profile test down
```

**Architecture:**
- Production Qdrant: `localhost:6333` → `~/.claude/qdrant` (persistent)
- Production YAML: `~/.claude/memory/*.yaml` (persistent)
- Production Graph: `~/.claude/memory/_graph.json` (persistent)
- Test Qdrant: `localhost:6334` → tmpfs (deleted on stop)
- Test YAML: `/tmp/test_memory` inside container (deleted on stop)

## Recent Work

- Knowledge Graph: 4-phase implementation (foundation, hierarchy, skills, intelligence)
- Auto-linking on save with 5 relation rules (supersedes, led_to, depends_on, contradicts, related_to)
- Graph-enhanced recall (seed → expand → rank pipeline)
- Topic clustering (agglomerative) + hierarchical context generation
- Skill extraction from memory clusters
- Memory consolidation and proactive context summary
- All tests passing (237 passed, 9 skipped)
