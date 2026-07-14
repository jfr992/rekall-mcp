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


def test_conflict_pair_renders_outdated_stub(tmp_path):
    """The corpus's one conflict pair (retry limit 5 → 3) must actually group:
    recall + format shows the newer value and stubs the older one (freshness
    Stage B/C, same pipeline test_freshness_integration pins)."""
    from memory.demo_seed import seed

    manager = _embedded_manager(tmp_path)
    seed(manager, tmp_path / "demo")

    results = manager.recall(
        "Stripe webhook retry limit",
        project="demo-payments-api",
        limit=10,
        score_threshold=0.0,
    )
    out = manager._format_with_guidance(results)

    assert "3 attempts" in out, f"newer conflict member missing:\n{out}"
    assert "5 attempts" not in out, f"older conflict member should be stubbed:\n{out}"
    assert "[outdated — replaced by the newer entry above]" in out


class TestDemoCommand:
    """`rekall demo` — isolated-by-default seeding, manifest-only clean, refusal."""

    def test_demo_seeds_isolated_store_and_prints_queries(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from memory.cli import memory
        from memory.demo_seed import SUGGESTED_QUERIES

        monkeypatch.delenv("MEMORY_STORAGE_PATH", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))

        result = CliRunner().invoke(memory, ["demo"])

        assert result.exit_code == 0, result.output
        demo_dir = tmp_path / "rekall" / "demo"
        ids = json.loads((demo_dir / "manifest.json").read_text())["memory_ids"]
        assert len(ids) == 20
        assert list((demo_dir / "memory").rglob("*.yaml")), "YAML must land in the demo dir"
        assert (demo_dir / "qdrant").is_dir(), "vectors must land in the demo dir"
        for query in SUGGESTED_QUERIES:
            assert query in result.output

    def test_demo_refuses_non_empty_non_demo_store(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from memory.cli import memory

        store = tmp_path / "real-memory"
        (store / "real-project").mkdir(parents=True)
        (store / "real-project" / "2026-07-01.yaml").write_text(
            "date: '2026-07-01'\nnotes:\n- id: 2026-07-01_note_rea10000\n  content: real memory\n"
        )
        monkeypatch.setenv("MEMORY_STORAGE_PATH", str(store))

        result = CliRunner().invoke(memory, ["demo"])

        assert result.exit_code == 2, result.output
        assert "--force-into-real-store" in result.output
        yaml_files = list(store.rglob("*.yaml"))
        assert len(yaml_files) == 1, "refusal must not write anything"

    def test_demo_clean_round_trip(self, tmp_path, monkeypatch):
        import gc

        from click.testing import CliRunner

        from memory.cli import memory

        monkeypatch.delenv("MEMORY_STORAGE_PATH", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        runner = CliRunner()

        assert runner.invoke(memory, ["demo"]).exit_code == 0
        # Drop the first invocation's embedded store handle before --clean
        # reopens the same qdrant path (flock is per-process-handle).
        gc.collect()

        result = runner.invoke(memory, ["demo", "--clean"])

        assert result.exit_code == 0, result.output
        demo_dir = tmp_path / "rekall" / "demo"
        assert not (demo_dir / "manifest.json").exists()
        assert not list((demo_dir / "memory").rglob("*.yaml")), "all seeded YAML removed"

    def test_demo_force_seeds_into_non_empty_store(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from memory.cli import memory

        store = tmp_path / "real-memory"
        (store / "real-project").mkdir(parents=True)
        (store / "real-project" / "2026-07-01.yaml").write_text(
            "date: '2026-07-01'\nnotes:\n- id: 2026-07-01_note_rea10000\n  content: real memory\n"
        )
        monkeypatch.setenv("MEMORY_STORAGE_PATH", str(store))
        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "q"))

        result = CliRunner().invoke(memory, ["demo", "--force-into-real-store"])

        assert result.exit_code == 0, result.output
        ids = json.loads((store.parent / "manifest.json").read_text())["memory_ids"]
        assert len(ids) == 20
