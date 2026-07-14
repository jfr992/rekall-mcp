"""Tests for core infrastructure: VectorStore, Embedder, Telemetry.

Tests are organized to read like documentation:
    - TestTelemetry: How we measure
    - TestEmbedder: How we encode text
    - TestVectorStore: How we store and search
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# TELEMETRY TESTS: How we measure
# =============================================================================


class TestTelemetry:
    """Telemetry tracks operations for observability."""

    @pytest.fixture(autouse=True)
    def reset_telemetry(self):
        """Reset singleton before each test."""
        from core.telemetry import Telemetry

        Telemetry.reset()
        yield
        Telemetry.reset()

    def test_tracks_operation_count(self):
        """Each operation increments the counter."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        with telemetry.track("test.operation"):
            pass

        metrics = telemetry.get_operation("test.operation")
        assert metrics.count == 1

    def test_tracks_operation_duration(self):
        """Operations record their duration."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        with telemetry.track("test.slow"):
            time.sleep(0.01)  # 10ms

        metrics = telemetry.get_operation("test.slow")
        assert metrics.avg_ms >= 10  # At least 10ms

    def test_tracks_errors(self):
        """Failed operations are tracked separately."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        try:
            with telemetry.track("test.failing"):
                raise ValueError("test error")
        except ValueError:
            pass

        metrics = telemetry.get_operation("test.failing")
        assert metrics.count == 1
        assert metrics.errors == 1
        assert metrics.success_rate == 0.0

    def test_decorator_tracks_functions(self):
        """@traced decorator works like context manager."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        @telemetry.traced("test.decorated")
        def my_function():
            return 42

        result = my_function()

        assert result == 42
        assert telemetry.get_operation("test.decorated").count == 1

    def test_gauge_sets_point_in_time_value(self):
        """Gauges track current values (not cumulative)."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        telemetry.gauge("test.queue_size", 100)
        telemetry.gauge("test.queue_size", 50)

        metrics = telemetry.get_metrics()
        assert metrics["gauges"]["test.queue_size"] == 50

    def test_get_metrics_returns_all_data(self):
        """get_metrics() exports everything."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        with telemetry.track("test.op"):
            pass
        telemetry.gauge("test.gauge", 42)

        metrics = telemetry.get_metrics()

        assert "uptime_seconds" in metrics
        assert "operations" in metrics
        assert "gauges" in metrics
        assert "test.op" in metrics["operations"]
        assert metrics["gauges"]["test.gauge"] == 42

    def test_percentiles_calculated_correctly(self):
        """p50, p95, p99 calculated from samples."""
        from core.telemetry import Telemetry

        telemetry = Telemetry.get()

        # Record operations with known durations
        for i in range(100):
            telemetry.record("test.percentiles", duration_ms=float(i), success=True)

        metrics = telemetry.get_operation("test.percentiles")

        # p50 should be around 50
        assert 45 <= metrics.p50_ms <= 55

        # p95 should be around 95
        assert 90 <= metrics.p95_ms <= 99


# =============================================================================
# EMBEDDER TESTS: How we encode text
# =============================================================================


class TestEmbedder:
    """Embedder converts text to vectors."""

    @pytest.fixture
    def mock_sentence_transformer(self):
        """Mock the SentenceTransformer model."""
        with patch("core.embeddings.Telemetry") as mock_tel:
            # Mock telemetry
            mock_tel.get.return_value = MagicMock(
                track=MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
            )

            with patch("sentence_transformers.SentenceTransformer") as mock_st:
                model = MagicMock()
                model.get_sentence_embedding_dimension.return_value = 384
                model.encode.return_value = MagicMock(tolist=MagicMock(return_value=[0.1] * 384))
                mock_st.return_value = model
                yield model

    def test_lazy_loads_model(self, mock_sentence_transformer):
        """Provider only loads when first used."""
        from core.embeddings import Embedder

        embedder = Embedder(provider="sentence-transformers")

        # Not loaded yet (provider pattern)
        assert embedder._provider is None

        # Access triggers load
        _ = embedder.dimensions

        # Now loaded
        assert embedder._provider is not None

    def test_encode_returns_vector(self, mock_sentence_transformer):
        """encode() returns list of floats."""
        from core.embeddings import Embedder

        embedder = Embedder(provider="sentence-transformers")
        vector = embedder.encode("Hello world")

        assert isinstance(vector, list)
        assert len(vector) == 384
        assert all(isinstance(v, float) for v in vector)

    def test_encode_batch_more_efficient(self, mock_sentence_transformer):
        """encode_batch() calls model.encode once for multiple texts."""
        from core.embeddings import Embedder

        # Setup mock to return multiple vectors
        mock_sentence_transformer.encode.return_value = MagicMock(
            tolist=MagicMock(return_value=[[0.1] * 384] * 3)
        )

        embedder = Embedder(provider="sentence-transformers")
        vectors = embedder.encode_batch(["one", "two", "three"])

        # Should call encode once with all texts
        mock_sentence_transformer.encode.assert_called_once()
        assert len(vectors) == 3

    def test_default_model_is_minilm(self):
        """Default model is all-MiniLM-L6-v2."""
        from core.embeddings import Embedder

        embedder = Embedder()
        assert embedder.model_name == "all-MiniLM-L6-v2"

    def test_custom_model_supported(self):
        """Can specify different model."""
        from core.embeddings import Embedder

        embedder = Embedder(model="paraphrase-MiniLM-L6-v2")
        assert embedder.model_name == "paraphrase-MiniLM-L6-v2"


class TestFastEmbedProvider:
    """FastEmbedProvider: no-torch ONNX embeddings, vector-identical to ST."""

    def test_fastembed_provider_encodes_384(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
        from core.embeddings import Embedder

        e = Embedder(model="all-MiniLM-L6-v2")
        assert e.provider_name == "fastembed"
        v = e.encode("hello world")
        assert len(v) == 384

    def test_auto_resolution_prefers_fastembed(self, monkeypatch):
        """No env, no explicit provider: fastembed wins when importable (packaged default)."""
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        from core.embeddings import Embedder

        assert Embedder().provider_name == "fastembed"

    def test_explicit_sentence_transformers_kept(self, monkeypatch):
        """EMBEDDING_PROVIDER=sentence-transformers keeps today's provider."""
        monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence-transformers")
        from core.embeddings import Embedder

        assert Embedder().provider_name == "sentence-transformers"


