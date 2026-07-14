"""Event contract v2: manager-layer emission with enriched payloads (U1 Task 1)."""

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


def test_recall_emits_one_memory_recalled_with_query_scores_tokens():
    mgr = _mgr(HITS)
    out = MemoryManager.recall(mgr, "auth rotation", limit=5, task_hint="auth middleware")

    assert mgr.record_event.call_count == 1
    kwargs = mgr.record_event.call_args.kwargs
    assert kwargs["event_type"] == "memory_recalled"
    assert kwargs["memory_ids"] == [m["memory_id"] for m in out]

    payload = kwargs["payload"]
    assert payload["query"] == "auth rotation"
    assert payload["task_hint"] == "auth middleware"
    assert payload["memories"] == [
        {"memory_id": m["memory_id"], "score": m["score"]} for m in out
    ]
    assert payload["token_estimate"] == sum(len(m["content"]) // 4 for m in out)
    assert payload["session_id"] is None
    assert payload["capture_origin"] is None
