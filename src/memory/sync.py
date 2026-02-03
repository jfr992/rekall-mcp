"""Memory Sync Tool.

Sync manually edited YAML memories to the Qdrant vector database.

Unlike migrate (which rebuilds everything), sync only updates what changed:
- New memories → Add to Qdrant
- Edited memories → Re-embed and update
- Deleted memories → Remove from Qdrant

Usage:
------
    # Sync all changes
    python -m memory.sync

    # Preview changes without applying
    python -m memory.sync --dry-run

    # Sync specific file
    python -m memory.sync --file ~/.claude/memory/2026-02-02.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    """Generate hash of content for change detection."""
    return hashlib.md5(content.encode()).hexdigest()[:12]


def _get_yaml_memories(storage_path: Path) -> dict[str, dict]:
    """Load all memories from YAML files, keyed by ID."""
    memories = {}

    for yaml_file in storage_path.glob("*.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            date = data.get("date", yaml_file.stem)

            # Process each type section
            for type_key in data:
                if not type_key.endswith("s") or not isinstance(data[type_key], list):
                    continue

                memory_type = type_key[:-1]  # Remove trailing 's'

                for memory in data[type_key]:
                    memory_id = memory.get("id")
                    content = memory.get("content", "")

                    if memory_id and content:
                        memories[memory_id] = {
                            "id": memory_id,
                            "content": content,
                            "content_hash": _content_hash(content),
                            "type": memory_type,
                            "date": date,
                            "timestamp": memory.get("timestamp", ""),
                            "project": memory.get("project", "general"),
                        }
        except Exception as e:
            logger.warning(f"Failed to read {yaml_file.name}: {e}")

    return memories


def _get_qdrant_memories(store) -> dict[str, dict]:
    """Load all memories from Qdrant, keyed by ID."""
    memories = {}

    try:
        results = store.scroll(limit=10000)
        for item in results:
            memory_id = item.get("memory_id")
            content = item.get("content", "")
            if memory_id:
                memories[memory_id] = {
                    "id": memory_id,
                    "content": content,
                    "content_hash": _content_hash(content),
                }
    except Exception as e:
        logger.warning(f"Failed to read from Qdrant: {e}")

    return memories


def sync_memories(
    storage_path: str | None = None,
    file_path: str | None = None,
    dry_run: bool = False,
    _config=None,
) -> dict:
    """Sync YAML memories to Qdrant.

    Args:
        storage_path: Memory storage directory (default: ~/.claude/memory)
        file_path: Specific file to sync (optional)
        dry_run: Preview changes without applying
        _config: Config override for testing

    Returns:
        Sync statistics
    """
    from config import get_config
    from core import Embedder, VectorStore

    config = _config or get_config()

    # Resolve storage path
    if file_path:
        storage_path = Path(file_path).parent
    else:
        storage_path = Path(storage_path or config.tools.memory.storage_path).expanduser()

    logger.info("=" * 60)
    logger.info("MEMORY SYNC")
    logger.info("=" * 60)
    logger.info(f"Storage: {storage_path}")
    if file_path:
        logger.info(f"File: {file_path}")
    logger.info("")

    if not storage_path.exists():
        logger.error(f"Storage path not found: {storage_path}")
        return {"error": "Storage path not found", "synced": 0}

    # Load memories from both sources
    logger.info("Loading memories from YAML files...")
    yaml_memories = _get_yaml_memories(storage_path)
    logger.info(f"  Found {len(yaml_memories)} memories in YAML")

    # Initialize Qdrant
    store = VectorStore(
        collection=config.tools.memory.collection,
        embedding_dim=384,  # Will be overwritten if collection exists
        url=config.qdrant.url,
    )

    logger.info("Loading memories from Qdrant...")
    qdrant_memories = _get_qdrant_memories(store)
    logger.info(f"  Found {len(qdrant_memories)} memories in Qdrant")

    # Calculate diff
    yaml_ids = set(yaml_memories.keys())
    qdrant_ids = set(qdrant_memories.keys())

    to_add = yaml_ids - qdrant_ids
    to_delete = qdrant_ids - yaml_ids

    # Check for content changes in existing memories
    to_update = set()
    for memory_id in yaml_ids & qdrant_ids:
        yaml_hash = yaml_memories[memory_id]["content_hash"]
        qdrant_hash = qdrant_memories[memory_id]["content_hash"]
        if yaml_hash != qdrant_hash:
            to_update.add(memory_id)

    logger.info("")
    logger.info("Changes detected:")
    logger.info(f"  + Add: {len(to_add)}")
    logger.info(f"  ~ Update: {len(to_update)}")
    logger.info(f"  - Delete: {len(to_delete)}")

    if not to_add and not to_update and not to_delete:
        logger.info("")
        logger.info("Already in sync!")
        return {"added": 0, "updated": 0, "deleted": 0, "synced": True}

    if dry_run:
        logger.info("")
        logger.info("[DRY RUN] No changes made")

        if to_add:
            logger.info("\nWould add:")
            for memory_id in list(to_add)[:5]:
                content = yaml_memories[memory_id]["content"][:60]
                logger.info(f"  + {memory_id}: {content}...")
            if len(to_add) > 5:
                logger.info(f"  ... and {len(to_add) - 5} more")

        if to_update:
            logger.info("\nWould update:")
            for memory_id in list(to_update)[:5]:
                content = yaml_memories[memory_id]["content"][:60]
                logger.info(f"  ~ {memory_id}: {content}...")

        if to_delete:
            logger.info("\nWould delete:")
            for memory_id in list(to_delete)[:5]:
                logger.info(f"  - {memory_id}")
            if len(to_delete) > 5:
                logger.info(f"  ... and {len(to_delete) - 5} more")

        return {
            "to_add": len(to_add),
            "to_update": len(to_update),
            "to_delete": len(to_delete),
            "dry_run": True,
        }

    # Initialize embedder for add/update operations
    embedder = None
    if to_add or to_update:
        logger.info("")
        logger.info("Initializing embedder...")
        embedder = Embedder(
            provider=config.tools.memory.embedding_provider,
            model=config.tools.memory.embedding_model,
        )

    # Apply changes
    added = 0
    updated = 0
    deleted = 0
    errors = 0

    # Add new memories
    if to_add:
        logger.info("")
        logger.info("Adding new memories...")
        for memory_id in to_add:
            try:
                memory = yaml_memories[memory_id]
                vector = embedder.encode(memory["content"])

                store.save(
                    id=memory_id,
                    vector=vector,
                    payload={
                        "memory_id": memory_id,
                        "content": memory["content"],
                        "date": memory["date"],
                        "timestamp": memory["timestamp"],
                        "type": memory["type"],
                        "project": memory["project"],
                    },
                )
                added += 1
            except Exception as e:
                logger.warning(f"  Failed to add {memory_id}: {e}")
                errors += 1
        logger.info(f"  Added: {added}")

    # Update changed memories
    if to_update:
        logger.info("")
        logger.info("Updating changed memories...")
        for memory_id in to_update:
            try:
                memory = yaml_memories[memory_id]
                vector = embedder.encode(memory["content"])

                store.save(
                    id=memory_id,
                    vector=vector,
                    payload={
                        "memory_id": memory_id,
                        "content": memory["content"],
                        "date": memory["date"],
                        "timestamp": memory["timestamp"],
                        "type": memory["type"],
                        "project": memory["project"],
                    },
                )
                updated += 1
            except Exception as e:
                logger.warning(f"  Failed to update {memory_id}: {e}")
                errors += 1
        logger.info(f"  Updated: {updated}")

    # Delete removed memories
    if to_delete:
        logger.info("")
        logger.info("Deleting removed memories...")
        for memory_id in to_delete:
            try:
                store.delete(filters={"memory_id": memory_id})
                deleted += 1
            except Exception as e:
                logger.warning(f"  Failed to delete {memory_id}: {e}")
                errors += 1
        logger.info(f"  Deleted: {deleted}")

    logger.info("")
    logger.info("=" * 60)
    logger.info("SYNC COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Added: {added}")
    logger.info(f"Updated: {updated}")
    logger.info(f"Deleted: {deleted}")
    logger.info(f"Errors: {errors}")

    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Sync YAML memories to Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sync all changes
  python -m memory.sync

  # Preview changes without applying
  python -m memory.sync --dry-run

  # Sync specific file after editing
  python -m memory.sync --file ~/.claude/memory/2026-02-02.yaml
""",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying",
    )
    parser.add_argument(
        "--file",
        help="Sync specific YAML file",
    )
    parser.add_argument(
        "--storage-path",
        help="Memory storage path (default: ~/.claude/memory)",
    )

    args = parser.parse_args()

    result = sync_memories(
        storage_path=args.storage_path,
        file_path=args.file,
        dry_run=args.dry_run,
    )

    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
