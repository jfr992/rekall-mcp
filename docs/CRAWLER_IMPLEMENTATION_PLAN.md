# Crawler + Indexer Implementation Plan

## Overview

Port Scrapy-based documentation crawler and indexer from spectro-mcp to memento-mcp, making it **generic and config-driven** so users can crawl and index their own tool documentation.

**Use Case:** Stay up-to-date with tools in your workflow by crawling their docs and enabling semantic search alongside personal memory.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  User Workflow                                          │
├─────────────────────────────────────────────────────────┤
│  1. Edit crawl_config.yaml (set target URLs)            │
│  2. make crawl          → Downloads docs to ./crawled_docs │
│  3. make index          → Chunks + embeds → Qdrant      │
│  4. Use AI with search_tool_docs(query)                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Data Flow                                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Web Docs                                               │
│      ↓                                                  │
│  Scrapy Spider (configurable)                           │
│      ↓                                                  │
│  HTML Parsing + Content Extraction                      │
│      ↓                                                  │
│  JSON files (./crawled_docs/)                           │
│      ↓                                                  │
│  Chunker (1000 chars, 200 overlap)                      │
│      ↓                                                  │
│  Embedder (reuse existing: ST/Ollama/Gemini)            │
│      ↓                                                  │
│  Qdrant (collection: tool_docs)                         │
│      ↓                                                  │
│  search_tool_docs() MCP tool                            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Design Decisions

### 1. Separate from Personal Memory
- **Personal Memory**: Collection `agent_memory` (decisions, learnings, etc.)
- **Tool Docs**: Collection `tool_docs` (crawled documentation)
- **Why?** Different data types, different query patterns, different lifecycles

### 2. Config-Driven (No Hardcoded URLs)
```yaml
# crawl_config.yaml
target:
  name: "nextjs-docs"
  start_urls:
    - https://nextjs.org/docs
  allowed_domains:
    - nextjs.org
  deny_patterns:
    - /blog/
    - /showcase/
```

### 3. Reuse Existing Infrastructure
- ✅ Embedding provider (already supports 3 types)
- ✅ Qdrant connection (already configured)
- ✅ Core utilities (telemetry, config, etc.)

### 4. Optional Feature
- Basic memory tools work without crawler
- Crawler/indexer only installed if needed: `pip install memento-mcp[crawler]`

---

## Implementation Phases

### **Phase 1: Crawler (Estimated: 2-3 hours)**

#### File: `src/crawler/spider.py`
**Port from:** `spectro-mcp/src/spectro_mcp/crawler/spider.py`

**Key Changes:**
- ❌ Remove: Hardcoded `allowed_domains = ["docs.spectrocloud.com"]`
- ✅ Add: Load from `crawl_config.yaml`
- ❌ Remove: Spectro-specific categorization
- ✅ Add: Generic URL-based categorization

**Generic Spider Class:**
```python
class GenericDocsSpider(CrawlSpider):
    """Config-driven documentation spider."""

    name = "generic_docs"

    def __init__(self, config_path="crawl_config.yaml", *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load config
        with open(config_path) as f:
            config = yaml.safe_load(f)

        self.start_urls = config["target"]["start_urls"]
        self.allowed_domains = config["target"]["allowed_domains"]

        # Build rules from config
        self.rules = (
            Rule(
                LinkExtractor(
                    allow_domains=self.allowed_domains,
                    deny=config["target"].get("deny_patterns", []),
                    unique=True,
                ),
                callback="parse_page",
                follow=True,
            ),
        )

        # Apply custom settings from config
        crawler_config = config.get("crawler", {})
        self.custom_settings.update({
            "CONCURRENT_REQUESTS": crawler_config.get("concurrent_requests", 1),
            "DOWNLOAD_DELAY": crawler_config.get("download_delay", 2.0),
            "RANDOMIZE_DOWNLOAD_DELAY": crawler_config.get("randomize_delay", True),
            # ... etc
        })
```

**Content Extraction:**
- Keep: HTML parsing logic (titles, descriptions, content)
- Keep: Code block extraction
- Keep: Breadcrumb extraction
- Remove: Spectro-specific category logic
- Add: Generic category detection from URL structure

