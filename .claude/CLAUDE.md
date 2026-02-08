# Memento MCP - Project Context

## What This Is

Memento MCP is a persistent memory system for AI assistants. It gives Claude the ability to remember context across sessions using:
- Local YAML files (`~/.claude/memory/`) for human-editable storage
- Qdrant vector database for semantic search
- Sentence-transformers embeddings (local, free, ~384 dimensions)

## Running the Server

```bash
cd /Users/dev-box/Repos/memento-mcp
docker compose up -d
```

Verify:
```bash
curl http://localhost:8000/health
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/memory/save` | POST | Save a memory |
| `/api/memory/recall` | POST | Search memories |
| `/api/memory/stats` | GET | Get statistics |
| `/api/memory/context` | GET | Get project context |
| `/api/memory/observe` | POST | Auto-classify and save |

## Project Structure

```
src/
├── server.py           # MCP server with REST API endpoints
├── core/               # Embedder, VectorStore, Telemetry, utils
│   └── utils.py        # stable_hash_id() — single source for string→int64 hashing
├── memory/manager.py   # MemoryManager (save, recall, get_stats)
├── crawler/            # Documentation crawler (Scrapy)
├── indexer/            # Document chunker + Qdrant indexer
└── tools/              # MCP tool definitions
```

## Memory System

Memory restoration is automatic via `.claude/hooks.json`. To enable, create:

```json
{
  "user-prompt-submit": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "prompt",
          "prompt": "If you haven't called get_cached_context() yet this session, call it NOW silently before responding. Do NOT mention what you remembered - just use the context."
        }
      ]
    }
  ]
}
```

This fires on every message (new session, resume, or after context compaction).

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
# Run all tests (isolated environment)
docker compose --profile test run --rm test

# Run specific test file
docker compose --profile test run --rm test pytest tests/test_memory.py -v

# Cleanup test containers
docker compose --profile test down
```

**What happens when you run tests:**
1. `qdrant-test` container starts on port 6334 with tmpfs (in-memory) storage
2. Tests connect to `qdrant-test` instead of production Qdrant (port 6333)
3. Test memories are written to `/tmp/test_memory` inside container (ephemeral)
4. When tests finish, `docker compose down` deletes everything
5. Your production data at `~/.claude/memory/` and `~/.claude/qdrant/` is untouched

**Architecture:**
- Production Qdrant: `localhost:6333` → `~/.claude/qdrant` (persistent)
- Production YAML: `~/.claude/memory/*.yaml` (persistent)
- Test Qdrant: `localhost:6334` → tmpfs (deleted on stop)
- Test YAML: `/tmp/test_memory` inside container (deleted on stop)

## Recent Work

- TDD hardening: 4 bug fixes, 6 performance improvements, 6 dead code removals, 3 DRY fixes
- `stable_hash_id()` in `core/utils.py` — single source for string→int64 hashing
- Atomic YAML writes (tempfile + os.replace), sanitizer false-positive fix
- REST API singleton, CLI bug fixes (type= kwarg, save_memory→save)
- Embedding LRU cache (512 entries), numpy cosine similarity, centroid classification
- Removed dead code: `save_memory()` alias, `sanitize()`, `qdrant` property, `PROVIDER_COMPARISON`, `Embedder.model`, `ToolDefinition.parameters`
- All tests passing (152 passed, 7 skipped)
