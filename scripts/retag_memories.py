"""Bulk retag memories from an audit map. Dry-run by default.

Reads a retag-map.json produced by a memory audit: a list of
{"from": "<project>", "to": {"<dest>": {"<reason>": ["id", ...]}}, "count": N}.

Ambiguous groups (`app`, `clawd`) are excluded unless --include-ambiguous is set.
No writes happen unless --apply is passed.

Usage:
    python scripts/retag_memories.py --map retag-map.json
    python scripts/retag_memories.py --map retag-map.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDE = frozenset({"app", "clawd"})


def build_plan(
    map_path: Path,
    exclude_from: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Flatten a retag map into from/to/id groups, skipping excluded sources."""
    excluded = set(DEFAULT_EXCLUDE if exclude_from is None else exclude_from)
    raw = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("retag map must be a JSON list")

    plan: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        source = entry.get("from")
        destinations = entry.get("to")
        if not isinstance(source, str) or not isinstance(destinations, dict):
            continue
        if source in excluded:
            continue
        for dest, reasons in destinations.items():
            if not isinstance(dest, str) or not isinstance(reasons, dict):
                continue
            ids: list[str] = []
            for bucket in reasons.values():
                if not isinstance(bucket, list):
                    continue
                ids.extend(str(item) for item in bucket)
            plan.append({"from": source, "to": dest, "ids": ids, "count": len(ids)})
    return plan


def format_summary(plan: list[dict[str, Any]]) -> str:
    lines = []
    for item in plan:
        lines.append(f"{item['from']} -> {item['to']}: {item['count']}")
    total = sum(item["count"] for item in plan)
    lines.append(f"total: {total}")
    return "\n".join(lines)


def _http_apply(memory_id: str, project: str) -> bool:
    import urllib.error
    import urllib.request

    base = os.environ.get("REKALL_API_URL", "http://127.0.0.1:8000").rstrip("/")
    url = f"{base}/api/memory/{memory_id}"
    request = urllib.request.Request(
        url,
        data=json.dumps({"project": project}).encode(),
        method="PATCH",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    token = os.environ.get("REKALL_API_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return 200 <= response.status < 300


def main_with_args(
    argv: list[str] | None = None,
    apply_one: Callable[[str, str], Any] | None = None,
) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Bulk retag Rekall memories from an audit map.")
    parser.add_argument("--map", required=True, help="Path to retag-map.json")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the retags. Without this flag, only print a dry-run plan.",
    )
    parser.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="Include the app and clawd groups that default to exclusion.",
    )
    args = parser.parse_args(argv)

    exclude = set() if args.include_ambiguous else set(DEFAULT_EXCLUDE)
    plan = build_plan(Path(args.map), exclude_from=exclude)
    print(format_summary(plan))

    if not args.apply:
        return {"dry_run": True, "applied": 0, "plan": plan}

    apply = apply_one or _http_apply
    applied = 0
    for item in plan:
        for memory_id in item["ids"]:
            apply(memory_id, item["to"])
            applied += 1
    return {"dry_run": False, "applied": applied, "plan": plan}


def main() -> int:
    main_with_args()
    return 0


if __name__ == "__main__":
    sys.exit(main())