**Output Format:**
```json
{
  "id": "abc123def456",
  "url": "https://docs.example.com/getting-started",
  "title": "Getting Started",
  "description": "Learn how to set up...",
  "content": "Full text content here...",
  "code_examples": [
    {"language": "bash", "code": "npm install..."}
  ],
  "breadcrumbs": ["Home", "Docs", "Getting Started"],
  "category": "getting-started",
  "crawled_at": "2026-02-02T10:30:00Z"
}
```

#### File: `src/crawler/pipeline.py`
**Port from:** `spectro-mcp/src/spectro_mcp/crawler/pipeline.py`

**Purpose:** Process and save crawled documents

**Key Components:**
```python
class DocumentPipeline:
    """Pipeline to process and save crawled documents."""

    def __init__(self):
        self.output_dir = Path("./crawled_docs")
        self.output_dir.mkdir(exist_ok=True)
        self.seen_ids = set()

    def process_item(self, item, spider):
        # Deduplicate
        if item["id"] in self.seen_ids:
            raise DropItem(f"Duplicate: {item['url']}")

        # Validate
        if len(item["content"]) < 100:
            raise DropItem(f"Too short: {item['url']}")

        # Save to JSON
        output_file = self.output_dir / f"{item['id']}.json"
        with open(output_file, "w") as f:
            json.dump(item, f, indent=2)

        self.seen_ids.add(item["id"])
        return item
```

#### File: `src/crawler/cli.py`
**Port from:** `spectro-mcp/src/spectro_mcp/crawler/cli.py`

**Purpose:** Command-line interface for crawling

```python
def main():
    """Run the documentation crawler."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="crawl_config.yaml")
    parser.add_argument("--output", default="./crawled_docs")
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()

    # Run Scrapy
    process = CrawlerProcess()
    process.crawl(
        GenericDocsSpider,
        config_path=args.config,
        output_dir=args.output,
    )
    process.start()
```

#### File: `src/crawler/incremental.py`
**Port from:** `spectro-mcp/src/spectro_mcp/crawler/incremental.py`

**Purpose:** Track what's already crawled, only fetch new/updated pages

**Optional:** Can skip for MVP, add later if needed

---

### **Phase 2: Indexer (Estimated: 2-3 hours)**

#### File: `src/indexer/chunker.py`
**Port from:** `spectro-mcp/src/spectro_mcp/indexer/chunker.py`

**Purpose:** Split large documents into searchable chunks

**Algorithm:**
```
Input: Document with 5000 characters
Output: Chunks of 1000 chars with 200 char overlap

Chunk 1: chars 0-1000
Chunk 2: chars 800-1800  (200 overlap with chunk 1)
Chunk 3: chars 1600-2600 (200 overlap with chunk 2)
...
```

**Key Function:**
```python
def chunk_document(
    doc: dict,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[dict]:
    """Split document into overlapping chunks."""
    text = doc["content"]
    chunks = []

    start = 0
    chunk_id = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end]

        chunks.append({
            "chunk_id": f"{doc['id']}_chunk_{chunk_id}",
            "doc_id": doc["id"],
            "url": doc["url"],
            "title": doc["title"],
            "chunk_text": chunk_text,
            "chunk_index": chunk_id,
            "category": doc["category"],
            "code_examples": doc.get("code_examples", []),
        })

        chunk_id += 1
        start = end - chunk_overlap  # Overlap

    return chunks
```

**Why Overlap?**
- Prevents important information from being split mid-sentence
- Ensures semantic context isn't lost at boundaries

#### File: `src/indexer/embeddings.py`
**Port from:** `spectro-mcp/src/spectro_mcp/indexer/embeddings.py`

**Purpose:** Generate embeddings for chunks

**Strategy:** Reuse existing `core/embeddings.py`
```python
from core.embeddings import get_embedder

def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Add embeddings to chunks."""
    embedder = get_embedder()  # Uses config (ST/Ollama/Gemini)

    for chunk in chunks:
        # Combine title + content for better semantic representation
        text = f"{chunk['title']}\n\n{chunk['chunk_text']}"
        chunk["embedding"] = embedder.encode(text)

    return chunks
```

**No changes needed** - just wrap existing embedder

#### File: `src/indexer/qdrant.py`
**Port from:** `spectro-mcp/src/spectro_mcp/indexer/qdrant.py`