# =============================================================================
# VECTOR STORE TESTS: How we store and search
# =============================================================================


class TestVectorStore:
    """VectorStore saves and searches vectors in Qdrant."""

    @pytest.fixture
    def mock_qdrant(self):
        """Mock Qdrant client."""
        with patch("core.vector_store.QdrantClient") as mock_class:
            client = MagicMock()
            mock_class.return_value = client

            # Collection doesn't exist yet
            client.get_collections.return_value = MagicMock(collections=[])

            yield client

    @pytest.fixture
    def mock_telemetry(self):
        """Mock telemetry to avoid singleton issues."""
        with patch("core.vector_store.Telemetry") as mock:
            instance = MagicMock()
            instance.track.return_value = MagicMock(
                __enter__=MagicMock(return_value=None),
                __exit__=MagicMock(return_value=None),
            )
            mock.get.return_value = instance
            yield instance

    @pytest.fixture
    def store(self, mock_qdrant, mock_telemetry):
        """Create a VectorStore with mocked dependencies."""
        from core.vector_store import VectorStore

        store = VectorStore(collection="test_collection")
        store._client = mock_qdrant
        return store

    def test_save_stores_vector_with_payload(self, store, mock_qdrant):
        """save() upserts to Qdrant."""
        store.save(
            id="doc_001",
            vector=[0.1] * 384,
            payload={"type": "note", "project": "test"},
        )

        mock_qdrant.upsert.assert_called_once()
        call = mock_qdrant.upsert.call_args
        assert call.kwargs["collection_name"] == "test_collection"

    def test_search_returns_scored_results(self, store, mock_qdrant):
        """search() returns results with scores."""
        # Mock search results
        mock_qdrant.query_points.return_value = MagicMock(
            points=[
                MagicMock(score=0.95, payload={"content": "Result 1"}),
                MagicMock(score=0.80, payload={"content": "Result 2"}),
            ]
        )

        results = store.search(vector=[0.1] * 384, limit=2)

        assert len(results) == 2
        assert results[0]["score"] == 0.95
        assert results[0]["content"] == "Result 1"

    def test_search_with_filters(self, store, mock_qdrant):
        """search() applies filters."""
        mock_qdrant.query_points.return_value = MagicMock(points=[])

        store.search(
            vector=[0.1] * 384,
            filters={"project": "my-app"},
        )

        call = mock_qdrant.query_points.call_args
        assert call.kwargs["query_filter"] is not None

    def test_scroll_gets_all_matching(self, store, mock_qdrant):
        """scroll() retrieves all vectors matching filter."""
        mock_qdrant.scroll.return_value = (
            [
                MagicMock(payload={"content": "Item 1"}),
                MagicMock(payload={"content": "Item 2"}),
            ],
            None,
        )

        results = store.scroll(filters={"type": "note"})

        assert len(results) == 2
        assert results[0]["content"] == "Item 1"

    def test_scroll_with_vectors(self, store, mock_qdrant):
        """scroll(with_vectors=True) returns payload + vector data."""
        mock_qdrant.scroll.return_value = (
            [
                MagicMock(payload={"memory_id": "m1"}, vector=[0.1, 0.2, 0.3]),
                MagicMock(payload={"memory_id": "m2"}, vector=(0.4, 0.5, 0.6)),
            ],
            None,
        )

        results = store.scroll(with_vectors=True)

        assert len(results) == 2
        assert results[0]["memory_id"] == "m1"
        assert results[0]["vector"] == [0.1, 0.2, 0.3]
        assert results[1]["vector"] == [0.4, 0.5, 0.6]

    def test_delete_removes_matching(self, store, mock_qdrant):
        """delete() removes vectors by filter."""
        store.delete(filters={"project": "old-project"})

        mock_qdrant.delete.assert_called_once()

    def test_count_returns_collection_size(self, store, mock_qdrant):
        """count() returns number of vectors."""
        mock_qdrant.get_collection.return_value = MagicMock(points_count=42)

        count = store.count()

        assert count == 42

    def test_creates_collection_if_not_exists(self, mock_qdrant, mock_telemetry):
        """Connecting creates collection automatically."""
        from core.vector_store import VectorStore

        # Collection doesn't exist
        mock_qdrant.get_collections.return_value = MagicMock(collections=[])

        # url=:6334 so the test-isolation guard allows the (mocked) connect
        store = VectorStore(collection="new_collection", url="http://localhost:6334")
        _ = store.client  # Triggers connection

        mock_qdrant.create_collection.assert_called_once()

    def test_recreate_collection_creates_after_delete_with_stale_listing(self, store, mock_qdrant):
        """recreate_collection() creates even if list still shows deleted collection."""
        mock_qdrant.get_collections.return_value = MagicMock(
            collections=[SimpleNamespace(name="test_collection")]
        )

        store.recreate_collection()

        mock_qdrant.delete_collection.assert_called_once_with(collection_name="test_collection")
        mock_qdrant.create_collection.assert_called_once()


