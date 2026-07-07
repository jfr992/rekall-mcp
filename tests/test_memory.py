"""Tests for the memory system.

Following TDD principles - these tests define the expected behavior.
DRY: Uses fixtures and parametrization to avoid repetition.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import yaml

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
    @pytest.mark.parametrize(
        "secret,description",
        [
            # API Keys
            ("api_key=sk-abc123def456", "generic api_key"),
            ("apiKey: 'my-secret-key'", "camelCase apiKey"),
            ('API_KEY="test123"', "uppercase API_KEY"),
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
            (
                "-----BEGIN RSA PRIVATE KEY-----\nMIIE...base64...\n-----END RSA PRIVATE KEY-----",
                "RSA private key",
            ),
            (
                "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----",
                "generic private key",
            ),
        ],
    )
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
        """Saving a memory should create a YAML file."""
        memory_manager.save("Test content", type="note", project="test")

        # Check file was created (daily YAML format)
        yaml_files = list(temp_memory_dir.rglob("*.yaml"))
        assert len(yaml_files) == 1
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in str(yaml_files[0])

    def test_save_returns_memory_id(self, memory_manager):
        """save() should return a valid memory ID."""
        memory_id = memory_manager.save("Test", type="decision")

        assert memory_id is not None
        assert "decision" in memory_id
        # ID format: YYYY-MM-DD_type_hash
        parts = memory_id.split("_")
        assert len(parts) >= 3

    def test_save_stores_correct_metadata(self, memory_manager, temp_memory_dir):
        """Saved memory should have correct metadata."""
        memory_manager.save(
            content="Architecture decision",
            type="decision",
            project="my-project",
            priority="high",
        )

        # Read the YAML file
        yaml_file = list(temp_memory_dir.rglob("*.yaml"))[0]
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        # Check decisions section exists with our memory
        assert "decisions" in data
        assert len(data["decisions"]) == 1
        memory = data["decisions"][0]
        assert memory["content"] == "Architecture decision"
        assert memory["project"] == "my-project"
        assert "timestamp" in memory

    def test_save_sanitizes_content(self, memory_manager, temp_memory_dir):
        """Saved content should be sanitized."""
        memory_manager.save(
            content="My api_key=secret123 is here",
            type="note",
        )

        # Read the YAML file
        yaml_file = list(temp_memory_dir.rglob("*.yaml"))[0]
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        content = data["notes"][0]["content"]
        assert "secret123" not in content
        assert "[REDACTED]" in content

    def test_save_calls_store_save(self, memory_manager, mock_store):
        """Saving should call store.save()."""
        memory_manager.save("Test content", type="note")

        mock_store.save.assert_called_once()

    def test_save_invokes_auto_link(self, memory_manager, mock_store, mock_embedder, monkeypatch):
        """Saving should run auto-link and persist graph updates."""
        graph = MagicMock()
        memory_manager._knowledge_graph = graph

        result = MagicMock(edges_created=2, relations={"related_to": 2})
        monkeypatch.setattr(
            "memory.manager.auto_link",
            lambda **_: result,
        )

        memory_manager.save("Test memory", type="decision", project="api")

        graph.add_node.assert_called_once()
        graph.save.assert_called_once()

    def test_save_continues_if_auto_link_fails(self, memory_manager, monkeypatch):
        """Auto-link exceptions should not break save."""
        graph = MagicMock()
        memory_manager._knowledge_graph = graph

        def _broken_link(**_kwargs):
            raise RuntimeError("linking unavailable")

        monkeypatch.setattr("memory.manager.auto_link", _broken_link)

        memory_id = memory_manager.save("Noisy save", type="note")

        assert memory_id is not None

    @pytest.mark.parametrize(
        "memory_type", ["note", "decision", "learning", "preference", "session"]
    )
    def test_save_different_types(self, memory_manager, temp_memory_dir, memory_type):
        """All memory types should be saveable."""
        memory_id = memory_manager.save("Content", type=memory_type)

        assert memory_type in memory_id
        # File should be daily YAML with type section
        yaml_files = list(temp_memory_dir.rglob("*.yaml"))
        assert len(yaml_files) == 1
        with open(yaml_files[0]) as f:
            data = yaml.safe_load(f)
        assert f"{memory_type}s" in data


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

        # Verify content in YAML file
        yaml_file = list(temp_memory_dir.rglob("*.yaml"))[0]
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        assert "sessions" in data
        content = data["sessions"][0]["content"]
        assert "Built API" in content
        assert "Added tests" in content

    def test_save_session_with_all_fields(self, memory_manager, temp_memory_dir):
        """Session summary should include all provided fields."""
        memory_manager.save_session_summary(
            tasks_completed=["Task 1"],
            decisions_made=["Decision 1"],
            learnings=["Learning 1"],
            preferences=["Preference 1"],
            project="test",
        )

        yaml_file = list(temp_memory_dir.rglob("*.yaml"))[0]
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        content = data["sessions"][0]["content"]
        assert "Tasks Completed" in content
        assert "Decisions" in content
        assert "Learnings" in content
        assert "Preferences" in content

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


class TestHierarchicalContext:
    """Test topic-aware context generation."""

    def test_get_hierarchical_project_context_from_vectors(self, memory_manager, mock_store):
        """Manager should build topic clusters from vector-backed points."""
        mock_store.scroll.return_value = [
            {
                "memory_id": "a",
                "content": "PostgreSQL index optimization",
                "type": "decision",
                "project": "api",
                "date": "2026-02-24",
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "memory_id": "b",
                "content": "PostgreSQL query tuning",
                "type": "learning",
                "project": "api",
                "date": "2026-02-23",
                "vector": [0.98, 0.01, 0.0],
            },
            {
                "memory_id": "c",
                "content": "UI palette contrast fix",
                "type": "note",
                "project": "api",
                "date": "2026-02-22",
                "vector": [-1.0, 0.0, 0.0],
            },
        ]

        context = memory_manager.get_hierarchical_project_context(project="api")

        assert "# Hierarchical Context" in context
        assert "postgre" in context.lower()
        call_args = mock_store.scroll.call_args.kwargs
        assert call_args["with_vectors"] is True
        assert call_args["filters"] == {"project": "api"}

    def test_hierarchical_project_context_empty(self, memory_manager, mock_store):
        """Empty store should return empty context string."""
        mock_store.scroll.return_value = []

        context = memory_manager.get_hierarchical_project_context(project="api")

        assert context == ""


class TestSkillContext:
    """Test inferred skill context generation."""

    def test_get_skill_context_extracts_repeated_terms(self, memory_manager, mock_store):
        """Manager should extract candidate skills from repeated terms."""
        mock_store.scroll.return_value = [
            {"memory_id": "a", "content": "Added PostgreSQL query plan optimization"},
            {"memory_id": "b", "content": "Migrated data model using PostgreSQL"},
            {"memory_id": "c", "content": "Refactored Redis caching strategy"},
        ]

        context = memory_manager.get_skill_context(project="api", min_mentions=2, max_skills=4)

        assert "## postgresql (2 mentions)" in context
        assert "# Skill Context: api" in context
        call_args = mock_store.scroll.call_args.kwargs
        assert call_args["filters"] == {"project": "api"}

    def test_get_skill_context_empty(self, memory_manager, mock_store):
        """Empty store returns empty string."""
        mock_store.scroll.return_value = []

        context = memory_manager.get_skill_context(project="api")

        assert context == ""


class TestIntelligenceLayer:
    """Test conflict detection and proactive summary tooling."""

    def test_save_creates_contradiction_edge(self, memory_manager, mock_store):
        """Saving a contradiction should create a `contradicts` edge."""
        from memory.knowledge_graph import KnowledgeGraph

        memory_manager._knowledge_graph = KnowledgeGraph(memory_manager.memory_dir / "_graph.json")
        memory_manager._knowledge_graph.add_node(
            "old_decision", topic="api", memory_type="decision"
        )

        mock_store.search.return_value = [
            {
                "memory_id": "old_decision",
                "type": "decision",
                "content": "Use Redis cache for sessions",
                "score": 0.88,
            },
        ]

        memory_id = memory_manager.save(
            content="Do not use Redis cache for sessions",
            type="decision",
            project="api",
        )

        graph_edges = memory_manager._knowledge_graph.get_edges(memory_id, direction="out")
        assert any(
            edge.target == "old_decision" and edge.relation == "contradicts" for edge in graph_edges
        )

    def test_consolidate_memories_reports_signals(self, memory_manager, mock_store):
        """Consolidation should report supersedes and contradictions."""
        from memory.knowledge_graph import KnowledgeGraph

        graph = KnowledgeGraph(memory_manager.memory_dir / "_graph.json")
        memory_manager._knowledge_graph = graph

        graph.add_node("old", topic="api", memory_type="decision")
        graph.add_node("new", topic="api", memory_type="decision")
        graph.add_node("conflict_a", topic="api", memory_type="decision")
        graph.add_node("conflict_b", topic="api", memory_type="decision")

        graph.add_edge("new", "old", "supersedes", weight=0.9)
        graph.add_edge("conflict_a", "conflict_b", "contradicts", weight=0.82)

        mock_store.scroll.return_value = [
            {
                "memory_id": "old",
                "project": "api",
                "type": "decision",
                "content": "Old decision to cache in Redis",
            },
            {
                "memory_id": "new",
                "project": "api",
                "type": "decision",
                "content": "New decision to cache in Redis via RedisJSON",
            },
            {
                "memory_id": "conflict_a",
                "project": "api",
                "type": "decision",
                "content": "Do not cache responses on hot path",
            },
            {
                "memory_id": "conflict_b",
                "project": "api",
                "type": "decision",
                "content": "Cache responses aggressively on hot path",
            },
        ]

        report = memory_manager.consolidate_memories(project="api")

        assert "Memory Consolidation: api" in report
        assert "Superseded Memories" in report
        assert "old" in report
        assert "Conflicting Memories" in report

    def test_consolidate_deduplicates_bidirectional_pairs(self, memory_manager, mock_store):
        """Consolidation should not report A→B and B→A as separate entries."""
        from memory.knowledge_graph import KnowledgeGraph

        graph = KnowledgeGraph(memory_manager.memory_dir / "_graph.json")
        memory_manager._knowledge_graph = graph

        graph.add_node("mem_a", topic="api", memory_type="decision")
        graph.add_node("mem_b", topic="api", memory_type="decision")

        # Create bidirectional contradicts edges (as the linker + rebuild can)
        graph.add_edge("mem_a", "mem_b", "contradicts", weight=0.80)
        graph.add_edge("mem_b", "mem_a", "contradicts", weight=0.80)

        mock_store.scroll.return_value = [
            {
                "memory_id": "mem_a",
                "project": "api",
                "type": "decision",
                "content": "Use EST timezone",
            },
            {
                "memory_id": "mem_b",
                "project": "api",
                "type": "decision",
                "content": "Use UTC timezone",
            },
        ]

        report = memory_manager.consolidate_memories(project="api")

        # The pair should appear exactly once, not twice
        conflict_count = report.count("may conflict")
        assert conflict_count == 1, f"Expected 1 conflict entry, got {conflict_count}"

    def test_get_proactive_context_summary_prioritizes_signals(self, memory_manager, mock_store):
        """Proactive summary should include top signals and conflict section."""
        from memory.knowledge_graph import KnowledgeGraph

        graph = KnowledgeGraph(memory_manager.memory_dir / "_graph.json")
        memory_manager._knowledge_graph = graph

        now = datetime.now().strftime("%Y-%m-%d")
        graph.add_node("high", topic="api", memory_type="decision")
        graph._graph.nodes["high"]["importance"] = 0.99
        graph.add_node("old", topic="api", memory_type="decision")
        graph._graph.nodes["old"]["importance"] = 0.3
        graph.add_edge("old", "high", "contradicts", weight=0.9)

        mock_store.scroll.return_value = [
            {
                "memory_id": "high",
                "project": "api",
                "type": "decision",
                "content": "Use strict authentication for all endpoints",
                "date": now,
            },
            {
                "memory_id": "old",
                "project": "api",
                "type": "decision",
                "content": "Allow anonymous access to staging endpoint",
                "date": now,
            },
        ]

        report = memory_manager.get_proactive_context_summary(project="api")

        assert "Proactive Context: api" in report
        assert "Top Signals" in report
        assert "Conflicts to Review" in report
        top_signals_section = report.split("Top Signals")[1]
        assert top_signals_section.index("high") < top_signals_section.index("old")


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
        """Stats should count YAML files and memories by type."""
        import yaml

        # Create YAML files (current format)
        (temp_memory_dir / "2026-02-01.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-02-01",
                    "notes": [{"id": "1", "content": "note 1"}],
                    "decisions": [{"id": "2", "content": "decision 1"}],
                }
            )
        )
        (temp_memory_dir / "2026-02-02.yaml").write_text(
            yaml.dump(
                {
                    "date": "2026-02-02",
                    "preferences": [{"id": "3", "content": "pref 1"}],
                }
            )
        )

        stats = memory_manager.get_stats()

        assert stats["memory_files"] == 2
        assert stats["by_type"]["note"] == 1
        assert stats["by_type"]["decision"] == 1
        assert stats["by_type"]["preference"] == 1

    def test_stats_handles_store_error(self, memory_manager, mock_store):
        """Stats should handle store errors gracefully."""
        mock_store.count.side_effect = Exception("Connection refused")

        stats = memory_manager.get_stats()

        assert stats["total_memories"] == 0  # Graceful fallback

    def test_stats_includes_knowledge_graph_metrics(self, memory_manager, mock_store):
        """Stats should include knowledge graph node/edge counts."""
        mock_store.count.return_value = 5

        # Add some nodes and edges to the graph
        kg = memory_manager.knowledge_graph
        kg.add_node("a", memory_type="decision")
        kg.add_node("b", memory_type="learning")
        kg.add_edge("a", "b", "led_to", weight=0.8)

        stats = memory_manager.get_stats()

        assert "knowledge_graph" in stats
        assert stats["knowledge_graph"]["nodes"] == 2
        assert stats["knowledge_graph"]["edges"] == 1
        assert "relations" in stats["knowledge_graph"]

    def test_stats_graph_metrics_empty_when_no_graph(self, memory_manager, mock_store):
        """Stats should show 0 nodes/edges when graph is empty."""
        mock_store.count.return_value = 0

        stats = memory_manager.get_stats()

        assert stats["knowledge_graph"]["nodes"] == 0
        assert stats["knowledge_graph"]["edges"] == 0


# =============================================================================
# BUG FIX TESTS (Phase 2)
# =============================================================================


class TestAtomicYamlWrites:
    """2a: YAML writes should be atomic (crash-safe)."""

    def test_rapid_saves_produce_valid_yaml(self, memory_manager, temp_memory_dir):
        """Writing 10 memories rapidly should always produce valid YAML."""
        for i in range(10):
            memory_manager.save(f"Memory number {i}", type="note")

        yaml_files = list(temp_memory_dir.rglob("*.yaml"))
        assert len(yaml_files) >= 1
        for yf in yaml_files:
            with open(yf) as f:
                data = yaml.safe_load(f)
            assert data is not None
            assert "notes" in data

    def test_no_temp_files_remain(self, memory_manager, temp_memory_dir):
        """After saves complete, no .tmp files should linger."""
        memory_manager.save("Test content", type="note")

        tmp_files = list(temp_memory_dir.rglob("*.tmp"))
        assert len(tmp_files) == 0


class TestSanitizerFalsePositives:
    """2b: Sanitizer should not corrupt legitimate hex content."""

    @pytest.fixture
    def sanitizer(self):
        from memory.manager import Sanitizer

        return Sanitizer.sanitize

    def test_preserves_md5_hashes(self, sanitizer):
        content = "File checksum: d41d8cd98f00b204e9800998ecf8427e"
        assert sanitizer(content) == content

    def test_preserves_uuids(self, sanitizer):
        content = "Request ID: 550e8400e29b41d4a716446655440000"
        assert sanitizer(content) == content

    def test_preserves_git_shas(self, sanitizer):
        content = "Commit 043c50e fix: Isolate test environment"
        assert sanitizer(content) == content

    def test_still_catches_hex_keys_with_context(self, sanitizer):
        content = "secret=d41d8cd98f00b204e9800998ecf8427e"
        sanitized = sanitizer(content)
        assert "d41d8cd98f00b204e9800998ecf8427e" not in sanitized
        assert "[REDACTED]" in sanitized


class TestMemoryManagerSingleton:
    """2c: REST API should reuse the same MemoryManager instance."""

    def test_get_memory_manager_returns_same_instance(self):
        pytest.importorskip("mcp", reason="mcp package not installed locally")
        # Reset singleton
        import memory.singleton as _ms
        import server

        _ms._instance = None
        try:
            m1 = server._get_memory_manager()
            m2 = server._get_memory_manager()
            assert m1 is m2
        finally:
            import memory.singleton as _ms

            _ms._instance = None


class TestCliRecallType:
    """2d: CLI recall should pass type= not memory_type=."""

    def test_recall_passes_type_not_memory_type(self):
        """Verify the CLI source uses `type=memory_type`."""
        from pathlib import Path

        import memory.cli

        source = Path(memory.cli.__file__).read_text()
        # The recall function body should use type= not memory_type=
        assert "type=memory_type," in source
        assert "memory_type=memory_type," not in source


class TestCliSaveAlias:
    """2e: CLI save should use mgr.save() not mgr.save_memory()."""

    def test_save_uses_save_not_save_memory(self):
        from pathlib import Path

        import memory.cli

        source = Path(memory.cli.__file__).read_text()
        assert "mgr.save(" in source
        assert "mgr.save_memory(" not in source


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
            qdrant_url="http://localhost:6334",
        )

    @pytest.mark.integration
    def test_full_save_and_recall_cycle(self, real_memory_manager):
        """Test complete save -> recall cycle."""
        # Save
        _ = real_memory_manager.save(
            content="Integration test memory about architecture",
            type="decision",
            project="integration-test",
        )

        # Recall — single-word query scores ~0.4, so lower the gate below the
        # 0.45 default; this test exercises the save->recall round-trip, not
        # relevance tuning.
        results = real_memory_manager.recall(
            query="architecture",
            project="integration-test",
            score_threshold=0.3,
        )

        assert len(results) > 0
        assert any("architecture" in r["content"].lower() for r in results)

        # Cleanup
        real_memory_manager.clear_project("integration-test")
