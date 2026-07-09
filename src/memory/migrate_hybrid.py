"""Migration script for hybrid search schema.

Reads all memories from YAML, builds BM25 vocabulary,
recreates Qdrant collection with sparse vectors, and re-indexes.

Usage:
    python -m memory.migrate_hybrid [--dry-run] [--memory-dir PATH] [--qdrant-url URL]
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from memory.lifecycle import summarize_lifecycle
from memory.representation import build_embedding_text, extract_entities

logger = logging.getLogger(__name__)

_INTERNAL_KEYS = {"_yaml_file", "_type_key", "_index", "_schema_changed"}
_SCHEMA_BACKFILL_FIELDS = (
    "reinforcement_count",
    "tier",
    "durability",
    "lifecycle_reason",
    "retention_days",
    "entities",
    "embedding_text",
)


def _first_nonblank(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _public_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in memory.items() if key not in _INTERNAL_KEYS}


def _age_days(date_str: str) -> int:
    try:
        memory_date = datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return 0
    return max(0, (datetime.now() - memory_date).days)


def _normalize_schema(memory: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(memory)
    changed = False
    content = str(normalized.get("content") or "")

    if normalized.get("reinforcement_count") is None:
        normalized["reinforcement_count"] = 0
        changed = True

    entities = normalized.get("entities")
    if not isinstance(entities, list):
        normalized["entities"] = extract_entities(content)
        changed = True

    if not _first_nonblank(normalized.get("embedding_text")):
        normalized["embedding_text"] = build_embedding_text(content, normalized)
        changed = True

    lifecycle = summarize_lifecycle(
        {
            **normalized,
            "age_days": _age_days(str(normalized.get("date") or "")),
        }
    )
    for key, value in lifecycle.items():
        if normalized.get(key) != value:
            normalized[key] = value
            changed = True

    normalized["_schema_changed"] = changed
    return normalized


def _write_schema_backfill(memories: list[dict[str, Any]]) -> int:
    by_file: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        if not memory.get("_schema_changed") or not memory.get("_yaml_file"):
            continue
        by_file[Path(memory["_yaml_file"])].append(memory)

    updated = 0
    for yaml_file, file_memories in by_file.items():
        data = yaml.safe_load(yaml_file.read_text()) or {}
        file_changed = False

        for memory in file_memories:
            type_key = memory.get("_type_key")
            index = memory.get("_index")
            if not isinstance(type_key, str) or not isinstance(index, int):
                continue
            items = data.get(type_key)
            if not isinstance(items, list) or index >= len(items):
                continue
            item = items[index]
            if not isinstance(item, dict):
                continue
            item_id = _first_nonblank(item.get("memory_id"), item.get("id"))
            if item_id != memory.get("memory_id"):
                continue

            item_changed = False
            for field in _SCHEMA_BACKFILL_FIELDS:
                if item.get(field) != memory.get(field):
                    item[field] = memory.get(field)
                    item_changed = True
            if item_changed:
                updated += 1
                file_changed = True

        if not file_changed:
            continue

        fd, tmp_path = tempfile.mkstemp(dir=yaml_file.parent, suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            os.replace(tmp_path, yaml_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    return updated


def load_all_yaml_memories(memory_dir: Path | str) -> list[dict[str, Any]]:
    """Load all memories from YAML files in the given directory.

    Reads every *.yaml file (skipping names starting with _) and
    flattens all memory entries into a single list with normalized fields.

    Args:
        memory_dir: Directory containing dated YAML memory files

    Returns:
        List of memory dicts with normalized identity fields and preserved metadata.
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

            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                yaml_id = _first_nonblank(item.get("id"), item.get("memory_id"))
                memory_id = _first_nonblank(item.get("memory_id"), item.get("id"))
                content = item.get("content", "")
                if not memory_id or not str(content or "").strip():
                    continue

                memory = dict(item)
                memory.update(
                    {
                        "id": yaml_id,
                        "memory_id": memory_id,
                        "content": content,
                        "date": date,
                        "type": mem_type,
                        "project": item.get("project", "general"),
                        "_yaml_file": str(yaml_file),
                        "_type_key": key,
                        "_index": index,
                    }
                )
                memories.append(memory)

    return memories


def build_corpus(memories: list[dict[str, Any]]) -> list[str]:
    """Extract non-empty representation strings for BM25 training.

    Args:
        memories: List of memory dicts (output of load_all_yaml_memories)

    Returns:
        List of embedding_text strings, falling back to raw content
    """
    corpus: list[str] = []
    for memory in memories:
        text = _first_nonblank(memory.get("embedding_text"), memory.get("content"))
        if text:
            corpus.append(text)
    return corpus


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
    memories = [_normalize_schema(memory) for memory in load_all_yaml_memories(memory_dir)]

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
            "schema_updates": sum(1 for memory in memories if memory.get("_schema_changed")),
        }

    schema_updates = _write_schema_backfill(memories)

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

        payload = _public_memory(mem)
        embedding_text = payload["embedding_text"]
        payload["repr_version"] = 2

        # Repr v2: dense = raw content, sparse BM25 = embedding_text
        vector = embedder.encode(payload["content"])
        store.save(
            id=payload["memory_id"],
            vector=vector,
            payload=payload,
            content=embedding_text,
        )

        if (i + 1) % 100 == 0:
            logger.info(f"Indexed {i + 1}/{len(memories)}")

    logger.info(f"Migration complete: {len(memories)} memories indexed")

    return {
        "status": "complete",
        "memories": len(memories),
        "vocab_size": len(encoder.vocab),
        "schema_updates": schema_updates,
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
