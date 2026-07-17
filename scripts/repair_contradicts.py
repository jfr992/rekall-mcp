"""Repair unrefined contradicts edges left by the repr-v2 graph rebuild.

The 2026-07 repr-v2 migration rebuilt the graph with the recalibrated 0.46
floor and no ANTHROPIC_API_KEY, so the then-default deterministic entity-band
verdict ("contradicts") flagged 664 edges — 47% of the corpus — all with
band=None, llm_refined=False. This re-judges those edges under the U2.5
policy (related_to default, negation floor 0.60).

The graph stores NO memory content — content is joined from Qdrant via
store.get_many on the edge endpoints. Env: QDRANT_URL (server) or QDRANT_PATH
(embedded), exactly one, like other scripts; optional REKALL_COLLECTION and
MEMORY_STORAGE_PATH (graph directory).

Per unrefined contradicts edge (llm_refined falsy, no negation_matched):
- with ANTHROPIC_API_KEY: _llm_refine re-judges (one Haiku call per pair,
  ~$0.001 each — cap spend with --limit). Keep or downgrade is stamped
  llm_refined=True either way, so re-runs skip the edge (idempotent; a rare
  fail-open API error therefore also exempts that edge from future passes).
- without: _is_contradiction at the restored 0.60 floor, edge weight as
  similarity. Keep stamps negation_matched=True; else downgrade.

Downgrades go through KnowledgeGraph.set_edge_relation — add_edge's priority
guard refuses contradicts→related_to. Edges whose endpoints are missing from
Qdrant are skipped loudly, never mutated.

Dry-run by default; --apply writes and saves. Prints before/after counts.

Usage (never against production without a tarball first — see CLAUDE.md):
    QDRANT_URL=http://localhost:6333 uv run python scripts/repair_contradicts.py
    QDRANT_URL=... uv run python scripts/repair_contradicts.py --apply --limit 100
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memory.knowledge_graph import KnowledgeGraph  # noqa: E402
from memory.linker import _is_contradiction, _llm_refine  # noqa: E402

logger = logging.getLogger(__name__)


def _relation_counts(graph: KnowledgeGraph) -> dict[str, int]:
    return dict(graph.stats()["relations"])


def repair_contradicts(
    graph: KnowledgeGraph,
    store: Any,
    *,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Re-judge unrefined contradicts edges; downgrade the unsupported ones."""
    targets = [
        (source, target, dict(data))
        for source, target, data in graph._graph.edges(data=True)
        if data.get("relation") == "contradicts"
        and not data.get("llm_refined")
        and not data.get("negation_matched")
    ]
    if limit is not None:
        targets = targets[:limit]

    before = _relation_counts(graph)

    endpoint_ids = sorted({node for source, target, _ in targets for node in (source, target)})
    contents = {
        payload.get("memory_id"): str(payload.get("content") or "")
        for payload in store.get_many(endpoint_ids)
    }

    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    examined = kept_negation = kept_llm = downgraded = missing = 0

    for source, target, data in targets:
        source_content = contents.get(source)
        target_content = contents.get(target)
        if not source_content or not target_content:
            logger.warning(f"  {source} -> {target}: endpoint content missing in Qdrant, skipping")
            missing += 1
            continue
        examined += 1

        negation_hit = _is_contradiction(
            new_content=source_content,
            cand_content=target_content,
            similarity=float(data.get("weight", 0.0)),
        )

        if has_key:
            relation, _ = _llm_refine(
                new_content=source_content,
                cand_content=target_content,
                deterministic="contradicts" if negation_hit else "related_to",
            )
            keep = relation == "contradicts"
            markers: dict[str, Any] = {"llm_refined": True}
            if negation_hit:
                markers["negation_matched"] = True
        else:
            keep = negation_hit
            markers = {"negation_matched": True} if negation_hit else {}

        if keep:
            if has_key:
                kept_llm += 1
            else:
                kept_negation += 1
            if apply:
                graph.set_edge_relation(source, target, "contradicts", **markers)
        else:
            downgraded += 1
            if apply:
                graph.set_edge_relation(source, target, "related_to", **markers)

    if apply:
        graph.save()
        after = _relation_counts(graph)
    else:
        after = dict(before)
        if downgraded:
            after["contradicts"] = after.get("contradicts", 0) - downgraded
            after["related_to"] = after.get("related_to", 0) + downgraded

    return {
        "applied": apply,
        "examined": examined,
        "kept_negation": kept_negation,
        "kept_llm": kept_llm,
        "downgraded": downgraded,
        "skipped_missing_content": missing,
        "before": before,
        "after": after,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Re-judge unrefined contradicts edges")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="cap edges examined (LLM spend)")
    args = parser.parse_args(argv)

    qdrant_url = os.environ.get("QDRANT_URL")
    qdrant_path = os.environ.get("QDRANT_PATH")
    if bool(qdrant_url) == bool(qdrant_path):
        print("Exactly one of QDRANT_URL / QDRANT_PATH is required")
        return 1

    from core import VectorStore

    store = VectorStore(
        collection=os.environ.get("REKALL_COLLECTION", "agent_memory"),
        url=qdrant_url,
        path=qdrant_path,
    )
    memory_dir = Path(os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")).expanduser()
    graph = KnowledgeGraph(memory_dir / "_graph.json")

    result = repair_contradicts(graph, store, apply=args.apply, limit=args.limit)
    mode = "APPLIED" if result["applied"] else "DRY-RUN"
    print(
        f"{mode}: examined={result['examined']} downgraded={result['downgraded']} "
        f"kept_negation={result['kept_negation']} kept_llm={result['kept_llm']} "
        f"skipped_missing_content={result['skipped_missing_content']}"
    )
    print(f"before: {result['before']}")
    print(f"after:  {result['after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
