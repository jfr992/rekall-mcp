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
    """Group memories into topic clusters via graph community detection.

    Uses grouping relations only (excludes `contradicts` — a contradiction
    should keep two memories as separate concepts). Greedy modularity finds
    sub-topics inside dense blobs where connected-components would return one
    giant group. Isolated memories fall out as singletons. Communities larger
    than MAX_CLUSTER split by memory type.
    """
    by_id = {_mid(m): m for m in memories if _mid(m)}
    g = nx.Graph()
    g.add_nodes_from(by_id)
    for s, t, data in graph._graph.edges(data=True):
        if data.get("relation") in GROUPING_RELATIONS and s in by_id and t in by_id:
            g.add_edge(s, t)

    clusters: list[list[dict]] = []
    for comp in nx.connected_components(g):
        sub = g.subgraph(comp)
        if sub.number_of_edges() == 0:
            clusters.append([by_id[i] for i in comp])
            continue
        for community in nx.community.greedy_modularity_communities(sub):
            members = [by_id[i] for i in community]
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


def _raw_brief(cluster: list[dict]) -> str:
    """Fallback body when synthesis is unavailable: memory contents as bullets."""
    return "\n".join(f"- {m.get('content', '').strip()}" for m in cluster)


def make_synthesis_fn(
    cache: dict, synth: Callable[[list[dict]], tuple[str, str]] | None = None
) -> Callable[[list[dict]], tuple[str, str]]:
    """Return a fn that distills a cluster into (title, brief).

    `synth` (LLM) is injected: when present and it returns a plausible result,
    that's the distilled knowledge brief. When absent or it errors, falls back
    to a slug title + raw memory contents so export always works keyless.
    Cached by cluster membership so preview == export and re-runs are free.
    """

    def synthesis_fn(cluster: list[dict]) -> tuple[str, str]:
        key = cluster_key(cluster)
        if key in cache:
            return tuple(cache[key])
        result = None
        if synth is not None:
            try:
                candidate = synth(cluster)
                if _plausible(candidate) and candidate[1]:
                    result = candidate
            except Exception:
                result = None
        if result is None:
            title, _ = slug_title(cluster)
            result = (title, _raw_brief(cluster))
        cache[key] = list(result)
        return result

    return synthesis_fn


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


def _render_body(cluster, brief, graph, id_to_path, self_path) -> str:
    """Body = the distilled brief, then a collapsed Sources list of the
    underlying memories, then cross-cluster Related links.
    """
    lines = [brief, ""]

    lines.append("## Sources")
    for m in cluster:
        meta = m.get("date") or (m.get("timestamp") or "")[:10]
        content = m.get("content", "").strip()
        suffix = f" _({meta})_" if meta else ""
        lines.append(f"- {content}{suffix}")
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


