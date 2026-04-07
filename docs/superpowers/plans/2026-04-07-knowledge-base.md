# Knowledge Base UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browsable, searchable knowledge base UI at `/kb` with topic cards, split detail view, search, and hygiene mode.

**Architecture:** Hybrid approach — reuse existing REST endpoints, add `?format=json` to hierarchy and consolidate endpoints, add one new `/api/kb/topic/<label>` endpoint. Frontend is a single embedded HTML page (same pattern as `/dashboard`) with hash-based client-side routing.

**Tech Stack:** Python (FastAPI/Starlette), HTML/CSS/JS (no frameworks), existing Qdrant + knowledge graph infrastructure.

**Spec:** `docs/superpowers/specs/2026-04-07-knowledge-base-design.md`

**Test command:** `PYTHONPATH=src .venv/bin/python -m pytest tests/ -v`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `src/memory/topics.py` | Add `topics_to_json()` — structured JSON output for topic clusters |
| Modify | `src/memory/manager.py` | Add `get_topic_clusters()` and `consolidate_memories_json()` methods |
| Modify | `src/server.py` | Add `?format=json` to hierarchy/consolidate, new `/api/kb/topic/<label>` endpoint, new `/kb` route |
| Create | `tests/test_kb_api.py` | Tests for all new/modified backend endpoints |

---

### Task 1: Hierarchy endpoint — JSON format

Add `topics_to_json()` to topics.py and `get_topic_clusters()` to manager.py so the hierarchy endpoint can return structured JSON instead of markdown.

**Files:**
- Modify: `src/memory/topics.py` (add function after `render_hierarchical_context`)
- Modify: `src/memory/manager.py:785-819` (add new method)
- Modify: `src/server.py:380-418` (add format param branch)
- Create: `tests/test_kb_api.py`

- [ ] **Step 1: Write failing test for `topics_to_json`**

Create `tests/test_kb_api.py`:

```python
"""Tests for Knowledge Base API endpoints."""

import pytest
from memory.topics import TopicCluster, topics_to_json


class TestTopicsToJson:
    def test_converts_clusters_to_dict(self):
        clusters = [
            TopicCluster(
                topic_id="topic_0",
                label="Architecture",
                memories=[
                    {
                        "memory_id": "2026-01-01_decision_aaa",
                        "content": "Chose PostgreSQL",
                        "type": "decision",
                        "date": "2026-01-01",
                        "project": "test-proj",
                    },
                    {
                        "memory_id": "2026-01-02_learning_bbb",
                        "content": "NATS works well",
                        "type": "learning",
                        "date": "2026-01-02",
                        "project": "test-proj",
                    },
                ],
            ),
        ]
        result = topics_to_json(clusters, project="test-proj")

        assert result["project"] == "test-proj"
        assert len(result["topics"]) == 1
        topic = result["topics"][0]
        assert topic["label"] == "Architecture"
        assert topic["memory_count"] == 2
        assert topic["memories"][0]["memory_id"] == "2026-01-01_decision_aaa"
        assert topic["memories"][0]["type"] == "decision"
        assert topic["memories"][0]["content"] == "Chose PostgreSQL"

    def test_default_project_is_all(self):
        result = topics_to_json([], project=None)
        assert result["project"] == "all"
        assert result["topics"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestTopicsToJson -v`

Expected: `ImportError: cannot import name 'topics_to_json'`

- [ ] **Step 3: Implement `topics_to_json` in topics.py**

Add after `render_hierarchical_context` (after line ~381) in `src/memory/topics.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestTopicsToJson -v`

Expected: 2 passed

- [ ] **Step 5: Write failing test for `get_topic_clusters` on manager**

Add to `tests/test_kb_api.py`:

