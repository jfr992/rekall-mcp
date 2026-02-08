"""Tests for memory CLI commands.

DRY: Reuses fixtures from test_memory.py via conftest import pattern.
TDD: Tests define expected CLI behavior.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_memory_manager():
    """Mock MemoryManager for CLI tests."""
    with patch("memory.cli.MemoryManager") as mock_class:
        manager = MagicMock()
        mock_class.return_value = manager

        # Default return values
        manager.save.return_value = "2026-02-01_note_1234"
        manager.recall.return_value = [
            {
                "score": 0.9,
                "content": "Test memory content",
                "date": "2026-02-01",
                "type": "decision",
                "project": "test-project",
            }
        ]
        manager.get_project_context.return_value = "# Project Context: test\n## Content"
        manager.get_stats.return_value = {
            "total_memories": 10,
            "memory_files": 5,
            "memory_dir": "/tmp/memory",
            "by_type": {"note": 5, "decision": 3, "learning": 2},
        }
        manager.save_session_summary.return_value = "2026-02-01_session_5678"

        yield manager


class TestSaveCommand:
    """Test the 'save' CLI command."""

    def test_save_basic(self, cli_runner, mock_memory_manager):
        """Basic save command should work."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["save", "Test content"])

        assert result.exit_code == 0
        assert "Saved" in result.output
        mock_memory_manager.save.assert_called_once()

    def test_save_with_type(self, cli_runner, mock_memory_manager):
        """Save with --type flag."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["save", "Decision made", "--type", "decision"])

        assert result.exit_code == 0
        mock_memory_manager.save.assert_called_with(
            "Decision made", type="decision", project=None
        )

    def test_save_with_project(self, cli_runner, mock_memory_manager):
        """Save with --project flag."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["save", "Content", "--project", "my-project"])

        assert result.exit_code == 0
        mock_memory_manager.save.assert_called_with(
            "Content", type="note", project="my-project"
        )

    def test_save_with_all_options(self, cli_runner, mock_memory_manager):
        """Save with all options."""
        from memory.cli import memory

        result = cli_runner.invoke(
            memory,
            ["save", "Full test", "-t", "learning", "-p", "test-proj"],
        )

        assert result.exit_code == 0
        mock_memory_manager.save.assert_called_with(
            "Full test", type="learning", project="test-proj"
        )


class TestRecallCommand:
    """Test the 'recall' CLI command."""

    def test_recall_basic(self, cli_runner, mock_memory_manager):
        """Basic recall command."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["recall", "architecture"])

        assert result.exit_code == 0
        assert "Test memory content" in result.output
        mock_memory_manager.recall.assert_called_once()

    def test_recall_with_limit(self, cli_runner, mock_memory_manager):
        """Recall with --limit flag."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["recall", "test", "--limit", "3"])

        assert result.exit_code == 0
        call_kwargs = mock_memory_manager.recall.call_args.kwargs
        assert call_kwargs.get("limit") == 3

    def test_recall_with_project_filter(self, cli_runner, mock_memory_manager):
        """Recall with --project filter."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["recall", "test", "-p", "my-project"])

        assert result.exit_code == 0
        call_kwargs = mock_memory_manager.recall.call_args.kwargs
        assert call_kwargs.get("project") == "my-project"

    def test_recall_no_results(self, cli_runner, mock_memory_manager):
        """Recall with no results should show message."""
        from memory.cli import memory

        mock_memory_manager.recall.return_value = []

        result = cli_runner.invoke(memory, ["recall", "nonexistent"])

        assert result.exit_code == 0
        assert "No relevant memories" in result.output

    def test_recall_shows_score(self, cli_runner, mock_memory_manager):
        """Recall output should show relevance score."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["recall", "test"])

        assert result.exit_code == 0
        assert "0.9" in result.output or "score" in result.output.lower()


