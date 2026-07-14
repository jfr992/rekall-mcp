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
        mock_memory_manager.save.assert_called_with("Decision made", type="decision", project=None)

    def test_save_with_project(self, cli_runner, mock_memory_manager):
        """Save with --project flag."""
        from memory.cli import memory

        result = cli_runner.invoke(memory, ["save", "Content", "--project", "my-project"])

        assert result.exit_code == 0
        mock_memory_manager.save.assert_called_with("Content", type="note", project="my-project")

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


class TestServeCommand:
    """Test the 'serve' CLI command (daemon tier over the embedded store)."""

    def test_serve_refuses_when_daemon_already_running(self, cli_runner, monkeypatch, tmp_path):
        from core.ownership import Acquisition
        from memory.cli import memory

        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        monkeypatch.setattr(
            "core.ownership.acquire",
            lambda *a, **k: Acquisition(mode="daemon", base_url="http://127.0.0.1:8000"),
        )

        result = cli_runner.invoke(memory, ["serve"])

        assert result.exit_code == 2
        assert "already running" in result.output

    def test_serve_embedded_sets_env_defaults_and_runs_server(
        self, cli_runner, monkeypatch, tmp_path
    ):
        import os

        import server
        from core.ownership import Acquisition
        from memory.cli import memory

        rekall_dir = tmp_path / "rekall"
        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.delenv("QDRANT_PATH", raising=False)
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")  # serve must force streamable-http
        # setenv-then-delenv registers HOST-was-absent for restore (serve sets it).
        monkeypatch.setenv("HOST", "sentinel")
        monkeypatch.delenv("HOST")
        monkeypatch.setenv("REKALL_DIR", str(rekall_dir))
        monkeypatch.setattr(
            "core.ownership.acquire",
            lambda *a, **k: Acquisition(mode="embedded", path=rekall_dir / "qdrant"),
        )
        ran = []
        monkeypatch.setattr(server, "main", lambda: ran.append(True))

        result = cli_runner.invoke(memory, ["serve"])

        assert result.exit_code == 0, result.output
        assert ran == [True]
        assert os.environ["MCP_TRANSPORT"] == "streamable-http"
        assert os.environ["HOST"] == "127.0.0.1"
        assert os.environ["QDRANT_PATH"] == str(rekall_dir / "qdrant")

    def test_serve_with_qdrant_url_never_defaults_qdrant_path(
        self, cli_runner, monkeypatch, tmp_path
    ):
        import os

        import server
        from memory.cli import memory

        monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
        monkeypatch.delenv("QDRANT_PATH", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        monkeypatch.setattr("core.ownership.probe_daemon", lambda *a, **k: "absent")
        ran = []
        monkeypatch.setattr(server, "main", lambda: ran.append(True))

        result = cli_runner.invoke(memory, ["serve"])

        assert result.exit_code == 0, result.output
        assert ran == [True]
        assert "QDRANT_PATH" not in os.environ

    def test_serve_with_qdrant_url_writes_url_ownership_record(
        self, cli_runner, monkeypatch, tmp_path
    ):
        """serve in url mode must own the YAML store on record — a later
        embedded acquire against the same rekall_dir has to see it and refuse."""
        import json

        import server
        from memory.cli import memory

        rekall_dir = tmp_path / "rekall"
        monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
        monkeypatch.delenv("QDRANT_PATH", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(rekall_dir))
        monkeypatch.setattr("core.ownership.probe_daemon", lambda *a, **k: "absent")
        monkeypatch.setattr(server, "main", lambda: None)

        result = cli_runner.invoke(memory, ["serve"])

        assert result.exit_code == 0, result.output
        record = json.loads((rekall_dir / "active-backend.json").read_text())
        assert record["backend"] == "url"
        assert record["target"] == "http://localhost:6334"


class TestWarmupCommand:
    """Test the 'warmup' CLI command (model pre-download)."""

    def test_warmup_encodes_once_and_prints_cache_location(self, cli_runner, monkeypatch):
        from memory.cli import memory

        encoded = []

        class _FakeEmbedder:
            provider_name = "fastembed"
            model_name = "all-MiniLM-L6-v2"

            def __init__(self, *a, **k):
                pass

            def encode(self, text):
                encoded.append(text)
                return [0.0] * 384

        monkeypatch.setattr("core.embeddings.Embedder", _FakeEmbedder)
        monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/tmp/fe-cache")

        result = cli_runner.invoke(memory, ["warmup"])

        assert result.exit_code == 0, result.output
        assert len(encoded) == 1
        assert "fastembed" in result.output
        assert "/tmp/fe-cache" in result.output


class TestReindexCommand:
    """Test the 'reindex' CLI command (ownership-gated rebuild)."""

    def test_reindex_refuses_when_daemon_running(self, cli_runner, monkeypatch, tmp_path):
        from core.ownership import Acquisition
        from memory.cli import memory

        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        monkeypatch.setattr(
            "core.ownership.acquire",
            lambda *a, **k: Acquisition(mode="daemon", base_url="http://127.0.0.1:8000"),
        )

        result = cli_runner.invoke(memory, ["reindex"])

        assert result.exit_code == 2
        assert "daemon is running" in result.output

    def test_reindex_embedded_rebuilds_and_reports(self, cli_runner, monkeypatch, tmp_path):
        from core.ownership import Acquisition
        from memory.cli import memory

        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        monkeypatch.setattr(
            "core.ownership.acquire",
            lambda *a, **k: Acquisition(mode="embedded", path=tmp_path / "rekall" / "qdrant"),
        )

        result = cli_runner.invoke(memory, ["reindex", "--tarball-dir", str(tmp_path / "backups")])

        assert result.exit_code == 0, result.output
        assert '"points": 0' in result.output
        assert '"verified": true' in result.output
        assert list((tmp_path / "backups").glob("*.tar.gz")), "tarballs must be written"

    def test_reindex_embedded_reuses_acquire_client(self, cli_runner, monkeypatch, tmp_path):
        """Real acquire holds the embedded flock through its client; the reindex
        manager must reuse it — a second client on the same path is refused."""
        from memory.cli import memory

        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.delenv("QDRANT_PATH", raising=False)
        monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
        monkeypatch.setenv("MEMORY_STORAGE_PATH", str(tmp_path / "memory"))
        monkeypatch.setattr("core.ownership.probe_daemon", lambda *a, **k: "absent")

        connected = []
        monkeypatch.setattr(
            "memory.reindex.reindex",
            lambda mgr, tarball_dir=None: connected.append(mgr.store.client) or {"ok": True},
        )

        result = cli_runner.invoke(memory, ["reindex"])

        assert result.exit_code == 0, result.output
        assert connected, "reindex body never touched the store"
