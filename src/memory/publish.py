"""Memory publish orchestration: filter → cluster → title → render.

Format-agnostic. The title function and renderer are injected so the pipeline
is testable without an LLM and reusable across export formats.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable

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


_STOP = {"the", "a", "an", "and", "for", "to", "of", "in", "on", "is", "with"}


def cluster_key(cluster: list[dict]) -> str:
    ids = sorted(_mid(m) for m in cluster)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]


def slug_title(cluster: list[dict]) -> tuple[str, str]:
    """Deterministic (title, summary) from the longest-content member."""
    hub = max(cluster, key=lambda m: len(m.get("content", "")))
    words = re.findall(r"[A-Za-z0-9]+", hub.get("content", ""))
    keep = [w for w in words if w.lower() not in _STOP][:6] or ["memory"]
    return " ".join(keep), hub.get("content", "")[:120]


def _plausible(t) -> bool:
    return bool(
        isinstance(t, tuple) and len(t) == 2 and t[0] and 2 <= len(t[0]) <= 120
    )


def make_title_fn(
    cache: dict, judge: Callable[[list[dict]], tuple[str, str]] | None = None
) -> Callable[[list[dict]], tuple[str, str]]:
    """Return a title_fn that caches by cluster membership and falls back to slug."""

    def title_fn(cluster: list[dict]) -> tuple[str, str]:
        key = cluster_key(cluster)
        if key in cache:
            return tuple(cache[key])
        result = None
        if judge is not None:
            try:
                candidate = judge(cluster)
                if _plausible(candidate):
                    result = candidate
            except Exception:
                result = None
        if result is None:
            result = slug_title(cluster)
        cache[key] = list(result)
        return result

    return title_fn
