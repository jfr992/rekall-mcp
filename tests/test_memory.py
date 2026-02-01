"""Tests for the memory system.

Following TDD principles - these tests define the expected behavior.
DRY: Uses fixtures and parametrization to avoid repetition.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# FIXTURES (DRY - reusable test components)
# =============================================================================


@pytest.fixture
def temp_memory_dir(tmp_path):
    """Create a temporary directory for memory storage."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return memory_dir


@pytest.fixture(autouse=True)
def reset_telemetry():
    """Reset telemetry singleton before each test."""
    from core.telemetry import Telemetry
    Telemetry.reset()
    yield
    Telemetry.reset()


@pytest.fixture
def mock_store():
    """Mock VectorStore."""
    with patch("memory.manager.VectorStore") as mock_class:
        store = MagicMock()
        mock_class.return_value = store
        store.count.return_value = 0
        yield store


@pytest.fixture
def mock_embedder():
    """Mock Embedder."""
    with patch("memory.manager.Embedder") as mock_class:
        embedder = MagicMock()
        mock_class.return_value = embedder
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        yield embedder


@pytest.fixture
def memory_manager(temp_memory_dir, mock_store, mock_embedder):
    """Create a MemoryManager with mocked dependencies."""
    from memory.manager import MemoryManager

    manager = MemoryManager(
        memory_dir=temp_memory_dir,
        qdrant_url="http://localhost:6333",
    )
    manager._store = mock_store
    manager._embedder = mock_embedder
    return manager


# =============================================================================
# SANITIZATION TESTS
# =============================================================================


class TestSanitization:
    """Test credential sanitization - critical for security."""

    @pytest.fixture
    def sanitizer(self):
        """Get sanitizer function."""
        from memory.manager import Sanitizer
        return Sanitizer.sanitize

    # DRY: Parametrize all credential patterns
    @pytest.mark.parametrize("secret,description", [
        # API Keys
        ("api_key=sk-abc123def456", "generic api_key"),
        ("apiKey: 'my-secret-key'", "camelCase apiKey"),
        ("API_KEY=\"test123\"", "uppercase API_KEY"),

        # Passwords
        ("password=mysecretpass", "password"),
        ("passwd: hunter2", "passwd"),
        ("pwd='secret123'", "pwd"),

        # Tokens
        ("token=abc123xyz", "generic token"),
        ("secret: my-secret-value", "secret"),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "bearer token"),
        ("Authorization: Basic dXNlcjpwYXNz", "basic auth"),

        # Provider-specific
        ("ghp_1234567890abcdef1234567890abcdef1234", "GitHub PAT"),
        ("gho_1234567890abcdef1234567890abcdef1234", "GitHub OAuth"),
        ("sk-1234567890abcdef1234567890abcdef1234567890abcdef", "OpenAI key"),
        ("sk-ant-abc123-def456", "Anthropic key"),
        ("xoxb-123-456-abc", "Slack bot token"),
        ("AKIAIOSFODNN7EXAMPLE", "AWS access key"),

        # PEM keys
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...base64...\n-----END RSA PRIVATE KEY-----", "RSA private key"),
        ("-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----", "generic private key"),
    ])
    def test_sanitizes_credentials(self, sanitizer, secret, description):
        """Each credential type should be redacted."""
        content = f"Here is my {description}: {secret}"
        sanitized = sanitizer(content)

        # Should not contain the original secret
        assert secret not in sanitized, f"Failed to sanitize {description}"
        # Should contain redaction marker
        assert "[REDACTED]" in sanitized

    def test_preserves_safe_content(self, sanitizer):
        """Normal content should not be modified."""
        safe_content = "This is a normal message about architecture decisions."
        assert sanitizer(safe_content) == safe_content

    def test_sanitizes_multiple_secrets(self, sanitizer):
        """Multiple secrets in one content should all be redacted."""
        content = """
        Config:
          api_key: secret123
          password: hunter2
          token: abc123
        """
        sanitized = sanitizer(content)

        assert "secret123" not in sanitized
        assert "hunter2" not in sanitized
        assert "abc123" not in sanitized
        assert sanitized.count("[REDACTED]") >= 3


# =============================================================================
# SAVE MEMORY TESTS
# =============================================================================


