# Contributing to Rekall

> **For users:** start at [`README.md`](README.md). This file is for agents (and humans) modifying the codebase.

## Before you change anything

```bash
uv run --extra dev pytest -v                             # all tests, fast
REKALL_TEST_LANE=embedded uv run --extra dev pytest -q   # embedded-qdrant lane (CI runs both)
uv run --extra dev pytest -m wheel                       # wheel gate: build + clean-venv stdio smoke
docker compose --profile test run --rm test              # isolated Docker
```

Tests must pass before you commit. The test profile uses Qdrant on `localhost:6334` (tmpfs) — **never** point tests at production Qdrant on `6333`.

If you're about to do anything destructive (migration, prune, schema change), tarball first:

```bash
TS=$(date +%Y%m%d-%H%M%S)
tar czf ~/backups/pre-$TS-memory.tar.gz -C ~ .claude/memory
docker compose stop qdrant
tar czf ~/backups/pre-$TS-qdrant.tar.gz -C ~/.claude qdrant
docker compose start qdrant
```

## Repo layout (where things live)

```
src/server.py                MCP server + REST endpoints
src/tools/builtin/memory.py  MCP tool definitions
src/memory/<feature>.py      Domain modules (one file per concern)
src/memory/renderers/        Export-format renderers (okf.py); add one file per format
src/core/                    Embedder, vector_store, telemetry, utils
ui/                          Next.js cockpit (port 3333)
benchmarks/                  LongMemEval runner + dataset
tests/                       pytest suite (mirrors src/ structure)
claude/                      Shippable Claude Code bundle (NOT auto-loaded)
docs/                        User-facing docs (SETUP, MIGRATION, ARCHITECTURE, ...)
```

## Adding a new REST endpoint

Pattern (in order):

1. **`src/server.py`** — add `@mcp.custom_route(...)` handler. Use the `_ok` / `_bad_request` / `_server_error` helpers in `server.py` for response shape.
2. **`src/tools/builtin/memory.py`** — register an MCP tool that calls the endpoint. Skip this if the endpoint is destructive (see prune_apply for the pattern of REST-only, no MCP).
3. **`tests/test_server_*.py`** — REST contract test. Hit the endpoint, assert response shape.
4. **`ui/lib/schemas.ts`** — add Zod schema for response.
5. **`ui/lib/api/<endpoint>.ts`** — typed fetch client.
6. **`ui/lib/queries/use-<endpoint>.ts`** — TanStack Query hook.
7. **`ui/components/<surface>/`** — UI consumer if it surfaces in the cockpit.
8. **`README.md`** — add a row to the REST API table.

The whole pattern lives end-to-end in `/api/memory/kb` (added in v1.5.0) — copy that as a template.

## Adding a new MCP tool

