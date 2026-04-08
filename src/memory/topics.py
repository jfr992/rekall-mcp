"""Topic discovery and hierarchy generation for memories."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

STOP_WORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "how",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "more",
    "most",
    "no",
    "not",
    "nor",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class TopicCluster:
    """Result of grouping related memories."""

    topic_id: str
    label: str
    memories: list[dict[str, Any]]


def _coerce_vector(value: Any) -> list[float]:
    """Convert a vector-like payload into a list of floats."""
    if value is None:
        return []

    if isinstance(value, dict):
        if len(value) == 1:
            value = next(iter(value.values()))
        else:
            return []

    if isinstance(value, (list, tuple)):
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError):
            return []

    return []


def _extract_terms(content: str, max_terms: int = 4) -> list[str]:
    """Return normalized terms from content."""
    terms = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", content.lower())
    terms = [t for t in terms if t not in STOP_WORDS and len(t) > 2]
    return terms[:max_terms]


def _cluster_label(points: list[dict[str, Any]], members: list[int]) -> str:
    """Infer a short label from most frequent content terms."""
    frequencies: Counter[str] = Counter()
    for idx in members:
        frequencies.update(_extract_terms(points[idx]["content"]))

    if not frequencies:
        return "topic"

    ordered = sorted(
        frequencies.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return ", ".join(term for term, _ in ordered[:2])


def _cluster_from_vectors(
    points: list[dict[str, Any]],
    *,
    similarity_threshold: float,
    max_topics: int | None,
) -> list[list[int]]:
    """Cluster points by vector similarity using scipy average-linkage."""
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage

    valid_idx = [i for i, p in enumerate(points) if p.get("vector")]
    invalid_idx = [i for i in range(len(points)) if i not in set(valid_idx)]

    if len(valid_idx) < 2:
        return [[i] for i in range(len(points))]

    mat = np.array([points[i]["vector"] for i in valid_idx], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat /= norms

    # Average-linkage matches original algorithm's _cluster_similarity semantics
    Z = linkage(mat, method="average", metric="cosine")
    dist_t = max(0.0, 1.0 - similarity_threshold)
    labels = fcluster(Z, t=dist_t, criterion="distance")

    if max_topics is not None and len(set(labels)) > max_topics:
        labels = fcluster(Z, t=max_topics, criterion="maxclust")

    clusters: dict[int, list[int]] = defaultdict(list)
    for local_i, lbl in enumerate(labels):
        clusters[lbl].append(valid_idx[local_i])

    result = [sorted(v) for v in clusters.values()]
    # Absorb invalid-vector memories into the largest cluster rather than
    # creating singletons that blow past the max_topics cap.
    if invalid_idx:
        result[0].extend(invalid_idx)
        result[0] = sorted(result[0])
    return result


def _cluster_lexical(points: list[dict[str, Any]], max_topics: int | None) -> list[list[int]]:
    """Fallback clustering using top lexical term per memory."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for idx, point in enumerate(points):
        terms = _extract_terms(point["content"], max_terms=1)
        key = terms[0] if terms else "topic"
        buckets[key].append(idx)

    clusters = [sorted(indices) for indices in buckets.values()]
    clusters.sort(key=lambda members: (len(members), members), reverse=True)

    if max_topics is None or len(clusters) <= max_topics:
        return clusters

    while len(clusters) > max_topics:
        smallest = clusters.pop()
        clusters[0].extend(smallest)
        clusters[0].sort()
    return clusters


def build_topic_clusters(
    points: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.72,
    max_topics: int | None = None,
) -> list[TopicCluster]:
    """Discover topic clusters from memory points.

    Args:
        points: List of memory payloads.
        similarity_threshold: Minimum similarity for vector merges.
        max_topics: Optional hard cap for topic count.

    Returns:
        List of ordered topic clusters.
    """
    prepared: list[dict[str, Any]] = []
    for idx, point in enumerate(points):
        content = point.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue

        point_copy = dict(point)
        point_copy["memory_id"] = str(
            point.get("memory_id")
            or point.get("id")
            or point.get("timestamp")
            or idx
        )
        point_copy["vector"] = _coerce_vector(point.get("vector"))
        prepared.append(point_copy)

    if not prepared:
        return []

    usable_vectors = [point["vector"] for point in prepared if point["vector"]]
    if len(usable_vectors) >= 2:
        cluster_indices = _cluster_from_vectors(
            prepared,
            similarity_threshold=similarity_threshold,
            max_topics=max_topics,
        )
    else:
        cluster_indices = _cluster_lexical(
            prepared,
            max_topics=max_topics,
        )

    # Sort clusters: bigger topics first, then label alpha.
    clusters: list[TopicCluster] = []
    for index, members in enumerate(cluster_indices):
        members_as_list = sorted(members)
        label = _cluster_label(prepared, members_as_list)
        label = label or "topic"
        clusters.append(
            TopicCluster(
                topic_id=f"topic_{index + 1}",
                label=label,
                memories=[prepared[idx] for idx in members_as_list],
            )
        )

    clusters.sort(key=lambda topic: (-len(topic.memories), topic.label))
    return clusters


def topics_to_json(
    topics: list[TopicCluster],
    *,
    project: str | None = None,
    max_items_per_topic: int | None = None,
) -> dict:
    """Convert topic clusters to structured JSON dict."""
    return {
        "project": project or "all",
        "topics": [
            {
                "topic_id": topic.topic_id,
                "label": topic.label,
                "memory_count": len(topic.memories),
                "memories": [
                    {
                        "memory_id": m.get("memory_id", ""),
                        "content": m.get("content", ""),
                        "type": m.get("type", "note"),
                        "date": m.get("date", ""),
                        "project": m.get("project", "general"),
                    }
                    for m in (topic.memories[:max_items_per_topic] if max_items_per_topic else topic.memories)
                ],
            }
            for topic in topics
        ],
    }


def render_hierarchical_context(
    topics: list[TopicCluster],
    *,
    project: str | None = None,
    max_items_per_topic: int | None = None,
) -> str:
    """Render hierarchical topics into markdown."""
    if not topics:
        return f"# Hierarchical Context: {project or 'all'}\n\nNo memories yet.\n"

    lines = [f"# Hierarchical Context: {project or 'all'}", ""]
    for topic in topics:
        lines.append(f"## {topic.label}")
        lines.append(f"- Items: {len(topic.memories)}")
        for idx, memory in enumerate(topic.memories):
            if max_items_per_topic is not None and idx >= max_items_per_topic:
                break

            memory_id = memory.get("memory_id", "")
            memory_type = memory.get("type", "note")
            date = memory.get("date", "")
            content = memory.get("content", "").strip()
            header = " - "
            if memory_id:
                header += f"[{memory_id}] "
            if date or memory_type:
                header += f"({date} {memory_type}) "
            lines.append(f"{header}{content}")

        lines.append("")

    return "\n".join(lines)
