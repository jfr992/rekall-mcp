# Memento MCP

**Give Claude a memory with associative recall.** Three steps, five minutes.

Memento MCP is a persistent memory system with a **knowledge graph** layer. It stores memories as YAML + vector embeddings, connects them with typed relationships, and retrieves context using graph-enhanced semantic search.

---

## Install

### 1. Download and Start

```bash
git clone https://github.com/jfr992/memento-mcp.git
cd memento-mcp
docker compose up -d                # starts Qdrant on :6333
bash scripts/start-memento.sh       # starts the MCP backend on :8000 (and the cockpit on :3333)
```

`start-memento.sh` is idempotent — re-run it any time. Memories live at `$MEMORY_STORAGE_PATH` (default `~/.claude/memory`); set the env var before running the script if you want a different location.

> **Need Docker?** Get it free at [docker.com/get-started](https://www.docker.com/get-started/)

### 2. Tell Claude

```bash
claude mcp add --transport http --url http://localhost:8000 memory
```

### 3. Verify

```bash
curl http://localhost:8000/health
```

**Done.** Claude now remembers things between sessions.

---

## How to Use

Just talk normally. Claude automatically remembers:

- **Decisions** - "Let's use PostgreSQL"
- **Preferences** - "I prefer TypeScript"
- **Lessons** - "That bug was caused by..."

To check memories: *"What do you remember about this project?"*

### Python API

```python
from memory import MemoryManager

memory = MemoryManager()

# Save (auto-links to related memories in the knowledge graph)
memory.save("Chose PostgreSQL for JSON support", type="decision", project="my-app")
memory.save("User prefers concise responses", type="preference")

# Recall (graph-enhanced: vector search + relationship traversal)
results = memory.recall("what database did we choose?")
for r in results:
    print(f"[{r['score']:.2f}] {r['content']}")

# Project context (flat or hierarchical)
context = memory.get_project_context("my-app")
```

### CLI

```bash
# Save
python -m memory.cli save "Decided to use PostgreSQL" --type decision --project my-app

# Recall
python -m memory.cli recall "database choices"
python -m memory.cli recall "recent work" --limit 3 --days 7

# Stats
python -m memory.cli stats
```

---

## Knowledge Graph

Every memory is a node. Relationships are typed edges created automatically on save:

| Relation | Meaning | Example |
|----------|---------|---------|
| `related_to` | Semantically similar | Two PostgreSQL facts |
| `led_to` | Temporal causation | Decision led to a learning |
| `depends_on` | Structural dependency | Decision depends on requirement |
| `supersedes` | Newer replaces older | Updated decision overwrites old |
| `contradicts` | Opposing content | Conflicting memories |

### Graph-Enhanced Recall

Recall uses a 3-phase pipeline instead of flat cosine search:

```
1. SEED    - Vector search (top K x 2 candidates)
2. EXPAND  - Traverse 1-hop graph neighbors of seed results
3. RANK    - Composite: vector(40%) + importance(20%) + proximity(15%) + tier(15%) + recency(10%)
```

This finds memories that are *structurally related*, not just textually similar. Falls back to pure vector search when the graph is empty.

### Cockpit UI

Browse the knowledge graph at `http://localhost:3333/brain` (Next.js cockpit, run with `cd ui && npm run dev -- -p 3333`). Surfaces:

- `/brain` — force-directed graph view, nodes are memories, edges show typed relationships
- `/kb` — typed columns (decisions, requirements, preferences, learnings)
- `/continuity` — resume packets and handoff summaries
- `/hygiene` — pressure metrics, prune flow, lifecycle backfill

---

## Slash command shortcuts (optional, manual)

`claude/skills/` ships seven user-invocable slash commands. They are NOT auto-triggering — type the slash command to invoke. Install once globally:

```bash
mkdir -p ~/.claude/skills
cp -r claude/skills/* ~/.claude/skills/
```

| Slash command | What it does |
|---------------|--------------|
| `/memory-observe <note>` | Manual save with auto-classification |
| `/memory-recall <query>` | Graph-enhanced semantic search |
| `/memory-restore` | Manual context restore (importance-ranked) |
| `/memory-stats` | Health check + graph metrics |
| `/memory-rebuild` | Rebuild the knowledge graph |
| `/memory-consolidate` | Detect duplicate and contradictory memories |
| `/memory-skills` | Show extracted skills from memory clusters |

The auto-save mechanism is the **Stop hook** at `claude/hooks/memento-observe.sh` (a Haiku judge gated by signal detection — keywords, new commits, or session length), not the slash commands. See [`claude/INSTALL.md`](claude/INSTALL.md) for hook setup.

---

## Your Data

Everything stays on your computer in editable files:

```
~/.claude/memory/
  2026-02-02.yaml       <- Human-editable memories
  _graph.json           <- Knowledge graph (auto-managed)
```

Nothing is sent anywhere. Backup = copy the folder.

Credentials are automatically sanitized before storage:

```
Input:  "Set api_key to sk-abc123def456"
Stored: "Set api_key to [REDACTED]"
```

### Securing a non-localhost deployment

The server binds `0.0.0.0` (required for Claude Code's port-mapped network) and is
**unauthenticated by default** — fine on a trusted machine. If you expose it on an
untrusted network, either bind loopback (`HOST=127.0.0.1`) or enable bearer auth:

```bash
export MEMENTO_API_TOKEN=$(openssl rand -hex 32)   # on the server
```

When set, every request except `/health` requires the token. Point clients at it:

```bash
# Claude Code
claude mcp add --transport http --url http://localhost:8000 \
  --header "Authorization: Bearer $MEMENTO_API_TOKEN" memory
# Cockpit: ui/.env.local
echo "NEXT_PUBLIC_MEMENTO_API_TOKEN=$MEMENTO_API_TOKEN" >> ui/.env.local
```

---

## Benchmark

Tested on [LongMemEval](https://github.com/xiaowu0162/LongMemEval) (500 questions, 6 question types). Reproducible — runner in [`benchmarks/`](benchmarks/).

`main` ships with **dense-only** retrieval (96.6% R@5 — matches MemPalace raw). Hybrid BM25 + dense retrieval and the +graph variant live on the `feat/hybrid-search-bm25` branch and reproduce the higher scores in the table below.

| Mode | R@5 | Branch | What It Tests |
|------|-----|--------|---------------|
| Dense (semantic only) | 96.6% | `main` (default) | Same as MemPalace raw — identical score |
| Hybrid (BM25 + dense) | 97.6% | `feat/hybrid-search-bm25` | Beats all published zero-API scores |
| Hybrid + graph | 97.6% | `feat/hybrid-search-bm25` | Adds knowledge graph expansion |
| MemPalace (raw, ChromaDB) | 96.6% | (external) | Highest previously published zero-API score |

Hybrid search catches entity-specific queries that pure semantic search misses. No LLM required, no API calls, runs entirely local.

```bash
# Reproduce
bash benchmarks/download_data.sh
docker compose up -d
PYTHONPATH=src:. .venv/bin/python -m benchmarks.longmemeval_runner \
    benchmarks/data/longmemeval_s_cleaned.json --mode all
```

---

## How Search Works

Memories are converted to **embeddings** (vectors that capture meaning) for semantic search:

```
"Use PostgreSQL" -> [0.12, 0.45, 0.78, ...]  <- Numbers that represent meaning
```

When you ask "what database?", Claude searches by meaning, not keywords. The knowledge graph then expands results by following relationship edges to find structurally related memories.

**Embedding options** (see [docs/SETUP.md](docs/SETUP.md)):
| Provider | Runs on | Cost | Quality |
|----------|---------|------|---------|
| `sentence-transformers` | Your computer | Free | Good (default) |
| `ollama` | Your computer | Free | Better |
| `gemini` | Google Cloud | Free tier | Best |

---

## Troubleshooting

**"Connection refused"** - Make sure Docker is running: `docker compose ps`

**"Cockpit UI not loading"** - Backend transport must be HTTP and the cockpit must be running:
```bash
docker compose exec mcp env | rg 'MCP_TRANSPORT|HOST'   # backend
cd ui && npm run dev -- -p 3333                          # cockpit
```

**"Claude forgets"** - Install the memory plugin (skills + hook) or add to `~/.claude/CLAUDE.md`:
```
At session start, call get_cached_context() to restore memory.
```

**Memories not found** - Rebuild the knowledge graph:
```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

**Graph shows 0 edges** - Run rebuild after first install or upgrade:
```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

**Restart everything:** `docker compose down && docker compose up -d`

---

<details>
<summary><b>How It Works</b></summary>

### The Flow

```
You say something important
        |
Claude saves it -> YAML file + Qdrant vector + Knowledge Graph node
        |
Auto-linker finds related memories -> Creates typed edges
        |
Later: Claude recalls by meaning + follows graph relationships
```

### Example

```
You: "Let's use PostgreSQL for JSON support"
AI:  saves to memory, creates embedding, auto-links to related memories

[3 days later]

You: "What database did we choose?"
AI:  vector search finds the memory
     graph expansion surfaces the related requirement and learnings
     "We chose PostgreSQL for its JSON support"
```

### Memory Types

| Type | Example | AI Behavior | Importance |
|------|---------|-------------|------------|
| `requirement` | "Must use Python 3.11+" | **Must** follow | 1.0 |
| `decision` | "Chose PostgreSQL" | Reference, can revisit | 0.85 |
| `preference` | "Prefers Terraform" | Suggest, offer alternatives | 0.75 |
| `learning` | "JWT bug fix" | Apply to similar cases | 0.65 |
| `fact` | "Project uses AWS" | Background context | 0.55 |
| `note` | "General observation" | Low-priority context | 0.35 |

### MCP Tools

| Tool | Purpose |
|------|---------|
| `observe(summary)` | Auto-classify and save (accepts caller `cwd` for project scope) |
| `recall_memories(query)` | Graph-enhanced semantic search |
| `save_memory(content, type)` | Manual save with explicit type |
| `memory_detail(memory_id)` | Single memory + neighbors + scope |
| `memory_kb(project)` | Typed slices (decisions / requirements / preferences / learnings) |
| `memory_pressure(project)` | Pressure metrics + flagged candidates |
| `memory_pressure_snapshot()` | Detailed pressure snapshot |
| `prune_plan(project, limit)` | Build prune plan (apply via REST only) |
| `backfill_lifecycle(project, dry_run)` | Tier metadata backfill on existing memories |
| `resume_packet(project)` | Continuity resume |
| `handoff_summary(project)` | Continuity summary |
| `agent_startup(project)` | Unified startup payload |
| `memory_lifecycle()` | Behavioral classifier output |
| `get_cached_context(project)` | Flat context (prompt-cache optimized) |
| `get_hierarchical_context(project)` | Topic-grouped context tree |
| `skill_context()` | Extracted skills from memory clusters |
| `memory_stats()` | Health + graph metrics |
| `consolidate_memories()` | Detect duplicates and conflicts |
| `proactive_context_summary()` | Top signals ranked by importance x recency |
| `rebuild_knowledge_graph()` | Rebuild graph from all existing memories |

### REST API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/memory/save` | POST | Save a memory |
| `/api/memory/recall` | POST | Graph-enhanced search |
| `/api/memory/observe` | POST | Auto-classify and save (accepts `cwd` for scope) |
| `/api/memory/stats` | GET | Statistics + graph metrics |
| `/api/memory/projects` | GET | List of projects + memory counts |
| `/api/memory/context` | GET | Flat project context |
| `/api/memory/context/hierarchy` | GET | Topic-grouped (`?days=N` for date filter) |
| `/api/memory/context/smart` | GET | Token-capped smart context (`?limit=&max_tokens=`) |
| `/api/memory/context/proactive` | GET | Top signals + conflict detection |
| `/api/memory/context/skills` | GET | Inferred skill context from memory clusters |
| `/api/memory/context/startup` | GET | Unified agent startup payload |
| `/api/memory/detail/{id}` | GET | Full memory + neighbors + scope |
| `/api/memory/kb` | GET | Typed slices |
| `/api/memory/pressure` | GET | Pressure metrics + flagged candidates |
| `/api/memory/resume` | GET | Resume packet for continuity |
| `/api/memory/prune/plan` | POST | Build prune plan (plan-id, 15-min TTL, 200-deletion cap) |
| `/api/memory/prune/apply` | POST | Apply plan with typed-id confirmation (REST-only) |
| `/api/memory/lifecycle/backfill` | POST | Backfill tier metadata (dry-run + execute) |
| `/api/memory/{id}` | DELETE | Delete a single memory |
| `/api/memory/cleanup` | POST | Batch cleanup (prune superseded, age-based) |
| `/api/memory/graph` | GET | Graph visualization data |
| `/api/memory/graph/rebuild` | POST | Rebuild knowledge graph |
| `/api/memory/consolidate` | GET | Detect superseded/conflicting pairs |
| `/api/memory/recall/quick` | GET | Fast high-threshold recall for per-prompt injection |
| `/api/memory/compact` | POST | LLM-summarize old memories (dry-run by default) |

</details>

---

<details>
<summary><b>Cost Savings</b></summary>

### Token Savings
- ~80% reduction in repetitive context

### Prompt Cache Savings
`get_cached_context()` returns identical content per turn -> 90% discount after turn 1

At high usage: **~$54/month savings** per 10k cached tokens

</details>

---

<details>
<summary><b>For Developers</b></summary>

### Local Development

```bash
pip install -e ".[dev]"
docker compose up -d qdrant
cd src && python -m server
```

### Tests

Tests run in an isolated environment and **never affect your production data**.

```bash
# Run all tests (fast, local)
uv run --extra dev pytest -v

# Run all tests (isolated Docker)
docker compose --profile test run --rm test

# Run specific test file
docker compose --profile test run --rm test pytest tests/test_memory.py -v

# Cleanup
docker compose --profile test down
```

**What happens:**
- `qdrant-test` starts on port 6334 with ephemeral tmpfs storage
- Tests use `/tmp/test_memory` for YAML files (inside container)
- Production data at `~/.claude/memory/` and `~/.claude/qdrant/` stays untouched
- Everything auto-deletes when tests finish

### Project Structure

```
src/
├── server.py               # MCP server + REST API endpoints
├── core/                   # Embedder, VectorStore, Telemetry, utils
│   └── utils.py            # stable_hash_id() for string->int64 hashing
├── memory/
│   ├── manager.py          # MemoryManager (save, recall, get_stats)
│   ├── knowledge_graph.py  # KnowledgeGraph (networkx DiGraph, persistence)
│   ├── linker.py           # Auto-linking: classify relations on save
│   ├── graph.py            # Visualization graph builder
│   ├── cache_context.py    # Stable cacheable context + hierarchical variant
│   ├── topics.py           # Topic auto-classification (agglomerative clustering)
│   └── skills.py           # Skill extraction from memory clusters
├── crawler/                # Documentation crawler (Scrapy)
├── indexer/                # Document chunker + Qdrant indexer
└── tools/                  # MCP tool definitions
```

### Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical design, knowledge graph internals |
| [docs/SETUP.md](docs/SETUP.md) | Setup, embedding providers, migration |
| [docs/TUNING.md](docs/TUNING.md) | Customize what Claude remembers |
| [docs/MEMORY_PLUGIN.md](docs/MEMORY_PLUGIN.md) | Memory Plugin skills and hooks |
| [docs/CLAUDE_MEMORY_SETTINGS.md](docs/CLAUDE_MEMORY_SETTINGS.md) | Claude-specific policy and tuning knobs |

</details>

---

## Requirements

- Docker (or Python 3.11+)
- ~500MB disk (embedding model downloads on first use)
- macOS, Linux, or Windows (WSL)

---

## License

MIT
