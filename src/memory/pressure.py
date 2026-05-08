"""Memory pressure and cleanup heuristics.

Keeps working memory from turning into sludge by identifying short-retention,
low-signal memories that should be pruned or deprioritized.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def identify_pressure(memories: list[dict[str, Any]], *, today: str | None = None) -> dict[str, Any]:
    current = today or datetime.now().strftime("%Y-%m-%d")
    low_value: list[dict[str, Any]] = []
    stale_working: list[dict[str, Any]] = []

    for memory in memories:
        tier = memory.get("tier", "working")
        retention = int(memory.get("retention_days", 0) or 0)
        salience = float(memory.get("salience", 0.0) or 0.0)
        date = memory.get("date", current)

        if salience < 0.35 and tier == "working":
            low_value.append(memory)

        if tier == "working" and retention:
            cutoff = (datetime.strptime(current, "%Y-%m-%d") - timedelta(days=retention)).strftime("%Y-%m-%d")
            if date <= cutoff:
                stale_working.append(memory)

    return {
        "low_value_count": len(low_value),
        "stale_working_count": len(stale_working),
        "candidates": _dedupe(low_value + stale_working),
    }


def render_pressure_report(pressure: dict[str, Any]) -> str:
    lines = ["# Memory Pressure Report", ""]
    lines.append(f"- low_value_count: {pressure.get('low_value_count', 0)}")
    lines.append(f"- stale_working_count: {pressure.get('stale_working_count', 0)}")
    lines.append("")

    candidates = pressure.get("candidates", [])
    if candidates:
        lines.append("## Cleanup Candidates")
        for item in candidates[:12]:
            lines.append(
                f"- [{item.get('tier', 'working')}/{item.get('type', 'note')}] {item.get('content', '')[:140]}"
            )
    else:
        lines.append("No cleanup pressure detected.")

    return "\n".join(lines) + "\n"


def _dedupe(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for memory in memories:
        key = memory.get("memory_id") or memory.get("content")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(memory)
    return out