`src/tools/builtin/memory.py` exposes tools via the `@mcp.tool()` decorator. The tool name (the function's name) is what the user/agent invokes; the docstring becomes the tool description Claude sees. Keep descriptions short and trigger-shaped — start with "Use when ..." rather than "This function ...".

## Adding a new cockpit surface

Surfaces live under `ui/app/<name>/page.tsx`. Pattern:

1. Page component reads from one or more TanStack Query hooks.
2. Wraps in a Suspense boundary with `loading.tsx`.
3. Components live in `ui/components/<surface>/`.
4. Tests in `ui/tests/<component>.test.tsx` use the fixtures in `ui/tests/fixtures/`.
5. Add the route to `ui/components/shell/sidebar-nav.tsx`.

## Memory schema invariants (don't break)

A memory record has:

| Field | Type | Notes |
|-------|------|-------|
| `id` / `memory_id` | string | `<date>_<type>_<short_hash>` |
| `content` | string | the actual memory text, sanitized |
| `type` | enum | `decision \| learning \| preference \| requirement \| fact \| note \| session \| summary` |
| `project` | string | resolved from caller cwd, never default to backend cwd |
| `date` | YYYY-MM-DD string | NOT epoch — Qdrant `Range` filters won't work; filter post-retrieval |
| `tier` | enum | `working \| episodic \| semantic \| identity` |
| `durability` | float | importance×retention factor |
| `reinforcement_count` | int | increments on cosine ≥ 0.97 dedupe |
| `compacted` / `compacted_into` | bool / string | set by compaction; originals stay in YAML, removed from Qdrant |
| `repr_version` | int | dense-vector representation: 2 = `encode(content)` (v1 encoded embedding_text); `scripts/migrate_repr_v2.py` skips points already at 2 |

**Don't bump the schema silently.** If you add a new field, update `memory/observe.py` (sanitization), `memory/lifecycle.py` (defaults), and `tests/conftest.py` (test fixtures). If existing memories need backfill, write a migration that runs through `manager.backfill_lifecycle()`.

**Identity tier is sacred.** Reinforcement can promote `episodic → semantic → identity`, but nothing auto-demotes identity. Prune contract refuses to delete identity memories.

## Storage discipline

- Production YAML lives at `MEMORY_STORAGE_PATH` (env var). Default: `~/.claude/memory`. v1.5.0+ writes nested per-project: `<project>/<date>.yaml`. Override `MEMORY_STORAGE_PATH` to relocate.
- The nested layout is what the v1.5.0 scope-aware observe writes. Don't add code that assumes flat — use `Path.rglob("*.yaml")`, not `glob("*.yaml")`.
- Knowledge graph at `~/.claude/memory/_graph.json` (always there, even when YAML moves).
- Production Qdrant at `localhost:6333` → `~/.claude/qdrant`. **Read-only from tests.**
- Test Qdrant at `localhost:6334` → tmpfs. Wiped on stop.
- Embedded vector store (uvx/serve tiers) at `~/.rekall/qdrant` (`QDRANT_PATH`); YAML home unchanged at `~/.claude/memory`.
- The ownership protocol (`src/core/ownership.py`) is the only sanctioned way for entry points to decide daemon-vs-embedded — never construct a second store on a locked path.

## Hook discipline (claude/hooks/)

Two hooks ship in `claude/hooks/`. They're inert until installed at `~/.claude/hooks/` with matching `~/.claude/settings.json` entries.

- **`rekall-restore.sh`** (UserPromptSubmit) — fetch-don't-inject. Status line only (~92 bytes/session). **Don't add context dumps here.** If you want context, the agent calls `recall_memories()` on demand.
- **`rekall-observe.sh`** (Stop) — Haiku judge with cheap signal gate. **Never add a hook that fires Haiku per turn without a gate.** Current gate fires on (a) new commits since last fire, (b) durability keyword in last user message, or (c) 5+ turns AND zero saves today. Without the gate you'd burn ~$30/month per active developer.

**Re-entrancy:** if a hook invokes `claude -p`, that inner Claude Code instance fires its own hooks. Guard with `REKALL_JUDGE_INFLIGHT=1` set before exec, checked at the top of the hook. Without this, infinite hook recursion.

**Tool namespace:** the running server registers as `rekall` (in the Claude Code MCP config), so tools are `mcp__rekall__*` — not `mcp__memory__*`. If you copy a hook from another project, namespace-patch first.

## Branch + PR rules

- **Never** push to main. Feature branch + PR.
- **Never** force-push without asking. **Never** rebase a published branch into a different shape.
- **Never** use `--no-verify` on git commands — the `git-safety.sh` PreToolUse hook (when installed) blocks it anyway, and pre-commit hooks exist for a reason.
- Squash if the branch is WIP-heavy and reads as one logical change. Merge-commit if 10+ meaningful commits each describe real work (the v1.5.0 PR was 79 commits, merge-commit preserved the history).
- Bump `pyproject.toml` version on release. Tag `vX.Y.Z`. Create GitHub release with `docs/MIGRATION.md` excerpt as release notes.

## What we deliberately don't do

- **`/dashboard` route.** Removed in v1.5.0 (409 lines of embedded HTML). The cockpit at `:3333` is the supported UI. Don't bring it back.
- **Proactive context injection.** The restore hook is zero-injection by design — anything in the data is reachable via `recall_memories()` on demand. Per-session firehose injection burns tokens for noise.
- **Per-turn LLM judge without a gate.** Cost cliff. See hook discipline above.
- **Synthesizing rules into CLAUDE.md from imagined sources.** Real incident — a rule about commit footers got fabricated and almost shipped. Verbatim source or explicit author intent only.
- **BM25 hybrid on main.** Lives on `feat/hybrid-search-bm25` until the migrate_hybrid.py glob→rglob fix and the compact.py asyncio.run→await fix land. Don't merge without those.
- **More reads over smarter reads.** A new context surface ships only with evidence it reduces duplicate memory_ids across capsule buckets (test-asserted) or feeds the recall-utility loop (event emitted + consumed by the utility report). No evidence, no merge.
- **Eval corpus and scenario queries in `tests/test_software_evals.py` may not be edited in the same PR as ranking/routing changes, except to add scenarios.**

## Deferred work (with reason)

- **BM25 hybrid merge** — adds Qdrant-native sparse vectors for identifier-style queries. Marginal value at <5k memories; merge when scale demands. Pre-merge fix required: `migrate_hybrid.py` glob→rglob.
- **Auto-compaction** — shipped on main (`src/memory/compact.py`, route `POST /api/memory/compact`). Known issue: asyncio.run inside sync path (see pitfall table).
- **Session-end summary** — Claude Code has no native end-of-session hook. Workaround would be a slash command the user types at session end. Not worth building until per-turn judge proves insufficient.

## Pitfalls (real ones we've hit)

| Pitfall | Where | Fix |
|---------|-------|-----|
| `asyncio.run()` inside sync function called from async route → "event loop already running" | `src/memory/compact.py:284` (main) | Make `compact_memories` async, change to `await _summarize_with_llm(...)` |
| `glob("*.yaml")` returns zero files when YAML is nested per-project | `migrate_hybrid.py` (BM25 branch) | `rglob("*.yaml")` |
| Qdrant `Range` filter on `date` (string `YYYY-MM-DD`) silently returns 0 hits | `manager.recall()` `days` filter | Filter post-retrieval via Python string compare |
| RRF prefetch drops `query_filter` at the outer `query_points` level | `vector_store.py:331` (fixed in v1.5.0) | Pass `query_filter=query_filter` to the outer `query_points` call too |
| Backend resolves scope from its own cwd → all observations under "rekall-mcp" | `/api/memory/observe` (fixed in v1.5.0) | Endpoint accepts `cwd` from caller, plumbs to `ScopeDetector.detect()` |
| Stop hook fires per turn at $0.001/each → ~$30/month/dev | `rekall-observe.sh` (fixed in v1.5.0) | Cheap signal gate before Haiku call |
| `claude -p` from a Stop hook recursively fires its own Stop hook | `rekall-observe.sh` | `REKALL_JUDGE_INFLIGHT=1` env var guard |
| `uv run python -m server` runs the STALE installed copy of `server.py`/`config.py` — hatchling copies force-included top-level modules into site-packages at sync; edits to `src/server.py` are invisible until re-sync | dev workflow (since v1.11 packaging) | `PYTHONPATH=src uv run python -m server` in dev, or `uv sync --reinstall-package rekall-mcp` after editing those two files |
| Restore hook fetches 12KB of "proactive context" but echoes only the status line | pre-v1.5.0 `rekall-restore.sh` | Either drop the fetch entirely (current — nuclear mode) or actually inject (was the bug we caught) |
| Compose defaults to named volumes → existing installs mount empty stores and "all memories are gone" | `docker-compose.yaml` (v1.11) | Layer `docker-compose.bind-mounts.example.yaml` (or copy it to `docker-compose.override.yaml`) to keep the `~/.claude/` bind mounts |
| Stale `.env` `EMBEDDING_PROVIDER=sentence-transformers` on the slim image (no torch) silently degrades endpoints to zero | v1.11 deploy | Remove the var or set `fastembed` (vectors are identical); #57 tracks making the failure loud |

## Where to read next

- [`README.md`](README.md) — user-facing
- [`docs/MIGRATION.md`](docs/MIGRATION.md) — v1.4 → v1.5 upgrade
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview
- [`docs/CLAUDE_MEMORY_SETTINGS.md`](docs/CLAUDE_MEMORY_SETTINGS.md) — runtime knobs + tuning
- [`docs/TUNING.md`](docs/TUNING.md) — recall behavior tuning
