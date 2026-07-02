# Migration Guide — v1.5.x → v1.6.0 (Hardening)

**No breaking changes. No migration steps required** — upgrade in place.

v1.6.0 is a hardening release: input validation, correctness fixes, retrieval
performance, and CI. Behavior is backward-compatible; the server still binds
`0.0.0.0` by default (required for Claude Code).

### Highlights

- **Security:** every REST route validates `project` (blocks path traversal),
  `type` (enum), and numeric params (bounded) → `400` instead of `500` or silent
  acceptance. `HOST` defaults to `0.0.0.0`; set `HOST=127.0.0.1` on untrusted
  networks (a no-auth warning logs on non-loopback bind).
- **Correctness (silent failures fixed):** `cleanup()` now prunes the nested
  `<project>/<date>.yaml` layout (was a no-op); `clear_project()` clears YAML +
  graph + vectors (was vectors-only); hybrid search honors `score_threshold`.
- **Performance:** graph-neighbor expansion in recall is one batched fetch (was
  N+1); `memory_id` is indexed; recall no longer writes the graph to disk per query.
- **API:** `/kb`, `/pressure`, `/projects`, `/graph` now return a `truncated`
  flag; the duplicate `/api/memory/context/resume` route was removed (use
  `/api/memory/resume`).
- **Ops:** GitHub Actions CI (lint, format, tests, integration vs Qdrant, UI),
  `make backup`, importance-decay now runs during graph rebuild.

### Optional

- If you relied on `/api/memory/context/resume`, switch to `/api/memory/resume`
  (identical payload).

---

# Migration Guide — v1.4.0 → v1.5.0 (Brain Observatory cockpit)

This release replaces the legacy embedded HTML dashboard at `:8000/dashboard` with a standalone Next.js cockpit at `:3333`, adds new REST endpoints + MCP tools for memory hygiene and continuity, and tightens scope resolution on `/api/memory/observe`.

> **Moving memories between machines or from an older install on another machine?** See [`docs/DATA_TRANSFER.md`](DATA_TRANSFER.md) for the Qdrant-snapshot and YAML-reingestion paths.

## Breaking changes

### `/dashboard` route removed

The 409-line embedded HTML dashboard at `http://localhost:8000/dashboard` is gone. The route returns 404. Use the cockpit instead.

If you have bookmarks, scripts, or hooks pointing at `:8000/dashboard`, update them to `http://localhost:3333/brain`.

## The cockpit

Next.js 15 + React 19 + Tailwind v4. Runs as a separate process from the backend (port 3333). Four surfaces:

| Path | Purpose |
|------|---------|
| `/brain` | Force-directed memory graph. Tier + type encoding, link sparsifier, project scope dropdown, hover details. |
| `/kb` | Typed knowledge columns: decisions, requirements, preferences, learnings. Bounded scroll per column. |
| `/continuity` | Resume packet with important + recent + next steps + conflicts. |
| `/hygiene` | Pressure gauges, prune builder + review + apply gate, lifecycle backfill runner. |

### Run the cockpit

```bash
cd ui
npm install
npm run dev -- -p 3333
# open http://localhost:3333/brain
```

For production:

```bash
cd ui
npm run build
npm run start -- -p 3333
```

The backend at `:8000` must be running first (`docker compose up -d` for Qdrant, then `MCP_TRANSPORT=streamable-http uv run python -m server`).

### Project scope

The cockpit reads `/api/memory/projects` and offers a scope dropdown. The default is `all memories` (empty filter — cross-project view). Pick a specific project to scope all surfaces to that project's memories.

## New REST endpoints

