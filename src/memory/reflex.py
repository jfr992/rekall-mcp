"""Action-aware reflex recall for risky software work."""

from __future__ import annotations

from typing import Any


_CUES = {
    "iac": {
        "terms": ("terraform", "terragrunt", "tofu"),
        "query": "infrastructure terraform terragrunt tofu safety rules prior failures",
    },
    "memory_data": {
        "terms": ("qdrant", "memory sync", "memory cleanup", "compact", "prune", "reindex"),
        "query": "memory qdrant sync cleanup compaction prune backup data loss rules",
    },
    "hooks": {
        "terms": ("claude hook", "hooks", "settings.json", "CLAUDE.md", "session-start-memory"),
        "query": "claude hooks settings backup startup memory policy",
    },
    "helm": {
        "terms": ("helm", "chart", "longhorn", "k3s"),
        "query": "helm chart longhorn k3s deployment gotchas",
    },
}


def detect_reflex_cues(text: str) -> list[str]:
    """Return reflex cue names matched by the supplied text."""
    lowered = text.lower()
    cues = []
    for name, rule in _CUES.items():
        if any(term.lower() in lowered for term in rule["terms"]):
            cues.append(name)
    return cues


def build_reflex_packet(
    manager,
    *,
    text: str,
    project: str | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """Build a small recall packet for cues matched by command or prompt text."""
    cues = detect_reflex_cues(text)
    memories = []
    seen: set[str] = set()

    for cue in cues:
        query = _CUES[cue]["query"]
        for memory in manager.recall(
            query=query,
            project=project,
            limit=limit,
            score_threshold=0.5,
        ):
            memory_id = memory.get("memory_id")
            if memory_id and memory_id in seen:
                continue
            if memory_id:
                seen.add(memory_id)
            memories.append({**memory, "reason": cue})

    return {
        "text": text,
        "project": project,
        "cues": cues,
        "memories": memories[:limit],
    }