class TestSaveMemory:
    """Test memory saving functionality."""

    def test_save_creates_file(self, memory_manager, temp_memory_dir):
        """Saving a memory should create a JSONL file."""
        memory_manager.save_memory("Test content", memory_type="note", project="test")

        # Check file was created
        jsonl_files = list(temp_memory_dir.rglob("*.jsonl"))
        assert len(jsonl_files) == 1
        assert "notes.jsonl" in str(jsonl_files[0])

    def test_save_returns_memory_id(self, memory_manager):
        """save_memory should return a valid memory ID."""
        memory_id = memory_manager.save_memory("Test", memory_type="decision")

        assert memory_id is not None
        assert "decision" in memory_id
        # ID format: YYYY-MM-DD_type_hash
        parts = memory_id.split("_")
        assert len(parts) >= 3

    def test_save_stores_correct_metadata(self, memory_manager, temp_memory_dir):
        """Saved memory should have correct metadata."""
        memory_manager.save_memory(
            content="Architecture decision",
            memory_type="decision",
            project="my-project",
            metadata={"priority": "high"},
        )

        # Read the file
        jsonl_file = list(temp_memory_dir.rglob("*.jsonl"))[0]
        with open(jsonl_file) as f:
            data = json.loads(f.readline())

        assert data["content"] == "Architecture decision"
        assert data["metadata"]["type"] == "decision"
        assert data["metadata"]["project"] == "my-project"
        assert "date" in data["metadata"]
        assert "timestamp" in data["metadata"]

    def test_save_sanitizes_content(self, memory_manager, temp_memory_dir):
        """Saved content should be sanitized."""
        memory_manager.save_memory(
            content="My api_key=secret123 is here",
            memory_type="note",
        )

        # Read the file
        jsonl_file = list(temp_memory_dir.rglob("*.jsonl"))[0]
        with open(jsonl_file) as f:
            data = json.loads(f.readline())

        assert "secret123" not in data["content"]
        assert "[REDACTED]" in data["content"]

    def test_save_calls_store_save(self, memory_manager, mock_store):
        """Saving should call store.save()."""
        memory_manager.save_memory("Test content", memory_type="note")

        mock_store.save.assert_called_once()

    @pytest.mark.parametrize("memory_type", ["note", "decision", "learning", "preference", "session"])
    def test_save_different_types(self, memory_manager, temp_memory_dir, memory_type):
        """All memory types should be saveable."""
        memory_id = memory_manager.save_memory("Content", memory_type=memory_type)

        assert memory_type in memory_id
        # File should be named {type}s.jsonl
        jsonl_files = list(temp_memory_dir.rglob("*.jsonl"))
        assert f"{memory_type}s.jsonl" in str(jsonl_files[0])


# =============================================================================
# RECALL TESTS
# =============================================================================


class TestRecall:
    """Test memory recall functionality."""

    @pytest.fixture
    def memory_with_results(self, memory_manager, mock_store):
        """Setup mock to return search results."""
        mock_store.search.return_value = [
            {
                "score": 0.9,
                "content": "Architecture decision",
                "date": "2026-02-01",
                "type": "decision",
                "project": "test-project",
                "memory_id": "2026-02-01_decision_1234",
            },
            {
                "score": 0.7,
                "content": "Another memory",
                "date": "2026-01-31",
                "type": "note",
                "project": "test-project",
                "memory_id": "2026-01-31_note_5678",
            },
        ]
        return memory_manager

    def test_recall_returns_results(self, memory_with_results):
        """Recall should return matching memories."""
        results = memory_with_results.recall("architecture")

        assert len(results) == 2
        assert results[0]["score"] == 0.9
        assert results[0]["content"] == "Architecture decision"

    def test_recall_includes_all_fields(self, memory_with_results):
        """Each result should have all expected fields."""
        results = memory_with_results.recall("test")

        required_fields = ["score", "content", "date", "type", "project", "memory_id"]
        for result in results:
            for field in required_fields:
                assert field in result

    def test_recall_with_project_filter(self, memory_manager, mock_store):
        """Recall should filter by project when specified."""
        mock_store.search.return_value = []

        memory_manager.recall("test", project="my-project")

        call_args = mock_store.search.call_args
        assert call_args.kwargs.get("filters") == {"project": "my-project"}

    def test_recall_with_type_filter(self, memory_manager, mock_store):
        """Recall should filter by memory type when specified."""
        mock_store.search.return_value = []

        memory_manager.recall("test", type="decision")

        call_args = mock_store.search.call_args
        assert call_args.kwargs.get("filters") == {"type": "decision"}

    def test_recall_respects_limit(self, memory_manager, mock_store):
        """Recall should pass limit to store."""
        mock_store.search.return_value = []

        memory_manager.recall("test", limit=3)

        call_args = mock_store.search.call_args
        assert call_args.kwargs.get("limit") == 3

    def test_recall_empty_results(self, memory_manager, mock_store):
        """Recall should handle no results gracefully."""
        mock_store.search.return_value = []

        results = memory_manager.recall("nonexistent query")

        assert results == []


# =============================================================================
# SESSION SUMMARY TESTS
# =============================================================================


