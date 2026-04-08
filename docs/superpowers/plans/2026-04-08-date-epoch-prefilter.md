# Date Epoch Pre-Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `days` filter in `recall_memories()` to use Qdrant Range pre-filter instead of post-retrieval string comparison, ensuring temporal queries return complete results.

**Architecture:** Add `date_epoch` (unix timestamp integer) to every Qdrant point payload. Create an integer index on it. Use `Range(gte=cutoff_epoch)` in Qdrant queries so the vector search only considers memories within the date range. Backfill existing points.

**Tech Stack:** Python, Qdrant, pytest

---

### Task 1: Add `date_epoch` integer index to VectorStore

**Files:**
- Modify: `src/core/vector_store.py:143-160` (add `create_index` call for integer type)
- Test: `tests/test_vector_store_index.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_vector_store_index.py`:

```python
"""Tests for VectorStore index creation."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_telemetry():
    from core.telemetry import Telemetry
    Telemetry.reset()
    yield
    Telemetry.reset()


def test_create_index_supports_integer_type():
    """create_index should pass 'integer' field_type to Qdrant."""
    with patch("core.vector_store.QdrantClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="memories")]
        )

        from core.vector_store import VectorStore

        store = VectorStore(collection="memories")
        store.create_index("date_epoch", field_type="integer")

        mock_client.create_payload_index.assert_called_once_with(
            collection_name="memories",
            field_name="date_epoch",
            field_schema="integer",
        )
```

- [ ] **Step 2: Run test to verify it passes (existing code already supports this)**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_vector_store_index.py -v`

Expected: PASS — `create_index` already accepts `field_type` parameter and passes it through. This test locks in the behavior.

- [ ] **Step 3: Commit**

```bash
git add tests/test_vector_store_index.py
git commit -m "test: add test for integer index creation in VectorStore"
```

---

### Task 2: Add `date_epoch` to memory save payload

**Files:**
- Modify: `src/memory/manager.py:250-259` (add `date_epoch` to payload dict)
- Test: `tests/test_memory.py` (add test to existing save tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py` inside the `TestSave` class (after `test_save_different_types`):

```python
def test_save_includes_date_epoch_in_payload(self, memory_manager, mock_store):
    """Saved memories should include date_epoch as unix timestamp integer."""
    memory_manager.save("Test content", type="fact")

    call_args = mock_store.save.call_args
    payload = call_args.kwargs.get("payload") or call_args[1].get("payload")

    assert "date_epoch" in payload
    assert isinstance(payload["date_epoch"], int)
    # date_epoch should be within last minute (not some arbitrary value)
    import time
    now = int(time.time())
    assert now - 86400 < payload["date_epoch"] <= now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestSave::test_save_includes_date_epoch_in_payload -v`

Expected: FAIL with `KeyError: 'date_epoch'`

- [ ] **Step 3: Write minimal implementation**

In `src/memory/manager.py`, modify the payload dict at line 250-259. Add `date_epoch` after `date`:

```python
# Build payload
date_epoch = int(datetime.strptime(date, "%Y-%m-%d").timestamp())
payload = {
    "memory_id": memory_id,
    "content": content,
    "date": date,
    "date_epoch": date_epoch,
    "timestamp": timestamp,
    "type": type,
    "project": project or "general",
    **metadata,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestSave::test_save_includes_date_epoch_in_payload -v`

Expected: PASS

- [ ] **Step 5: Run all save tests to check for regressions**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestSave -v`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/memory/manager.py tests/test_memory.py
git commit -m "feat: add date_epoch integer field to memory save payload"
```

---

### Task 3: Use `date_epoch` Range pre-filter in recall

