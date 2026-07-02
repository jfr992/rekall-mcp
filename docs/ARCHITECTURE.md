# Architecture

How the system is built and why.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       YOUR APPLICATION                          │
│                  (Claude Code, Scripts, etc.)                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY MANAGER                             │
│                                                                 │
│   memory.save("decided on PostgreSQL", type="decision")         │
│   memory.recall("what did we decide?")                          │
│                                                                 │
└────────┬──────────────┬───────────────────┬─────────────────────┘
         │              │                   │
         ▼              ▼                   ▼
┌────────────────┐ ┌──────────────┐ ┌────────────────────────┐
│  CORE: EMBEDDER│ │ CORE: VECTOR │ │  KNOWLEDGE GRAPH       │
│                │ │ STORE        │ │                        │
│ Text → 384-dim │ │ Qdrant DB    │ │  networkx DiGraph      │
│ vector         │ │ Save, search │ │  Typed edges           │
│ all-MiniLM-L6  │ │ filter       │ │  Auto-linking on save  │
└────────────────┘ └──────┬───────┘ └───────────┬────────────┘
                          │                     │
                          ▼                     ▼
               ┌──────────────────┐  ┌──────────────────────┐
               │  YAML FILES      │  │  _graph.json         │
               │  ~/.claude/      │  │  ~/.claude/memory/   │
               │  memory/*.yaml   │  │  Atomic writes       │
               └──────────────────┘  └──────────────────────┘
```

---

## Core Principle: DRY

All shared functionality lives in `core/`:

```
src/core/
├── utils.py         # Shared utilities (stable_hash_id)
├── telemetry.py     # One place for metrics
├── embeddings.py    # One place for text→vector (with LRU cache)
└── vector_store.py  # One place for Qdrant operations
```

All tools use these. No duplication.

---

## Components

### 1. Memory Manager (`memory/manager.py`)

The main interface:

```python
from memory import MemoryManager

memory = MemoryManager()

# Save (auto-links to knowledge graph)
memory.save("User prefers diagrams", type="preference")

# Recall (graph-enhanced: seed → expand → rank)
results = memory.recall("how does user like explanations?")

# Project context
context = memory.get_project_context("my-app")
```

**Responsibilities:**
- Sanitize content (remove credentials)
- Save to file + vector store + knowledge graph node
- Auto-link new memories via `linker.auto_link()`
- Graph-enhanced recall (3-phase pipeline)
- Track metrics via telemetry

### 2. Knowledge Graph (`memory/knowledge_graph.py`)

Persistent directed graph of memory relationships.

```python
from memory.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph("~/.claude/memory/_graph.json")

# Nodes are memories
kg.add_node("mem_123", memory_type="decision")

# Edges are typed relationships
kg.add_edge("mem_123", "mem_456", "led_to", weight=0.8)

# Traversal
neighbors = kg.get_neighbors("mem_123", hops=1)
chain = kg.get_chain("mem_123", relation="led_to")

# Analysis
importance = kg.get_importance("mem_123")
stats = kg.stats()  # {"nodes": 133, "edges": 286, "relations": {...}}
```

**Storage:** `~/.claude/memory/_graph.json` (atomic writes via tempfile + os.replace)

**Backend:** networkx DiGraph in memory

**Relation types:**

| Relation | Meaning | Auto-detection rule |
|----------|---------|---------------------|
| `related_to` | Semantically similar (default) | similarity > 0.5, same project |
| `led_to` | Temporal causation | New learning + existing decision |
| `depends_on` | Structural dependency | New decision + existing requirement |
| `supersedes` | Newer replaces older | similarity > 0.9 + same type |
| `contradicts` | Opposing content | Asymmetric negation + overlap >= 2 + proximity |
| `part_of` | Belongs to topic cluster | Topic assignment |

**Importance scoring by type:**

| Type | Base Weight |
|------|-------------|
| `requirement` | 1.0 |
| `decision` | 0.85 |
| `preference` | 0.75 |
| `learning` | 0.65 |
| `fact` | 0.55 |
| `note` | 0.35 |
| `session` | 0.25 |

Temporal decay: `importance *= 0.98^(days_idle - 7)` after 7 days of non-access.

### 3. Auto-Linker (`memory/linker.py`)

Classifies relationships between memories on every save.

```python
from memory.linker import auto_link

result = auto_link(
    graph=kg, memory_id="new_learning",
    content="Connection pooling needs pgbouncer",
    memory_type="learning", project="api",
    embedder=emb, store=vs,
)
# result.edges_created = 3
# result.relations = {"led_to": 1, "related_to": 2}
```

**Rules applied in priority order (first match wins per candidate):**

1. **CONTRADICTS** - Requires all 4: similarity >= 0.6, exactly one text has negation (asymmetric), token overlap >= 2 non-stopwords, negation within 3 words of a shared concept
2. **SUPERSEDES** - similarity > 0.9 + same type (old importance halved)
3. **LED_TO** - New learning + candidate is decision
4. **DEPENDS_ON** - New decision + candidate is requirement
5. **RELATED_TO** - Default for similar memories

Both `save()` and `rebuild()` call the same `auto_link()` function (DRY).

### 4. Embedder (`core/embeddings.py`)

Converts text to vectors for semantic search.

**Model:** `all-MiniLM-L6-v2` (384 dimensions, ~80MB, runs on CPU, ~6ms per encoding)

LRU cache (512 entries) prevents redundant encodings.

### 5. Vector Store (`core/vector_store.py`)

Wrapper around Qdrant for vector operations. Supports save, search (with filters), scroll, delete.

**Filter note:** The `date` field is stored as a `YYYY-MM-DD` string. Qdrant's `Range` filter requires numeric values, so date/`days` filtering is applied post-retrieval in Python (lexicographic comparison of ISO date strings is correct). The `project` and `type` fields use exact-match filters in Qdrant as normal.

### 6. Topic Clustering (`memory/topics.py`)

Agglomerative clustering discovers topics from memory vectors. Topic labels are derived from the most frequent terms in each cluster. Falls back to lexical extraction when clustering fails.

### 7. Skill Extraction (`memory/skills.py`)

Extracts capabilities from memory clusters using term-frequency analysis. Each skill represents a learned capability backed by multiple related memories.

### 8. Telemetry (`core/telemetry.py`)

Tracks all operations with counts, latencies, percentiles. OTEL-compatible metrics dict.

---

## Data Flow

### Saving a Memory

```
1. User calls memory.save("Decided to use Python", type="decision")
                                    │
2. Sanitize: Remove credentials     │
   "api_key=abc123" → "[REDACTED]"  │
                                    │
3. Generate embedding               │
   "Decided to use Python" → [0.1, 0.3, ...]
                                    │
4. Save to YAML file (durability)   │
   ~/.claude/memory/<project>/2026-02-23.yaml │
                                    │
5. Save to Qdrant (searchability)   │
   Collection: agent_memory         │
                                    │
6. Add node to knowledge graph      │
   importance = 0.85 (decision)     │
                                    │
7. Auto-link to related memories    │
   Find candidates via Qdrant       │
   Classify: led_to, depends_on...  │
   Create typed edges               │
                                    │
8. Save graph (atomic write)        │
   ~/.claude/memory/_graph.json     │
                                    │
9. Record telemetry                 │
   memory.save: 1 call, 15ms       │
```

### Recalling Memories (Graph-Enhanced)

```
1. User calls memory.recall("what technology did we choose?")
                                    │
2. Phase 1: SEED                    │
   Generate query embedding         │
   Vector search → top limit×2      │
   candidates from Qdrant           │
                                    │
3. Phase 2: EXPAND                  │
   For each seed result:            │
     Get 1-hop graph neighbors      │
     Record access on node          │
   Fetch expanded memories          │
   from Qdrant                      │
                                    │
4. Phase 3: RANK                    │
   For each candidate:              │
     vector_score × 0.40            │
     + importance × 0.20            │
     + graph_proximity × 0.15      │
     + tier × 0.15                 │
     + recency × 0.10              │
   Sort by composite score          │
                                    │
5. Return top N results             │
   Includes: score, vector_score,   │
   content, type, project, date     │
```

Falls back to pure vector search when the knowledge graph has 0 edges.

---

## Storage

### Triple Storage Strategy

| Storage | Purpose | File |
|---------|---------|------|
| **YAML files** | Durability, backup, human-readable | `~/.claude/memory/<project>/*.yaml` |
| **Qdrant** | Fast semantic search | `~/.claude/qdrant/` (Docker volume) |
| **Knowledge graph** | Typed relationships, traversal | `~/.claude/memory/_graph.json` |

YAML files are the source of truth. Qdrant and the graph can be rebuilt from YAML at any time.

### File Structure

```
~/.claude/memory/
├── <project>/
│   ├── 2026-02-01.yaml  # Day's memories, per project
│   └── 2026-02-02.yaml
├── ...
└── _graph.json           # Knowledge graph (networkx export)
```

### Qdrant Collection

```
Collection: agent_memory
Vectors: 384 dimensions (cosine distance)
Indexes: date, project, type (for filtering)
```

---

## Security

### Credential Sanitization

Content passes through pattern-based sanitization before storage. Matches API keys, tokens, passwords, PEM keys, and other secrets. All matched content becomes `[REDACTED]`.

### Local-Only by Default

- Everything stored on your machine
- No cloud services required
- Qdrant runs locally in Docker

---

## Testing

```
tests/
├── test_knowledge_graph.py       # KnowledgeGraph persistence, traversal, analysis
├── test_auto_linking.py          # Auto-linking rules and classification
├── test_graph_enhanced_recall.py # Graph-enhanced recall pipeline
├── test_graph_rebuild.py         # Graph rebuild from Qdrant
├── test_topics.py                # Topic clustering
├── test_skills.py                # Skill extraction
├── test_cache_context.py         # Cacheable + hierarchical context
├── test_memory_graph.py          # Visualization graph builder
├── test_server_memory_graph.py   # Server endpoint tests
├── test_core.py                  # Telemetry, Embedder, VectorStore
├── test_memory.py                # MemoryManager
├── test_memory_cli.py            # CLI commands
├── test_performance.py           # Benchmarks
└── ...

245 passed, 9 skipped
```

All tests use mocks to avoid needing real Qdrant/model. Integration tests use isolated Docker containers.

---

## Observability

### Tracked Operations

| Operation | Description |
|-----------|-------------|
| `memory.save` | Saving a memory (includes auto-linking) |
| `memory.recall` | Graph-enhanced search |
| `memory.get_project_context` | Getting project context |
| `memory.get_stats` | Getting system stats |
| `embedder.encode` | Text to vector conversion |
| `vector_store.save` | Saving to Qdrant |
| `vector_store.search` | Searching Qdrant |
| `vector_store.scroll` | Listing from Qdrant |

Per-operation metrics: `count`, `errors`, `success_rate_pct`, `avg_ms`, `p50_ms`, `p95_ms`, `p99_ms`.

---

## Extension Points

### Adding a New Memory Type

```python
memory.save("Custom content", type="my_custom_type")
```

Types without a defined weight in `TYPE_WEIGHTS` default to 0.35 importance.

### Adding a New Relation Type

Add to `RELATION_TYPES` in `knowledge_graph.py` and add classification logic in `linker.py:_classify_relation()`.

### Custom Embedding Model

```python
embedder = Embedder(model="paraphrase-MiniLM-L6-v2")
```

After switching models, rebuild the index: `python -m memory.migrate`

---

## Memory OS (Backend Hardening — 2026-04-10)

### Behavioral tiering

Tiers are computed from behavioral signals, not a pure type→tier lookup. See
`src/memory/lifecycle.py:classify` and `LifecycleSignals`. Promotion is
deterministic; identity tier is sacred (only reachable via explicit
`save(tier="identity")`).

- `working` — recent scratch, low-confidence
- `episodic` — session/time-anchored events
- `semantic` — durable facts, decisions, high-salience requirements, reinforced notes
- `identity` — stable user/agent preferences (explicit only)

**Classification rules** (applied in order):
1. `explicit_tier="identity"` → `identity` (sacred, short-circuits)
2. `type ∈ {note, fact, learning}` AND `reinforcement_count ≥ 5` AND `age_days ≥ 7` → `semantic`
3. `type ∈ {decision, requirement}` AND `salience ≥ 0.6` → `semantic`
4. `contradicts_count ≥ 2` → demote one tier (floored at `working`)

**Recall tier weights**: `identity=1.0, semantic=0.66, episodic=0.33, working=0.0`
at `0.15` final weight. Old weights made tier a rounding error (max 0.015).

### Reinforcement loop

When `manager.save` hits the dedupe path, it calls
`intelligence.reinforce_and_reclassify` — a pure function that:
1. Increments `reinforcement_count`
2. Recomputes tier/durability via `classify()`
3. Returns a new dict (does not mutate the input)

The caller (`_reinforce_existing_memory`) persists via `store.update_payload`.
Identity tier is preserved through the reinforcement path.

### Safe pruning

Prune is a two-step plan/apply contract with a plan id gate, 15-minute TTL,
and a hard cap of 200 deletions per apply. See `src/memory/prune.py`.

**Safety rules enforced in `build_plan`:**
- Identity-tier memories are NEVER selected
- Memories without an explicit `salience` field are NEVER selected
  (prevents wiping hand-saved notes whose salience is unknown)
- Memories adjacent (1-hop) to an identity-tier memory are NEVER selected
  (neighborhood protection)
- Reinforced memories (`reinforcement_count > 0`) are NEVER selected
- Young memories (`age_days < 7`) are NEVER selected

**`apply_plan` requires:**
- A matching `confirm_plan_id` (not just any UUID)
- Non-expired plan (15-minute TTL)
- Hard-caps at 200 deletions; excess goes to `skipped`

**`prune_apply` is REST-only.** There is deliberately no matching MCP tool,
so agents cannot self-delete. Only the UI (or a human with `curl`) can
execute a prune.

### Trust boundaries

`src/memory/trust.py` loads `~/.claude/memory/trust.yaml` (override via
`REKALL_MEMORY_DIR`). If the file is missing or malformed, every detection
resolves to `personal`. No hardcoded client names.

Schema:
```yaml
boundaries:
  - name: my-client
    match:
      remote_contains: "gitlab.my-client.internal"
      name_contains: "client-repo-"   # list of strings also accepted
```

`ScopeDetector.detect()` is `lru_cache`d per cwd. Credentials in HTTPS
remote URLs are stripped via `_strip_creds` before being persisted in
memory payloads.

### New REST endpoints

All endpoints return structured JSON (plain dicts via `_ok`). MCP tool
parity exists for every endpoint EXCEPT `POST /api/memory/prune/apply`,
which is deliberately REST-only.

| Path | Method | Purpose | MCP tool |
|------|--------|---------|----------|
| `/api/memory/detail/{id}` | GET | Single memory + 1-hop neighbors | `memory_detail` |
| `/api/memory/kb` | GET | Typed slices (decisions, requirements, preferences, learnings) | `memory_kb` |
| `/api/memory/pressure` | GET | Structured pressure snapshot with `load_score`, `capacity`, `flagged` | `memory_pressure_snapshot` |
| `/api/memory/prune/plan` | POST | Build a dry prune plan | `prune_plan` |
| `/api/memory/prune/apply` | POST | Apply a plan (requires `{plan_id, confirm}`) | **none (REST-only)** |
| `/api/memory/lifecycle/backfill` | POST | One-shot backfill for existing memories | `backfill_lifecycle` |
| `/api/memory/resume` | GET | Bounded-scroll resume packet with `truncated` flag | `resume_packet` |

### Migration

Existing installations with memories saved before this branch need a one-shot
lifecycle backfill to populate `tier` / `durability` / `retention_days` on
legacy memories:

```bash
# Dry run first
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H 'content-type: application/json' \
  -d '{"dry_run": true}' | jq

# Then apply
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H 'content-type: application/json' \
  -d '{"dry_run": false}' | jq
```

The backfill is idempotent and safe to re-run.
