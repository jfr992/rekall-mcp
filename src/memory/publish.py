"""Memory publish orchestration: filter → cluster → title → render.

Format-agnostic. The title function and renderer are injected so the pipeline
is testable without an LLM and reusable across export formats.
"""

from __future__ import annotations

import networkx as nx

GROUPING_RELATIONS = frozenset(
    {"related_to", "led_to", "depends_on", "part_of", "supersedes"}
)
MAX_CLUSTER = 15  # ponytail: split at 15, tune if docs read badly


def _mid(m: dict) -> str:
    return m.get("memory_id") or m.get("id") or ""


def cluster_memories(memories: list[dict], graph) -> list[list[dict]]:
    """Group memories into concept clusters via graph connected components.

    Uses grouping relations only (excludes `contradicts` — a contradiction
    should keep two memories as separate concepts). Singletons form their own
    cluster. Components larger than MAX_CLUSTER split by memory type.
    """
    by_id = {_mid(m): m for m in memories if _mid(m)}
    g = nx.Graph()
    g.add_nodes_from(by_id)
    for s, t, data in graph._graph.edges(data=True):
        if data.get("relation") in GROUPING_RELATIONS and s in by_id and t in by_id:
            g.add_edge(s, t)

    clusters: list[list[dict]] = []
    for comp in nx.connected_components(g):
        members = [by_id[i] for i in comp]
        clusters.extend(_split_oversized(members))
    return clusters


def _split_oversized(members: list[dict]) -> list[list[dict]]:
    if len(members) <= MAX_CLUSTER:
        return [members]
    by_type: dict[str, list[dict]] = {}
    for m in members:
        by_type.setdefault(m.get("type", "note"), []).append(m)
    out: list[list[dict]] = []
    for group in by_type.values():
        for i in range(0, len(group), MAX_CLUSTER):
            out.append(group[i : i + MAX_CLUSTER])
    return out
