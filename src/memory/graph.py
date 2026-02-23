"""Graph helpers for memory visualization."""

from __future__ import annotations

import math
from typing import Any


def _coerce_vector(value: Any) -> list[float]:
    """Coerce an arbitrary vector-like payload into a float list."""
    if value is None:
        return []

    if isinstance(value, dict):
        # Qdrant can occasionally return a dict when named vectors are enabled.
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


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Calculate cosine similarity for two vectors."""
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = 0.0
    left_norm_sq = 0.0
    right_norm_sq = 0.0

    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm_sq += a * a
        right_norm_sq += b * b

    if left_norm_sq == 0.0 or right_norm_sq == 0.0:
        return 0.0

    return dot / (math.sqrt(left_norm_sq) * math.sqrt(right_norm_sq))


def _project_to_2d(vector: list[float]) -> tuple[float, float]:
    """Project a high-dimensional vector into 2D with a deterministic transform."""
    if not vector:
        return 0.0, 0.0

    x = 0.0
    y = 0.0
    # 2*pi*(sqrt(5)-1)/2 for decorrelated projection.
    phi = 2.399963229728653

    for i, value in enumerate(vector):
        weight = i + 1
        angle = phi * weight
        x += math.cos(angle) * value
        y += math.sin(angle) * value

    scale = max(max(abs(x), abs(y)), 1.0)
    return (x / scale, y / scale)


def build_memory_graph(
    points: list[dict[str, Any]],
    neighbor_count: int = 5,
    min_similarity: float = 0.35,
    knowledge_graph=None,
) -> dict[str, Any]:
    """Build a graph payload from memory vectors and metadata."""
    nodes: list[dict[str, Any]] = []
    node_vectors: list[list[float]] = []
    seen_ids: set[str] = set()

    for idx, point in enumerate(points):
        vector = _coerce_vector(point.get("vector"))
        if not vector:
            continue

        memory_id = point.get("memory_id") or point.get("id") or f"memory_{idx}"
        if memory_id in seen_ids:
            continue

        seen_ids.add(memory_id)
        x, y = _project_to_2d(vector)
        content = point.get("content", "")

        nodes.append(
            {
                "id": str(memory_id),
                "content": content,
                "project": point.get("project", "general"),
                "type": point.get("type", "note"),
                "date": point.get("date", ""),
                "memory_id": point.get("memory_id"),
                "position": {"x": x, "y": y},
            }
        )
        node_vectors.append(vector)

    if not nodes:
        return {"nodes": [], "links": [], "stats": {"nodes": 0, "links": 0}}

    neighbor_count = max(1, int(neighbor_count))
    links: list[dict[str, Any]] = []
    degrees = [0] * len(nodes)

    if knowledge_graph is not None and knowledge_graph.stats()["edges"] > 0:
        node_ids = {node["id"] for node in nodes}
        node_index = {node["id"]: idx for idx, node in enumerate(nodes)}
        for source, target, data in knowledge_graph._graph.edges(data=True):
            source_id = str(source)
            target_id = str(target)

            if source_id in node_ids and target_id in node_ids:
                links.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "weight": data.get("weight", 0.5),
                        "relation": data.get("relation", "related_to"),
                    }
                )
                if source_id in node_ids:
                    degrees[node_index[source_id]] += 1
                if target_id in node_ids:
                    degrees[node_index[target_id]] += 1
    else:
        for i in range(len(nodes)):
            similarities: list[tuple[int, float]] = []
            for j in range(i + 1, len(nodes)):
                score = _cosine_similarity(node_vectors[i], node_vectors[j])
                if score >= min_similarity:
                    similarities.append((j, score))

            similarities.sort(key=lambda item: item[1], reverse=True)
            for j, score in similarities[:neighbor_count]:
                links.append(
                    {
                        "source": nodes[i]["id"],
                        "target": nodes[j]["id"],
                        "weight": score,
                    }
                )
                degrees[i] += 1
                degrees[j] += 1

    for idx, degree in enumerate(degrees):
        nodes[idx]["degree"] = degree

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "nodes": len(nodes),
            "links": len(links),
            "dimensions": len(node_vectors[0]),
        },
    }
