from __future__ import annotations

from collections import Counter
from typing import Any

_DANGER_TERMS = (
    "backup",
    "delete",
    "cleanup",
    "qdrant",
    "terraform",
    "terragrunt",
    "tofu",
    "secret",
    "production",
)
_OPEN_LOOP_TERMS = ("next", "follow up", "open", "blocked", "remaining")
_SECTION_LIMITS = {
    "standing_context": 8,
    "active_workstreams": 6,
    "operating_rules": 6,
    "danger_zones": 6,
    "open_loops": 6,
}
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

    standing_context = []
    active_workstreams = []
    operating_rules = []
    danger_zones = []
    open_loops = []

    for point, importance in enriched:
        content = (point.get("content") or "").lower()
        memory_type = point.get("type")
        row = _item(point, importance)

        if memory_type in {"requirement", "preference"}:
            operating_rules.append(row)
        if memory_type in {"decision", "learning", "fact"}:
            standing_context.append(row)
        if memory_type in {"note", "summary", "session"} or "workstream" in content:
            active_workstreams.append(row)
        if any(term in content for term in _DANGER_TERMS):
            danger_zones.append(row)
        if any(term in content for term in _OPEN_LOOP_TERMS):
            open_loops.append(row)

    return {
        "project": project,
        "entities": [entity for entity, _count in entity_counts.most_common(16)],
        "standing_context": standing_context[: _SECTION_LIMITS["standing_context"]],
        "active_workstreams": active_workstreams[: _SECTION_LIMITS["active_workstreams"]],
        "operating_rules": operating_rules[: _SECTION_LIMITS["operating_rules"]],
        "danger_zones": danger_zones[: _SECTION_LIMITS["danger_zones"]],
        "open_loops": open_loops[: _SECTION_LIMITS["open_loops"]],
    }


def render_project_capsule(capsule: dict[str, Any]) -> str:
    lines = [f"# Project Capsule: {capsule['project']}", ""]

    entities = capsule.get("entities") or []
    if entities:
        lines.append("Entities: " + ", ".join(entities[:16]))
        lines.append("")

    sections = [
        ("Standing Context", "standing_context"),
        ("Active Workstreams", "active_workstreams"),
        ("Operating Rules", "operating_rules"),
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
