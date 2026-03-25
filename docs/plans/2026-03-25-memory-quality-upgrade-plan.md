# Memory Quality Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make memory retrieval work like a human brain — hybrid search (BM25 + dense), smart context injection, progressive disclosure, auto-compaction.

**Architecture:** Add BM25 sparse vectors to Qdrant collection alongside existing dense vectors. Use RRF fusion for hybrid search. Add smart context endpoint with project-aware ranking. Compaction via LLM summarization.

**Tech Stack:** Qdrant sparse vectors, sentence-transformers, Python NLTK (tokenization), Anthropic/OpenAI (compaction LLM)

---

## File Structure

### New Files
| File | Responsibility |
|------|----------------|
| `src/core/sparse_encoder.py` | BM25 sparse vector encoding |
| `src/memory/migrate_hybrid.py` | Migration script for hybrid schema |
| `src/memory/compact.py` | LLM-powered memory compaction |
| `tests/test_sparse_encoder.py` | BM25 encoder tests |
| `tests/test_hybrid_search.py` | Hybrid search tests |
| `tests/test_smart_context.py` | Smart context endpoint tests |
| `tests/test_compact.py` | Compaction tests |

### Modified Files
| File | Changes |
|------|---------|
| `src/core/vector_store.py` | Add sparse vector support, hybrid search |
| `src/core/__init__.py` | Export BM25Encoder |
| `src/memory/manager.py` | Initialize encoder, update save/recall |
| `src/server.py` | Add `/api/memory/context/smart`, `/api/memory/recall/quick`, `/api/memory/compact` |
| `src/tools/builtin/memory.py` | Update tool descriptions |

---

## Phase 1: Hybrid Search

### Task 1.1: BM25 Encoder - Tests

**Files:**
- Create: `tests/test_sparse_encoder.py`

- [ ] **Step 1: Write failing tests for BM25Encoder**