**Files:**
- Modify: `src/memory/manager.py:527-644` (replace post-filter with pre-filter)
- Test: `tests/test_memory.py` (add test to existing recall tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py` inside the `TestRecall` class:

```python
def test_recall_passes_date_epoch_range_filter_to_store(self, memory_manager, mock_store):
    """When days_back is set, recall should pass a date_epoch Range filter to the store."""
    mock_store.search.return_value = []

    memory_manager.recall("test query", days_back=7)

    call_args = mock_store.search.call_args
    filters = call_args.kwargs.get("filters") or call_args[1].get("filters")

    assert "date_epoch" in filters
    assert isinstance(filters["date_epoch"], dict)
    assert "gte" in filters["date_epoch"]
    assert isinstance(filters["date_epoch"]["gte"], int)

    # Cutoff should be roughly 7 days ago
    import time
    expected_cutoff = int(time.time()) - (7 * 86400)
    actual_cutoff = filters["date_epoch"]["gte"]
    assert abs(actual_cutoff - expected_cutoff) < 120  # within 2 minutes


def test_recall_no_date_filter_without_days_back(self, memory_manager, mock_store):
    """When days_back is not set, no date_epoch filter should be passed."""
    mock_store.search.return_value = []

    memory_manager.recall("test query")

    call_args = mock_store.search.call_args
    filters = call_args.kwargs.get("filters") or call_args[1].get("filters")

    assert filters is None or "date_epoch" not in (filters or {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestRecall::test_recall_passes_date_epoch_range_filter_to_store tests/test_memory.py::TestRecall::test_recall_no_date_filter_without_days_back -v`

Expected: FAIL — `date_epoch` not in filters

- [ ] **Step 3: Write minimal implementation**

In `src/memory/manager.py`, modify the `recall()` method. Replace lines 534-540:

```python
# Date filtering: use Qdrant Range pre-filter on date_epoch
if days_back:
    cutoff_epoch = int((datetime.now() - timedelta(days=days_back)).timestamp())
    filters["date_epoch"] = {"gte": cutoff_epoch}
```

And remove the post-retrieval filter at lines 640-642:

```python
# REMOVE these lines:
# if cutoff_date:
#     scored = [r for r in scored if (r.get("date") or "") >= cutoff_date]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestRecall::test_recall_passes_date_epoch_range_filter_to_store tests/test_memory.py::TestRecall::test_recall_no_date_filter_without_days_back -v`

Expected: PASS

- [ ] **Step 5: Run all recall tests to check for regressions**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestRecall -v`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/memory/manager.py tests/test_memory.py
git commit -m "feat: use date_epoch Range pre-filter in recall instead of post-filter"
```

---

### Task 4: Update server `_parse_graph_filters` to use `date_epoch`

**Files:**
- Modify: `src/server.py:244-262` (`_parse_graph_filters`)
- Modify: `src/server.py:552-557` (remove post-filter in graph endpoint)
- Test: `tests/test_server_memory_graph.py:22-46` (update existing tests)

- [ ] **Step 1: Update the existing tests**

In `tests/test_server_memory_graph.py`, replace the two existing filter tests:

```python
def test_parse_graph_filters_includes_expected_fields():
    """Graph filters should include project/type and date_epoch range."""
    from server import _parse_graph_filters

    query = QueryParams({"project": "api", "type": "decision", "days": "7"})

    filters = _parse_graph_filters(query)

    assert filters["project"] == "api"
    assert filters["type"] == "decision"
    assert "date_epoch" in filters
    assert isinstance(filters["date_epoch"], dict)
    assert "gte" in filters["date_epoch"]
    assert isinstance(filters["date_epoch"]["gte"], int)

    import time
    expected_cutoff = int(time.time()) - (7 * 86400)
    assert abs(filters["date_epoch"]["gte"] - expected_cutoff) < 120


def test_parse_graph_filters_without_days_has_no_date_filter():
    """Date filter should be omitted when days is not provided."""
    from server import _parse_graph_filters

    filters = _parse_graph_filters(QueryParams({"project": "api"}))

    assert filters["project"] == "api"
    assert "date_epoch" not in filters
    assert "_cutoff_date" not in filters
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_server_memory_graph.py::test_parse_graph_filters_includes_expected_fields tests/test_server_memory_graph.py::test_parse_graph_filters_without_days_has_no_date_filter -v`

Expected: FAIL — `_cutoff_date` still in filters, `date_epoch` missing

- [ ] **Step 3: Write minimal implementation**

In `src/server.py`, replace `_parse_graph_filters` (lines 244-262):

```python
def _parse_graph_filters(query_params) -> dict[str, Any]:
    filters: dict[str, Any] = {}

    project = query_params.get("project")
    if project:
        filters["project"] = project

    mem_type = query_params.get("type")
    if mem_type:
        filters["type"] = mem_type

    days = query_params.get("days")
    if days:
        cutoff_epoch = int((datetime.now() - timedelta(days=int(days))).timestamp())
        filters["date_epoch"] = {"gte": cutoff_epoch}

    return filters
```

Add `Any` to the imports at the top of `server.py` if not already present:

```python
from typing import Any
```

- [ ] **Step 4: Remove post-filter in graph endpoint**

In `src/server.py`, at the `/api/memory/graph` endpoint (around line 552), remove:

```python
# REMOVE these lines:
# cutoff_date = filters.pop("_cutoff_date", None)
# ...
# if cutoff_date:
#     points = [p for p in points if (p.get("date") or "") >= cutoff_date]
```

The `filters` dict now goes directly to `store.scroll()` with `date_epoch` Range filter handled by `_build_filter`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_server_memory_graph.py -v`

Expected: All PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -v --timeout=30`

Expected: All PASS (some may skip if Docker/Qdrant unavailable)

- [ ] **Step 7: Commit**

```bash
git add src/server.py tests/test_server_memory_graph.py
git commit -m "feat: use date_epoch Range filter in server graph endpoint"
```

---

### Task 5: Backfill migration for existing Qdrant points

**Files:**
- Modify: `src/memory/manager.py` (add `backfill_date_epoch` method)
- Modify: `src/server.py` (expose via existing rebuild endpoint or new endpoint)
- Test: `tests/test_memory.py` (add migration test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
class TestBackfillDateEpoch:
    """Tests for the date_epoch backfill migration."""

    def test_backfill_adds_date_epoch_to_points(self, memory_manager, mock_store):
        """Backfill should set date_epoch on all points missing it."""
        mock_store.scroll.return_value = [
            {"memory_id": "2026-04-01_fact_abc", "date": "2026-04-01", "content": "old memory"},
            {"memory_id": "2026-04-08_fact_def", "date": "2026-04-08", "content": "new memory"},
        ]

        count = memory_manager.backfill_date_epoch()

        assert count == 2
        assert mock_store.client.set_payload.call_count == 2

        # Verify first call payload
        first_call = mock_store.client.set_payload.call_args_list[0]
        payload = first_call.kwargs.get("payload") or first_call[1].get("payload")
        assert "date_epoch" in payload
        assert isinstance(payload["date_epoch"], int)

    def test_backfill_skips_points_with_date_epoch(self, memory_manager, mock_store):
        """Backfill should skip points that already have date_epoch."""
        mock_store.scroll.return_value = [
            {"memory_id": "2026-04-01_fact_abc", "date": "2026-04-01", "date_epoch": 1743465600},
        ]

        count = memory_manager.backfill_date_epoch()

        assert count == 0
        mock_store.client.set_payload.assert_not_called()

    def test_backfill_handles_missing_date_field(self, memory_manager, mock_store):
        """Backfill should skip points with no date field."""
        mock_store.scroll.return_value = [
            {"memory_id": "unknown_fact_abc", "content": "no date"},
        ]

        count = memory_manager.backfill_date_epoch()

        assert count == 0
        mock_store.client.set_payload.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestBackfillDateEpoch -v`

Expected: FAIL — `backfill_date_epoch` method doesn't exist

- [ ] **Step 3: Write minimal implementation**

Add to `src/memory/manager.py` in the `MemoryManager` class (after the `cleanup` method):

```python
def backfill_date_epoch(self) -> int:
    """Add date_epoch field to all existing Qdrant points missing it.

    One-time migration. Safe to run multiple times — skips points
    that already have date_epoch.

    Returns:
        Number of points updated
    """
    from core.utils import stable_hash_id

    points = self.store.scroll(limit=10000)
    updated = 0

    for point in points:
        # Skip if already has date_epoch
        if point.get("date_epoch"):
            continue

        date_str = point.get("date")
        if not date_str:
            continue

        memory_id = point.get("memory_id")
        if not memory_id:
            continue

        try:
            date_epoch = int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())
        except ValueError:
            continue

        point_id = stable_hash_id(memory_id)
        self.store.client.set_payload(
            collection_name=self.store.collection,
            payload={"date_epoch": date_epoch},
            points=[point_id],
        )
        updated += 1

    # Create integer index if it doesn't exist (idempotent)
    try:
        self.store.create_index("date_epoch", field_type="integer")
    except Exception:
        pass  # Index may already exist

    logger.info(f"Backfilled date_epoch on {updated} points")
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_memory.py::TestBackfillDateEpoch -v`

Expected: PASS

- [ ] **Step 5: Wire into rebuild endpoint**

In `src/server.py`, find the `/api/memory/graph/rebuild` endpoint. Add `backfill_date_epoch()` call after the graph rebuild:

```python
# After existing rebuild logic:
backfill_count = manager.backfill_date_epoch()
```

Include `backfill_count` in the response JSON.

- [ ] **Step 6: Commit**

```bash
git add src/memory/manager.py src/server.py tests/test_memory.py
git commit -m "feat: add date_epoch backfill migration, wire into rebuild endpoint"
```

---

### Task 6: Create `date_epoch` index on VectorStore init

**Files:**
- Modify: `src/memory/manager.py` (add index creation in `__init__` or lazy init)

- [ ] **Step 1: Add index creation after store initialization**

In `src/memory/manager.py`, in the `MemoryManager.__init__` or the property that initializes the store, add:

```python
# Create date_epoch index (idempotent — Qdrant ignores if exists)
try:
    self.store.create_index("date_epoch", field_type="integer")
except Exception:
    pass  # Index may already exist, or Qdrant not yet available
```

Place this after the existing index creation calls (search for `create_index` in the file to find the pattern).

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -v --timeout=30`

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/memory/manager.py
git commit -m "feat: create date_epoch integer index on VectorStore init"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -v --timeout=30`

Expected: All PASS

- [ ] **Step 2: Manual smoke test (if Qdrant available)**

```bash
# Start the server
docker compose up -d

# Save a memory
curl -X POST http://localhost:8000/api/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "Test date_epoch filter", "type": "fact"}'

# Recall with days=1 — should return the memory
curl -X POST http://localhost:8000/api/memory/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "anything unrelated to the content", "days": 1}'

# Recall with days=0 — should return nothing (or only today)
# Verify the memory appears in days=1 but NOT in a search without days
# where the query is semantically distant
```

- [ ] **Step 3: Run backfill on existing data**

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

Verify response includes `backfill_count`.

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address any issues found during verification"
```