class TestContextCommand:
    """Test the 'context' CLI command."""

    def test_context_returns_formatted(self, cli_runner, mock_memory_manager):
        """Context command returns project context."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["context", "my-project"])

        assert result.exit_code == 0
        assert "Project Context" in result.output
        mock_memory_manager.get_project_context.assert_called_with("my-project")

    def test_context_empty_project(self, cli_runner, mock_memory_manager):
        """Empty project context shows message."""
        from memory.cli import memory

        mock_memory_manager.get_project_context.return_value = ""

        result = cli_runner.invoke(memory, ["context", "nonexistent"])

        assert result.exit_code == 0
        assert "No stored context" in result.output


class TestStatsCommand:
    """Test the 'stats' CLI command."""

    def test_stats_shows_counts(self, cli_runner, mock_memory_manager):
        """Stats command shows memory counts."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["stats"])

        assert result.exit_code == 0
        assert "10" in result.output  # total_memories
        assert "5" in result.output  # memory_files

    def test_stats_shows_by_type(self, cli_runner, mock_memory_manager):
        """Stats shows breakdown by type."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["stats"])

        assert result.exit_code == 0
        assert "note" in result.output
        assert "decision" in result.output


class TestEndSessionCommand:
    """Test the 'end-session' CLI command."""

    def test_end_session_with_tasks(self, cli_runner, mock_memory_manager):
        """End session with tasks."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["end-session", "--tasks", "Task 1, Task 2"])

        assert result.exit_code == 0
        assert "Saved" in result.output or "saved" in result.output

    def test_end_session_with_all_fields(self, cli_runner, mock_memory_manager):
        """End session with all fields."""
        from memory.cli import memory

        result = cli_runner.invoke(
            memory,
            [
                "end-session",
                "--tasks",
                "Task 1",
                "--decisions",
                "Decision 1",
                "--learnings",
                "Learning 1",
                "--project",
                "test",
            ],
        )

        assert result.exit_code == 0
        mock_memory_manager.save_session_summary.assert_called_once()

    def test_end_session_empty(self, cli_runner, mock_memory_manager):
        """End session with no content."""
        from memory.cli import memory

        mock_memory_manager.save_session_summary.return_value = ""

        result = cli_runner.invoke(memory, ["end-session"])

        assert result.exit_code == 0
        assert "No content" in result.output


class TestClearCommand:
    """Test the 'clear' CLI command."""

    def test_clear_requires_confirmation(self, cli_runner, mock_memory_manager):
        """Clear should require confirmation."""
        from memory.cli import memory

        # Without --yes flag, should prompt (and fail in non-interactive)
        result = cli_runner.invoke(memory, ["clear", "test-project"])

        # Either prompts for confirmation or requires --yes
        assert result.exit_code != 0 or "Aborted" in result.output

    def test_clear_with_confirmation(self, cli_runner, mock_memory_manager):
        """Clear with --yes flag should proceed."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["clear", "test-project", "--yes"])

        assert result.exit_code == 0
        mock_memory_manager.clear_project.assert_called_with("test-project")


class TestGlobalOptions:
    """Test global CLI options."""

    def test_custom_memory_dir(self, cli_runner):
        """--memory-dir option should be passed to manager."""
        from memory.cli import memory

        with patch("memory.cli.MemoryManager") as mock_class:
            mock_class.return_value = MagicMock(
                get_stats=MagicMock(
                    return_value={
                        "total_memories": 0,
                        "memory_files": 0,
                        "memory_dir": "/custom/path",
                        "by_type": {},
                    }
                )
            )

            result = cli_runner.invoke(memory, ["--memory-dir", "/custom/path", "stats"])

            assert result.exit_code == 0
            mock_class.assert_called_with(
                memory_dir="/custom/path",
                qdrant_url="http://localhost:6333",
            )

    def test_custom_qdrant_url(self, cli_runner):
        """--qdrant-url option should be passed to manager."""
        from memory.cli import memory

        with patch("memory.cli.MemoryManager") as mock_class:
            mock_class.return_value = MagicMock(
                get_stats=MagicMock(
                    return_value={
                        "total_memories": 0,
                        "memory_files": 0,
                        "memory_dir": "/tmp",
                        "by_type": {},
                    }
                )
            )

            result = cli_runner.invoke(memory, ["--qdrant-url", "http://custom:6333", "stats"])

            assert result.exit_code == 0
            mock_class.assert_called_with(
                memory_dir="~/.claude/memory",
                qdrant_url="http://custom:6333",
            )
