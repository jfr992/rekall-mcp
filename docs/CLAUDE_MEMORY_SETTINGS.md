# Claude Memory Settings (for MCP/Claude tuning)

Use this file as the single source of truth for how Claude should use memory.
You can copy the policy blocks into `~/.claude/CLAUDE.md` and adjust without code changes.

## 1) Recommended CLAUDE.md block

```markdown
## Memory Policy

### Session start
- Always call `get_cached_context(project)` once per project at session start.
- If this is a new project or ambiguous context, pass explicit `project`.

### Save policy (conservative default)
- Call `observe(summary)` for:
  - architecture/tech decisions
  - bug fixes + root cause
  - user preferences
  - constraints or requirements
- Do NOT call `observe` for:
  - routine command results
  - temporary exploratory thoughts
  - partial or incorrect attempts

### Recall policy
- Use `recall_memories(query, limit=5)` for targeted questions.
- If results are sparse, retry with `limit=8..12`.
- Always pass `project` when context should stay per-project.

### Failsafe
- If memory seems stale, call `memory_stats()` and `curl http://localhost:8000/api/memory/recall` with explicit limits.
```

## 2) Runtime knobs available today

### Docker / server controls

- `MCP_TRANSPORT` controls protocol (`streamable-http` required for dashboard + browser API access).
- `HOST`, `PORT` control listening address.
- `MEMORY_STORAGE_PATH` is where YAML memory files are persisted.
- `QDRANT_URL` controls vector DB endpoint.
- `EMBEDDING_PROVIDER` sets embedding backend (`sentence-transformers`, `ollama`, `gemini`).
- `LOG_LEVEL` for diagnostics.
- `OLLAMA_URL`, `EMBEDDING_API_KEY` as provider-specific settings.

Current compose defaults:
- service: `memento-mcp` on port `8000`
- transport: `streamable-http`
- project storage: `/data/memory` in container (`~/.claude/memory` on host)
- dashboard: `http://localhost:8000/dashboard`

### API defaults to remember

- `GET /api/memory/context?project=...`  
  - if no `project`, defaults to `general`
- `POST /api/memory/recall` body defaults:
  - `limit`: `5`
  - no score threshold exposed in API
- `GET /api/memory/graph` supports:
  - `limit` (default `120`, min `1`)
  - `neighbor_count` (default `5`, min `1`)
  - `min_similarity` (default `0.35`)
  - `project`, `type`, `days` filters

### Dashboard controls (query surface from UI)
- `project` text field
- `type` dropdown (`note`, `fact`, `preference`, `decision`, `learning`, `session`, `requirement`)
- `limit`, `neighbors`, `min score`, `days` presets

## 3) Known hard constraints (code-level)

- Project auto-detection in tool calls uses current working directory name.
- `/api/memory/context` has no `limit` query currently; it returns manager default (5) context items.
- `MemoryManager.recall()` uses fixed similarity threshold `0.45`.
- No dedupe guard exists for `save/observe`; repeated saves can create duplicates.
- `get_project_context()` requires valid project; `general` is a catch-all when unset.

## 4) Claude-safe adjustment checklist

When behavior drifts:

1. Verify transport/UI: `curl http://localhost:8000/health`, then `curl http://localhost:8000/dashboard`.
2. Confirm container and env: `docker compose ps` and `docker compose exec mcp env | rg MCP_TRANSPORT|HOST|QDRANT_URL`.
3. Narrow scope by adding explicit `project` to all recall/context calls.
4. Reduce noise by tightening `observe` triggers in CLAUDE.md policy.
5. Use dashboard filters to validate clustering (`/api/memory/graph?project=...`).
6. If needed, perform controlled cleanup:
   - inspect `~/.claude/memory/*.yaml`
   - remove stale project files
   - restart: `docker compose restart mcp`
