"""Auto-linking utilities for memory relationships."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory.knowledge_graph import KnowledgeGraph
from memory.representation import extract_entities

if TYPE_CHECKING:
    from core.embeddings import Embedder
    from core.vector_store import VectorStore


logger = logging.getLogger(__name__)


_MAX_CANDIDATES = 10
# Repr v2 calibration (2026-07-09): stored-vs-stored cosines re-measured on the
# linker/freshness fixture pairs after dense vectors moved from embedding_text
# to raw content (all-MiniLM). Bands re-derived by bracket midpoint between the
# nearest measured pairs on either side of each old boundary:
#   supersedes 0.9 -> 0.85  (entity-band max 0.7717 < S <= supersedes min 0.9261)
#   contradiction floor 0.6 -> 0.46  (unrelated 0.1678 < C <= band min 0.7464)
#   similar floor 0.5 -> 0.40  (same bracket; keeps the historical offset below C)
_SIMILARITY_THRESHOLD = 0.40
_CONTRADICTION_SIMILARITY_THRESHOLD = 0.46
_SUPERSEDES_SIMILARITY_THRESHOLD = 0.85

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
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?")
_MIN_CONTRADICTION_OVERLAP = 2
_NEGATION_PROXIMITY_WINDOW = 3
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
    # Repr v2: stored dense vectors are encode(content) — search with the same
    # representation or similarity silently degrades (PR #38 bug class).
    vector = embedder.encode(content)
    new_entities = extract_entities(content)

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

        relation, llm_refined = _classify_relation(
            new_type=memory_type,
            new_content=content,
            cand_type=candidate.get("type", "note"),
            cand_content=candidate.get("content", ""),
            similarity=candidate.get("score", 0.0),
            new_entities=new_entities,
            cand_entities=candidate.get("entities") or [],
        )

        if relation == "related_to" and candidate.get("score", 0.0) < _SIMILARITY_THRESHOLD:
            continue

        if relation == "supersedes":
            graph.add_edge(
                memory_id,
                candidate_id,
                "supersedes",
                weight=candidate["score"],
                llm_refined=llm_refined,
            )
            if llm_refined:
                logger.debug("llm_refined supersedes: %s -> %s", memory_id, candidate_id)
            # Reduce the importance of the superseded memory.
            if candidate_id in graph._graph:
                old_importance = graph._graph.nodes[candidate_id].get("importance", 0.0)
                if old_importance > 0.1:
                    graph._graph.nodes[candidate_id]["importance"] = old_importance * 0.5
                    graph._dirty = True

        elif relation == "contradicts":
            # Direction from newer memory -> older memory.
            graph.add_edge(
                memory_id,
                candidate_id,
                "contradicts",
                weight=candidate["score"],
                llm_refined=llm_refined,
            )

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


def _entity_overlap(new_entities: list[str], cand_entities: list[str]) -> int:
    """Return count of case-insensitive shared entities between two lists."""
    new_set = {e.lower() for e in new_entities}
    cand_set = {e.lower() for e in cand_entities}
    return len(new_set & cand_set)


def _llm_refine(*, new_content: str, cand_content: str, deterministic: str) -> tuple[str, bool]:
    """Optionally refine the deterministic relation via a Haiku call. Fail-open.

    Returns ``(relation, llm_refined)`` where ``llm_refined`` is True only when
    the LLM answer differed from the deterministic input.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return deterministic, False
    try:
        import anthropic as _ant

        client = _ant.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Memory A (newer): {new_content}\n"
                        f"Memory B (older): {cand_content}\n\n"
                        "Does A supersede B, contradict B, or is it just related? "
                        "Reply with exactly one word: SUPERSEDES, CONTRADICTS, or RELATED."
                    ),
                }
            ],
        )
        word = response.content[0].text.strip().upper()
        mapping = {
            "SUPERSEDES": "supersedes",
            "CONTRADICTS": "contradicts",
            "RELATED": "related_to",
        }
        result = mapping.get(word, deterministic)
        llm_refined = result != deterministic
        return result, llm_refined
    except Exception:
        return deterministic, False


