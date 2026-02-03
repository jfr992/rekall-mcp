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
├── core/               # Embedder, VectorStore, Telemetry
├── memory/manager.py   # MemoryManager (save, recall, get_stats)
├── crawler/            # Documentation crawler (Scrapy)
├── indexer/            # Document chunker + Qdrant indexer
└── tools/              # MCP tool definitions
```

## Key Files

- `server.py:179` - Health check endpoint
- `server.py:203` - REST API endpoints for memory
- `memory/manager.py:179` - save() method
- `memory/manager.py:288` - recall() method
- `memory/manager.py:531` - get_stats() method

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

## Recent Work

- Added REST API endpoints for memory tools
- Added `/health` endpoint using `@mcp.custom_route()`
- Fixed Docker networking (QDRANT_URL env var)
- Ported crawler/indexer from spectro-mcp
- All tests passing (129 passed, 6 skipped)
