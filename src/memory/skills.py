"""Skill extraction from memory points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memory.topics import _extract_terms

STOP_WORDS = {
    "can",
    "for",
    "how",
    "now",
    "our",
    "out",
    "the",
    "this",
    "that",
    "too",
    "with",
}


@dataclass(frozen=True)
class Skill:
    """A skill candidate derived from memory evidence."""

    name: str
    mentions: int
    snippets: list[str]


def extract_skills(
    points: list[dict[str, Any]],
    *,
    min_mentions: int = 2,
    max_skills: int = 8,
) -> list[Skill]:
    """Derive likely skills from repeated memory terms.

    Args:
        points: Memory payloads with optional `content`, `memory_id`.
        min_mentions: Minimum number of memories mentioning a term.
        max_skills: Maximum number of skills to return.

    Returns:
        Sorted skill candidates (highest evidence first).
    """
    mentions: dict[str, set[str]] = {}
    snippets: dict[str, list[str]] = {}

    for point in points:
        memory_id = point.get("memory_id") or point.get("id") or ""
        if not memory_id:
            continue

        raw_terms = _extract_terms(point.get("content", ""), max_terms=16)
        seen_terms = set(raw_terms)
        for term in seen_terms:
            normalized = term.lower()
            if normalized in STOP_WORDS:
                continue

            mention_set = mentions.setdefault(normalized, set())
            mention_set.add(str(memory_id))
            snippet = f"{memory_id}: {point.get('content', '').strip()}"
            snippets.setdefault(normalized, []).append(snippet)

    ranked = sorted(
        ((name, len(ids)) for name, ids in mentions.items() if len(ids) >= min_mentions),
        key=lambda pair: (-pair[1], pair[0]),
    )

    if max_skills <= 0:
        return []

    skills: list[Skill] = []
    for name, count in ranked[:max_skills]:
        skills.append(
            Skill(
                name=name,
                mentions=count,
                snippets=snippets[name][:2],
            )
        )

    return skills


def render_skill_context(
    skills: list[Skill],
    *,
    project: str | None = None,
) -> str:
    """Render extracted skills into markdown."""
    if not skills:
        return f"# Skill Context: {project or 'all'}\n\nNo explicit skills identified.\n"

    lines = [f"# Skill Context: {project or 'all'}", ""]
    for skill in skills:
        lines.append(f"## {skill.name} ({skill.mentions} mentions)")
        for snippet in skill.snippets:
            lines.append(f"- {snippet}")
        lines.append("")

    return "\n".join(lines)