def _classify_relation(
    *,
    new_type: str,
    new_content: str,
    cand_type: str,
    cand_content: str,
    similarity: float,
    new_entities: list[str] | None = None,
    cand_entities: list[str] | None = None,
) -> tuple[str, bool]:
    """Classify a pair relation.

    Returns ``(relation, llm_refined)`` — ``llm_refined`` is True when the LLM
    answer overrode the deterministic classification.  All non-LLM paths return
    ``llm_refined=False``.
    """
    if _is_contradiction(new_content=new_content, cand_content=cand_content, similarity=similarity):
        return "contradicts", False

    if similarity > _SUPERSEDES_SIMILARITY_THRESHOLD and new_type == cand_type:
        return "supersedes", False

    # Entity-band contradicts: same type, mid-range similarity, shared entities signal conflict.
    if (
        new_type == cand_type
        and _CONTRADICTION_SIMILARITY_THRESHOLD
        <= similarity
        < _SUPERSEDES_SIMILARITY_THRESHOLD
        and _entity_overlap(new_entities or [], cand_entities or []) >= 1
    ):
        relation, llm_refined = _llm_refine(
            new_content=new_content,
            cand_content=cand_content,
            deterministic="contradicts",
        )
        if llm_refined:
            logger.debug("llm_refined %s: new -> cand", relation)
        return relation, llm_refined

    if new_type == "learning" and cand_type == "decision":
        return "led_to", False

    if new_type == "decision" and cand_type == "requirement":
        return "depends_on", False

    if similarity > _SIMILARITY_THRESHOLD:
        return "related_to", False

    return "related_to", False


def _is_contradiction(
    *,
    new_content: str,
    cand_content: str,
    similarity: float,
) -> bool:
    """Return True when texts appear semantically related and logically opposite.

    Requires:
    1. High enough semantic similarity (>= 0.6)
    2. Exactly one text contains negation (asymmetric)
    3. Minimum token overlap (>= 2 shared non-stop-words)
    4. The negation targets a concept shared with the other text
       (negation word must appear within 3 words of a shared token)
    """
    if similarity < _CONTRADICTION_SIMILARITY_THRESHOLD:
        return False

    new_has_negation = _contains_negation(new_content)
    cand_has_negation = _contains_negation(cand_content)
    if not (new_has_negation or cand_has_negation):
        return False

    # Ignore when both assertions negate the same concept.
    if new_has_negation and cand_has_negation:
        return False

    if _token_overlap(new_content, cand_content) < _MIN_CONTRADICTION_OVERLAP:
        return False

    # The negation must target a concept shared with the other text.
    negating = new_content if new_has_negation else cand_content
    other = cand_content if new_has_negation else new_content
    return _negation_near_shared_concept(negating, other)


def _negation_near_shared_concept(
    negating_text: str,
    other_text: str,
) -> bool:
    """Check if a negation word appears near a token that also appears in other_text.

    This prevents false positives where a negation is incidental (e.g. "not a
    standard issue type") and unrelated to the shared concepts between texts.
    """
    words = negating_text.lower().split()
    other_tokens = _tokenize(other_text)

    for i, word in enumerate(words):
        clean = re.sub(r"[^\w'-]", "", word)
        if not _NEGATION_RE.search(clean):
            continue
        # Check words within window after the negation
        for j in range(i + 1, min(i + _NEGATION_PROXIMITY_WINDOW + 1, len(words))):
            neighbor = words[j]
            neighbor_tokens = {
                t for t in _TOKEN_RE.findall(neighbor) if t.lower() not in _STOP_WORDS
            }
            if {t.lower() for t in neighbor_tokens} & other_tokens:
                return True
    return False


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
