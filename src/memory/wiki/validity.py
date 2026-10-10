"""Page validity derived from the graph at read time; no background job."""

from __future__ import annotations

from memory.wiki.pages import Page


def compute_validity(page: Page, *, store, graph) -> dict:
    reasons: list[str] = []
    sources = list(dict.fromkeys(page.sources))
    if not sources:
        reasons.append("no sources")
    found = {p.get("memory_id"): p for p in (store.get_many(sources) if sources else [])}
    for mid in sources:
        point = found.get(mid)
        if point is None:
            reasons.append(f"source {mid} not found")
            continue
        if point.get("disputed"):
            reasons.append(f"source {mid} disputed")
        for edge in graph.get_edges(mid, direction="in"):
            if (
                getattr(edge, "relation", "") == "supersedes"
                and getattr(edge, "source", "") not in sources
            ):
                reasons.append(f"source {mid} superseded by {edge.source}")
    if not reasons:
        return {"validity": "ok", "reasons": []}
    # A stale procedure is worse than none: withdraw it from default results.
    return {"validity": "withdrawn" if page.type == "process" else "stale", "reasons": reasons}
