"""Memory Cleanup Tool.

Prevents storage from growing indefinitely by:
1. Deleting memories older than X days
2. Limiting total number of memories (keeps newest)

Storage format: Daily YAML files (~/.claude/memory/YYYY-MM-DD.yaml)

Usage:
    # See what would be cleaned (dry run)
    python -m memory.cleanup --dry-run

    # Delete memories older than 90 days
    python -m memory.cleanup --max-age-days 90

    # Keep only last 1000 memories
    python -m memory.cleanup --max-memories 1000
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def get_storage_stats(storage_path: Path) -> dict:
    """Get storage statistics from YAML files."""
    if not storage_path.exists():
        return {"exists": False}

    yaml_files = list(storage_path.glob("*.yaml"))
    total_size = sum(f.stat().st_size for f in yaml_files)

    # Count memories and find date range
    total_memories = 0
    dates = []

    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            date = data.get("date", yaml_file.stem)
            dates.append(date)

            # Count memories in each type section
            for key in data:
                if key.endswith("s") and isinstance(data[key], list):
                    total_memories += len(data[key])
        except Exception:
            pass

    oldest = min(dates) if dates else None
    newest = max(dates) if dates else None

    return {
        "exists": True,
        "file_count": len(yaml_files),
        "memory_count": total_memories,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest_date": oldest,
        "newest_date": newest,
    }


def cleanup_by_age(
    storage_path: Path,
    max_age_days: int,
    dry_run: bool = False,
) -> dict:
    """Delete YAML files older than max_age_days.

    Args:
        storage_path: Memory storage directory
        max_age_days: Delete files older than this
        dry_run: Preview only, don't delete

    Returns:
        Cleanup statistics
    """
    cutoff_date = (datetime.utcnow() - timedelta(days=max_age_days)).strftime("%Y-%m-%d")

    to_delete = []
    for yaml_file in storage_path.glob("*.yaml"):
        # File name is date: YYYY-MM-DD.yaml
        file_date = yaml_file.stem
        if file_date < cutoff_date:
            to_delete.append(yaml_file)

    if dry_run:
        return {
            "would_delete_files": len(to_delete),
            "files": [f.name for f in to_delete[:10]],
            "dry_run": True,
        }

    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete {f.name}: {e}")

    return {"deleted_files": deleted}


def cleanup_by_count(
    storage_path: Path,
    max_memories: int,
    dry_run: bool = False,
) -> dict:
    """Keep only the newest N memories across all files.

    This may modify or delete YAML files to stay under the limit.

    Args:
        storage_path: Memory storage directory
        max_memories: Maximum memories to keep
        dry_run: Preview only, don't modify

    Returns:
        Cleanup statistics
    """
    # Load all memories with their source info
    all_memories = []

    for yaml_file in storage_path.glob("*.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}

            date = data.get("date", yaml_file.stem)

            for type_key in data:
                if not type_key.endswith("s") or not isinstance(data[type_key], list):
                    continue

                for memory in data[type_key]:
                    all_memories.append(
                        {
                            "file": yaml_file,
                            "date": date,
                            "type_key": type_key,
                            "memory": memory,
                            "timestamp": memory.get("timestamp", date),
                        }
                    )
        except Exception:
            pass

    # Sort by timestamp (newest first)
    all_memories.sort(key=lambda m: m["timestamp"], reverse=True)

    # Find memories to delete (oldest beyond limit)
    to_keep = all_memories[:max_memories]
    to_delete = all_memories[max_memories:]

    if not to_delete:
        return {"deleted_memories": 0, "message": "Already under limit"}

    if dry_run:
        return {
            "current_count": len(all_memories),
            "would_delete": len(to_delete),
            "would_keep": len(to_keep),
            "dry_run": True,
        }

    # Group memories to keep by file
    keep_by_file: dict[Path, dict] = {}
    for mem in to_keep:
        f = mem["file"]
        if f not in keep_by_file:
            keep_by_file[f] = {"date": mem["date"]}
        type_key = mem["type_key"]
        if type_key not in keep_by_file[f]:
            keep_by_file[f][type_key] = []
        keep_by_file[f][type_key].append(mem["memory"])

    # Rewrite files with only kept memories, delete empty files
    files_modified = 0
    files_deleted = 0

    for yaml_file in storage_path.glob("*.yaml"):
        if yaml_file in keep_by_file:
            # Rewrite with kept memories
            try:
                with open(yaml_file, "w") as f:
                    yaml.dump(keep_by_file[yaml_file], f, default_flow_style=False)
                files_modified += 1
            except Exception as e:
                logger.warning(f"Failed to update {yaml_file.name}: {e}")
        else:
            # Delete file entirely
            try:
                yaml_file.unlink()
                files_deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {yaml_file.name}: {e}")

    return {
        "deleted_memories": len(to_delete),
        "files_modified": files_modified,
        "files_deleted": files_deleted,
    }


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
    logger.info(f"YAML files: {stats['file_count']}")
    logger.info(f"Total memories: {stats['memory_count']}")
    logger.info(f"Size: {stats['total_size_mb']} MB")
    logger.info(f"Date range: {stats['oldest_date']} to {stats['newest_date']}")
    logger.info("")

    result = {"before": stats}

    # Apply age limit first (simpler - deletes whole files)
    if max_age_days is not None:
        logger.info(f"Cleaning memories older than {max_age_days} days...")
        age_result = cleanup_by_age(storage_path, max_age_days, dry_run)
        result["by_age"] = age_result
        logger.info(f"  {age_result}")

    # Then apply count limit
    if max_memories is not None:
        logger.info(f"Limiting to {max_memories} newest memories...")
        count_result = cleanup_by_count(storage_path, max_memories, dry_run)
        result["by_count"] = count_result
        logger.info(f"  {count_result}")

    # Get new stats
    if not dry_run:
        new_stats = get_storage_stats(storage_path)
        result["after"] = new_stats
        logger.info("")
        logger.info("After cleanup:")
        logger.info(f"  Memories: {new_stats['memory_count']}")
        logger.info(f"  Size: {new_stats['total_size_mb']} MB")

        # Remind to sync Qdrant
        if stats["memory_count"] != new_stats["memory_count"]:
            logger.info("")
            logger.info("Run 'python -m memory.sync' to update Qdrant index.")

    logger.info("")
    logger.info("=" * 60)
    return result


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
    logger.info(f"YAML files: {stats['file_count']}")
    logger.info(f"Total memories: {stats['memory_count']}")
    logger.info(f"Size: {stats['total_size_mb']} MB")
    logger.info(f"Oldest: {stats['oldest_date'] or 'N/A'}")
    logger.info(f"Newest: {stats['newest_date'] or 'N/A'}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Manage memory storage (YAML format)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show storage stats
  python -m memory.cleanup --stats

  # Preview cleanup (dry run)
  python -m memory.cleanup --max-age-days 90 --dry-run

  # Delete memories older than 90 days
  python -m memory.cleanup --max-age-days 90

  # Keep only last 1000 memories
  python -m memory.cleanup --max-memories 1000
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
