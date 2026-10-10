"""Relabel `contradicts` edges that no model ever checked to `related_to`.

Until the linker change "negation hit only nominates", a negation heuristic
stamped `contradicts` with llm_refined=False. Those edges are relabelled here;
llm_refined=True contradicts edges are kept. Weight, created and auto survive;
`migrated_from: "contradicts"` is added.

Dry run by default. `--apply` backs up `_graph.json` next to itself, then saves.
Stop the mcp container first: a running server holds the graph in memory and
would overwrite the file.

    uv run python scripts/migrate_unchecked_contradicts.py
    uv run python scripts/migrate_unchecked_contradicts.py --apply
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memory.knowledge_graph import KnowledgeGraph  # noqa: E402


def migrate(graph: KnowledgeGraph, *, apply: bool = False) -> dict[str, Any]:
    contradicts = [
        (source, target, data)
        for source, target, data in graph._graph.edges(data=True)
        if data.get("relation") == "contradicts"
    ]
    unchecked = [(s, t) for s, t, data in contradicts if not data.get("llm_refined")]
    if apply:
        for source, target in unchecked:
            graph.set_edge_relation(source, target, "related_to", migrated_from="contradicts")
        graph.save()
    return {
        "applied": apply,
        "total": len(contradicts),
        "relabeled": len(unchecked),
        "kept": len(contradicts) - len(unchecked),
    }


def _server_reachable() -> bool:
    base = os.environ.get("REKALL_API_URL", "http://localhost:8000").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=1):
            return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Relabel unchecked contradicts edges")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--force", action="store_true", help="skip the server-running check")
    args = parser.parse_args(argv)

    if args.apply and not args.force and _server_reachable():
        print(
            "Rekall server is reachable; stop the mcp container first (it would overwrite the graph)."
        )
        return 1

    memory_dir = Path(os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")).expanduser()
    graph_path = memory_dir / "_graph.json"
    graph = KnowledgeGraph(graph_path)

    if args.apply and graph_path.exists():
        backup = graph_path.with_name(f"_graph.json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        if any(
            d.get("relation") == "contradicts" and not d.get("llm_refined")
            for _, _, d in graph._graph.edges(data=True)
        ):
            shutil.copy2(graph_path, backup)
            print(f"backup: {backup}")

    result = migrate(graph, apply=args.apply)
    mode = "APPLIED" if result["applied"] else "DRY-RUN"
    print(
        f"{mode}: contradicts={result['total']} "
        f"unchecked_to_relabel={result['relabeled']} checked_kept={result['kept']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
