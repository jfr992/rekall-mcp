"""Guard tests: the suite must be physically unable to reach production Qdrant."""

import pytest

from core.vector_store import VectorStore
from memory.manager import MemoryManager


def test_manager_default_url_is_test_qdrant(tmp_path):
    """With no explicit qdrant_url, a manager built inside a test must point at :6334."""
    manager = MemoryManager(memory_dir=tmp_path)
    assert "6334" in manager._qdrant_url, (
        f"MemoryManager defaulted to {manager._qdrant_url} — test isolation is broken"
    )


def test_connecting_to_production_qdrant_raises():
    """Explicitly pointing a store at :6333 inside a test must hard-fail."""
    store = VectorStore(collection="isolation-check", url="http://localhost:6333")
    with pytest.raises(RuntimeError, match="production Qdrant"):
        _ = store.client
