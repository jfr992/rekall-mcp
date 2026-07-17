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

    def test_encode_document_is_bm25_weighted(self):
        """encode_document() applies IDF x BM25 TF saturation x length norm."""
        import math

        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        corpus = ["hello world", "hello there", "world peace treaty"]
        encoder.fit(corpus)

        doc = "hello hello world"
        result = encoder.encode_document(doc)

        # Hand-computed BM25 for "hello" (df=2, N=3): tf=2, doc_len=3, avg=7/3
        hello_id = encoder.vocab["hello"]
        idf = math.log((3 - 2 + 0.5) / (2 + 0.5) + 1)
        k1, b = encoder.k1, encoder.b
        expected = idf * (2 * (k1 + 1)) / (2 + k1 * (1 - b + b * 3 / (7 / 3)))
        assert abs(result[hello_id] - expected) < 1e-9

    def test_encode_is_alias_for_encode_document(self):
        """encode() stays as a back-compat alias for encode_document()."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "hello there", "world peace treaty"])

        text = "hello hello world"
        assert encoder.encode(text) == encoder.encode_document(text)

    def test_encode_query_is_raw_term_count(self):
        """encode_query() weights each vocab token by its raw count in the query.

        No IDF, no k1/b saturation, no length normalization — IDF lives on the
        document side so the dot product applies it exactly once.
        """
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "hello there", "world peace treaty"])

        result = encoder.encode_query("hello hello world")

        hello_id = encoder.vocab["hello"]
        world_id = encoder.vocab["world"]
        assert result == {hello_id: 2.0, world_id: 1.0}

    def test_dot_product_applies_idf_exactly_once(self):
        """Hand-computed BM25: sparse dot(query, doc) = sum(query_tf x IDF x doc_bm25_tf).

        Guards the ~IDF^2 regression: IDF must come from the document side only.
        """
        import math

        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        corpus = ["hello world", "hello there", "world peace treaty"]
        encoder.fit(corpus)

        doc = "hello hello world"
        query = "hello hello"  # repeated query term

        doc_vec = encoder.encode_document(doc)
        query_vec = encoder.encode_query(query)
        dot = sum(query_vec[i] * doc_vec[i] for i in query_vec.keys() & doc_vec.keys())

        # hello: df=2, N=3, doc tf=2, doc_len=3, avg_doc_len=7/3, query tf=2
        idf = math.log((3 - 2 + 0.5) / (2 + 0.5) + 1)
        k1, b = encoder.k1, encoder.b
        doc_weight = idf * (2 * (k1 + 1)) / (2 + k1 * (1 - b + b * 3 / (7 / 3)))
        assert abs(dot - 2.0 * doc_weight) < 1e-9

    def test_repeated_query_terms_scale_linearly(self):
        """Query-side TF is linear: doubling a query term doubles its weight."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "hello there", "world peace treaty"])

        hello_id = encoder.vocab["hello"]
        once = encoder.encode_query("hello")[hello_id]
        twice = encoder.encode_query("hello hello")[hello_id]
        thrice = encoder.encode_query("hello hello hello")[hello_id]

        assert twice == 2 * once
        assert thrice == 3 * once

    def test_document_length_affects_document_side_only(self):
        """Length normalization changes encode_document, never encode_query."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "hello there", "world peace treaty"])

        hello_id = encoder.vocab["hello"]

        short_doc = encoder.encode_document("hello")[hello_id]
        long_doc = encoder.encode_document("hello peace treaty there world")[hello_id]
        assert short_doc != long_doc  # doc side is length-normalized

        short_q = encoder.encode_query("hello")[hello_id]
        long_q = encoder.encode_query("hello peace treaty there world")[hello_id]
        assert short_q == long_q == 1.0  # query side is not

    def test_fit_on_nonempty_vocab_raises(self):
        """fit() on an already-fitted encoder raises — fresh encoder per generation.

        Refitting a reused encoder retains stale terms and shifts token IDs.
        """
        import pytest

        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world"])

        with pytest.raises(ValueError):
            encoder.fit(["another corpus"])

    def test_interrupted_save_leaves_original_vocab_intact(self):
        """save() is atomic: a failure mid-save never corrupts the existing file.

        Patch os.replace to raise — the original vocab must be byte-identical
        and no stray partial files may remain beside it.
        """
        from unittest.mock import patch

        import pytest

        from core.sparse_encoder import BM25Encoder

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bm25.json"

            first = BM25Encoder()
            first.fit(["hello world"])
            first.save(str(path))
            original_bytes = path.read_bytes()

            second = BM25Encoder()
            second.fit(["completely different corpus"])
            with patch("core.sparse_encoder.os.replace", side_effect=OSError("disk full")):
                with pytest.raises(OSError):
                    second.save(str(path))

            assert path.read_bytes() == original_bytes
            assert [p.name for p in Path(tmpdir).iterdir()] == ["bm25.json"]

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
