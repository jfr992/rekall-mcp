"""Memory publish orchestration: filter → cluster → title → render.

Format-agnostic. The title function and renderer are injected so the pipeline
is testable without an LLM and reusable across export formats.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable

import networkx as nx

from memory.publish_types import Bundle, Concept

GROUPING_RELATIONS = frozenset(
    {"related_to", "led_to", "depends_on", "part_of", "supersedes"}
)
MAX_CLUSTER = 15  # ponytail: split at 15, tune if docs read badly


def _mid(m: dict) -> str:
    return m.get("memory_id") or m.get("id") or ""


def cluster_memories(memories: list[dict], graph) -> list[list[dict]]:
    """Group memories into concept clusters via graph connected components.

    Uses grouping relations only (excludes `contradicts` — a contradiction
    should keep two memories as separate concepts). Singletons form their own
    cluster. Components larger than MAX_CLUSTER split by memory type.
    """
    by_id = {_mid(m): m for m in memories if _mid(m)}
    g = nx.Graph()
    g.add_nodes_from(by_id)
    for s, t, data in graph._graph.edges(data=True):
        if data.get("relation") in GROUPING_RELATIONS and s in by_id and t in by_id:
            g.add_edge(s, t)

    clusters: list[list[dict]] = []
    for comp in nx.connected_components(g):
        members = [by_id[i] for i in comp]
        clusters.extend(_split_oversized(members))
    return clusters


def _split_oversized(members: list[dict]) -> list[list[dict]]:
    if len(members) <= MAX_CLUSTER:
        return [members]
    by_type: dict[str, list[dict]] = {}
    for m in members:
        by_type.setdefault(m.get("type", "note"), []).append(m)
    out: list[list[dict]] = []
    for group in by_type.values():
        for i in range(0, len(group), MAX_CLUSTER):
            out.append(group[i : i + MAX_CLUSTER])
    return out


_STOP = {"the", "a", "an", "and", "for", "to", "of", "in", "on", "is", "with"}


def cluster_key(cluster: list[dict]) -> str:
    ids = sorted(_mid(m) for m in cluster)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]


def slug_title(cluster: list[dict]) -> tuple[str, str]:
    """Deterministic (title, summary) from the longest-content member."""
    hub = max(cluster, key=lambda m: len(m.get("content", "")))
    words = re.findall(r"[A-Za-z0-9]+", hub.get("content", ""))
    keep = [w for w in words if w.lower() not in _STOP][:6] or ["memory"]
    return " ".join(keep), hub.get("content", "")[:120]


def _plausible(t) -> bool:
    return bool(
        isinstance(t, tuple) and len(t) == 2 and t[0] and 2 <= len(t[0]) <= 120
    )


def make_title_fn(
    cache: dict, judge: Callable[[list[dict]], tuple[str, str]] | None = None
) -> Callable[[list[dict]], tuple[str, str]]:
    """Return a title_fn that caches by cluster membership and falls back to slug."""

    def title_fn(cluster: list[dict]) -> tuple[str, str]:
        key = cluster_key(cluster)
        if key in cache:
            return tuple(cache[key])
        result = None
        if judge is not None:
            try:
                candidate = judge(cluster)
                if _plausible(candidate):
                    result = candidate
            except Exception:
                result = None
        if result is None:
            result = slug_title(cluster)
        cache[key] = list(result)
        return result

    return title_fn


_TYPE_MAP = {"learning": "runbook"}
_MIN_CONTENT = 40


def map_type(t: str) -> str:
    return _TYPE_MAP.get(t, t or "note")


def _keep(m: dict) -> bool:
    c = (m.get("content") or "").strip()
    if m.get("project") == "test-project":
        return False
    if m.get("type") == "note" and len(c) < _MIN_CONTENT:
        return False
    return bool(c)


def _dominant_type(cluster: list[dict]) -> str:
    counts: dict[str, int] = {}
    for m in cluster:
        counts[m.get("type", "note")] = counts.get(m.get("type", "note"), 0) + 1
    return max(counts, key=counts.get)


def _unique_slug(slug: str, used: set[str]) -> str:
    candidate, n = slug, 2
    while candidate in used:
        candidate = f"{slug}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _render_body(cluster, summary, graph, id_to_path, self_path) -> str:
    lines = [summary, ""]
    for m in cluster:
        lines.append(f"## {m.get('content', '').strip()}")
        meta = m.get("date") or (m.get("timestamp") or "")[:10]
        if meta:
            lines.append(f"_{meta}_")
        lines.append("")
    related: set[str] = set()
    for m in cluster:
        for e in graph.get_edges(_mid(m)):
            other = e.target if e.source == _mid(m) else e.source
            tgt = id_to_path.get(other)
            if tgt and tgt != self_path:
                related.add(tgt)
    if related:
        lines.append("## Related")
        for p in sorted(related):
            lines.append(f"- [/{p[:-3]}](/{p})")
        lines.append("")
    return "\n".join(lines)


def build_bundle(memories, graph, *, title_fn, renderer, project_hint=""):
    """Filter → cluster → title → render into a Bundle. Cross-cluster edges
    (including contradicts) surface as bundle-relative links in a Related section.
    """
    from memory.renderers.okf import slugify

    mems = [m for m in memories if _keep(m)]
    clusters = cluster_memories(mems, graph)

    # First pass: assign each cluster a path so cross-links can resolve.
    assigned: list[tuple[list[dict], str, tuple[str, str], str]] = []
    id_to_path: dict[str, str] = {}
    used: set[str] = set()
    for cluster in clusters:
        okf_type = map_type(_dominant_type(cluster))
        title, summary = title_fn(cluster)
        proj = cluster[0].get("project") or project_hint or "general"
        slug = _unique_slug(slugify(title), used)
        path = f"{proj}/{okf_type}s/{slug}.md"
        assigned.append((cluster, path, (title, summary), okf_type))
        for m in cluster:
            id_to_path[_mid(m)] = path

    concepts: list[Concept] = []
    for cluster, path, (title, summary), okf_type in assigned:
        body = _render_body(cluster, summary, graph, id_to_path, path)
        newest = max((m.get("timestamp") or m.get("date") or "") for m in cluster)
        proj = cluster[0].get("project") or project_hint or "general"
        fm = {
            "type": okf_type,
            "title": title,
            "tags": sorted({proj} | {m.get("type", "note") for m in cluster}),
        }
        if newest:
            fm["timestamp"] = newest
        concepts.append(Concept(path=path, frontmatter=fm, body=body))

    bundle = renderer.render(concepts)
    return Bundle(
        tree=bundle.tree,
        files=bundle.files,
        stats={**bundle.stats, "clusters": len(clusters)},
    )


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    try:
        path.write_text(json.dumps(cache, indent=0))
    except OSError:
        pass  # cache is best-effort; export must not fail on cache write


def _build_judge():
    model = os.getenv("MEMENTO_JUDGE_MODEL")
    if not model:
        return None, "slug"

    def judge(cluster):
        from memory.intelligence import summarize_cluster_title

        return summarize_cluster_title(cluster, model=model)

    return judge, "haiku"


def publish_from_manager(manager, *, project=None, fmt="okf") -> Bundle:
    """Build an export bundle from a MemoryManager. Loads memories + graph,
    manages the title cache on disk, and picks a judge if one is configured.
    """
    from memory.renderers import get_renderer

    filters = {"project": project} if project and project != "all" else None
    memories = manager.store.scroll(filters=filters, limit=10000)
    graph = manager.knowledge_graph

    cache_path = Path(manager.memory_dir) / "_publish_cache.json"
    cache = _load_cache(cache_path)
    judge, titled_by = _build_judge()
    title_fn = make_title_fn(cache, judge=judge)

    bundle = build_bundle(
        memories,
        graph,
        title_fn=title_fn,
        renderer=get_renderer(fmt),
        project_hint=project or "",
    )
    _save_cache(cache_path, cache)
    return Bundle(
        tree=bundle.tree,
        files=bundle.files,
        stats={**bundle.stats, "titled_by": titled_by},
    )
