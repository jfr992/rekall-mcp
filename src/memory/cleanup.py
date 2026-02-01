"""Memory Cleanup Tool.

Prevents storage from growing indefinitely by:
1. Limiting total number of memories
2. Deleting memories older than X days
3. Removing duplicates

Usage:
    # See what would be cleaned (dry run)
    python -m memory.cleanup --dry-run

    # Keep only last 1000 memories
    python -m memory.cleanup --max-memories 1000

    # Delete memories older than 90 days
    python -m memory.cleanup --max-age-days 90

    # Both limits
    python -m memory.cleanup --max-memories 1000 --max-age-days 90
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def get_storage_stats(storage_path: Path) -> dict:
    """Get storage statistics."""
    if not storage_path.exists():
        return {"exists": False}

    files = list(storage_path.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files)

    # Parse dates from files
    dates = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                if "created_at" in data:
                    dates.append(data["created_at"])
        except Exception:
            pass

    oldest = min(dates) if dates else None
    newest = max(dates) if dates else None

    return {
        "exists": True,
        "file_count": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest": oldest,
        "newest": newest,
    }


def find_memories_to_delete(
    storage_path: Path,
    max_memories: int | None = None,
    max_age_days: int | None = None,
) -> list[Path]:
    """Find memories that should be deleted based on limits.

    Args:
        storage_path: Where memories are stored
        max_memories: Keep only this many (delete oldest first)
        max_age_days: Delete memories older than this

    Returns:
        List of file paths to delete
    """
    if not storage_path.exists():
        return []

    # Load all memories with their dates
    memories = []
    for f in storage_path.glob("*.json"):
        try:
            with open(f) as fp:
                data = json.load(fp)
                created_at = data.get("created_at", "1970-01-01T00:00:00Z")
                memories.append({"path": f, "created_at": created_at})
        except Exception:
            # If we can't read it, mark for deletion
            memories.append({"path": f, "created_at": "1970-01-01T00:00:00Z"})

    # Sort by date (newest first)
    memories.sort(key=lambda m: m["created_at"], reverse=True)

    to_delete = set()

    # Apply max_memories limit (keep newest)
    if max_memories is not None and len(memories) > max_memories:
        for mem in memories[max_memories:]:
            to_delete.add(mem["path"])

    # Apply max_age_days limit
    if max_age_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat() + "Z"

        for mem in memories:
            if mem["created_at"] < cutoff_str:
                to_delete.add(mem["path"])

    return list(to_delete)


def cleanup_memories(
    storage_path: str | None = None,
    max_memories: int | None = None,
    max_age_days: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Clean up old memories based on limits.

    Args:
        storage_path: Where memories are stored
        max_memories: Keep only this many (delete oldest first)
        max_age_days: Delete memories older than this
        dry_run: If True, only report what would be deleted

    Returns:
        Cleanup statistics
    """
    from config import get_config

    config = get_config()
    storage_path = Path(storage_path or config.tools.memory.storage_path).expanduser()

    logger.info("=" * 60)
    logger.info("MEMORY CLEANUP")
    logger.info("=" * 60)

    # Get current stats
    stats = get_storage_stats(storage_path)
    if not stats["exists"]:
        logger.info(f"Storage path not found: {storage_path}")
        return {"error": "Storage path not found"}

    logger.info(f"Storage path: {storage_path}")
    logger.info(f"Current memories: {stats['file_count']}")
    logger.info(f"Current size: {stats['total_size_mb']} MB")
    logger.info("")

    # Find what to delete
    to_delete = find_memories_to_delete(storage_path, max_memories, max_age_days)

    if not to_delete:
        logger.info("Nothing to clean up.")
        return {
            "before_count": stats["file_count"],
            "deleted_count": 0,
            "after_count": stats["file_count"],
        }

    logger.info(f"Memories to delete: {len(to_delete)}")

    if dry_run:
        logger.info("\n[DRY RUN] No files deleted.")
        logger.info("\nWould delete:")
        for f in to_delete[:10]:
            logger.info(f"  - {f.name}")
        if len(to_delete) > 10:
            logger.info(f"  ... and {len(to_delete) - 10} more")

        return {
            "before_count": stats["file_count"],
            "would_delete": len(to_delete),
            "dry_run": True,
        }

    # Actually delete
    deleted = 0
    errors = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete {f.name}: {e}")
            errors += 1

    # Get new stats
    new_stats = get_storage_stats(storage_path)

    logger.info("")
    logger.info("=" * 60)
    logger.info("CLEANUP COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Deleted: {deleted} memories")
    logger.info(f"Errors: {errors}")
    logger.info(f"Remaining: {new_stats['file_count']} memories")
    logger.info(f"New size: {new_stats['total_size_mb']} MB")

    # Also clean up Qdrant (remove vectors for deleted memories)
    if deleted > 0:
        logger.info("\nNote: Run 'python -m memory.migrate' to sync Qdrant index.")

    return {
        "before_count": stats["file_count"],
        "deleted_count": deleted,
        "errors": errors,
        "after_count": new_stats["file_count"],
        "size_mb": new_stats["total_size_mb"],
    }


def show_stats(storage_path: str | None = None) -> dict:
    """Show storage statistics."""
    from config import get_config

    config = get_config()
    storage_path = Path(storage_path or config.tools.memory.storage_path).expanduser()

    stats = get_storage_stats(storage_path)

    logger.info("=" * 60)
    logger.info("MEMORY STORAGE STATS")
    logger.info("=" * 60)

    if not stats["exists"]:
        logger.info(f"Storage path not found: {storage_path}")
        return stats

    logger.info(f"Path: {storage_path}")
    logger.info(f"Memories: {stats['file_count']}")
    logger.info(f"Size: {stats['total_size_mb']} MB")
    logger.info(f"Oldest: {stats['oldest'] or 'N/A'}")
    logger.info(f"Newest: {stats['newest'] or 'N/A'}")

    # Estimate growth
    if stats["file_count"] > 0:
        avg_size = stats["total_size_bytes"] / stats["file_count"]
        logger.info("")
        logger.info("Projections (at current average size):")
        logger.info(f"  1,000 memories: ~{round(1000 * avg_size / (1024 * 1024), 1)} MB")
        logger.info(f"  10,000 memories: ~{round(10000 * avg_size / (1024 * 1024), 1)} MB")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Manage memory storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show storage stats
  python -m memory.cleanup --stats

  # Preview cleanup (dry run)
  python -m memory.cleanup --max-memories 1000 --dry-run

  # Keep only last 1000 memories
  python -m memory.cleanup --max-memories 1000

  # Delete memories older than 90 days
  python -m memory.cleanup --max-age-days 90

  # Both limits
  python -m memory.cleanup --max-memories 1000 --max-age-days 90
""",
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show storage statistics only",
    )
    parser.add_argument(
        "--max-memories",
        type=int,
        help="Keep only this many memories (delete oldest first)",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        help="Delete memories older than this many days",
    )
    parser.add_argument(
        "--storage-path",
        help="Memory storage path (default: from config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )

    args = parser.parse_args()

    if args.stats:
        show_stats(args.storage_path)
        return

    if args.max_memories is None and args.max_age_days is None:
        # No limits specified, just show stats
        show_stats(args.storage_path)
        logger.info("")
        logger.info("To clean up, specify --max-memories or --max-age-days")
        logger.info("Use --dry-run to preview what would be deleted")
        return

    result = cleanup_memories(
        storage_path=args.storage_path,
        max_memories=args.max_memories,
        max_age_days=args.max_age_days,
        dry_run=args.dry_run,
    )

    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
