# Task 3 Report: Memory Doctor Trust Report

## Status

DONE

## Scope

Implemented the read-only Memory Doctor trust report for Rekall.

Files changed:
- `src/memory/doctor.py`
- `src/memory/manager.py`
- `src/server.py`
- `src/tools/builtin/memory.py`
- `tests/test_memory_doctor.py`
- `tests/test_server_nervous_system.py`
- `README.md`

Notes:
- `README.md` was updated only for docs parity on the new public MCP tool and REST route.
- No hooks, startup scripts, live `~/.claude` files, or destructive memory/Qdrant logic were modified.

## TDD Evidence

### RED

Command:

```bash
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
```

Result:

```text
tests/test_memory_doctor.py FF
tests/test_server_nervous_system.py F

ModuleNotFoundError: No module named 'memory.doctor'
ImportError: cannot import name 'api_memory_doctor' from 'server'
```

Interpretation:
- The new doctor module did not exist yet.
- The new REST route did not exist yet.
- This is the expected failing state before implementation.

### GREEN

Command:

```bash
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py tests/test_docs_parity.py -q
```

Final result:

```text
6 passed in 0.15s
```

Intermediate note:
- The first green attempt surfaced README parity failures for `/api/memory/doctor` and `memory_doctor`.
- I then added the minimal README rows required by `tests/test_docs_parity.py`.

## Startup Compatibility Check

Command:

```bash
uv run --extra dev pytest tests/test_startup.py tests/test_server_startup.py -q
```

Result:

```text
2 passed in 0.20s
```

Interpretation:
- Claude startup compatibility remained intact.
- Server import/startup behavior stayed green after adding the new route and tool.

## Implementation Summary

### `src/memory/doctor.py`

Added `run_memory_doctor(manager, project=None, limit=10000) -> dict`:
- Reads YAML memory ids from nested project storage using `rglob("*.yaml")`
- Reads Qdrant payload ids via `manager.store.scroll(...)`
- Computes drift:
  - `missing_from_qdrant`
  - `missing_from_yaml`
- Reports provenance gaps:
  - `missing_agent`
  - `missing_source_tool`
  - `missing_cwd`
- Includes:
  - `vector_health`
  - `graph` stats
  - `findings`
  - overall `status`

This implementation is read-only.

### `src/memory/manager.py`

Added a minimal passthrough:

```python
def doctor(self, project: str | None = None) -> dict[str, Any]:
    from memory.doctor import run_memory_doctor
    return run_memory_doctor(self, project=project)
```

### `src/server.py`

Added read-only REST endpoint:

```text
GET /api/memory/doctor?project=...
```

Pattern matches existing server helpers:
- `_safe_project(...)`
- `_ok(...)`
- `_bad_request(...)`
- `_server_error(...)`
- `RequestValidationError`

### `src/tools/builtin/memory.py`

Added MCP tool definition and registration:

```text
memory_doctor(project: str | None = None) -> str
```

The tool:
- resolves scope using existing scope detection
- calls `self.manager.doctor(...)`
- returns a concise summary string

### `tests/test_memory_doctor.py`

Added coverage for:
- YAML/Qdrant drift detection
- provenance gap detection

### `tests/test_server_nervous_system.py`

Added coverage for:
- REST route wiring
- `project` parameter passthrough to `manager.doctor(...)`

### `README.md`

Added the minimum public-surface documentation required by docs parity:
- MCP tools table row for `memory_doctor(project)`
- REST API table row for `/api/memory/doctor`

## Commands Run

```bash
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py -q
uv run --extra dev pytest tests/test_memory_doctor.py tests/test_server_nervous_system.py tests/test_docs_parity.py -q
uv run --extra dev pytest tests/test_startup.py tests/test_server_startup.py -q
```

## Self-Review

What looks good:
- The task stayed within the requested ownership boundaries.
- The doctor report is read-only and does not call any mutating manager/store/graph methods.
- Tests verify both core report logic and the new REST surface.
- README parity is preserved.
- Startup compatibility remains green.

Tradeoffs:
- The MCP tool returns a concise trust summary rather than the full JSON report. That matches the task brief and keeps the tool readable for agents.
- The doctor implementation intentionally stays lightweight and deterministic; it reports trust signals without attempting repair.

Risks / concerns:
- The report assumes YAML entries store ids under `id` and Qdrant payloads under `memory_id`, which is consistent with current schema expectations.
- The provenance checks currently count missing fields in Qdrant payloads but do not attempt to infer provenance from YAML, by design.

## Commit

Planned commit message:

```text
feat: add memory doctor trust report
```
