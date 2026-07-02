"""Core infrastructure: shared components for vector search and observability.

This module provides reusable building blocks:

    from core import VectorStore, Embedder, Telemetry

    # Create observable vector store
    store = VectorStore(collection="my_data")
    embedder = Embedder()

    # Everything is automatically traced
    store.save(content="hello", embedding=embedder.encode("hello"))
    results = store.search(query_embedding=embedder.encode("hi"))

All operations emit OTEL metrics for observability.
"""

from core.embeddings import Embedder
from core.sparse_encoder import BM25Encoder
from core.telemetry import Telemetry
from core.utils import rekall_env, stable_hash_id
from core.vector_store import VectorStore

__all__ = ["VectorStore", "Embedder", "Telemetry", "stable_hash_id", "rekall_env", "BM25Encoder"]
