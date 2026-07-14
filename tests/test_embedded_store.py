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