```python
from unittest.mock import MagicMock, patch


class TestManagerGetTopicClusters:
    @pytest.fixture
    def manager(self, tmp_path):
        with patch("memory.manager.VectorStore") as mock_vs:
            store = MagicMock()
            mock_vs.return_value = store
            store.count.return_value = 0

            from memory.manager import MemoryManager

            mgr = MemoryManager(
                memory_dir=str(tmp_path / "memory"),
                qdrant_url="http://localhost:6333",
            )
            mgr._store = store
            yield mgr

    def test_returns_topic_clusters(self, manager):
        manager._store.scroll.return_value = [
            {
                "memory_id": "2026-01-01_decision_aaa",
                "content": "Chose PostgreSQL",
                "type": "decision",
                "date": "2026-01-01",
                "project": "test",
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "memory_id": "2026-01-02_fact_bbb",
                "content": "PostgreSQL runs on port 5432",
                "type": "fact",
                "date": "2026-01-02",
                "project": "test",
                "vector": [0.99, 0.01, 0.0],
            },
        ]

        clusters = manager.get_topic_clusters(project="test", limit=10)

        assert isinstance(clusters, list)
        assert len(clusters) >= 1
        assert hasattr(clusters[0], "label")
        assert hasattr(clusters[0], "memories")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestManagerGetTopicClusters -v`

Expected: `AttributeError: 'MemoryManager' object has no attribute 'get_topic_clusters'`

- [ ] **Step 7: Implement `get_topic_clusters` in manager.py**

Add new method to `MemoryManager` class in `src/memory/manager.py`, near `get_hierarchical_project_context` (~line 785):

```python
def get_topic_clusters(
    self,
    project: str | None = None,
    limit: int = 120,
    max_topics: int = 8,
    similarity_threshold: float = 0.72,
) -> list:
    """Return raw TopicCluster objects (for JSON serialization)."""
    from memory.topics import build_topic_clusters

    filters = {}
    if project:
        filters["project"] = project
    points = self.store.scroll(filters=filters, limit=limit, with_vectors=True)
    if not points:
        return []
    return build_topic_clusters(
        points,
        similarity_threshold=similarity_threshold,
        max_topics=max_topics,
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestManagerGetTopicClusters -v`

Expected: 1 passed

- [ ] **Step 9: Wire up `?format=json` in server.py hierarchy endpoint**

Modify the hierarchy handler in `src/server.py` (around line 380-418). Add `format` query param check:

```python
# At the top of the handler, after parsing other params:
fmt = params.get("format", "markdown")

# Replace the existing context fetch + response with:
if fmt == "json":
    from memory.topics import topics_to_json
    clusters = manager.get_topic_clusters(
        project=project,
        limit=limit,
        max_topics=max_topics,
        similarity_threshold=similarity_threshold,
    )
    result = topics_to_json(clusters, project=project)
    result["params"] = {
        "limit": limit,
        "max_topics": max_topics,
        "similarity_threshold": similarity_threshold,
    }
    return JSONResponse(result)
else:
    context = manager.get_hierarchical_project_context(
        project=project,
        limit=limit,
        max_topics=max_topics,
        similarity_threshold=similarity_threshold,
    )
    return JSONResponse({
        "project": project or "all",
        "context": context,
        "params": {
            "limit": limit,
            "max_topics": max_topics,
            "similarity_threshold": similarity_threshold,
        },
    })
```

- [ ] **Step 10: Run all tests to verify nothing broke**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py tests/test_cache_context.py -v`

Expected: All pass

- [ ] **Step 11: Commit**

```bash
git add src/memory/topics.py src/memory/manager.py src/server.py tests/test_kb_api.py
git commit -m "feat(kb): add JSON format to hierarchy endpoint

