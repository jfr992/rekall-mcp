"""Read-time conflict detection + freshness annotation (spec 2026-07-06, Stage B).

Same-type only in v1 — cross-type conflicts are PR-F2 (needs eval scenarios first).
Comparison basis: STORED vectors. Repr v2 stores encode(content) — theta 0.81 is
the bracket midpoint between the max measured non-conflict pair cosine (0.7717)
and the min measured conflict pair cosine (0.8455) on the linker/freshness test
fixture corpus (all-MiniLM, 2026-07-09 calibration). Never deletes, never
reorders scores — output is annotation only.
"""

from __future__ import annotations

import math


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def detect_conflict_groups(
    memories: list[dict],
    graph,
    vectors: dict[str, list[float]] | None,
    theta: float = 0.81,
) -> list[set[str]]:
    """Union same-type pairs linked by (a) supersedes/contradicts edges or
    (b) stored-vector cosine >= theta AND >= 1 shared entity (the linker's
    contradiction evidence standard — cosine alone is not conflict evidence).
    When either member carries no entity metadata the cosine leg falls back
    to cosine-only. Returns groups of size >= 2."""
    ids = [m.get("memory_id") for m in memories if m.get("memory_id")]
    type_of = {m["memory_id"]: m.get("type", "note") for m in memories if m.get("memory_id")}
    entities_of = {
        m["memory_id"]: {str(e).lower() for e in (m.get("entities") or [])}
        for m in memories
        if m.get("memory_id")
    }
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    # (a) graph edges within the retrieved set, same-type only (cross-type = F2)
    if graph is not None:
        idset = set(ids)
        for src, tgt, data in graph._graph.edges(data=True):
            if (
                src in idset
                and tgt in idset
                and data.get("relation") in ("supersedes", "contradicts")
                and type_of.get(src) == type_of.get(tgt)
            ):
                union(src, tgt)

    # (b) stored-vector similarity within the retrieved set
    if vectors:
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if type_of.get(a) != type_of.get(b):
                    continue
                ea, eb = entities_of.get(a), entities_of.get(b)
                if ea and eb and not (ea & eb):
                    continue
                va, vb = vectors.get(a), vectors.get(b)
                if va and vb and _cosine(va, vb) >= theta:
                    union(a, b)

    groups: dict[str, set[str]] = {}
    for i in ids:
        groups.setdefault(find(i), set()).add(i)
    return [g for g in groups.values() if len(g) >= 2]


def mark_outdated(memories: list[dict], groups: list[set[str]]) -> list[dict]:
    """Set ephemeral `_outdated: True` on all but the newest member of each group.
    Newest = max(timestamp or date). Underscore field: rendering-only, never stored."""
    key = lambda m: m.get("timestamp") or m.get("date") or ""  # noqa: E731
    by_id = {m.get("memory_id"): m for m in memories if m.get("memory_id")}
    for group in groups:
        members = sorted((by_id[i] for i in group if i in by_id), key=key, reverse=True)
        for older in members[1:]:
            older["_outdated"] = True
    return memories