**Purpose:** Index chunks into Qdrant

**Key Changes:**
- ❌ Remove: Spectro-specific collection name
- ✅ Add: Configurable collection name from `crawl_config.yaml`

**Implementation:**
```python
from core.vector_store import get_vector_store

def index_chunks(chunks: list[dict], collection_name: str = "tool_docs"):
    """Index chunks into Qdrant."""
    vector_store = get_vector_store()

    # Create collection if needed
    vector_store.create_collection(
        collection_name,
        vector_size=384,  # For all-MiniLM-L6-v2
    )

    # Batch insert
    points = []
    for chunk in chunks:
        points.append({
            "id": chunk["chunk_id"],
            "vector": chunk["embedding"],
            "payload": {
                "doc_id": chunk["doc_id"],
                "url": chunk["url"],
                "title": chunk["title"],
                "text": chunk["chunk_text"],
                "category": chunk["category"],
                "chunk_index": chunk["chunk_index"],
            }
        })

    vector_store.upsert(collection_name, points)
```

**Payload Fields for Search:**
- `text`: Chunk content (returned in search results)
- `url`: Source URL (for citations)
- `title`: Document title
- `category`: For filtering (e.g., only search "API" docs)

#### File: `src/indexer/cli.py`
**Port from:** `spectro-mcp/src/spectro_mcp/indexer/cli.py`

**Purpose:** Command-line interface for indexing

```python
def main():
    """Index crawled documents into Qdrant."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="./crawled_docs")
    parser.add_argument("--collection", default="tool_docs")
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    # Load all JSON files
    docs = []
    for json_file in Path(args.input).glob("*.json"):
        with open(json_file) as f:
            docs.append(json.load(f))

    print(f"Loaded {len(docs)} documents")

    # Chunk documents
    all_chunks = []
    for doc in docs:
        chunks = chunk_document(doc)
        all_chunks.extend(chunks)

    print(f"Created {len(all_chunks)} chunks")

    # Generate embeddings
    all_chunks = embed_chunks(all_chunks)

    # Index into Qdrant
    if args.recreate:
        vector_store = get_vector_store()
        vector_store.delete_collection(args.collection)

    index_chunks(all_chunks, args.collection)

    print(f"Indexed {len(all_chunks)} chunks into '{args.collection}'")
```

---

### **Phase 3: Integration (Estimated: 1 hour)**

#### File: `Makefile` (additions)
**Add crawler commands:**

```makefile
# =============================================================================
# DOCUMENTATION CRAWLER
# =============================================================================

# Crawl documentation (requires crawl_config.yaml)
crawl:
	@echo "Starting documentation crawler..."
	@if [ ! -f "crawl_config.yaml" ]; then \
		echo "Error: crawl_config.yaml not found. Copy from crawl_config.yaml.example"; \
		exit 1; \
	fi
	python -m crawler.cli --config crawl_config.yaml
	@echo "Crawl complete! Documents saved to ./crawled_docs"

# Index crawled docs into Qdrant
index:
	@echo "Indexing crawled documents into Qdrant..."
	@if [ ! -d "crawled_docs" ]; then \
		echo "Error: crawled_docs directory not found. Run 'make crawl' first."; \
		exit 1; \
	fi
	python -m indexer.cli --input crawled_docs --collection tool_docs
	@echo "Indexing complete!"

# Rebuild index from scratch
reindex:
	@echo "Recreating tool_docs collection..."
	python -m indexer.cli --input crawled_docs --collection tool_docs --recreate
	@echo "Reindexing complete!"

# Clean crawled docs
clean-crawl:
	rm -rf crawled_docs/
	rm -rf .scrapy_cache/

# Full workflow: crawl + index
crawl-and-index: crawl index
	@echo "Documentation crawling and indexing complete!"
```

#### File: `pyproject.toml` (additions)
**Add crawler dependencies:**

```toml
[project.optional-dependencies]
# ... existing dev, test

crawler = [
    "scrapy>=2.11.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
]

# All features
all = [
    "memento-mcp[dev,test,crawler]",
]
```

**Add CLI entry points:**
```toml
[project.scripts]
memento-crawl = "crawler.cli:main"
memento-index = "indexer.cli:main"
```

