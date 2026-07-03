# Task 5 Report: Cross-Project Transfer Recall

## Status

Completed.

## Files Changed

- `tests/test_cross_project_recall.py`
- `src/memory/manager.py`
- `src/server.py`
- `src/tools/builtin/memory.py`
- `README.md`

## TDD Evidence

### RED

Command:

```bash
uv run --extra dev pytest tests/test_cross_project_recall.py -q
```

Observed result:

- `4 failed`
- `AttributeError: 'MemoryManager' object has no attribute 'recall_cross_project'`
- `404 == 200` for `POST /api/memory/recall/cross-project`
- `KeyError: 'recall_across_projects'`

This confirmed the manager API, REST route, and MCP tool did not exist before implementation.

### GREEN

Command:

```bash
uv run --extra dev pytest tests/test_cross_project_recall.py tests/test_docs_parity.py -q
```

Observed result:

- `7 passed in 0.15s`

## Compatibility Checks

Command:

```bash
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
```

Observed result:

- `12 passed in 0.28s`

## Implementation Summary

### `src/memory/manager.py`

- Added `MemoryManager.recall_cross_project(...)`.
- Kept existing `recall()` behavior unchanged.
- Composed two `recall()` calls:
  - one scoped to `current_project`
  - one broad/global search
- Deduplicated same-project memories from broader results.
- Labeled returned items with additive scopes:
  - `same_project`
  - `related_project`
  - `global`

### `src/server.py`

- Added `POST /api/memory/recall/cross-project`.
- Reused existing request helpers and validation patterns:
  - `_safe_project`
  - `_body_int`
  - `_ok`
  - `_bad_request`
  - `_server_error`
  - `RequestValidationError`

### `src/tools/builtin/memory.py`

- Added tool metadata entry for `recall_across_projects`.
- Registered MCP tool `recall_across_projects(query, current_project, limit=8)`.
- Rendered grouped markdown sections for same-project, related-project, and global recall.

### `tests/test_cross_project_recall.py`

- Added manager behavior test from the task brief.
- Added REST contract tests for the new route.
- Added MCP tool formatting/dispatch test for the new tool.

### `README.md`

- Added docs parity rows for:
  - `recall_across_projects(query, current_project)`
  - `POST /api/memory/recall/cross-project`

## Commands Run

```bash
uv run --extra dev pytest tests/test_cross_project_recall.py -q
uv run --extra dev pytest tests/test_cross_project_recall.py tests/test_docs_parity.py -q
uv run --extra dev pytest tests/test_capsules.py tests/test_startup.py tests/test_server_startup.py tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
git status --short
git diff -- src/memory/manager.py src/server.py src/tools/builtin/memory.py tests/test_cross_project_recall.py README.md
```

## Self-Review

### What Looks Good

- The change is additive and does not modify `recall()` or `recall_memories()`.
- Startup/capsule compatibility checks stayed green.
- README parity is preserved for both route and tool names.
- The route accepts `current_project` and also falls back to `project`, which keeps the request surface forgiving without changing the required validation.

### Risks / Notes

- “Related projects” are currently defined as any non-`general`, non-current project result returned by the broader recall. This matches the brief’s additive approach, but it does not yet encode an explicit project relationship graph.
- The manager method defaults `related_limit` independently, but the REST and MCP surfaces currently expose only `limit`, which is intentional per the task brief.

### Scope Discipline

- Did not edit hooks, startup code paths, capsules, doctor implementation, or unrelated files.
- Did not touch production Qdrant configuration; tests remained pointed at `localhost:6334`.
