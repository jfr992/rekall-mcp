# Claude Code Memory Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Rekall reliable and safe enough for Claude Code to use as the first supported agent memory client.

**Architecture:** Keep YAML as source of truth, Qdrant as recall index, and the knowledge graph as ranking/evidence metadata. Add one shared project identity resolver, one provenance envelope, local-first secure defaults, and explicit graph recall evidence around the existing `MemoryManager`, MCP tools, REST routes, and startup packet.

**Tech Stack:** Python 3.12, FastMCP/Starlette, Qdrant, PyYAML, pytest, Next.js/TypeScript, Vitest, Docker Compose.

---

### Task 1: Add Regression Tests For Nested YAML Discovery

**Files:**
- Modify: `tests/test_sync.py`
- Modify: `tests/test_compact.py`
- Modify: `tests/test_cache_context.py`

**Step 1: Write failing sync tests**

Add tests proving `memory.sync._get_yaml_memories()` reads nested project files
and that `sync_memories()` refuses a suspicious delete plan when YAML discovery
finds zero memories but Qdrant has existing memories.

```python
def test_loads_nested_project_yaml(tmp_path):
    from memory.sync import _get_yaml_memories

    project_dir = tmp_path / "my-app"
    project_dir.mkdir()
    (project_dir / "2026-07-02.yaml").write_text(
        yaml.dump({"date": "2026-07-02", "facts": [{"id": "m1", "content": "nested", "project": "my-app"}]})
    )

    assert "m1" in _get_yaml_memories(tmp_path)
```

**Step 2: Write failing compaction tests**

Add tests proving `mark_compacted_in_yaml()` updates nested YAML files and leaves
unrelated nested project files untouched.

**Step 3: Write failing cache context tests**

Add a test proving `CacheableContext` reads nested YAML when building stable
context.

**Step 4: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_sync.py tests/test_compact.py tests/test_cache_context.py -q
```

Expected: new tests fail because some code still assumes flat YAML.

**Step 5: Commit**

```bash
git add tests/test_sync.py tests/test_compact.py tests/test_cache_context.py
git commit -m "test: cover nested memory yaml reliability"
```

### Task 2: Fix Nested YAML Discovery And Unsafe Sync Deletes

**Files:**
- Modify: `src/memory/sync.py`
- Modify: `src/memory/compact.py`
- Modify: `src/memory/cache_context.py`
- Modify: `src/memory/migrate_hybrid.py`
- Modify: `tests/test_sync.py`

**Step 1: Replace flat scans**

Change production YAML scans from `glob("*.yaml")` to a shared nested scan
helper or direct `rglob("*.yaml")`.

Skip internal files deliberately:

```python
def _iter_memory_yaml_files(root: Path):
    for yaml_file in root.rglob("*.yaml"):
        if yaml_file.name.startswith("_"):
            continue
        yield yaml_file
```

**Step 2: Add sync delete guard**

In `sync_memories()`, if `yaml_memories` is empty, `qdrant_memories` is not
empty, and the caller has not passed an explicit force flag, return a blocked
result instead of deleting.

Example response shape:

```python
{
    "synced": False,
    "blocked": True,
    "reason": "yaml_discovery_empty_with_existing_qdrant",
    "to_delete": 0,
}
```

**Step 3: Add force flag only to sync internals/CLI**

If the current sync CLI exists, expose the force flag there. Keep the default
safe.

**Step 4: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_sync.py tests/test_compact.py tests/test_cache_context.py tests/test_migrate_hybrid.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add src/memory/sync.py src/memory/compact.py src/memory/cache_context.py src/memory/migrate_hybrid.py tests/test_sync.py tests/test_compact.py tests/test_cache_context.py tests/test_migrate_hybrid.py
git commit -m "fix: make memory yaml scans nested-safe"
```

### Task 3: Make Compaction Async-Safe And Failure-Visible

**Files:**
- Modify: `src/memory/compact.py`
- Modify: `src/server.py`
- Modify: `tests/test_compact.py`
- Modify: `tests/test_server_memory_os_endpoints.py` or create `tests/test_server_compact.py`

**Step 1: Write failing async route test**