Add topics_to_json() helper and get_topic_clusters() manager method.
Hierarchy endpoint now accepts ?format=json for structured output."
```

---

### Task 2: Consolidate endpoint — JSON format

Add structured JSON output to the consolidation endpoint for the Fix mode.

**Files:**
- Modify: `src/memory/manager.py:853-945` (add JSON branch)
- Modify: `src/server.py:540-570` (add format param)
- Modify: `tests/test_kb_api.py`

- [ ] **Step 1: Write failing test for JSON consolidation**

Add to `tests/test_kb_api.py`:

```python
class TestConsolidateJson:
    @pytest.fixture
    def manager(self, tmp_path):
        with patch("memory.manager.VectorStore") as mock_vs:
            store = MagicMock()
            mock_vs.return_value = store
            store.count.return_value = 0

            from memory.manager import MemoryManager

            mgr = MemoryManager(
                memory_dir=str(tmp_path / "memory"),
                qdrant_url="http://localhost:6333",
            )
            mgr._store = store
            yield mgr

    def test_returns_structured_dict(self, manager):
        manager._store.scroll.return_value = []
        result = manager.consolidate_memories_json(project=None, limit=10)

        assert isinstance(result, dict)
        assert "superseded" in result
        assert "conflicts" in result
        assert isinstance(result["superseded"], list)
        assert isinstance(result["conflicts"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestConsolidateJson -v`

Expected: `AttributeError: 'MemoryManager' object has no attribute 'consolidate_memories_json'`

- [ ] **Step 3: Implement `consolidate_memories_json` in manager.py**

Add new method to `MemoryManager` in `src/memory/manager.py`, near `consolidate_memories` (~line 853). This method mirrors the existing consolidation logic but returns structured data instead of markdown:

```python
def consolidate_memories_json(
    self,
    project: str | None = None,
    limit: int = 240,
) -> dict:
    """Return consolidation results as structured JSON."""
    from memory.knowledge_graph import RELATION_TYPES

    filters = {}
    if project:
        filters["project"] = project
    points = self.store.scroll(filters=filters, limit=limit, with_vectors=False)
    points_by_id = {p["memory_id"]: p for p in points if "memory_id" in p}

    seen_supersedes = {}
    seen_conflicts = {}

    if hasattr(self, "knowledge_graph") and self.knowledge_graph:
        for edge in self.knowledge_graph._graph.edges(data=True):
            src, tgt, data = edge
            relation = data.get("relation", "related_to")
            weight = data.get("weight", 0.5)
            pair = (min(src, tgt), max(src, tgt))
            if relation == "supersedes":
                if pair not in seen_supersedes or weight > seen_supersedes[pair]:
                    seen_supersedes[pair] = weight
            elif relation == "contradicts":
                if pair not in seen_conflicts or weight > seen_conflicts[pair]:
                    seen_conflicts[pair] = weight

    def _mem_summary(mid):
        p = points_by_id.get(mid, {})
        return {
            "memory_id": mid,
            "content": p.get("content", "")[:200],
            "type": p.get("type", "note"),
            "date": p.get("date", ""),
            "project": p.get("project", "general"),
        }

    return {
        "project": project or "all",
        "superseded": [
            {
                "newer": _mem_summary(pair[1]),
                "older": _mem_summary(pair[0]),
                "score": round(weight, 3),
            }
            for pair, weight in sorted(seen_supersedes.items(), key=lambda x: -x[1])
        ],
        "conflicts": [
            {
                "a": _mem_summary(pair[0]),
                "b": _mem_summary(pair[1]),
                "score": round(weight, 3),
            }
            for pair, weight in sorted(seen_conflicts.items(), key=lambda x: -x[1])
        ],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestConsolidateJson -v`

Expected: 1 passed

- [ ] **Step 5: Wire up `?format=json` in server.py consolidate endpoint**

Modify the consolidate handler in `src/server.py` (~line 540-570). Add format param:

```python
# After parsing existing params:
fmt = params.get("format", "markdown")

if fmt == "json":
    result = manager.consolidate_memories_json(project=project, limit=limit)
    return JSONResponse(result)
else:
    # existing markdown logic
    summary = manager.consolidate_memories(project=project, limit=limit, save_summary=save_summary)
    return JSONResponse({"project": project or "all", "limit": limit, "save_summary": save_summary, "summary": summary})
```

- [ ] **Step 6: Run tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py -v`

Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/memory/manager.py src/server.py tests/test_kb_api.py
git commit -m "feat(kb): add JSON format to consolidate endpoint

Add consolidate_memories_json() for structured superseded/conflict pairs.
Consolidate endpoint accepts ?format=json."
```

---

### Task 3: New `/api/kb/topic/<label>` endpoint

Returns memories for a single topic with inline graph connections.

**Files:**
- Modify: `src/server.py` (add new route)
- Modify: `tests/test_kb_api.py`

- [ ] **Step 1: Write failing test for topic endpoint**

Add to `tests/test_kb_api.py`:

```python
class TestKbTopicEndpoint:
    @pytest.fixture
    def manager(self, tmp_path):
        with patch("memory.manager.VectorStore") as mock_vs:
            store = MagicMock()
            mock_vs.return_value = store
            store.count.return_value = 0

            from memory.manager import MemoryManager

            mgr = MemoryManager(
                memory_dir=str(tmp_path / "memory"),
                qdrant_url="http://localhost:6333",
            )
            mgr._store = store
            yield mgr

    def test_get_topic_with_connections(self, manager):
        """Test that get_topic_detail returns memories with connections."""
        manager._store.scroll.return_value = [
            {
                "memory_id": "2026-01-01_decision_aaa",
                "content": "Chose PostgreSQL",
                "type": "decision",
                "date": "2026-01-01",
                "project": "test",
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "memory_id": "2026-01-02_fact_bbb",
                "content": "PostgreSQL on port 5432",
                "type": "fact",
                "date": "2026-01-02",
                "project": "test",
                "vector": [0.99, 0.01, 0.0],
            },
        ]

        from memory.topics import TopicCluster

        cluster = TopicCluster(
            topic_id="topic_0",
            label="Database",
            memories=manager._store.scroll.return_value,
        )
        result = manager.get_topic_detail(cluster)

        assert result["topic"] == "Database"
        assert result["memory_count"] == 2
        assert len(result["memories"]) == 2
        assert "connections" in result["memories"][0]
        assert isinstance(result["memories"][0]["connections"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestKbTopicEndpoint -v`

Expected: `AttributeError: 'MemoryManager' object has no attribute 'get_topic_detail'`

- [ ] **Step 3: Implement `get_topic_detail` in manager.py**

Add to `MemoryManager` class in `src/memory/manager.py`:

```python
def get_topic_detail(self, cluster) -> dict:
    """Return a topic's memories with inline graph connections."""
    points_by_id = {m["memory_id"]: m for m in cluster.memories if "memory_id" in m}

    memories = []
    for m in cluster.memories:
        mid = m.get("memory_id", "")
        connections = []

        if hasattr(self, "knowledge_graph") and self.knowledge_graph:
            edges = self.knowledge_graph.get_edges(mid)
            for edge in edges:
                neighbor_id = edge.target if edge.source == mid else edge.source
                neighbor = points_by_id.get(neighbor_id)
                if not neighbor:
                    # Try to fetch from store
                    hits = self.store.scroll(
                        filters={"memory_id": neighbor_id}, limit=1, with_vectors=False
                    )
                    neighbor = hits[0] if hits else None
                if neighbor:
                    connections.append(
                        {
                            "memory_id": neighbor_id,
                            "content": neighbor.get("content", "")[:150],
                            "relation": edge.relation,
                            "weight": round(edge.weight, 3),
                            "type": neighbor.get("type", "note"),
                            "date": neighbor.get("date", ""),
                        }
                    )

        memories.append(
            {
                "memory_id": mid,
                "content": m.get("content", ""),
                "type": m.get("type", "note"),
                "date": m.get("date", ""),
                "project": m.get("project", "general"),
                "connections": connections,
            }
        )

    return {
        "topic": cluster.label,
        "memory_count": len(memories),
        "memories": memories,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py::TestKbTopicEndpoint -v`

Expected: 1 passed

- [ ] **Step 5: Add the `/api/kb/topic/<label>` route in server.py**

Add new route in `src/server.py` (near the other API routes):

```python
@mcp.custom_route("/api/kb/topic/{label}", methods=["GET"])
async def api_kb_topic(request):
    """Get a single topic's memories with graph connections."""
    from starlette.responses import JSONResponse

    try:
        label = request.path_params["label"]
        params = dict(request.query_params)
        project = params.get("project")
        limit = int(params.get("limit", "200"))
        max_topics = int(params.get("max_topics", "20"))
        similarity_threshold = float(params.get("similarity_threshold", "0.72"))

        manager = _get_memory_manager()
        clusters = manager.get_topic_clusters(
            project=project,
            limit=limit,
            max_topics=max_topics,
            similarity_threshold=similarity_threshold,
        )

        # Find matching cluster by label (case-insensitive)
        cluster = None
        for c in clusters:
            if c.label.lower() == label.lower():
                cluster = c
                break

        if not cluster:
            return JSONResponse(
                {"error": f"Topic '{label}' not found", "available": [c.label for c in clusters]},
                status_code=404,
            )

        result = manager.get_topic_detail(cluster)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
```

- [ ] **Step 6: Run all backend tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py -v`

Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/memory/manager.py src/server.py tests/test_kb_api.py
git commit -m "feat(kb): add /api/kb/topic/<label> endpoint

Returns single topic's memories with inline graph connections.
Includes get_topic_detail() on MemoryManager."
```

---

### Task 4: KB HTML page — skeleton, home view, topic cards

Build the `/kb` route with the full home view: top bar, stats, skills, and topic card grid.

**Files:**
- Modify: `src/server.py` (add `/kb` route with embedded HTML)

- [ ] **Step 1: Add the `/kb` route in server.py**

Add a new route handler in `src/server.py` (after the dashboard route). The HTML follows the same embedded pattern as the dashboard. Write the full HTML including:

- CSS: dark neural theme matching dashboard (`#050510` bg, glass panels, type colors)
- Top bar: MEMENTO KB brand, search input, project pills, type pills, KB/Fix toggle, Brain link
- Stats bar: fetches `GET /api/memory/stats`
- Skills row: fetches `GET /api/memory/context/skills?format=json` (use markdown parsing as fallback)
- Topic cards grid: fetches `GET /api/memory/context/hierarchy?format=json&limit=200&max_topics=12`
- Hash routing skeleton: `hashchange` listener with view switching
- Helper functions: `esc()` for HTML escaping, `buildFilters()` for query params

```python
@mcp.custom_route("/kb", methods=["GET"])
async def api_kb(_request):
    """Knowledge Base UI."""
    from starlette.responses import HTMLResponse

    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Memento — Knowledge Base</title>
<style>
/* ... full CSS here — same dark theme as dashboard ... */
</style>
</head>
<body>
<!-- Top bar, stats bar, skills row, topic cards container -->
<!-- Script: fetch data, render views, hash routing -->
</body>
</html>"""
    return HTMLResponse(html)
```

The HTML should be ~400 lines for this task (home view only). Topic card click sets `location.hash = '#topic=' + label`.

- [ ] **Step 2: Verify the route works**

Run: `PYTHONPATH=src .venv/bin/python -c "import ast; ast.parse(open('src/server.py').read()); print('Syntax OK')"`

Then start the server and visit `http://localhost:8000/kb` to verify the home view renders with topic cards.

- [ ] **Step 3: Commit**

```bash
git add src/server.py
git commit -m "feat(kb): add /kb route with home view

Topic cards grid, stats bar, skills row, project/type filters.
Hash-based routing skeleton for future views."
```

---

### Task 5: Topic detail split view + search

Add the split view for topic detail and search results.

**Files:**
- Modify: `src/server.py` (extend KB HTML with detail view + search)

- [ ] **Step 1: Add topic detail view**

In the KB HTML's JavaScript section, add:

- `renderTopicDetail(label)` function: fetches `GET /api/kb/topic/<label>`, renders left panel (memory list) and right panel (detail + connections)
- Left panel: compact memory rows, click to select
- Right panel: type badge, date, project, full content, connections section with clickable links
- Breadcrumb: `Topics / <label>` with click to go back
- Connection click handler: sets `location.hash = '#topic=<targetTopic>&select=<memoryId>'`

- [ ] **Step 2: Add search functionality**

Add to the KB HTML JavaScript:

- Debounced search (300ms) on the search input: `POST /api/memory/recall` with `{query, limit: 20}`
- `renderSearchResults(query, results)` function: same split layout as topic detail
- Left panel: search results ranked by score
- Right panel: selected result detail + connections (fetch connections via graph endpoint for selected memory)
- Breadcrumb: `Search / "<query>"`

- [ ] **Step 3: Wire up hash routing**

Complete the `hashchange` listener:

```javascript
function route() {
    var hash = location.hash.slice(1);
    if (hash.startsWith("topic=")) {
        var label = decodeURIComponent(hash.split("topic=")[1].split("&")[0]);
        renderTopicDetail(label);
    } else if (hash.startsWith("search=")) {
        var query = decodeURIComponent(hash.split("search=")[1]);
        doSearch(query);
    } else if (hash === "fix") {
        renderFixMode();
    } else {
        renderHome();
    }
}
window.addEventListener("hashchange", route);
```

- [ ] **Step 4: Verify**

Visit `http://localhost:8000/kb`, click a topic card — should show split view. Type in search — should show results. Click a connection — should navigate.

- [ ] **Step 5: Commit**

```bash
git add src/server.py
git commit -m "feat(kb): add topic detail split view and search

Split view with memory list + detail pane + graph connections.
Debounced search with recall endpoint. Hash-based navigation."
```

---

### Task 6: Fix mode + responsive + cross-links

Add the hygiene mode and final polish.

**Files:**
- Modify: `src/server.py` (extend KB HTML with Fix mode + responsive)

- [ ] **Step 1: Add Fix mode view**

Add `renderFixMode()` to the KB HTML JavaScript:

- Fetches `GET /api/memory/consolidate?format=json`
- Renders superseded pairs: side-by-side cards, score badge, "Confirm & Delete" / "Dismiss" buttons
- Renders conflicts: side-by-side cards, "Keep A" / "Keep B" / "Dismiss" buttons
- Delete action: `DELETE /api/memory/<id>`, then re-fetch consolidation data
- Empty state: "All clean" message when no issues

- [ ] **Step 2: Add KB/Fix toggle behavior**

Wire the mode toggle buttons:

```javascript
document.getElementById("mode-kb").addEventListener("click", function() {
    location.hash = "";
});
document.getElementById("mode-fix").addEventListener("click", function() {
    location.hash = "fix";
});
```

Update toggle visual state based on current hash.

- [ ] **Step 3: Add responsive breakpoints**

Add media queries to the KB CSS:

```css
@media (max-width: 1024px) {
    .topic-grid { grid-template-columns: repeat(2, 1fr); }
    .split-left { width: 220px; }
}
@media (max-width: 768px) {
    .topic-grid { grid-template-columns: 1fr; }
    .split-view { flex-direction: column; }
    .split-left { width: 100%; max-height: 40vh; }
}
```

- [ ] **Step 4: Add Brain dashboard link**

In the top bar, the "Brain →" link navigates to `/dashboard`:

```html
<a href="/dashboard" style="...">Brain &rarr;</a>
```

Also add a reciprocal "KB →" link in the brain dashboard top bar (small edit to the dashboard HTML).

- [ ] **Step 5: Final verification**

1. Visit `/kb` — topic cards load, stats show, skills display
2. Click a topic — split view with memories and connections
3. Click a connection — navigates to the connected memory's topic
4. Search for a term — results appear in split view
5. Toggle to Fix mode — superseded/conflicts display (or "all clean")
6. Click "Brain →" — opens brain dashboard
7. Resize window — responsive layout adapts

- [ ] **Step 6: Run all tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_kb_api.py -v`

Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/server.py
git commit -m "feat(kb): add Fix mode, responsive layout, cross-links

Hygiene view with superseded/conflict pairs and delete actions.
Responsive breakpoints for mobile/tablet. Brain dashboard link."
```

---

## Summary

| Task | What | Backend | Frontend | Tests |
|------|------|---------|----------|-------|
| 1 | Hierarchy `?format=json` | `topics.py`, `manager.py`, `server.py` | - | Yes |
| 2 | Consolidate `?format=json` | `manager.py`, `server.py` | - | Yes |
| 3 | `/api/kb/topic/<label>` | `manager.py`, `server.py` | - | Yes |
| 4 | KB home view | `server.py` (route) | HTML/CSS/JS | Manual |
| 5 | Topic detail + search | `server.py` (HTML) | HTML/CSS/JS | Manual |
| 6 | Fix mode + polish | `server.py` (HTML) | HTML/CSS/JS | Manual |

Tasks 1-3 are fully TDD with automated tests. Tasks 4-6 are frontend (embedded HTML) verified manually since there's no test harness for the embedded UI.
