# Claude Memory Settings (for MCP/Claude tuning)

Use this file as the single source of truth for how Claude should use memory.
You can copy the policy blocks into `~/.claude/CLAUDE.md` and adjust without code changes.

## 1) Recommended CLAUDE.md block

```markdown
## Memory Policy

### Session start
- Prefer `agent_startup(project?, agent="claude-code")` once per project at session start.
- Read the project capsule before deciding what to recall; call `memory_doctor(project)` only when recall trust is in question.
- If the optional `SessionStart` capsule hook is installed, treat its injected context as familiarity only; still use targeted recall for the user's actual task.
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
- Every save auto-links to related memories in the knowledge graph.

### Recall policy
- Use `recall_memories(query, limit=5)` for targeted questions.
- Use `recall_across_projects(query, current_project)` when a lesson from another repo may apply.
- Use `reflex_recall(text, project)` before risky infrastructure, hook, Qdrant/memory, or deployment work.
- Recall is graph-enhanced: results include 1-hop neighbors from the knowledge graph.
- Scoring: 50% vector similarity, 20% importance, 15% recency, 15% graph proximity.
- If results are sparse, retry with `limit=8..12`.
- Always pass `project` when context should stay per-project.

### Knowledge graph maintenance
- If graph stats show 0 edges, run `rebuild_knowledge_graph()`.
- Use `consolidate_memories()` to find duplicates/conflicts.
- Use `proactive_context_summary()` for top signals ranked by importance × recency.

### Context hints + open loops
- Pass `task_hint` to `recall_memories` when you know what you're working on — a short noun phrase, 2+ words ("auth middleware refactor"). Matching memories surface first; single words are ignored server-side; omitting it changes nothing.
- Call `close_loop(memory_id, note?)` when a pending item is finished, blocked, or abandoned — it appends a RESOLVED stamp (history preserved) and the item drops out of the session-start Open Loops list.

### Failsafe
- If memory seems stale, call `memory_doctor(project)` first, then `memory_stats()` for counts.
- Cockpit UI at `http://localhost:3333/brain` for visual graph exploration (ships as a container via `docker compose up -d`).
```

## 2) Runtime knobs available today

### Docker / server controls

- `MCP_TRANSPORT` controls protocol (`streamable-http` required for browser API access from the cockpit).
- `HOST`, `PORT` control listening address.
- `MEMORY_STORAGE_PATH` is where YAML memory files are persisted.
- `QDRANT_URL` controls vector DB endpoint.
- `QDRANT_PATH` selects an embedded (local-path) Qdrant store instead — mutually exclusive with `QDRANT_URL`.
- `EMBEDDING_PROVIDER` sets embedding backend (`fastembed` default; `sentence-transformers` requires the `[torch]` extra; `ollama`, `gemini`).
- `LOG_LEVEL` for diagnostics.
- `OLLAMA_URL`, `GEMINI_API_KEY` as provider-specific settings.
- `REKALL_MARKER_DIR` — directory where the restore, observe, and reflex hooks write/read per-session marker files (default `/tmp`).
- `REKALL_REFLEX` — dedicated kill switch for `rekall-reflex.sh` (PreToolUse). Set to `0` to disable reflex recalls without touching autosave. Also gated by `REKALL_AUTOSAVE` (see below) — either variable at `0` disables it.

Current compose defaults:
- service: `rekall-mcp` on port `8000`
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
3. **RANK**: `vector(0.40) + importance(0.20) + proximity(0.15) + tier(0.15) + recency(0.10)`

### Lifecycle metric semantics

Read these as the agent-facing meaning — wrong interpretation leads to wrong pruning or recall decisions:

- **durability** — retention strength (0.0–1.0). `null` means the memory pre-dates lifecycle assignment or is identity-protected; treat as unknown, not as low retention. `0.0` is a valid computed value, not the same as absent.
- **salience** — the observation engine's save confidence at write time. `null` means the field was never written (legacy or hand-saved memory); treat as unknown, not as low confidence. The prune planner never selects memories with `null` salience.
- **reinforcement_count** — how many times a near-duplicate observation triggered the dedupe path and was merged into this memory rather than saved separately. Not a popularity score.

## 4) Known hard constraints (code-level)

- Project auto-detection in tool calls uses current working directory name.
- `/api/memory/context` returns manager default (50) context items, no `limit` param.
- `MemoryManager.recall()` uses fixed similarity threshold `0.45` for vector phase.
- Dedupe guard on `save/observe`: cosine ≥ 0.97 plus exact normalized string match reinforces the existing memory instead of duplicating. Near-duplicates below the threshold still accumulate — use `consolidate` to find them.
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
   - inspect `~/.claude/memory/<project>/*.yaml`
   - remove stale project files
   - rebuild graph: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`
   - restart: `docker compose restart mcp`

## 6) Freshness — conflict detection and stale-content suppression

Rekall detects conflicting memories of the same type at read time, not write time, so no data is lost:

- **On every save**: the auto-linker records `supersedes` or `contradicts` graph edges when a new memory is highly similar to an existing one of the same type.
- **On every recall**: the two top-N results are compared via graph edges and stored-vector cosine (θ ≥ 0.9). Conflicting pairs are annotated with `_outdated: True` on all but the newest member. This is ephemeral — nothing is written back.
- **In `recall_formatted` output**: entries render newest-first. Outdated entries are collapsed to a single stub line (`[outdated — replaced by the newer entry above]`) so the agent never acts on stale information. The imperative header `*…the newest is correct — ignore older values.*` appears whenever the same memory type repeats in the result set.
- **Check memory first** before writing new facts in the same domain: `recall_memories(query, limit=5)` surfaces any existing entries that might already be superseded.

## 7) Hooks: memory-prune.sh (gated daily superseded-prune)

`claude/hooks/memory-prune.sh` is a thin `SessionStart` hook that fires the `/api/memory/prune/superseded` endpoint at most **once per calendar day**. Install it alongside `rekall-restore.sh` and `rekall-observe.sh`.

**What it does:**
- Sends `{"confirm_date": "YYYY-MM-DD"}` to `/api/memory/prune/superseded`.
- The server evaluates safety gates (backup-first, ≤ 10 deletions per fire, ≤ 20 deletions per calendar day, confirm-date token must match today) before deleting anything.
- Prints a one-line summary only when memories are actually removed.
- Exits 0 and is silent on any error (curl timeout, server unreachable, empty result).

**Kill switch:** set `REKALL_AUTOSAVE=0` — the hook exits immediately without calling the server. `REKALL_AUTOSAVE` is the master switch for all shipped rekall hooks, including read-only ones (`rekall-reflex.sh` gates on it too, alongside its own `REKALL_REFLEX` switch) — despite the name, it is not save-specific.

**Server-side caps (hard limits in `src/memory/prune_superseded.py`):**
- `MAX_PER_FIRE = 10` — maximum deletions in one endpoint call.
- `MAX_PER_DAY = 20` — maximum deletions across all calls in a calendar day.
- A backup tarball is created before any deletion (writes to `~/backups/`).

**Marker file:** `$REKALL_MARKER_DIR/rekall-prune-YYYYMMDD` (default `/tmp`) prevents re-firing within the same day. Delete it to force a re-run.

## 8) Skill reference

| Skill | Command | Purpose |
|-------|---------|---------|
| `/memory-restore` | Session start | Load hierarchical + flat context |
| `/memory-recall` | Search | Graph-enhanced semantic search |
| `/memory-observe` | Save | Auto-classify and save |
| `/memory-stats` | Diagnostics | Health + graph metrics |
| `/memory-rebuild` | Maintenance | Rebuild knowledge graph |
| `/memory-consolidate` | Cleanup | Find duplicates/conflicts |
| `/memory-skills` | Explore | Show extracted skills |
