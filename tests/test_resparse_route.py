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


def test_resparse_route_maps_failures_to_500_with_remediation(monkeypatch):
    from memory.resparse import ResparsePreflightError

    def refuse(manager):
        raise ResparsePreflightError("no 'bm25' sparse field — run a full reindex")

    monkeypatch.setattr("memory.resparse.resparse", refuse)

    response = _client(monkeypatch).post("/api/memory/resparse")

    assert response.status_code == 500
    assert "reindex" in response.json()["error"]


def test_resparse_route_rejects_browser_marked_cross_origin(monkeypatch):
    response = _client(monkeypatch).post(
        "/api/memory/resparse",
        content="x=1",
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )

    assert response.status_code == 403
