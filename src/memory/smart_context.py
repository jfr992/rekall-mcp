"""Smart context injection — project-aware, token-capped memory context.

Produces a lean, relevant context string for session start injection.
Instead of dumping everything, selects and ranks memories by:
- Importance (from knowledge graph)
- Recency (days since created)
- Type weight (decisions > learnings > notes)

Usage:
    from memory.smart_context import get_smart_context

    result = get_smart_context(manager, project="byte-edge", max_tokens=2000)
    print(result["context"])   # formatted markdown
    print(result["tokens"])    # token budget used
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.manager import MemoryManager

logger = logging.getLogger(__name__)

# Type weight: higher = more important to include
TYPE_WEIGHTS: dict[str, float] = {
    "requirement": 1.0,
    "decision": 0.9,
    "learning": 0.8,
    "preference": 0.7,
    "note": 0.5,
    "session": 0.3,
    "summary": 0.6,
}

# ~4 characters per token (conservative estimate)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count using character-based heuristic.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def score_memory(memory: dict[str, Any], importance: float = 0.5) -> float:
    """Score a memory for smart context ranking.

    Formula: importance × 0.3 + recency × 0.3 + type_weight × 0.2 + access × 0.2
    (access_frequency simplified to a fixed 0.5 since we don't track it per-memory easily)

    Args:
        memory: Memory dict with date, type fields
        importance: Graph importance score (0-1)

    Returns:
        Combined score (0-1)
    """
    # Recency: 1.0 = today, 0.0 = 365+ days old
    recency = 0.5  # fallback
    date_str = memory.get("date")
    if date_str:
        try:
            mem_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_old = (datetime.now() - mem_date).days
            recency = max(0.0, 1.0 - days_old / 365)
        except ValueError:
            pass

    type_weight = TYPE_WEIGHTS.get(memory.get("type", "note"), 0.5)

    return (
        importance * 0.3
        + recency * 0.3
        + type_weight * 0.2
        + 0.5 * 0.2  # access_frequency placeholder
    )


def select_within_budget(
    memories: list[dict[str, Any]],
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Select memories that fit within the token budget, highest score first.

    Args:
        memories: List of memory dicts with _score key set
        max_tokens: Token budget

    Returns:
        Subset of memories fitting within budget (sorted by score desc)
    """
    # Sort by _score descending
    ranked = sorted(memories, key=lambda m: m.get("_score", 0.0), reverse=True)

    selected: list[dict[str, Any]] = []
    used_tokens = 0

    for mem in ranked:
        content = mem.get("content", "")
        tokens = estimate_tokens(content)

        if used_tokens + tokens <= max_tokens:
            selected.append(mem)
            used_tokens += tokens
        # Continue checking — a shorter memory later might still fit
        elif used_tokens >= max_tokens * 0.9:
            break  # budget >90% used, stop

    return selected


def format_smart_context(
    memories: list[dict[str, Any]],
    project: str | None = None,
) -> str:
    """Format memories as lean markdown for session injection.

    Groups into Recent (last 7 days) and Key Context sections.

    Args:
        memories: List of memory dicts
        project: Optional project name for header

    Returns:
        Markdown string
    """
    if not memories:
        return ""

    cutoff_recent = (
        datetime.now()
        .__class__
        .now()
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    # Use 7-day cutoff for "recent"
    from datetime import timedelta

    recent_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    recent: list[dict] = []
    key_context: list[dict] = []

    for mem in memories:
        date = mem.get("date", "")
        if date >= recent_cutoff:
            recent.append(mem)
        else:
            key_context.append(mem)

    lines: list[str] = []

    header = f"## Resuming: {project}" if project else "## Memory Context"
    lines.append(header)
    lines.append("")

    if recent:
        lines.append("### Recent (last 7 days)")
        for mem in recent:
            mem_type = mem.get("type", "note")
            content = mem.get("content", "").replace("\n", " ")[:120]
            date = mem.get("date", "")
            lines.append(f"- [{mem_type}] {content} ({date})")
        lines.append("")

    if key_context:
        lines.append("### Key Context")
        for mem in key_context:
            mem_type = mem.get("type", "note")
            content = mem.get("content", "").replace("\n", " ")[:120]
            lines.append(f"- [{mem_type}] {content}")
        lines.append("")

    total = len(memories)
    tokens = estimate_tokens("\n".join(lines))
    lines.append(f"<!-- {total} memories | {tokens} tokens | project: {project or 'all'} -->")

    return "\n".join(lines)


def get_smart_context(
    manager: "MemoryManager",
    project: str | None = None,
    limit: int = 10,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Get smart, token-efficient context for session injection.

    Args:
        manager: MemoryManager instance
        project: Filter by project name (None = all projects)
        limit: Max memories to consider before token truncation
        max_tokens: Token budget for returned context

    Returns:
        Dict with keys: context, memories_included, tokens, project
    """
    # Fetch candidate memories
    filters: dict[str, Any] = {}
    if project:
        filters["project"] = project

    points = manager.store.scroll(
        filters=filters if filters else None,
        limit=limit * 3,  # fetch more, then rank+truncate
    )

    if not points:
        return {
            "context": "",
            "memories_included": 0,
            "tokens": 0,
            "project": project or "all",
        }

    # Score each memory
    graph = manager.knowledge_graph
    graph_has_nodes = graph.stats()["nodes"] > 0

    scored: list[dict[str, Any]] = []
    for point in points:
        memory_id = point.get("memory_id", "")
        importance = graph.get_importance(memory_id) if graph_has_nodes and memory_id else 0.5
        score = score_memory(point, importance=importance)
        scored.append({**point, "_score": score})

    # Select within token budget
    selected = select_within_budget(scored, max_tokens=max_tokens)

    # Format
    context = format_smart_context(selected, project=project)
    tokens = estimate_tokens(context)

    return {
        "context": context,
        "memories_included": len(selected),
        "tokens": tokens,
        "project": project or "all",
    }
