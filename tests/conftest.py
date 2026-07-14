"""Pytest configuration and fixtures for Rekall MCP tests."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from core.utils import is_prod_qdrant_url as _is_production_qdrant_url
from memory import MemoryManager

HOST_TEST_QDRANT_URL = "http://localhost:6334"


def _resolve_test_qdrant_url() -> str:
    configured = os.environ.get("QDRANT_URL")
    if configured and not _is_production_qdrant_url(configured):
        return configured
    return HOST_TEST_QDRANT_URL


TEST_QDRANT_URL = _resolve_test_qdrant_url()


@pytest.fixture(autouse=True)
def _qdrant_isolation(monkeypatch):
    """Force every test toward the disposable test Qdrant and refuse :6333.

    Production Qdrant lives on :6333 (CLAUDE.md: tests must never touch it).
    """
    monkeypatch.setenv("QDRANT_URL", TEST_QDRANT_URL)

    from core.vector_store import VectorStore

    original_connect = VectorStore._connect

    def guarded_connect(self):
        if getattr(self, "path", None) is not None:
            # Embedded (local-path) mode never talks to a Qdrant server.
            return original_connect(self)
        if self.url in {HOST_TEST_QDRANT_URL, "http://127.0.0.1:6334"}:
            self.url = TEST_QDRANT_URL
        if _is_production_qdrant_url(self.url):
            raise RuntimeError(
                f"Test attempted to reach production Qdrant ({self.url}). "
                "Tests must use disposable Qdrant: localhost:6334 on the host "
                "or qdrant-test:6333 inside docker compose."
            )
        return original_connect(self)

    # expose the real method so tests can exercise the code-level guard directly
    guarded_connect.__wrapped__ = original_connect
    monkeypatch.setattr(VectorStore, "_connect", guarded_connect)


@pytest.fixture(autouse=True)
def _storage_isolation(tmp_path, monkeypatch):
    """Force default storage resolution toward tmp and refuse prod ~/.claude/memory.

    Code that resolves storage from MEMORY_STORAGE_PATH (singleton manager,
    server routes, CLI env fallbacks) gets a per-test tmp dir instead of prod.
    The shared singleton is reset so no test inherits another's storage path.
    """
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(tmp_path / "memory-store"))
    from memory import singleton

    singleton.reset_memory_manager()
    yield
    singleton.reset_memory_manager()


@pytest.fixture(autouse=True)
def _clean_integration_collection(request):
    """Give each integration test a fresh agent_memory collection.

    The test Qdrant is shared across the run; without this, save() dedups
    against memories left by earlier tests — which skips YAML writes and
    creates spurious supersedes edges. Only integration tests hit real Qdrant,
    so unit tests (which mock the store) are left untouched.
    """
    if request.node.get_closest_marker("integration"):
        from core.vector_store import VectorStore

        try:
            VectorStore(
                collection=MemoryManager.COLLECTION, url=TEST_QDRANT_URL
            ).recreate_collection()
        except Exception:
            pass
    yield


@pytest.fixture
def temp_memory_dir():
    """Create temporary memory directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def memory_manager(temp_memory_dir: Path) -> MemoryManager:
    """Create a MemoryManager instance for testing (test Qdrant only)."""
    return MemoryManager(memory_dir=temp_memory_dir, qdrant_url=TEST_QDRANT_URL)


@pytest.fixture
def sample_memory_entry() -> dict:
    """Sample memory entry for testing."""
    return {
        "id": "2026-02-01_decision_1234",
        "content": "Decided to use PostgreSQL for its JSON support",
        "project": "test-project",
        "timestamp": "2026-02-01T14:33:22.789012",
        "type": "decision",
        "tier": "working",
        "embedding_text": (
            "Project test-project. Type decision. Tier working. "
            "Entities: PostgreSQL. Claim: Decided to use PostgreSQL for its JSON support"
        ),
        "entities": ["PostgreSQL"],
        "repr_version": 2,
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


@pytest.fixture(autouse=True)
def _reset_scope_trust_cache():
    """Reset the scope detector's trust cache between tests so env var changes take effect."""
    try:
        from memory.scope import ScopeDetector

        ScopeDetector.reset_trust_cache()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        from memory.scope import ScopeDetector

        ScopeDetector.reset_trust_cache()
    except (ImportError, AttributeError):
        pass


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
