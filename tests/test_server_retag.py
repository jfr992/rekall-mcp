"""PATCH /api/memory/{id} — retag project and/or memory type."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    manager = MagicMock()
    import server

    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_patch_project_calls_manager_and_returns_200(client):
    tc, manager = client
    manager.retag_memory.return_value = {
        "memory_id": "2026-07-10_decision_aaaa",
        "project": "veril-clips",
        "type": "decision",
    }

    r = tc.patch(
        "/api/memory/2026-07-10_decision_aaaa",
        json={"project": "veril-clips"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["memory_id"] == "2026-07-10_decision_aaaa"
    assert body["project"] == "veril-clips"
    manager.retag_memory.assert_called_once_with(
        "2026-07-10_decision_aaaa",
        project="veril-clips",
        memory_type=None,
    )


def test_patch_memory_type_validated(client):
    tc, manager = client
    manager.retag_memory.return_value = {
        "memory_id": "2026-07-10_decision_aaaa",
        "project": "my-app",
        "type": "fact",
    }

    r = tc.patch(
        "/api/memory/2026-07-10_decision_aaaa",
        json={"memory_type": "fact"},
    )

    assert r.status_code == 200
    assert r.json()["type"] == "fact"
    manager.retag_memory.assert_called_once_with(
        "2026-07-10_decision_aaaa",
        project=None,
        memory_type="fact",
    )


def test_patch_invalid_memory_type_returns_400(client):
    tc, manager = client

    r = tc.patch(
        "/api/memory/2026-07-10_decision_aaaa",
        json={"memory_type": "project"},
    )

    assert r.status_code == 400
    manager.retag_memory.assert_not_called()


def test_patch_empty_body_returns_400(client):
    tc, manager = client

    r = tc.patch("/api/memory/2026-07-10_decision_aaaa", json={})

    assert r.status_code == 400
    manager.retag_memory.assert_not_called()


def test_patch_unknown_memory_returns_404(client):
    tc, manager = client
    manager.retag_memory.return_value = None

    r = tc.patch(
        "/api/memory/2026-07-10_decision_missing",
        json={"project": "veril-clips"},
    )

    assert r.status_code == 404


def test_patch_cross_origin_mutation_rejected_by_browser_guard(monkeypatch):
    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.retag_memory.return_value = {"memory_id": "2026-07-10_decision_aaaa"}
    monkeypatch.setattr("memory.singleton._instance", manager)

    tc = TestClient(server.build_app())
    r = tc.patch(
        "/api/memory/2026-07-10_decision_aaaa",
        content='{"project": "veril-clips"}',
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403
