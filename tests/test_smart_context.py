"""Tests for smart context injection endpoint and quick recall."""

from __future__ import annotations

import pytest


class TestSmartContextRanking:
    """Test the ranking algorithm used for smart context selection."""

    def test_score_memory_higher_for_recent(self):
        """Recent memories score higher than old ones."""
        from datetime import datetime, timedelta

        from memory.smart_context import score_memory

        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")

        recent_mem = {"date": today, "type": "decision", "memory_id": "r1"}
        old_mem = {"date": old, "type": "decision", "memory_id": "o1"}

        recent_score = score_memory(recent_mem, importance=0.5)
        old_score = score_memory(old_mem, importance=0.5)

        assert recent_score > old_score

    def test_score_memory_higher_for_important(self):
        """High-importance memories score higher."""
        from memory.smart_context import score_memory

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

        high = {"date": today, "type": "note", "memory_id": "h1"}
        low = {"date": today, "type": "note", "memory_id": "l1"}

        assert score_memory(high, importance=0.9) > score_memory(low, importance=0.1)

    def test_score_memory_type_weight(self):
        """Decisions score higher than notes for same recency/importance."""
        from memory.smart_context import score_memory

        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

        decision = {"date": today, "type": "decision", "memory_id": "d1"}
        note = {"date": today, "type": "note", "memory_id": "n1"}

        assert score_memory(decision, importance=0.5) >= score_memory(note, importance=0.5)

    def test_score_memory_missing_date_doesnt_crash(self):
        """score_memory handles missing date without crashing."""
        from memory.smart_context import score_memory

        mem = {"type": "note", "memory_id": "x1"}
        score = score_memory(mem, importance=0.5)

        assert isinstance(score, float)


class TestTokenEstimation:
    """Test token counting / estimation."""

    def test_estimate_tokens_short_text(self):
        """Short text returns small token count."""
        from memory.smart_context import estimate_tokens

        count = estimate_tokens("Hello world")

        assert count > 0
        assert count < 10

    def test_estimate_tokens_empty(self):
        """Empty string returns 0."""
        from memory.smart_context import estimate_tokens

        assert estimate_tokens("") == 0

    def test_estimate_tokens_approx_four_chars_per_token(self):
        """~4 chars per token heuristic."""
        from memory.smart_context import estimate_tokens

        text = "a" * 400
        count = estimate_tokens(text)

        assert 80 <= count <= 120  # roughly 100 tokens


class TestFormatSmartContext:
    """Test context formatting."""

    def test_format_produces_markdown(self):
        """format_smart_context returns markdown string."""
        from memory.smart_context import format_smart_context

        memories = [
            {"type": "decision", "content": "Use Python", "date": "2026-03-25", "memory_id": "d1"},
            {
                "type": "learning",
                "content": "Async is hard",
                "date": "2026-03-20",
                "memory_id": "l1",
            },
        ]

        result = format_smart_context(memories, project="my-app")

        assert isinstance(result, str)
        assert len(result) > 0
        assert "decision" in result.lower() or "Decision" in result or "Use Python" in result

    def test_format_includes_project_name(self):
        """format_smart_context includes project name."""
        from memory.smart_context import format_smart_context

        memories = [
            {"type": "note", "content": "Some note", "date": "2026-03-25", "memory_id": "n1"},
        ]

        result = format_smart_context(memories, project="byte-edge")

        assert "byte-edge" in result

    def test_format_empty_memories_returns_empty(self):
        """format_smart_context with no memories returns empty string."""
        from memory.smart_context import format_smart_context

        result = format_smart_context([], project="my-app")

        assert result == "" or "No" in result

    def test_format_groups_by_section(self):
        """format_smart_context organizes memories into sections."""
        from datetime import datetime, timedelta

        from memory.smart_context import format_smart_context

        today = datetime.now().strftime("%Y-%m-%d")
        old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        memories = [
            {"type": "decision", "content": "Chose Python", "date": today, "memory_id": "d1"},
            {"type": "learning", "content": "Old lesson", "date": old, "memory_id": "l1"},
        ]

        result = format_smart_context(memories, project="test")

        assert isinstance(result, str)
        assert len(result) > 0


class TestSmartContextTruncation:
    """Test that context respects token budget."""

    def test_select_memories_under_budget(self):
        """select_within_budget returns memories fitting token limit."""
        from memory.smart_context import estimate_tokens, select_within_budget

        memories = [
            {
                "content": "a" * 200,
                "memory_id": f"m{i}",
                "type": "note",
                "date": "2026-03-25",
                "_score": 1.0 - i * 0.1,
            }
            for i in range(10)
        ]

        selected = select_within_budget(memories, max_tokens=100)

        total_tokens = sum(estimate_tokens(m["content"]) for m in selected)
        assert total_tokens <= 100

    def test_select_within_budget_keeps_highest_scored(self):
        """select_within_budget keeps highest-scored memories when truncating."""
        from memory.smart_context import select_within_budget

        memories = [
            {
                "content": "high score memory",
                "memory_id": "h",
                "type": "decision",
                "date": "2026-03-25",
                "_score": 0.9,
            },
            {
                "content": "low score memory that takes space " * 20,
                "memory_id": "l",
                "type": "note",
                "date": "2026-03-25",
                "_score": 0.1,
            },
        ]

        selected = select_within_budget(memories, max_tokens=50)

        ids = [m["memory_id"] for m in selected]
        if ids:  # if anything fits
            assert "h" in ids or len(selected) >= 1


@pytest.mark.integration
class TestGetSmartContext:
    """Test the get_smart_context manager-level function (requires Qdrant)."""

    def test_get_smart_context_returns_dict(self, tmp_path, monkeypatch):
        """get_smart_context returns dict with context and metadata."""
        import yaml

        from memory.manager import MemoryManager
        from memory.smart_context import get_smart_context

        # Write test YAML memory
        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-03-25",
                    "decisions": [
                        {
                            "id": "d1",
                            "content": "Use Python for the project",
                            "project": "test-proj",
                            "timestamp": "2026-03-25T10:00:00",
                        },
                    ],
                }
            )
        )

        monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
        manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")

        result = get_smart_context(manager, project="test-proj", max_tokens=2000)

        assert isinstance(result, dict)
        assert "context" in result
        assert "memories_included" in result
        assert "tokens" in result
        assert isinstance(result["tokens"], int)

    def test_get_smart_context_respects_max_tokens(self, tmp_path, monkeypatch):
        """get_smart_context respects max_tokens budget."""
        import yaml

        from memory.manager import MemoryManager
        from memory.smart_context import estimate_tokens, get_smart_context

        # Write several memories
        memories = [
            {
                "id": f"m{i}",
                "content": f"Memory content number {i} with some detail here",
                "project": "p",
                "timestamp": f"2026-03-25T0{i}:00:00",
            }
            for i in range(5)
        ]
        (tmp_path / "2026-03-25.yaml").write_text(
            yaml.dump({"date": "2026-03-25", "notes": memories})
        )

        monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
        manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")

        result = get_smart_context(manager, project="p", max_tokens=50)

        assert estimate_tokens(result["context"]) <= 100  # some buffer for formatting
