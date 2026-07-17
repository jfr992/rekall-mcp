"""Hybrid (RRF) search must not silently drop the caller's score_threshold."""

from unittest.mock import MagicMock

from qdrant_client.http.models import FusionQuery

from core.vector_store import VectorStore


class FakeSparseEncoder:
    # Query side changed to asymmetric BM25: search() now calls encode_query().
    def encode_query(self, text: str) -> dict[int, float]:
        return {1: 0.5, 7: 0.25}


def test_hybrid_search_passes_threshold_to_dense_prefetch():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    dense_prefetch = kwargs["prefetch"][0]
    assert dense_prefetch.score_threshold == 0.9


def test_hybrid_search_omits_threshold_when_zero():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.0, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert kwargs["prefetch"][0].score_threshold is None


def test_hybrid_search_does_not_threshold_outer_rrf_query():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert isinstance(kwargs["query"], FusionQuery)
    assert "score_threshold" not in kwargs


def test_hybrid_search_keeps_filter_on_prefetches_and_outer_query():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(
        vector=[0.1] * 384,
        limit=5,
        filters={"project": "rekall-mcp"},
        query_text="TOPE-123",
    )

    kwargs = store._client.query_points.call_args.kwargs
    query_filter = kwargs["query_filter"]
    assert query_filter is not None
    assert kwargs["prefetch"][0].filter == query_filter
    assert kwargs["prefetch"][1].filter == query_filter
