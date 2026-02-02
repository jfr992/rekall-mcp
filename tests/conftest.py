"""Pytest configuration and fixtures for Memento MCP tests."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from memory import MemoryManager


@pytest.fixture
def temp_memory_dir():
    """Create temporary memory directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def memory_manager(temp_memory_dir: Path) -> MemoryManager:
    """Create a MemoryManager instance for testing."""
    return MemoryManager(memory_dir=temp_memory_dir)


@pytest.fixture
def sample_memory_entry() -> dict:
    """Sample memory entry for testing."""
    return {
        "id": "2026-02-01_decision_1234",
        "content": "Decided to use PostgreSQL for its JSON support",
        "project": "test-project",
        "timestamp": "2026-02-01T14:33:22.789012",
    }


@pytest.fixture
def sample_yaml_file(temp_memory_dir: Path, sample_memory_entry: dict) -> Path:
    """Create a sample YAML file for testing."""
    today = datetime.now().strftime("%Y-%m-%d")
    yaml_file = temp_memory_dir / f"{today}.yaml"

    data = {
        "date": today,
        "decisions": [sample_memory_entry],
        "learnings": [
            {
                "id": f"{today}_learning_5678",
                "content": "Fixed JWT validation bug with trailing slash",
                "project": "test-project",
                "timestamp": datetime.now().isoformat(),
            }
        ],
    }

    with open(yaml_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return yaml_file


@pytest.fixture
def tool_registry():
    """Registry for capturing tool registrations in tests.

    Returns a tuple of (capture_tool decorator, registered_tools dict).
    Used to test MCP tool registration without actual MCP server.
    """
    registered_tools = {}

    def capture_tool():
        """Decorator factory that captures registered tools."""

        def decorator(func):
            registered_tools[func.__name__] = func
            return func

        return decorator

    return capture_tool, registered_tools


@pytest.fixture
def mock_embedder():
    """Mock embedder for testing without loading actual models."""

    class MockEmbedder:
        """Fake embedder that returns consistent vectors."""

        def encode(self, text: str) -> list[float]:
            """Return a fake embedding based on text length."""
            # Different lengths for different texts to test similarity
            base = [0.1] * 384  # Standard embedding size
            # Vary slightly based on text to ensure uniqueness
            base[0] = len(text) / 100.0
            return base

    return MockEmbedder()


@pytest.fixture
def classification_samples() -> dict[str, list[str]]:
    """Sample texts for testing classification."""
    return {
        "decision": [
            "Decided to use PostgreSQL",
            "Going with React for the frontend",
            "Chose FastAPI over Flask",
        ],
        "learning": [
            "Fixed bug where JWT validation fails",
            "Discovered that API rate limits apply per IP",
            "Found out that CORS must be configured before routes",
        ],
        "preference": [
            "User prefers Terraform over CloudFormation",
            "Team likes pytest more than unittest",
            "Prefers async/await over callbacks",
        ],
        "requirement": [
            "Must use Python 3.11+",
            "Should support Docker deployment",
            "Must have API authentication",
        ],
        "fact": [
            "Database runs on port 5432",
            "API endpoint is /api/v1/users",
            "Server uses UTC timezone",
        ],
    }
