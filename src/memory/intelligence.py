"""Higher-level memory promotion and continuity intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory.lifecycle import LifecycleSignals, classify, compute_retention_days, promote_memory


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


def reinforce_and_reclassify(
    memory: dict[str, Any],
    *,
    graph,
    now: datetime,
) -> dict[str, Any]:
    """Return a NEW memory dict with reinforcement_count +1 and tier recomputed.

    Pure function: does not mutate `memory`, does not touch the store/graph
    (caller is responsible for persistence). Reads only `graph.count_contradicts`.
    """
    new_memory = dict(memory)

    new_count = int(new_memory.get("reinforcement_count") or 0) + 1
    new_memory["reinforcement_count"] = new_count

    date_str = new_memory.get("date") or now.strftime("%Y-%m-%d")
    try:
        mem_date = datetime.strptime(date_str, "%Y-%m-%d")
        age_days = max(0, (now - mem_date).days)
    except ValueError:
        age_days = 0

    memory_id = new_memory.get("memory_id", "")
    contradicts_count = graph.count_contradicts(memory_id) if memory_id else 0

    current_tier = new_memory.get("tier")
    explicit_tier = current_tier if current_tier == "identity" else None

    signals = LifecycleSignals(
        memory_type=new_memory.get("type", "note"),
        salience=float(new_memory.get("salience") or 0.0),
        age_days=age_days,
        reinforcement_count=new_count,
        contradicts_count=contradicts_count,
        explicit_tier=explicit_tier,
    )
    result = classify(signals)

    new_memory["tier"] = result.tier
    new_memory["durability"] = result.durability
    new_memory["lifecycle_reason"] = result.reason
    new_memory["retention_days"] = compute_retention_days(new_memory.get("type", "note"), result.tier)
    return new_memory


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
