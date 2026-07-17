"""T2 score contract: RRF selects hybrid candidates, cosine is the only score space.

The downstream blend (manager) multiplies vector_score by 0.40 — every path out of
VectorStore.search() must return cosine-valued scores, never RRF rank scores.
"""

from __future__ import annotations

import math

import pytest


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
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
    def make_store(self, request, tmp_path):
        """Factory for a hybrid VectorStore, parametrized over both client modes."""
        from core import VectorStore

        stores: list[VectorStore] = []

        def _make(encoder):
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
            stores.append(store)
            return store

        yield _make

        for store in stores:
            try:
                store.delete_collection()
            except Exception:
                pass

    @pytest.fixture
    def hybrid_store(self, make_store):
        """VectorStore with an encoder fitted on CORPUS."""
        from core import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(self.CORPUS)
        return make_store(encoder)

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
            for item in hybrid_store.get_many([h["memory_id"] for h in hybrid], with_vectors=True)
        }
        for hit in hybrid:
            manual = _cosine(query_vector, stored[hit["memory_id"]])
            assert hit["score"] == pytest.approx(manual, abs=1e-6)

    def test_fully_oov_query_falls_through_to_dense_path(self, hybrid_store):
        """encode_query() -> {} falls through to the dense-only path; pin the
        equivalence. Same ids/order/payloads; scores approx because embedded
        qdrant-local jitters identical dense queries at ~1e-8 (probed)."""
        from core import Embedder

        embedder = Embedder()
        self._seed(hybrid_store, embedder)

        # No token of this query is in the fitted vocab.
        query = "zzqx-77841 frobnicator"
        assert hybrid_store.sparse_encoder.encode_query(query) == {}
        query_vector = embedder.encode(query)

        hybrid = hybrid_store.search(vector=query_vector, query_text=query, limit=3)
        dense = hybrid_store.search(vector=query_vector, query_text="", limit=3)

        assert len(dense) > 0
        assert [h["memory_id"] for h in hybrid] == [h["memory_id"] for h in dense]
        for h_hit, d_hit in zip(hybrid, dense, strict=True):
            assert h_hit["score"] == pytest.approx(d_hit["score"], abs=1e-6)
            assert {k: v for k, v in h_hit.items() if k != "score"} == {
                k: v for k, v in d_hit.items() if k != "score"
            }

    def test_sparse_zero_hits_equals_dense_only_output(self, make_store):
        """Encodable query whose sparse leg matches zero points: hybrid output
        equals dense-only output — same ids, same cosine scores, same order.
        Includes a negative-cosine point so the default 0.0 threshold must
        behave identically in both paths."""
        from core import BM25Encoder

        # "ghostterm" enters the vocab via a fit-only doc that is never saved.
        encoder = BM25Encoder()
        encoder.fit(self.CORPUS + ["ghostterm placeholder document"])
        store = make_store(encoder)

        # Synthetic dense vectors with known cosines to the query (= e0).
        dim = 384
        query_vector = [1.0] + [0.0] * (dim - 1)

        def _vec(c0: float, other_axis: int) -> list[float]:
            v = [0.0] * dim
            v[0] = c0
            v[other_axis] = math.sqrt(1.0 - c0 * c0)
            return v

        points = [
            ("p0", _vec(0.9, 1), self.CORPUS[0]),
            ("p1", _vec(0.6, 2), self.CORPUS[1]),
            ("p2", _vec(0.3, 3), self.CORPUS[2]),
            # Negative cosine: dense path's default 0.0 threshold excludes it.
            ("p_neg", _vec(-0.5, 4), "unrelated filler entry"),
        ]
        for pid, vec, content in points:
            store.save(id=pid, vector=vec, payload={"memory_id": pid}, content=content)

        query = "ghostterm"
        assert store.sparse_encoder.encode_query(query) != {}

        hybrid = store.search(vector=query_vector, query_text=query, limit=4)
        dense = store.search(vector=query_vector, query_text="", limit=4)

        assert [h["memory_id"] for h in dense] == ["p0", "p1", "p2"]
        assert [h["memory_id"] for h in hybrid] == [h["memory_id"] for h in dense]
        for h_hit, d_hit in zip(hybrid, dense, strict=True):
            assert h_hit["score"] == pytest.approx(d_hit["score"], abs=1e-6)

    def test_sparse_leg_recovers_dense_invisible_point_with_cosine_score(self, make_store):
        """Coverage: an identifier-only memory whose degenerate dense vector keeps
        it out of the dense top-k IS returned by hybrid via the sparse leg — and
        its score is still cosine-valued, not an RRF rank score."""
        from core import BM25Encoder

        identifier_doc = "EDGE-9999 device conflict on host"
        encoder = BM25Encoder()
        encoder.fit(self.CORPUS + [identifier_doc])
        store = make_store(encoder)

        dim = 384
        query_vector = [1.0] + [0.0] * (dim - 1)

        def _vec(c0: float, other_axis: int) -> list[float]:
            v = [0.0] * dim
            v[0] = c0
            v[other_axis] = math.sqrt(1.0 - c0 * c0)
            return v

        id_cosine = 0.05  # nearly orthogonal to the query: dense-invisible
        points = [
            ("close0", _vec(0.9, 1), self.CORPUS[0]),
            ("close1", _vec(0.8, 2), self.CORPUS[1]),
            ("close2", _vec(0.7, 3), self.CORPUS[2]),
            ("edge", _vec(id_cosine, 4), identifier_doc),
        ]
        for pid, vec, content in points:
            store.save(id=pid, vector=vec, payload={"memory_id": pid}, content=content)

        hybrid = store.search(vector=query_vector, query_text="EDGE-9999", limit=3)
        dense = store.search(vector=query_vector, query_text="", limit=3)

        assert "edge" not in [h["memory_id"] for h in dense]
        hybrid_by_id = {h["memory_id"]: h for h in hybrid}
        assert "edge" in hybrid_by_id
        assert hybrid_by_id["edge"]["score"] == pytest.approx(id_cosine, abs=1e-6)


