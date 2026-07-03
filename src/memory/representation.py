from __future__ import annotations

import re
from typing import Any

_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[a-z0-9]+(?:-[a-z0-9]+)+|[a-zA-Z_][a-zA-Z0-9_]*|[A-Z]+-\d+)\b"
)

_STOP = {
    "Project",
    "Type",
    "Tier",
    "Claim",
    "Context",
    "Use",
    "The",
    "This",
    "That",
}


def extract_entities(text: str, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    for match in _ENTITY_RE.finditer(text):
        entity = match.group(0).strip(".,:;()[]{}")
        if len(entity) < 2 or entity in _STOP or entity.lower() in _STOP:
            continue
        key = entity.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(entity)
        if len(entities) >= limit:
            break
    return entities


def build_embedding_text(content: str, metadata: dict[str, Any]) -> str:
    project = metadata.get("project") or "general"
    memory_type = metadata.get("type") or "note"
    tier = metadata.get("tier") or "working"
    repo = metadata.get("repo_name")
    entities = metadata.get("entities") or extract_entities(content)

    parts = [
        f"Project {project}.",
        f"Type {memory_type}.",
        f"Tier {tier}.",
    ]
    if repo:
        parts.append(f"Repository {repo}.")
    if entities:
        parts.append("Entities: " + ", ".join(entities) + ".")
    parts.append("Claim: " + " ".join(content.split()))
    return " ".join(parts)