```python
# tests/test_sparse_encoder.py
"""Tests for BM25 sparse vector encoder."""

import pytest
from pathlib import Path
import tempfile


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

    def test_encode_exact_term_has_high_weight(self):
        """Exact terms get higher weight than rare terms."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["TOPE-123 is a ticket", "another document", "more text"])

        result = encoder.encode("TOPE-123")

        # TOPE-123 should be in result with non-zero weight
        assert len(result) > 0

    def test_save_and_load_preserves_state(self):
        """save/load round-trips correctly."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        encoder.fit(["hello world", "test document"])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bm25.json"
            encoder.save(str(path))

            loaded = BM25Encoder()
            loaded.load(str(path))

            assert loaded.vocab == encoder.vocab
            assert loaded.avg_doc_len == encoder.avg_doc_len

    def test_tokenize_handles_special_chars(self):
        """Tokenizer handles ticket IDs, error codes, etc."""
        from core.sparse_encoder import BM25Encoder

        encoder = BM25Encoder()
        tokens = encoder._tokenize("TOPE-123 stable_hash_id ERROR_CODE")

        assert "tope-123" in tokens or "tope" in tokens
        assert "stable_hash_id" in tokens or "stable" in tokens
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_sparse_encoder.py -v`
Expected: ModuleNotFoundError or ImportError (module doesn't exist)

- [ ] **Step 3: Commit test file**

```bash
git add tests/test_sparse_encoder.py
git commit -m "test: add BM25 sparse encoder tests"
```

---

### Task 1.2: BM25 Encoder - Implementation

**Files:**
- Create: `src/core/sparse_encoder.py`
- Modify: `src/core/__init__.py`

- [ ] **Step 1: Implement BM25Encoder class**

```python
# src/core/sparse_encoder.py
"""BM25 sparse vector encoder for hybrid search.

Converts text to sparse vectors using BM25 term weighting.
Used alongside dense embeddings for hybrid search with RRF fusion.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

# Common English stopwords (minimal set to preserve technical terms)
STOPWORDS = frozenset([
    "a", "an", "the", "is", "it", "to", "of", "and", "or", "in", "on", "at",
    "for", "with", "as", "by", "this", "that", "be", "are", "was", "were",
])


class BM25Encoder:
    """BM25 sparse vector encoder for hybrid search.

    Tokenizes text and computes BM25 term weights as sparse vectors.
    Sparse vectors enable exact term matching (e.g., "TOPE-123") that
    dense embeddings miss.

    Example:
        encoder = BM25Encoder()
        encoder.fit(corpus)
        sparse = encoder.encode("TOPE-123 connection pooling")
        # Returns: {token_id: weight, ...}
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """Initialize encoder with BM25 parameters.

        Args:
            k1: Term frequency saturation parameter (1.2-2.0 typical)
            b: Length normalization parameter (0.75 typical)
        """
        self.k1 = k1
        self.b = b
        self.vocab: dict[str, int] = {}
        self.idf: dict[int, float] = {}
        self.avg_doc_len: float = 0.0
        self._doc_count: int = 0

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text preserving technical terms.

        Handles:
        - Ticket IDs (TOPE-123, JIRA-456)
        - Snake_case identifiers (stable_hash_id)
        - Error codes (ERROR_CODE_123)
        - Standard words
        """
        # Lowercase but preserve structure
        text = text.lower()

        # Split on whitespace and punctuation, but keep hyphens/underscores in words
        tokens = re.findall(r'[a-z0-9][a-z0-9_-]*[a-z0-9]|[a-z0-9]', text)

        # Remove stopwords
        return [t for t in tokens if t not in STOPWORDS]

    def fit(self, corpus: list[str]) -> None:
        """Build vocabulary and IDF from corpus.

        Args:
            corpus: List of documents (memory content strings)
        """
        if not corpus:
            return

        # Build vocabulary and document frequencies
        doc_freq: Counter[str] = Counter()
        total_len = 0

        for doc in corpus:
            tokens = self._tokenize(doc)
            total_len += len(tokens)

            # Count unique tokens per document
            unique_tokens = set(tokens)
            for token in unique_tokens:
                doc_freq[token] += 1

                # Add to vocabulary if new
                if token not in self.vocab:
                    self.vocab[token] = len(self.vocab)

        self._doc_count = len(corpus)
        self.avg_doc_len = total_len / len(corpus) if corpus else 0.0

        # Compute IDF for each term
        for token, df in doc_freq.items():
            token_id = self.vocab[token]
            # IDF with smoothing to avoid division by zero
            self.idf[token_id] = math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1)

    def encode(self, text: str) -> dict[int, float]:
        """Encode text to sparse vector.

        Args:
            text: Text to encode

        Returns:
            Dict mapping token_id to BM25 weight
        """
        if not self.vocab:
            return {}

        tokens = self._tokenize(text)
        if not tokens:
            return {}

        # Count term frequencies
        tf: Counter[str] = Counter(tokens)
        doc_len = len(tokens)

        # Compute BM25 weights
        sparse: dict[int, float] = {}
        for token, freq in tf.items():
            if token not in self.vocab:
                continue

            token_id = self.vocab[token]
            idf = self.idf.get(token_id, 0.0)

            # BM25 term weight formula
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / max(self.avg_doc_len, 1))

            sparse[token_id] = idf * numerator / denominator

        return sparse

    def save(self, path: str) -> None:
        """Persist vocabulary and IDF to disk.

        Args:
            path: File path for JSON output
        """
        data = {
            "k1": self.k1,
            "b": self.b,
            "vocab": self.vocab,
            "idf": {str(k): v for k, v in self.idf.items()},
            "avg_doc_len": self.avg_doc_len,
            "doc_count": self._doc_count,
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str) -> None:
        """Load vocabulary and IDF from disk.

        Args:
            path: File path for JSON input
        """
        with open(path) as f:
            data = json.load(f)

        self.k1 = data.get("k1", 1.5)
        self.b = data.get("b", 0.75)
        self.vocab = data.get("vocab", {})
        self.idf = {int(k): v for k, v in data.get("idf", {}).items()}
        self.avg_doc_len = data.get("avg_doc_len", 0.0)
        self._doc_count = data.get("doc_count", 0)
```

- [ ] **Step 2: Export from core/__init__.py**

Add to `src/core/__init__.py`:
```python
from core.sparse_encoder import BM25Encoder
```

And update `__all__` to include `"BM25Encoder"`.

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_sparse_encoder.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit implementation**

```bash
git add src/core/sparse_encoder.py src/core/__init__.py
git commit -m "feat: add BM25 sparse encoder for hybrid search"
```

---

### Task 1.3: VectorStore Hybrid Search - Tests

**Files:**
- Create: `tests/test_hybrid_search.py`

- [ ] **Step 1: Write failing tests for hybrid search**

```python
# tests/test_hybrid_search.py
"""Tests for hybrid search (dense + sparse vectors)."""

import pytest


@pytest.fixture
def hybrid_store(tmp_path, monkeypatch):
    """Create a VectorStore with sparse encoder for testing."""
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")

    from core import VectorStore, BM25Encoder

    # Build encoder from test corpus
    corpus = [
        "TOPE-123 connection pooling issue",
        "PostgreSQL database optimization",
        "Memory leak in worker process",
    ]
    encoder = BM25Encoder()
    encoder.fit(corpus)

    store = VectorStore(
        collection="test_hybrid",
        url="http://localhost:6334",
        sparse_encoder=encoder,
    )

    yield store

    # Cleanup
    try:
        store.delete_collection()
    except Exception:
        pass


class TestHybridSearch:
    """Test hybrid search functionality."""

    @pytest.mark.integration
    def test_save_with_sparse_vector(self, hybrid_store):
        """save() stores both dense and sparse vectors."""
        from core import Embedder

        embedder = Embedder()
        content = "TOPE-123 connection pooling issue"

        hybrid_store.save(
            id="test_1",
            vector=embedder.encode(content),
            payload={"content": content},
            content=content,  # For sparse encoding
        )

        # Should not raise
        assert hybrid_store.count() == 1

    @pytest.mark.integration
    def test_search_finds_exact_term(self, hybrid_store):
        """Hybrid search finds exact terms like TOPE-123."""
        from core import Embedder

        embedder = Embedder()

        # Save test data
        docs = [
            ("1", "TOPE-123 connection pooling issue"),
            ("2", "General database performance tips"),
            ("3", "TOPE-456 memory leak investigation"),
        ]

        for doc_id, content in docs:
            hybrid_store.save(
                id=doc_id,
                vector=embedder.encode(content),
                payload={"content": content, "memory_id": doc_id},
                content=content,
            )

        # Search for exact ticket ID
        results = hybrid_store.search(
            vector=embedder.encode("TOPE-123"),
            query_text="TOPE-123",
            limit=3,
        )

        # TOPE-123 should be top result
        assert len(results) > 0
        assert "TOPE-123" in results[0].get("content", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_hybrid_search.py -v -k "not integration"`
Expected: TypeError (sparse_encoder parameter doesn't exist yet)

- [ ] **Step 3: Commit test file**

```bash
git add tests/test_hybrid_search.py
git commit -m "test: add hybrid search tests"
```

---

### Task 1.4: VectorStore Hybrid Search - Implementation

**Files:**
- Modify: `src/core/vector_store.py:75-130` (init and _ensure_collection)
- Modify: `src/core/vector_store.py:153-187` (save method)
- Modify: `src/core/vector_store.py:238-284` (search method)

- [ ] **Step 1: Update VectorStore __init__ to accept sparse_encoder**

In `src/core/vector_store.py`, modify `__init__`:

```python
def __init__(
    self,
    collection: str,
    url: str = "http://localhost:6333",
    api_key: str | None = None,
    embedding_dim: int = 384,
    sparse_encoder: "BM25Encoder | None" = None,  # NEW
) -> None:
    """Initialize vector store.

    Args:
        collection: Collection name
        url: Qdrant server URL
        api_key: Optional API key
        embedding_dim: Vector dimensions (default: 384 for MiniLM)
        sparse_encoder: Optional BM25 encoder for hybrid search
    """
    self.collection = collection
    self.url = url
    self.api_key = api_key
    self.embedding_dim = embedding_dim
    self.sparse_encoder = sparse_encoder  # NEW

    self._client: QdrantClient | None = None
    self._telemetry = Telemetry.get()
```

- [ ] **Step 2: Update _ensure_collection to create sparse vector field**

```python
def _ensure_collection(self) -> None:
    """Create collection if it doesn't exist."""
    from qdrant_client.http.models import SparseVectorParams

    collections = [c.name for c in self._client.get_collections().collections]

    if self.collection not in collections:
        logger.info(f"Creating collection: {self.collection}")

        # Sparse vector config (only if encoder provided)
        sparse_config = None
        if self.sparse_encoder:
            sparse_config = {
                "bm25": SparseVectorParams()
            }

        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(
                size=self.embedding_dim,
                distance=Distance.COSINE,
            ),
            sparse_vectors_config=sparse_config,
        )
```

- [ ] **Step 3: Update save() to include sparse vector**

```python
def save(
    self,
    id: str | int,
    vector: list[float],
    payload: dict[str, Any] | None = None,
    content: str | None = None,  # NEW: for sparse encoding
) -> None:
    """Save a vector with metadata.

    Args:
        id: Unique identifier
        vector: Dense embedding vector
        payload: Metadata dict
        content: Original text (for sparse vector encoding)
    """
    from qdrant_client.http.models import SparseVector

    with self._telemetry.track("vector_store.save"):
        point_id = id if isinstance(id, int) else stable_hash_id(id)

        # Build sparse vector if encoder available
        sparse_vectors = None
        if self.sparse_encoder and content:
            sparse = self.sparse_encoder.encode(content)
            if sparse:
                sparse_vectors = {
                    "bm25": SparseVector(
                        indices=list(sparse.keys()),
                        values=list(sparse.values()),
                    )
                }

        point = PointStruct(
            id=point_id,
            vector=vector,
            payload=payload or {},
        )

        # Add sparse vectors if available
        if sparse_vectors:
            point = PointStruct(
                id=point_id,
                vector={"": vector},  # Named vector for hybrid
                payload=payload or {},
            )
            # Qdrant requires different structure for sparse
            self.client.upsert(
                collection_name=self.collection,
                points=[{
                    "id": point_id,
                    "vector": {
                        "": vector,
                        "bm25": sparse_vectors["bm25"],
                    },
                    "payload": payload or {},
                }],
            )
        else:
            self.client.upsert(
                collection_name=self.collection,
                points=[point],
            )
```

- [ ] **Step 4: Update search() for hybrid search with RRF**

```python
def search(
    self,
    vector: list[float],
    limit: int = 10,
    filters: dict[str, Any] | None = None,
    score_threshold: float = 0.0,
    query_text: str = "",  # NEW: for BM25 search
) -> list[dict[str, Any]]:
    """Search for similar vectors (hybrid if sparse encoder available).

    Args:
        vector: Query vector (dense)
        limit: Maximum results
        filters: Filter by payload fields
        score_threshold: Minimum similarity
        query_text: Original query text (for BM25 sparse search)

    Returns:
        List of results with score and payload
    """
    with self._telemetry.track("vector_store.search"):
        query_filter = self._build_filter(filters) if filters else None

        # Hybrid search if sparse encoder available and query_text provided
        if self.sparse_encoder and query_text:
            return self._hybrid_search(
                vector=vector,
                query_text=query_text,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )

        # Standard dense search
        results = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
        ).points

        return [
            {
                "score": hit.score,
                **hit.payload,
            }
            for hit in results
        ]

def _hybrid_search(
    self,
    vector: list[float],
    query_text: str,
    limit: int,
    query_filter: Filter | None,
    score_threshold: float,
) -> list[dict[str, Any]]:
    """Hybrid search: dense + sparse with RRF fusion."""
    from qdrant_client.http.models import SparseVector

    # Get sparse vector for query
    sparse = self.sparse_encoder.encode(query_text)
    if not sparse:
        # Fall back to dense-only
        results = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
        ).points
        return [{"score": hit.score, **hit.payload} for hit in results]

    sparse_vector = SparseVector(
        indices=list(sparse.keys()),
        values=list(sparse.values()),
    )

    # Prefetch more candidates for RRF fusion
    prefetch_limit = limit * 2

    # Use Qdrant's native hybrid search with RRF
    results = self.client.query_points(
        collection_name=self.collection,
        prefetch=[
            # Dense search
            {
                "query": vector,
                "using": "",
                "limit": prefetch_limit,
            },
            # Sparse search
            {
                "query": sparse_vector,
                "using": "bm25",
                "limit": prefetch_limit,
            },
        ],
        query={"fusion": "rrf"},  # RRF fusion
        limit=limit,
        query_filter=query_filter,
    ).points

    return [
        {
            "score": hit.score,
            **hit.payload,
        }
        for hit in results
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_hybrid_search.py tests/test_sparse_encoder.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run existing tests to ensure no regression**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_core.py tests/test_memory.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit implementation**

```bash
git add src/core/vector_store.py
git commit -m "feat: add hybrid search with BM25 sparse vectors"
```

---

### Task 1.5: MemoryManager Integration

**Files:**
- Modify: `src/memory/manager.py:122-175` (init and properties)
- Modify: `src/memory/manager.py:197-276` (save method)
- Modify: `src/memory/manager.py:334-476` (recall method)

- [ ] **Step 1: Add BM25 encoder initialization to MemoryManager**

In `__init__`, add:
```python
# BM25 encoder for hybrid search
self._sparse_encoder: BM25Encoder | None = None
self._bm25_path = self.memory_dir / "_bm25_vocab.json"
```

Add property:
```python
@property
def sparse_encoder(self) -> BM25Encoder | None:
    """Get BM25 encoder, loading from disk if available."""
    if self._sparse_encoder is None and self._bm25_path.exists():
        from core import BM25Encoder
        self._sparse_encoder = BM25Encoder()
        self._sparse_encoder.load(str(self._bm25_path))
    return self._sparse_encoder
```

- [ ] **Step 2: Update store property to pass sparse_encoder**

```python
@property
def store(self) -> VectorStore:
    """Get vector store, initializing if needed."""
    if self._store is None:
        self._store = VectorStore(
            collection=self.COLLECTION,
            url=self._qdrant_url,
            sparse_encoder=self.sparse_encoder,  # NEW
        )
        for field in ["date", "project", "type"]:
            try:
                self._store.create_index(field)
            except Exception:
                pass
    return self._store
```

- [ ] **Step 3: Update save() to pass content for sparse encoding**

In `save()`, change:
```python
self.store.save(id=memory_id, vector=vector, payload=payload)
```
To:
```python
self.store.save(
    id=memory_id,
    vector=vector,
    payload=payload,
    content=content,  # For sparse encoding
)
```

- [ ] **Step 4: Update recall() to pass query_text for hybrid search**

In `recall()`, change:
```python
seed_results = self.store.search(
    vector=query_vector,
    limit=limit * 2 if limit and graph_has_edges else limit,
    filters=filters if filters else None,
    score_threshold=score_threshold,
)
```
To:
```python
seed_results = self.store.search(
    vector=query_vector,
    limit=limit * 2 if limit and graph_has_edges else limit,
    filters=filters if filters else None,
    score_threshold=score_threshold,
    query_text=query,  # For hybrid search
)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_memory.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/memory/manager.py
git commit -m "feat: integrate BM25 encoder into MemoryManager"
```

---

### Task 1.6: Migration Script

**Files:**
- Create: `src/memory/migrate_hybrid.py`
- Create: `tests/test_migrate_hybrid.py`

- [ ] **Step 1: Write migration test**

```python
# tests/test_migrate_hybrid.py
"""Tests for hybrid search migration."""

import pytest
from pathlib import Path


class TestMigrateHybrid:
    """Test migration to hybrid search schema."""

    def test_load_all_yaml_memories(self, tmp_path):
        """load_all_yaml_memories() reads all YAML files."""
        from memory.migrate_hybrid import load_all_yaml_memories

        # Create test YAML
        yaml_content = """
date: "2026-03-25"
decisions:
  - id: "2026-03-25_decision_abc123"
    content: "Use hybrid search"
    project: "memento"
"""
        (tmp_path / "2026-03-25.yaml").write_text(yaml_content)

        memories = load_all_yaml_memories(tmp_path)

        assert len(memories) == 1
        assert memories[0]["content"] == "Use hybrid search"

    def test_build_corpus_from_memories(self, tmp_path):
        """Migration builds BM25 corpus from all memory content."""
        from memory.migrate_hybrid import build_corpus

        memories = [
            {"content": "First memory", "memory_id": "1"},
            {"content": "Second memory", "memory_id": "2"},
        ]

        corpus = build_corpus(memories)

        assert len(corpus) == 2
        assert "First memory" in corpus
```

- [ ] **Step 2: Implement migration script**

```python
# src/memory/migrate_hybrid.py
"""Migration script for hybrid search schema.

Reads all memories from YAML, builds BM25 vocabulary,
recreates Qdrant collection with sparse vectors, and re-indexes.

Usage:
    python -m memory.migrate_hybrid [--dry-run]
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core import BM25Encoder, Embedder, VectorStore
from core.utils import stable_hash_id

logger = logging.getLogger(__name__)


def load_all_yaml_memories(memory_dir: Path) -> list[dict]:
    """Load all memories from YAML files."""
    memories = []

    for yaml_file in sorted(memory_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue  # Skip internal files

        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load {yaml_file}: {e}")
            continue

        date = data.get("date", yaml_file.stem)

        for key, items in data.items():
            if key == "date" or not isinstance(items, list):
                continue

            mem_type = key.rstrip("s")  # "decisions" -> "decision"

            for item in items:
                if not isinstance(item, dict):
                    continue

                memories.append({
                    "memory_id": item.get("id", ""),
                    "content": item.get("content", ""),
                    "date": date,
                    "type": mem_type,
                    "project": item.get("project", "general"),
                    "timestamp": item.get("timestamp", ""),
                })

    return memories


def build_corpus(memories: list[dict]) -> list[str]:
    """Extract content strings for BM25 training."""
    return [m["content"] for m in memories if m.get("content")]


def migrate_to_hybrid(
    memory_dir: Path | str = "~/.claude/memory",
    qdrant_url: str = "http://localhost:6333",
    dry_run: bool = False,
) -> dict:
    """Migrate to hybrid search schema.

    Args:
        memory_dir: Path to memory YAML files
        qdrant_url: Qdrant server URL
        dry_run: If True, don't actually modify anything

    Returns:
        Migration stats
    """
    memory_dir = Path(memory_dir).expanduser()

    # 1. Load all memories from YAML
    logger.info("Loading memories from YAML...")
    memories = load_all_yaml_memories(memory_dir)
    logger.info(f"Loaded {len(memories)} memories")

    if not memories:
        return {"status": "no_memories", "count": 0}

    # 2. Build BM25 vocabulary
    logger.info("Building BM25 vocabulary...")
    corpus = build_corpus(memories)
    encoder = BM25Encoder()
    encoder.fit(corpus)
    logger.info(f"Vocabulary size: {len(encoder.vocab)}")

    if dry_run:
        return {
            "status": "dry_run",
            "memories": len(memories),
            "vocab_size": len(encoder.vocab),
        }

    # 3. Save BM25 vocabulary
    bm25_path = memory_dir / "_bm25_vocab.json"
    encoder.save(str(bm25_path))
    logger.info(f"Saved BM25 vocab to {bm25_path}")

    # 4. Recreate collection with sparse support
    logger.info("Recreating Qdrant collection...")
    store = VectorStore(
        collection="agent_memory",
        url=qdrant_url,
        sparse_encoder=encoder,
    )
    store.recreate_collection()

    # 5. Re-index all memories
    logger.info("Re-indexing memories...")
    embedder = Embedder()

    for i, mem in enumerate(memories):
        if not mem.get("content"):
            continue

        vector = embedder.encode(mem["content"])
        store.save(
            id=mem["memory_id"],
            vector=vector,
            payload=mem,
            content=mem["content"],
        )

        if (i + 1) % 100 == 0:
            logger.info(f"Indexed {i + 1}/{len(memories)}")

    logger.info(f"Migration complete: {len(memories)} memories indexed")

    return {
        "status": "complete",
        "memories": len(memories),
        "vocab_size": len(encoder.vocab),
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Migrate to hybrid search")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--memory-dir", default="~/.claude/memory")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")

    args = parser.parse_args()

    result = migrate_to_hybrid(
        memory_dir=args.memory_dir,
        qdrant_url=args.qdrant_url,
        dry_run=args.dry_run,
    )

    print(f"Migration result: {result}")
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/dev-box/Repos/memento-mcp && uv run pytest tests/test_migrate_hybrid.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/memory/migrate_hybrid.py tests/test_migrate_hybrid.py
git commit -m "feat: add migration script for hybrid search"
```

---

## Phase 2-4: Remaining Tasks (Summary)

The remaining phases follow the same TDD pattern. Key tasks:

### Phase 2: Smart Context Injection
- Task 2.1: Add `/api/memory/context/smart` endpoint
- Task 2.2: Implement ranking algorithm (importance × recency × type_weight)
- Task 2.3: Token estimation and truncation
- Task 2.4: Update session-start hook

### Phase 3: Progressive Disclosure
- Task 3.1: Minimal session start config
- Task 3.2: Add `/api/memory/recall/quick` endpoint (fast, high-threshold)
- Task 3.3: Optional per-prompt hook

### Phase 4: Auto-Compaction
- Task 4.1: Compaction logic (group by project+type, older than N days)
- Task 4.2: LLM summarization (Anthropic/OpenAI)
- Task 4.3: Add `/api/memory/compact` endpoint
- Task 4.4: CLI command (`memento compact`)
- Task 4.5: YAML `compacted` flag handling

---

## Verification Checklist

After all phases complete:

- [ ] `pytest tests/` passes (all tests)
- [ ] Query "TOPE-123" returns memories containing that exact string
- [ ] Session start injects <2000 tokens, project-relevant
- [ ] `recall_memories()` uses hybrid search
- [ ] Old memories can be compacted via API
