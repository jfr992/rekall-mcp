"""CLI for indexing crawled documents into Qdrant."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for indexer CLI."""
    parser = argparse.ArgumentParser(
        description="Index crawled documents into Qdrant for semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index documents from crawled_docs directory
  python -m indexer.cli --input crawled_docs

  # Index with custom Qdrant URL
  python -m indexer.cli --input docs --qdrant-url http://qdrant:6333

  # Recreate collection (delete existing)
  python -m indexer.cli --input docs --recreate

  # Use custom collection name
  python -m indexer.cli --input docs --collection my_tool_docs
""",
    )
    parser.add_argument(
        "--input",
        "-i",
        default="crawled_docs",
        help="Input directory with crawled documents (default: crawled_docs)",
    )
    parser.add_argument(
        "--qdrant-url",
        default=None,
        help="Qdrant server URL (default: QDRANT_URL env var or localhost:6333)",
    )
    parser.add_argument(
        "--collection",
        "-c",
        default=None,
        help="Collection name (default: DOCS_COLLECTION env var or tool_docs)",
    )
    parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Sentence transformer model name (default: all-MiniLM-L6-v2)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for embedding generation (default: 32)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Target chunk size in characters (default: 512)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate collection (delete existing data)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        sys.exit(1)

    # Load manifest
    manifest_file = input_dir / "manifest.json"
    if not manifest_file.exists():
        logger.error(f"Manifest not found: {manifest_file}")
        logger.error("Run the crawler first to generate documents")
        sys.exit(1)

    with open(manifest_file) as f:
        manifest = json.load(f)

    logger.info(f"Found {manifest['total_documents']} documents to index")

    # Set environment variables if provided
    if args.qdrant_url:
        os.environ["QDRANT_URL"] = args.qdrant_url
    if args.collection:
        os.environ["DOCS_COLLECTION"] = args.collection

    # Initialize components
    from core import Embedder
    from indexer.chunker import DocumentChunker
    from indexer.qdrant import QdrantIndexer

    chunker = DocumentChunker(chunk_size=args.chunk_size, chunk_overlap=50)
    embedder = Embedder(model_name=args.model)
    indexer = QdrantIndexer(
        url=args.qdrant_url,
        collection_name=args.collection,
    )

    # Recreate collection if requested
    if args.recreate:
        try:
            indexer.delete_collection()
            logger.info("Deleted existing collection")
        except Exception:
            pass  # Collection might not exist

    # Ensure collection exists
    indexer.ensure_collection(embedding_dim=embedder.dimension)

    # Process documents
    all_chunks = []
    for doc_info in manifest["documents"]:
        doc_file = input_dir / f"{doc_info['id']}.json"
        if not doc_file.exists():
            logger.warning(f"Document file not found: {doc_file}")
            continue

        with open(doc_file) as f:
            document = json.load(f)

        chunks = chunker.chunk_document(document)
        all_chunks.extend(chunks)
        logger.info(f"Chunked '{doc_info['title'][:40]}': {len(chunks)} chunks")

    logger.info(f"Total chunks to index: {len(all_chunks)}")

    if not all_chunks:
        logger.warning("No chunks to index!")
        sys.exit(0)

    # Generate embeddings
    logger.info("Generating embeddings...")
    chunk_texts = [chunk.content for chunk in all_chunks]

    # Process in batches
    embeddings = []
    for i in range(0, len(chunk_texts), args.batch_size):
        batch = chunk_texts[i : i + args.batch_size]
        batch_embeddings = [embedder.encode(text) for text in batch]
        embeddings.extend(batch_embeddings)
        logger.info(f"Embedded {min(i + args.batch_size, len(chunk_texts))}/{len(chunk_texts)}")

    # Index in Qdrant
    logger.info("Indexing in Qdrant...")
    indexer.index_chunks(all_chunks, embeddings)

    # Get stats
    stats = indexer.get_stats()
    logger.info("Indexing complete!")
    logger.info(f"Collection: {stats.get('collection')}")
    logger.info(f"Total points: {stats.get('points_count')}")
    logger.info(f"Status: {stats.get('status')}")


if __name__ == "__main__":
    main()
