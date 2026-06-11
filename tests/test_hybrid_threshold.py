"""Hybrid (RRF) search must not silently drop the caller's score_threshold."""

from unittest.mock import MagicMock

from core.vector_store import VectorStore


class FakeSparseEncoder:
    def encode(self, text: str) -> dict[int, float]:
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
