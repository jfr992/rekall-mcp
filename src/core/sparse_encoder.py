"""BM25 sparse vector encoder for hybrid search.

Converts text to sparse vectors using BM25 term weighting.
Used alongside dense embeddings for hybrid search with RRF fusion.

Example:
    encoder = BM25Encoder()
    encoder.fit(corpus)
    sparse = encoder.encode("TOPE-123 connection pooling")
    # Returns: {token_id: weight, ...}
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from pathlib import Path

# Common English stopwords (minimal — preserve technical terms like IDs)
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "it",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "for",
        "with",
        "as",
        "by",
        "this",
        "that",
        "be",
        "are",
        "was",
        "were",
        "its",
        "not",
        "but",
        "all",
        "so",
        "do",
        "if",
        "up",
    ]
)


class BM25Encoder:
    """BM25 sparse vector encoder for hybrid search.

    Tokenizes text and computes BM25 term weights as sparse vectors.
    Sparse vectors enable exact term matching (e.g., "TOPE-123") that
    dense cosine similarity misses.

    Usage:
        encoder = BM25Encoder()
        encoder.fit(corpus)
        sparse = encoder.encode("TOPE-123 connection pooling")
        encoder.save("~/.claude/memory/_bm25_vocab.json")

        loaded = BM25Encoder()
        loaded.load("~/.claude/memory/_bm25_vocab.json")
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """Initialize encoder with BM25 parameters.

        Args:
            k1: Term frequency saturation (1.2-2.0 typical)
            b: Length normalization (0.75 typical)
        """
        self.k1 = k1
        self.b = b
        self.vocab: dict[str, int] = {}
        self.idf: dict[int, float] = {}
        self.avg_doc_len: float = 0.0
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text, preserving technical identifiers.

        Handles ticket IDs (TOPE-123), snake_case (stable_hash_id),
        error codes, and standard words.
        """
        text = text.lower()
        # Match hyphenated IDs, underscore identifiers, and plain words
        tokens = re.findall(r"[a-z0-9][a-z0-9_-]*[a-z0-9]|[a-z0-9]", text)
        return [t for t in tokens if t not in STOPWORDS]

    def fit(self, corpus: list[str]) -> None:
        """Build vocabulary and IDF from corpus.

        Args:
            corpus: List of documents (memory content strings)

        Raises:
            ValueError: If already fitted — refit reassigns token IDs; use a
                fresh encoder per vocab generation.
        """
        if self.vocab:
            raise ValueError(
                "Encoder already fitted; fit() reassigns token IDs. "
                "Create a fresh BM25Encoder per vocab generation."
            )
        if not corpus:
            return

        doc_freq: Counter[str] = Counter()
        total_len = 0

        for doc in corpus:
            tokens = self._tokenize(doc)
            total_len += len(tokens)

            for token in set(tokens):
                doc_freq[token] += 1
                if token not in self.vocab:
                    self.vocab[token] = len(self.vocab)

        self._doc_count = len(corpus)
        self.avg_doc_len = total_len / len(corpus)

        for token, df in doc_freq.items():
            token_id = self.vocab[token]
            # Smoothed IDF: avoids negative values for high-freq terms
            self.idf[token_id] = math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1)

    def encode_document(self, text: str) -> dict[int, float]:
        """Encode a document to a sparse BM25 vector (IDF x TF saturation x length norm).

        Args:
            text: Document text to encode

        Returns:
            Dict mapping token_id -> BM25 weight. Empty if vocab not built.
        """
        if not self.vocab:
            return {}

        tokens = self._tokenize(text)
        if not tokens:
            return {}

        tf: Counter[str] = Counter(tokens)
        doc_len = len(tokens)

        sparse: dict[int, float] = {}
        for token, freq in tf.items():
            if token not in self.vocab:
                continue

            token_id = self.vocab[token]
            idf = self.idf.get(token_id, 0.0)

            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (
                1 - self.b + self.b * doc_len / max(self.avg_doc_len, 1)
            )

            sparse[token_id] = idf * numerator / denominator

        return sparse

    def encode_query(self, text: str) -> dict[int, float]:
        """Encode a query to a sparse vector of raw term counts.

        No IDF and no length normalization — the document side carries both,
        so IDF appears exactly once in the sparse dot product.

        Args:
            text: Query text to encode

        Returns:
            Dict mapping token_id -> query term count. Empty if vocab not built.
        """
        if not self.vocab:
            return {}

        tf: Counter[str] = Counter(self._tokenize(text))
        return {self.vocab[token]: float(freq) for token, freq in tf.items() if token in self.vocab}

    def encode(self, text: str) -> dict[int, float]:
        """Deprecated alias for encode_document(); queries should use encode_query()."""
        return self.encode_document(text)

    def save(self, path: str, binding: dict | None = None) -> None:
        """Persist vocabulary and IDF to disk.

        Args:
            path: File path (JSON)
            binding: Optional store identity ({target, collection, points}) —
                loaders refuse a vocab bound to a different store.
        """
        data: dict = {
            "k1": self.k1,
            "b": self.b,
            "vocab": self.vocab,
            "idf": {str(k): v for k, v in self.idf.items()},
            "avg_doc_len": self.avg_doc_len,
            "doc_count": self._doc_count,
        }
        if binding is not None:
            data["_binding"] = binding
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic publish: same-dir temp + fsync + os.replace so a crash mid-save
        # never leaves a truncated vocab (which would brick every save/recall).
        tmp = target.with_name(f".{target.name}.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    def load(self, path: str) -> None:
        """Load vocabulary and IDF from disk.

        Args:
            path: File path (JSON)
        """
        with open(path) as f:
            data = json.load(f)

        self.k1 = data.get("k1", 1.5)
        self.b = data.get("b", 0.75)
        self.vocab = data.get("vocab", {})
        self.idf = {int(k): v for k, v in data.get("idf", {}).items()}
        self.avg_doc_len = data.get("avg_doc_len", 0.0)
        self._doc_count = data.get("doc_count", 0)
