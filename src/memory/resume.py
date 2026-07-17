"""Resume packet generation for agent session startup.

Produces a concise packet oriented around continuity, not just retrieval.
"""

from __future__ import annotations

from typing import Any

from memory.continuity import extract_next_steps, format_handoff_summary
from memory.intelligence import apply_memory_promotion, changed_since_last_session
from memory.pressure import identify_pressure, render_pressure_report
from memory.scope import MemoryScope

# Bounded scroll cap — prevents "recent" being a random 7% slice at scale.
# When the project exceeds this, `truncated=True` is set in the packet.
MAX_RESUME_SCROLL = 2000


def build_resume_packet(
    manager,
    *,
    scope: MemoryScope | None,
    limit: int = 12,
) -> dict[str, Any]:
    """Build an agent-facing resume packet for session start.

    Bounded scroll + Python-side sort by (date, importance) — fixes C2
    where the old 24-point slice was in Qdrant point-id order.
    """
    project = scope.project or "general" if scope else None
    filters = {"project": project} if project else None

    # Fetch up to MAX_RESUME_SCROLL points, bounded so "recent" is truthful at scale.
    points = manager.store.scroll(filters=filters, limit=MAX_RESUME_SCROLL)
    truncated = len(points) >= MAX_RESUME_SCROLL

    graph = manager.knowledge_graph
    graph_has_nodes = graph.stats()["nodes"] > 0

    # Annotate each point with its importance from the graph (or a default).
    enriched: list[dict[str, Any]] = []
    for point in points:
        memory_id = point.get("memory_id", "")
        date = point.get("date", "")
        mem_type = point.get("type", "note")
        content = (point.get("content", "") or "").strip().replace("\n", " ")
        importance = graph.get_importance(memory_id) if graph_has_nodes and memory_id else 0.5

        enriched.append(
            {
                "memory_id": memory_id,
                "type": mem_type,
                "date": date,
                "content": content,
                "importance": round(float(importance), 4),
                "tier": point.get("tier", "working"),
            }
        )

    # Sort by (date desc, importance desc) — this is the fix for C2.
    enriched.sort(key=lambda item: (item["date"] or "", item["importance"]), reverse=True)

    recent = enriched[:limit]
    important = sorted(enriched, key=lambda x: (-x["importance"], x["date"]))[:limit]

    unresolved: list[dict[str, Any]] = []
    if graph_has_nodes:
        for item in enriched:
            memory_id = item["memory_id"]
            if not memory_id:
                continue
            for edge in graph.get_edges(memory_id, direction="out"):
                if edge.relation == "contradicts":
                    unresolved.append(
                        {
                            "memory_id": memory_id,
                            "conflicts_with": edge.target,
                            "content": item["content"],
                        }
                    )
            if len(unresolved) >= 6:
                break

    promotion = apply_memory_promotion(graph, recent + important)
    promoted_memories = promotion["memories"]

    dedup_recent = changed_since_last_session(_dedupe_by_id(recent), limit=limit)
    dedup_important = _dedupe_by_id(
        sorted(promoted_memories, key=lambda x: (-x["importance"], x["date"]))
    )[:limit]
    dedup_unresolved = _dedupe_conflicts(unresolved)[:6]

    next_steps = extract_next_steps(dedup_recent + dedup_important)
    handoff = format_handoff_summary(
        recent=dedup_recent,
        important=dedup_important,
        next_steps=next_steps,
    )
    pressure = identify_pressure(points)

    return {
        "scope": scope.to_metadata() if scope else None,
        "recent": dedup_recent,
        "important": dedup_important,
        "unresolved": dedup_unresolved,
        "next_steps": next_steps,
        "handoff": handoff,
        "pressure": pressure,
        "pressure_report": render_pressure_report(pressure),
        "promotion": {"promoted": promotion["promoted"]},
        "truncated": truncated,
        "summary": render_resume_packet(
            scope=scope,
            recent=dedup_recent,
            important=dedup_important,
            unresolved=dedup_unresolved,
        ),
    }


def render_resume_packet(
    *,
    scope: MemoryScope | None,
    recent: list[dict[str, Any]],
    important: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> str:
    lines = [f"# Resume Packet: {scope.project if scope else 'all projects'}", ""]
    if scope:
        lines.append(f"- agent: {scope.agent}")
        if scope.branch:
            lines.append(f"- branch: {scope.branch}")
        if scope.repo_name:
            lines.append(f"- repo: {scope.repo_name}")
        lines.append(f"- trust_boundary: {scope.trust_boundary}")
    lines.append("")

    if important:
        lines.append("## Important Context")
        for item in important:
            lines.append(f"- [{item['tier']}/{item['type']}] {item['content'][:160]}")
        lines.append("")

    if recent:
        lines.append("## Recent Changes")
        for item in recent:
            lines.append(
                f"- [{item['date']}] [{item['tier']}/{item['type']}] {item['content'][:160]}"
            )
        lines.append("")

    if unresolved:
        lines.append("## Unresolved Conflicts")
        for item in unresolved:
            lines.append(f"- {item['memory_id']} conflicts with {item['conflicts_with']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        memory_id = item.get("memory_id")
        if not memory_id or memory_id in seen:
            continue
        seen.add(memory_id)
        out.append(item)
    return out


def _dedupe_conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = tuple(sorted([item.get("memory_id", ""), item.get("conflicts_with", "")]))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