Add a test that calls the compact REST route in execute mode from the async
server path and asserts it creates a summary instead of swallowing
`asyncio.run()` failure.

**Step 2: Convert compaction to async**

Change:

```python
def compact_memories(...):
```

to:

```python
async def compact_memories(...):
```

Replace internal `asyncio.run(_summarize_with_llm(...))` with:

```python
summary = await _summarize_with_llm(prompt)
```

**Step 3: Update callers**

In `src/server.py`, call:

```python
result = await compact_memories(...)
```

If a CLI or sync caller needs compaction, wrap it with `asyncio.run()` only at
the outermost command-line boundary.

**Step 4: Return partial failures**

Have compaction return `errors` and avoid deleting original Qdrant points unless
summary save and YAML marking both succeed.

**Step 5: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_compact.py tests/test_server_compact.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add src/memory/compact.py src/server.py tests/test_compact.py tests/test_server_compact.py
git commit -m "fix: make memory compaction async-safe"
```

### Task 4: Introduce Shared Project Identity

**Files:**
- Create: `src/memory/project.py`
- Create: `tests/test_project_identity.py`
- Modify: `src/memory/scope.py`
- Modify: `src/memory/manager.py`
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Modify: `ui/lib/schemas.ts`
- Modify: `ui/lib/project-store.ts`

**Step 1: Write project identity tests**

Cover:

- valid safe names remain unchanged
- names with spaces get stable safe keys
- path traversal is rejected
- display name is preserved
- legacy exact project values can still be resolved for reads

**Step 2: Add identity module**

Create:

```python
@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    key: str
    display_name: str
    raw: str

def resolve_project(value: str | None, *, fallback: str = "general") -> ProjectIdentity:
    ...
```

Use a path-safe key such as `[A-Za-z0-9._-]{1,64}`. Preserve existing safe
project names exactly.

**Step 3: Use identity in scope and saves**

`ScopeDetector.detect()` should resolve project once. `MemoryManager.save()`
should store:

```python
"project": identity.key,
"project_display_name": identity.display_name,
```

**Step 4: Replace REST-only validation**

Replace `_safe_project()` in `src/server.py` with the shared resolver so REST
and MCP agree.

**Step 5: Preserve legacy read compatibility**

For project list and reads, support existing raw project names. Prefer canonical
keys for new writes.

**Step 6: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_project_identity.py tests/test_scope.py tests/test_server_validation.py tests/test_memory.py -q
npm test -- schemas project
```

Expected: pass.

**Step 7: Commit**

```bash
git add src/memory/project.py src/memory/scope.py src/memory/manager.py src/server.py src/tools/builtin/memory.py ui/lib/schemas.ts ui/lib/project-store.ts tests/test_project_identity.py tests/test_scope.py tests/test_server_validation.py tests/test_memory.py
git commit -m "feat: unify memory project identity"
```

### Task 5: Make Deployment Defaults Local-First

**Files:**
- Modify: `src/server.py`
- Modify: `src/core/vector_store.py`
- Modify: `src/memory/manager.py`
- Modify: `docker-compose.yaml`
- Modify: `.env.example`
- Modify: `tests/test_server_host_default.py`
- Modify: `tests/test_auth_middleware.py`

**Step 1: Write failing host default tests**

Assert backend host defaults to loopback when no `HOST` is configured.

**Step 2: Bind local ports to loopback**

In compose, publish local services as loopback bindings:

```yaml
ports:
  - "127.0.0.1:8000:8000"
  - "127.0.0.1:6333:6333"
```

Keep service-internal binding explicit where Docker networking needs it.

**Step 3: Add network exposure guard**

If backend host is non-loopback and `REKALL_API_TOKEN` is missing, fail startup
unless an explicit unsafe override is set.

Suggested override:

```text
REKALL_ALLOW_UNAUTH_NETWORK=1
```

**Step 4: Plumb Qdrant API key**

Pass `QDRANT_API_KEY` from environment into `VectorStore` and Qdrant clients.

**Step 5: Document team mode**

In `.env.example`, document local mode, team mode, token requirements, and
Qdrant API key behavior.

