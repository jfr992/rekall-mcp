from __future__ import annotations

import re
from typing import Any

_HARD_IDENTIFIER_RE = re.compile(r"(?<!\w)#\d+\b|\b[A-Z][A-Z0-9]*-\d+\b|\b[0-9a-fA-F]{7,40}\b")
_ENTITY_RE = re.compile(
    _HARD_IDENTIFIER_RE.pattern
    + r"|\b(?:[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z0-9]+(?:-[a-z0-9]+)+|[A-Z]{2,}|(?=[a-z0-9]*\d)[a-z][a-z0-9]+|[A-Z][A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b"
)
RESOLVED_PATTERN = re.compile(
    r"\b(?:merged|shipped|deployed|fixed|released|closed)\b", re.IGNORECASE
)

_STOP = {
    "claim",
    "context",
    "decided",
    "fixed",
    "learned",
    "project",
    "that",
    "the",
    "this",
    "tier",
    "type",
    "use",
}


def extract_entities(text: str, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    for match in _ENTITY_RE.finditer(text):
        entity = match.group(0).strip(".,:;()[]{}")
        if len(entity) < 2 or entity.lower() in _STOP:
            continue
        key = entity.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(entity)
        if len(entities) >= limit:
            break
    return entities


def hard_identifiers(content: str, entities: list[str] | None = None) -> set[str]:
    # Re-extract for older payloads that predate PR/SHA entity support.
    return {
        entity.lower()
        for entity in [*(entities or []), *extract_entities(content)]
        if _HARD_IDENTIFIER_RE.fullmatch(entity)
    }


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
