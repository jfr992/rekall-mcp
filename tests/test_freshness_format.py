"""Stage A: newest-first rendering + imperative header (spec §Part 1 Stage A).

The 0/18 eval failure: old and new facts render as equal bullets.
Deterministic newest-first + an imperative header is the first ladder rung.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

from memory.manager import MemoryManager


def _fmt(mems):
    # _format_with_guidance is instance-independent of storage; bind it cheaply
    return MemoryManager._format_with_guidance(object.__new__(MemoryManager), mems)


def _make_manager_with_fake_store(search_results: list[dict]) -> MemoryManager:
    """Build a MemoryManager that skips __init__ and stubs out all I/O."""
    mgr = object.__new__(MemoryManager)

    # Embedder stub — set the backing attr, not the property
    embedder = MagicMock()
    embedder.encode.return_value = [0.0] * 384
    mgr._embedder = embedder

    # Graph stub — no nodes/no edges forces the simple no-graph scoring branch
    graph = MagicMock()
    graph.stats.return_value = {"nodes": 0, "edges": 0}
    mgr._knowledge_graph = graph

    # Store stub
    store = MagicMock()
    store.search.return_value = search_results
    mgr._store = store

    # Telemetry stub — must return a context manager
    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry

    return mgr


def test_same_type_renders_newest_first_by_timestamp():
    mems = [
        {
            "content": "billing DB is MySQL 8",
            "type": "fact",
            "date": "2026-03-14",
            "timestamp": "2026-03-14T10:00:00.000001",
            "memory_id": "old",
        },
        {
            "content": "billing DB migrated to CockroachDB",
            "type": "fact",
            "date": "2026-07-01",
            "timestamp": "2026-07-01T09:00:00.000001",
            "memory_id": "new",
        },
    ]
    out = _fmt(mems)
    assert out.index("CockroachDB") < out.index("MySQL")


def test_imperative_header_when_types_repeat():
    mems = [
        {
            "content": "A",
            "type": "fact",
            "date": "2026-07-01",
            "timestamp": "2026-07-01T09:00:00",
            "memory_id": "a",
        },
        {
            "content": "B",
            "type": "fact",
            "date": "2026-03-01",
            "timestamp": "2026-03-01T09:00:00",
            "memory_id": "b",
        },
    ]
    out = _fmt(mems)
    assert "newest is correct" in out


def test_no_header_when_all_types_unique():
    mems = [
        {
            "content": "A",
            "type": "fact",
            "date": "2026-07-01",
            "timestamp": "2026-07-01T09:00:00",
            "memory_id": "a",
        },
        {
            "content": "B",
            "type": "decision",
            "date": "2026-03-01",
            "timestamp": "2026-03-01T09:00:00",
            "memory_id": "b",
        },
    ]
    assert "newest is correct" not in _fmt(mems)


def test_missing_timestamp_falls_back_to_date_and_ties_keep_order():
    mems = [
        {"content": "first-retrieved", "type": "fact", "date": "2026-05-01", "memory_id": "x"},
        {"content": "second-retrieved", "type": "fact", "date": "2026-05-01", "memory_id": "y"},
        {"content": "newer-by-date", "type": "fact", "date": "2026-06-01", "memory_id": "z"},
    ]
    out = _fmt(mems)
    assert out.index("newer-by-date") < out.index("first-retrieved") < out.index("second-retrieved")


def test_recall_result_includes_timestamp():
    mgr = _make_manager_with_fake_store(
        [
            {
                "memory_id": "m1",
                "content": "billing DB is MySQL 8",
                "type": "fact",
                "date": "2026-03-14",
                "timestamp": "2026-03-14T10:00:00.000001",
                "project": "api",
                "score": 0.9,
            }
        ]
    )
    results = mgr.recall("billing database")
    assert results, "expected at least one result"
    assert "timestamp" in results[0], "recall result must carry timestamp for freshness sort"
