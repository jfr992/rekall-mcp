"""Continuity helpers for startup and handoff behavior."""

from __future__ import annotations

from typing import Any


def extract_next_steps(memories: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    """Infer likely next steps from memory content."""
    candidates: list[tuple[str, float]] = []

    for memory in memories:
        content = (memory.get("content") or "").strip().replace("\n", " ")
        lowered = content.lower()
        if not content:
            continue

        score = float(memory.get("importance", 0.0) or 0.0)
        if any(
            token in lowered
            for token in ["todo", "next", "follow up", "need to", "remaining", "pending"]
        ):
            score += 0.5
        if memory.get("type") in {"requirement", "decision", "learning"}:
            score += 0.2

        if score >= 0.45:
            candidates.append((content[:180], score))

    candidates.sort(key=lambda item: item[1], reverse=True)

    seen = set()
    output = []
    for text, _score in candidates:
        if text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def format_handoff_summary(
    *, recent: list[dict[str, Any]], important: list[dict[str, Any]], next_steps: list[str]
) -> str:
    lines = ["## Handoff Summary", ""]

    if important:
        lines.append("### Keep in mind")
        for item in important[:5]:
            lines.append(
                f"- [{item.get('tier', 'working')}/{item.get('type', 'note')}] {item.get('content', '')[:150]}"
            )
        lines.append("")

    if recent:
        lines.append("### Just happened")
        for item in recent[:5]:
            lines.append(f"- [{item.get('date', '')}] {item.get('content', '')[:150]}")
        lines.append("")

    if next_steps:
        lines.append("### Likely next steps")
        for step in next_steps:
            lines.append(f"- {step}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
