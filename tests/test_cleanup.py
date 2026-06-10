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


# =============================================================================
# MemoryManager.delete() tests
# =============================================================================


class TestMemoryManagerDelete:
    """Tests for MemoryManager.delete() method."""

    def test_delete_removes_from_yaml(self, tmp_path):
        """delete() should remove the entry from the YAML file."""
        data = {
            "date": "2026-04-01",
            "facts": [
                {"id": "2026-04-01_fact_aaa", "content": "Ran git commit", "project": "test", "timestamp": "2026-04-01T10:00:00"},
                {"id": "2026-04-01_fact_bbb", "content": "Ran go test", "project": "test", "timestamp": "2026-04-01T11:00:00"},
            ],
        }
        (tmp_path / "2026-04-01.yaml").write_text(yaml.dump(data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        result = manager.delete("2026-04-01_fact_aaa")

        assert result is True
        with open(tmp_path / "2026-04-01.yaml") as f:
            reloaded = yaml.safe_load(f)
        assert len(reloaded["facts"]) == 1
        assert reloaded["facts"][0]["id"] == "2026-04-01_fact_bbb"

    def test_delete_nonexistent_returns_false(self, tmp_path):
        """delete() should return False for unknown memory_id."""
        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        result = manager.delete("nonexistent_id")
        assert result is False

    def test_delete_removes_empty_yaml_file(self, tmp_path):
        """delete() should remove YAML file if it becomes empty."""
        data = {
            "date": "2026-04-01",
            "facts": [
                {"id": "2026-04-01_fact_only", "content": "Only entry", "project": "test", "timestamp": "2026-04-01T10:00:00"},
            ],
        }
        yaml_file = tmp_path / "2026-04-01.yaml"
        yaml_file.write_text(yaml.dump(data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        manager.delete("2026-04-01_fact_only")
        assert not yaml_file.exists()


# =============================================================================
# MemoryManager.cleanup() tests
# =============================================================================


class TestMemoryManagerCleanup:
    """Tests for MemoryManager.cleanup() method."""

    def test_cleanup_prunes_old_facts(self, tmp_path):
        """cleanup() should delete facts older than max_age_days."""
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        old_data = {
            "date": old_date,
            "facts": [
                {"id": f"{old_date}_fact_old1", "content": "Old fact", "project": "test", "timestamp": f"{old_date}T10:00:00"},
            ],
        }
        (tmp_path / f"{old_date}.yaml").write_text(yaml.dump(old_data))

        recent_data = {
            "date": recent_date,
            "facts": [
                {"id": f"{recent_date}_fact_new1", "content": "New fact", "project": "test", "timestamp": f"{recent_date}T10:00:00"},
            ],
            "decisions": [
                {"id": f"{recent_date}_decision_1", "content": "A decision", "project": "test", "timestamp": f"{recent_date}T11:00:00"},
            ],
        }
        (tmp_path / f"{recent_date}.yaml").write_text(yaml.dump(recent_data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        result = manager.cleanup(max_age_days_facts=7)

        assert result["facts_pruned"] == 1
        assert not (tmp_path / f"{old_date}.yaml").exists()
        with open(tmp_path / f"{recent_date}.yaml") as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 1
        assert len(data["decisions"]) == 1

    def test_cleanup_prunes_superseded(self, tmp_path):
        """cleanup() should delete memories superseded in the knowledge graph."""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "date": today,
            "preferences": [
                {"id": f"{today}_preference_old", "content": "Old preference", "project": "test", "timestamp": f"{today}T10:00:00"},
                {"id": f"{today}_preference_new", "content": "New preference", "project": "test", "timestamp": f"{today}T11:00:00"},
            ],
        }
        (tmp_path / f"{today}.yaml").write_text(yaml.dump(data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)

        manager.knowledge_graph.add_node(f"{today}_preference_old", memory_type="preference")
        manager.knowledge_graph.add_node(f"{today}_preference_new", memory_type="preference")
        manager.knowledge_graph.add_edge(f"{today}_preference_new", f"{today}_preference_old", relation="supersedes", weight=0.9)
        manager.knowledge_graph.save()

        result = manager.cleanup(prune_superseded=True)

        assert result["superseded_pruned"] == 1
        with open(tmp_path / f"{today}.yaml") as f:
            remaining = yaml.safe_load(f)
        assert len(remaining["preferences"]) == 1
        assert remaining["preferences"][0]["id"] == f"{today}_preference_new"

    def test_cleanup_flags_contradictions(self, tmp_path):
        """cleanup() should flag contradictions but not delete them."""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "date": today,
            "decisions": [
                {"id": f"{today}_decision_a", "content": "Use Postgres", "project": "test", "timestamp": f"{today}T10:00:00"},
                {"id": f"{today}_decision_b", "content": "Use MySQL", "project": "test", "timestamp": f"{today}T11:00:00"},
            ],
        }
        (tmp_path / f"{today}.yaml").write_text(yaml.dump(data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        manager.knowledge_graph.add_node(f"{today}_decision_a", memory_type="decision")
        manager.knowledge_graph.add_node(f"{today}_decision_b", memory_type="decision")
        manager.knowledge_graph.add_edge(f"{today}_decision_a", f"{today}_decision_b", relation="contradicts", weight=0.8)
        manager.knowledge_graph.save()

        result = manager.cleanup(prune_superseded=True)

        assert result["contradictions_flagged"] == 1
        assert len(result["contradictions"]) == 1
        with open(tmp_path / f"{today}.yaml") as f:
            remaining = yaml.safe_load(f)
        assert len(remaining["decisions"]) == 2

    def test_cleanup_dry_run(self, tmp_path):
        """cleanup(dry_run=True) should not delete anything."""
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        data = {
            "date": old_date,
            "facts": [
                {"id": f"{old_date}_fact_1", "content": "Old fact", "project": "test", "timestamp": f"{old_date}T10:00:00"},
            ],
        }
        yaml_file = tmp_path / f"{old_date}.yaml"
        yaml_file.write_text(yaml.dump(data))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        result = manager.cleanup(max_age_days_facts=7, dry_run=True)

        assert result["facts_pruned"] == 1
        assert result["dry_run"] is True
        assert yaml_file.exists()


# =============================================================================
# Integration test
# =============================================================================


@pytest.mark.integration
class TestCleanupIntegration:
    """Integration: save -> supersede -> cleanup -> verify gone."""

    def test_full_cleanup_flow(self, tmp_path):
        """Save memories, create supersedes, run cleanup, verify pruning."""
        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)

        # Save two preferences — new supersedes old
        old_id = manager.save("Prefer tabs over spaces", type="preference", project="test")
        new_id = manager.save("Prefer spaces over tabs (changed mind)", type="preference", project="test")

        # Create supersedes edge
        manager.knowledge_graph.add_edge(new_id, old_id, relation="supersedes", weight=0.9)
        manager.knowledge_graph.save()

        # Also save an old fact
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        old_fact_data = {
            "date": old_date,
            "facts": [
                {"id": f"{old_date}_fact_stale", "content": "Stale observation", "project": "test", "timestamp": f"{old_date}T10:00:00"},
            ],
        }
        (tmp_path / f"{old_date}.yaml").write_text(yaml.dump(old_fact_data))

        # Run cleanup
        result = manager.cleanup(max_age_days_facts=7, prune_superseded=True)

        assert result["facts_pruned"] == 1
        assert result["superseded_pruned"] >= 1  # auto-linker may create extra edges
        assert not (tmp_path / f"{old_date}.yaml").exists()

        # New preference should survive, old one deleted
        today = datetime.now().strftime("%Y-%m-%d")
        with open(tmp_path / f"{today}.yaml") as f:
            remaining = yaml.safe_load(f)
        preference_ids = [p["id"] for p in remaining.get("preferences", [])]
        assert new_id in preference_ids
        assert old_id not in preference_ids
