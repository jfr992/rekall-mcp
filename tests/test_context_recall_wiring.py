"""task_hint wiring: fails-soft identity + promotion through recall (spec 2026-07-08)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from memory.manager import MemoryManager

HITS = [
    {
        "memory_id": f"m{i}",
        "content": f"note {i}",
        "score": 0.9 - i * 0.05,
        "date": "2026-07-01",
        "type": "fact",
        "project": "p",
        "timestamp": f"2026-07-01T0{i}:00:00",
    }
    for i in range(8)
]


def _mgr(hits):
    mgr = object.__new__(MemoryManager)
    mgr._store = MagicMock()
    mgr._store.search.return_value = [dict(h) for h in hits]
    mgr._store.get_many.return_value = []
    mgr._knowledge_graph = MagicMock()
    mgr._knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    mgr._embedder = MagicMock()
    mgr._embedder.encode.return_value = [0.0] * 384
    mgr.record_event = MagicMock()

    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry
    return mgr


def test_recall_with_hint_promotes_matching_memory():
    hits = [dict(h) for h in HITS]
    hits[6]["content"] = "auth middleware rotation decision"
    out = MemoryManager.recall(_mgr(hits), "q", limit=5, task_hint="auth middleware")
    ids = [m["memory_id"] for m in out]
    assert "m6" in ids
    assert out[ids.index("m6")].get("_context_matched") is True


def test_recall_without_hint_is_byte_identical():
    baseline = MemoryManager.recall(_mgr(HITS), "q", limit=5)
    with_none = MemoryManager.recall(_mgr(HITS), "q", limit=5, task_hint=None)
    assert [m["memory_id"] for m in baseline] == [m["memory_id"] for m in with_none]
    assert not any("_context_matched" in m for m in with_none)


def test_recall_formatted_passes_task_hint_through():
    hits = [dict(h) for h in HITS]
    hits[6]["content"] = "auth middleware rotation decision"
    out = MemoryManager.recall_formatted(
        _mgr(hits), "q", limit=5, task_hint="auth middleware"
    )
    assert "auth middleware rotation decision" in out


def test_recall_single_token_hint_is_ignored():
    hits = [dict(h) for h in HITS]
    hits[7]["content"] = "auth middleware rotation decision"
    out = MemoryManager.recall(_mgr(hits), "q", limit=5, task_hint="auth")
    assert [m["memory_id"] for m in out] == [f"m{i}" for i in range(5)]
