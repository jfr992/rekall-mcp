# Architecture

This document explains how the system is built and why.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         YOUR APPLICATION                         │
│                    (Claude Code, Scripts, etc.)                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MEMORY MANAGER                            │
│                                                                  │
│   memory.save("decision about architecture", type="decision")   │
│   memory.recall("what did we decide?")                          │
│                                                                  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│      CORE: EMBEDDER       │   │   CORE: VECTOR STORE      │
│                           │   │                           │
│  Text → 384-dim vector    │   │  Qdrant database          │
│  "architecture" → [0.1,   │   │  Save, search, filter     │
│   0.3, 0.2, ...]          │   │                           │
└───────────────────────────┘   └───────────────────────────┘
                                            │
                                            ▼
                                ┌───────────────────────────┐
                                │    LOCAL FILE STORAGE     │
                                │                           │
                                │  ~/.claude/memory/        │
                                │    2026-02-01.yaml        │
                                │    2026-02-02.yaml        │
                                └───────────────────────────┘
```

---

## Core Principle: DRY (Don't Repeat Yourself)

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

The main interface. Simple API:

```python
from memory import MemoryManager

memory = MemoryManager()

# Save
memory.save("User prefers diagrams", type="preference")

# Recall
results = memory.recall("how does user like explanations?")

# Project context
context = memory.get_project_context("my-app")
```

**Responsibilities:**
- Sanitize content (remove credentials)
- Save to both file and vector store
- Format search results
- Track metrics

### 2. Embedder (`core/embeddings.py`)

Converts text to vectors for semantic search.

```python
from core import Embedder

embedder = Embedder()
vector = embedder.encode("architecture decisions")
# Returns: [0.1, 0.3, 0.2, ...] (384 floats)
```

**Model:** `all-MiniLM-L6-v2`
- 384 dimensions
- ~80MB
- Runs on CPU
- ~6ms per encoding

### 3. Vector Store (`core/vector_store.py`)

Wrapper around Qdrant for vector operations.

```python
from core import VectorStore

store = VectorStore(collection="memories")

# Save
store.save(id="mem_001", vector=[...], payload={"type": "decision"})

# Search
results = store.search(vector=[...], filters={"type": "decision"})
```

**Why Qdrant?**
- Fast (sub-10ms searches)
- Runs locally (Docker)
- Open source
- Good Python SDK

### 4. Telemetry (`core/telemetry.py`)

Tracks all operations for observability.

```python
from core import Telemetry

telemetry = Telemetry.get()

# Automatic tracking
with telemetry.track("memory.save"):
    # ... operation ...

# Get metrics
metrics = telemetry.get_metrics()
# Returns OTEL-compatible dict with counts, latencies, percentiles
```

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
4. Save to file (durability)        │
   ~/.claude/memory/2026-02-01.yaml
                                    │
5. Save to Qdrant (searchability)   │
   Collection: agent_memory
                                    │
6. Record telemetry                 │
   memory.save: 1 call, 15ms
```

### Recalling Memories

```
1. User calls memory.recall("what technology did we choose?")
                                    │
2. Generate query embedding         │
   "what technology..." → [0.2, 0.1, ...]
                                    │
3. Search Qdrant (semantic)         │
   Find vectors similar to query
                                    │
4. Return results with scores       │
   [{"content": "Decided to use Python", "score": 0.85}]
                                    │
5. Record telemetry                 │
   memory.recall: 1 call, 12ms
```

---

## Storage

### Dual Storage Strategy

| Storage | Purpose | Trade-off |
|---------|---------|-----------|
| **Files** | Durability, backup, human-readable | No semantic search |
| **Qdrant** | Fast semantic search | Requires running server |

If Qdrant is unavailable, file storage still works.

### File Structure

```
~/.claude/memory/
├── 2026-02-01.yaml
├── 2026-02-02.yaml
└── ...
```

