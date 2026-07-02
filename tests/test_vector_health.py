"""Vector health: zero vectors mean dead semantic search — must be visible."""

from unittest.mock import MagicMock

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def _manager_with_vectors(tmp_path, vectors):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:9")
    store = MagicMock()
    store.count.return_value = len(vectors)
    store.scroll.return_value = [{"memory_id": f"m{i}", "vector": v} for i, v in enumerate(vectors)]
    manager._store = store
    kg = MagicMock()
    kg.stats.return_value = {"nodes": 0, "edges": 0, "relations": {}}
    manager._knowledge_graph = kg
    return manager


def test_stats_reports_zero_vectors(tmp_path):
    manager = _manager_with_vectors(tmp_path, [[0.0, 0.0, 0.0], [0.1, 0.2, 0.3]])

    stats = manager.get_stats()

    assert stats["vector_health"] == {"sampled": 2, "zero_vectors": 1}


def test_stats_vector_health_all_good(tmp_path):
    manager = _manager_with_vectors(tmp_path, [[0.5, 0.1], [0.2, 0.9]])

    assert manager.get_stats()["vector_health"] == {"sampled": 2, "zero_vectors": 0}


def test_health_endpoint_degrades_on_zero_vectors(monkeypatch, tmp_path):
    import server

    manager = _manager_with_vectors(tmp_path, [[0.0, 0.0], [0.0, 0.0]])
    monkeypatch.setattr(server, "_memory_manager_instance", manager)
    server._reset_vector_health_cache()

    app = Starlette(routes=[Route("/health", server.health_check)])
    body = TestClient(app).get("/health").json()

    assert body["status"] == "degraded"
    assert body["vectors"] == {"sampled": 2, "zero_vectors": 2}


def test_health_endpoint_healthy_with_real_vectors(monkeypatch, tmp_path):
    import server

    manager = _manager_with_vectors(tmp_path, [[0.3, 0.7]])
    monkeypatch.setattr(server, "_memory_manager_instance", manager)
    server._reset_vector_health_cache()

    app = Starlette(routes=[Route("/health", server.health_check)])
    body = TestClient(app).get("/health").json()

    assert body["status"] == "healthy"
    assert body["vectors"]["zero_vectors"] == 0