#### File: `src/tools/builtin/docs.py` (NEW)
**Create documentation search tool:**

```python
"""Documentation search tools for crawled content."""

from core.embeddings import get_embedder
from core.vector_store import get_vector_store


def search_tool_docs(
    query: str,
    limit: int = 5,
    collection: str = "tool_docs",
    category: str | None = None,
) -> list[dict]:
    """Search indexed tool documentation.

    Args:
        query: Search query
        limit: Max results to return
        collection: Qdrant collection name
        category: Optional category filter (e.g., "api", "tutorials")

    Returns:
        List of matching documentation chunks with URLs
    """
    embedder = get_embedder()
    vector_store = get_vector_store()

    # Generate query embedding
    query_vector = embedder.encode(query)

    # Build filter
    filters = {}
    if category:
        filters["category"] = category

    # Search Qdrant
    results = vector_store.search(
        collection_name=collection,
        query_vector=query_vector,
        limit=limit,
        filters=filters,
    )

    # Format results
    formatted = []
    for result in results:
        formatted.append({
            "title": result.payload["title"],
            "url": result.payload["url"],
            "content": result.payload["text"],
            "score": result.score,
            "category": result.payload["category"],
        })

    return formatted
```

**Register as MCP tool:**
```python
# In src/tools/builtin/memory.py or separate docs.py

@mcp.tool()
async def search_tool_docs(query: str, category: str = None, limit: int = 5) -> str:
    """Search indexed tool documentation for relevant information.

    Use this when you need information about tools, libraries, or frameworks
    that have been crawled and indexed. Returns relevant documentation snippets
    with source URLs.

    Args:
        query: What you're looking for (e.g., "API authentication", "deployment guide")
        category: Optional filter (e.g., "api", "tutorials", "getting-started")
        limit: Max results (default: 5)

    Returns:
        Formatted search results with documentation snippets
    """
    from tools.builtin.docs import search_tool_docs as _search

    try:
        results = _search(query, limit, category=category)

        if not results:
            return f"No documentation found for: {query}"

        output = f"# Documentation Search: {query}\n\n"
        output += f"Found {len(results)} relevant results:\n\n"

        for i, result in enumerate(results, 1):
            output += f"## {i}. {result['title']}\n"
            output += f"**Category:** {result['category']}\n"
            output += f"**URL:** {result['url']}\n"
            output += f"**Relevance:** {result['score']:.2f}\n\n"
            output += f"{result['content'][:500]}...\n\n"
            output += "---\n\n"

        return output

    except Exception as e:
        return f"Error searching documentation: {str(e)}"
```

---

## Configuration Files

### `crawl_config.yaml.example`
✅ Already created

### `.gitignore` additions
```
# Crawler output
crawled_docs/
.scrapy_cache/
crawl_config.yaml
```

---

## Testing Strategy

### Manual Testing Workflow
```bash
# 1. Setup
cp crawl_config.yaml.example crawl_config.yaml
# Edit crawl_config.yaml with target docs

# 2. Install crawler dependencies
pip install -e ".[crawler]"

# 3. Crawl
make crawl
# Verify: ls crawled_docs/ should show JSON files

# 4. Index
make qdrant  # Start Qdrant if not running
make index
# Verify: Check Qdrant dashboard - should see tool_docs collection

# 5. Search
# Use Claude with: "Search the Next.js docs for deployment info"
# Tool: search_tool_docs(query="deployment")
```

### Unit Tests (Phase 4)
- `tests/test_crawler.py` - Test HTML parsing
- `tests/test_chunker.py` - Test chunking logic
- `tests/test_indexer.py` - Test Qdrant integration

---

## Dependencies Matrix

| Component | Required Packages | Already Have? |
|-----------|------------------|---------------|
| Crawler | scrapy, beautifulsoup4, lxml | ❌ Need to add |
| Indexer | sentence-transformers, qdrant-client | ✅ Already installed |
| Embeddings | (ST/Ollama/Gemini) | ✅ Already configured |
| CLI | argparse | ✅ Built-in |

**Installation:**
```bash
# Basic (no crawler)
pip install memento-mcp

# With crawler
pip install memento-mcp[crawler]

# Everything
pip install memento-mcp[all]
```

---

## Example Use Cases

