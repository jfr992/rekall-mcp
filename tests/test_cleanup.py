"""Tests for memory cleanup tool."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestStorageStats:
    """Tests for storage statistics."""

    def test_stats_empty_directory(self, tmp_path):
        """Should report zero for empty directory."""
        from memory.cleanup import get_storage_stats

        stats = get_storage_stats(tmp_path)

        assert stats["exists"] is True
        assert stats["file_count"] == 0

    def test_stats_nonexistent_directory(self):
        """Should report not exists for missing directory."""
        from memory.cleanup import get_storage_stats

        stats = get_storage_stats(Path("/nonexistent/path"))

        assert stats["exists"] is False

    def test_stats_with_memories(self, tmp_path):
        """Should count memories and calculate size."""
        from memory.cleanup import get_storage_stats

        # Create some memory files
        for i in range(5):
            mem = {"id": f"mem{i}", "content": "test", "created_at": "2024-01-01T00:00:00Z"}
            (tmp_path / f"mem{i}.json").write_text(json.dumps(mem))

        stats = get_storage_stats(tmp_path)

        assert stats["file_count"] == 5
        assert stats["total_size_bytes"] > 0


class TestFindMemoriesToDelete:
    """Tests for finding memories to delete."""

    @pytest.fixture
    def memories_with_dates(self, tmp_path):
        """Create memories with various dates."""
        base_date = datetime.utcnow()

        memories = [
            ("newest", base_date),
            ("recent", base_date - timedelta(days=10)),
            ("old", base_date - timedelta(days=100)),
            ("oldest", base_date - timedelta(days=200)),
        ]

        for name, date in memories:
            mem = {
                "id": name,
                "content": f"Memory {name}",
                "created_at": date.isoformat() + "Z",
            }
            (tmp_path / f"{name}.json").write_text(json.dumps(mem))

        return tmp_path

    def test_max_memories_keeps_newest(self, memories_with_dates):
        """Should keep newest when applying max_memories."""
        from memory.cleanup import find_memories_to_delete

        to_delete = find_memories_to_delete(
            memories_with_dates,
            max_memories=2,
        )

        # Should delete oldest 2
        assert len(to_delete) == 2
        names = {f.stem for f in to_delete}
        assert "oldest" in names
        assert "old" in names
        assert "newest" not in names
        assert "recent" not in names

    def test_max_age_deletes_old(self, memories_with_dates):
        """Should delete memories older than max_age_days."""
        from memory.cleanup import find_memories_to_delete

        to_delete = find_memories_to_delete(
            memories_with_dates,
            max_age_days=50,
        )

        # Should delete memories older than 50 days
        names = {f.stem for f in to_delete}
        assert "oldest" in names
        assert "old" in names
        assert "newest" not in names
        assert "recent" not in names

    def test_both_limits_combined(self, memories_with_dates):
        """Should apply both limits."""
        from memory.cleanup import find_memories_to_delete

        to_delete = find_memories_to_delete(
            memories_with_dates,
            max_memories=3,
            max_age_days=150,
        )

        # oldest (200 days) deleted by both limits
        # old (100 days) kept by age but might be deleted by count
        names = {f.stem for f in to_delete}
        assert "oldest" in names

    def test_no_limits_deletes_nothing(self, memories_with_dates):
        """Should delete nothing when no limits specified."""
        from memory.cleanup import find_memories_to_delete

        to_delete = find_memories_to_delete(memories_with_dates)

        assert len(to_delete) == 0


class TestCleanupMemories:
    """Tests for the cleanup function."""

    def test_dry_run_does_not_delete(self, tmp_path):
        """Dry run should not delete files."""
        from memory.cleanup import cleanup_memories

        # Create memories
        for i in range(5):
            mem = {"id": f"mem{i}", "content": "test", "created_at": "2024-01-01T00:00:00Z"}
            (tmp_path / f"mem{i}.json").write_text(json.dumps(mem))

        # Pass storage_path directly - it bypasses config
        result = cleanup_memories(
            storage_path=str(tmp_path),
            max_memories=2,
            dry_run=True,
        )

        # Files should still exist
        assert len(list(tmp_path.glob("*.json"))) == 5
        assert result.get("dry_run") is True
        assert result.get("would_delete") == 3

    def test_cleanup_deletes_files(self, tmp_path):
        """Should delete files when not dry run."""
        from memory.cleanup import cleanup_memories

        # Create memories with dates
        base_date = datetime.utcnow()
        for i in range(5):
            date = base_date - timedelta(days=i * 30)
            mem = {"id": f"mem{i}", "content": "test", "created_at": date.isoformat() + "Z"}
            (tmp_path / f"mem{i}.json").write_text(json.dumps(mem))

        result = cleanup_memories(
            storage_path=str(tmp_path),
            max_memories=2,
            dry_run=False,
        )

        # Should have only 2 files left
        remaining = list(tmp_path.glob("*.json"))
        assert len(remaining) == 2
        assert result["deleted_count"] == 3
        assert result["after_count"] == 2
