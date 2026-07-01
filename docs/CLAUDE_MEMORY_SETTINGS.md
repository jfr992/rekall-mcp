# Claude Memory Settings (for MCP/Claude tuning)

Use this file as the single source of truth for how Claude should use memory.
You can copy the policy blocks into `~/.claude/CLAUDE.md` and adjust without code changes.

## 1) Recommended CLAUDE.md block

```markdown
## Memory Policy

### Session start
- Always call `get_cached_context(project)` once per project at session start.
- If this is a new project or ambiguous context, pass explicit `project`.
- For richer context, use `get_hierarchical_context(project)` — returns topic-grouped tree with relationships.

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
- Every save auto-links to related memories in the knowledge graph.

### Recall policy
- Use `recall_memories(query, limit=5)` for targeted questions.
- Recall is graph-enhanced: results include 1-hop neighbors from the knowledge graph.
- Scoring: 50% vector similarity, 20% importance, 15% recency, 15% graph proximity.
- If results are sparse, retry with `limit=8..12`.
- Always pass `project` when context should stay per-project.

### Knowledge graph maintenance
- If graph stats show 0 edges, run `rebuild_knowledge_graph()`.
- Use `consolidate_memories()` to find duplicates/conflicts.
- Use `proactive_context_summary()` for top signals ranked by importance × recency.

### Failsafe
- If memory seems stale, call `memory_stats()` and check graph node/edge counts.
- Cockpit UI at `http://localhost:3333/brain` for visual graph exploration (ships as a container via `docker compose up -d`).
```

## 2) Runtime knobs available today

### Docker / server controls

- `MCP_TRANSPORT` controls protocol (`streamable-http` required for browser API access from the cockpit).
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
- cockpit: `http://localhost:3333/brain` (Next.js, separate from backend)

### API defaults to remember

- `GET /api/memory/context?project=...`
  - if no `project`, defaults to `general`
- `GET /api/memory/context/hierarchy?max_topics=8&similarity_threshold=0.72`
  - topic-grouped hierarchical context
- `POST /api/memory/recall` body defaults:
  - `limit`: `5`
  - Graph-enhanced: seeds expanded via 1-hop traversal, re-ranked by composite score
  - Score threshold: `0.45` (vector phase), `0.0` for graph-expanded neighbors
- `POST /api/memory/graph/rebuild`:
  - Rebuilds entire knowledge graph from all Qdrant memories
  - Returns: `{status, nodes, edges, duration_ms}`
- `GET /api/memory/graph` supports:
  - `limit` (default `120`, min `1`)
  - `neighbor_count` (default `5`, min `1`)
  - `min_similarity` (default `0.35`)
  - `project`, `type`, `days` filters
  - When knowledge graph has edges, uses real typed edges instead of cosine similarity
- `GET /api/memory/consolidate?limit=240&project=...`
  - Returns superseded and contradicting memory pairs
- `GET /api/memory/context/proactive?limit=120&project=...`
  - Top memories ranked by importance × recency, plus conflict detection

### Dashboard controls (query surface from UI)
- `project` text field
- `type` dropdown (`note`, `fact`, `preference`, `decision`, `learning`, `session`, `requirement`)
- `limit`, `neighbors`, `min score`, `days` presets
- Edge labels show relation types when knowledge graph is active

## 3) Knowledge graph internals

### Storage
- File: `~/.claude/memory/_graph.json` (atomic writes via tempfile + os.replace)
- Backed by networkx DiGraph in memory
- Edges: typed (`related_to`, `led_to`, `depends_on`, `contradicts`, `supersedes`, `part_of`)
- Nodes: memory_id with importance score, access count, last accessed date

### Auto-linking rules (on every save)
1. **SUPERSEDES**: similarity > 0.9 + same type → new replaces old (old importance halved)
2. **CONTRADICTS**: negation patterns detected in content
3. **LED_TO**: new learning + existing decision → causation edge
4. **DEPENDS_ON**: new decision + existing requirement → dependency edge
5. **RELATED_TO**: similarity > 0.5 + same project → default edge

### Importance scoring
- Base weight by type: requirement (1.0) → session (0.25)
- Temporal decay: `importance *= 0.98^(days_idle - 7)` after 7 days of non-access
- Access tracking: `record_access()` called on every recall hit

### Recall pipeline
1. **SEED**: vector search → top limit × 2 results
2. **EXPAND**: 1-hop graph neighbors of seeds
3. **RANK**: `vector(0.50) + importance(0.20) + recency(0.15) + proximity(0.15)`

## 4) Known hard constraints (code-level)

- Project auto-detection in tool calls uses current working directory name.
- `/api/memory/context` returns manager default (50) context items, no `limit` param.
- `MemoryManager.recall()` uses fixed similarity threshold `0.45` for vector phase.
- No dedupe guard on `save/observe`; repeated saves create duplicates (use `consolidate` to find them).
- `get_project_context()` requires valid project; `general` is catch-all when unset.
- Knowledge graph `_graph.json` can grow large with many memories; `rebuild()` takes ~60s for ~1300 memories.

## 5) Claude-safe adjustment checklist

When behavior drifts:

1. Verify backend: `curl http://localhost:8000/health`. For the cockpit, `curl http://localhost:3333/brain`.
2. Confirm container and env: `docker compose ps` and `docker compose exec mcp env | rg MCP_TRANSPORT|HOST|QDRANT_URL`.
3. Check knowledge graph: `curl http://localhost:8000/api/memory/stats` — verify node/edge counts.
4. If graph has 0 edges: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`.
5. Narrow scope by adding explicit `project` to all recall/context calls.
6. Reduce noise by tightening `observe` triggers in CLAUDE.md policy.
7. Use cockpit `/brain` scope filter to validate clustering (`/api/memory/graph?project=...`).
8. Check for drift: `curl http://localhost:8000/api/memory/consolidate` — review supersedes/contradicts.
9. If needed, perform controlled cleanup:
   - inspect `~/.claude/memory/*.yaml`
   - remove stale project files
   - rebuild graph: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`
   - restart: `docker compose restart mcp`

## 6) Skill reference

| Skill | Command | Purpose |
|-------|---------|---------|
| `/memory-restore` | Session start | Load hierarchical + flat context |
| `/memory-recall` | Search | Graph-enhanced semantic search |
| `/memory-observe` | Save | Auto-classify and save |
| `/memory-stats` | Diagnostics | Health + graph metrics |
| `/memory-rebuild` | Maintenance | Rebuild knowledge graph |
| `/memory-consolidate` | Cleanup | Find duplicates/conflicts |
| `/memory-skills` | Explore | Show extracted skills |
