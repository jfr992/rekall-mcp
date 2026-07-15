"""POST /api/memory/feedback — labeled recall evidence (U2 Task 2).

Feedback events are EVIDENCE ONLY: nothing reads them into ranking
(weights frozen until the 500-pair gate). The grep-pin test enforces it.
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
    """Ranking weights are frozen: feedback is evidence, never a scoring input."""
    from pathlib import Path

    manager_src = (Path(__file__).parent.parent / "src" / "memory" / "manager.py").read_text()
    assert "memory_feedback" not in manager_src
