"""Action-aware reflex recall for risky software work."""

from __future__ import annotations

from typing import Any

_CUES = {
    "destructive": {
        "terms": (
            "rm -rf",
            "drop table",
            "force-delete",
            "forcedelete",
            "rotate",
            "prune",
            "kubectl delete",
            "terraform destroy",
            "tofu destroy",
            "helm uninstall",
        ),
        "query": "backups data loss incidents safety rules destructive operations",
    },
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


MAX_CUES = 3


def build_reflex_packet(
    manager,
    *,
    text: str,
    project: str | None = None,
    limit: int = 4,
    cwd: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build a small recall packet for cues matched by command or prompt text.

    Selects up to MAX_CUES matched cues (destructive first, then _CUES
    declaration order) and merges their queries into a single recall call —
    one network round trip regardless of how many cue groups matched.
    """
    all_cues = detect_reflex_cues(text)
    cues = all_cues[:MAX_CUES]
    dropped_cues = all_cues[MAX_CUES:]

    if limit <= 0 or not cues:
        return {
            "text": text,
            "project": project,
            "cues": cues,
            "dropped_cues": dropped_cues,
            "memories": [],
        }

    merged_query = " ".join(_CUES[cue]["query"] for cue in cues)

    memories = []
    seen: set[str] = set()
    for memory in manager.recall(
        query=merged_query,
        project=project,
        limit=limit,
        score_threshold=0.5,
        cwd=cwd,
        source="reflex",
        session_id=session_id,
    ):
        if len(memories) >= limit:
            break
        memory_id = memory.get("memory_id")
        if memory_id and memory_id in seen:
            continue
        if memory_id:
            seen.add(memory_id)
        memories.append(memory)

    return {
        "text": text,
        "project": project,
        "cues": cues,
        "dropped_cues": dropped_cues,
        "memories": memories,
    }
