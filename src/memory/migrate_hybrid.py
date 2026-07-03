"""Migration script for hybrid search schema.

Reads all memories from YAML, builds BM25 vocabulary,
recreates Qdrant collection with sparse vectors, and re-indexes.

Usage:
    python -m memory.migrate_hybrid [--dry-run] [--memory-dir PATH] [--qdrant-url URL]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from memory.representation import build_embedding_text, extract_entities

logger = logging.getLogger(__name__)


def load_all_yaml_memories(memory_dir: Path | str) -> list[dict[str, Any]]:
    """Load all memories from YAML files in the given directory.

    Reads every *.yaml file (skipping names starting with _) and
    flattens all memory entries into a single list with normalized fields.

    Args:
        memory_dir: Directory containing dated YAML memory files

    Returns:
        List of memory dicts with keys: memory_id, content, date, type, project
    """
    memory_dir = Path(memory_dir)
    memories: list[dict[str, Any]] = []

    for yaml_file in sorted(memory_dir.rglob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue

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

            # "decisions" -> "decision", "learnings" -> "learning"
            mem_type = key.rstrip("s")

            for item in items:
                if not isinstance(item, dict):
                    continue

                memories.append(
                    {
                        "memory_id": item.get("id", ""),
                        "content": item.get("content", ""),
                        "date": date,
                        "type": mem_type,
                        "project": item.get("project", "general"),
                        "timestamp": item.get("timestamp", ""),
                        "tier": item.get("tier"),
                        "repo_name": item.get("repo_name"),
                        "embedding_text": item.get("embedding_text"),
                        "entities": item.get("entities"),
                    }
                )

    return memories


def build_corpus(memories: list[dict[str, Any]]) -> list[str]:
    """Extract non-empty content strings for BM25 training.

    Args:
        memories: List of memory dicts (output of load_all_yaml_memories)

    Returns:
        List of content strings
    """
    return [m["content"] for m in memories if m.get("content")]


def migrate_to_hybrid(
    memory_dir: Path | str = "~/.claude/memory",
    qdrant_url: str = "http://localhost:6333",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Migrate Qdrant collection to hybrid search schema.

    Steps:
    1. Load all memories from YAML
    2. Fit BM25 encoder on corpus
    3. (unless dry_run) Save BM25 vocab, recreate collection, re-index

    Args:
        memory_dir: Path to memory YAML files
        qdrant_url: Qdrant server URL
        dry_run: Preview without making changes

    Returns:
        Migration stats dict with keys: status, memories, vocab_size
    """
    memory_dir = Path(memory_dir).expanduser()

    logger.info("Loading memories from YAML...")
    memories = load_all_yaml_memories(memory_dir)

    if not memories:
        return {"status": "no_memories", "count": 0}

    logger.info(f"Loaded {len(memories)} memories")

    corpus = build_corpus(memories)
    from core import BM25Encoder

    encoder = BM25Encoder()
    encoder.fit(corpus)
    logger.info(f"Vocabulary size: {len(encoder.vocab)}")

    if dry_run:
        return {
            "status": "dry_run",
            "memories": len(memories),
            "vocab_size": len(encoder.vocab),
        }

    # Save BM25 vocabulary
    bm25_path = memory_dir / "_bm25_vocab.json"
    encoder.save(str(bm25_path))
    logger.info(f"Saved BM25 vocab to {bm25_path}")

    # Recreate collection with sparse vector support
    from core import Embedder, VectorStore

    store = VectorStore(
        collection="agent_memory",
        url=qdrant_url,
        sparse_encoder=encoder,
    )
    store.recreate_collection()
    logger.info("Recreated Qdrant collection with sparse vectors")

    # Re-index all memories
    embedder = Embedder()
    for i, mem in enumerate(memories):
        if not mem.get("content"):
            continue

        entities = mem.get("entities") or extract_entities(mem["content"])
        embedding_text = mem.get("embedding_text") or build_embedding_text(
            mem["content"],
            {**mem, "entities": entities},
        )
        mem["entities"] = entities
        mem["embedding_text"] = embedding_text

        vector = embedder.encode(embedding_text)
        store.save(
            id=mem["memory_id"],
            vector=vector,
            payload=mem,
            content=embedding_text,
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
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--memory-dir", default="~/.claude/memory", help="YAML memory directory")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant URL")
    args = parser.parse_args()

    result = migrate_to_hybrid(
        memory_dir=args.memory_dir,
        qdrant_url=args.qdrant_url,
        dry_run=args.dry_run,
    )
    print(f"Result: {result}")
