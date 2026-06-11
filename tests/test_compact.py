"""Tests for memory auto-compaction."""

from __future__ import annotations

from datetime import datetime, timedelta

import yaml


class TestGroupMemoriesForCompaction:
    """Test grouping logic for compaction."""

    def test_groups_by_project_and_type(self):
        """group_memories groups by project+type key."""
        from memory.compact import group_memories

        memories = [
            {
                "memory_id": "1",
                "content": "A",
                "project": "p1",
                "type": "decision",
                "date": "2026-01-01",
            },
            {
                "memory_id": "2",
                "content": "B",
                "project": "p1",
                "type": "decision",
                "date": "2026-01-02",
            },
            {
                "memory_id": "3",
                "content": "C",
                "project": "p1",
                "type": "learning",
                "date": "2026-01-03",
            },
            {
                "memory_id": "4",
                "content": "D",
                "project": "p2",
                "type": "decision",
                "date": "2026-01-04",
            },
        ]

        groups = group_memories(memories)

        assert ("p1", "decision") in groups
        assert ("p1", "learning") in groups
        assert ("p2", "decision") in groups
        assert len(groups[("p1", "decision")]) == 2
        assert len(groups[("p1", "learning")]) == 1

    def test_empty_list_returns_empty_groups(self):
        """Empty input returns empty groups."""
        from memory.compact import group_memories

        assert group_memories([]) == {}


class TestSelectOldMemories:
    """Test selection of memories older than threshold."""

    def test_selects_memories_older_than_days(self):
        """select_old_memories returns only memories past the age threshold."""
        from memory.compact import select_old_memories

        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

        memories = [
            {"memory_id": "old", "content": "Old one", "date": old, "type": "note", "project": "p"},
            {
                "memory_id": "new",
                "content": "New one",
                "date": today,
                "type": "note",
                "project": "p",
            },
        ]

        old_mems = select_old_memories(memories, older_than_days=30)

        ids = [m["memory_id"] for m in old_mems]
        assert "old" in ids
        assert "new" not in ids

    def test_excludes_already_compacted(self):
        """select_old_memories skips memories already marked compacted."""
        from memory.compact import select_old_memories

        old = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

        memories = [
            {
                "memory_id": "1",
                "content": "A",
                "date": old,
                "type": "note",
                "project": "p",
                "compacted": True,
            },
            {"memory_id": "2", "content": "B", "date": old, "type": "note", "project": "p"},
        ]

        old_mems = select_old_memories(memories, older_than_days=30)

        ids = [m["memory_id"] for m in old_mems]
        assert "1" not in ids
        assert "2" in ids

    def test_excludes_summaries(self):
        """select_old_memories skips memories of type 'summary'."""
        from memory.compact import select_old_memories

        old = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

        memories = [
            {
                "memory_id": "s1",
                "content": "Summary",
                "date": old,
                "type": "summary",
                "project": "p",
            },
            {"memory_id": "n1", "content": "Note", "date": old, "type": "note", "project": "p"},
        ]

        old_mems = select_old_memories(memories, older_than_days=30)

        ids = [m["memory_id"] for m in old_mems]
        assert "s1" not in ids
        assert "n1" in ids


class TestBuildCompactionPrompt:
    """Test LLM prompt building."""

    def test_prompt_includes_all_content(self):
        """build_compaction_prompt includes all memory content."""
        from memory.compact import build_compaction_prompt

        memories = [
            {"content": "Decision A: use Python", "type": "decision"},
            {"content": "Learning B: async is tricky", "type": "learning"},
        ]

        prompt = build_compaction_prompt(memories, project="my-app", mem_type="decision")

        assert "Decision A" in prompt
        assert "Learning B" in prompt
        assert "my-app" in prompt

    def test_prompt_is_non_empty(self):
        """build_compaction_prompt returns non-empty string."""
        from memory.compact import build_compaction_prompt

        memories = [{"content": "Something", "type": "note"}]
        prompt = build_compaction_prompt(memories, project="p", mem_type="note")

        assert len(prompt) > 20


class TestMarkCompactedInYaml:
    """Test YAML compaction flagging."""

    def test_marks_memories_as_compacted(self, tmp_path):
        """mark_compacted_in_yaml sets compacted=True on target IDs."""
        from memory.compact import mark_compacted_in_yaml

        old_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        yaml_file = tmp_path / f"{old_date}.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "date": old_date,
                    "notes": [
                        {"id": "m1", "content": "First note", "project": "p"},
                        {"id": "m2", "content": "Second note", "project": "p"},
                    ],
                }
            )
        )

        mark_compacted_in_yaml(
            memory_dir=tmp_path,
            memory_ids={"m1"},
            summary_id="summary_xyz",
        )

        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        notes = data["notes"]
        m1 = next(n for n in notes if n["id"] == "m1")
        m2 = next(n for n in notes if n["id"] == "m2")

        assert m1.get("compacted") is True
        assert m1.get("compacted_into") == "summary_xyz"
        assert "compacted" not in m2

    def test_does_not_touch_unrelated_memories(self, tmp_path):
        """mark_compacted_in_yaml ignores IDs not in the set."""
        from memory.compact import mark_compacted_in_yaml

        date = "2026-01-01"
        yaml_file = tmp_path / f"{date}.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "date": date,
                    "notes": [{"id": "keep_me", "content": "Keep", "project": "p"}],
                }
            )
        )

        mark_compacted_in_yaml(
            memory_dir=tmp_path,
            memory_ids={"unrelated_id"},
            summary_id="s1",
        )

        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        note = data["notes"][0]
        assert "compacted" not in note


class TestCompactDryRun:
    """Test dry-run compaction (no LLM, no Qdrant)."""

    def test_dry_run_returns_preview(self, tmp_path):
        """compact_memories dry_run=True returns groups without executing."""
        from memory.compact import compact_memories

        old_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
        memories = [
            {
                "memory_id": "m0",
                "content": "Old memory 0",
                "date": old_date,
                "type": "note",
                "project": "test",
            },
            {
                "memory_id": "m1",
                "content": "Old memory 1",
                "date": old_date,
                "type": "note",
                "project": "test",
            },
            {
                "memory_id": "new",
                "content": "New memory",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "type": "note",
                "project": "test",
            },
        ]

        result = compact_memories(memories, dry_run=True, older_than_days=30)

        assert result["dry_run"] is True
        assert result["groups"] >= 1
        assert result["memories_to_compact"] >= 2

    def test_dry_run_nothing_old_returns_zero(self):
        """dry_run with all-new memories returns zero to compact."""
        from memory.compact import compact_memories

        today = datetime.now().strftime("%Y-%m-%d")
        memories = [
            {"memory_id": "n1", "content": "New", "date": today, "type": "note", "project": "p"},
        ]

        result = compact_memories(memories, dry_run=True, older_than_days=30)

        assert result["memories_to_compact"] == 0
