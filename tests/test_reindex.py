"""Reindex contract: tarball -> rebuild -> verify -> graph (portability spec rev 3).

All tests run against tmp_path embedded stores — never a Qdrant server.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.manager import MemoryManager


def _embedded_manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))


def test_reindex_tarballs_both_roots_first(tmp_path, monkeypatch):
    from core.vector_store import VectorStore
    from memory.reindex import reindex

    manager = _embedded_manager(tmp_path)
    manager.save("decided to verify tarball ordering in reindex", type="decision", project="proj-a")

    tarball_dir = tmp_path / "backups"
    seen_at_recreate: list[list[str]] = []
    original = VectorStore.recreate_collection

    def recording(self):
        seen_at_recreate.append(sorted(p.name for p in tarball_dir.glob("*.tar.gz")))
        return original(self)

    monkeypatch.setattr(VectorStore, "recreate_collection", recording)

    result = reindex(manager, tarball_dir=tarball_dir)

    assert len(seen_at_recreate) == 1, "collection must be recreated exactly once"
    names = seen_at_recreate[0]
    assert len(names) == 2, f"both root tarballs must exist before recreation, saw {names}"
    assert any("memory" in n for n in names)
    assert any("qdrant" in n for n in names)
    assert result["points"] == 1


def test_reindex_loads_embedder_before_recreate(tmp_path, monkeypatch):
    from memory.reindex import reindex

    manager = _embedded_manager(tmp_path)
    memory_id = manager.save("embedder failure must not destroy the collection", type="note")
    assert manager.store.count() == 1

    class EmbedderBroken(Exception):
        pass

    def boom(text):
        raise EmbedderBroken(text)

    monkeypatch.setattr(manager.embedder, "encode", boom)

    with pytest.raises(EmbedderBroken):
        reindex(manager, tarball_dir=tmp_path / "backups")

    assert manager.store.count() == 1, "collection must be untouched when the embedder fails"
    assert manager.store.get_by_id(memory_id) is not None
