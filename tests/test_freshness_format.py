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


def test_detect_groups_same_type_high_sim_only():
    from memory.freshness import detect_conflict_groups

    mems = [
        {"memory_id": "old", "type": "fact"},
        {"memory_id": "new", "type": "fact"},
        {"memory_id": "other", "type": "decision"},
    ]
    v = {"old": [1.0, 0.0], "new": [0.96, 0.28], "other": [1.0, 0.0]}
    groups = detect_conflict_groups(mems, graph=None, vectors=v, theta=0.9)
    assert groups == [{"old", "new"}]


def test_mark_outdated_flags_all_but_newest():
    from memory.freshness import mark_outdated

    mems = [
        {"memory_id": "old", "type": "fact", "timestamp": "2026-03-01T00:00:00"},
        {"memory_id": "new", "type": "fact", "timestamp": "2026-07-01T00:00:00"},
    ]
    mark_outdated(mems, [{"old", "new"}])
    assert mems[0].get("_outdated") is True and "_outdated" not in mems[1]


def test_recall_annotates_outdated_on_conflict_pair():
    """recall() sets _outdated on older member of a detected conflict group."""
    mems = [
        {
            "memory_id": "old",
            "content": "pinned to Terraform 1.4.x",
            "type": "decision",
            "date": "2026-03-01",
            "timestamp": "2026-03-01T00:00:00",
            "project": "api",
            "score": 0.95,
        },
        {
            "memory_id": "new",
            "content": "upgraded pin to Terraform 1.9.4",
            "type": "decision",
            "date": "2026-07-01",
            "timestamp": "2026-07-01T00:00:00",
            "project": "api",
            "score": 0.92,
        },
    ]
    mgr = _make_manager_with_fake_store(mems)
    # Two unit-norm vectors with cosine >= 0.9 (both decision type → will group)
    mgr._store.get_many.return_value = [
        {"memory_id": "old", "_vector": [1.0] + [0.0] * 383},
        {"memory_id": "new", "_vector": [0.96, 0.28] + [0.0] * 382},
    ]

    results = mgr.recall("terraform version")
    by_id = {r["memory_id"]: r for r in results}
    assert by_id["old"].get("_outdated") is True, "older member must be flagged"
    assert "_outdated" not in by_id["new"], "newer member must not be flagged"


def test_detect_groups_via_supersedes_edge_without_cosine():
    """Graph-edge path: a supersedes edge unions a same-type pair even when
    vectors are absent (no cosine hit possible). A led_to edge must NOT union."""
    import networkx as nx

    from memory.freshness import detect_conflict_groups

    class FakeGraph:
        def __init__(self):
            self._graph = nx.DiGraph()

    g = FakeGraph()
    g._graph.add_edge("new", "old", relation="supersedes")
    g._graph.add_edge("new", "other", relation="led_to")
    mems = [
        {"memory_id": "old", "type": "fact"},
        {"memory_id": "new", "type": "fact"},
        {"memory_id": "other", "type": "fact"},
    ]
    groups = detect_conflict_groups(mems, graph=g, vectors=None)
    assert groups == [{"old", "new"}]


def test_outdated_label_rendered():
    mems = [
        {
            "content": "pinned to Terraform 1.4.x",
            "type": "decision",
            "date": "2026-03-01",
            "timestamp": "2026-03-01T00:00:00",
            "memory_id": "old",
            "_outdated": True,
        },
        {
            "content": "upgraded pin to Terraform 1.9.4",
            "type": "decision",
            "date": "2026-07-01",
            "timestamp": "2026-07-01T00:00:00",
            "memory_id": "new",
        },
    ]
    out = _fmt(mems)
    assert "[OUTDATED — the entry above replaces this] pinned to Terraform 1.4.x" in out
