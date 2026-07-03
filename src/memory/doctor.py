from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _yaml_ids(memory_dir: Path, project: str | None) -> set[str]:
    ids: set[str] = set()
    roots = [memory_dir / project, memory_dir] if project else [memory_dir]
    for root in roots:
        if not root.exists():
            continue
        for yaml_file in root.rglob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            data = yaml.safe_load(yaml_file.read_text()) or {}
            for value in data.values():
                if isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        if project and item.get("project") != project:
                            continue
                        if item.get("id"):
                            ids.add(str(item["id"]))
    return ids


def run_memory_doctor(manager, project: str | None = None, limit: int = 10000) -> dict[str, Any]:
    filters = {"project": project} if project else None
    qdrant_points = manager.store.scroll(filters=filters, limit=limit)
    qdrant_ids = {str(point["memory_id"]) for point in qdrant_points if point.get("memory_id")}
    yaml_ids = _yaml_ids(Path(manager.memory_dir), project)

    missing_from_qdrant = sorted(yaml_ids - qdrant_ids)
    missing_from_yaml = sorted(qdrant_ids - yaml_ids)

    provenance = {
        "missing_agent": sum(1 for point in qdrant_points if not point.get("agent")),
        "missing_source_tool": sum(1 for point in qdrant_points if not point.get("source_tool")),
        "missing_cwd": sum(1 for point in qdrant_points if not point.get("cwd")),
    }
    vector_health = manager.vector_health()
    graph_stats = manager.knowledge_graph.stats()

    findings = []
    if missing_from_qdrant:
        findings.append("yaml_not_indexed")
    if missing_from_yaml:
        findings.append("qdrant_without_yaml")
    if vector_health.get("zero_vectors", 0):
        findings.append("zero_vectors")
    if any(provenance.values()):
        findings.append("missing_provenance")

    return {
        "status": "healthy" if not findings else "degraded",
        "project": project,
        "yaml_count": len(yaml_ids),
        "qdrant_count": len(qdrant_ids),
        "missing_from_qdrant": missing_from_qdrant,
        "missing_from_yaml": missing_from_yaml,
        "vector_health": vector_health,
        "graph": graph_stats,
        "provenance": provenance,
        "findings": findings,
    }
