"""Auto-linking utilities for memory relationships."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.knowledge_graph import KnowledgeGraph

if TYPE_CHECKING:
    from core.embeddings import Embedder
    from core.vector_store import VectorStore


logger = logging.getLogger(__name__)


_MAX_CANDIDATES = 10
_SIMILARITY_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class LinkResult:
    """Result of automatic linking for one memory."""

    edges_created: int
    relations: dict[str, int]


def auto_link(
    *,
    graph: KnowledgeGraph,
    memory_id: str,
    content: str,
    memory_type: str,
    project: str,
    embedder: Embedder,
    store: VectorStore,
) -> LinkResult:
    """Find and persist likely relationships for a new memory."""
    vector = embedder.encode(content)

    candidates = store.search(
        vector=vector,
        limit=_MAX_CANDIDATES,
        filters={"project": project},
        score_threshold=_SIMILARITY_THRESHOLD,
    )

    relations: dict[str, int] = {}

    # Ensure source node exists before we add edges.
    if memory_id not in graph._graph:
        graph.add_node(
            memory_id,
            topic=project,
            memory_type=memory_type,
        )

    for candidate in candidates:
        candidate_id = candidate.get("memory_id", "")
        if candidate_id == memory_id or not candidate_id:
            continue

        relation = _classify_relation(
            new_type=memory_type,
            new_content=content,
            cand_type=candidate.get("type", "note"),
            cand_content=candidate.get("content", ""),
            similarity=candidate.get("score", 0.0),
        )

        if relation == "related_to" and candidate.get("score", 0.0) < _SIMILARITY_THRESHOLD:
            continue

        if relation == "supersedes":
            graph.add_edge(memory_id, candidate_id, "supersedes", weight=candidate["score"])
            # Reduce the importance of the superseded memory.
            if candidate_id in graph._graph:
                old_importance = graph._graph.nodes[candidate_id].get("importance", 0.0)
                if old_importance > 0.1:
                    graph._graph.nodes[candidate_id]["importance"] = old_importance * 0.5
                    graph._dirty = True

        elif relation == "led_to":
            # Direction decision -> learning.
            graph.add_edge(candidate_id, memory_id, "led_to", weight=candidate["score"])
        elif relation == "depends_on":
            # Direction decision -> requirement.
            graph.add_edge(memory_id, candidate_id, "depends_on", weight=candidate["score"])
        else:
            if candidate_id not in graph._graph:
                graph.add_node(
                    candidate_id,
                    topic=project,
                    memory_type=candidate.get("type", "note"),
                )
            graph.add_edge(memory_id, candidate_id, relation, weight=candidate["score"])

        relations[relation] = relations.get(relation, 0) + 1

    return LinkResult(
        edges_created=sum(relations.values()),
        relations=relations,
    )


def _classify_relation(
    *,
    new_type: str,
    new_content: str,
    cand_type: str,
    cand_content: str,
    similarity: float,
) -> str:
    """Classify a pair relation.

    Current implementation applies heuristic rules in order.
    """
    del new_content
    del cand_content

    if similarity > 0.9 and new_type == cand_type:
        return "supersedes"

    if new_type == "learning" and cand_type == "decision":
        return "led_to"

    if new_type == "decision" and cand_type == "requirement":
        return "depends_on"

    if similarity > _SIMILARITY_THRESHOLD:
        return "related_to"

    return "related_to"
