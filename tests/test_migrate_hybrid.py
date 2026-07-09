"""Tests for hybrid search migration script."""

from __future__ import annotations

import yaml


class TestLoadAllYamlMemories:
    """Test YAML memory loading."""

    def test_loads_memories_from_single_file(self, tmp_path):
        """load_all_yaml_memories reads decisions from a single YAML."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "decisions": [
                        {
                            "id": "2026-03-25_decision_abc",
                            "content": "Use hybrid search",
                            "project": "rekall",
                        },
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1
        assert memories[0]["content"] == "Use hybrid search"
        assert memories[0]["type"] == "decision"
        assert memories[0]["project"] == "rekall"

    def test_loads_memories_from_nested_project_directory(self, tmp_path):
        """load_all_yaml_memories discovers nested per-project YAML files."""
        from memory.migrate_hybrid import load_all_yaml_memories

        nested_file = tmp_path / "byte-edge" / "2026-07-03.yaml"
        nested_file.parent.mkdir()
        nested_file.write_text(
            yaml.dump(
                {
                    "date": "2026-07-03",
                    "notes": [
                        {"id": "n1", "content": "Nested note", "project": "byte-edge"},
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1
        assert memories[0]["content"] == "Nested note"
        assert memories[0]["project"] == "byte-edge"

    def test_loads_nested_project_memory_ids(self, tmp_path):
        """load_all_yaml_memories reads memories below project directories."""
        from memory.migrate_hybrid import load_all_yaml_memories

        project_dir = tmp_path / "byte-edge"
        project_dir.mkdir()
        (project_dir / "2026-07-03.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-07-03",
                    "facts": [
                        {"id": "m1", "content": "Nested", "project": "byte-edge"},
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert [memory["id"] for memory in memories] == ["m1"]
        assert [memory["memory_id"] for memory in memories] == ["m1"]

    def test_loads_memory_id_only_entries(self, tmp_path):
        """YAML exports with memory_id but no id are still valid memories."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [
                        {
                            "memory_id": "mid-only",
                            "content": "Payload-style memory",
                            "project": "rekall",
                        }
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert [memory["id"] for memory in memories] == ["mid-only"]
        assert [memory["memory_id"] for memory in memories] == ["mid-only"]

    def test_preserves_distinct_id_and_memory_id_when_present(self, tmp_path):
        """Loader should not collapse explicit id/memory_id fields when both exist."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [
                        {
                            "id": "yaml-id",
                            "memory_id": "payload-id",
                            "content": "Both ids exist",
                            "project": "rekall",
                        }
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert memories[0]["id"] == "yaml-id"
        assert memories[0]["memory_id"] == "payload-id"

    def test_loads_multiple_types(self, tmp_path):
        """load_all_yaml_memories reads multiple memory types."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "decisions": [{"id": "d1", "content": "Decision content", "project": "p"}],
                    "learnings": [{"id": "l1", "content": "Learning content", "project": "p"}],
                    "notes": [{"id": "n1", "content": "Note content", "project": "p"}],
                }
            )
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
                yaml.dump(
                    {
                        "date": date,
                        "notes": [{"id": f"n{i}", "content": f"Note {i}", "project": "p"}],
                    }
                )
            )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 3

    def test_skips_internal_files(self, tmp_path):
        """Files starting with _ are skipped."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "_bm25_vocab.json").write_text("{}")
        (tmp_path / "_graph.json").write_text("{}")
        (tmp_path / "_metadata.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [{"id": "internal", "content": "Internal", "project": "p"}],
                }
            )
        )
        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [{"id": "n1", "content": "Real note", "project": "p"}],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1

    def test_preserves_embedding_text_and_entities(self, tmp_path):
        """load_all_yaml_memories keeps embedding_text and entities fields."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [
                        {
                            "id": "n1",
                            "content": "Keep these fields",
                            "project": "p",
                            "embedding_text": "Project p. Claim Keep these fields.",
                            "entities": ["Project", "Claim"],
                        }
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1
        assert memories[0]["embedding_text"] == "Project p. Claim Keep these fields."
        assert memories[0]["entities"] == ["Project", "Claim"]

    def test_preserves_existing_metadata_fields(self, tmp_path):
        """Loader keeps provenance/lifecycle fields instead of whitelisting them away."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [
                        {
                            "id": "n1",
                            "content": "Keep metadata",
                            "project": "p",
                            "agent": "claude-code",
                            "source_tool": "rekall-observe",
                            "cwd": "/repo/p",
                            "tier": "semantic",
                            "durability": 0.91,
                        }
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert memories[0]["agent"] == "claude-code"
        assert memories[0]["source_tool"] == "rekall-observe"
        assert memories[0]["cwd"] == "/repo/p"
        assert memories[0]["tier"] == "semantic"
        assert memories[0]["durability"] == 0.91

    def test_skips_entries_without_id_or_content(self, tmp_path):
        """load_all_yaml_memories ignores malformed memory entries."""
        from memory.migrate_hybrid import load_all_yaml_memories

        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "notes": [
                        {"id": "n1", "content": "Real note", "project": "p"},
                        {"content": "Missing id", "project": "p"},
                        {"id": "n2", "content": "", "project": "p"},
                    ],
                }
            )
        )

        memories = load_all_yaml_memories(tmp_path)

        assert [memory["id"] for memory in memories] == ["n1"]

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
            yaml.dump(
                {"date": "2026-03-25", "notes": [{"id": "n1", "content": "OK", "project": "p"}]}
            )
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

    def test_prefers_embedding_text(self):
        """build_corpus trains on deterministic embedding text when present."""
        from memory.migrate_hybrid import build_corpus

        memories = [
            {
                "content": "Raw phrasing",
                "embedding_text": "Project rekall. Claim: canonical phrasing.",
            },
            {"content": "Only raw"},
        ]

        assert build_corpus(memories) == ["Project rekall. Claim: canonical phrasing.", "Only raw"]

    def test_blank_embedding_text_falls_back_to_content(self):
        """Whitespace-only embedding text should not hide raw content."""
        from memory.migrate_hybrid import build_corpus

        memories = [{"content": "Raw fallback", "embedding_text": "   "}]

        assert build_corpus(memories) == ["Raw fallback"]

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
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "decisions": [
                        {"id": "d1", "content": "Use BM25 for search", "project": "rekall"},
                        {
                            "id": "d2",
                            "content": "Keep YAML as source of truth",
                            "project": "rekall",
                        },
                    ],
                }
            )
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
            yaml.dump(
                {"date": "2026-03-25", "notes": [{"id": "n1", "content": "test", "project": "p"}]}
            )
        )

        migrate_to_hybrid(memory_dir=tmp_path, qdrant_url="http://localhost:6334", dry_run=True)

        assert not (tmp_path / "_bm25_vocab.json").exists()


class TestMigrateToHybridWrite:
    """Test non-dry-run migration side effects without a live Qdrant."""

    def test_migration_backfills_schema_fields_to_yaml(self, tmp_path, monkeypatch):
        from memory.migrate_hybrid import migrate_to_hybrid

        project_dir = tmp_path / "byte-edge"
        project_dir.mkdir()
        yaml_file = project_dir / "2026-07-03.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "date": "2026-07-03",
                    "decisions": [
                        {
                            "id": "d1",
                            "content": "Decided to use PostgreSQL for JSON support",
                            "project": "byte-edge",
                            "source_tool": "legacy-import",
                        }
                    ],
                }
            )
        )

        saved = []

        class FakeBM25Encoder:
            vocab = {"postgresql": 1}

            def fit(self, corpus):
                self.corpus = corpus

            def save(self, path):
                (tmp_path / "_bm25_vocab.json").write_text("{}")

            def encode(self, content):
                return {1: 1.0}

        class FakeEmbedder:
            def encode(self, text):
                return [0.1] * 384

        class FakeVectorStore:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def recreate_collection(self):
                return None

            def save(self, **kwargs):
                saved.append(kwargs)

        monkeypatch.setattr("core.BM25Encoder", FakeBM25Encoder)
        monkeypatch.setattr("core.Embedder", FakeEmbedder)
        monkeypatch.setattr("core.VectorStore", FakeVectorStore)

        result = migrate_to_hybrid(
            memory_dir=tmp_path,
            qdrant_url="http://localhost:6334",
            dry_run=False,
        )

        data = yaml.safe_load(yaml_file.read_text())
        entry = data["decisions"][0]
        assert result["schema_updates"] == 1
        assert entry["entities"] == ["PostgreSQL", "JSON"]
        assert entry["embedding_text"].startswith("Project byte-edge.")
        assert entry["tier"] == "semantic"
        assert entry["reinforcement_count"] == 0
        assert saved[0]["payload"]["embedding_text"] == entry["embedding_text"]
        assert saved[0]["payload"]["source_tool"] == "legacy-import"

    def test_reindex_encodes_raw_content_for_dense_vector(self, tmp_path, monkeypatch):
        """Repr v2: the re-index dense vector encodes raw content; the sparse
        leg (content= kwarg) keeps embedding_text."""
        from memory.migrate_hybrid import migrate_to_hybrid

        yaml_file = tmp_path / "2026-07-03.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "date": "2026-07-03",
                    "decisions": [
                        {
                            "id": "d1",
                            "content": "Decided to use PostgreSQL for JSON support",
                            "project": "byte-edge",
                        }
                    ],
                }
            )
        )

        saved = []
        encoded = []

        class FakeBM25Encoder:
            vocab = {"postgresql": 1}

            def fit(self, corpus):
                pass

            def save(self, path):
                (tmp_path / "_bm25_vocab.json").write_text("{}")

            def encode(self, content):
                return {1: 1.0}

        class FakeEmbedder:
            def encode(self, text):
                encoded.append(text)
                return [0.1] * 384

        class FakeVectorStore:
            def __init__(self, **kwargs):
                pass

            def recreate_collection(self):
                return None

            def save(self, **kwargs):
                saved.append(kwargs)

        monkeypatch.setattr("core.BM25Encoder", FakeBM25Encoder)
        monkeypatch.setattr("core.Embedder", FakeEmbedder)
        monkeypatch.setattr("core.VectorStore", FakeVectorStore)

        migrate_to_hybrid(memory_dir=tmp_path, qdrant_url="http://localhost:6334", dry_run=False)

        assert encoded == ["Decided to use PostgreSQL for JSON support"]
        assert saved[0]["content"] == saved[0]["payload"]["embedding_text"]
        assert saved[0]["payload"]["embedding_text"].startswith("Project byte-edge.")
        assert saved[0]["payload"]["repr_version"] == 2
