"""Tests for crawler and indexer modules."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Check if scrapy is available
try:
    import importlib.util

    SCRAPY_AVAILABLE = importlib.util.find_spec("scrapy") is not None
except ImportError:
    SCRAPY_AVAILABLE = False


# =============================================================================
# Test: DocumentChunker
# =============================================================================


class TestDocumentChunker:
    """Tests for the document chunker."""

    def test_import(self):
        """Test chunker can be imported."""
        from indexer.chunker import DocumentChunk, DocumentChunker

        assert DocumentChunker is not None
        assert DocumentChunk is not None

    def test_chunk_simple_document(self):
        """Test chunking a simple document."""
        from indexer.chunker import DocumentChunker

        chunker = DocumentChunker(chunk_size=512, min_chunk_size=50)

        document = {
            "id": "test_doc_001",
            "url": "https://example.com/docs/test",
            "title": "Test Document",
            "description": "This is a test document for chunking.",
            "content": "This is the main content. " * 50,  # ~250 chars
            "category": "tutorials",
            "code_examples": [],
        }

        chunks = chunker.chunk_document(document)

        assert len(chunks) >= 1
        assert chunks[0].doc_id == "test_doc_001"
        assert "Test Document" in chunks[0].content  # Header chunk
        print(f"✅ Created {len(chunks)} chunks from document")

    def test_chunk_with_code_examples(self):
        """Test that code examples become separate chunks."""
        from indexer.chunker import DocumentChunker

        chunker = DocumentChunker(chunk_size=512, min_chunk_size=20)

        document = {
            "id": "test_doc_002",
            "url": "https://example.com/docs/api",
            "title": "API Reference",
            "description": "API documentation",
            "content": "Use the API like this. " * 20,
            "category": "api",
            "code_examples": [
                {"language": "python", "code": "import requests\nresponse = requests.get('/api')"},
                {"language": "bash", "code": "curl https://api.example.com/v1/"},
            ],
        }

        chunks = chunker.chunk_document(document)

        # Should have header, content, and code chunks
        chunk_types = [c.metadata.get("chunk_type") for c in chunks]
        assert "header" in chunk_types
        assert "code" in chunk_types

        # Find code chunks
        code_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "code"]
        assert len(code_chunks) == 2

        # Verify language metadata
        languages = [c.metadata.get("language") for c in code_chunks]
        assert "python" in languages
        assert "bash" in languages

        print(f"✅ Code examples chunked correctly: {len(code_chunks)} code chunks")

    def test_chunk_large_document(self):
        """Test chunking a large document splits properly."""
        from indexer.chunker import DocumentChunker

        chunker = DocumentChunker(chunk_size=500, min_chunk_size=100)

        # Create large content
        large_content = "\n\n".join([f"Section {i}: " + "Content " * 100 for i in range(10)])

        document = {
            "id": "large_doc",
            "url": "https://example.com/large",
            "title": "Large Document",
            "description": "A very large document",
            "content": large_content,
            "category": "general",
            "code_examples": [],
        }

        chunks = chunker.chunk_document(document)

        # Should create multiple chunks
        assert len(chunks) > 3
        print(f"✅ Large document split into {len(chunks)} chunks")

        # Each chunk should be reasonably sized (allow 2x for sentence boundaries)
        for chunk in chunks:
            assert len(chunk.content) <= 1000  # Allow overflow for sentence boundaries

    def test_chunk_metadata_preserved(self):
        """Test that metadata is preserved in chunks."""
        from indexer.chunker import DocumentChunker

        chunker = DocumentChunker()

        document = {
            "id": "meta_test",
            "url": "https://example.com/meta",
            "title": "Metadata Test",
            "description": "Testing metadata preservation",
            "content": "Content for testing metadata. " * 30,
            "category": "testing",
            "code_examples": [],
        }

        chunks = chunker.chunk_document(document)

        for chunk in chunks:
            assert chunk.metadata.get("url") == "https://example.com/meta"
            assert chunk.metadata.get("title") == "Metadata Test"
            assert chunk.metadata.get("category") == "testing"
            assert "chunk_type" in chunk.metadata

        print("✅ Metadata preserved in all chunks")


# =============================================================================
# Test: QdrantIndexer
# =============================================================================


@pytest.mark.integration
class TestQdrantIndexer:
    """Tests for the Qdrant indexer."""

    def test_import(self):
        """Test indexer can be imported."""
        from indexer.qdrant import QdrantIndexer

        assert QdrantIndexer is not None

    def test_indexer_initialization(self, monkeypatch):
        """Test indexer initializes with correct defaults."""
        monkeypatch.delenv("QDRANT_URL", raising=False)
        from indexer.qdrant import QdrantIndexer

        indexer = QdrantIndexer()

        assert indexer.collection_name == "tool_docs"
        assert "6333" in indexer.url

    def test_indexer_custom_config(self):
        """Test indexer accepts custom configuration."""
        from indexer.qdrant import QdrantIndexer

        indexer = QdrantIndexer(
            url="http://custom:6333",
            collection_name="my_docs",
        )

        assert indexer.url == "http://custom:6333"
        assert indexer.collection_name == "my_docs"
        print("✅ Indexer accepts custom config")

    def test_indexer_env_vars(self):
        """Test indexer reads from environment variables."""
        from indexer.qdrant import QdrantIndexer

        # Save original values
        original_url = os.environ.get("QDRANT_URL")
        original_collection = os.environ.get("DOCS_COLLECTION")

        os.environ["QDRANT_URL"] = "http://env-qdrant:6333"
        os.environ["DOCS_COLLECTION"] = "env_docs"

        try:
            indexer = QdrantIndexer()
            assert indexer.url == "http://env-qdrant:6333"
            assert indexer.collection_name == "env_docs"
            print("✅ Indexer reads from environment")
        finally:
            # Restore original values
            if original_url is not None:
                os.environ["QDRANT_URL"] = original_url
            elif "QDRANT_URL" in os.environ:
                del os.environ["QDRANT_URL"]
            if original_collection is not None:
                os.environ["DOCS_COLLECTION"] = original_collection
            elif "DOCS_COLLECTION" in os.environ:
                del os.environ["DOCS_COLLECTION"]

    @pytest.mark.skipif(
        os.environ.get("QDRANT_URL") is None,
        reason="Qdrant not available",
    )
    def test_ensure_collection(self):
        """Test creating a collection in Qdrant."""
        from indexer.qdrant import QdrantIndexer

        indexer = QdrantIndexer(collection_name="test_collection_temp")

        try:
            indexer.ensure_collection(embedding_dim=384)
            stats = indexer.get_stats()
            assert stats.get("collection") == "test_collection_temp"
            print(f"✅ Collection created: {stats}")
        finally:
            try:
                indexer.delete_collection()
            except Exception:
                pass

    @pytest.mark.skipif(
        os.environ.get("QDRANT_URL") is None,
        reason="Qdrant not available",
    )
    def test_index_and_search(self):
        """Test indexing chunks and searching."""
        from indexer.chunker import DocumentChunk
        from indexer.qdrant import QdrantIndexer

        indexer = QdrantIndexer(collection_name="test_search_temp")

        try:
            # Create collection
            indexer.ensure_collection(embedding_dim=3)

            # Create test chunks
            chunks = [
                DocumentChunk(
                    doc_id="doc1",
                    chunk_id="doc1_chunk_0",
                    content="Python is a programming language",
                    metadata={"category": "programming", "chunk_type": "content"},
                ),
                DocumentChunk(
                    doc_id="doc2",
                    chunk_id="doc2_chunk_0",
                    content="JavaScript runs in browsers",
                    metadata={"category": "web", "chunk_type": "content"},
                ),
            ]

            # Fake embeddings (just for testing)
            embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

            # Index
            indexed = indexer.index_chunks(chunks, embeddings)
            assert indexed == 2

            # Search
            results = indexer.search(query_embedding=[0.1, 0.2, 0.3], limit=5)
            assert len(results) > 0
            print(f"✅ Indexed {indexed} chunks, search returned {len(results)} results")

        finally:
            try:
                indexer.delete_collection()
            except Exception:
                pass


# =============================================================================
# Test: Crawler Config
# =============================================================================


class TestCrawlerConfig:
    """Tests for crawler configuration loading."""

    @pytest.mark.skipif(not SCRAPY_AVAILABLE, reason="Scrapy not installed")
    def test_load_config(self):
        """Test loading crawler configuration from YAML."""
        from crawler.spider import load_crawl_config

        # Create temp config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
target:
  name: test-docs
  start_urls:
    - https://test.example.com/
  allowed_domains:
    - test.example.com
  categories:
    api:
      - /api/
crawler:
  download_delay: 1.0
""")
            config_path = f.name

        try:
            config = load_crawl_config(config_path)

            assert config["target"]["name"] == "test-docs"
            assert "https://test.example.com/" in config["target"]["start_urls"]
            assert config["crawler"]["download_delay"] == 1.0
            print("✅ Config loaded successfully")
        finally:
            os.unlink(config_path)

    @pytest.mark.skipif(not SCRAPY_AVAILABLE, reason="Scrapy not installed")
    def test_config_not_found(self):
        """Test error when config file not found."""
        from crawler.spider import load_crawl_config

        with pytest.raises(FileNotFoundError):
            load_crawl_config("/nonexistent/path/config.yaml")

        print("✅ FileNotFoundError raised for missing config")