### Use Case 1: Next.js Documentation
```yaml
# crawl_config.yaml
target:
  name: "nextjs"
  start_urls:
    - https://nextjs.org/docs
  allowed_domains:
    - nextjs.org
  deny_patterns:
    - /blog/
    - /showcase/
```

**Workflow:**
1. `make crawl` → Downloads ~200 pages
2. `make index` → Creates ~1500 chunks in Qdrant
3. Ask Claude: "How do I implement middleware in Next.js 14?"
4. Tool calls: `search_tool_docs("middleware Next.js 14")`
5. Returns: Relevant docs with code examples

### Use Case 2: Internal Company Wiki
```yaml
# crawl_config.yaml
target:
  name: "company-wiki"
  start_urls:
    - https://wiki.mycompany.com/engineering
  allowed_domains:
    - wiki.mycompany.com
  deny_patterns:
    - /admin/
    - /edit/
```

**Benefit:** Search your company's internal docs alongside personal memory

---

## Migration from Spectro-MCP

### Files to Port (with changes)

| Spectro File | Memento File | Changes |
|--------------|--------------|---------|
| `spectro_mcp/crawler/spider.py` | `crawler/spider.py` | Config-driven, generic categories |
| `spectro_mcp/crawler/pipeline.py` | `crawler/pipeline.py` | Generic output paths |
| `spectro_mcp/crawler/cli.py` | `crawler/cli.py` | Config parameter |
| `spectro_mcp/indexer/chunker.py` | `indexer/chunker.py` | Minimal changes |
| `spectro_mcp/indexer/qdrant.py` | `indexer/qdrant.py` | Reuse vector_store |
| `spectro_mcp/indexer/embeddings.py` | `indexer/embeddings.py` | Reuse embedder |
| `spectro_mcp/indexer/cli.py` | `indexer/cli.py` | Generic parameters |

### Files NOT to Port
- ❌ `spectro_mcp/api/` - Search API server (not needed)
- ❌ `spectro_mcp/search/` - Search tool integration (replace with docs.py)
- ❌ `spectro_mcp/tools/docs.py` - Spectro-specific docs (replace)

---

## Success Criteria

✅ **Phase 1 Complete When:**
- Can run `make crawl` with custom config
- JSON files appear in `./crawled_docs/`
- Content extraction works (title, text, code blocks)

✅ **Phase 2 Complete When:**
- Can run `make index` on crawled docs
- Qdrant collection `tool_docs` is created
- Can query collection directly and get results

✅ **Phase 3 Complete When:**
- `search_tool_docs()` MCP tool works
- Claude can search indexed docs
- Results include URLs for citation

---

## Timeline Estimate

| Phase | Tasks | Time | Status |
|-------|-------|------|--------|
| Phase 1 | Crawler | 2-3 hours | Not started |
| Phase 2 | Indexer | 2-3 hours | Not started |
| Phase 3 | Integration | 1 hour | Not started |
| **Total** | | **5-7 hours** | |

---

## Next Steps

1. **Review this plan** - Confirm approach is correct
2. **Start Phase 1** - Port crawler with config system
3. **Test incrementally** - Crawl a small site first
4. **Move to Phase 2** - Once crawling works
5. **Final integration** - Add MCP tool

---

## Questions to Resolve

1. **Collection naming:** Single `tool_docs` collection or one per tool?
   - **Recommendation:** Single collection with `source` metadata field

2. **Update frequency:** How often to re-crawl?
   - **Recommendation:** Manual (`make crawl`) + document incremental.py for auto-updates

3. **Rate limiting:** How aggressive to crawl?
   - **Recommendation:** Conservative (2s delay) by default, configurable

4. **Storage:** Keep crawled JSON files or just Qdrant?
   - **Recommendation:** Keep JSON files (allows re-indexing with different settings)

---

## Future Enhancements (v2)

- 🔄 Incremental crawling (only fetch changed pages)
- 📅 Scheduled re-crawling (cron integration)
- 🎯 Smart categorization (ML-based vs URL patterns)
- 🔍 Search result ranking improvements
- 📊 Crawler analytics dashboard
- 🧪 A/B testing different chunking strategies

---

**Created:** 2026-02-02
**Status:** Ready for implementation
**Next Action:** Review and approve plan, then start Phase 1
