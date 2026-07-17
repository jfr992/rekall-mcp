"""T2 score contract: RRF selects hybrid candidates, cosine is the only score space.

The downstream blend (manager) multiplies vector_score by 0.40 — every path out of
VectorStore.search() must return cosine-valued scores, never RRF rank scores.
"""

from __future__ import annotations

import math

import pytest


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@pytest.mark.integration
class TestHybridScoreContract:
    """Integration tests against disposable Qdrant (server :6334 and embedded)."""

    CORPUS = [
        "TOPE-123 connection pooling issue in prod",
        "PostgreSQL database optimization tips",
        "Memory leak in worker process identified",
    ]

    @pytest.fixture(params=["server", "embedded"])
    def hybrid_store(self, request, tmp_path):
        """VectorStore with fitted encoder, parametrized over both client modes."""
        from core import BM25Encoder, VectorStore

        encoder = BM25Encoder()
        encoder.fit(self.CORPUS)

        if request.param == "server":
            store = VectorStore(
                collection="test_score_contract",
                url="http://localhost:6334",
                sparse_encoder=encoder,
            )
        else:
            store = VectorStore(
                collection="test_score_contract",
                path=str(tmp_path / "qdrant"),
                sparse_encoder=encoder,
            )

        yield store

        try:
            store.delete_collection()
        except Exception:
            pass

    def _seed(self, store, embedder):
        for i, content in enumerate(self.CORPUS):
            store.save(
                id=f"m{i}",
                vector=embedder.encode(content),
                payload={"content": content, "memory_id": f"m{i}"},
                content=content,
            )

    def test_hybrid_scores_are_cosine_valued(self, hybrid_store):
        """Hybrid hit scores are cosine: bounded [-1, 1] and equal to the dense-path
        score for the same point (±1e-6)."""
        from core import Embedder

        embedder = Embedder()
        self._seed(hybrid_store, embedder)

        query = "TOPE-123"
        query_vector = embedder.encode(query)

        hybrid = hybrid_store.search(vector=query_vector, query_text=query, limit=3)
        # query_text="" forces the dense-only path on the same store/collection.
        dense = hybrid_store.search(vector=query_vector, query_text="", limit=3)

        assert len(hybrid) > 0
        for hit in hybrid:
            assert -1.0 <= hit["score"] <= 1.0

        dense_scores = {hit["memory_id"]: hit["score"] for hit in dense}
        for hit in hybrid:
            assert hit["memory_id"] in dense_scores
            assert hit["score"] == pytest.approx(dense_scores[hit["memory_id"]], abs=1e-6)

        # Probe the storage-side normalization claim: cosine is scale-invariant,
        # so the locally computed cosine over the stored vector must match the
        # score Qdrant computed for the dense path, normalized storage or not.
        stored = {
            item["memory_id"]: item["_vector"]
            for item in hybrid_store.get_many(
                [h["memory_id"] for h in hybrid], with_vectors=True
            )
        }
        for hit in hybrid:
            manual = _cosine(query_vector, stored[hit["memory_id"]])
            assert hit["score"] == pytest.approx(manual, abs=1e-6)
