# OKF Publish Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (subagents are failing this session due to auth — execute inline). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export Memento memory (per-project or all) to a conformant OKF v0.1 markdown bundle, surfaced via REST endpoint, MCP tool, Claude Code skill, and a `/kb` cockpit tab.

**Architecture:** A format-agnostic orchestrator (`src/memory/publish.py`) filters memories, clusters them via graph connected components, and titles each cluster through an injected `title_fn` (cached Haiku with deterministic slug fallback). It hands clusters to an injected renderer (`src/memory/renderers/okf.py`) that emits OKF concept docs. The endpoint/tool/skill/UI are thin callers of `build_bundle`.

**Tech Stack:** Python 3.11+, networkx, PyYAML, Starlette (custom routes), FastMCP tools, Next.js 15 + TanStack Query + Zod (UI), pytest + vitest.

## Global Constraints

- Python `>=3.11`; no new runtime dependencies (networkx, pyyaml already present).
- Export is **read-only** on memory storage — never mutates YAML/Qdrant/graph.
- Keyless operation must work: `title_fn` falls back to deterministic slug when no LLM.
- Preview output MUST equal export output for the same memory state (title cache).
- Write path (`mode=dir`) confined to `MEMENTO_PUBLISH_DIR` (default `~/.claude/publish`); reject paths escaping it.
- OKF v0.1 conformance: every non-reserved `.md` has parseable frontmatter with non-empty `type`; `index.md`/`log.md` reserved; cross-links bundle-relative (`/…`).
- Work on branch `feat/okf-publish`. Keep `scripts/digest.py`.
- Files stay under 800 lines; `publish.py` ~200, `renderers/okf.py` ~150.

---

### Task 1: Bundle data types + renderer package skeleton

**Files:**
- Create: `src/memory/renderers/__init__.py`
- Create: `src/memory/publish_types.py`
- Test: `tests/test_publish_types.py`

**Interfaces:**
- Produces: `Bundle` dataclass `{tree: list[str], files: dict[str, str], stats: dict}`; `Concept` dataclass `{path: str, frontmatter: dict, body: str}`; `get_renderer(fmt: str) -> Renderer` raising `ValueError` on unknown.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_types.py
import pytest
from memory.publish_types import Bundle, Concept


def test_bundle_holds_tree_files_stats():
    b = Bundle(tree=["a/b.md"], files={"a/b.md": "x"}, stats={"concepts": 1})
    assert b.tree == ["a/b.md"]
    assert b.files["a/b.md"] == "x"
    assert b.stats["concepts"] == 1


def test_concept_defaults_empty():
    c = Concept(path="t/x.md", frontmatter={"type": "note"}, body="hello")
    assert c.frontmatter["type"] == "note"


def test_get_renderer_unknown_raises():
    from memory.renderers import get_renderer
    with pytest.raises(ValueError):
        get_renderer("nonesuch")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_publish_types.py -v`
Expected: FAIL (ModuleNotFoundError: memory.publish_types)

- [ ] **Step 3: Write minimal implementation**

```python
# src/memory/publish_types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Concept:
    path: str                      # bundle-relative, ends with .md
    frontmatter: dict[str, Any]    # MUST include non-empty "type"
    body: str


@dataclass(frozen=True, slots=True)
class Bundle:
    tree: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


class Renderer(Protocol):
    def render(self, concepts: list[Concept]) -> Bundle: ...
```

```python
# src/memory/renderers/__init__.py
from __future__ import annotations

from memory.publish_types import Renderer


def get_renderer(fmt: str) -> Renderer:
    if fmt == "okf":
        from memory.renderers.okf import OkfRenderer

        return OkfRenderer()
    raise ValueError(f"Unknown export format: {fmt}")
```

- [ ] **Step 4: Run tests** — Run: `uv run --extra dev pytest tests/test_publish_types.py -v` — Expected: 2 pass, `test_get_renderer_unknown_raises` still fails (okf not built).

- [ ] **Step 5: Stub the renderer so the import resolves**

```python
# src/memory/renderers/okf.py
from __future__ import annotations

from memory.publish_types import Bundle, Concept


class OkfRenderer:
    def render(self, concepts: list[Concept]) -> Bundle:
        return Bundle()
