"""`rekall demo` corpus: manifest-exact seeding, manifest-only cleanup.

All tests run against tmp_path embedded stores — never a Qdrant server,
never real ~/.rekall or ~/.claude.
"""

from __future__ import annotations

import json
from pathlib import Path

from memory.manager import MemoryManager


def _embedded_manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(memory_dir=tmp_path / "memory", qdrant_path=str(tmp_path / "q"))


def test_seed_writes_manifest_matching_store(tmp_path):
    from memory.demo_seed import seed

    manager = _embedded_manager(tmp_path)
    demo_dir = tmp_path / "demo"

    ids = seed(manager, demo_dir)

    manifest = json.loads((demo_dir / "manifest.json").read_text())
    assert manifest["memory_ids"] == ids
    assert len(ids) == len(set(ids)) == 20

    stored = manager.store.get_many(ids)
    assert len(stored) == 20
    assert all(m["content"].startswith("[demo]") for m in stored)
    assert sum(1 for m in stored if "TODO:" in m["content"]) == 1


def test_clean_removes_only_manifest_ids(tmp_path):
    from memory.demo_seed import clean, seed

    manager = _embedded_manager(tmp_path)
    survivor = manager.save(
        "real decision that must survive the demo clean", type="decision", project="real-project"
    )
    demo_dir = tmp_path / "demo"
    ids = seed(manager, demo_dir)

    deleted = clean(manager, demo_dir / "manifest.json")

    assert deleted == len(ids)
    assert manager.store.count() == 1
    assert manager.store.get_by_id(survivor) is not None
    assert not (demo_dir / "manifest.json").exists()