# =============================================================================
# Test: Document Pipeline
# =============================================================================


class TestDocumentPipeline:
    """Tests for the document pipeline."""

    def test_import(self):
        """Test pipeline can be imported."""
        from crawler.pipeline import DocumentPipeline

        assert DocumentPipeline is not None

    def test_pipeline_saves_documents(self):
        """Test pipeline saves documents to JSON files."""
        from crawler.pipeline import DocumentPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CRAWL_OUTPUT_DIR"] = tmpdir

            try:
                pipeline = DocumentPipeline()

                # Mock spider
                mock_spider = MagicMock()
                mock_spider.logger = MagicMock()

                pipeline.open_spider(mock_spider)

                # Process items
                items = [
                    {
                        "id": "doc001",
                        "url": "https://example.com/1",
                        "title": "Test Doc 1",
                        "category": "general",
                        "content": "Content 1",
                    },
                    {
                        "id": "doc002",
                        "url": "https://example.com/2",
                        "title": "Test Doc 2",
                        "category": "api",
                        "content": "Content 2",
                    },
                ]

                for item in items:
                    pipeline.process_item(item, mock_spider)

                pipeline.close_spider(mock_spider)

                # Verify files created
                output_dir = Path(tmpdir)
                assert (output_dir / "doc001.json").exists()
                assert (output_dir / "doc002.json").exists()
                assert (output_dir / "manifest.json").exists()

                # Verify manifest content
                with open(output_dir / "manifest.json") as f:
                    manifest = json.load(f)
                    assert manifest["total_documents"] == 2
                    assert len(manifest["documents"]) == 2

                print("✅ Pipeline saves documents and manifest correctly")

            finally:
                del os.environ["CRAWL_OUTPUT_DIR"]


