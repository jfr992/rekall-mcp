"""VectorStore: Save and search vectors in Qdrant.

Usage:
    from core import VectorStore, Embedder

    store = VectorStore(collection="memories")
    embedder = Embedder()

    # Save
    store.save(
        id="memory_001",
        vector=embedder.encode("Architecture decision"),
        payload={"type": "decision", "project": "my-app"}
    )

    # Search
    results = store.search(
        vector=embedder.encode("architecture"),
        limit=5,
        filters={"project": "my-app"}
    )

All operations are traced via Telemetry.
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    PointStruct,
    Prefetch,
    Range,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from core.telemetry import Telemetry
from core.utils import stable_hash_id

logger = logging.getLogger(__name__)


class VectorStore:
    """Vector database operations using Qdrant.

    Provides a clean interface for:
    - Saving vectors with metadata (payload)
    - Semantic search with filters
    - Collection management

    All operations emit telemetry metrics.

    Example:
        store = VectorStore(collection="docs")

        # Save a vector
        store.save(
            id="doc_123",
            vector=[0.1, 0.2, ...],
            payload={"title": "Getting Started"}
        )

        # Search
        results = store.search(
            vector=[0.1, 0.2, ...],
            limit=10
        )
    """

    def __init__(
        self,
        collection: str,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        embedding_dim: int = 384,
        sparse_encoder: Any | None = None,
    ) -> None:
        """Initialize vector store.

        Args:
            collection: Collection name (e.g., "memories", "docs")
            url: Qdrant server URL
            api_key: Optional API key for Qdrant Cloud
            embedding_dim: Vector dimensions (default: 384 for MiniLM)
            sparse_encoder: BM25Encoder for hybrid search (optional)
        """
        self.collection = collection
        self.url = url
        self.api_key = api_key
        self.embedding_dim = embedding_dim
        self.sparse_encoder = sparse_encoder

        self._client: QdrantClient | None = None
        self._telemetry = Telemetry.get()

    # -------------------------------------------------------------------------
    # CONNECTION: Lazy client initialization
    # -------------------------------------------------------------------------

    @property
    def client(self) -> QdrantClient:
        """Get Qdrant client, connecting if needed."""
        if self._client is None:
            with self._telemetry.track("vector_store.connect"):
                self._connect()
        return self._client

    def _connect(self) -> None:
        """Connect to Qdrant and ensure collection exists."""
        logger.info(f"Connecting to Qdrant at {self.url}")
        self._client = QdrantClient(url=self.url, api_key=self.api_key)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        collections = [c.name for c in self._client.get_collections().collections]

        if self.collection not in collections:
            logger.info(f"Creating collection: {self.collection}")
            sparse_config = None
            if self.sparse_encoder is not None:
                # SparseVectorsConfig is a Dict alias — use plain dict
                sparse_config = {"bm25": SparseVectorParams()}
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE,
                ),
                sparse_vectors_config=sparse_config,
            )

    def create_index(self, field: str, field_type: str = "keyword") -> None:
        """Create an index for faster filtering.

        Args:
            field: Field name in payload (e.g., "project", "type")
            field_type: Index type ("keyword" for exact match)

        Example:
            store.create_index("project")
            store.create_index("type")
        """
        with self._telemetry.track("vector_store.create_index"):
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name=field,
                field_schema=field_type,
            )
            logger.info(f"Created index on {field}")

    # -------------------------------------------------------------------------
    # SAVE: Store vectors
    # -------------------------------------------------------------------------

    def save(
        self,
        id: str | int,
        vector: list[float],
        payload: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> None:
        """Save a vector with metadata.

        Args:
            id: Unique identifier (string or int)
            vector: Embedding vector
            payload: Metadata dict (searchable via filters)
            content: Original text for sparse BM25 encoding (optional)

        Example:
            store.save(
                id="mem_001",
                vector=embedder.encode("Decided to use Python"),
                payload={"type": "decision", "project": "my-app"},
                content="Decided to use Python",
            )
        """
        with self._telemetry.track("vector_store.save"):
            point_id = id if isinstance(id, int) else stable_hash_id(id)

            # Build sparse vector if encoder and content available
            if self.sparse_encoder is not None and content:
                sparse = self.sparse_encoder.encode(content)
                if sparse:
                    self.client.upsert(
                        collection_name=self.collection,
                        points=[
                            {
                                "id": point_id,
                                "vector": {
                                    "": vector,
                                    "bm25": SparseVector(
                                        indices=list(sparse.keys()),
                                        values=list(sparse.values()),
                                    ),
                                },
                                "payload": payload or {},
                            }
                        ],
                    )
                    return

            # Dense-only save (no encoder or no content)
            self.client.upsert(
                collection_name=self.collection,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload or {},
                    )
                ],
            )

    def save_batch(
        self,
        items: list[dict[str, Any]],
        batch_size: int = 100,
    ) -> int:
        """Save multiple vectors efficiently.

        Args:
            items: List of {"id": ..., "vector": [...], "payload": {...}}
            batch_size: Batch size for upserting

        Returns:
            Number of items saved

        Example:
            store.save_batch([
                {"id": "1", "vector": [...], "payload": {"type": "note"}},
                {"id": "2", "vector": [...], "payload": {"type": "note"}},
            ])
        """
        with self._telemetry.track("vector_store.save_batch"):
            points = []

            for item in items:
                item_id = item["id"]
                point_id = item_id if isinstance(item_id, int) else stable_hash_id(item_id)

                points.append(
                    PointStruct(
                        id=point_id,
                        vector=item["vector"],
                        payload=item.get("payload", {}),
                    )
                )

                # Batch upsert
                if len(points) >= batch_size:
                    self.client.upsert(collection_name=self.collection, points=points)
                    points = []

            # Remaining
            if points:
                self.client.upsert(collection_name=self.collection, points=points)

            return len(items)

    # -------------------------------------------------------------------------
    # SEARCH: Find similar vectors
    # -------------------------------------------------------------------------

    def search(
        self,
        vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float = 0.0,
        query_text: str = "",
    ) -> list[dict[str, Any]]:
        """Search for similar vectors (hybrid if sparse encoder available).

        Args:
            vector: Query vector (dense)
            limit: Maximum results
            filters: Filter by payload fields {"field": "value"}
            score_threshold: Minimum similarity (0-1)
            query_text: Original query text for BM25 sparse search

        Returns:
            List of results with score and payload

        Example:
            results = store.search(
                vector=embedder.encode("TOPE-123"),
                query_text="TOPE-123",
                limit=5,
            )
        """
        with self._telemetry.track("vector_store.search"):
            query_filter = self._build_filter(filters) if filters else None

            # Hybrid search if encoder + query text available
            if self.sparse_encoder is not None and query_text:
                sparse = self.sparse_encoder.encode(query_text)
                if sparse:
                    prefetch_limit = limit * 2
                    results = self.client.query_points(
                        collection_name=self.collection,
                        prefetch=[
                            Prefetch(
                                query=vector,
                                using="",
                                limit=prefetch_limit,
                                filter=query_filter,
                            ),
                            Prefetch(
                                query=SparseVector(
                                    indices=list(sparse.keys()),
                                    values=list(sparse.values()),
                                ),
                                using="bm25",
                                limit=prefetch_limit,
                                filter=query_filter,
                            ),
                        ],
                        query=FusionQuery(fusion=Fusion.RRF),
                        query_filter=query_filter,
                        limit=limit,
                    ).points

                    return [{"score": hit.score, **hit.payload} for hit in results]

            # Dense-only search
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

    def scroll(
        self,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        """Get all vectors matching filters (no query vector needed).

        Args:
            filters: Filter by payload fields
            limit: Maximum results
            with_vectors: Include vectors in returned payloads

        Returns:
            List of payloads (with vectors if requested)

        Example:
            all_decisions = store.scroll(filters={"type": "decision"})
        """
        with self._telemetry.track("vector_store.scroll"):
            query_filter = self._build_filter(filters) if filters else None

            results, _ = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=with_vectors,
            )

            if not with_vectors:
                return [point.payload for point in results]

            merged: list[dict[str, Any]] = []
            for point in results:
                payload = dict(point.payload or {})
                vector = point.vector
                if isinstance(vector, dict):
                    vector = next(iter(vector.values()), [])
                payload["vector"] = list(vector or [])
                merged.append(payload)

            return merged

    def _build_filter(self, filters: dict[str, Any]) -> Filter:
        """Convert dict filters to Qdrant Filter."""
        conditions = []

        for key, value in filters.items():
            if isinstance(value, dict):
                # Range filter: {"date": {"gte": "2026-01-01"}}
                conditions.append(FieldCondition(key=key, range=Range(**value)))
            else:
                # Exact match: {"project": "my-app"}
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

        return Filter(must=conditions)

    # -------------------------------------------------------------------------
    # DELETE: Remove vectors
    # -------------------------------------------------------------------------

    def delete(self, filters: dict[str, Any]) -> None:
        """Delete vectors matching filters.

        Args:
            filters: Which vectors to delete

        Example:
            store.delete(filters={"project": "old-project"})
        """
        with self._telemetry.track("vector_store.delete"):
            self.client.delete(
                collection_name=self.collection,
                points_selector=self._build_filter(filters),
            )

    def delete_collection(self) -> None:
        """Delete the entire collection."""
        with self._telemetry.track("vector_store.delete_collection"):
            self.client.delete_collection(collection_name=self.collection)
            logger.info(f"Deleted collection: {self.collection}")

    def recreate_collection(self) -> None:
        """Delete and recreate the collection (useful for migration)."""
        with self._telemetry.track("vector_store.recreate_collection"):
            # Delete if exists
            collections = [c.name for c in self.client.get_collections().collections]
            if self.collection in collections:
                self.client.delete_collection(collection_name=self.collection)
                logger.info(f"Deleted collection: {self.collection}")

            # Create fresh
            self._ensure_collection()
            logger.info(f"Recreated collection: {self.collection}")

    # -------------------------------------------------------------------------
    # INFO: Collection stats
    # -------------------------------------------------------------------------

    def count(self) -> int:
        """Get number of vectors in collection."""
        with self._telemetry.track("vector_store.count"):
            info = self.client.get_collection(collection_name=self.collection)
            count = info.points_count
            self._telemetry.gauge(f"vector_store.{self.collection}.size", count)
            return count

    def __repr__(self) -> str:
        connected = "connected" if self._client else "not connected"
        return f"VectorStore(collection={self.collection}, {connected})"
