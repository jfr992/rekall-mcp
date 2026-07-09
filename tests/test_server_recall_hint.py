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


def test_recall_event_payload_carries_task_hint(client, fake_manager):
    client.post("/api/memory/recall", json={"query": "q", "task_hint": "auth middleware"})
    payload = fake_manager.record_event.call_args.kwargs["payload"]
    assert payload["task_hint"] == "auth middleware"