```

- [ ] **Step 6: Run tests** — Expected: 3 pass.

- [ ] **Step 7: Commit**

```bash
git add src/memory/publish_types.py src/memory/renderers/ tests/test_publish_types.py
git commit -m "feat(publish): bundle/concept types + renderer registry"
```

---

### Task 2: Clustering — connected components, exclude contradicts, cap at 15

**Files:**
- Create: `src/memory/publish.py`
- Test: `tests/test_publish_clustering.py`

**Interfaces:**
- Consumes: `KnowledgeGraph` (has `._graph` networkx DiGraph with edges carrying `relation`).
- Produces: `cluster_memories(memories: list[dict], graph) -> list[list[dict]]`. `memories` are dicts with at least `memory_id`/`id`. Groups by connected components over grouping relations (`related_to`, `led_to`, `depends_on`, `part_of`, `supersedes`); excludes `contradicts`; singletons become one-element clusters; components larger than `MAX_CLUSTER=15` split by memory `type`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_clustering.py
import networkx as nx
from memory.publish import cluster_memories


class FakeGraph:
    def __init__(self, edges):
        self._graph = nx.DiGraph()
        for s, t, rel in edges:
            self._graph.add_edge(s, t, relation=rel)


def _mem(mid, mtype="learning"):
    return {"memory_id": mid, "type": mtype, "content": f"c-{mid}"}


def test_related_memories_cluster_together():
    mems = [_mem("a"), _mem("b"), _mem("c")]
    g = FakeGraph([("a", "b", "related_to"), ("b", "c", "led_to")])
    clusters = cluster_memories(mems, g)
    assert len(clusters) == 1
    assert {m["memory_id"] for m in clusters[0]} == {"a", "b", "c"}


def test_contradicts_does_not_merge():
    mems = [_mem("a"), _mem("b")]
    g = FakeGraph([("a", "b", "contradicts")])
    clusters = cluster_memories(mems, g)
    assert len(clusters) == 2


def test_singleton_is_own_cluster():
    mems = [_mem("a"), _mem("b"), _mem("c")]
    g = FakeGraph([("a", "b", "related_to")])
    clusters = cluster_memories(mems, g)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_oversized_cluster_splits_by_type():
    mems = [_mem(str(i), "learning") for i in range(20)]
    # chain them all into one giant component
    edges = [(str(i), str(i + 1), "related_to") for i in range(19)]
    g = FakeGraph(edges)
    clusters = cluster_memories(mems, g)
    assert all(len(c) <= 15 for c in clusters)
```

- [ ] **Step 2: Run test** — Run: `uv run --extra dev pytest tests/test_publish_clustering.py -v` — Expected: FAIL (cannot import cluster_memories).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memory/publish.py
from __future__ import annotations

import networkx as nx

GROUPING_RELATIONS = frozenset(
    {"related_to", "led_to", "depends_on", "part_of", "supersedes"}
)
MAX_CLUSTER = 15  # ponytail: split at 15, tune if docs read badly


def _mid(m: dict) -> str:
    return m.get("memory_id") or m.get("id") or ""


def cluster_memories(memories: list[dict], graph) -> list[list[dict]]:
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
```

- [ ] **Step 4: Run tests** — Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/publish.py tests/test_publish_clustering.py
git commit -m "feat(publish): graph-component clustering, excl contradicts, cap 15"
```

---

### Task 3: Titling — cached title_fn with slug fallback

**Files:**
- Modify: `src/memory/publish.py`
- Test: `tests/test_publish_titling.py`

**Interfaces:**
- Produces: `slug_title(cluster: list[dict]) -> tuple[str, str]` returning `(title, summary)` from the highest-degree/first member, deterministic. `make_title_fn(cache: dict, judge=None) -> Callable[[list[dict]], tuple[str, str]]` — wraps a `judge` callable (Haiku); caches by member-id-set hash; falls back to `slug_title` when `judge` is None or returns implausible output. `cluster_key(cluster) -> str` stable hash of sorted member ids.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_titling.py
from memory.publish import slug_title, make_title_fn, cluster_key


def _mem(mid, content):
    return {"memory_id": mid, "type": "learning", "content": content}


def test_slug_title_deterministic():
    c = [_mem("a", "KubeVirt namespace recovery recipe for stuck ns")]
    t1 = slug_title(c)
    t2 = slug_title(c)
    assert t1 == t2
    assert t1[0]  # non-empty title


def test_cluster_key_order_independent():
    a = [_mem("x", "1"), _mem("y", "2")]
    b = [_mem("y", "2"), _mem("x", "1")]
    assert cluster_key(a) == cluster_key(b)


def test_title_fn_uses_cache():
    calls = []

    def judge(cluster):
        calls.append(1)
        return ("Judged Title", "summary")

    cache = {}
    fn = make_title_fn(cache, judge=judge)
    c = [_mem("a", "content")]
    first = fn(c)
    second = fn(c)
    assert first == ("Judged Title", "summary")
    assert second == first
    assert len(calls) == 1  # cached second time


def test_title_fn_falls_back_when_no_judge():
    fn = make_title_fn({}, judge=None)
    title, _ = fn([_mem("a", "some memory content here")])
    assert title


def test_title_fn_falls_back_on_implausible_judge():
    fn = make_title_fn({}, judge=lambda c: ("", ""))  # empty -> implausible
    title, _ = fn([_mem("a", "real content")])
    assert title  # slug used instead
```

- [ ] **Step 2: Run test** — Expected: FAIL (import errors).

- [ ] **Step 3: Write minimal implementation** (append to `src/memory/publish.py`)

```python
import hashlib
import re
from typing import Callable

_STOP = {"the", "a", "an", "and", "for", "to", "of", "in", "on", "is", "with"}


def cluster_key(cluster: list[dict]) -> str:
    ids = sorted(_mid(m) for m in cluster)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]


def slug_title(cluster: list[dict]) -> tuple[str, str]:
    hub = max(cluster, key=lambda m: len(m.get("content", "")))
    words = [w for w in re.findall(r"[A-Za-z0-9]+", hub.get("content", ""))]
    keep = [w for w in words if w.lower() not in _STOP][:6] or ["memory"]
    title = " ".join(keep)
    summary = hub.get("content", "")[:120]
    return title, summary


