"""Event contract v2: manager-layer emission with enriched payloads (U1 Task 1)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

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


def test_record_event_merges_session_id_into_payload(tmp_path):
    mgr = object.__new__(MemoryManager)
    mgr._event_log = None
    mgr.memory_dir = tmp_path

    mgr.record_event(
        event_type="memory_recalled",
        project="p",
        session_id="sess-42",
        payload={"query": "q"},
    )
    mgr.record_event(event_type="memory_recalled", project="p", payload={"query": "q"})

    events = mgr.event_log.tail(limit=2)
    assert events[0].payload["session_id"] == "sess-42"
    # absent param -> key present and null (old callers stay contract-shaped)
    assert events[1].payload["session_id"] is None


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


@pytest.mark.asyncio
async def test_mcp_recall_tool_rides_on_manager_emission(tool_registry):
    """recall_memories has no emission of its own — manager.recall carries it."""
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider = OptimizedMemoryTools()
    provider._manager = _mgr(HITS)
    provider.register(FakeMCP())

    await registered_tools["recall_memories"](query="auth rotation", limit=3)

    assert provider._manager.record_event.call_count == 1
    assert provider._manager.record_event.call_args.kwargs["event_type"] == "memory_recalled"


@pytest.fixture
def rest_client():
    from starlette.testclient import TestClient

    from server import mcp

    return TestClient(mcp.streamable_http_app())


@pytest.fixture
def fake_rest_manager(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


def test_cross_project_handler_does_not_emit(rest_client, fake_rest_manager):
    """Both inner manager.recall calls emit; the handler must add nothing."""
    fake_rest_manager.recall_cross_project.return_value = {
        "query": "q",
        "current_project": "p",
        "same_project": [{"memory_id": "m1", "content": "x"}],
        "related_projects": [],
        "global": [],
    }
    r = rest_client.post(
        "/api/memory/recall/cross-project", json={"query": "q", "current_project": "p"}
    )
    assert r.status_code == 200
    fake_rest_manager.record_event.assert_not_called()


def test_reflex_handler_does_not_emit(rest_client, fake_rest_manager):
    """manager.recall emits once per cue; the handler must add nothing."""
    fake_rest_manager.reflex.return_value = {
        "cues": ["iac"],
        "memories": [{"memory_id": "m1", "content": "x", "reason": "iac"}],
    }
    r = rest_client.post("/api/memory/reflex", json={"text": "terraform apply"})
    assert r.status_code == 200
    fake_rest_manager.record_event.assert_not_called()


def _real_save_manager(tmp_path, monkeypatch):
    """Real manager against tmp storage, vector/graph legs stubbed (pattern:
    tests/test_memory_events.py::test_manager_records_memory_saved_event)."""
    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = type(
        "Store",
        (),
        {"search": lambda *a, **k: [], "save": lambda *a, **k: None},
    )()
    manager._embedder = type("Embedder", (), {"encode": lambda self, text: [0.1] * 384})()
    manager._knowledge_graph = type(
        "Graph",
        (),
        {"add_node": lambda *a, **k: None, "save": lambda *a, **k: None},
    )()
    monkeypatch.setattr(
        "memory.manager.auto_link",
        lambda **kwargs: type("R", (), {"edges_created": 0, "relations": {}})(),
    )
    return manager


def test_save_stamps_capture_origin_into_memory_saved_event(tmp_path, monkeypatch):
    manager = _real_save_manager(tmp_path, monkeypatch)

    manager.save("Use capsules", type="decision", project="p", capture_origin="cli")
    manager.save("Another memory entirely", type="decision", project="p")

    events = manager.event_log.tail(limit=2)
    assert events[0].payload["capture_origin"] == "cli"
    assert events[1].payload["capture_origin"] == "rest"  # documented default
