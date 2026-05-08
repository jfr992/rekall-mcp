"""Fix I4 — existing memories without a tier field must get one via backfill."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def manager_with_legacy_memories(tmp_path):
    from memory.manager import MemoryManager

    legacy_memories = [
        {"memory_id": "m1", "type": "note", "content": "a", "date": "2026-01-01", "salience": 0.3},
        {"memory_id": "m2", "type": "decision", "content": "b", "date": "2026-02-01", "salience": 0.8},
        {"memory_id": "m3", "type": "preference", "content": "c", "date": "2026-03-01", "salience": 0.5},
    ]

    with patch("memory.manager.VectorStore") as store_class, \
         patch("memory.manager.Embedder") as embedder_class:
        store = MagicMock()
        embedder = MagicMock()
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        store.count.return_value = len(legacy_memories)

        # scroll returns the legacy memories in one batch
        def scroll_side_effect(filters=None, limit=500, **kwargs):
            return list(legacy_memories)
        store.scroll.side_effect = scroll_side_effect

        store_class.return_value = store
        embedder_class.return_value = embedder

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_url="http://localhost:6333")
        mgr._store = store
        mgr._embedder = embedder
        # Ensure graph has no contradicts for clean tier computation
        mgr.knowledge_graph.stats = MagicMock(return_value={"nodes": 0, "edges": 0})
        mgr.knowledge_graph.count_contradicts = MagicMock(return_value=0)
        yield mgr, legacy_memories


def test_backfill_populates_tier_on_all_legacy_memories(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    report = mgr.backfill_lifecycle(dry_run=False)

    assert sum(report["updated_by_tier"].values()) == 3
    # note (age > 7 days, no reinforcement, salience 0.3) -> working
    # decision + salience 0.8 -> semantic (Rule 3)
    # preference -> semantic (identity is explicit-only)
    assert report["updated_by_tier"]["working"] == 1
    assert report["updated_by_tier"]["semantic"] == 2
    # update_payload must be called once per memory
    assert mgr._store.update_payload.call_count == 3


def test_backfill_dry_run_does_not_write(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    report = mgr.backfill_lifecycle(dry_run=True)

    assert sum(report["updated_by_tier"].values()) == 3
    assert mgr._store.update_payload.call_count == 0


def test_backfill_respects_project_filter(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    mgr.backfill_lifecycle(dry_run=True, project="test-project")

    # scroll was called with the project filter
    mgr._store.scroll.assert_called()
    args, kwargs = mgr._store.scroll.call_args
    filters = kwargs.get("filters") or (args[0] if args else None)
    assert filters == {"project": "test-project"}


def test_backfill_report_has_required_fields(manager_with_legacy_memories):
    mgr, _ = manager_with_legacy_memories
    report = mgr.backfill_lifecycle(dry_run=True)

    assert "dry_run" in report
    assert "updated_by_tier" in report
    assert "skipped" in report
    assert "errors" in report
    assert "total" in report
    assert report["dry_run"] is True
    assert report["total"] == 3
