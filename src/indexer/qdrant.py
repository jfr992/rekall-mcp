"""Qdrant vector database integration for document indexing."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from core.utils import stable_hash_id

if TYPE_CHECKING:
    from indexer.chunker import DocumentChunk

logger = logging.getLogger(__name__)


class QdrantIndexer:
    """Index documents in Qdrant vector database.

    This is separate from the memory system's VectorStore - it's designed
    for indexing crawled documentation, not agent memories.

    Example:
        indexer = QdrantIndexer(collection_name="my_docs")
        indexer.ensure_collection(embedding_dim=384)
        indexer.index_chunks(chunks, embeddings)
        results = indexer.search(query_embedding)
    """

    DEFAULT_COLLECTION = "tool_docs"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        """Initialize Qdrant client.

        Args:
            url: Qdrant server URL (default: QDRANT_URL env var or localhost:6333)
            api_key: Optional API key for Qdrant Cloud
            collection_name: Name of collection to use
        """
        self.url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key or os.environ.get("QDRANT_API_KEY")
        self.collection_name = collection_name or os.environ.get(
            "DOCS_COLLECTION", self.DEFAULT_COLLECTION
        )
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        """Lazy load Qdrant client."""
        if self._client is None:
            self._client = QdrantClient(url=self.url, api_key=self.api_key)
        return self._client

    def ensure_collection(self, embedding_dim: int) -> None:
        """Create collection if it doesn't exist.

        Args:
            embedding_dim: Dimension of embedding vectors
        """
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            logger.info(f"Creating collection: {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=embedding_dim,
                    distance=Distance.COSINE,
                ),
            )

            # Create payload indexes for filtering
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="category",
                field_schema="keyword",
            )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="chunk_type",
                field_schema="keyword",
            )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="doc_id",
                field_schema="keyword",
            )
            logger.info(f"Created collection with indexes: {self.collection_name}")
        else:
            logger.info(f"Collection {self.collection_name} already exists")

    def index_chunks(
        self,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
        batch_size: int = 100,
    ) -> int:
        """Index document chunks with embeddings.

        Args:
            chunks: List of document chunks
            embeddings: Corresponding embeddings
            batch_size: Batch size for upserting

        Returns:
            Number of points indexed
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have same length"
            )

        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            point = PointStruct(
                id=stable_hash_id(chunk.chunk_id),
                vector=embedding,
                payload={
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    **chunk.metadata,
                },
            )
            points.append(point)

            # Batch upsert
            if len(points) >= batch_size:
                self.client.upsert(collection_name=self.collection_name, points=points)
                logger.info(f"Indexed batch of {len(points)} points")
                points = []

        # Index remaining points
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
            logger.info(f"Indexed final batch of {len(points)} points")

        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        category: str | None = None,
        chunk_type: str | None = None,
        score_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search for similar documents.

        Args:
            query_embedding: Query vector
            limit: Maximum number of results
            category: Optional category filter
            chunk_type: Optional chunk type filter
            score_threshold: Minimum similarity score

        Returns:
            List of search results with scores
        """
        # Build filter
        conditions = []
        if category:
            conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if chunk_type:
            conditions.append(FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type)))

        query_filter = Filter(must=conditions) if conditions else None

        # Execute search
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
        ).points

        # Format results
        return [
            {
                "score": hit.score,
                "content": hit.payload.get("content", ""),
                "url": hit.payload.get("url", ""),
                "title": hit.payload.get("title", ""),
                "category": hit.payload.get("category", ""),
                "chunk_type": hit.payload.get("chunk_type", ""),
                "doc_id": hit.payload.get("doc_id", ""),
            }
            for hit in results
        ]

    def delete_collection(self) -> None:
        """Delete the collection."""
        self.client.delete_collection(collection_name=self.collection_name)
        logger.info(f"Deleted collection: {self.collection_name}")

    def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        try:
            info = self.client.get_collection(collection_name=self.collection_name)
            return {
                "collection": self.collection_name,
                "points_count": info.points_count,
                "status": info.status.name if hasattr(info.status, "name") else str(info.status),
            }
        except Exception as e:
            return {"collection": self.collection_name, "error": str(e)}