**Step 6: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_server_host_default.py tests/test_auth_middleware.py tests/test_qdrant_isolation.py -q
```

Expected: pass.

**Step 7: Commit**

```bash
git add src/server.py src/core/vector_store.py src/memory/manager.py docker-compose.yaml .env.example tests/test_server_host_default.py tests/test_auth_middleware.py tests/test_qdrant_isolation.py
git commit -m "fix: make memory services local-first by default"
```

### Task 6: Add Recall Evidence To Graph-Enhanced Recall

**Files:**
- Modify: `src/memory/knowledge_graph.py`
- Modify: `src/memory/manager.py`
- Modify: `src/tools/builtin/memory.py`
- Modify: `tests/test_graph_enhanced_recall.py`
- Modify: `tests/test_memory.py`

**Step 1: Write failing evidence tests**

Assert vector seed results include `recall_evidence.source == "vector"` and
graph-expanded results include seed id, relation, and relation weight.

**Step 2: Add edge-aware neighbor helper**

Add a graph method that returns neighbor id plus edge metadata instead of only
ids.

Example shape:

```python
{
    "memory_id": "learning_pool",
    "seed_memory_id": "decision_pg",
    "relation": "led_to",
    "relation_weight": 0.8,
}
```

**Step 3: Attach score components**

In `MemoryManager.recall()`, preserve vector score, importance score, recency
score, tier score, graph score, and final score in `recall_evidence`.

**Step 4: Update formatted recall**

In `recall_formatted()`, add a short `Why:` line for each result without making
the output noisy.

**Step 5: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_graph_enhanced_recall.py tests/test_memory.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add src/memory/knowledge_graph.py src/memory/manager.py src/tools/builtin/memory.py tests/test_graph_enhanced_recall.py tests/test_memory.py
git commit -m "feat: explain graph-enhanced memory recall"
```

### Task 7: Persist Provenance On Every Memory Write

**Files:**
- Modify: `src/memory/scope.py`
- Modify: `src/memory/manager.py`
- Modify: `src/tools/builtin/memory.py`
- Modify: `src/server.py`
- Modify: `tests/test_scope.py`
- Modify: `tests/test_memory.py`
- Modify: `tests/test_server_validation.py`

**Step 1: Write failing provenance tests**

Assert memories saved through `save_memory`, `observe`, and REST save include
provenance fields in both the Qdrant payload and YAML entry.

**Step 2: Extend scope metadata**

Add fields to `MemoryScope` or a companion provenance helper:

```python
created_by: str
source_tool: str
source_event: str
save_reason: str
cwd: str
observed_at: str
```

Keep `to_metadata()` backwards-compatible by omitting empty values.

**Step 3: Add tool-specific provenance**

In MCP tools:

- `observe()` sets `source_tool="observe"`
- `save_memory()` sets `source_tool="save_memory"`
- `agent_startup()` does not save memory

REST save should set `source_tool="rest:/api/memory/save"`.

**Step 4: Persist to YAML and Qdrant**

Ensure `_save_to_file()` copies provenance metadata into memory entries.

