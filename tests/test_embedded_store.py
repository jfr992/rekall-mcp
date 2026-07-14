"""Embedded (local-path) Qdrant mode for VectorStore and MemoryManager."""

from pathlib import Path

import pytest

from core.vector_store import VectorStore


def test_path_mode_constructs_local_client(tmp_path):
    vs = VectorStore(collection="t", path=str(tmp_path / "q"))
    vs.save(
        id="2026-01-01_note_aaaa1111",
        vector=[0.1] * 384,
        payload={"memory_id": "2026-01-01_note_aaaa1111", "content": "x"},
        content=None,
    )
    assert vs.get_many(["2026-01-01_note_aaaa1111"])[0]["memory_id"] == "2026-01-01_note_aaaa1111"


def test_url_and_path_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        VectorStore(collection="t", url="http://localhost:6334", path=str(tmp_path / "q"))


def test_manager_reuses_injected_qdrant_client(tmp_path):
    """The acquire-held client IS the store lock — the manager must reuse it;
    a second client on the same path would hit qdrant's flock and fail."""
    from qdrant_client import QdrantClient

    from memory import MemoryManager

    client = QdrantClient(path=str(tmp_path / "q"))
    manager = MemoryManager(
        memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"), qdrant_client=client
    )

    memory_id = manager.save("injected client save works", type="note")

    assert manager.store.client is client
    assert manager.store.get_by_id(memory_id) is not None


def test_manager_store_dimensions_follow_embedder(tmp_path):
    """A 768-dim embedder must produce a 768-dim collection — hardcoded 384
    would fail on the first upsert."""
    from types import SimpleNamespace

    from memory import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))
    manager._embedder = SimpleNamespace(dimensions=768)

    assert manager.store.embedding_dim == 768
    manager.store.save(
        id="2026-01-01_note_dim76800",
        vector=[0.1] * 768,
        payload={"memory_id": "2026-01-01_note_dim76800", "content": "x"},
        content=None,
    )
    assert manager.store.get_by_id("2026-01-01_note_dim76800") is not None


def test_manager_env_both_set_raises_on_store_access(monkeypatch, tmp_path):
    """QDRANT_URL + QDRANT_PATH both in env: mutual-exclusion error propagates."""
    from memory import MemoryManager

    monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "q"))
    manager = MemoryManager(memory_dir=tmp_path / "memory")
    with pytest.raises(ValueError, match="mutually exclusive"):
        _ = manager.store


def test_guard_refuses_home_rekall_qdrant_path_under_pytest(monkeypatch, tmp_path):
    from core.utils import assert_test_isolation

    monkeypatch.setenv("QDRANT_PATH", str(Path.home() / ".rekall" / "qdrant"))
    with pytest.raises(RuntimeError, match="prod"):
        assert_test_isolation()


def test_store_refuses_prod_qdrant_path_under_pytest():
    vs = VectorStore(collection="t", path=str(Path.home() / ".rekall" / "qdrant"))
    with pytest.raises(RuntimeError, match="prod"):
        _ = vs.client


def test_manager_qdrant_path_roundtrip(tmp_path):
    from memory import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))
    memory_id = manager.save("Decided to use embedded Qdrant for the trial tier", type="decision")
    results = manager.recall("embedded qdrant trial tier")
    assert any(r.get("memory_id", r.get("id")) == memory_id for r in results)
