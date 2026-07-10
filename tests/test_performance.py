"""Tests for Phase 4 performance improvements."""

from unittest.mock import MagicMock

import pytest

# =============================================================================
# 4a: Embedding cache
# =============================================================================


class TestEmbeddingCache:
    """Embedder.encode() should cache results and skip redundant model calls."""

    @pytest.fixture(autouse=True)
    def reset_telemetry(self):
        from core.telemetry import Telemetry

        Telemetry.reset()
        yield
        Telemetry.reset()

    def test_cache_returns_identical_vector(self):
        """Same text encoded twice returns identical vector."""
        from core.embeddings import Embedder

        mock_provider = MagicMock()
        mock_provider.encode.return_value = [0.1, 0.2, 0.3]

        embedder = Embedder()
        embedder._provider = mock_provider

        v1 = embedder.encode("hello")
        v2 = embedder.encode("hello")
        assert v1 == v2

    def test_cache_calls_provider_once(self):
        """Provider.encode() should only be called once for repeated text."""
        from core.embeddings import Embedder

        mock_provider = MagicMock()
        mock_provider.encode.return_value = [0.1, 0.2, 0.3]

        embedder = Embedder()
        embedder._provider = mock_provider

        embedder.encode("hello")
        embedder.encode("hello")
        mock_provider.encode.assert_called_once_with("hello")

    def test_cache_evicts_oldest(self):
        """Cache should evict oldest entry when exceeding max size."""
        from core.embeddings import Embedder

        mock_provider = MagicMock()
        mock_provider.encode.side_effect = lambda t: [float(hash(t) % 100)]

        embedder = Embedder()
        embedder._provider = mock_provider
        embedder._cache_max = 3

        embedder.encode("a")
        embedder.encode("b")
        embedder.encode("c")
        embedder.encode("d")  # Should evict "a"

        assert "a" not in embedder._cache
        assert "d" in embedder._cache


# =============================================================================
# 4b: numpy cosine similarity
# =============================================================================


class TestNumpyCosine:
    """Cosine similarity should match reference values and handle edge cases."""

    def test_identical_vectors_score_one(self):
        from tools.builtin.memory import _cosine_similarity

        vec = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 1e-6

    def test_orthogonal_vectors_score_zero(self):
        from tools.builtin.memory import _cosine_similarity

        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_opposite_vectors_score_negative(self):
        from tools.builtin.memory import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) < 0

    def test_handles_zero_vectors(self):
        from tools.builtin.memory import _cosine_similarity

        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert _cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0


# =============================================================================
# 4c: Multi-example centroids
# =============================================================================


class TestCentroidClassification:
    """Classification should work correctly with centroid embeddings."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset the type embeddings cache before each test."""
        import tools.builtin.memory as mem_mod

        mem_mod._TYPE_EMBEDDINGS_CACHE = None
        yield
        mem_mod._TYPE_EMBEDDINGS_CACHE = None

    @pytest.fixture(autouse=True)
    def reset_telemetry(self):
        from core.telemetry import Telemetry

        Telemetry.reset()
        yield
        Telemetry.reset()

    def test_classification_returns_valid_types(self):
        from tools.builtin.memory import _classify_by_embedding

        mock_embedder = MagicMock()
        # Return distinct vectors for different types of content
        call_count = [0]

        def mock_encode(text):
            call_count[0] += 1
            # Return a unique vector per call
            return [float(call_count[0])] * 10

        mock_embedder.encode.side_effect = mock_encode

        result = _classify_by_embedding("Decided to use Python", mock_embedder)
        assert result in {"decision", "learning", "preference", "requirement", "fact"}


# =============================================================================
# 4e: Recall threshold
# =============================================================================


class TestRecallThreshold:
    """Default recall threshold should be reasonable."""

    def test_default_threshold_is_reasonable(self):
        import inspect

        from memory.manager import MemoryManager

        sig = inspect.signature(MemoryManager.recall)
        default = sig.parameters["score_threshold"].default
        # 0.35 measured at 93.8% seeded probe accuracy vs 75.0% at 0.40 and 70.8% at 0.45 (3-repeat arms, 2026-07-09, docs/superpowers/specs/2026-07-09-dense-representation-fix.md)
        assert default >= 0.35, f"Default threshold {default} is below the measured 0.35 floor"