def _plausible(t: tuple) -> bool:
    return bool(t and isinstance(t, tuple) and len(t) == 2 and t[0] and 2 <= len(t[0]) <= 120)


def make_title_fn(
    cache: dict, judge: Callable[[list[dict]], tuple[str, str]] | None = None
) -> Callable[[list[dict]], tuple[str, str]]:
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
```

- [ ] **Step 4: Run tests** — Expected: 5 pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/publish.py tests/test_publish_titling.py
git commit -m "feat(publish): cached title_fn with deterministic slug fallback"
```

---

### Task 4: OKF renderer — conformant concept docs

**Files:**
- Modify: `src/memory/renderers/okf.py`
- Test: `tests/test_renderer_okf.py`

**Interfaces:**
- Consumes: `Concept`, `Bundle` from `publish_types`.
- Produces: `OkfRenderer.render(concepts: list[Concept]) -> Bundle` — emits one `.md` per concept with YAML frontmatter (non-empty `type`) + body; adds a per-directory `index.md`; `tree` lists all paths sorted; `stats` includes `concepts`. `slugify(text) -> str` for filenames.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_renderer_okf.py
import yaml
from memory.publish_types import Concept
from memory.renderers.okf import OkfRenderer, slugify


def _c(path, mtype="runbook", body="hello"):
    return Concept(path=path, frontmatter={"type": mtype, "title": "T"}, body=body)


def test_every_concept_has_nonempty_type_frontmatter():
    b = OkfRenderer().render([_c("byte-edge/runbooks/x.md")])
    content = b.files["byte-edge/runbooks/x.md"]
    assert content.startswith("---\n")
    fm = yaml.safe_load(content.split("---\n")[1])
    assert fm["type"] == "runbook"
    assert fm["type"]  # non-empty


def test_reserved_names_not_used_for_concepts():
    b = OkfRenderer().render([_c("a/b.md")])
    # generated index.md exists but is not a concept we passed
    assert "a/index.md" in b.files or "index.md" in b.files


def test_slugify_stable_and_safe():
    assert slugify("KubeVirt namespace recovery!") == "kubevirt-namespace-recovery"
    assert slugify("a/b c") == "a-b-c"


def test_tree_lists_all_files_sorted():
    b = OkfRenderer().render([_c("z/a.md"), _c("a/b.md")])
    assert b.tree == sorted(b.tree)
    assert "z/a.md" in b.tree and "a/b.md" in b.tree


def test_stats_reports_concept_count():
    b = OkfRenderer().render([_c("a/b.md"), _c("a/c.md")])
    assert b.stats["concepts"] == 2
```

- [ ] **Step 2: Run test** — Expected: FAIL (slugify/render not implemented).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memory/renderers/okf.py
from __future__ import annotations

import re

import yaml

from memory.publish_types import Bundle, Concept

_RESERVED = {"index.md", "log.md"}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "concept"


def _emit(concept: Concept) -> str:
    fm = dict(concept.frontmatter)
    assert fm.get("type"), "OKF concept requires non-empty type"
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{front}\n---\n{concept.body}\n"


class OkfRenderer:
    def render(self, concepts: list[Concept]) -> Bundle:
        files: dict[str, str] = {}
        dirs: dict[str, list[str]] = {}
        for c in concepts:
            assert c.path.rsplit("/", 1)[-1] not in _RESERVED
            files[c.path] = _emit(c)
            d = c.path.rsplit("/", 1)[0] if "/" in c.path else ""
            dirs.setdefault(d, []).append(c.path)

        for d, paths in dirs.items():
            idx = f"{d}/index.md" if d else "index.md"
            listing = "\n".join(f"- [/{p[:-3]}](/{p})" for p in sorted(paths))
            files[idx] = f"---\ntype: index\n---\n# {d or 'root'}\n\n{listing}\n"

        tree = sorted(files)
        return Bundle(tree=tree, files=files, stats={"concepts": len(concepts)})
```

- [ ] **Step 4: Run tests** — Expected: 5 pass. Also run `tests/test_publish_types.py::test_get_renderer_unknown_raises` neighbors to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add src/memory/renderers/okf.py tests/test_renderer_okf.py
git commit -m "feat(publish): OKF v0.1 renderer — conformant concept docs + index"
```

---

### Task 5: build_bundle orchestration — concept assembly + cross-links

**Files:**
- Modify: `src/memory/publish.py`
- Test: `tests/test_publish_build.py`

**Interfaces:**
- Consumes: `cluster_memories`, `make_title_fn`, `get_renderer`, `Concept`.
- Produces: `build_bundle(memories, graph, *, title_fn, renderer, project_hint="") -> Bundle`. Filters out sub-40-char `note`/empty content and `test-project`. Builds one `Concept` per cluster: `type` = OKF-mapped dominant member type, `title`/summary from `title_fn`, body = member contents as `##` sections, plus a `## Related` block with bundle-relative links for cross-cluster + `contradicts` edges. Concept path = `<project>/<okf_type>s/<slug>.md`. `map_type(t) -> str` (`learning`→`runbook`, else identity).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_build.py
import networkx as nx
from memory.publish import build_bundle, make_title_fn, map_type
from memory.renderers import get_renderer


