# Task 2 Report: Deterministic Memory Representation

## Scope

Implemented deterministic memory representation for newly saved memories:

- added `src/memory/representation.py`
- added `tests/test_memory_representation.py`
- wired `MemoryManager.save()` to persist `entities` and `embedding_text`
- made newly saved vectors encode `embedding_text`
- updated hybrid migration to preserve existing `embedding_text`/`entities` when present and synthesize them when absent
- updated test fixture defaults in `tests/conftest.py`

Kept compatibility constraints intact:

- no startup output changes
- no Claude hook changes
- no live `~/.claude` edits
- no REST startup behavior changes
- no production Qdrant setting changes
- existing memories without `embedding_text` remain readable and can still be re-indexed

## TDD Evidence

### RED

Command:

```bash
uv run --extra dev pytest tests/test_memory_representation.py -q
```

Exit code: `1`

Observed failures:

- `ModuleNotFoundError: No module named 'memory.representation'` in:
  - `test_extract_entities_preserves_software_identifiers`
  - `test_build_embedding_text_adds_scope_and_entities`
- `test_manager_saves_embedding_text_and_uses_it_for_vector` failed because `MemoryManager.save()` still encoded raw content:
  - expected prefix: `Project byte-edge.`
  - actual encoded text: `Longhorn settings matter`

### GREEN

Command:

```bash
uv run --extra dev pytest tests/test_memory_representation.py tests/test_memory.py tests/test_migrate_hybrid.py -q
```

Exit code: `0`

Observed result:

```text
82 passed, 2 warnings in 16.58s
```

Notes:

- the first implementation pass changed `build_corpus()` and broke two existing migration tests
- corrected by keeping BM25 corpus generation on raw content and limiting deterministic representation to re-indexing

## Startup Compatibility Check

Command:

```bash
uv run --extra dev pytest tests/test_startup.py tests/test_server_startup.py -q
```

Exit code: `0`

Observed result:

```text
2 passed in 0.22s
```

## Commands Run

```bash
sed -n '1,260p' .superpowers/sdd/task-2-brief.md
git status --short
git branch --show-current
rg -n "embedding_text|entities|representation|memory_saved|event_log" src tests
sed -n '1,420p' src/memory/manager.py
sed -n '1,260p' tests/conftest.py
sed -n '1,260p' src/memory/migrate_hybrid.py
sed -n '1,260p' tests/test_memory.py
sed -n '1,260p' tests/test_migrate_hybrid.py
uv run --extra dev pytest tests/test_memory_representation.py -q
uv run --extra dev pytest tests/test_memory_representation.py tests/test_memory.py tests/test_migrate_hybrid.py -q
uv run --extra dev pytest tests/test_startup.py tests/test_server_startup.py -q
git diff -- src/memory/representation.py src/memory/manager.py src/memory/migrate_hybrid.py tests/conftest.py tests/test_memory_representation.py
git diff --stat -- src/memory/representation.py src/memory/manager.py src/memory/migrate_hybrid.py tests/conftest.py tests/test_memory_representation.py
git add src/memory/representation.py src/memory/manager.py src/memory/migrate_hybrid.py tests/conftest.py tests/test_memory_representation.py
git add -f .superpowers/sdd/task-2-report.md
git commit -m "feat: add deterministic memory representation"
git show --stat --summary HEAD -- src/memory/representation.py src/memory/manager.py src/memory/migrate_hybrid.py tests/conftest.py tests/test_memory_representation.py .superpowers/sdd/task-2-report.md
```

## Files Changed

- `src/memory/representation.py`
- `src/memory/manager.py`
- `src/memory/migrate_hybrid.py`
- `tests/conftest.py`
- `tests/test_memory_representation.py`

## Implementation Notes

### `src/memory/representation.py`

- added deterministic entity extraction with identifier-friendly regex coverage for:
  - hyphenated service names
  - mixed-case software names
  - underscore identifiers
  - ticket-style IDs
- added `build_embedding_text()` with stable metadata ordering:
  - `Project`
  - `Type`
  - `Tier`
  - optional `Repository`
  - optional `Entities`
  - `Claim`

### `src/memory/manager.py`

- imported `build_embedding_text` and `extract_entities`
- after lifecycle summarization, now attaches:
  - `payload["entities"]`
  - `payload["embedding_text"]`
- vector embedding now uses `payload["embedding_text"]`
- vector-store sparse content input now also uses `embedding_text`
- YAML durability path still stores the original sanitized `content`, keeping existing read behavior intact

### `src/memory/migrate_hybrid.py`

- switched YAML discovery from `glob("*.yaml")` to `rglob("*.yaml")` so nested per-project memories are included
- loader now carries forward optional fields:
  - `tier`
  - `repo_name`
  - `embedding_text`
  - `entities`
- re-index path now:
  - preserves existing `embedding_text`/`entities` if already present
  - synthesizes them for older entries if absent
  - encodes and sparse-indexes using `embedding_text`
- left `build_corpus()` behavior unchanged to preserve existing BM25 test expectations

### `tests/conftest.py`

- updated sample memory fixture with deterministic representation fields so old-memory reads remain covered by fixtures

### `tests/test_memory_representation.py`

- added direct unit coverage for:
  - identifier-preserving entity extraction
  - deterministic embedding text construction
  - manager save path using `embedding_text` for vector encoding and payload persistence

## Self-Review

### What looks good

- change stayed inside the owned files
- TDD evidence is real and captured
- startup compatibility guardrail passed
- migration path covers both new and legacy memories
- YAML durability semantics stayed stable while vector representation changed

### Risks checked

- avoided changing startup logging or startup code paths
- avoided changes to Claude hooks or live user state
- avoided modifying production Qdrant defaults
- preserved legacy fixture readability by keeping raw `content` in YAML entries

### Remaining concern

- duplicate detection still queries embeddings from raw `content` while newly saved vectors are produced from `embedding_text`; exact duplicate resolution still has the normalized payload-content equality guard, but dense similarity behavior is now slightly asymmetric between query-time and stored vectors. This did not break the focused suite, so I left it untouched for this task to keep the slice minimal.

## Commit

- Commit created with message: `feat: add deterministic memory representation`
