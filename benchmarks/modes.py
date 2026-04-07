"""Three retrieval modes for LongMemEval benchmarking.

Each function takes one LongMemEval entry, ingests its haystack into
a fresh Qdrant collection, queries, and returns ranked session IDs.

Modes build on each other:
    dense       — semantic embeddings only (comparable to MemPalace raw)
    hybrid      — BM25 sparse + dense with RRF fusion
    hybrid+graph — hybrid + 1-hop knowledge graph expansion
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.dataset import build_session_corpus

_embedder = None
_EMBEDDING_DIM = 384


def _get_embedder():
    """Lazy-load embedder singleton."""
    global _embedder
    if _embedder is None:
        from core.embeddings import Embedder

        _embedder = Embedder()
    return _embedder


def _collection_name(question_id: str, mode: str) -> str:
    """Sanitize question_id for use as Qdrant collection name."""
    safe_id = question_id.replace("-", "_").replace(".", "_")
    return f"bench_{mode}_{safe_id}"


def _ingest_dense(
    entry: dict, qdrant_url: str, collection: str, include_assistant: bool = False
) -> tuple[list[str], "VectorStore"]:
    """Ingest haystack sessions into Qdrant with dense embeddings only."""
    from core.vector_store import VectorStore

    corpus = build_session_corpus(entry, include_assistant=include_assistant)
    embedder = _get_embedder()

    store = VectorStore(
        collection=collection, url=qdrant_url, embedding_dim=_EMBEDDING_DIM
    )
    store.recreate_collection()

    texts = [doc["text"] for doc in corpus]
    vectors = embedder.encode_batch(texts)
    session_ids = []

    for doc, vector in zip(corpus, vectors):
        store.save(
            id=doc["session_id"],
            vector=vector,
            payload={
                "session_id": doc["session_id"],
                "content": doc["text"],
                "date": doc["date"],
            },
        )
        session_ids.append(doc["session_id"])

    return session_ids, store


def _ingest_hybrid(
    entry: dict, qdrant_url: str, collection: str, include_assistant: bool = False
) -> tuple[list[str], "VectorStore"]:
    """Ingest haystack sessions with both dense and sparse (BM25) embeddings."""
    from core.sparse_encoder import BM25Encoder
    from core.vector_store import VectorStore

    corpus = build_session_corpus(entry, include_assistant=include_assistant)
    embedder = _get_embedder()

    # Build BM25 encoder from corpus
    bm25 = BM25Encoder()
    texts = [doc["text"] for doc in corpus]
    bm25.fit(texts)

    # Create store with hybrid search enabled
    store = VectorStore(
        collection=collection,
        url=qdrant_url,
        embedding_dim=_EMBEDDING_DIM,
        sparse_encoder=bm25,
    )
    store.recreate_collection()

    vectors = embedder.encode_batch(texts)
    session_ids = []

    for doc, vector in zip(corpus, vectors):
        store.save(
            id=doc["session_id"],
            vector=vector,
            payload={
                "session_id": doc["session_id"],
                "content": doc["text"],
                "date": doc["date"],
            },
            content=doc["text"],  # Triggers sparse encoding
        )
        session_ids.append(doc["session_id"])

    return session_ids, store


def retrieve_dense(
    entry: dict,
    qdrant_url: str = "http://localhost:6333",
    n_results: int = 50,
    include_assistant: bool = False,
) -> list[str]:
    """Mode 1: Dense-only retrieval (apples-to-apples vs MemPalace raw).

    Args:
        entry: LongMemEval question entry with haystack_sessions
        qdrant_url: Qdrant server URL (default: production)
        n_results: Max results to return
        include_assistant: Include assistant turns in documents

    Returns:
        List of session IDs ranked by relevance
    """
    collection = _collection_name(entry["question_id"], "dense")
    session_ids, store = _ingest_dense(entry, qdrant_url, collection, include_assistant)

    embedder = _get_embedder()
    query_vector = embedder.encode(entry["question"])

    results = store.search(
        vector=query_vector,
        limit=min(n_results, len(session_ids)),
        score_threshold=0.0,
    )

    # Rank results
    ranked = [r["session_id"] for r in results if "session_id" in r]
    seen = set(ranked)

    # Add remaining sessions in original order
    for sid in session_ids:
        if sid not in seen:
            ranked.append(sid)

    store.delete_collection()
    return ranked


def retrieve_hybrid(
    entry: dict,
    qdrant_url: str = "http://localhost:6333",
    n_results: int = 50,
    include_assistant: bool = False,
) -> list[str]:
    """Mode 2: Hybrid BM25 + dense with RRF fusion.

    Args:
        entry: LongMemEval question entry with haystack_sessions
        qdrant_url: Qdrant server URL (default: production)
        n_results: Max results to return
        include_assistant: Include assistant turns in documents

    Returns:
        List of session IDs ranked by hybrid relevance
    """
    collection = _collection_name(entry["question_id"], "hybrid")
    session_ids, store = _ingest_hybrid(entry, qdrant_url, collection, include_assistant)

    embedder = _get_embedder()
    query_vector = embedder.encode(entry["question"])

    # Hybrid search: combines dense + sparse via RRF
    results = store.search(
        vector=query_vector,
        limit=min(n_results, len(session_ids)),
        score_threshold=0.0,
        query_text=entry["question"],  # Enables BM25 fusion
    )

    # Rank results
    ranked = [r["session_id"] for r in results if "session_id" in r]
    seen = set(ranked)

    # Add remaining sessions in original order
    for sid in session_ids:
        if sid not in seen:
            ranked.append(sid)

    store.delete_collection()
    return ranked


def retrieve_hybrid_graph(
    entry: dict,
    qdrant_url: str = "http://localhost:6333",
    n_results: int = 50,
    include_assistant: bool = False,
    similarity_threshold: float = 0.5,
) -> list[str]:
    """Mode 3: Hybrid search + knowledge graph expansion.

    Hybrid search gets seed results, then expands via 1-hop graph neighbors.

    Args:
        entry: LongMemEval question entry with haystack_sessions
        qdrant_url: Qdrant server URL (default: production)
        n_results: Max results to return
        include_assistant: Include assistant turns in documents
        similarity_threshold: Min cosine similarity for graph edges

    Returns:
        List of session IDs ranked by hybrid + graph relevance
    """
    collection = _collection_name(entry["question_id"], "graph")
    session_ids, store = _ingest_hybrid(entry, qdrant_url, collection, include_assistant)

    embedder = _get_embedder()

    with tempfile.TemporaryDirectory() as tmpdir:
        graph_path = Path(tmpdir) / "bench_graph.json"
        from memory.knowledge_graph import KnowledgeGraph

        graph = KnowledgeGraph(graph_path)

        # Add all sessions as graph nodes
        for doc in build_session_corpus(entry, include_assistant):
            graph.add_node(
                memory_id=doc["session_id"],
                topic=doc["text"][:100],
                importance=0.5,
                memory_type="fact",
            )

        # Build similarity-based edges from embeddings
        texts = [doc["text"] for doc in build_session_corpus(entry, include_assistant)]
        vectors = embedder.encode_batch(texts)

        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                # Compute cosine similarity
                dot = sum(a * b for a, b in zip(vectors[i], vectors[j]))
                norm_i = sum(a * a for a in vectors[i]) ** 0.5
                norm_j = sum(a * a for a in vectors[j]) ** 0.5

                if norm_i and norm_j:
                    sim = dot / (norm_i * norm_j)
                else:
                    sim = 0.0

                # Add bidirectional edge if similar enough
                if sim > similarity_threshold:
                    graph.add_edge(
                        source=session_ids[i],
                        target=session_ids[j],
                        relation="related_to",
                        weight=sim,
                    )

        graph.save()

        # Hybrid search for seed results
        query_vector = embedder.encode(entry["question"])
        seed_results = store.search(
            vector=query_vector,
            limit=min(n_results * 2, len(session_ids)),
            score_threshold=0.0,
            query_text=entry["question"],
        )

        seed_ids = [r["session_id"] for r in seed_results if "session_id" in r]

        # Expand via 1-hop neighbors in graph
        expanded_ids: set[str] = set()
        for sid in seed_ids[:10]:  # Expand from top-10 seeds only
            neighbors = graph.get_neighbors(sid, hops=1)
            expanded_ids.update(neighbors)

        # Combine: seeds first, then expanded, then remaining
        ranked = []
        seen: set[str] = set()

        # 1. Ranked seed results
        for sid in seed_ids:
            if sid not in seen:
                ranked.append(sid)
                seen.add(sid)

        # 2. Expanded neighbors
        for sid in expanded_ids:
            if sid not in seen:
                ranked.append(sid)
                seen.add(sid)

        # 3. Remaining sessions in original order
        for sid in session_ids:
            if sid not in seen:
                ranked.append(sid)
                seen.add(sid)

    store.delete_collection()
    return ranked
