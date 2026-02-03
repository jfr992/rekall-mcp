"""Memory Migration Tool.

When you switch embedding providers, your memories need to be re-indexed.
This tool reads your saved memories and re-embeds them with the new provider.

Why is this needed?
-------------------
Each embedding provider creates vectors in its own "language":
- sentence-transformers speaks "384-dimensional"
- Ollama speaks "768-dimensional"
- Gemini speaks "768-dimensional" (but different meaning!)

Even if two providers use the same number of dimensions, their vectors
mean completely different things - like French and Spanish both using
the Latin alphabet but being different languages.

Usage:
------
    # After changing your embedding provider in config:
    python -m memory.migrate

    # Or specify the new provider explicitly:
    python -m memory.migrate --provider gemini --api-key YOUR_KEY

What it does:
-------------
1. Reads all your memory files from ~/.claude/memory/
2. Creates new vectors using your new embedding provider
3. Rebuilds the Qdrant search index
4. Your memories are preserved - only the search index changes
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def migrate_memories(
    storage_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    dry_run: bool = False,
    _config=None,  # For testing
) -> dict:
    """Re-index all memories with a new embedding provider.

    Args:
        storage_path: Where memories are stored (default: ~/.claude/memory)
        provider: New embedding provider (sentence-transformers, ollama, gemini)
        model: Model name for the provider
        api_key: API key (for Gemini)
        base_url: Base URL (for Ollama)
        dry_run: If True, only count memories without migrating
        _config: Config override for testing

    Returns:
        Migration statistics
    """
    from config import get_config
    from core import Embedder, VectorStore

    config = _config or get_config()

    # Use provided values or fall back to config
    storage_path = storage_path or config.tools.memory.storage_path
    storage_path = Path(storage_path).expanduser()

    provider = provider or config.tools.memory.embedding_provider
    model = model or config.tools.memory.embedding_model
    api_key = api_key or config.tools.memory.embedding_api_key
    base_url = base_url or config.tools.memory.embedding_base_url

    logger.info("=" * 60)
    logger.info("MEMORY MIGRATION")
    logger.info("=" * 60)
    logger.info(f"Storage path: {storage_path}")
    logger.info(f"New provider: {provider}")
    logger.info(f"Model: {model}")
    logger.info("")

    # Find all memory files (YAML format)
    if not storage_path.exists():
        logger.error(f"Storage path not found: {storage_path}")
        return {"error": "Storage path not found", "migrated": 0}

    yaml_files = list(storage_path.glob("*.yaml"))
    logger.info(f"Found {len(yaml_files)} daily memory files")

    # Count total memories across all files
    total_memories = 0
    if yaml_files:
        for yaml_file in yaml_files:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
            for key in data:
                if key.endswith("s") and isinstance(data[key], list):
                    total_memories += len(data[key])
        logger.info(f"Total memories: {total_memories}")

    if dry_run:
        logger.info("\n[DRY RUN] No changes made")
        return {"found": total_memories, "migrated": 0, "dry_run": True}

    if not yaml_files:
        logger.info("No memories to migrate")
        return {"found": 0, "migrated": 0}

    # Initialize new embedder
    logger.info(f"\nInitializing {provider} embedder...")
    embedder = Embedder(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    # Test the embedder
    try:
        test_vector = embedder.encode("test")
        logger.info(f"Embedder ready: {len(test_vector)} dimensions")
    except Exception as e:
        logger.error(f"Embedder failed: {e}")
        return {"error": str(e), "migrated": 0}

    # Initialize vector store with new dimensions
    logger.info("\nConnecting to Qdrant...")
    store = VectorStore(
        collection=config.tools.memory.collection,
        embedding_dim=embedder.dimensions,
        url=config.qdrant.url,
    )

    # Delete old collection and recreate
    logger.info("Recreating collection with new dimensions...")
    store.recreate_collection()

    # Migrate each memory from YAML files
    logger.info("\nMigrating memories...")
    migrated = 0
    errors = 0

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            date = data.get("date", yaml_file.stem)

            # Process each type section (requirements, decisions, preferences, etc.)
            for type_key in data:
                if not type_key.endswith("s") or not isinstance(data[type_key], list):
                    continue

                memory_type = type_key[:-1]  # Remove trailing 's'

                for memory in data[type_key]:
                    try:
                        # Re-embed the content
                        content = memory.get("content", "")
                        if not content:
                            continue

                        vector = embedder.encode(content)

                        # Store in Qdrant
                        store.save(
                            id=memory.get("id", f"{date}_{memory_type}_{migrated}"),
                            vector=vector,
                            payload={
                                "memory_id": memory.get("id"),
                                "content": content,
                                "date": date,
                                "timestamp": memory.get("timestamp", ""),
                                "type": memory_type,
                                "project": memory.get("project", "general"),
                            },
                        )

                        migrated += 1
                        if migrated % 10 == 0 or migrated == total_memories:
                            logger.info(f"  Progress: {migrated}/{total_memories}")

                    except Exception as e:
                        logger.warning(f"  Failed to migrate memory from {yaml_file.name}: {e}")
                        errors += 1

        except Exception as e:
            logger.warning(f"  Failed to process {yaml_file.name}: {e}")
            errors += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("MIGRATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Migrated: {migrated}")
    logger.info(f"Errors: {errors}")
    logger.info(f"Provider: {provider}")
    logger.info(f"Dimensions: {embedder.dimensions}")

    return {
        "found": total_memories,
        "migrated": migrated,
        "errors": errors,
        "provider": provider,
        "dimensions": embedder.dimensions,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Migrate memories to a new embedding provider",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate using config settings
  python -m memory.migrate

  # Migrate to Gemini
  python -m memory.migrate --provider gemini --api-key YOUR_KEY

  # Migrate to Ollama
  python -m memory.migrate --provider ollama

  # Preview without making changes
  python -m memory.migrate --dry-run
""",
    )

    parser.add_argument(
        "--provider",
        choices=["sentence-transformers", "ollama", "gemini"],
        help="Embedding provider to migrate to",
    )
    parser.add_argument("--model", help="Model name for the provider")
    parser.add_argument("--api-key", help="API key (for Gemini)")
    parser.add_argument("--base-url", help="Base URL (for Ollama)")
    parser.add_argument("--storage-path", help="Memory storage path (default: ~/.claude/memory)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count memories without migrating",
    )

    args = parser.parse_args()

    result = migrate_memories(
        storage_path=args.storage_path,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        dry_run=args.dry_run,
    )

    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
