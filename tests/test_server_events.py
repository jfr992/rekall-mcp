"""Tests for POST /api/memory/events endpoint.

Handler-level emission tests moved with the emissions themselves:
manager/builder-layer contract lives in tests/test_event_contract.py,
handler no-double-emit pins in test_event_contract.py and
tests/test_server_recall_hint.py (event contract v2).
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    manager = MagicMock()
    manager.record_event.return_value = None
    import server

    monkeypatch.setattr("memory.singleton._instance", manager)
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
