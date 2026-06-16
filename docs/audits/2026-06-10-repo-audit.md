# Memento MCP — Repository Audit & Improvement Plan

> Audited: 2026-06-10 · Version: v1.5.2 · Branch: main (bcb3101) · Analysis only, no code modified.

## Executive Summary

**Overall health: B-.** This is a genuinely well-crafted local-first memory system — strong test culture (54 test files, pre-commit-enforced pytest), production-grade Docker, structured telemetry, full Zod validation in the UI — undermined by a handful of sharp edges that contradict its own documented rules.

**Top 3 risks:**

1. The test suite connects to **production Qdrant on :6333 by default** — the exact thing `CLAUDE.md` forbids — and the pre-commit hook runs it on every commit.
2. The shipped startup script binds the server to `0.0.0.0` with **zero authentication** on destructive endpoints (delete, prune, cleanup), plus an unvalidated `project` parameter that can path-traverse out of the memory directory.
3. Silent-failure correctness bugs: `cleanup()` uses flat `glob` on a nested layout (does nothing), and `clear_project()` deletes from one of three stores, orphaning YAML and graph.

**Top 3 opportunities:** a CI workflow (currently none — everything rides on local pre-commit), fixing the per-request embedding-model instantiation and N+1 recall pattern (cheap, large latency wins), and executing the already-written config-merge plan to collapse the two overlapping config systems.

None of this requires architectural surgery; it's 2–3 days of focused fixes.

---

## Phase 1 — Repo Map

**Purpose:** Persistent memory for AI assistants (Claude Code/Codex) via MCP. Memories stored as YAML (durable) + Qdrant vectors (searchable) + a NetworkX knowledge graph (associative recall). Single-user, localhost-first. Maturity: Beta (v1.5.2, `pyproject.toml:11`), actively developed, real users (351 live memories).

**Stack:** Python 3.11 (FastMCP/Starlette/uvicorn, qdrant-client, sentence-transformers, networkx), Next.js 15 / React 19 cockpit (TanStack Query, Zod, Zustand, react-force-graph), Docker for Qdrant, `uv` + hatchling, pytest, ruff/mypy/pre-commit.

**Architecture & flow:**

```
Claude Code ──MCP/REST──▶ server.py (25 routes) ──▶ MemoryManager (manager.py)
                                                       ├─ Sanitizer → YAML per project/date
                                                       ├─ Embedder → Qdrant (agent_memory)
                                                       └─ KnowledgeGraph (_graph.json) ← auto_link
Cockpit UI (:3333) ──REST──▶ same endpoints
Hooks (claude/hooks/*.sh) ──▶ /api/memory/observe (Haiku-judged capture)
```

**Key directories:**

| Path | Role |
|------|------|
| `src/server.py` | MCP + REST entry, 1049 lines |
| `src/memory/` | 23 domain modules; `manager.py` is the 1370-line core |
| `src/core/` | Embedder, vector store, telemetry |
| `src/tools/` | Pluggable tool registry |
| `src/crawler/`, `src/indexer/` | Doc-crawling sidecar, loosely coupled |
| `ui/` | 4-surface Next.js cockpit |
| `benchmarks/` | LongMemEval runner |
| `claude/` | Shippable hook/skill bundle |
| `tests/` | 54 pytest files |

**Surprises:** no CI whatsoever (`.github/` absent) despite excellent pre-commit discipline; two docker-compose files where only `.yaml` is real; the codebase violates two of its own documented pitfalls (`glob` vs `rglob`, test Qdrant isolation) *on main* — the pitfall table in `CLAUDE.md` describes the BM25 branch, but main has the same class of bug.

---

## Phase 2 — Audit Report

### 🔴 Critical

**C1. Tests default to production Qdrant (:6333), and pre-commit runs them on every commit.** *(fact, verified)*