# =============================================================================
# Test: End-to-End Workflow
# =============================================================================


class TestEndToEndWorkflow:
    """Test the complete crawler -> indexer workflow."""

    @pytest.mark.skipif(
        os.environ.get("QDRANT_URL") is None,
        reason="Qdrant not available",
    )
    def test_full_workflow(self):
        """Test complete workflow: create docs -> chunk -> index -> search."""
        from core import Embedder
        from indexer.chunker import DocumentChunker
        from indexer.qdrant import QdrantIndexer

        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Create mock crawled documents
            docs = [
                {
                    "id": "doc_python",
                    "url": "https://example.com/python",
                    "title": "Python Tutorial",
                    "description": "Learn Python programming",
                    "content": "Python is a versatile programming language. " * 20,
                    "category": "tutorials",
                    "code_examples": [
                        {"language": "python", "code": "print('Hello World')"},
                    ],
                },
                {
                    "id": "doc_api",
                    "url": "https://example.com/api",
                    "title": "API Reference",
                    "description": "REST API documentation",
                    "content": "The API uses JSON for requests and responses. " * 20,
                    "category": "api",
                    "code_examples": [
                        {"language": "bash", "code": "curl https://api.example.com/"},
                    ],
                },
            ]

            # Save docs
            docs_dir = Path(tmpdir)
            manifest = {"total_documents": len(docs), "documents": []}

            for doc in docs:
                doc_file = docs_dir / f"{doc['id']}.json"
                doc_file.write_text(json.dumps(doc))
                manifest["documents"].append(
                    {
                        "id": doc["id"],
                        "url": doc["url"],
                        "title": doc["title"],
                        "category": doc["category"],
                    }
                )

            (docs_dir / "manifest.json").write_text(json.dumps(manifest))

            # 2. Chunk documents
            chunker = DocumentChunker(chunk_size=512)
            all_chunks = []

            for doc in docs:
                chunks = chunker.chunk_document(doc)
                all_chunks.extend(chunks)

            print(f"Created {len(all_chunks)} chunks from {len(docs)} documents")

            # 3. Generate embeddings
            embedder = Embedder()
            embeddings = [embedder.encode(chunk.content) for chunk in all_chunks]

            print(f"Generated {len(embeddings)} embeddings (dim={embedder.dimensions})")

            # 4. Index in Qdrant
            indexer = QdrantIndexer(collection_name="test_e2e_workflow")

            try:
                indexer.ensure_collection(embedding_dim=embedder.dimensions)
                indexed = indexer.index_chunks(all_chunks, embeddings)

                print(f"Indexed {indexed} chunks")

                # 5. Search
                query = "How to use Python?"
                query_embedding = embedder.encode(query)
                results = indexer.search(query_embedding, limit=3)

                assert len(results) > 0
                print(f"Search for '{query}' returned {len(results)} results:")
                for r in results:
                    print(f"  - {r['title']}: {r['content'][:50]}... (score: {r['score']:.3f})")

                # Verify Python doc ranks higher for Python query
                titles = [r["title"] for r in results]
                assert "Python Tutorial" in titles

                print("✅ End-to-end workflow completed successfully!")

            finally:
                try:
                    indexer.delete_collection()
                except Exception:
                    pass


# =============================================================================
# Run tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
