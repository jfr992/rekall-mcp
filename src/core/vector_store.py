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
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from core.telemetry import Telemetry

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
    ) -> None:
        """Initialize vector store.

        Args:
            collection: Collection name (e.g., "memories", "docs")
            url: Qdrant server URL
            api_key: Optional API key for Qdrant Cloud
            embedding_dim: Vector dimensions (default: 384 for MiniLM)
        """
        self.collection = collection
        self.url = url
        self.api_key = api_key
        self.embedding_dim = embedding_dim

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
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE,
                ),
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
    ) -> None:
        """Save a vector with metadata.

        Args:
            id: Unique identifier (string or int)
            vector: Embedding vector
            payload: Metadata dict (searchable via filters)

        Example:
            store.save(
                id="mem_001",
                vector=embedder.encode("Decided to use Python"),
                payload={"type": "decision", "project": "my-app"}
            )
        """
        with self._telemetry.track("vector_store.save"):
            # Convert string ID to int hash if needed
            point_id = id if isinstance(id, int) else hash(id) % (2**63)

            point = PointStruct(
                id=point_id,
                vector=vector,
                payload=payload or {},
            )

            self.client.upsert(
                collection_name=self.collection,
                points=[point],
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
                point_id = item_id if isinstance(item_id, int) else hash(item_id) % (2**63)

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
    ) -> list[dict[str, Any]]:
        """Search for similar vectors.

        Args:
            vector: Query vector
            limit: Maximum results
            filters: Filter by payload fields {"field": "value"}
            score_threshold: Minimum similarity (0-1)

        Returns:
            List of results with score and payload

        Example:
            results = store.search(
                vector=embedder.encode("architecture"),
                limit=5,
                filters={"project": "my-app"}
            )
        """
        with self._telemetry.track("vector_store.search"):
            # Build filter
            query_filter = self._build_filter(filters) if filters else None

            # Execute search
            results = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold,
            ).points

            # Format results
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
    ) -> list[dict[str, Any]]:
        """Get all vectors matching filters (no query vector needed).

        Args:
            filters: Filter by payload fields
            limit: Maximum results

        Returns:
            List of payloads (no scores since not searching)

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
                with_vectors=False,
            )

            return [point.payload for point in results]

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