- `tests/conftest.py:23` — `MemoryManager(memory_dir=temp_memory_dir)` omits `qdrant_url`; `src/memory/manager.py:142` defaults to `http://localhost:6333`. `tests/test_cleanup.py:256–426` constructs 8 more managers the same way; `test_delete_removes_from_yaml` (`test_cleanup.py:243`) drives `manager.delete()` → `manager.py:603–613` → `self.store.client.delete(...)` against whatever is on :6333. Connecting also triggers `_ensure_collection()` (`vector_store.py:124`), which will *create* the collection in prod. The failure is swallowed (`except Exception: logger.warning`) so nobody notices.
- The documented commands — `uv run --extra dev pytest -v` (CLAUDE.md) and the pre-commit pytest hook (`.pre-commit-config.yaml:33–39`) — set no `QDRANT_URL`. Only the Docker test profile (`docker-compose.yaml:123`) is isolated. Actual data-loss exposure today is limited (deletes target hashed test IDs), but this is a loaded gun pointed at the 351 real memories, and it directly violates the repo's own rule: *"never point tests at production Qdrant on 6333."*

### 🟠 High

**H1. Production startup binds `0.0.0.0` with zero auth on destructive endpoints.** *(fact)*

- `scripts/start-memento.sh:28` sets `HOST=0.0.0.0`; `src/server.py:107` also hardcodes `host="0.0.0.0"` in the FastMCP constructor (the `main()` default of `127.0.0.1` at `server.py:1012` is overridden by the script). No auth, no CORS policy, no rate limit on any of the 25 routes. Anyone on the LAN can `DELETE /api/memory/{id}` (`server.py:454`), `POST /api/memory/cleanup` (`server.py:479`), `POST /api/memory/prune/apply` (`server.py:759`), or `POST /api/memory/compact` (`server.py:685` — which spends *your* LLM API money). For a personal memory store containing decisions/preferences, this is also a privacy leak via `GET /api/memory/kb?full=true`.

**H2. Path traversal via the `project` parameter.** *(fact)*

- `src/memory/manager.py:486–488`: `project_dir = self.memory_dir / project` with no validation; `project` arrives verbatim from request bodies (`server.py:264`, `server.py:967`). `project="../../../tmp/evil"` writes YAML outside `~/.claude/memory`. Combined with H1, reachable from the network. Same unvalidated string also reaches `ScopeDetector.detect(cwd=caller_cwd)` (`server.py:993`), which runs `git` subprocesses against arbitrary caller-supplied paths (safe arg-list exec, but still probing).

**H3. `cleanup()` silently does nothing on the current storage layout.** *(fact — correctness)*

- `src/memory/manager.py:653` iterates `self.memory_dir.glob("*.yaml")` — flat. v1.5.0+ writes nested `<project>/<date>.yaml` (`manager.py:486–488`), so the `max_age_days_facts` prune matches zero files and reports `facts_pruned: 0` with no error. This is the exact pitfall CLAUDE.md documents for `migrate_hybrid.py`, alive on main. A silent no-op behind an API that claims to have cleaned.

**H4. `clear_project()` deletes from 1 of 3 stores.** *(fact — correctness)*

- `src/memory/manager.py:1366–1370` deletes only Qdrant points. YAML files and knowledge-graph nodes survive, so `get_stats()` (YAML-based counts), graph rebuilds, and the cockpit disagree about what exists. Contrast `delete()` (`manager.py:535–623`), which correctly handles all three.

**H5. Fresh `Embedder()` per observe request; all CPU-bound work runs on the event loop.** *(fact — performance)*

- `src/server.py:979` constructs `Embedder()` inside `api_observe` for auto-classification. `Embedder` has no cross-instance model cache (`embeddings.py:305–338`; `SentenceTransformerProvider` lazy-loads per instance, `embeddings.py:107`) — every auto-typed observation pays model construction (~seconds, ~500MB churn) instead of reusing `manager.embedder`. Worse, *every* route handler is `async` but calls the fully synchronous manager (encode → Qdrant → YAML → graph save) directly — e.g. `server.py:294`, `:994` — blocking the entire event loop, `/health` included. One slow recall stalls all clients.

**H6. No CI.** *(fact)*

- No `.github/workflows/`. Every guarantee (tests, ruff, mypy) exists only on contributors' machines and can be bypassed with one `git commit --no-verify` (the git-safety hook blocking that is opt-in). For a repo accepting PRs with a merge-based flow, this is the single highest-leverage missing piece.

### 🟡 Medium

