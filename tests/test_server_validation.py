"""Request validation: traversal-shaped projects, unknown types, garbage numerics → 400."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):

    fake = MagicMock()
    fake.save.return_value = "2026-06-10_note_abc12345"
    fake.recall.return_value = []
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_save_rejects_path_traversal_project(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "project": "../../etc"})
    assert r.status_code == 400
    fake_manager.save.assert_not_called()


def test_save_rejects_unknown_type(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "type": "banana"})
    assert r.status_code == 400
    fake_manager.save.assert_not_called()


def test_save_accepts_valid_payload(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "type": "note", "project": "my-app"})
    assert r.status_code == 200


def test_observe_allows_auto_type(client, fake_manager, monkeypatch):
    import tools.builtin.memory as tbm

    monkeypatch.setattr(tbm, "_classify_by_embedding", lambda s, e: "learning")
    r = client.post("/api/memory/observe", json={"summary": "Decided to use X because Y"})
    assert r.status_code == 200


def test_smart_context_rejects_non_integer_limit(client, fake_manager):
    r = client.get("/api/memory/context/smart?limit=abc")
    assert r.status_code == 400


def test_recall_clamps_absurd_limit(client, fake_manager):
    r = client.post("/api/memory/recall", json={"query": "x", "limit": 999999})
    assert r.status_code == 200
    assert fake_manager.recall.call_args.kwargs["limit"] <= 100


def test_kb_rejects_traversal_project(client, fake_manager):
    r = client.get("/api/memory/kb?project=../../secrets")
    assert r.status_code == 400


def test_observe_uses_manager_embedder_for_auto_classification(client, fake_manager, monkeypatch):
    """api_observe must reuse manager.embedder, not construct a fresh model per request."""
    import tools.builtin.memory as tbm

    captured = {}

    def fake_classify(summary, embedder):
        captured["embedder"] = embedder
        return "learning"

    monkeypatch.setattr(tbm, "_classify_by_embedding", fake_classify)

    r = client.post("/api/memory/observe", json={"summary": "Fixed the bug because of X"})

    assert r.status_code == 200
    assert captured["embedder"] is fake_manager.embedder
