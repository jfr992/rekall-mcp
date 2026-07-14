"""REST contract: /api/memory/recall accepts task_hint and logs it (spec 2026-07-08)."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):
    fake = MagicMock()
    fake.recall.return_value = [{"memory_id": "m1", "content": "x"}]
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_recall_passes_task_hint_to_manager(client, fake_manager):
    r = client.post(
        "/api/memory/recall",
        json={"query": "rotation", "task_hint": "auth middleware"},
    )
    assert r.status_code == 200
    assert fake_manager.recall.call_args.kwargs["task_hint"] == "auth middleware"


def test_recall_rejects_non_string_task_hint(client, fake_manager):
    r = client.post("/api/memory/recall", json={"query": "q", "task_hint": 42})
    assert r.status_code == 400
    fake_manager.recall.assert_not_called()


def test_recall_truncates_oversized_task_hint(client, fake_manager):
    r = client.post("/api/memory/recall", json={"query": "q", "task_hint": "auth " * 4000})
    assert r.status_code == 200
    assert len(fake_manager.recall.call_args.kwargs["task_hint"]) == 256


def test_rest_recall_emits_exactly_once(client, fake_manager):
    """Emission lives in manager.recall — the REST handler must not add a second."""

    def _recall(*args, **kwargs):
        fake_manager.record_event(
            event_type="memory_recalled", project="general", payload={"query": "q"}
        )
        return [{"memory_id": "m1", "content": "x", "score": 0.9}]

    fake_manager.recall.side_effect = _recall
    r = client.post("/api/memory/recall", json={"query": "q"})
    assert r.status_code == 200
    assert fake_manager.record_event.call_count == 1
