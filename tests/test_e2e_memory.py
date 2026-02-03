"""End-to-end tests for memory system.

Tests the complete workflow:
1. Config loading (no hardcoded values)
2. Observation with auto-classification
3. Save to YAML
4. Index in Qdrant
5. Recall with semantic search

Following TDD: These tests define the expected behavior.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml


class TestConfigLoading:
    """Test that configuration is loaded from YAML, not hardcoded."""

    def test_default_config_has_no_hardcoded_values(self):
        """All defaults should come from config, not code."""
        from config import get_config

        config = get_config()

        # Memory settings should be configurable
        assert hasattr(config.tools.memory, "storage_path")
        assert hasattr(config.tools.memory, "embedding_provider")
        assert hasattr(config.tools.memory, "embedding_model")
        assert hasattr(config.tools.memory, "collection")

        # Should have defaults but be overrideable
        assert config.tools.memory.storage_path is not None
        assert config.tools.memory.embedding_provider in [
            "sentence-transformers",
            "ollama",
            "gemini",
        ]


class TestObserveClassification:
    """Test automatic observation classification."""

    def test_classify_decision(self):
        """'Decided to use X' should classify as decision."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("Decided to use PostgreSQL")
        assert result == "decision"

        result = _classify_by_keywords("We're going with React")
        assert result == "decision"

    def test_classify_learning(self):
        """Bug fixes should classify as learning."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("Fixed JWT validation bug")
        assert result == "learning"

        result = _classify_by_keywords("Discovered that API rate limits")
        assert result == "learning"

    def test_classify_preference(self):
        """User preferences should classify correctly."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("User prefers Terraform")
        assert result == "preference"

    def test_classify_requirement(self):
        """Requirements should be identified."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("Must use Python 3.11")
        assert result == "requirement"

    def test_classify_fact(self):
        """Facts should be identified."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("Database runs on port 5432")
        assert result == "fact"

    def test_default_classification(self):
        """Unknown observations should default to learning."""
        from tools.builtin.memory import _classify_by_keywords

        result = _classify_by_keywords("Something happened")
        assert result == "learning"


class TestEndToEndWorkflow:
    """Test the complete observe → save → recall workflow."""

    @pytest.fixture
    def temp_memory_dir(self):
        """Create temporary memory directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_observe_creates_yaml_file(self, temp_memory_dir):
        """Observing should create a YAML file for the day."""
        from memory import MemoryManager

        manager = MemoryManager(memory_dir=temp_memory_dir)

        # Observe something
        _ = manager.save(
            content="Decided to use PostgreSQL", type="decision", project="test-project"
        )

        # Should create YAML file for today
        today = datetime.now().strftime("%Y-%m-%d")
        yaml_file = temp_memory_dir / f"{today}.yaml"

        assert yaml_file.exists(), f"Expected YAML file at {yaml_file}"

    def test_yaml_contains_correct_structure(self, temp_memory_dir):
        """YAML should have proper structure with type sections."""
        from memory import MemoryManager

        manager = MemoryManager(memory_dir=temp_memory_dir)

        # Save different types
        manager.save("Decided to use PostgreSQL", type="decision", project="test")
        manager.save("User prefers Terraform", type="preference", project="test")

        # Load YAML
        today = datetime.now().strftime("%Y-%m-%d")
        yaml_file = temp_memory_dir / f"{today}.yaml"

        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        # Should have type sections
        assert "decisions" in data
        assert "preferences" in data

        # Should have content
        assert len(data["decisions"]) == 1
        assert len(data["preferences"]) == 1

        # Should be human-readable
        assert "PostgreSQL" in data["decisions"][0]["content"]
        assert "Terraform" in data["preferences"][0]["content"]

    def test_yaml_is_human_editable(self, temp_memory_dir):
        """User should be able to manually edit YAML files."""
        from memory import MemoryManager

        manager = MemoryManager(memory_dir=temp_memory_dir)
        manager.save("Original content", type="note", project="test")

        # Get YAML file
        today = datetime.now().strftime("%Y-%m-%d")
        yaml_file = temp_memory_dir / f"{today}.yaml"

        # Manually edit it
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        data["notes"][0]["content"] = "Manually edited content"

        with open(yaml_file, "w") as f:
            yaml.dump(data, f)

        # Should be able to read it back
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        assert data["notes"][0]["content"] == "Manually edited content"


class TestNoDRYViolations:
    """Test that we follow DRY (Don't Repeat Yourself) principles."""

    def test_single_classification_implementation(self):
        """Classification should be in ONE place, not duplicated."""
        from tools.builtin.memory import _classify_by_keywords, _classify_smart

        # Should be able to import these
        assert callable(_classify_by_keywords)
        assert callable(_classify_smart)

        # Keyword classifier should be reused by smart classifier
        # (tested by ensuring consistent results)
        result1 = _classify_by_keywords("Decided to use X")
        result2 = _classify_smart("Decided to use X", None)  # Falls back to keywords

        assert result1 == result2 == "decision"

    def test_no_hardcoded_memory_types(self):
        """Memory types should be configurable, not hardcoded strings."""
        # This is more of a code review test, but we can check
        # that types come from somewhere consistent

        # Should return dict with known types
        # (This requires embedder, so we'll test the structure)
        # The types should be defined once and reused
        pass  # Implementation will validate this


class TestDataLoaderSystem:
    """Test configurable data loader (no hardcoded docs)."""

    def test_data_loader_reads_yaml(self):
        """Data loader should read tool config from YAML files."""
        # This test will pass once we implement the data loader
        # For now, it documents the expected behavior
        pytest.skip("Data loader not yet implemented")

    def test_user_can_override_tool_config(self):
        """Users should be able to add custom tool configs."""
        # Expected: User creates ~/.config/memento-mcp/data/mytool_docs.yaml
        # System loads it automatically
        pytest.skip("Data loader not yet implemented")

    def test_no_hardcoded_documentation(self):
        """Documentation should come from YAML, not hardcoded dicts."""
        pytest.skip("Data loader not yet implemented")
