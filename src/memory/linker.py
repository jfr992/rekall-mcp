"""Auto-linking utilities for memory relationships."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.knowledge_graph import KnowledgeGraph

if TYPE_CHECKING:
    from core.embeddings import Embedder
    from core.vector_store import VectorStore


logger = logging.getLogger(__name__)


_MAX_CANDIDATES = 10
_SIMILARITY_THRESHOLD = 0.5
_CONTRADICTION_SIMILARITY_THRESHOLD = 0.6

_NEGATION_PATTERNS = (
    r"\bno longer\b",
    r"\bnot\b",
    r"\bnever\b",
    r"\bcan(?:not|'t)\b",
    r"\bcannot\b",
    r"\bdo not\b",
    r"\bdid not\b",
    r"\bshould not\b",
    r"\bmust not\b",
    r"\bdisabl(?:ed|ing|e)\b",
    r"\bcancel(?:led|ing)?\b",
    r"\bremoved\b",
    r"\bstop\b",
    r"\bavoid(?:ed)?\b",
    r"\bforbid(?:den)?\b",
)

_NEGATION_RE = re.compile("|".join(_NEGATION_PATTERNS), re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "for",
    "from",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "will",
    "with",
    "within",
    "would",
}


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

        elif relation == "contradicts":
            # Direction from newer memory -> older memory.
            graph.add_edge(memory_id, candidate_id, "contradicts", weight=candidate["score"])

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
    if _is_contradiction(new_content=new_content, cand_content=cand_content, similarity=similarity):
        return "contradicts"

    if similarity > 0.9 and new_type == cand_type:
        return "supersedes"

    if new_type == "learning" and cand_type == "decision":
        return "led_to"

    if new_type == "decision" and cand_type == "requirement":
        return "depends_on"

    if similarity > _SIMILARITY_THRESHOLD:
        return "related_to"

    return "related_to"


def _is_contradiction(
    *,
    new_content: str,
    cand_content: str,
    similarity: float,
) -> bool:
    """Return True when texts appear semantically related and logically opposite."""
    if similarity < _CONTRADICTION_SIMILARITY_THRESHOLD:
        return False

    new_has_negation = _contains_negation(new_content)
    cand_has_negation = _contains_negation(cand_content)
    if not (new_has_negation or cand_has_negation):
        return False

    # Ignore when both assertions negate the same concept.
    if new_has_negation and cand_has_negation:
        return False

    overlap = _token_overlap(new_content, cand_content)
    return overlap > 0


def _contains_negation(content: str) -> bool:
    """Detect language patterns that usually indicate negation."""
    return bool(_NEGATION_RE.search(content.lower()))


def _token_overlap(a: str, b: str) -> int:
    """Count non-stopword token overlap between two memories."""
    return len(_tokenize(a) & _tokenize(b))


def _tokenize(content: str) -> set[str]:
    """Tokenize and normalize text for rough lexical overlap checks."""
    tokens = {token.lower() for token in _TOKEN_RE.findall(content)}
    return {token for token in tokens if token not in _STOP_WORDS}
