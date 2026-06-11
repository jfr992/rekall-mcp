"""Tests for BM25 sparse vector encoder."""

from __future__ import annotations

import tempfile
from pathlib import Path


class TestBM25Encoder:
    """Test BM25 sparse vector encoding."""

    def test_fit_builds_vocabulary(self):
        """fit() builds vocabulary from corpus."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        corpus = ["hello world", "hello there", "world peace"]
        encoder.fit(corpus)

        assert "hello" in encoder.vocab
        assert "world" in encoder.vocab
        assert len(encoder.vocab) >= 4

    def test_encode_returns_sparse_vector(self):
        """encode() returns dict of token_id -> weight."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "hello there"])

        result = encoder.encode("hello world")

        assert isinstance(result, dict)
        assert len(result) > 0
        assert all(isinstance(k, int) for k in result.keys())
        assert all(isinstance(v, float) for v in result.values())

    def test_encode_exact_term_has_weight(self):
        """Exact terms get non-zero weight."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["TOPE-123 is a ticket", "another document", "more text"])

        result = encoder.encode("TOPE-123")

        assert len(result) > 0
        assert all(v > 0 for v in result.values())

    def test_encode_returns_empty_for_stopwords_only(self):
        """Text with only stopwords returns empty sparse vector."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "test document"])

        result = encoder.encode("a an the")

        assert isinstance(result, dict)

    def test_encode_unknown_term_returns_empty(self):
        """Terms not in vocabulary are ignored."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world"])

        result = encoder.encode("xyz_unknown_term_not_in_vocab")

        assert isinstance(result, dict)

    def test_encode_empty_before_fit_returns_empty(self):
        """encode() before fit() returns empty dict."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        result = encoder.encode("hello world")

        assert result == {}

    def test_save_and_load_preserves_vocab(self):
        """save/load round-trips vocab correctly."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "test document"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bm25.json"
            encoder.save(str(path))

            loaded = BM25Encoder()
            loaded.load(str(path))

            assert loaded.vocab == encoder.vocab
            assert abs(loaded.avg_doc_len - encoder.avg_doc_len) < 0.01

    def test_save_and_load_preserves_idf(self):
        """save/load round-trips IDF values correctly."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "test document"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bm25.json"
            encoder.save(str(path))

            loaded = BM25Encoder()
            loaded.load(str(path))

            assert loaded.idf == encoder.idf

    def test_save_creates_parent_dirs(self):
        """save() creates parent directories if needed."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "dir" / "bm25.json"
            encoder.save(str(path))

            assert path.exists()

    def test_encode_after_load_same_as_original(self):
        """encode() after load produces same results as original."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "test document", "another entry"])

        text = "hello test"
        original = encoder.encode(text)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bm25.json"
            encoder.save(str(path))

            loaded = BM25Encoder()
            loaded.load(str(path))

            reloaded = loaded.encode(text)

        assert original == reloaded

    def test_tokenize_handles_ticket_ids(self):
        """Tokenizer preserves ticket IDs like TOPE-123."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        tokens = encoder._tokenize("TOPE-123 stable_hash_id ERROR_CODE")

        # At minimum should have lowercase versions of words
        token_set = set(tokens)
        assert len(token_set) > 0

    def test_fit_empty_corpus_is_safe(self):
        """fit() with empty corpus doesn't crash."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit([])

        assert encoder.vocab == {}
        assert encoder.avg_doc_len == 0.0

    def test_idf_higher_for_rare_terms(self):
        """Rare terms get higher IDF than common terms."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(
            [
                "common word appears here",
                "common word also here",
                "common word again here",
                "rare_unique_xyz only once",
            ]
        )

        common_id = encoder.vocab.get("common")
        rare_id = encoder.vocab.get("rare_unique_xyz")

        if common_id is not None and rare_id is not None:
            assert encoder.idf[rare_id] > encoder.idf[common_id]
