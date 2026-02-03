"""Tests for memory cleanup tool (YAML format)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml


class TestStorageStats:
    """Tests for storage statistics."""

    def test_stats_empty_directory(self, tmp_path):
        """Should report zero for empty directory."""
        from memory.cleanup import get_storage_stats

        stats = get_storage_stats(tmp_path)

        assert stats["exists"] is True
        assert stats["file_count"] == 0
        assert stats["memory_count"] == 0

    def test_stats_nonexistent_directory(self):
        """Should report not exists for missing directory."""
        from memory.cleanup import get_storage_stats

        stats = get_storage_stats(Path("/nonexistent/path"))

        assert stats["exists"] is False

    def test_stats_with_memories(self, tmp_path):
        """Should count memories and calculate size."""
        from memory.cleanup import get_storage_stats

        # Create a YAML memory file
        data = {
            "date": "2024-01-01",
            "decisions": [
                {"id": "dec1", "content": "Decision 1", "timestamp": "2024-01-01T10:00:00"},
                {"id": "dec2", "content": "Decision 2", "timestamp": "2024-01-01T11:00:00"},
            ],
            "learnings": [
                {"id": "learn1", "content": "Learning 1", "timestamp": "2024-01-01T12:00:00"},
            ],
        }
        (tmp_path / "2024-01-01.yaml").write_text(yaml.dump(data))

        stats = get_storage_stats(tmp_path)

        assert stats["file_count"] == 1
        assert stats["memory_count"] == 3  # 2 decisions + 1 learning
        assert stats["total_size_bytes"] > 0


class TestCleanupByAge:
    """Tests for age-based cleanup."""

    @pytest.fixture
    def memories_by_date(self, tmp_path):
        """Create YAML files with different dates."""
        today = datetime.utcnow()

        # Recent file (today)
        data_today = {
            "date": today.strftime("%Y-%m-%d"),
            "decisions": [{"id": "today1", "content": "Today", "timestamp": today.isoformat()}],
        }
        (tmp_path / f"{today.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data_today))

        # Old file (100 days ago)
        old_date = today - timedelta(days=100)
        data_old = {
            "date": old_date.strftime("%Y-%m-%d"),
            "decisions": [{"id": "old1", "content": "Old", "timestamp": old_date.isoformat()}],
        }
        (tmp_path / f"{old_date.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data_old))

        return tmp_path

    def test_age_cleanup_deletes_old_files(self, memories_by_date):
        """Should delete YAML files older than max_age_days."""
        from memory.cleanup import cleanup_by_age

        result = cleanup_by_age(memories_by_date, max_age_days=50, dry_run=False)

        # Old file should be deleted
        remaining = list(memories_by_date.glob("*.yaml"))
        assert len(remaining) == 1
        assert result["deleted_files"] == 1

    def test_age_cleanup_dry_run(self, memories_by_date):
        """Dry run should not delete files."""
        from memory.cleanup import cleanup_by_age

        result = cleanup_by_age(memories_by_date, max_age_days=50, dry_run=True)

        # Files should still exist
        remaining = list(memories_by_date.glob("*.yaml"))
        assert len(remaining) == 2
        assert result["dry_run"] is True
        assert result["would_delete_files"] == 1


class TestCleanupByCount:
    """Tests for count-based cleanup."""

    @pytest.fixture
    def many_memories(self, tmp_path):
        """Create YAML file with many memories."""
        base_date = datetime.utcnow()

        memories = []
        for i in range(10):
            memories.append(
                {
                    "id": f"mem{i}",
                    "content": f"Memory {i}",
                    "timestamp": (base_date - timedelta(hours=i)).isoformat(),
                }
            )

        data = {
            "date": base_date.strftime("%Y-%m-%d"),
            "decisions": memories,
        }
        (tmp_path / f"{base_date.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data))

        return tmp_path

    def test_count_cleanup_keeps_newest(self, many_memories):
        """Should keep newest N memories."""
        from memory.cleanup import cleanup_by_count

        result = cleanup_by_count(many_memories, max_memories=3, dry_run=False)

        # Should have deleted 7 memories
        assert result["deleted_memories"] == 7

        # Verify remaining
        remaining_file = list(many_memories.glob("*.yaml"))[0]
        with open(remaining_file) as f:
            data = yaml.safe_load(f)

        assert len(data["decisions"]) == 3

    def test_count_cleanup_dry_run(self, many_memories):
        """Dry run should not modify files."""
        from memory.cleanup import cleanup_by_count

        result = cleanup_by_count(many_memories, max_memories=3, dry_run=True)

        # Files should be unchanged
        remaining_file = list(many_memories.glob("*.yaml"))[0]
        with open(remaining_file) as f:
            data = yaml.safe_load(f)

        assert len(data["decisions"]) == 10
        assert result["dry_run"] is True
        assert result["would_delete"] == 7

    def test_count_cleanup_already_under_limit(self, many_memories):
        """Should do nothing if already under limit."""
        from memory.cleanup import cleanup_by_count

        result = cleanup_by_count(many_memories, max_memories=100, dry_run=False)

        assert result["deleted_memories"] == 0


class TestCleanupMemories:
    """Tests for the main cleanup function."""

    def test_cleanup_with_age_limit(self, tmp_path):
        """Should clean up by age."""
        from memory.cleanup import cleanup_memories

        today = datetime.utcnow()

        # Create recent file
        data_today = {
            "date": today.strftime("%Y-%m-%d"),
            "facts": [{"id": "f1", "content": "Recent", "timestamp": today.isoformat()}],
        }
        (tmp_path / f"{today.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data_today))

        # Create old file
        old_date = today - timedelta(days=100)
        data_old = {
            "date": old_date.strftime("%Y-%m-%d"),
            "facts": [{"id": "f2", "content": "Old", "timestamp": old_date.isoformat()}],
        }
        (tmp_path / f"{old_date.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data_old))

        result = cleanup_memories(
            storage_path=str(tmp_path),
            max_age_days=50,
            dry_run=False,
        )

        # Should have 1 file left
        remaining = list(tmp_path.glob("*.yaml"))
        assert len(remaining) == 1
        assert result["after"]["memory_count"] == 1

    def test_cleanup_dry_run(self, tmp_path):
        """Dry run should not modify anything."""
        from memory.cleanup import cleanup_memories

        today = datetime.utcnow()

        data = {
            "date": today.strftime("%Y-%m-%d"),
            "preferences": [
                {"id": "p1", "content": "Pref 1", "timestamp": today.isoformat()},
                {"id": "p2", "content": "Pref 2", "timestamp": today.isoformat()},
            ],
        }
        (tmp_path / f"{today.strftime('%Y-%m-%d')}.yaml").write_text(yaml.dump(data))

        result = cleanup_memories(
            storage_path=str(tmp_path),
            max_memories=1,
            dry_run=True,
        )

        # File should be unchanged
        with open(tmp_path / f"{today.strftime('%Y-%m-%d')}.yaml") as f:
            remaining = yaml.safe_load(f)

        assert len(remaining["preferences"]) == 2
        assert "by_count" in result
        assert result["by_count"]["dry_run"] is True
