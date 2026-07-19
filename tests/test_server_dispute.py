"""POST /api/memory/{id}/dispute — REST contract for un-dispute resolution (T5).

Same shape as test_server_pin.py: browser-guard covered mutation, manager-mock
client idiom. Minimal v1 — clear disputed=false only, no new mutation machinery.
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


def test_undispute_calls_manager_and_returns_200(client):
    tc, manager = client
    manager.set_disputed.return_value = True

    r = tc.post("/api/memory/2026-07-10_fact_aaaa/dispute", json={"disputed": False})

    assert r.status_code == 200
    assert r.json() == {"memory_id": "2026-07-10_fact_aaaa", "disputed": False}
    manager.set_disputed.assert_called_once_with("2026-07-10_fact_aaaa", disputed=False)


def test_dispute_unknown_memory_id_returns_404(client):
    tc, manager = client
    manager.set_disputed.return_value = False

    r = tc.post("/api/memory/2026-07-10_fact_unknown/dispute", json={"disputed": False})

    assert r.status_code == 404


def test_dispute_cross_origin_mutation_rejected_by_browser_guard(monkeypatch):
    """Same mutation rules as pin/DELETE: dispute is browser-guard covered."""
    from unittest.mock import MagicMock

    from starlette.testclient import TestClient

    import server

    manager = MagicMock()
    manager.set_disputed.return_value = True
    monkeypatch.setattr("memory.singleton._instance", manager)

    tc = TestClient(server.build_app())
    r = tc.post(
        "/api/memory/2026-07-10_fact_aaaa/dispute",
        content='{"disputed": false}',
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403


def test_dispute_missing_disputed_key_returns_400(client):
    tc, manager = client

    r = tc.post("/api/memory/2026-07-10_fact_aaaa/dispute", json={})

    assert r.status_code == 400
    manager.set_disputed.assert_not_called()