**M1. N+1 recall expansion + missing `memory_id` index.** `manager.py:770–776` runs one Qdrant *vector search* per graph neighbor (`limit=1`, filter on `memory_id`), and only `date/project/type` get payload indexes (`manager.py:192`) — so each lookup is an unindexed scan. The point ID is deterministically `stable_hash_id(memory_id)`; a single `client.retrieve()` batch would do. Also `get_by_id` (`vector_store.py:398–405`) scans the same way.

**M2. Hybrid search silently drops `score_threshold`.** `vector_store.py:307–335`: the RRF branch never passes `score_threshold`, so the moment a `_bm25_vocab.json` exists, `recall(score_threshold=0.45)` (`manager.py:748`) and quick-recall's `threshold=0.7` (`server.py:369`) silently stop filtering — RRF scores are rank-based (~0.01–0.03), a different scale entirely. Latent today (encoder loads only if the vocab file exists, `manager.py:174`), guaranteed regression the day the BM25 branch merges. Dedupe survives only because of its exact-string fallback (`manager.py:356–360`).

**M3. `recall()` mutates and rewrites the graph on every read.** `manager.py:764` (`record_access`) + `manager.py:784` (`graph.save()`) — every recall serializes the whole `_graph.json` to disk. Write amplification, and concurrent recalls from two sessions race (the manager singleton is shared across requests, `server.py:189–199`, with no locking).

**M4. Validation gaps produce 500s and unbounded work.** `_read_int`/`_read_float` (`server.py:202–213`) raise `ValueError` on `limit=abc` → 500 instead of 400 (only the graph route catches it, `server.py:533`). No upper bounds: `limit=999999999` hits `store.scroll`. `save` accepts any `type` string (`server.py:263`) — a typo mints a new YAML section and breaks the 7-type enum invariant documented in CLAUDE.md.

**M5. Duplicate endpoints and split response conventions.** `/api/memory/context/resume` (`server.py:640`) and `/api/memory/resume` (`server.py:727`) are byte-identical handlers; half the file uses `_ok/_server_error` helpers, half inline `JSONResponse` — a stalled migration that invites drift.

**M6. Silent truncation on scroll-backed endpoints.** `scroll()` (`vector_store.py:354`) fetches one page; `/api/memory/kb` caps at 2000 (`server.py:888`), `/projects` at 5000 (`server.py:815`), graph rebuild at 10000 (`knowledge_graph.py:373`) — no `truncated` flag, no pagination. At memory-count growth these quietly lie.

**M7. Two config systems + stale compose file + doc drift.** `src/config.py` (372 lines, pydantic, `${VAR}` substitution) vs `src/tools/config.py` + `server.py:get_config()` — overlapping `TOOLS_ENABLED` handling, different load priorities. The untracked `docs/superpowers/plans/2026-05-08-memento-config-merge.md` already plans the fix. `docker-compose.yml` (15-line stub) shadows the real `docker-compose.yaml`. Docs drift: README's ranking formula (`README.md:105`, "vector 50%") doesn't match code (`manager.py:827–833`: 40/20/10/15/15 incl. tier); `docs/SETUP.md:39` omits the `/mcp` URL suffix so the install command fails; README's REST table is missing ~3 live endpoints; `qdrant/qdrant:latest` unpinned (`docker-compose.yaml:20`).

**M8. UI: `z.any()` holes in the resume schema.** `ui/lib/schemas.ts:156–162` types `important/recent/unresolved/next_steps` as `z.any()`, forcing `as any` casts in `ui/app/continuity/page.tsx:39–41` — the one surface with zero contract protection while every other endpoint is properly Zod-parsed. Plus unscoped `qc.invalidateQueries()` on project switch (`ui/components/shell/project-switcher.tsx:19`).

### 🟢 Low

