"""READ-ONLY dry-run: linker entity-band membership at corpus scale.

Measures how many same-type entity-overlapping pairs fall into the OLD
contradiction band [0.6, 0.9) on the STORED dense vectors vs the NEW band
[0.46, 0.85) on locally re-encoded raw content (repr v2). This is the evidence
gate for the provisional 0.46 floor (calibrated on only ~5 fixture pairs).

No writes, no LLM calls — one scroll, local math only. Safe against production.

Usage:
    QDRANT_URL=http://localhost:6333 uv run python scripts/edge_count_dryrun.py
    # optional: REKALL_COLLECTION=agent_memory
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logger = logging.getLogger(__name__)

OLD_BAND = (0.60, 0.90)
NEW_BAND = (0.46, 0.85)


def _entities_of(payload: dict[str, Any]) -> set[str]:
    from memory.representation import extract_entities

    entities = payload.get("entities")
    if not isinstance(entities, list) or not entities:
        entities = extract_entities(str(payload.get("content") or ""))
    return {str(e).lower() for e in entities}


def edge_count_dryrun(qdrant_url: str, collection: str = "agent_memory") -> dict[str, Any]:
    """Report OLD-band (stored vectors) vs NEW-band (re-encoded content) pairs."""
    import numpy as np
    from qdrant_client import QdrantClient

    from core import Embedder

    client = QdrantClient(url=qdrant_url, timeout=60)
    embedder = Embedder()

    ids: list[str] = []
    types: list[str] = []
    entity_sets: list[set[str]] = []
    stored_vectors: list[list[float]] = []
    contents: list[str] = []

    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break
        for point in points:
            payload = dict(point.payload or {})
            content = str(payload.get("content") or "").strip()
            vector = point.vector
            if isinstance(vector, dict):
                vector = vector.get("") or next(
                    (v for v in vector.values() if isinstance(v, list)), None
                )
            if not content or not vector:
                continue
            ids.append(str(payload.get("memory_id") or point.id))
            types.append(str(payload.get("type") or "note"))
            entity_sets.append(_entities_of(payload))
            stored_vectors.append(list(vector))
            contents.append(content)
        if offset is None:
            break

    n = len(ids)
    if n < 2:
        return {"points": n, "considered_pairs": 0, "old_band_pairs": 0, "new_band_pairs": 0, "pairs": []}

    def _cosine_matrix(vectors: list[list[float]]) -> Any:
        matrix = np.asarray(vectors, dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit = matrix / norms
        return unit @ unit.T

    old_cos = _cosine_matrix(stored_vectors)
    new_cos = _cosine_matrix([embedder.encode(c) for c in contents])

    considered = old_band = new_band = 0
    pairs: list[tuple[str, str, float, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if types[i] != types[j] or not (entity_sets[i] & entity_sets[j]):
                continue
            considered += 1
            o, w = float(old_cos[i, j]), float(new_cos[i, j])
            old_band += OLD_BAND[0] <= o < OLD_BAND[1]
            new_band += NEW_BAND[0] <= w < NEW_BAND[1]
            pairs.append((ids[i], ids[j], round(o, 4), round(w, 4)))

    return {
        "points": n,
        "considered_pairs": considered,
        "old_band_pairs": old_band,
        "new_band_pairs": new_band,
        "pairs": pairs,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    qdrant_url = os.environ.get("QDRANT_URL")
    if not qdrant_url:
        print("QDRANT_URL env var is required")
        return 1
    report = edge_count_dryrun(
        qdrant_url=qdrant_url,
        collection=os.environ.get("REKALL_COLLECTION", "agent_memory"),
    )
    print(
        f"points={report['points']} considered_pairs={report['considered_pairs']} "
        f"old_band[0.60,0.90)={report['old_band_pairs']} "
        f"new_band[0.46,0.85)={report['new_band_pairs']}"
    )
    for a, b, o, w in report["pairs"]:
        if OLD_BAND[0] <= o < OLD_BAND[1] or NEW_BAND[0] <= w < NEW_BAND[1]:
            print(f"  {a} <-> {b}  stored={o:.4f}  repr_v2={w:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
