"""T3 — POST /api/memory/resparse contract + the exclusive maintenance barrier."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient


def _client(monkeypatch) -> TestClient:
    import server

    monkeypatch.setattr("memory.singleton._instance", MagicMock())
    return TestClient(server.build_app())


def test_resparse_route_returns_transaction_result(monkeypatch):
    result = {"points_updated": 5, "vocab_size": 42, "oov_identifier_reset": True}
    monkeypatch.setattr("memory.resparse.resparse", lambda manager: result)

    response = _client(monkeypatch).post("/api/memory/resparse")

    assert response.status_code == 200
    assert response.json() == result
