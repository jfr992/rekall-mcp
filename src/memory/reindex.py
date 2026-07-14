"""Reindex contract: tarball -> rebuild -> verify -> graph (portability spec rev 3).

Lock-safety: every collection touch goes through the caller's ``manager.store``.
A second VectorStore on the same embedded path would fail qdrant's flock.
"""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import BM25Encoder
from memory.migrate_hybrid import build_corpus, load_all_yaml_memories

if TYPE_CHECKING:
    from memory.manager import MemoryManager

logger = logging.getLogger(__name__)

INDEXED_FIELDS = ("date", "project", "type", "memory_id")


def _tarball(src: Path, dest: Path) -> None:
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(src, arcname=src.name)


def _backup_roots(manager: MemoryManager, tarball_dir: Path) -> list[Path]:
    """Tarball BOTH roots before anything touches the collection."""
    tarball_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts: list[Path] = []

    mem_tar = tarball_dir / f"rekall-reindex-{ts}-memory.tar.gz"
    _tarball(manager.memory_dir, mem_tar)
    artifacts.append(mem_tar)

    if manager._qdrant_path:
        qdrant_root = Path(manager._qdrant_path)
        qdrant_root.mkdir(parents=True, exist_ok=True)
        q_tar = tarball_dir / f"rekall-reindex-{ts}-qdrant.tar.gz"
        _tarball(qdrant_root, q_tar)
        artifacts.append(q_tar)
    else:
        note = tarball_dir / f"rekall-reindex-{ts}-qdrant-url.NOTE.txt"
        note.write_text(
            f"qdrant target {manager._qdrant_url} is a server — snapshot it "
            "server-side before relying on this backup\n"
        )
        artifacts.append(note)
    return artifacts


def _rebuild_collection(
    manager: MemoryManager,
    memories: list[dict[str, Any]],
    encoder: BM25Encoder,
) -> int:
    """Recreate the collection and re-embed every YAML memory (repr v2).

    The store copies the sparse encoder once at construction, so BOTH
    ``manager._sparse_encoder`` and ``manager.store.sparse_encoder`` are set
    before recreation. Points are written via ``manager.store.save`` — never
    ``manager.save`` (which would re-trigger dedupe/linker/bootstrap).
    """
    embedder = manager.embedder
    sentinel = manager.reindex_sentinel
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    manager._sparse_encoder = encoder
    manager.store.sparse_encoder = encoder
    encoder.save(str(manager._bm25_path))

    manager.store.recreate_collection()
    for field in INDEXED_FIELDS:
        try:
            manager.store.create_index(field)
        except Exception:
            pass  # Index may already exist

    for mem in memories:
        payload = {k: v for k, v in mem.items() if not k.startswith("_")}
        content = str(payload.get("content") or "")
        embedding_text = str(payload.get("embedding_text") or "") or content
        payload["embedding_text"] = embedding_text
        payload["repr_version"] = 2
        manager.store.save(
            id=payload["memory_id"],
            vector=embedder.encode(content),
            payload=payload,
            content=embedding_text,
        )

    count = manager.store.count()
    if count != len(memories):
        raise RuntimeError(
            f"reindex verification failed: {count} points != {len(memories)} YAML memories"
        )
    if memories:
        sample = manager.store.scroll(limit=1, with_vectors=True)
        if not sample or not any(v != 0 for v in sample[0].get("vector") or []):
            raise RuntimeError("reindex verification failed: sampled vector is all-zero")
    return count


def reindex(manager: MemoryManager, *, tarball_dir: Path | None = None) -> dict[str, Any]:
    """Rebuild the vector store from YAML: tarball -> rebuild -> verify -> graph."""
    tarball_dir = Path(tarball_dir) if tarball_dir else Path.home() / "backups"
    _backup_roots(manager, tarball_dir)

    # Prove the embedder loads and encodes BEFORE the collection is touched —
    # a missing/broken model must never leave us with a destroyed collection.
    manager.embedder.encode("rekall reindex embedder probe")

    memories = load_all_yaml_memories(manager.memory_dir)
    encoder = BM25Encoder()
    encoder.fit(build_corpus(memories))

    points = _rebuild_collection(manager, memories, encoder)
    graph_stats = manager.knowledge_graph.rebuild(store=manager.store, embedder=manager.embedder)

    # Success — clear the marker. On any failure above it stays put and the
    # manager refuses save/recall until a reindex completes.
    manager.reindex_sentinel.unlink(missing_ok=True)
    return {"points": points, "verified": True, "graph_nodes": graph_stats["nodes"]}
