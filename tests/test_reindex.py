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


def test_reindex_rebuilds_counts_match(tmp_path):
    import yaml

    from memory.reindex import reindex

    manager = _embedded_manager(tmp_path)
    project_dir = manager.memory_dir / "proj-a"
    project_dir.mkdir(parents=True)
    entries = [
        {
            "id": f"2026-07-01_note_aaaa000{i}",
            "content": f"observation {i}: module mod_{i} handles concern {i}",
            "project": "proj-a",
            "timestamp": f"2026-07-01T10:0{i}:00",
        }
        for i in range(5)
    ]
    compacted = {
        "id": "2026-07-01_note_dead0000",
        "content": "old observation folded into a summary",
        "project": "proj-a",
        "timestamp": "2026-07-01T09:00:00",
        "compacted": True,
        "compacted_into": "2026-07-01_summary_beef0000",
    }
    (project_dir / "2026-07-01.yaml").write_text(
        yaml.dump({"date": "2026-07-01", "notes": [*entries, compacted]}, sort_keys=False)
    )

    result = reindex(manager, tarball_dir=tmp_path / "backups")

    assert result["points"] == 5, "compacted originals must not be re-indexed"
    assert result["verified"] is True
    assert manager.store.count() == 5
    assert manager.store.get_by_id("2026-07-01_note_dead0000") is None
    sample = manager.store.scroll(limit=5, with_vectors=True)
    assert all(any(v != 0 for v in p["vector"]) for p in sample), "vectors must be non-zero"
