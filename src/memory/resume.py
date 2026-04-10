"""Resume packet generation for agent session startup.

Produces a concise packet oriented around continuity, not just retrieval.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from memory.intelligence import apply_memory_promotion, changed_since_last_session
from memory.scope import MemoryScope


def build_resume_packet(
    manager,
    *,
    scope: MemoryScope,
    limit: int = 12,
) -> dict[str, Any]:
    """Build an agent-facing resume packet for session start."""
    project = scope.project or "general"
    filters = {"project": project}
    points = manager.store.scroll(filters=filters, limit=max(limit * 3, 24))

    now = datetime.now()
    recent_cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    recent = []
    important = []
    unresolved = []

    graph = manager.knowledge_graph
    graph_has_nodes = graph.stats()["nodes"] > 0

    for point in points:
        memory_id = point.get("memory_id", "")
        date = point.get("date", "")
        mem_type = point.get("type", "note")
        content = (point.get("content", "") or "").strip().replace("\n", " ")
        importance = graph.get_importance(memory_id) if graph_has_nodes and memory_id else 0.5

        item = {
            "memory_id": memory_id,
            "type": mem_type,
            "date": date,
            "content": content,
            "importance": round(float(importance), 4),
            "tier": point.get("tier", "working"),
        }

        if date >= recent_cutoff:
            recent.append(item)
        if importance >= 0.7 or mem_type in {"decision", "requirement", "preference"}:
            important.append(item)

        if graph_has_nodes and memory_id:
            for edge in graph.get_edges(memory_id, direction="out"):
                if edge.relation == "contradicts":
                    unresolved.append(
                        {
                            "memory_id": memory_id,
                            "conflicts_with": edge.target,
                            "content": content,
                        }
                    )

    promotion = apply_memory_promotion(graph, recent + important)
    promoted_memories = promotion["memories"]

    dedup_recent = changed_since_last_session(_dedupe_by_id(recent), limit=limit)
    dedup_important = _dedupe_by_id(sorted(promoted_memories, key=lambda x: (-x["importance"], x["date"])))[:limit]
    dedup_unresolved = _dedupe_conflicts(unresolved)[:6]

    return {
        "scope": scope.to_metadata(),
        "recent": dedup_recent,
        "important": dedup_important,
        "unresolved": dedup_unresolved,
        "promotion": {"promoted": promotion["promoted"]},
        "summary": render_resume_packet(
            scope=scope,
            recent=dedup_recent,
            important=dedup_important,
            unresolved=dedup_unresolved,
        ),
    }


def render_resume_packet(*, scope: MemoryScope, recent: list[dict[str, Any]], important: list[dict[str, Any]], unresolved: list[dict[str, Any]]) -> str:
    lines = [f"# Resume Packet: {scope.project}", ""]
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
            lines.append(f"- [{item['date']}] [{item['tier']}/{item['type']}] {item['content'][:160]}")
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