class FakeGraph:
    def __init__(self, edges):
        self._graph = nx.DiGraph()
        for s, t, rel in edges:
            self._graph.add_edge(s, t, relation=rel, weight=0.6)

    def get_edges(self, mid, direction="both"):
        out = []
        for s, t, d in self._graph.edges(data=True):
            if s == mid or t == mid:
                out.append(type("E", (), {"source": s, "target": t, "relation": d["relation"]}))
        return out


def _mem(mid, content, project="byte-edge", mtype="learning"):
    return {"memory_id": mid, "content": content, "project": project, "type": mtype}


def test_build_bundle_produces_concepts():
    mems = [_mem("a", "KubeVirt stuck namespace recovery recipe long enough")]
    g = FakeGraph([])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    assert b.stats["concepts"] >= 1
    assert any(p.endswith(".md") and "index" not in p for p in b.tree)


def test_map_type_learning_to_runbook():
    assert map_type("learning") == "runbook"
    assert map_type("decision") == "decision"


def test_short_notes_filtered_out():
    mems = [_mem("a", "hi", mtype="note"), _mem("b", "a genuinely long useful learning here")]
    g = FakeGraph([])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    joined = "\n".join(b.files.values())
    assert "genuinely long useful" in joined
    assert "\n## hi\n" not in joined


def test_contradicts_becomes_related_link():
    mems = [_mem("a", "we should use approach X for the thing"),
            _mem("b", "we should NOT use approach X for the thing")]
    g = FakeGraph([("a", "b", "contradicts")])
    b = build_bundle(mems, g, title_fn=make_title_fn({}), renderer=get_renderer("okf"))
    joined = "\n".join(b.files.values())
    assert "## Related" in joined or "## Conflicts" in joined
```

- [ ] **Step 2: Run test** — Expected: FAIL.

- [ ] **Step 3: Write minimal implementation** (append to `src/memory/publish.py`)

```python
from memory.publish_types import Bundle, Concept

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


def build_bundle(memories, graph, *, title_fn, renderer, project_hint=""):
    mems = [m for m in memories if _keep(m)]
    clusters = cluster_memories(mems, graph)

    # first pass: assign each cluster a path so cross-links can resolve
    assigned: list[tuple[list[dict], str, tuple[str, str]]] = []
    id_to_path: dict[str, str] = {}
    used: set[str] = set()
    for cluster in clusters:
        okf_type = map_type(_dominant_type(cluster))
        title, summary = title_fn(cluster)
        proj = cluster[0].get("project") or project_hint or "general"
        slug = _unique_slug(slug_title_slug(title), used)
        path = f"{proj}/{okf_type}s/{slug}.md"
        assigned.append((cluster, path, (title, summary)))
        for m in cluster:
            id_to_path[_mid(m)] = path

    concepts: list[Concept] = []
    for cluster, path, (title, summary) in assigned:
        body = _render_body(cluster, summary, graph, id_to_path, path)
        okf_type = map_type(_dominant_type(cluster))
        newest = max((m.get("timestamp") or m.get("date") or "") for m in cluster)
        proj = cluster[0].get("project") or project_hint or "general"
        fm = {"type": okf_type, "title": title,
              "tags": sorted({proj} | {m.get("type", "note") for m in cluster})}
        if newest:
            fm["timestamp"] = newest
        concepts.append(Concept(path=path, frontmatter=fm, body=body))

    bundle = renderer.render(concepts)
    return Bundle(tree=bundle.tree, files=bundle.files,
                  stats={**bundle.stats, "clusters": len(clusters)})


def slug_title_slug(title: str) -> str:
    from memory.renderers.okf import slugify
    return slugify(title)


def _unique_slug(slug: str, used: set[str]) -> str:
    candidate = slug
    n = 2
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
```

- [ ] **Step 4: Run tests** — Run: `uv run --extra dev pytest tests/test_publish_build.py tests/test_publish_clustering.py tests/test_publish_titling.py -v` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/publish.py tests/test_publish_build.py
git commit -m "feat(publish): build_bundle orchestration + cross-links"
```

---

### Task 6: Manager-facing publish + real Haiku judge wiring

**Files:**
- Modify: `src/memory/publish.py`
- Test: `tests/test_publish_manager.py`

**Interfaces:**
- Consumes: `MemoryManager` (`.store.scroll(filters, limit)`, `.knowledge_graph`, `.memory_dir`).
- Produces: `publish_from_manager(manager, *, project=None, fmt="okf") -> Bundle`. Loads memories via `store.scroll`, loads graph, loads/saves title cache at `manager.memory_dir/_publish_cache.json`, builds a Haiku judge only if `MEMENTO_JUDGE_MODEL`/key available else `None`, calls `build_bundle`. Sets `stats["titled_by"]` = `"haiku"|"slug"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_manager.py
import networkx as nx
from memory.publish import publish_from_manager


class FakeGraph:
    def __init__(self):
        self._graph = nx.DiGraph()

    def get_edges(self, mid, direction="both"):
        return []


class FakeStore:
    def scroll(self, filters=None, limit=100, with_vectors=False):
        return [{"memory_id": "a", "content": "a long useful learning about pods", "project": "p", "type": "learning"}]


class FakeManager:
    def __init__(self, tmp):
        self.store = FakeStore()
        self.knowledge_graph = FakeGraph()
        self.memory_dir = tmp


def test_publish_from_manager_slug_when_no_judge(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMENTO_JUDGE_MODEL", raising=False)
    b = publish_from_manager(FakeManager(tmp_path))
    assert b.stats["titled_by"] == "slug"
    assert b.stats["concepts"] >= 1


def test_publish_writes_and_reuses_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMENTO_JUDGE_MODEL", raising=False)
    publish_from_manager(FakeManager(tmp_path))
    assert (tmp_path / "_publish_cache.json").exists()
```

