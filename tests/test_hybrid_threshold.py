"""Hybrid (RRF) search must not silently drop the caller's score_threshold."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client.http.models import FusionQuery

from core.vector_store import VectorStore


class FakeSparseEncoder:
    # Query side changed to asymmetric BM25: search() now calls encode_query().
    def encode_query(self, text: str) -> dict[int, float]:
        return {1: 0.5, 7: 0.25}


def test_hybrid_prefetch_carries_no_threshold():
    """T2 score contract: the threshold is cosine and applied post-scoring, so
    neither prefetch leg carries it — candidate selection is threshold-free."""
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert kwargs["prefetch"][0].score_threshold is None
    assert kwargs["prefetch"][1].score_threshold is None


# T2 deliberately moved the threshold out of the prefetch: it is now applied
# post-scoring on locally computed cosine (this replaces the old pin that
# asserted 0.9 landed on the dense prefetch).
def test_hybrid_threshold_filters_on_cosine_post_scoring():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    query = [1.0] + [0.0] * 383
    orthogonal = [0.0, 1.0] + [0.0] * 382
    store._client.query_points.return_value.points = [
        SimpleNamespace(score=0.033, vector={"": query}, payload={"memory_id": "aligned"}),
        SimpleNamespace(score=0.032, vector={"": orthogonal}, payload={"memory_id": "ortho"}),
    ]

    results = store.search(vector=query, limit=5, score_threshold=0.5, query_text="TOPE-123")

    assert [r["memory_id"] for r in results] == ["aligned"]
    assert results[0]["score"] == pytest.approx(1.0)


# T2 deliberately replaced the old 0.0-becomes-None prefetch pin: 0.0 is now a
# real cosine floor applied post-scoring, mirroring Qdrant (drop below, keep ties).
def test_hybrid_zero_threshold_keeps_zero_and_drops_negative_cosine():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    query = [1.0] + [0.0] * 383
    orthogonal = [0.0, 1.0] + [0.0] * 382
    opposite = [-1.0] + [0.0] * 383
    store._client.query_points.return_value.points = [
        SimpleNamespace(score=0.033, vector={"": orthogonal}, payload={"memory_id": "ortho"}),
        SimpleNamespace(score=0.032, vector={"": opposite}, payload={"memory_id": "neg"}),
    ]

    results = store.search(vector=query, limit=5, score_threshold=0.0, query_text="TOPE-123")

    assert [r["memory_id"] for r in results] == ["ortho"]
    assert results[0]["score"] == pytest.approx(0.0)


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