class TestSessionSummary:
    """Test session summary functionality."""

    def test_save_session_with_tasks(self, memory_manager, temp_memory_dir):
        """Session summary should include tasks."""
        memory_id = memory_manager.save_session_summary(
            tasks_completed=["Built API", "Added tests"],
            project="test",
        )

        assert memory_id != ""
        assert "session" in memory_id

        # Verify content
        jsonl_file = list(temp_memory_dir.rglob("sessions.jsonl"))[0]
        with open(jsonl_file) as f:
            data = json.loads(f.readline())

        assert "Built API" in data["content"]
        assert "Added tests" in data["content"]

    def test_save_session_with_all_fields(self, memory_manager, temp_memory_dir):
        """Session summary should include all provided fields."""
        memory_manager.save_session_summary(
            tasks_completed=["Task 1"],
            decisions_made=["Decision 1"],
            learnings=["Learning 1"],
            preferences=["Preference 1"],
            project="test",
        )

        jsonl_file = list(temp_memory_dir.rglob("sessions.jsonl"))[0]
        with open(jsonl_file) as f:
            data = json.loads(f.readline())

        assert "Tasks Completed" in data["content"]
        assert "Decisions" in data["content"]
        assert "Learnings" in data["content"]
        assert "Preferences" in data["content"]

    def test_save_session_empty_returns_empty(self, memory_manager):
        """Empty session summary should return empty string."""
        memory_id = memory_manager.save_session_summary()

        assert memory_id == ""


# =============================================================================
# PROJECT CONTEXT TESTS
# =============================================================================


class TestProjectContext:
    """Test project context retrieval."""

    def test_get_context_returns_formatted_string(self, memory_manager, mock_store):
        """Project context should return formatted markdown."""
        mock_store.scroll.return_value = [
            {
                "content": "Decision about architecture",
                "date": "2026-02-01",
                "type": "decision",
                "timestamp": "2026-02-01T10:00:00",
            }
        ]

        context = memory_manager.get_project_context("my-project")

        assert "# Project Context: my-project" in context
        assert "Decision about architecture" in context
        assert "2026-02-01" in context

    def test_get_context_empty_project(self, memory_manager, mock_store):
        """Empty project should return empty string."""
        mock_store.scroll.return_value = []

        context = memory_manager.get_project_context("nonexistent")

        assert context == ""


# =============================================================================
# STATS TESTS
# =============================================================================


class TestStats:
    """Test statistics functionality."""

    def test_stats_returns_required_fields(self, memory_manager, mock_store):
        """Stats should include all required fields."""
        mock_store.count.return_value = 10

        stats = memory_manager.get_stats()

        assert "total_memories" in stats
        assert "memory_files" in stats
        assert "memory_dir" in stats
        assert "by_type" in stats

    def test_stats_counts_files(self, memory_manager, temp_memory_dir, mock_store):
        """Stats should count JSONL files."""
        # Create some files
        (temp_memory_dir / "2026-02-01").mkdir()
        (temp_memory_dir / "2026-02-01" / "notes.jsonl").write_text('{"id": "1"}\n')
        (temp_memory_dir / "2026-02-01" / "decisions.jsonl").write_text('{"id": "2"}\n')

        stats = memory_manager.get_stats()

        assert stats["memory_files"] == 2

    def test_stats_handles_store_error(self, memory_manager, mock_store):
        """Stats should handle store errors gracefully."""
        mock_store.count.side_effect = Exception("Connection refused")

        stats = memory_manager.get_stats()

        assert stats["total_memories"] == 0  # Graceful fallback


# =============================================================================
# INTEGRATION TEST (with real Qdrant if available)
# =============================================================================


class TestTelemetryIntegration:
    """Test that telemetry is properly integrated."""

    def test_save_emits_telemetry(self, memory_manager):
        """save() should record telemetry."""
        from core import Telemetry

        memory_manager.save("Test content", type="note")

        metrics = Telemetry.get().get_operation("memory.save")
        assert metrics.count == 1

    def test_recall_emits_telemetry(self, memory_manager, mock_store):
        """recall() should record telemetry."""
        from core import Telemetry

        mock_store.search.return_value = []
        memory_manager.recall("test query")

        metrics = Telemetry.get().get_operation("memory.recall")
        assert metrics.count == 1


@pytest.mark.integration
class TestIntegration:
    """Integration tests - require real Qdrant server.

    Run with: pytest -m integration
    """

    @pytest.fixture(autouse=True)
    def reset_telemetry(self):
        """Reset telemetry singleton."""
        from core.telemetry import Telemetry
        Telemetry.reset()
        yield
        Telemetry.reset()

    @pytest.fixture
    def real_memory_manager(self, tmp_path):
        """Create manager with real dependencies."""
        from memory.manager import MemoryManager

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        return MemoryManager(
            memory_dir=memory_dir,
            qdrant_url="http://localhost:6333",
        )

    @pytest.mark.skip(reason="Requires running Qdrant server")
    def test_full_save_and_recall_cycle(self, real_memory_manager):
        """Test complete save -> recall cycle."""
        # Save
        memory_id = real_memory_manager.save(
            content="Integration test memory about architecture",
            type="decision",
            project="integration-test",
        )

        # Recall
        results = real_memory_manager.recall(
            query="architecture",
            project="integration-test",
        )

        assert len(results) > 0
        assert any("architecture" in r["content"].lower() for r in results)

        # Cleanup
        real_memory_manager.clear_project("integration-test")