- [ ] **Step 2: Run test** — Expected: FAIL.

- [ ] **Step 3: Write minimal implementation** (append to `src/memory/publish.py`)

```python
import json
import os
from pathlib import Path


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
        # ponytail: reuse the observe-hook Haiku path; stubbed callable here.
        from memory.intelligence import summarize_cluster_title  # thin helper
        return summarize_cluster_title(cluster, model=model)

    return judge, "haiku"


def publish_from_manager(manager, *, project=None, fmt="okf") -> Bundle:
    from memory.renderers import get_renderer

    filters = {"project": project} if project and project != "all" else None
    memories = manager.store.scroll(filters=filters, limit=10000)
    graph = manager.knowledge_graph

    cache_path = Path(manager.memory_dir) / "_publish_cache.json"
    cache = _load_cache(cache_path)
    judge, titled_by = _build_judge()
    title_fn = make_title_fn(cache, judge=judge)

    bundle = build_bundle(memories, graph, title_fn=title_fn,
                          renderer=get_renderer(fmt), project_hint=project or "")
    _save_cache(cache_path, cache)
    return Bundle(tree=bundle.tree, files=bundle.files,
                  stats={**bundle.stats, "titled_by": titled_by})
```

Note: `summarize_cluster_title` is only imported when a judge is active; add a minimal helper to `src/memory/intelligence.py` in this task:

```python
# append to src/memory/intelligence.py
def summarize_cluster_title(cluster: list[dict], *, model: str) -> tuple[str, str]:
    """Ask the judge model for a (title, summary). Falls back handled by caller."""
    # Implementation calls the same Haiku path as the observe hook.
    # For now, raise so make_title_fn's guard uses slug until wired to the LLM client.
    raise NotImplementedError("wire to LLM client in a follow-up step")
```

(Guarded: `make_title_fn` catches the exception → slug. Real LLM wiring is a later, isolated step — export works keyless today.)