# =============================================================================
# INTEGRATION: All components together
# =============================================================================


class TestCoreIntegration:
    """Test core components work together."""

    @pytest.fixture(autouse=True)
    def reset_telemetry(self):
        """Reset telemetry singleton."""
        from core.telemetry import Telemetry

        Telemetry.reset()
        yield
        Telemetry.reset()

    def test_telemetry_singleton(self):
        """All components share same telemetry instance."""
        from core.telemetry import Telemetry

        t1 = Telemetry.get()
        t2 = Telemetry.get()

        assert t1 is t2

    def test_imports_work(self):
        """Can import from core package."""
        from core import Embedder, Telemetry, VectorStore

        assert Embedder is not None
        assert VectorStore is not None
        assert Telemetry is not None


def test_scroll_unwraps_hybrid_named_vectors_any_order():
    """Hybrid points return named dicts; dense must win regardless of key order."""
    from unittest.mock import MagicMock

    from core.vector_store import VectorStore

    store = VectorStore.__new__(VectorStore)
    store.collection = "test_collection"
    store._telemetry = MagicMock()
    store._telemetry.track.return_value.__enter__ = lambda s: None
    store._telemetry.track.return_value.__exit__ = lambda s, *a: None
    client = MagicMock()
    store._client = client

    dense = [0.1, 0.2, 0.3]
    sparse = MagicMock()  # SparseVector-like, not a list
    p1 = MagicMock(payload={"memory_id": "a"}, vector={"bm25": sparse, "": dense})
    p2 = MagicMock(payload={"memory_id": "b"}, vector={"": dense, "bm25": sparse})
    p3 = MagicMock(payload={"memory_id": "c"}, vector=dense)
    client.scroll.return_value = ([p1, p2, p3], None)

    out = store.scroll(with_vectors=True)

    assert [p["vector"] for p in out] == [dense, dense, dense]
