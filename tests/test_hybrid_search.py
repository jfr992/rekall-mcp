"""Tests for hybrid search (dense + sparse vectors with RRF fusion)."""

from __future__ import annotations

import pytest


class TestVectorStoreSparseEncoder:
    """Test VectorStore sparse_encoder parameter (unit, no Qdrant needed)."""

    def test_init_accepts_sparse_encoder(self):
        """VectorStore.__init__ accepts sparse_encoder parameter."""
        from core import BM25Encoder, VectorStore

        encoder = BM25Encoder()
        encoder.fit(["test document"])

        store = VectorStore(
            collection="test",
            url="http://localhost:6334",
            sparse_encoder=encoder,
        )

        assert store.sparse_encoder is encoder

    def test_init_without_sparse_encoder_defaults_to_none(self):
        """VectorStore without sparse_encoder has None."""
        from core import VectorStore

        store = VectorStore(collection="test", url="http://localhost:6334")

        assert store.sparse_encoder is None

    def test_repr_includes_collection(self):
        """VectorStore __repr__ includes collection name."""
        from core import VectorStore

        store = VectorStore(collection="my_collection", url="http://localhost:6334")

        assert "my_collection" in repr(store)


class TestBM25EncoderHybridFlow:
    """Test BM25 encoding flow that feeds into hybrid search."""

    def test_encode_ticket_id_has_weight(self):
        """Encoding a ticket ID produces a non-empty sparse vector."""
        from core import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit([
            "TOPE-123 connection pooling issue in prod",
            "PostgreSQL database optimization tips",
            "Memory leak in worker process identified",
        ])

        result = encoder.encode("TOPE-123")

        assert isinstance(result, dict)
        assert len(result) > 0

    def test_different_queries_produce_different_vectors(self):
        """Two different queries produce different sparse vectors."""
        from core import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit([
            "TOPE-123 connection pooling",
            "database optimization",
            "memory management tips",
        ])

        v1 = encoder.encode("TOPE-123 connection")
        v2 = encoder.encode("database optimization")

        assert v1 != v2

    def test_exact_term_in_query_gets_higher_idf_score(self):
        """Rare term in query yields higher weight than common term."""
        from core import BM25Encoder

        encoder = BM25Encoder()
        # "common" appears in all docs; "rare_unique_xyz" only once
        encoder.fit([
            "common term everywhere here",
            "common word appears again",
            "common repeated once more",
            "rare_unique_xyz single mention",
        ])

        common_vec = encoder.encode("common")
        rare_vec = encoder.encode("rare_unique_xyz")

        common_weight = max(common_vec.values()) if common_vec else 0.0
        rare_weight = max(rare_vec.values()) if rare_vec else 0.0

        assert rare_weight > common_weight

    def test_sparse_vector_values_are_positive(self):
        """BM25 weights are always positive."""
        from core import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["first document", "second document", "third entry"])

        result = encoder.encode("first document")

        assert all(v > 0 for v in result.values())


@pytest.mark.integration
class TestHybridSearchIntegration:
    """Integration tests requiring running Qdrant on port 6334."""

    @pytest.fixture
    def hybrid_store(self):
        """VectorStore with sparse encoder, connected to test Qdrant."""
        from core import BM25Encoder, VectorStore

        corpus = [
            "TOPE-123 connection pooling issue",
            "PostgreSQL database optimization",
            "Memory leak in worker process",
        ]
        encoder = BM25Encoder()
        encoder.fit(corpus)

        store = VectorStore(
            collection="test_hybrid_search",
            url="http://localhost:6334",
            sparse_encoder=encoder,
        )

        yield store

        try:
            store.delete_collection()
        except Exception:
            pass

    def test_save_with_content_for_sparse(self, hybrid_store):
        """save() with content= stores sparse vector alongside dense."""
        from core import Embedder

        embedder = Embedder()
        content = "TOPE-123 connection pooling issue"

        hybrid_store.save(
            id="t1",
            vector=embedder.encode(content),
            payload={"content": content, "memory_id": "t1"},
            content=content,
        )

        assert hybrid_store.count() == 1

    def test_hybrid_search_returns_exact_match_first(self, hybrid_store):
        """Hybrid search returns exact-term match as top result."""
        from core import Embedder

        embedder = Embedder()
        docs = [
            ("1", "TOPE-123 connection pooling issue"),
            ("2", "general database performance tips"),
            ("3", "TOPE-456 memory leak investigation"),
        ]

        for doc_id, content in docs:
            hybrid_store.save(
                id=doc_id,
                vector=embedder.encode(content),
                payload={"content": content, "memory_id": doc_id},
                content=content,
            )

        results = hybrid_store.search(
            vector=embedder.encode("TOPE-123"),
            query_text="TOPE-123",
            limit=3,
        )

        assert len(results) > 0
        assert "TOPE-123" in results[0].get("content", "")