Each file is a YAML list of memories for that date:
```yaml
- id: 2026-02-01_decision_a4044b26
  timestamp: '2026-02-01T10:30:00'
  type: decision
  project: my-app
  content: Chose PostgreSQL for JSON support
- id: 2026-02-01_learning_b3921c45
  timestamp: '2026-02-01T14:15:32'
  type: learning
  project: my-app
  content: JWT validation fails with trailing slash in issuer URL
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

Before any content is stored, it passes through sanitization:

```python
PATTERNS = [
    r'api_key=...',      # Generic API keys
    r'ghp_...',          # GitHub tokens
    r'sk-...',           # OpenAI keys
    r'password=...',     # Passwords
    r'-----BEGIN...',    # PEM keys
    # ... 12 patterns total
]
```

**All matched content → `[REDACTED]`**

### Local-Only by Default

- Everything stored on your machine
- No cloud services required
- Qdrant runs locally in Docker

---

## Performance

### Benchmarks (from real tests)

| Operation | Avg Latency | Throughput |
|-----------|-------------|------------|
| memory.save | 13ms | 75/sec |
| memory.recall | 13ms | 77/sec |
| memory.context | 4ms | 253/sec |
| embedder.encode | 6ms | 135/sec |
| vector_store.search | 4ms | 250/sec |

### Optimization Choices

1. **Lazy loading**: Model loads on first use, not at import
2. **Batch encoding**: 2.7x faster than single encoding
3. **Connection pooling**: Qdrant client reused
4. **Payload indexes**: Fast filtering by date/project/type

---

## Testing

```
tests/
├── test_core.py         # Telemetry, Embedder, VectorStore
├── test_memory.py       # MemoryManager
└── test_memory_cli.py   # CLI commands

Coverage:
- core/telemetry.py: 95%
- core/embeddings.py: 85%
- core/vector_store.py: 80%
- memory/manager.py: 86%
- memory/cli.py: 98%
```

All tests use mocks to avoid needing real Qdrant/model.

---

## Observability

### Tracked Operations

| Operation | Description |
|-----------|-------------|
| `memory.save` | Saving a memory |
| `memory.recall` | Searching memories |
| `memory.get_project_context` | Getting project context |
| `memory.get_stats` | Getting system stats |
| `memory.clear_project` | Deleting project memories |
| `embedder.encode` | Text → vector conversion |
| `embedder.encode_batch` | Batch encoding |
| `embedder.load_model` | Model initialization |
| `vector_store.save` | Saving to Qdrant |
| `vector_store.search` | Searching Qdrant |
| `vector_store.scroll` | Listing from Qdrant |
| `vector_store.delete` | Deleting from Qdrant |
| `vector_store.connect` | Connecting to Qdrant |

### Per-Operation Metrics

Each operation records: `count`, `errors`, `success_rate_pct`, `avg_ms`, `p50_ms`, `p95_ms`, `p99_ms`.

Access via `Telemetry.get().get_metrics()` (OTEL-compatible dict) or `Telemetry.get().summary()` for a human-readable table.

---

## Extension Points

### Adding a New Tool Provider

```python
# tools/builtin/my_tool.py
from tools.base import BaseToolProvider, ToolDefinition

class MyToolProvider(BaseToolProvider):
    name = "my_tool"
    description = "What it does"

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="do_something",
                description="Does something useful",
                handler=self.do_something,
            ),
        ]

    async def do_something(self, arg: str) -> str:
        return f"Did something with {arg}"
```

Register in `tools/builtin/__init__.py` and enable in config:

```yaml
tools:
  my_tool:
    enabled: true
```

### Adding a New Memory Type

```python
memory.save("Custom content", type="my_custom_type")
```

### Custom Embedding Model

```python
embedder = Embedder(model="paraphrase-MiniLM-L6-v2")
```

### Custom Vector Store

```python
store = VectorStore(
    collection="my_collection",
    url="http://qdrant-server:6333",
    embedding_dim=768,  # Different model
)
```
