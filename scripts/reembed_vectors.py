"""Re-embed stored memory vectors in place (payloads and YAML untouched).

Remedy for the zero-vector corruption class that /health reports as
`degraded` (all-zero embeddings = silently dead semantic search).

Usage (inside the mcp container, where the model lives):
    docker cp scripts/reembed_vectors.py rekall-mcp:/tmp/reembed_vectors.py
    docker exec rekall-mcp python /tmp/reembed_vectors.py

Or on the host with deps installed:
    PYTHONPATH=src uv run python scripts/reembed_vectors.py
"""

import os
import sys

sys.path.insert(0, "/app/src")

from qdrant_client import QdrantClient
from qdrant_client.models import PointVectors

from core.embeddings import Embedder

QDRANT = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("REKALL_COLLECTION", "agent_memory")
BATCH = 64


def main() -> None:
    client = QdrantClient(url=QDRANT, timeout=60)
    embedder = Embedder()

    offset = None
    total = fixed = already_ok = no_content = 0

    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION,
            limit=BATCH,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break

        to_fix = []
        for p in points:
            total += 1
            vec = p.vector
            if isinstance(vec, dict):
                vec = next(iter(vec.values())) if len(vec) == 1 else None
            if vec and any(x != 0 for x in vec):
                already_ok += 1
                continue
            content = (p.payload or {}).get("content") or ""
            if not content.strip():
                no_content += 1
                continue
            to_fix.append((p.id, content))

        if to_fix:
            vectors = embedder.encode_batch([c for _, c in to_fix])
            client.update_vectors(
                collection_name=COLLECTION,
                points=[
                    PointVectors(id=pid, vector=v)
                    for (pid, _), v in zip(to_fix, vectors, strict=True)
                ],
            )
            fixed += len(to_fix)
            print(f"progress: scanned={total} fixed={fixed}", flush=True)

        if offset is None:
            break

    print(f"DONE scanned={total} fixed={fixed} already_ok={already_ok} no_content={no_content}")


if __name__ == "__main__":
    main()
