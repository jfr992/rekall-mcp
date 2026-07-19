"""POST /api/memory/{id}/pin — REST contract for identity pinning (T4).

Browser-guard covered mutation (same rules as DELETE): mirrors
tests/test_server_events.py's manager-mock client idiom.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient

    manager = MagicMock()
    import server

    monkeypatch.setattr("memory.singleton._instance", manager)
    return TestClient(server.mcp.streamable_http_app()), manager


def test_pin_true_calls_manager_and_returns_200(client):
    tc, manager = client
    manager.set_identity_pin.return_value = True

    r = tc.post("/api/memory/2026-07-10_note_aaaa/pin", json={"pinned": True})

    assert r.status_code == 200
    assert r.json() == {"memory_id": "2026-07-10_note_aaaa", "pinned": True}
    manager.set_identity_pin.assert_called_once_with("2026-07-10_note_aaaa", pinned=True)


def test_pin_unknown_memory_id_returns_404(client):
    tc, manager = client
    manager.set_identity_pin.return_value = False

    r = tc.post("/api/memory/2026-07-10_note_unknown/pin", json={"pinned": True})

    assert r.status_code == 404


def test_pin_false_unpins(client):
    tc, manager = client
    manager.set_identity_pin.return_value = True

    r = tc.post("/api/memory/2026-07-10_note_aaaa/pin", json={"pinned": False})

    assert r.status_code == 200
    assert r.json() == {"memory_id": "2026-07-10_note_aaaa", "pinned": False}
    manager.set_identity_pin.assert_called_once_with("2026-07-10_note_aaaa", pinned=False)


def test_pin_cross_origin_mutation_rejected_by_browser_guard(monkeypatch):
    """Same mutation rules as DELETE: pin is browser-guard covered."""
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.set_identity_pin.return_value = True
    monkeypatch.setattr("memory.singleton._instance", manager)

    tc = TestClient(server.build_app())
    r = tc.post(
        "/api/memory/2026-07-10_note_aaaa/pin",
        content='{"pinned": true}',
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403


def test_pin_missing_pinned_key_returns_400(client):
    tc, manager = client

    r = tc.post("/api/memory/2026-07-10_note_aaaa/pin", json={})

    assert r.status_code == 400
    manager.set_identity_pin.assert_not_called()
