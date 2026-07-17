"""Hybrid (RRF) threshold contract.

Prod regression (2026-07-17) rewrote this contract: post-scoring the cosine
floor over ALL fused candidates killed every sparse-found identifier memory
(their dense cosine is low by definition — that is the coverage the sparse
index exists for). The threshold now lives server-side on the DENSE leg only,
identical to the dense-only path; sparse-leg matches bypass it and carry their
true cosine downstream.
"""

from unittest.mock import MagicMock

from qdrant_client.http.models import FusionQuery

from core.vector_store import VectorStore


class FakeSparseEncoder:
    # Query side changed to asymmetric BM25: search() now calls encode_query().
    def encode_query(self, text: str) -> dict[int, float]:
        return {1: 0.5, 7: 0.25}


def test_hybrid_dense_leg_carries_threshold_sparse_leg_does_not():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert kwargs["prefetch"][0].score_threshold == 0.9
    assert kwargs["prefetch"][1].score_threshold is None


def test_hybrid_fused_candidates_are_not_post_filtered():
    """A fused candidate below the cosine floor came in via the sparse leg
    (the dense leg filtered server-side) — it must survive with true cosine."""
    from types import SimpleNamespace

    import pytest

    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    query = [1.0] + [0.0] * 383
    orthogonal = [0.0, 1.0] + [0.0] * 382
    store._client.query_points.return_value.points = [
        SimpleNamespace(score=0.033, vector={"": query}, payload={"memory_id": "aligned"}),
        SimpleNamespace(score=0.032, vector={"": orthogonal}, payload={"memory_id": "ortho"}),
    ]

    results = store.search(vector=query, limit=5, score_threshold=0.5, query_text="TOPE-123")

    assert [r["memory_id"] for r in results] == ["aligned", "ortho"]
    assert results[0]["score"] == pytest.approx(1.0)
    assert results[1]["score"] == pytest.approx(0.0)  # true cosine, not inflated


def test_hybrid_search_does_not_threshold_outer_rrf_query():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert isinstance(kwargs["query"], FusionQuery)
    assert "score_threshold" not in kwargs
