"""Tests for server-side event emission and POST /api/memory/events endpoint."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class FakeJSON:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


@pytest.mark.asyncio
async def test_recall_handler_emits_memory_recalled(monkeypatch):
    from server import api_recall_memories

    manager = MagicMock()
    manager.recall.return_value = [
        {"memory_id": "id-1", "content": "foo"},
        {"memory_id": "id-2", "content": "bar"},
    ]
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = FakeJSON({"query": "test query", "project": "my-proj"})
    response = await api_recall_memories(request)

    assert response.status_code == 200
    manager.record_event.assert_called_once()
    call_kwargs = manager.record_event.call_args.kwargs
    assert call_kwargs["event_type"] == "memory_recalled"
    assert call_kwargs["source"] == "recall"
    assert set(call_kwargs["memory_ids"]) == {"id-1", "id-2"}


@pytest.mark.asyncio
async def test_capsule_handler_emits_memory_surfaced(monkeypatch):
    from server import api_project_capsule

    class QueryParams:
        def __init__(self, v):
            self._v = v

        def get(self, k, d=None):
            return self._v.get(k, d)

    manager = MagicMock()
    manager.get_project_capsule.return_value = {
        "project": "my-proj",
        "standing_context": [{"memory_id": "sc-1"}, {"memory_id": "sc-2"}],
        "danger_zones": [{"memory_id": "dz-1"}],
        "open_loops": [],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({"project": "my-proj"}))
    response = await api_project_capsule(request)

    assert response.status_code == 200
    manager.record_event.assert_called_once()
    call_kwargs = manager.record_event.call_args.kwargs
    assert call_kwargs["event_type"] == "memory_surfaced"
    assert call_kwargs["source"] == "capsule"
    assert set(call_kwargs["memory_ids"]) == {"sc-1", "sc-2", "dz-1"}


@pytest.mark.asyncio
async def test_reflex_handler_emits_memory_recalled(monkeypatch):
    from server import api_memory_reflex

    manager = MagicMock()
    manager.reflex.return_value = {
        "text": "deploy",
        "project": "my-proj",
        "cues": ["danger"],
        "memories": [{"memory_id": "r-1"}, {"memory_id": "r-2"}],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = FakeJSON({"text": "deploy prod", "project": "my-proj"})
    response = await api_memory_reflex(request)

    assert response.status_code == 200
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "memory_recalled"
    assert kw["source"] == "reflex"
    assert set(kw["memory_ids"]) == {"r-1", "r-2"}


@pytest.mark.asyncio
async def test_event_log_failure_does_not_fail_recall(monkeypatch):
    from server import api_recall_memories

    manager = MagicMock()
    manager.recall.return_value = [{"memory_id": "id-1"}]
    manager.record_event.side_effect = RuntimeError("event log broken")
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = FakeJSON({"query": "something"})
    response = await api_recall_memories(request)

    # Recall must succeed even when event emission explodes
    assert response.status_code == 200
    data = json.loads(response.body)
    assert data["count"] == 1


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    manager = MagicMock()
    manager.record_event.return_value = None
    import server

    monkeypatch.setattr(server, "_memory_manager_instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_post_events_valid_session_summary(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": ["id-1", "id-2"],
            "edits_after_recall": 3,
            "test_passes_after_recall": 5,
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "session_summary"
    assert kw["memory_ids"] == ["id-1", "id-2"]


def test_post_events_bad_kind_returns_400(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "unknown_kind",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": [],
            "edits_after_recall": 0,
            "test_passes_after_recall": 0,
        },
    )
    assert r.status_code == 400
    manager.record_event.assert_not_called()


def test_post_events_negative_int_returns_400(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": [],
            "edits_after_recall": -1,
            "test_passes_after_recall": 0,
        },
    )
    assert r.status_code == 400
    manager.record_event.assert_not_called()


def test_post_events_bool_edits_returns_400(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": [],
            "edits_after_recall": True,
            "test_passes_after_recall": 0,
        },
    )
    assert r.status_code == 400
    manager.record_event.assert_not_called()


def test_post_events_bool_test_passes_returns_400(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "recalled_ids": [],
            "edits_after_recall": 0,
            "test_passes_after_recall": True,
        },
    )
    assert r.status_code == 400
    manager.record_event.assert_not_called()


@pytest.mark.asyncio
async def test_startup_handler_emits_memory_surfaced(monkeypatch):
    from server import api_agent_startup

    class QueryParams:
        def __init__(self, v):
            self._v = v

        def get(self, k, d=None):
            return self._v.get(k, d)

    manager = MagicMock()
    manager.get_agent_startup.return_value = {
        "project": "my-proj",
        "project_capsule": {
            "standing_context": [{"memory_id": "sc-1"}, {"memory_id": "sc-2"}],
            "danger_zones": [{"memory_id": "dz-1"}],
            "open_loops": [],
        },
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = SimpleNamespace(query_params=QueryParams({"project": "my-proj"}))
    response = await api_agent_startup(request)

    assert response.status_code == 200
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "memory_surfaced"
    assert kw["source"] == "startup"
    assert set(kw["memory_ids"]) == {"sc-1", "sc-2", "dz-1"}


@pytest.mark.asyncio
async def test_cross_project_handler_emits_memory_recalled(monkeypatch):
    from server import api_cross_project_recall

    manager = MagicMock()
    manager.recall_cross_project.return_value = {
        "same_project": [{"memory_id": "sp-1"}, {"memory_id": "sp-2"}],
        "related_projects": [{"memory_id": "rp-1"}],
        "global": [{"memory_id": "gl-1"}],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    request = FakeJSON({"query": "test query", "current_project": "my-proj"})
    response = await api_cross_project_recall(request)

    assert response.status_code == 200
    manager.record_event.assert_called_once()
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "memory_recalled"
    assert kw["source"] == "cross_project"
    assert set(kw["memory_ids"]) == {"sp-1", "sp-2", "rp-1", "gl-1"}
