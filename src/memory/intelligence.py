"""Higher-level memory promotion and continuity intelligence."""

from __future__ import annotations

from typing import Any

from memory.lifecycle import promote_memory


def apply_memory_promotion(graph, memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote tiers based on graph access patterns and salience."""
    promoted = 0
    updated: list[dict[str, Any]] = []

    for memory in memories:
        memory_id = memory.get("memory_id", "")
        if not memory_id:
            continue

        node = graph._graph.nodes.get(memory_id, {}) if memory_id in graph._graph else {}
        access_count = int(node.get("access_count", 0))
        salience = float(memory.get("salience", 0.0) or 0.0)
        current_tier = memory.get("tier", "working")
        new_tier = promote_memory(current_tier, memory.get("type", "note"), access_count, salience)

        if new_tier != current_tier:
            memory["tier"] = new_tier
            promoted += 1
        updated.append(memory)

    return {"promoted": promoted, "memories": updated}


def changed_since_last_session(memories: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Return the most meaningful recent changes for continuity."""
    ranked = sorted(
        memories,
        key=lambda m: (
            m.get("date", ""),
            m.get("importance", 0.0),
            m.get("tier") == "identity",
        ),
        reverse=True,
    )
    return ranked[:limit]
