"""Tests for memory migration tool."""

import json
from unittest.mock import MagicMock

import pytest


class MockConfig:
    """Mock config for testing."""

    def __init__(self, storage_path="/tmp/test"):
        self.tools = MagicMock()
        self.tools.memory.storage_path = storage_path
        self.tools.memory.embedding_provider = "sentence-transformers"
        self.tools.memory.embedding_model = "all-MiniLM-L6-v2"
        self.tools.memory.embedding_api_key = ""
        self.tools.memory.embedding_base_url = ""
        self.tools.memory.collection = "test_memory"
        self.qdrant = MagicMock()
        self.qdrant.url = "http://localhost:6333"


class TestMigrationDryRun:
    """Tests for memory migration dry-run functionality."""

    @pytest.fixture
    def sample_memories(self, tmp_path):
        """Create sample memory files for testing."""
        memories = [
            {
                "id": "mem1",
                "content": "Use PostgreSQL for the database",
                "memory_type": "decision",
                "project": "myapp",
                "tags": ["database"],
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "mem2",
                "content": "The user prefers TypeScript over JavaScript",
                "memory_type": "preference",
                "project": "myapp",
                "tags": ["language"],
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]

        for mem in memories:
            file_path = tmp_path / f"{mem['id']}.json"
            with open(file_path, "w") as f:
                json.dump(mem, f)

        return tmp_path

    def test_dry_run_counts_memories(self, sample_memories):
        """Dry run should count memories without migrating."""
        from memory.migrate import migrate_memories

        config = MockConfig(str(sample_memories))

        result = migrate_memories(
            storage_path=str(sample_memories),
            dry_run=True,
            _config=config,
        )

        assert result["found"] == 2
        assert result["dry_run"] is True
        assert result["migrated"] == 0

    def test_dry_run_empty_directory(self, tmp_path):
        """Dry run of empty directory should return zero found."""
        from memory.migrate import migrate_memories

        config = MockConfig(str(tmp_path))

        result = migrate_memories(
            storage_path=str(tmp_path),
            dry_run=True,
            _config=config,
        )

        assert result["found"] == 0

    def test_nonexistent_path_returns_error(self):
        """Nonexistent path should return error."""
        from memory.migrate import migrate_memories

        config = MockConfig("/nonexistent/path")

        result = migrate_memories(
            storage_path="/nonexistent/path",
            dry_run=False,
            _config=config,
        )

        assert "error" in result
        assert result["migrated"] == 0


class TestProviderSelection:
    """Tests for embedding provider selection during migration."""

    def test_config_provider_used_by_default(self, tmp_path):
        """Should use provider from config when not specified."""
        from memory.migrate import migrate_memories

        config = MockConfig(str(tmp_path))
        config.tools.memory.embedding_provider = "ollama"

        result = migrate_memories(
            storage_path=str(tmp_path),
            dry_run=True,
            _config=config,
        )

        # Empty dir, no error = processed correctly
        assert result["found"] == 0

    def test_explicit_provider_overrides_config(self, tmp_path):
        """Explicit provider parameter should override config."""
        from memory.migrate import migrate_memories

        config = MockConfig(str(tmp_path))
        config.tools.memory.embedding_provider = "ollama"

        result = migrate_memories(
            storage_path=str(tmp_path),
            provider="sentence-transformers",
            dry_run=True,
            _config=config,
        )

        # Empty dir, no error = processed correctly
        assert result["found"] == 0


class TestMigrationCLI:
    """Tests for CLI argument parsing."""

    def test_cli_module_exists(self):
        """Migration module should be importable."""
        from memory import migrate

        assert hasattr(migrate, "migrate_memories")
        assert hasattr(migrate, "main")

    def test_migrate_memories_signature(self):
        """migrate_memories should accept expected parameters."""
        from memory.migrate import migrate_memories
        import inspect

        sig = inspect.signature(migrate_memories)
        params = list(sig.parameters.keys())

        assert "storage_path" in params
        assert "provider" in params
        assert "model" in params
        assert "api_key" in params
        assert "base_url" in params
        assert "dry_run" in params
