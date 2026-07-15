"""Embedder health: a broken provider means dead recall — /health must say so.

Real incident (#57): EMBEDDING_PROVIDER pointed at an uninstalled provider,
every encode raised ImportError, stats showed 0 memories, recall returned
empty — and /health said "healthy". Data was intact; the server couldn't
embed and didn't say so.
"""

import threading
import time
from unittest.mock import MagicMock

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def _manager(tmp_path, embedder):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:9")
    store = MagicMock()
    store.count.return_value = 1
    store.scroll.return_value = [{"memory_id": "m0", "vector": [0.3, 0.7]}]
    manager._store = store
    manager._embedder = embedder
    return manager


def _health_body(monkeypatch, manager):
    import server

    monkeypatch.setattr("memory.singleton._instance", manager)
    server._reset_vector_health_cache()
    server._reset_embedder_health_cache()

    app = Starlette(routes=[Route("/health", server.health_check)])
    return TestClient(app).get("/health").json()


def test_health_degrades_when_embedder_raises(monkeypatch, tmp_path):
    embedder = MagicMock()
    embedder.encode.side_effect = ImportError("sentence-transformers required")

    body = _health_body(monkeypatch, _manager(tmp_path, embedder))

    assert body["status"] == "degraded"
    assert body["embedder"] == {"error": "ImportError: sentence-transformers required"}


def test_health_healthy_when_embedder_works(monkeypatch, tmp_path):
    embedder = MagicMock()
    embedder.encode.return_value = [0.1, 0.2]

    body = _health_body(monkeypatch, _manager(tmp_path, embedder))

    assert body["status"] == "healthy"
    assert body["embedder"] == "ok"


def test_embedder_probe_is_cached(monkeypatch, tmp_path):
    """/health is polled by the cockpit — one probe per TTL, not per poll."""
    import server

    embedder = MagicMock()
    embedder.encode.return_value = [0.1, 0.2]
    monkeypatch.setattr("memory.singleton._instance", _manager(tmp_path, embedder))
    server._reset_vector_health_cache()
    server._reset_embedder_health_cache()

    app = Starlette(routes=[Route("/health", server.health_check)])
    client = TestClient(app)
    client.get("/health")
    client.get("/health")

    assert embedder.encode.call_count == 1


def test_slow_probe_reports_timeout_without_caching(monkeypatch, tmp_path):
    """First-run encode may download the model — /health must not hang on it."""
    import server

    release = threading.Event()
    embedder = MagicMock()
    embedder.encode.side_effect = lambda _: release.wait(2.0)
    monkeypatch.setattr("memory.singleton._instance", _manager(tmp_path, embedder))
    monkeypatch.setattr("server._EMBEDDER_PROBE_TIMEOUT_S", 0.05)
    server._reset_vector_health_cache()
    server._reset_embedder_health_cache()

    app = Starlette(routes=[Route("/health", server.health_check)])
    started = time.monotonic()
    body = TestClient(app).get("/health").json()

    assert time.monotonic() - started < 1.0
    assert body["status"] == "degraded"
    assert "timeout" in body["embedder"]["error"]
    # Not cached — once the load finishes, the next poll picks up the result.
    assert server._embedder_health_cache["value"] is None
    release.set()
