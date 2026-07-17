from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml


def _yaml_ids(memory_dir: Path, project: str | None) -> set[str]:
    ids: set[str] = set()
    roots = [memory_dir / project, memory_dir] if project else [memory_dir]
    for root in roots:
        if not root.exists():
            continue
        for yaml_file in root.rglob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            data = yaml.safe_load(yaml_file.read_text()) or {}
            for value in data.values():
                if isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        if project and item.get("project") != project:
                            continue
                        if item.get("id"):
                            ids.add(str(item["id"]))
    return ids


def _bm25_block(manager) -> dict[str, Any]:
    """BM25 vocab/drift health. Verdict stays inside this block, never global findings."""
    vocab_path = (
        getattr(manager, "_bm25_path", None) or Path(manager.memory_dir) / "_bm25_vocab.json"
    )
    drift_path = vocab_path.with_name("_bm25_drift.json")

    block: dict[str, Any] = {
        "vocab_present": False,
        "vocab_age_days": None,
        "vocab_size": None,
        "binding_ok": True,
        "oov_rate_window": None,
        "oov_identifier_seen": False,
        "saves_since_fit": 0,
        "resparse_inflight": False,
        "verdict": "missing",
    }

    if vocab_path.with_name(".resparse-in-progress").exists():
        # Mixed-generation sparse vectors: sparse leg is disabled until a
        # resparse rerun completes — this verdict outranks every other.
        block["vocab_present"] = vocab_path.exists()
        block["resparse_inflight"] = True
        block["verdict"] = "resparse_incomplete"
        return block

    try:
        drift = json.loads(drift_path.read_text())
    except (OSError, ValueError):
        drift = None
    if isinstance(drift, dict):
        window = [w for w in drift.get("window") or [] if isinstance(w, (int, float))]
        if window:
            block["oov_rate_window"] = round(sum(window) / len(window), 4)
        block["oov_identifier_seen"] = bool(drift.get("oov_identifier_seen"))
        saves = drift.get("saves_since_fit")
        block["saves_since_fit"] = saves if isinstance(saves, int) else 0

    if not vocab_path.exists():
        return block
    block["vocab_present"] = True
    block["vocab_age_days"] = round((time.time() - vocab_path.stat().st_mtime) / 86400, 2)

    try:
        data = json.loads(vocab_path.read_text())
        vocab = data.get("vocab") if isinstance(data, dict) else None
        if not isinstance(vocab, dict):
            raise ValueError("vocab is not a mapping")
    except (OSError, ValueError):
        block["verdict"] = "corrupt"
        return block
    block["vocab_size"] = len(vocab)

    binding = data.get("_binding")
    if binding:
        target = str(
            getattr(manager, "_qdrant_path", None) or getattr(manager, "_qdrant_url", None)
        )
        block["binding_ok"] = binding.get("target") == target and binding.get(
            "collection"
        ) == getattr(manager, "COLLECTION", None)

    stale = (
        (block["oov_rate_window"] is not None and block["oov_rate_window"] > 0.15)
        or block["vocab_age_days"] > 7
        or block["oov_identifier_seen"]
    )
    block["verdict"] = "stale" if stale else "ok"
    return block


def run_memory_doctor(manager, project: str | None = None, limit: int = 10000) -> dict[str, Any]:
    filters = {"project": project} if project else None
    qdrant_points = manager.store.scroll(filters=filters, limit=limit)
    qdrant_ids = {str(point["memory_id"]) for point in qdrant_points if point.get("memory_id")}
    yaml_ids = _yaml_ids(Path(manager.memory_dir), project)

    missing_from_qdrant = sorted(yaml_ids - qdrant_ids)
    missing_from_yaml = sorted(qdrant_ids - yaml_ids)

    provenance = {
        "missing_agent": sum(
            1 for point in qdrant_points if point.get("agent") in (None, "", "unknown")
        ),
        "missing_source_tool": sum(1 for point in qdrant_points if not point.get("source_tool")),
        "missing_cwd": sum(1 for point in qdrant_points if not point.get("cwd")),
    }
    vector_health = manager.vector_health()
    graph_stats = manager.knowledge_graph.stats()
    bm25 = _bm25_block(manager)

    findings = []
    notes: list[str] = []
    if missing_from_qdrant:
        findings.append("yaml_not_indexed")
    if missing_from_yaml:
        findings.append("qdrant_without_yaml")
    if vector_health.get("zero_vectors", 0):
        findings.append("zero_vectors")
    if any(provenance.values()):
        notes.append("missing_provenance")
    if bm25["verdict"] != "ok":
        notes.append(f"bm25:{bm25['verdict']}")

    return {
        "status": "healthy" if not findings else "degraded",
        "project": project,
        "yaml_count": len(yaml_ids),
        "qdrant_count": len(qdrant_ids),
        "missing_from_qdrant": missing_from_qdrant,
        "missing_from_yaml": missing_from_yaml,
        "vector_health": vector_health,
        "graph": graph_stats,
        "provenance": provenance,
        "bm25": bm25,
        "findings": findings,
        "notes": notes,
    }
