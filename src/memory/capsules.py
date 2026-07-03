from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

_DANGER_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\bnever\b",
        r"\bgotcha\b",
        r"\bcorrupt(?:ed|ion)?\b",
        r"data loss",
        r"\boutage\b",
        r"\bincident\b",
        r"race condition",
        r"\bbroken\b",
        r"\bfailed\b",
        r"migration failed",
        r"failed migration",
        r"security vulnerability",
        r"\bcve-",
        r"\bbreach\b",
        r"\bdo not\b",
        r"\bdon't\b",
    )
)
_OPEN_LOOP_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\bpending\b",
        r"\btodo\b",
        r"next step",
        r"\bunmerged\b",
        r"\bblocked\b",
        r"follow-up",
        r"follow up",
        r"waiting on",
        r"not yet",
        r"restart needed",
    )
)
_DANGER_TYPES = {"learning", "fact", "requirement", "decision"}
_STANDING_TYPES = {"decision", "requirement", "preference"}
_OPEN_LOOP_MAX_AGE_DAYS = 90
_SECTION_LIMITS = {"standing_context": 8, "danger_zones": 6, "open_loops": 6}
_MAX_CONTENT_CHARS = 240
_MAX_RENDER_CHARS = 1800


def _item(point: dict[str, Any], importance: float) -> dict[str, Any]:
    content = " ".join((point.get("content") or "").split())
    return {
        "memory_id": point.get("memory_id", ""),
        "date": point.get("date", ""),
        "type": point.get("type", "note"),
        "tier": point.get("tier", "working"),
        "importance": round(float(importance), 4),
        "content": content[:_MAX_CONTENT_CHARS],
    }


def build_project_capsule(manager, project: str, limit: int = 300) -> dict[str, Any]:
    scan_limit = max(limit, 2000)
    points = manager.store.scroll(filters={"project": project}, limit=scan_limit)
    enriched: list[tuple[dict[str, Any], float]] = []
    entity_counts: Counter[str] = Counter()

    for point in points:
        memory_id = point.get("memory_id", "")
        importance = manager.knowledge_graph.get_importance(memory_id) if memory_id else 0.5
        enriched.append((point, importance))
        for entity in point.get("entities") or []:
            entity_counts[str(entity)] += 1

    enriched.sort(key=lambda pair: (pair[0].get("date", ""), pair[1]), reverse=True)

    standing_context: list[dict[str, Any]] = []
    danger_zones: list[dict[str, Any]] = []
    open_loops: list[dict[str, Any]] = []

    cutoff = (datetime.now() - timedelta(days=_OPEN_LOOP_MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    for point, importance in enriched:
        content = (point.get("content") or "").lower()
        memory_type = point.get("type")
        row = _item(point, importance)

        if memory_type in _DANGER_TYPES and any(p.search(content) for p in _DANGER_PATTERNS):
            danger_zones.append(row)
        elif (point.get("date", "") >= cutoff) and any(
            p.search(content) for p in _OPEN_LOOP_PATTERNS
        ):
            open_loops.append(row)
        elif memory_type in _STANDING_TYPES:
            standing_context.append(row)

    return {
        "project": project,
        "entities": [entity for entity, _count in entity_counts.most_common(16)],
        "standing_context": standing_context[: _SECTION_LIMITS["standing_context"]],
        "danger_zones": danger_zones[: _SECTION_LIMITS["danger_zones"]],
        "open_loops": open_loops[: _SECTION_LIMITS["open_loops"]],
    }


def render_project_capsule(capsule: dict[str, Any]) -> str:
    lines = [f"# Project Capsule: {capsule['project']}", ""]

    sections = [
        ("Standing Context", "standing_context"),
        ("Danger Zones", "danger_zones"),
        ("Open Loops", "open_loops"),
    ]
    for title, key in sections:
        items = capsule.get(key) or []
        if not items:
            continue
        lines.append(f"## {title}")
        for item in items:
            lines.append(f"- [{item.get('date', 'unknown')}] {item.get('content', '')}")
        lines.append("")

    text = "\n".join(lines).strip() + "\n"
    if len(text) <= _MAX_RENDER_CHARS:
        return text
    return text[: _MAX_RENDER_CHARS - 4].rstrip() + "...\n"