class TestSparseCoverageSurvivesThreshold:
    """Prod regression (2026-07-17): the recall gate (0.35 cosine) killed every
    sparse-found identifier memory, because such memories have low dense cosine
    BY DEFINITION — that is why the sparse leg exists. Threshold governs the
    dense leg only; sparse-matched candidates bypass it, carrying their true
    (low) cosine downstream for ranking."""

    @pytest.fixture(params=["server", "embedded"])
    def store(self, request, tmp_path):
        from core import BM25Encoder, VectorStore

        corpus = [
            "EdgeHostDeviceAlreadyInUse stuck DELETING palette fix",
            "PostgreSQL database optimization tips",
            "Memory leak in worker process identified",
        ]
        encoder = BM25Encoder()
        encoder.fit(corpus)
        if request.param == "server":
            s = VectorStore(
                collection="test_sparse_coverage",
                url="http://localhost:6334",
                sparse_encoder=encoder,
            )
        else:
            s = VectorStore(
                collection="test_sparse_coverage",
                path=str(tmp_path / "qdrant"),
                sparse_encoder=encoder,
            )
        dims = 8
        # Identifier doc dense-orthogonal to the query axis; distractors near it.
        vecs = [
            [0.0] * 7 + [1.0],
            [1.0] + [0.0] * 7,
            [0.9, 0.1] + [0.0] * 6,
        ]
        s.embedding_dim = dims
        for i, (content, vec) in enumerate(zip(corpus, vecs, strict=True)):
            s.save(
                id=f"m{i}",
                vector=vec,
                payload={"content": content, "memory_id": f"m{i}"},
                content=content,
            )
        yield s
        try:
            s.delete_collection()
        except Exception:
            pass

    def test_sparse_found_low_cosine_hit_survives_recall_gate(self, store):
        query_vec = [1.0] + [0.0] * 7  # cosine 0.0 to the identifier doc
        hits = store.search(
            vector=query_vec,
            query_text="EdgeHostDeviceAlreadyInUse",
            limit=5,
            score_threshold=0.35,
        )
        ids = [h["memory_id"] for h in hits]
        assert "m0" in ids, f"sparse-found identifier memory was thresholded away: {ids}"
        m0 = next(h for h in hits if h["memory_id"] == "m0")
        assert -1.0 <= m0["score"] <= 1.0
        assert m0["score"] < 0.35  # true cosine preserved, not inflated past the gate

    def test_dense_leg_still_respects_threshold(self, store):
        # No sparse match for this query (OOV falls through to pure dense).
        query_vec = [1.0] + [0.0] * 7
        hits = store.search(
            vector=query_vec,
            query_text="zzzunknowntoken",
            limit=5,
            score_threshold=0.35,
        )
        assert all(h["score"] >= 0.35 for h in hits)
        assert "m0" not in [h["memory_id"] for h in hits]
