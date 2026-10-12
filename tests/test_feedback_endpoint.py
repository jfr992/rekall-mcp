"""POST /api/memory/feedback — one-click recall verdicts (U2 Task 2).

The endpoint records a memory_feedback event and runs the reinforce pass:
wrong disputes, useful credits, stale queues a supersede review. Ranking
weights never read the event (grep-pinned below).
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.store.get_many.return_value = [{"memory_id": "mem-1", "project": "proj-a"}]
    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_post_feedback_records_memory_feedback_event(client):
    tc, manager = client

    r = tc.post(
        "/api/memory/feedback",
        json={"memory_id": "mem-1", "verdict": "useful", "session_id": "sess-9"},
    )

    assert r.status_code == 200
    assert r.json() == {"recorded": True}
    manager.store.get_many.assert_called_once_with(["mem-1"])
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "memory_feedback"
    assert kw["project"] == "proj-a"  # sourced from the get_many hit, not the caller
    assert kw["memory_ids"] == ["mem-1"]
    assert kw["session_id"] == "sess-9"
    assert kw["payload"] == {"verdict": "useful", "editor": "ui"}


def test_post_feedback_unknown_memory_404(client):
    tc, manager = client
    manager.store.get_many.return_value = []

    r = tc.post("/api/memory/feedback", json={"memory_id": "ghost", "verdict": "useful"})

    assert r.status_code == 404
    assert r.json()["memory_id"] == "ghost"
    manager.record_event.assert_not_called()


def test_post_feedback_bad_verdict_400(client):
    tc, manager = client

    r = tc.post("/api/memory/feedback", json={"memory_id": "mem-1", "verdict": "meh"})

    assert r.status_code == 400
    assert "verdict" in r.json()["error"]
    manager.record_event.assert_not_called()


def test_grep_pin_nothing_in_manager_reads_memory_feedback():
    """Feedback acts through the reinforce pass only; manager ranking never reads it."""
    from pathlib import Path

    manager_src = (Path(__file__).parent.parent / "src" / "memory" / "manager.py").read_text()
    assert "memory_feedback" not in manager_src


def test_endpoint_event_round_trips_into_dispute_credit(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    import server
    from memory.events import EventLog
    from memory.manager import MemoryManager
    from memory.reinforce import credit_from_feedback

    mgr = MagicMock()
    mgr.store.get_many.return_value = [{"memory_id": "m1", "project": "p"}]
    log = EventLog(tmp_path / "_events.jsonl")
    holder = type("Holder", (), {"event_log": log})()
    mgr.record_event.side_effect = lambda **kw: MemoryManager.record_event(holder, **kw)
    monkeypatch.setattr("memory.singleton._instance", mgr)

    TestClient(server.mcp.streamable_http_app()).post(
        "/api/memory/feedback", json={"memory_id": "m1", "verdict": "wrong"}
    )

    credit = credit_from_feedback(log.tail(1)[0])
    assert credit is not None and credit.disputed


def test_feedback_runs_reinforce_pass_after_event(client, monkeypatch):
    tc, manager = client
    monkeypatch.setenv("REKALL_REINFORCE", "1")
    order = []
    manager.record_event.side_effect = lambda **kw: order.append("event")
    monkeypatch.setattr("server._run_reinforce_pass", lambda m: order.append("reinforce"))

    r = tc.post("/api/memory/feedback", json={"memory_id": "mem-1", "verdict": "wrong"})

    assert r.status_code == 200
    assert order == ["event", "reinforce"]


def test_feedback_skips_reinforce_when_disabled(client, monkeypatch):
    tc, _ = client
    monkeypatch.setenv("REKALL_REINFORCE", "0")
    called = []
    monkeypatch.setattr("server._run_reinforce_pass", lambda m: called.append(1))

    assert (
        tc.post("/api/memory/feedback", json={"memory_id": "mem-1", "verdict": "wrong"}).status_code
        == 200
    )
    assert called == []


def test_feedback_reinforce_failure_still_200(client, monkeypatch):
    tc, _ = client
    monkeypatch.setenv("REKALL_REINFORCE", "1")

    def boom(*a, **k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("memory.reinforce.process_events", boom)

    r = tc.post("/api/memory/feedback", json={"memory_id": "mem-1", "verdict": "wrong"})

    assert r.status_code == 200
