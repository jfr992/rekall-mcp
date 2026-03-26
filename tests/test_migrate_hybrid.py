"""Tests for hybrid search migration script."""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path


class TestLoadAllYamlMemories:
    """Test YAML memory loading."""

    def test_loads_memories_from_single_file(self, tmp_path):
        """load_all_yaml_memories reads decisions from a single YAML."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({
                "date": "2026-03-25",
                "decisions": [
                    {"id": "2026-03-25_decision_abc", "content": "Use hybrid search", "project": "memento"},
                ]
            })
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1
        assert memories[0]["content"] == "Use hybrid search"
        assert memories[0]["type"] == "decision"
        assert memories[0]["project"] == "memento"

    def test_loads_multiple_types(self, tmp_path):
        """load_all_yaml_memories reads multiple memory types."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({
                "date": "2026-03-25",
                "decisions": [{"id": "d1", "content": "Decision content", "project": "p"}],
                "learnings": [{"id": "l1", "content": "Learning content", "project": "p"}],
                "notes": [{"id": "n1", "content": "Note content", "project": "p"}],
            })
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 3
        types = {m["type"] for m in memories}
        assert types == {"decision", "learning", "note"}

    def test_loads_from_multiple_files(self, tmp_path):
        """load_all_yaml_memories reads all YAML files in directory."""
        from memory.migrate_hybrid import load_all_yaml_memories

        for i, date in enumerate(["2026-03-23", "2026-03-24", "2026-03-25"]):
            (tmp_path / f"{date}.yaml").write_text(
                yaml.dump({
                    "date": date,
                    "notes": [{"id": f"n{i}", "content": f"Note {i}", "project": "p"}],
                })
            )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 3

    def test_skips_internal_files(self, tmp_path):
        """Files starting with _ are skipped."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "_bm25_vocab.json").write_text("{}")
        (tmp_path / "_graph.json").write_text("{}")
        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({
                "date": "2026-03-25",
                "notes": [{"id": "n1", "content": "Real note", "project": "p"}],
            })
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1

    def test_handles_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        from memory.migrate_hybrid import load_all_yaml_memories

        memories = load_all_yaml_memories(tmp_path)

        assert memories == []

    def test_handles_malformed_yaml_gracefully(self, tmp_path):
        """Malformed YAML files are skipped without crashing."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "bad.yaml").write_text("this: is: not: valid: yaml: [unclosed")
        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({"date": "2026-03-25", "notes": [{"id": "n1", "content": "OK", "project": "p"}]})
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1


class TestBuildCorpus:
    """Test corpus building from memories."""

    def test_extracts_content_strings(self):
        """build_corpus returns list of content strings."""
        from memory.migrate_hybrid import build_corpus

        memories = [
            {"content": "First memory", "memory_id": "1"},
            {"content": "Second memory", "memory_id": "2"},
        ]

        corpus = build_corpus(memories)

        assert corpus == ["First memory", "Second memory"]

    def test_skips_empty_content(self):
        """build_corpus skips entries with empty content."""
        from memory.migrate_hybrid import build_corpus

        memories = [
            {"content": "Valid", "memory_id": "1"},
            {"content": "", "memory_id": "2"},
            {"content": None, "memory_id": "3"},
        ]

        corpus = build_corpus(memories)

        assert corpus == ["Valid"]


class TestMigrateToHybridDryRun:
    """Test dry-run migration (no Qdrant needed)."""

    def test_dry_run_returns_stats(self, tmp_path):
        """Dry run returns memory count and vocab size."""
        from memory.migrate_hybrid import migrate_to_hybrid

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({
                "date": "2026-03-25",
                "decisions": [
                    {"id": "d1", "content": "Use BM25 for search", "project": "memento"},
                    {"id": "d2", "content": "Keep YAML as source of truth", "project": "memento"},
                ],
            })
        )

        result = migrate_to_hybrid(
            memory_dir=tmp_path,
            qdrant_url="http://localhost:6334",
            dry_run=True,
        )

        assert result["status"] == "dry_run"
        assert result["memories"] == 2
        assert result["vocab_size"] > 0

    def test_dry_run_empty_directory_returns_no_memories(self, tmp_path):
        """Dry run on empty directory returns no_memories status."""
        from memory.migrate_hybrid import migrate_to_hybrid

        result = migrate_to_hybrid(
            memory_dir=tmp_path,
            qdrant_url="http://localhost:6334",
            dry_run=True,
        )

        assert result["status"] == "no_memories"

    def test_dry_run_does_not_write_bm25_file(self, tmp_path):
        """Dry run does not write _bm25_vocab.json."""
        from memory.migrate_hybrid import migrate_to_hybrid

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({"date": "2026-03-25", "notes": [{"id": "n1", "content": "test", "project": "p"}]})
        )

        migrate_to_hybrid(memory_dir=tmp_path, qdrant_url="http://localhost:6334", dry_run=True)

        assert not (tmp_path / "_bm25_vocab.json").exists()