def build_bundle(memories, graph, *, synthesis_fn, renderer, project_hint=""):
    """Filter → cluster → synthesize → render into a Bundle. Each cluster
    becomes one concept: an LLM-distilled brief (or raw fallback) + a Sources
    list. Cross-cluster edges (incl. contradicts) surface as Related links.
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
        title, brief = synthesis_fn(cluster)
        proj = cluster[0].get("project") or project_hint or "general"
        slug = _unique_slug(slugify(title), used)
        path = f"{proj}/{okf_type}s/{slug}.md"
        assigned.append((cluster, path, (title, brief), okf_type))
        for m in cluster:
            id_to_path[_mid(m)] = path

    concepts: list[Concept] = []
    for cluster, path, (title, brief), okf_type in assigned:
        body = _render_body(cluster, brief, graph, id_to_path, path)
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


_SYNTH_PROMPT = (
    "You are distilling an engineer's raw memory notes into one durable knowledge "
    "brief. Below are {n} related notes. Write:\n"
    "1. A short title (3-8 words, no quotes).\n"
    "2. A tight 2-4 sentence brief capturing the durable knowledge — the decision, "
    "the root cause, the rule, or the runbook step. Synthesize; do not transcribe. "
    "Drop ticket noise and dates.\n\n"
    "Return exactly:\nTITLE: <title>\nBRIEF: <brief>\n\nNotes:\n{notes}"
)


def _parse_synth(text: str) -> tuple[str, str]:
    title, brief = "", ""
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title = line[len("TITLE:") :].strip()
        elif line.startswith("BRIEF:"):
            brief = line[len("BRIEF:") :].strip()
        elif brief and line.strip():
            brief += " " + line.strip()
    return title, brief


def _llm_complete(prompt: str, *, model: str, base_url: str, token: str) -> str:
    """POST to an Anthropic-compatible /v1/messages endpoint (works against the
    litellm proxy). Uses httpx directly — no anthropic SDK dependency.
    """
    import httpx

    resp = httpx.post(
        f"{base_url.rstrip('/')}/v1/messages",
        headers={"x-api-key": token, "anthropic-version": "2023-06-01"},
        json={
            "model": model,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _build_synth():
    """Return (synth_fn, mode). synth_fn distills a cluster into (title, brief)
    via an Anthropic-compatible endpoint (honors ANTHROPIC_BASE_URL/AUTH_TOKEN,
    including the litellm proxy). Returns (None, 'raw') when unconfigured.
    """
    model = os.getenv("MEMENTO_PUBLISH_MODEL") or os.getenv("ANTHROPIC_MODEL")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
    if not (model and base_url and token):
        return None, "raw"

    def synth(cluster):
        notes = "\n".join(f"- {m.get('content', '').strip()}" for m in cluster)
        prompt = _SYNTH_PROMPT.format(n=len(cluster), notes=notes)
        text = _llm_complete(prompt, model=model, base_url=base_url, token=token)
        return _parse_synth(text)

    return synth, "llm"


def prewarm_synthesis(clusters, cache, synth, workers=10, progress=None) -> None:
    """Populate the synthesis cache concurrently. Fans LLM calls out over a
    bounded thread pool. `progress(done, total)` fires after each completion.
    Uncached-on-error clusters fall back to raw in build_bundle.
    """
    if synth is None:
        return
    from concurrent.futures import ThreadPoolExecutor

    todo = [c for c in clusters if cluster_key(c) not in cache]
    total = len(todo)
    if not total:
        if progress:
            progress(0, 0)
        return

    def _one(cluster):
        try:
            result = synth(cluster)
            if _plausible(result) and result[1]:
                return cluster_key(cluster), list(result)
        except Exception:
            return None
        return None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for outcome in pool.map(_one, todo):
            if outcome:
                key, value = outcome
                cache[key] = value
            done += 1
            if progress:
                progress(done, total)


def publish_from_manager(
    manager, *, project=None, fmt="okf", synthesize=False, progress=None
) -> Bundle:
    """Build an export bundle from a MemoryManager.

    synthesize=False (default): fast, keyless — raw briefs, no LLM. Cached
    syntheses from a prior run are still used if present. This is the preview
    path and never blocks on the LLM.

    synthesize=True: warm the cache with LLM-distilled briefs first (concurrent,
    `progress(done, total)` callback), then build. Use off the request hot path
    (background job / download), never inline in an async handler.
    """
    from memory.renderers import get_renderer

    filters = {"project": project} if project and project != "all" else None
    memories = manager.store.scroll(filters=filters, limit=10000)
    graph = manager.knowledge_graph

    cache_path = Path(manager.memory_dir) / "_publish_cache.json"
    cache = _load_cache(cache_path)
    synth, mode = _build_synth()

    if synthesize and synth is not None:
        mems = [m for m in memories if _keep(m)]
        prewarm_synthesis(cluster_memories(mems, graph), cache, synth, progress=progress)
    else:
        mode = "cached" if cache else "raw"

    # build_bundle only reads the cache — it never triggers new LLM calls here.
    synthesis_fn = make_synthesis_fn(cache, synth=None)

    bundle = build_bundle(
        memories,
        graph,
        synthesis_fn=synthesis_fn,
        renderer=get_renderer(fmt),
        project_hint=project or "",
    )
    _save_cache(cache_path, cache)
    return Bundle(
        tree=bundle.tree,
        files=bundle.files,
        stats={**bundle.stats, "synthesized": mode},
    )