- [ ] **Step 4: Run tests** — Run: `uv run --extra dev pytest tests/test_publish_manager.py -v` — Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/publish.py src/memory/intelligence.py tests/test_publish_manager.py
git commit -m "feat(publish): manager entrypoint + cache + judge seam"
```

---

### Task 7: REST endpoint /api/memory/publish

**Files:**
- Modify: `src/server.py` (add route near other `/api/memory/*` routes; add `_publish_bundle_bytes` helper)
- Test: `tests/test_server_publish.py`

**Interfaces:**
- Consumes: `publish_from_manager`, `_get_memory_manager`, `_safe_project`, `_ok`, `_bad_request`, `_server_error`.
- Produces: `GET/POST /api/memory/publish` with `project`, `format` (default `okf`), `mode` (`preview`|`tar`|`dir`), `dest`. `preview`→JSON, `tar`→gzip StreamingResponse, `dir`→writes under `MEMENTO_PUBLISH_DIR` (default `~/.claude/publish`), traversal-guarded.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_publish.py
import gzip
from starlette.testclient import TestClient
from server import app  # adjust import to match existing test_server_* pattern


def _client():
    return TestClient(app)


def test_preview_returns_tree_files_stats():
    r = _client().get("/api/memory/publish?project=nonexistent-xyz&mode=preview")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"tree", "files", "stats"}


def test_unknown_project_is_empty_not_error():
    r = _client().get("/api/memory/publish?project=nonexistent-xyz")
    assert r.status_code == 200
    assert r.json()["stats"]["concepts"] == 0


def test_dir_mode_rejects_traversal():
    r = _client().get("/api/memory/publish?mode=dir&dest=/etc/passwd")
    assert r.status_code == 400


def test_tar_mode_returns_gzip():
    r = _client().get("/api/memory/publish?project=nonexistent-xyz&mode=tar")
    assert r.status_code == 200
    assert r.content[:2] == b"\x1f\x8b"  # gzip magic
```

- [ ] **Step 2: Run test** — Expected: FAIL (404 no route).

- [ ] **Step 3: Write minimal implementation** (add to `src/server.py`)

```python
@mcp.custom_route("/api/memory/publish", methods=["GET", "POST"])
async def api_memory_publish(request):
    import io
    import os
    import tarfile
    from pathlib import Path

    from starlette.responses import Response

    from memory.publish import publish_from_manager

    try:
        q = request.query_params
        project = _safe_project(q.get("project"))
        fmt = q.get("format", "okf")
        mode = q.get("mode", "preview")

        manager = _get_memory_manager()
        try:
            bundle = publish_from_manager(manager, project=project, fmt=fmt)
        except ValueError as e:
            return _bad_request(str(e))

        if mode == "preview":
            return _ok({"tree": bundle.tree, "files": bundle.files, "stats": bundle.stats})

        if mode == "tar":
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for path, content in bundle.files.items():
                    data = content.encode()
                    info = tarfile.TarInfo(name=path)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            buf.seek(0)
            return Response(
                buf.read(),
                media_type="application/gzip",
                headers={"Content-Disposition": 'attachment; filename="okf-bundle.tar.gz"'},
            )

        if mode == "dir":
            base = Path(os.getenv("MEMENTO_PUBLISH_DIR", os.path.expanduser("~/.claude/publish"))).resolve()
            dest = q.get("dest")
            if not dest:
                return _bad_request("dest required for mode=dir")
            target = (base / dest).resolve() if not os.path.isabs(dest) else Path(dest).resolve()
            if base != target and base not in target.parents:
                return _bad_request("dest must be within MEMENTO_PUBLISH_DIR")
            tmp = target.with_suffix(".tmp")
            for path, content in bundle.files.items():
                fp = tmp / path
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content)
            if target.exists():
                import shutil
                shutil.rmtree(target)
            tmp.rename(target)
            return _ok({"written": len(bundle.files), "path": str(target)})

        return _bad_request(f"unknown mode: {mode}")
    except Exception as e:
        logger.error(f"Error building publish bundle: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Run tests** — Run: `uv run --extra dev pytest tests/test_server_publish.py -v` — Expected: 4 pass. (These are unit-level — use the existing `test_server_*` app import pattern; if they need Qdrant, mark `@pytest.mark.integration` per repo convention and assert against a mocked manager instead.)

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_server_publish.py
git commit -m "feat(publish): /api/memory/publish endpoint (preview/tar/dir)"
```

---

### Task 8: MCP tool publish_memory

**Files:**
- Modify: `src/tools/builtin/memory.py` (add tool method in the provider class alongside `observe`/`recall`)
- Test: `tests/test_publish_tool.py`

**Interfaces:**
- Consumes: `self.manager`, `publish_from_manager`.
- Produces: `@mcp.tool() async def publish_memory(project=None, format="okf") -> str` returning the tree + stats as readable text. (Preview-shaped; tar/dir stay endpoint-only for v1 per spec — tool returns the tree and tells the user to use the endpoint/UI for download.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish_tool.py
from memory.publish import publish_from_manager
import networkx as nx


class FakeGraph:
    def __init__(self):
        self._graph = nx.DiGraph()

    def get_edges(self, mid, direction="both"):
        return []


class FakeStore:
    def scroll(self, filters=None, limit=100, with_vectors=False):
        return [{"memory_id": "a", "content": "a useful long learning about pods here", "project": "p", "type": "learning"}]


class FakeManager:
    def __init__(self, tmp):
        self.store = FakeStore()
        self.knowledge_graph = FakeGraph()
        self.memory_dir = tmp


def test_publish_from_manager_text_summary(tmp_path):
    # tool formats this bundle; assert the underlying data is present
    b = publish_from_manager(FakeManager(tmp_path))
    assert b.tree
    assert b.stats["concepts"] >= 1
```

- [ ] **Step 2: Run test** — Expected: PASS for the data layer (the tool is a thin formatter; this guards the contract it formats).

- [ ] **Step 3: Add the tool** (inside the provider class in `src/tools/builtin/memory.py`, mirroring the `observe` tool registration)

```python
        @mcp.tool(structured_output=False)
        async def publish_memory(project: str | None = None, format: str = "okf") -> str:
            """Use when exporting memory to a shareable knowledge bundle (OKF markdown).

            Builds an OKF v0.1 bundle from memory (one project or all) and returns
            the file tree. For a downloadable .tar.gz or writing to disk, use the
            /api/memory/publish endpoint or the cockpit Export tab.
            """
            from memory.publish import publish_from_manager

            bundle = publish_from_manager(self.manager, project=project, fmt=format)
            lines = [f"OKF bundle — {bundle.stats.get('concepts', 0)} concepts, "
                     f"{bundle.stats.get('clusters', 0)} clusters, "
                     f"titled by {bundle.stats.get('titled_by', 'slug')}", ""]
            lines += bundle.tree
            return "\n".join(lines)
```

- [ ] **Step 4: Run tests** — Run: `uv run --extra dev pytest tests/test_publish_tool.py -v` — Expected: pass. Also run the full backend suite: `uv run --extra dev pytest -m "not integration" -q`.

- [ ] **Step 5: Commit**

```bash
git add src/tools/builtin/memory.py tests/test_publish_tool.py
git commit -m "feat(publish): publish_memory MCP tool"
```

---

### Task 9: Claude Code skill memento-publish

**Files:**
- Create: `claude/skills/memento-publish/SKILL.md`

**Interfaces:**
- Consumes: the `publish_memory` MCP tool (namespace `mcp__<server>__publish_memory`).
- Produces: a thin trigger skill.

- [ ] **Step 1: Write the skill file**

```markdown
---
name: memento-publish
description: Use when the user wants to export or publish memory to an OKF (Open Knowledge Format) bundle — shareable markdown knowledge docs.
---

# Publish memory to an OKF bundle

When the user asks to export, publish, or share their memory as a knowledge bundle:

1. Call the `publish_memory` MCP tool (project-scoped if the user named a project, else all memory).
2. Show the returned file tree.
3. Tell the user: for a downloadable `.tar.gz`, use the cockpit Knowledge → Export OKF tab, or `GET /api/memory/publish?mode=tar`; to write files to disk, `GET /api/memory/publish?mode=dir&dest=<name>` (writes under `MEMENTO_PUBLISH_DIR`, default `~/.claude/publish`).

Namespace note: the tool is `mcp__<server>__publish_memory` where `<server>` is
the MCP server name in the user's Claude Code config (`memento` if installed per
the repo's config; `memory` if added via the README's `claude mcp add ... memory`).
```

- [ ] **Step 2: Verify frontmatter parses** — Run: `uv run python -c "import yaml,io; d=open('claude/skills/memento-publish/SKILL.md').read(); print(yaml.safe_load(d.split('---')[1]))"` — Expected: dict with `name`, `description`.

- [ ] **Step 3: Commit**

```bash
git add claude/skills/memento-publish/SKILL.md
git commit -m "feat(publish): memento-publish Claude Code skill"
```

---

### Task 10: UI — schema, api client, query hook

**Files:**
- Modify: `ui/lib/schemas.ts` (add `PublishResponseSchema`)
- Create: `ui/lib/api/publish.ts`
- Create: `ui/lib/queries/use-publish.ts`
- Test: `ui/tests/publish-api.test.ts`

**Interfaces:**
- Produces: `PublishResponse` type; `getPublishPreview(project: string)`; `downloadBundle(project: string)`; `usePublish(project, enabled)` TanStack hook.

- [ ] **Step 1: Write the failing test**

```typescript
// ui/tests/publish-api.test.ts
import { describe, it, expect } from "vitest";
import { PublishResponseSchema } from "@/lib/schemas";

describe("PublishResponseSchema", () => {
  it("parses a valid publish response", () => {
    const ok = PublishResponseSchema.parse({
      tree: ["a/b.md"],
      files: { "a/b.md": "---\ntype: runbook\n---\nx" },
      stats: { concepts: 1, clusters: 1, titled_by: "slug" },
    });
    expect(ok.tree.length).toBe(1);
  });

  it("rejects missing tree", () => {
    expect(() => PublishResponseSchema.parse({ files: {}, stats: {} })).toThrow();
  });
});
```

- [ ] **Step 2: Run test** — Run: `cd ui && npx vitest run tests/publish-api.test.ts` — Expected: FAIL (schema undefined).

- [ ] **Step 3: Implement**

```typescript
// add to ui/lib/schemas.ts
export const PublishResponseSchema = z.object({
  tree: z.array(z.string()),
  files: z.record(z.string(), z.string()),
  stats: z.object({
    concepts: z.number(),
    clusters: z.number().optional(),
    titled_by: z.string().optional(),
  }).passthrough(),
});
export type PublishResponse = z.infer<typeof PublishResponseSchema>;
```

```typescript
// ui/lib/api/publish.ts
import { fetchJson } from "./client";
import { PublishResponseSchema } from "@/lib/schemas";

export async function getPublishPreview(project: string) {
  const qs = new URLSearchParams(project ? { project } : {});
  return fetchJson(`/api/memory/publish?${qs}`, undefined, (d) => PublishResponseSchema.parse(d));
}

export function downloadBundleUrl(project: string): string {
  const qs = new URLSearchParams({ mode: "tar", ...(project ? { project } : {}) });
  return `/api/memory/publish?${qs}`;
}
```

```typescript
// ui/lib/queries/use-publish.ts
import { useQuery } from "@tanstack/react-query";
import { getPublishPreview } from "@/lib/api/publish";

export function usePublish(project: string, enabled: boolean) {
  return useQuery({
    queryKey: ["publish", project],
    queryFn: () => getPublishPreview(project),
    enabled,
  });
}
```

- [ ] **Step 4: Run tests** — Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add ui/lib/schemas.ts ui/lib/api/publish.ts ui/lib/queries/use-publish.ts ui/tests/publish-api.test.ts
git commit -m "feat(ui): publish schema, api client, query hook"
```

---

### Task 11: UI — Export OKF tab in /kb

**Files:**
- Modify: `ui/app/kb/page.tsx` (add tabs Curated | Export OKF)
- Create: `ui/components/publish/okf-export.tsx` (tree + preview + download)
- Test: `ui/tests/okf-export.test.tsx`

**Interfaces:**
- Consumes: `usePublish`, `downloadBundleUrl`, `useProjectStore`.
- Produces: `<OkfExport />` — left file tree from `tree[]`, right rendered content of selected file, download button, stats footer, empty state.

- [ ] **Step 1: Write the failing test**

```tsx
// ui/tests/okf-export.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { OkfExport } from "@/components/publish/okf-export";

vi.mock("@/lib/queries/use-publish", () => ({
  usePublish: () => ({
    data: {
      tree: ["byte-edge/runbooks/x.md"],
      files: { "byte-edge/runbooks/x.md": "# KubeVirt recovery" },
      stats: { concepts: 1, titled_by: "slug" },
    },
    isLoading: false,
  }),
}));

describe("OkfExport", () => {
  it("shows the tree and previews a clicked file", () => {
    render(<OkfExport project="byte-edge" />);
    fireEvent.click(screen.getByText(/x.md/));
    expect(screen.getByText(/KubeVirt recovery/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test** — Expected: FAIL (component missing).

- [ ] **Step 3: Implement `ui/components/publish/okf-export.tsx`**

```tsx
"use client";
import { useState } from "react";
import { usePublish } from "@/lib/queries/use-publish";
import { downloadBundleUrl } from "@/lib/api/publish";

export function OkfExport({ project }: { project: string }) {
  const { data, isLoading } = usePublish(project, true);
  const [selected, setSelected] = useState<string | null>(null);

  if (isLoading) return <div>Building bundle…</div>;
  if (!data || data.tree.length === 0) return <div>No memories for this scope.</div>;

  return (
    <div className="grid grid-cols-[280px_1fr] gap-4">
      <ul className="space-y-1 text-sm">
        {data.tree.map((p) => (
          <li key={p}>
            <button className="text-left hover:underline" onClick={() => setSelected(p)}>{p}</button>
          </li>
        ))}
      </ul>
      <div>
        <a href={downloadBundleUrl(project)} className="mb-2 inline-block rounded border px-3 py-1">
          Download .tar.gz
        </a>
        <pre className="whitespace-pre-wrap rounded bg-muted p-3 text-sm">
          {selected ? data.files[selected] : "Select a file to preview."}
        </pre>
        <p className="mt-2 text-xs text-muted-foreground">
          {data.stats.concepts} concepts · titled by {data.stats.titled_by ?? "slug"}
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the tab into `ui/app/kb/page.tsx`** — add local tab state `[tab, setTab] = useState<"curated"|"okf">("curated")`, a two-button toggle, render existing KB content when `curated`, `<OkfExport project={project} />` when `okf`.

- [ ] **Step 5: Run tests** — Run: `cd ui && npx vitest run tests/okf-export.test.tsx` — Expected: pass. Then full UI suite `cd ui && npx vitest run` and build check `cd ui && npm run build`.

- [ ] **Step 6: Commit**

```bash
git add ui/app/kb/page.tsx ui/components/publish/okf-export.tsx ui/tests/okf-export.test.tsx
git commit -m "feat(ui): Export OKF tab in /kb"
```

---

### Task 12: End-to-end smoke against real memory + docs

**Files:**
- Modify: `README.md` (add `/api/memory/publish` row to the REST API table)
- Test: manual smoke (documented steps, no new automated test)

- [ ] **Step 1: Start backend, hit preview against a real project**

Run: `curl -s "http://localhost:8000/api/memory/publish?project=byte-edge&mode=preview" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['stats']); print('\n'.join(d['tree'][:15]))"`
Expected: non-zero `concepts`, a tree of `byte-edge/<type>s/<slug>.md` paths + `index.md`.

- [ ] **Step 2: Verify OKF conformance on the output** — pipe one file, confirm it starts with `---`, has `type:`, and cross-links begin with `/`.

- [ ] **Step 3: Download tarball** — Run: `curl -s "http://localhost:8000/api/memory/publish?project=byte-edge&mode=tar" -o /tmp/bundle.tar.gz && tar tzf /tmp/bundle.tar.gz | head` — Expected: lists `.md` paths.

- [ ] **Step 4: Add README REST row**

```markdown
| `GET /api/memory/publish` | Export memory to an OKF v0.1 bundle (`mode=preview\|tar\|dir`) |
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document /api/memory/publish endpoint"
```

---

## Self-Review

**Spec coverage:**
- §2 modules → Tasks 1,2,3,4,5,6 ✓
- §3 clustering/titling → Tasks 2,3 ✓ (contradicts excluded T2, cache T3)
- §4 endpoint/tool/skill → Tasks 7,8,9 ✓ (allowlist+traversal T7)
- §5 UI /kb tab → Tasks 10,11 ✓ (preview+download only; no dir in UI ✓)
- §6 error handling → T7 (empty→200, traversal→400, tar 500 path), T3 (judge fallback), T6 (cache best-effort) ✓
- §7 testing → tests at each layer T1–T11 ✓
- §8 out-of-scope respected (no UI dir write, no 2nd format, no import) ✓
- Keep `scripts/digest.py` → not touched by any task ✓

**Placeholder scan:** One deliberate `NotImplementedError` in Task 6 (`summarize_cluster_title`) — it is guarded by `make_title_fn`'s try/except so export works keyless; real LLM wiring is explicitly deferred as an isolated follow-up, not a hidden gap. All other steps contain runnable code.

**Type consistency:** `Bundle{tree,files,stats}` and `Concept{path,frontmatter,body}` consistent T1→T11. `title_fn(cluster)->(title,summary)` consistent T3→T5→T6. `build_bundle(memories, graph, *, title_fn, renderer, project_hint)` consistent T5→T6. `publish_from_manager(manager, *, project, fmt)` consistent T6→T7→T8. `map_type`/`slugify`/`cluster_key` names stable.

**Known follow-up (not blocking):** wire `summarize_cluster_title` to the real Haiku client (mirrors the observe-hook path) once base export is verified.