**Step 5: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_scope.py tests/test_memory.py tests/test_server_validation.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add src/memory/scope.py src/memory/manager.py src/tools/builtin/memory.py src/server.py tests/test_scope.py tests/test_memory.py tests/test_server_validation.py
git commit -m "feat: persist memory provenance"
```

### Task 8: Upgrade Claude Code Startup Packet

**Files:**
- Modify: `src/memory/startup.py`
- Modify: `src/memory/resume.py`
- Modify: `src/tools/builtin/memory.py`
- Modify: `docs/CLAUDE_MEMORY_SETTINGS.md`
- Modify: `docs/AGENT_STARTUP.md`
- Modify: `tests/test_server_startup.py`
- Modify: `tests/test_startup.py`
- Modify: `tests/test_startup_hints_match_doc.py`

**Step 1: Write failing startup tests**

Assert `agent_startup(agent="claude-code")` includes memory health warnings,
scope/provenance hints, and graph recall policy.

**Step 2: Add lightweight health warnings**

Include cheap checks only:

- graph node/edge counts
- whether graph has zero edges
- whether resume packet is truncated
- current trust boundary
- local/team mode hint

Do not run expensive sync or full graph rebuild during startup.

**Step 3: Update startup copy**

Make the Claude Code hints direct:

- call once per session
- always pass project when known
- use recall for targeted lookups
- use observe only for durable facts
- avoid destructive maintenance

**Step 4: Update docs**

Update `docs/CLAUDE_MEMORY_SETTINGS.md` and `docs/AGENT_STARTUP.md` with the
same policy. Keep docs/tests parity intact.

**Step 5: Run targeted tests**

Run:

```bash
uv run --extra dev pytest tests/test_server_startup.py tests/test_startup.py tests/test_startup_hints_match_doc.py tests/test_docs_parity.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add src/memory/startup.py src/memory/resume.py src/tools/builtin/memory.py docs/CLAUDE_MEMORY_SETTINGS.md docs/AGENT_STARTUP.md tests/test_server_startup.py tests/test_startup.py tests/test_startup_hints_match_doc.py tests/test_docs_parity.py
git commit -m "feat: sharpen claude-code memory startup"
```

### Task 9: Update UI For Project Identity And Recall Evidence

**Files:**
- Modify: `ui/lib/schemas.ts`
- Modify: `ui/lib/api/graph.ts`
- Modify: `ui/lib/api/projects.ts`
- Modify: `ui/components/shell/project-switcher.tsx`
- Modify: `ui/components/brain/node-drawer.tsx`
- Modify: `ui/tests/schemas.test.ts`
- Modify: `ui/tests/node-drawer.test.tsx`

**Step 1: Write failing UI schema tests**

Assert project API responses can include `project_key` and
`project_display_name`. Assert recall/graph detail schemas accept
`recall_evidence` when exposed.

**Step 2: Display names, filter keys**

Use display names in UI labels and canonical keys in API requests.

**Step 3: Surface evidence quietly**

In node/details UI, show provenance and recall evidence when present. Keep the
visual graph focused; do not turn it into a debug dashboard.

**Step 4: Run UI tests**

Run:

```bash
cd ui && npm test -- schemas node-drawer
```

Expected: pass.

**Step 5: Commit**

```bash
git add ui/lib/schemas.ts ui/lib/api/graph.ts ui/lib/api/projects.ts ui/components/shell/project-switcher.tsx ui/components/brain/node-drawer.tsx ui/tests/schemas.test.ts ui/tests/node-drawer.test.tsx
git commit -m "feat(ui): show canonical projects and memory evidence"
```

### Task 10: Full Verification And Documentation Sweep

**Files:**
- Modify: `README.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/MIGRATION.md`
- Modify: `docs/CLAUDE_MEMORY_SETTINGS.md`

**Step 1: Update user docs**

Document:

- local-first default
- team mode opt-in
- Claude Code startup flow
- project identity behavior
- provenance fields
- recall evidence
- safe sync/compaction guarantees

**Step 2: Run backend verification**

Run:

```bash
uv run ruff check src tests
uv run --extra dev pytest -m "not integration" --tb=short -q
```

Expected: ruff passes and pytest passes.

**Step 3: Run UI verification**

Run:

```bash
cd ui && npm test
cd ui && npm run build
```

Expected: tests and build pass.

**Step 4: Run docs parity**

Run:

```bash
uv run --extra dev pytest tests/test_docs_parity.py tests/test_startup_hints_match_doc.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add README.md docs/SETUP.md docs/ARCHITECTURE.md docs/MIGRATION.md docs/CLAUDE_MEMORY_SETTINGS.md
git commit -m "docs: document claude-code memory reliability"
```

### Task 11: Release Readiness Check

**Files:**
- No code changes expected.

**Step 1: Check worktree**

Run:

```bash
git status --short
```

Expected: only pre-existing unrelated local files remain, or the worktree is
clean.

**Step 2: Inspect commits**

Run:

```bash
git log --oneline main..HEAD
```

Expected: commits map to the tasks above.

**Step 3: Decide integration path**

Use `superpowers:finishing-a-development-branch`. Open a PR when the branch is
ready. Do not push to `main`.

## Execution Options

After this plan is approved:

1. **Subagent-Driven in this session**: dispatch one fresh implementation
   subagent per task and review between tasks.
2. **Parallel Session**: open a separate session in this branch and execute
   with `superpowers:executing-plans`.
