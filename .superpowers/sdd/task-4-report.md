# Task 4 Report: Project Familiarity Capsules

## Status

DONE

## Scope

Implemented project familiarity capsules with:

- `build_project_capsule(manager, project, limit=300)` in `src/memory/capsules.py`
- `render_project_capsule(capsule)` for bounded text rendering
- `MemoryManager.get_project_capsule(...)`
- additive `project_capsule` in agent startup payload
- bounded capsule section in startup summary
- REST route: `GET /api/memory/capsule`
- MCP tool: `project_capsule(project)`

Kept the startup contract additive only. No Claude hooks, live `~/.claude` files, or unrelated docs were touched.

## TDD Evidence

### RED

Added failing tests first:

- `tests/test_capsules.py`
- `tests/test_startup.py`
- `tests/test_server_startup.py`

Command:

```bash
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py -q
```

Observed failure:

```text
FAILED tests/test_capsules.py::test_capsule_groups_project_familiarity - ModuleNotFoundError: No module named 'memory.capsules'
FAILED tests/test_capsules.py::test_render_project_capsule_is_thin - ModuleNotFoundError: No module named 'memory.capsules'
FAILED tests/test_startup.py::test_build_agent_startup_returns_summary - AssertionError: assert 'project_capsule' in startup
FAILED tests/test_server_startup.py::test_api_project_capsule - ImportError: cannot import name 'api_project_capsule' from 'server'
```

### GREEN

Implemented the minimal production code, then ran the required focused suite.

Command:

```bash
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py tests/test_docs_parity.py -q
```

Observed success:

```text
8 passed in 0.26s
```

## Compatibility Checks

Command:

```bash
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
```

Observed success:

```text
5 passed in 0.15s
```

## Files Changed

- `src/memory/capsules.py`
- `src/memory/manager.py`
- `src/memory/startup.py`
- `src/server.py`
- `src/tools/builtin/memory.py`
- `tests/test_capsules.py`
- `tests/test_startup.py`
- `tests/test_server_startup.py`
- `README.md`

## Implementation Notes

- Capsule builder reads project-scoped memories via `store.scroll(filters={"project": project}, limit=limit)`.
- Memories are enriched with graph importance and grouped into:
  - `standing_context`
  - `active_workstreams`
  - `operating_rules`
  - `danger_zones`
  - `open_loops`
- Capsule output is intentionally bounded:
  - per-section item caps
  - per-item content truncation
  - renderer max length cap
- Startup payload now includes:
  - existing fields unchanged
  - additive `project_capsule`
- Startup summary now renders a `## Familiarity Capsule` section using the thin renderer.
- README parity was updated for the new REST route and MCP tool.

## Commands Run

```bash
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py -q
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py tests/test_docs_parity.py -q
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
git diff -- src/memory/capsules.py src/memory/manager.py src/memory/startup.py src/server.py src/tools/builtin/memory.py tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py README.md
git status --short
```

## Self-Review

What looks good:

- The change is additive and localized to the task-owned surface.
- Startup remains thin and bounded; it does not dump raw memory lists.
- Startup tests avoid live Qdrant by mocking `get_project_capsule`.
- Docs parity remains green for both route and tool exposure.

Things I checked closely:

- `agent_startup` REST shape remains compatible except for the additive `project_capsule` field.
- The new route uses existing validation helpers and response helpers.
- The MCP tool returns the rendered capsule rather than exposing raw internals.

Residual concern:

- `build_agent_startup()` now always requests a capsule for the resolved project. That matches the task brief and tests, but it does add one more memory-store read during startup by design.

## Task 4 Fix Pass

### Summary

Addressed the review findings for capsule startup resilience and capsule scan breadth:

- `build_agent_startup()` now degrades safely if capsule construction fails.
- `build_project_capsule()` now uses a broader bounded internal scan before ranking.
- Startup tests no longer touch production Qdrant and now cover the fallback path.

### Commands Run

```bash
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py tests/test_docs_parity.py -q
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
```

### Results

```text
10 passed in 0.36s
5 passed in 0.15s
```

### Notes

- `build_agent_startup()` now returns `project_capsule: {}` and still renders the startup summary when capsule retrieval fails.
- Capsule collection now scans up to 2000 points internally, while section caps and render truncation keep the output bounded.
