"""Tests for memory sync tool."""

from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestGetYamlMemories:
    """Tests for loading memories from YAML files."""

    def test_loads_memories_from_yaml(self, tmp_path):
        """Should load all memories from YAML files."""
        from memory.sync import _get_yaml_memories

        data = {
            "date": "2024-01-01",
            "decisions": [
                {
                    "id": "dec1",
                    "content": "Decision 1",
                    "project": "test",
                    "timestamp": "2024-01-01T10:00:00",
                },
            ],
            "learnings": [
                {
                    "id": "learn1",
                    "content": "Learning 1",
                    "project": "test",
                    "timestamp": "2024-01-01T11:00:00",
                },
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))

        memories = _get_yaml_memories(tmp_path)

        assert len(memories) == 2
        assert "dec1" in memories
        assert "learn1" in memories
        assert memories["dec1"]["type"] == "decision"
        assert memories["learn1"]["type"] == "learning"

    def test_empty_directory_returns_empty(self, tmp_path):
        """Should return empty dict for empty directory."""
        from memory.sync import _get_yaml_memories

        memories = _get_yaml_memories(tmp_path)

        assert memories == {}

    def test_includes_content_hash(self, tmp_path):
        """Should include content hash for change detection."""
        from memory.sync import _get_yaml_memories

        data = {
            "date": "2024-01-01",
            "facts": [
                {"id": "fact1", "content": "Some fact", "timestamp": "2024-01-01T10:00:00"},
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))

        memories = _get_yaml_memories(tmp_path)

        assert "content_hash" in memories["fact1"]
        assert len(memories["fact1"]["content_hash"]) == 12  # MD5 truncated


class TestContentHash:
    """Tests for content hash function."""

    def test_same_content_same_hash(self):
        """Same content should produce same hash."""
        from memory.sync import _content_hash

        hash1 = _content_hash("Hello world")
        hash2 = _content_hash("Hello world")

        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Different content should produce different hash."""
        from memory.sync import _content_hash

        hash1 = _content_hash("Hello world")
        hash2 = _content_hash("Hello there")

        assert hash1 != hash2


class TestSyncMemories:
    """Tests for the sync function."""

    @pytest.fixture
    def mock_qdrant_memories(self):
        """Mock for _get_qdrant_memories."""
        return {
            "existing1": {
                "id": "existing1",
                "content": "Old content",
                "content_hash": "abc123def456",
            },
        }

    @pytest.fixture
    def yaml_with_changes(self, tmp_path):
        """Create YAML with a new and updated memory."""
        data = {
            "date": "2024-01-01",
            "decisions": [
                # New memory (not in Qdrant)
                {
                    "id": "new1",
                    "content": "New decision",
                    "project": "test",
                    "timestamp": "2024-01-01T10:00:00",
                },
                # Updated memory (different content hash)
                {
                    "id": "existing1",
                    "content": "Updated content",
                    "project": "test",
                    "timestamp": "2024-01-01T11:00:00",
                },
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))
        return tmp_path

    def test_dry_run_detects_changes(self, yaml_with_changes, mock_qdrant_memories):
        """Dry run should detect adds, updates, and deletes."""
        from memory.sync import sync_memories

        with patch("memory.sync._get_qdrant_memories", return_value=mock_qdrant_memories):
            with patch("core.vector_store.VectorStore"):
                result = sync_memories(
                    storage_path=str(yaml_with_changes),
                    dry_run=True,
                )

        assert result["dry_run"] is True
        assert result["to_add"] == 1  # new1
        assert result["to_update"] == 1  # existing1 (content changed)
        assert result["to_delete"] == 0  # existing1 still in YAML

    def test_detects_deletions(self, tmp_path):
        """Should detect memories in Qdrant but not in YAML."""
        from memory.sync import sync_memories

        # Empty YAML directory
        qdrant_memories = {
            "orphan1": {"id": "orphan1", "content": "Orphaned", "content_hash": "xyz789"},
        }

        with patch("memory.sync._get_qdrant_memories", return_value=qdrant_memories):
            with patch("core.vector_store.VectorStore"):
                result = sync_memories(
                    storage_path=str(tmp_path),
                    dry_run=True,
                )

        assert result["to_delete"] == 1

    def test_already_in_sync(self, tmp_path):
        """Should report sync when no changes needed."""
        from memory.sync import sync_memories

        # Create YAML
        data = {
            "date": "2024-01-01",
            "facts": [
                {"id": "fact1", "content": "Same content", "timestamp": "2024-01-01T10:00:00"},
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))

        # Mock Qdrant with same content hash
        from memory.sync import _content_hash

        qdrant_memories = {
            "fact1": {
                "id": "fact1",
                "content": "Same content",
                "content_hash": _content_hash("Same content"),
            },
        }

        with patch("memory.sync._get_qdrant_memories", return_value=qdrant_memories):
            with patch("core.vector_store.VectorStore"):
                result = sync_memories(
                    storage_path=str(tmp_path),
                    dry_run=True,
                )

        assert result.get("synced") is True
        assert result["added"] == 0
        assert result["updated"] == 0
        assert result["deleted"] == 0


class TestSyncIntegration:
    """Integration tests for sync (with mocked Qdrant)."""

    def test_sync_adds_new_memories(self, tmp_path):
        """Should add new memories to Qdrant."""
        from memory.sync import sync_memories

        # Create YAML with new memory
        data = {
            "date": "2024-01-01",
            "decisions": [
                {
                    "id": "new1",
                    "content": "New decision",
                    "project": "test",
                    "timestamp": "2024-01-01T10:00:00",
                },
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))

        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [0.1] * 384

        with patch("memory.sync._get_qdrant_memories", return_value={}):
            with patch("core.VectorStore", return_value=mock_store):
                with patch("core.Embedder", return_value=mock_embedder):
                    result = sync_memories(
                        storage_path=str(tmp_path),
                        dry_run=False,
                    )

        assert result["added"] == 1
        mock_store.save.assert_called_once()
