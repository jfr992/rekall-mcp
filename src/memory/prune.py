"""Safe pruning from memory pressure signals."""

from __future__ import annotations

from typing import Any

from memory.pressure import identify_pressure


def plan_prune(memories: list[dict[str, Any]], *, aggressive: bool = False) -> dict[str, Any]:
    pressure = identify_pressure(memories)
    candidates = pressure.get("candidates", [])

    selected = []
    for memory in candidates:
        salience = float(memory.get("salience", 0.0) or 0.0)
        tier = memory.get("tier", "working")
        if tier != "working":
            continue
        if aggressive:
            if salience <= 0.45:
                selected.append(memory)
        else:
            if salience <= 0.25:
                selected.append(memory)

    return {
        "pressure": pressure,
        "selected": selected,
        "selected_count": len(selected),
        "aggressive": aggressive,
    }


def apply_prune_plan(manager, prune_plan: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    selected = prune_plan.get("selected", [])
    deleted: list[str] = []

    for memory in selected:
        memory_id = memory.get("memory_id")
        if not memory_id:
            continue
        if not dry_run:
            if manager.delete(memory_id):
                deleted.append(memory_id)
        else:
            deleted.append(memory_id)

    return {
        "dry_run": dry_run,
        "selected_count": prune_plan.get("selected_count", 0),
        "deleted_count": len(deleted),
        "memory_ids": deleted,
    }