- **Dead code:** `KnowledgeGraph.decay_importance` and `get_chain` have zero production callers (verified by grep) — importance decay is advertised but never runs.
- **Test shims in prod code:** pytest detection at `server.py:126`; the double-path compatibility hack in `knowledge_graph.py:63–74`.
- **`add_node` metadata refresh doesn't set `_dirty`** (`knowledge_graph.py:162–164`) — refreshed `last_accessed/topic` silently lost unless another op dirties the graph.
- **`observe.py:81`** — `lowered` assigned, never used (F841; suggests ruff isn't actually running clean), and `LOW_SIGNAL_PHRASES` includes `"i think"`/`"working on"`, which rejects substantive observations containing those substrings.
- **Stubbed tests:** `tests/test_e2e_memory.py:205–225` — 4 placeholder/skipped tests; `test_memory.py:653` skips the only real save→recall integration test.
- **`update_payload` docstring says "upsert"** but `set_payload` merges — stale keys survive (`vector_store.py:407–418`).
- Tracked working doc `implementation-plan.md` (45KB) at repo root.

### Strengths (preserve these)

1. **Prune safety design is exemplary** — plan/confirm/TTL gating, identity-tier protection, REST-only destructive path (`prune.py`, `server.py:759–787`, `tests/test_prune_safety.py`).
2. **Pre-commit gate runs the full test suite, ruff, mypy, secret detection** — rare discipline.
3. **Credential sanitization** at both content (`manager.py:67–93`, 87 parametrized tests) and git-remote level (`scope.py:20–27`).
4. **Atomic writes everywhere** (mkstemp + `os.replace` in `manager.py:517–529`, `knowledge_graph.py:124–134`).
5. **UI is clean:** every fetch Zod-parsed, no `console.log`, no hardcoded URLs, sensible React Query config, force-graph cleanup handled.
6. **Hardened Dockerfile** (non-root, CPU-only torch, model pre-download) and idempotent start/stop scripts.
7. **`test_dead_code.py`** — regression tests asserting removed APIs stay removed.
8. **Honest documentation** — CLAUDE.md's pitfalls table and "what we deliberately don't do" section.

---

## Phase 3 — Improvement Strategy

**Theme 1 — The safety net has a hole in the middle (C1, H6).**
Principle: *guarantees must be enforced by machinery, not memory.* Target state: tests are physically incapable of touching :6333 (autouse fixture forces `QDRANT_URL=:6334` + asserts it), and a GitHub Actions workflow runs lint+type+tests with a tmpfs Qdrant service on every PR. Done = a test pointing at 6333 fails loudly; CI is required to merge.

**Theme 2 — Trust boundary is implicit (H1, H2, M4).**
Principle: *a memory store is private data; default closed.* Target: bind `127.0.0.1` by default (0.0.0.0 only via explicit opt-in env + a startup warning), validate `project` against `^[A-Za-z0-9._-]+$`, validate `type` against the enum, bound numeric params. A shared-secret header is optional follow-up, not required for a localhost tool. Done = `start-memento.sh` runs on loopback; traversal/typo inputs return 400.

**Theme 3 — Failures must be loud (H3, H4, M2, M6).**
Principle: the repo's own rule — *errors never silently fail.* Target: `cleanup()` uses `rglob`; `clear_project()` clears all three stores; the hybrid branch either honors a threshold or rejects the param; scroll-backed endpoints return a `truncated` flag. Done = a regression test per former silent no-op.

**Theme 4 — Hot path hygiene (H5, M1, M3).**
Principle: *the request path should do request-sized work.* Target: reuse `manager.embedder`; batch neighbor fetch via `client.retrieve(ids=[...])`; index `memory_id`; make recall read-only (batch `record_access` + debounced graph save); push sync manager calls into `asyncio.to_thread`. Done = observe p95 < 200ms warm; recall doesn't write `_graph.json`.

**Theme 5 — One source of truth (M5, M7, docs).**
Principle: DRY applies to configs and docs, not just code. Target: execute the existing config-merge plan; delete the duplicate endpoint and stale compose file; sync README/SETUP with code. Done = one config loader, one compose file, REST table matches `server.py` routes, install command copy-pastes successfully.

**Explicitly NOT recommending:** auth/multi-tenancy beyond loopback-default (single-user tool; cost ≫ benefit), merging the BM25 branch (correctly deferred), raising backend unit coverage to 80%+ via mocked tests (mock-heavy tests of `manager.py` would test mocks; the one skipped integration test against :6334 in CI is worth more), UI test expansion beyond the resume schema fix (surface is healthy), and rewriting `manager.py` for size alone (1370 lines but cohesive — split only if/when the async refactor touches it).

---

## Phase 4 — Task Plan

### Quick wins (do immediately, all S)

| # | Task | Files |
|---|------|-------|
| QW1 | Autouse fixture: `monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")` + same in pre-commit hook env | `tests/conftest.py`, `.pre-commit-config.yaml:35` |
| QW2 | Default `HOST=127.0.0.1` in `start-memento.sh`; drop hardcoded `0.0.0.0` from `server.py:107` (read env) | `scripts/start-memento.sh:28`, `src/server.py:104–110` |
| QW3 | Fix `glob`→`rglob` in `cleanup()` + regression test on nested layout | `src/memory/manager.py:653` |
| QW4 | `api_observe`: use `manager.embedder`, drop per-request `Embedder()` | `src/server.py:975–982` |
| QW5 | Doc sync: SETUP.md `/mcp` suffix, README ranking weights, REST table; delete `docker-compose.yml`; pin qdrant image tag | `docs/SETUP.md:39`, `README.md:100–110,307+`, `docker-compose.yml` |

### Milestone 0 — Safety net

| Task | Description | Acceptance | Effort | Risk | Deps |
|---|---|---|---|---|---|
| **0.1** QW1 + isolation guard | Force test Qdrant URL via autouse fixture; add a fixture that *fails* any test if resolved URL ends in `:6333` | `pytest` with prod Qdrant up leaves its point count untouched; `verify_test_isolation.sh` passes | S | None (test-only) | — |
| **0.2** GitHub Actions CI | Workflow: ruff + mypy + pytest with `qdrant` service container on 6334; un-skip `test_memory.py:653` integration test in CI; add `ui: npm lint + vitest` job | CI red on lint/type/test failure; required check on PRs | M | Low | 0.1 |
| **0.3** Backup target | Codify the documented tarball backup ritual as `make backup` | `make backup` produces dated tarballs | S | None | — |

### Milestone 1 — Critical & correctness fixes

| Task | Description | Acceptance | Effort | Risk | Deps |
|---|---|---|---|---|---|
| **1.1** Loopback default + opt-in exposure (QW2) | Env-driven host with warning log when binding non-loopback | Fresh install serves on 127.0.0.1; UI still works | S | Low — Docker compose must keep `HOST=0.0.0.0` *inside* the container (port mapping handles exposure) | — |
| **1.2** Input validation layer | `project` regex, `type` enum, bounded `_read_int/_read_float` (catch ValueError→400, clamp max), applied across all routes | Traversal payloads & bad types → 400; fuzz test passes | M | Low | — |
| **1.3** Fix `cleanup()` (QW3) | rglob + return per-project counts | Regression test: facts pruned in nested dirs | S | Low | 0.1 |
| **1.4** Fix `clear_project()` | Delete YAML entries + graph nodes + vectors; reuse `delete()` internals | Test: after clear, stats/graph/YAML all agree = 0 | M | Medium — destructive path; ship behind dry_run default | 0.1, 0.2 |
| **1.5** Hybrid threshold honesty | Pass/translate `score_threshold` in RRF branch or log+document the semantic change | Test with sparse encoder active asserts filtering behavior | S | Low | — |

### Milestone 2 — High-leverage improvements

| Task | Description | Acceptance | Effort | Risk | Deps |
|---|---|---|---|---|---|
| **2.1** De-block the event loop | Wrap manager calls in `asyncio.to_thread` + a per-manager lock for graph writes | `/health` responds <50ms during concurrent recalls (add perf test) | L | Medium — concurrency; lock discipline needed | 0.2 |
| **2.2** Kill the N+1 | `memory_id` payload index; replace per-neighbor search with one `client.retrieve` batch of `stable_hash_id`s | Recall issues ≤2 Qdrant calls regardless of neighbor count | M | Low | 0.2 |
| **2.3** Read-only recall | Batch `record_access`, debounce `graph.save()` (dirty-flush on save/delete only, or periodic) | Recall produces zero writes to `_graph.json` | M | Medium — access counts become eventually-consistent | 2.1 |
| **2.4** Config merge | Execute `docs/superpowers/plans/2026-05-08-memento-config-merge.md` | One loader; `tools/config.py` deleted or thin shim; docs updated | XL — already broken down in that plan | Medium | 0.2 |
| **2.5** Endpoint consolidation | Delete duplicate `/api/memory/resume` twin; migrate all routes to `_ok/_bad_request/_server_error`; move pytest-detection out of import path | One resume route; uniform error shape asserted in tests | S | Low | — |

### Milestone 3 — Quality & polish

| Task | Effort | Notes |
|---|---|---|
| 3.1 Resume schema: replace `z.any()` with typed schemas, drop `as any` casts | S | `ui/lib/schemas.ts:156–162`, `continuity/page.tsx:39–41` |
| 3.2 `truncated` flags + documented caps on scroll endpoints | M | server.py kb/projects/pressure/graph |
| 3.3 Delete dead code (`decay_importance`, `get_chain`) **or** wire decay into a maintenance endpoint — decide intent first (see Open Questions) | S | `knowledge_graph.py:301`, `:273` |
| 3.4 Implement or delete the 4 stubbed tests; fix `observe.py:81` unused var; revisit `"i think"`/`"working on"` low-signal phrases | S | `test_e2e_memory.py:205–225` |
| 3.5 Graph `add_node` dirty-flag fix; remove the double-path hack | S | `knowledge_graph.py:63–74`, `:162–164` |
| 3.6 Scoped query invalidation in project switcher | S | `ui/components/shell/project-switcher.tsx:19` |

### Implementation sketches — top 3

**0.1 Test isolation (the gun on the table).** Add to `conftest.py`: an autouse fixture calling `monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")` *before* any `MemoryManager` construction, plus a session-scoped guard that monkeypatches `VectorStore._connect` to raise if `":6333" in self.url`. Gotcha: `MemoryManager` reads the env at `__init__` (`manager.py:142`), not lazily — fixture ordering matters, so use `autouse=True` and ensure no module-level manager construction in tests. Update `.pre-commit-config.yaml:35` entry to `env QDRANT_URL=http://localhost:6334 pytest ...`. Then make `verify_test_isolation.sh` part of CI rather than folklore.

**1.2 Validation layer.** One module-level helper set in `server.py`: `_safe_project(value) -> str | None` (regex `^[A-Za-z0-9._-]{1,64}$`, else raise a `ValidationError` mapped to 400), `_read_int(..., lo, hi)` clamping and catching `ValueError`. Apply mechanically to all 25 routes — the diff is boring on purpose. Enforce `type` against the documented enum in `manager.save()` itself (defense in depth: CLI and Python API get it free). Gotcha: existing memories may carry legacy types — validate on *write* only, never on read, and keep `session` in the enum (used at `manager.py:1150`, `:1290`).

**2.2 N+1 fix.** Point IDs are already deterministic (`stable_hash_id(memory_id)`, `manager.py:610`). In the expand phase replace the per-ID `store.search` loop (`manager.py:770–776`) with one `self.store.client.retrieve(collection, ids=[stable_hash_id(i) for i in new_ids], with_payload=True)` wrapped as `VectorStore.get_many(ids)`. Mark results `_graph_expanded=True` as before; their `score` should be 0.0 (they're re-ranked by the composite anyway). Also add `memory_id` to the indexed fields list at `manager.py:192` so `get_by_id` stops scanning. Gotcha: `retrieve` returns points in arbitrary order and silently omits missing IDs — fine here, but assert payloads non-null before use.

---

## Open Questions

1. **Is LAN access to the cockpit/API ever intended** (e.g., browsing the UI from another machine)? Determines whether 1.1 is "loopback, period" or "loopback + documented opt-in + shared-secret header."
2. **Is importance decay supposed to be live?** `decay_importance` is implemented and tested but never called — README implies dynamic importance. Wire it into a maintenance job, or delete and de-advertise.
3. **Crawler/indexer (`src/crawler/`, `src/indexer/`)** — product or appendix? Untested and isolated; if it's not part of the memory story, consider extracting or explicitly marking it experimental.
4. **`implementation-plan.md` (45KB, tracked at root)** — keep as living doc, or move to `docs/superpowers/plans/` with the others?
5. **Target scale** — at <5k memories the silent scroll caps (M6) and N+1 are tolerable; if you intend tens of thousands (bulk imports, LongMemEval-scale), M6 and pagination move up to High.

---

*Priority if you only do one thing this week: **Milestone 0 + the five quick wins** — about a day of work, converting this from "excellent code with a loaded footgun" to "excellent code."*