These are additive — existing endpoints unchanged. The cockpit consumes them; you can use them directly via curl too.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/memory/projects` | GET | List of projects + memory counts |
| `/api/memory/detail/{id}` | GET | Full memory + neighbors + scope context |
| `/api/memory/kb` | GET | Typed semantic slices (decisions/requirements/preferences/learnings) |
| `/api/memory/pressure` | GET | Pressure metrics (load_score, capacity, flagged) + candidate snapshot |
| `/api/memory/prune/plan` | POST | Build a prune plan with plan-id (15-min TTL, 200-deletion cap) |
| `/api/memory/prune/apply` | POST | Apply a plan with `confirm_plan_id` gate (REST-only — no MCP surface) |
| `/api/memory/lifecycle/backfill` | POST | Backfill tier/lifecycle metadata on existing memories (dry-run + execute) |
| `/api/memory/resume` | GET | Resume packet for session continuity |

## New MCP tools

REST endpoints above are mirrored as MCP tools (with one exception):

- `memory_detail(memory_id)` → `/api/memory/detail/{id}`
- `memory_kb(project=None, max_per_type=10)` → `/api/memory/kb`
- `memory_pressure(project=None)` → `/api/memory/pressure`
- `memory_pressure_snapshot()` → richer snapshot
- `prune_plan(project=None, limit=20)` → `/api/memory/prune/plan`
- `backfill_lifecycle(project=None, dry_run=True)` → `/api/memory/lifecycle/backfill`
- `resume_packet(project=None)` → `/api/memory/resume`
- `handoff_summary(project=None)` → continuity summary
- `agent_startup(project=None)` → unified startup payload (combines stats, recent, important, conflicts)
- `memory_lifecycle()` → behavioral classifier output

**`prune_apply` is REST-only on purpose.** It mutates state and the typed plan-id confirmation flow needs the cockpit's "type the plan id to confirm" gate to be safe. Don't expose destructive bulk delete to autonomous agents.

## Behavioral changes

### Scope resolution on `/api/memory/observe`

Previously the backend resolved memory scope from its own cwd. So every observation from every Claude Code session landed under `project: rekall-mcp`.

Now the endpoint accepts `cwd` and `project` in the request body. Hooks (e.g. Stop hook calling `/api/memory/observe`) should forward `$CLAUDE_PROJECT_DIR` or `$PWD`. The MCP `observe()` tool already does this implicitly.

If you wrote a script that POSTs to `/api/memory/observe`, you can opt in by passing `cwd` (recommended) or `project`. Old payloads without those fields still work — they just resolve to whatever the backend's cwd happens to be.

### YAML storage layout

The default `MEMORY_STORAGE_PATH` is unchanged. **If you set it explicitly to a directory, the manager now writes nested per-project files there:**

```
<storage>/<project>/<YYYY-MM-DD>.yaml
```

Old flat layout (`<storage>/<YYYY-MM-DD>.yaml`) is still readable on the recall side — but new saves create the nested layout. If you have existing flat YAMLs and want to consolidate, run a one-time migration with `manager.backfill_lifecycle()` after symlinking or moving files into project subdirs.

### Behavioral tier lifecycle

Memories now classify into one of four tiers — `working`, `episodic`, `semantic`, `identity` — with reinforcement-on-dedupe. Recall ranking adds a tier component:

```
0.40·vector + 0.20·importance + 0.10·recency + 0.15·graph_proximity + 0.15·tier_norm
```

To backfill tiers on pre-1.5 memories:

```bash
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
    -H "Content-Type: application/json" \
    -d '{"dry_run": true}'
# review the dry-run output, then:
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
    -H "Content-Type: application/json" \
    -d '{"dry_run": false}'
```

Or use the cockpit Hygiene surface's BackfillRunner card.

### Safe prune contract

The plan/apply pattern replaces ad-hoc deletion. Build a plan, review the candidates and reasons, then apply only with the matching `plan_id` (typed confirmation in the cockpit, or programmatic via REST). Plans expire after 15 minutes. Identity-tier memories are exempt from prune. Reinforced memories under 7 days old are protected.

### RRF hybrid search filter fix

If you're on the `feat/hybrid-search-bm25` branch (this main release ships dense-only), `vector_store.py` previously dropped `query_filter` from the outer `query_points` call at the RRF fusion level. Date / project / agent filters silently leaked out-of-window memories into hybrid results. Fixed in this release.

## Compatibility

- Existing memories preserved across the upgrade. No data migration required.
- Legacy `.claude/hooks.json` (project-local kebab-case format) was removed from the repo. If you had your own version, port it to `.claude/settings.json` with the `hooks` key and PascalCase event names (`UserPromptSubmit`, etc.).
- Existing MCP tool names unchanged — only additions.

## Rollback

```bash
git checkout v1.4.0
docker compose down && docker compose up -d
# the cockpit is additive — pre-1.5 backends ignore the ui/ directory
```

Memory data on disk works with both versions. If you want to rebuild the knowledge graph after rollback:

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```
