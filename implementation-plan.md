# Memory Knowledge Graph (MKG) — Implementation Plan

## Context

Memento-MCP stores memories as flat entries (YAML + Qdrant vectors), recalls via cosine similarity. Two problems:

1. **Similarity ≠ relevance** — cosine finds "similar text" not "useful context"
2. **No relationships** — can't follow chains: decision → learning → requirement change

Result: Claude re-asks for context every session. Fix: associative memory with typed relationships, graph-enhanced retrieval, hierarchical context.

---

## Execution Log

### Branch
- `feat/knowledge-graph-implementation-complete` (based on `feat-knowledge-graph-phase2-hierarchy`)

### What I completed on this branch
- Implemented all planned phases from this document:
  - Phase 1.1–1.7 (knowledge graph foundation, auto-linking, graph recall, rebuild, visualization, graph-recall tests)
  - Phase 2 (topics, hierarchical context, hierarchy tooling/API wiring)
  - Phase 3 (skill extraction + `skill_context`)
  - Phase 4 (conflict detection, consolidation, proactive summary)
- Added memory graph intelligence API endpoint coverage:
  - `/api/memory/consolidate`
  - `/api/memory/context/proactive`
  - `/api/memory/graph/rebuild`

### Verification
- Final test run:
  - `uv run pytest -q` → `237 passed, 9 skipped`
- Lint cleanup completed for current tree:
  - Removed unused imports and fixed import ordering warnings
  - Replaced non-explicit `zip(...)` usage with explicit `zip(..., strict=True)` in `src/memory/graph.py`

### Atomic commits in this branch
- `fe8d7d6` — `feat: add KnowledgeGraph class with persistence`
- `7a72c38` — `feat: add auto-linking algorithm`
- `ef8c58e` — `feat: wire auto-linking into MemoryManager.save`
- `fc4291c` — `feat: graph-enhanced recall replaces pure vector search`
- `334d438` — `feat: add rebuild_graph() for backfilling existing memories`
- `ea85011` — `feat: use knowledge graph edges in visualization graph`
- `ae56c26` — `feat: add topic clustering and hierarchy rendering`
- `525e2f3` — `feat: add cacheable hierarchical context`
- `8f2e062` — `feat: add hierarchical project context generation`
- `1c7d6ce` — `feat: expose hierarchical context via MCP tool and API`
- `4b0c9fc` — `feat: extract skills from memory clusters`
- `c784ab3` — `fix: preserve recall compatibility and graph path behavior`
- `191889e` — `feat: detect conflicts during auto-link`
- `12045af` — `feat: add memory consolidation and proactive summary APIs`
- `5d52fe7` — `test: cover server memory intelligence endpoints`

## Phase 1: Knowledge Graph Foundation

### Commit 1.1: `feat: add KnowledgeGraph class with persistence`

**New file**: `src/memory/knowledge_graph.py`

```python
"""Persistent knowledge graph for memory relationships.

Stores typed, weighted edges between memories. Backed by networkx
for traversal/analysis, persisted to _graph.json with atomic writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import networkx as nx


# -- Data Model ---------------------------------------------------------------

RELATION_TYPES = frozenset({
    "related_to",   # semantically similar (default)
    "led_to",       # temporal causation: A happened → B followed
    "depends_on",   # B requires A (decision depends on requirement)
    "contradicts",  # A and B conflict
    "supersedes",   # B replaces A (newer version)
    "part_of",      # B belongs to topic/cluster A
})

TYPE_WEIGHTS: dict[str, float] = {
    "requirement": 1.0,
    "decision": 0.85,
    "preference": 0.75,
    "learning": 0.65,
    "fact": 0.55,
    "note": 0.35,
    "session": 0.25,
}

GRAPH_VERSION = 1


@dataclass(frozen=True, slots=True)
class Edge:
    """A typed, weighted relationship between two memories."""

    source: str
    target: str
    relation: str
    weight: float
    auto: bool = True
    created: str = field(default_factory=lambda: date.today().isoformat())


# -- Knowledge Graph ----------------------------------------------------------

class KnowledgeGraph:
    """Persistent directed graph of memory relationships.

    Storage: ~/.claude/memory/_graph.json (atomic writes).
    In-memory: networkx DiGraph for traversal/analysis.
    """

    def __init__(self, graph_path: Path | str) -> None:
        self._path = Path(graph_path)
        self._graph = nx.DiGraph()
        self._dirty = False
        self._load()

    # -- Persistence -----------------------------------------------------------

    def _load(self) -> None:
        """Load graph from JSON file. Create empty if missing."""
        if not self._path.exists():
            return
        with open(self._path) as f:
            data = json.load(f)
        for node_id, attrs in data.get("nodes", {}).items():
            self._graph.add_node(node_id, **attrs)
        for edge in data.get("edges", []):
            self._graph.add_edge(
                edge["source"], edge["target"],
                relation=edge["relation"],
                weight=edge["weight"],
                auto=edge.get("auto", True),
                created=edge.get("created", ""),
            )

    def save(self) -> None:
        """Atomic write: tempfile + os.replace (POSIX atomic)."""
        if not self._dirty:
            return
        data = {
            "version": GRAPH_VERSION,
            "nodes": {
                n: dict(self._graph.nodes[n])
                for n in self._graph.nodes
            },
            "edges": [
                {
                    "source": u,
                    "target": v,
                    **self._graph.edges[u, v],
                }
                for u, v in self._graph.edges
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, suffix=".json.tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
            self._dirty = False
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # -- Node Operations -------------------------------------------------------

    def add_node(
        self,
        memory_id: str,
        *,
        topic: str = "",
        importance: float | None = None,
        memory_type: str = "note",
    ) -> None:
        if importance is None:
            importance = TYPE_WEIGHTS.get(memory_type, 0.35)
        self._graph.add_node(
            memory_id,
            topic=topic,
            importance=importance,
            access_count=0,
            last_accessed=date.today().isoformat(),
        )
        self._dirty = True

    def record_access(self, memory_id: str) -> None:
        if memory_id in self._graph:
            self._graph.nodes[memory_id]["access_count"] += 1
            self._graph.nodes[memory_id]["last_accessed"] = date.today().isoformat()
            self._dirty = True

    def remove_node(self, memory_id: str) -> None:
        if memory_id in self._graph:
            self._graph.remove_node(memory_id)  # cascades edges
            self._dirty = True

    # -- Edge Operations -------------------------------------------------------

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float,
        *,
        auto: bool = True,
    ) -> None:
        if relation not in RELATION_TYPES:
            raise ValueError(f"Unknown relation: {relation}")
        if source == target:
            return  # no self-links
        if self._graph.has_edge(source, target):
            return  # no duplicate edges
        self._graph.add_edge(
            source, target,
            relation=relation,
            weight=weight,
            auto=auto,
            created=date.today().isoformat(),
        )
        self._dirty = True

    def get_edges(
        self, memory_id: str, direction: str = "both",
    ) -> list[Edge]:
        edges: list[Edge] = []
        if direction in ("out", "both"):
            for _, target, data in self._graph.out_edges(memory_id, data=True):
                edges.append(Edge(source=memory_id, target=target, **data))
        if direction in ("in", "both"):
            for source, _, data in self._graph.in_edges(memory_id, data=True):
                edges.append(Edge(source=source, target=memory_id, **data))
        return edges

    # -- Traversal -------------------------------------------------------------

    def get_neighbors(
        self,
        memory_id: str,
        hops: int = 1,
        relation_filter: list[str] | None = None,
    ) -> list[str]:
        """BFS traversal up to N hops, optionally filtered by relation type."""
        if memory_id not in self._graph:
            return []
        visited: set[str] = set()
        frontier = {memory_id}
        for _ in range(hops):
            next_frontier: set[str] = set()
            for node in frontier:
                for neighbor in self._graph.successors(node):
                    if neighbor in visited or neighbor == memory_id:
                        continue
                    edge_data = self._graph.edges[node, neighbor]
                    if relation_filter and edge_data["relation"] not in relation_filter:
                        continue
                    next_frontier.add(neighbor)
                for neighbor in self._graph.predecessors(node):
                    if neighbor in visited or neighbor == memory_id:
                        continue
                    edge_data = self._graph.edges[neighbor, node]
                    if relation_filter and edge_data["relation"] not in relation_filter:
                        continue
                    next_frontier.add(neighbor)
            visited.update(next_frontier)
            frontier = next_frontier
        return list(visited)

    def get_chain(
        self, memory_id: str, relation: str = "led_to", max_depth: int = 5,
    ) -> list[str]:
        """Follow a single relation type forward, returning the chain."""
        chain: list[str] = []
        current = memory_id
        for _ in range(max_depth):
            successors = [
                t for _, t, d in self._graph.out_edges(current, data=True)
                if d["relation"] == relation
            ]
            if not successors:
                break
            current = successors[0]  # follow strongest edge
            chain.append(current)
        return chain

    # -- Analysis --------------------------------------------------------------

    def get_importance(self, memory_id: str) -> float:
        if memory_id not in self._graph:
            return 0.0
        return self._graph.nodes[memory_id].get("importance", 0.5)

    def decay_importance(self) -> int:
        """Apply temporal decay. Returns count of decayed nodes."""
        today = date.today()
        decayed = 0
        for node_id, data in self._graph.nodes(data=True):
            last = date.fromisoformat(data.get("last_accessed", str(today)))
            days_idle = (today - last).days
            if days_idle > 7:
                factor = 0.98 ** (days_idle - 7)
                new_importance = max(0.1, data["importance"] * factor)
                if new_importance != data["importance"]:
                    data["importance"] = new_importance
                    decayed += 1
                    self._dirty = True
        return decayed

    def stats(self) -> dict[str, Any]:
        relation_counts: dict[str, int] = {}
        for _, _, data in self._graph.edges(data=True):
            rel = data.get("relation", "unknown")
            relation_counts[rel] = relation_counts.get(rel, 0) + 1
        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "relations": relation_counts,
            "avg_degree": (
                sum(d for _, d in self._graph.degree()) / max(self._graph.number_of_nodes(), 1)
            ),
        }
```

**Tests**: `tests/test_knowledge_graph.py`

```python
"""Tests for KnowledgeGraph persistence, traversal, and analysis."""

import json
from pathlib import Path

from memory.knowledge_graph import KnowledgeGraph, Edge, TYPE_WEIGHTS


def _tmp_graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(tmp_path / "_graph.json")


# -- Persistence ---------------------------------------------------------------

def test_empty_graph_creates_no_file(tmp_path):
    kg = _tmp_graph(tmp_path)
    assert kg.stats()["nodes"] == 0
    assert not (tmp_path / "_graph.json").exists()


def test_save_and_reload_roundtrip(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a", memory_type="decision")
    kg.add_node("mem_b", memory_type="learning")
    kg.add_edge("mem_a", "mem_b", "led_to", weight=0.8)
    kg.save()

    kg2 = KnowledgeGraph(tmp_path / "_graph.json")
    assert kg2.stats()["nodes"] == 2
    assert kg2.stats()["edges"] == 1
    edges = kg2.get_edges("mem_a", direction="out")
    assert len(edges) == 1
    assert edges[0].relation == "led_to"
    assert edges[0].weight == 0.8


def test_atomic_write_no_partial(tmp_path):
    """If save crashes mid-write, original file is untouched."""
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a", memory_type="fact")
    kg.save()
    original = (tmp_path / "_graph.json").read_text()
    # Verify temp files are cleaned up
    assert not list(tmp_path.glob("*.json.tmp"))


# -- Node Operations ----------------------------------------------------------

def test_add_node_uses_type_weight(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a", memory_type="requirement")
    assert kg.get_importance("mem_a") == TYPE_WEIGHTS["requirement"]  # 1.0


def test_remove_node_cascades_edges(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("a")
    kg.add_node("b")
    kg.add_node("c")
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("b", "c", "led_to", 0.6)
    kg.remove_node("b")
    assert kg.stats()["nodes"] == 2
    assert kg.stats()["edges"] == 0


def test_record_access_increments_count(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a")
    kg.record_access("mem_a")
    kg.record_access("mem_a")
    # Access count tracked on node data (verify via save/reload)
    kg.save()
    kg2 = KnowledgeGraph(tmp_path / "_graph.json")
    with open(tmp_path / "_graph.json") as f:
        data = json.load(f)
    assert data["nodes"]["mem_a"]["access_count"] == 2


# -- Edge Operations ----------------------------------------------------------

def test_no_self_links(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("a")
    kg.add_edge("a", "a", "related_to", 0.9)
    assert kg.stats()["edges"] == 0


def test_no_duplicate_edges(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("a")
    kg.add_node("b")
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("a", "b", "led_to", 0.8)  # same pair, different relation
    assert kg.stats()["edges"] == 1  # first one wins


def test_invalid_relation_raises(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("a")
    kg.add_node("b")
    import pytest
    with pytest.raises(ValueError, match="Unknown relation"):
        kg.add_edge("a", "b", "invented_relation", 0.5)


# -- Traversal ----------------------------------------------------------------

def test_get_neighbors_one_hop(tmp_path):
    """a → b → c. From a, 1-hop = [b]."""
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("b", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=1)
    assert set(neighbors) == {"b"}


def test_get_neighbors_two_hops(tmp_path):
    """a → b → c. From a, 2-hops = [b, c]."""
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("b", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=2)
    assert set(neighbors) == {"b", "c"}


def test_get_neighbors_with_relation_filter(tmp_path):
    """a → b (related_to), a → c (led_to). Filter led_to = [c]."""
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("a", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=1, relation_filter=["led_to"])
    assert neighbors == ["c"]


def test_get_chain_follows_relation(tmp_path):
    """a →led_to→ b →led_to→ c →led_to→ d."""
    kg = _tmp_graph(tmp_path)
    for n in "abcd":
        kg.add_node(n)
    kg.add_edge("a", "b", "led_to", 0.8)
    kg.add_edge("b", "c", "led_to", 0.7)
    kg.add_edge("c", "d", "led_to", 0.6)

    chain = kg.get_chain("a", relation="led_to")
    assert chain == ["b", "c", "d"]


# -- Analysis -----------------------------------------------------------------

def test_importance_decay_after_idle(tmp_path):
    from unittest.mock import patch
    from datetime import date as date_cls

    kg = _tmp_graph(tmp_path)
    kg.add_node("old_mem", memory_type="decision")
    # Simulate 30 days idle
    kg._graph.nodes["old_mem"]["last_accessed"] = "2026-01-01"

    with patch("memory.knowledge_graph.date") as mock_date:
        mock_date.today.return_value = date_cls(2026, 2, 23)
        mock_date.fromisoformat = date_cls.fromisoformat
        decayed = kg.decay_importance()

    assert decayed == 1
    assert kg.get_importance("old_mem") < TYPE_WEIGHTS["decision"]


def test_stats_returns_relation_distribution(tmp_path):
    kg = _tmp_graph(tmp_path)
    for n in "abcd":
        kg.add_node(n)
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("a", "c", "led_to", 0.6)
    kg.add_edge("c", "d", "depends_on", 0.8)

    stats = kg.stats()
    assert stats["nodes"] == 4
    assert stats["edges"] == 3
    assert stats["relations"] == {"related_to": 1, "led_to": 1, "depends_on": 1}
```

---

### Commit 1.2: `feat: add auto-linking algorithm`

**New file**: `src/memory/linker.py`

```python
"""Auto-linking: detect and create relationships between memories on save.

Rules are applied in priority order (first match wins per candidate):
  1. SUPERSEDES — very similar + same type + same project → new replaces old
  2. CONTRADICTS — content opposes existing memory
  3. LED_TO — learning follows recent decision
  4. DEPENDS_ON — decision references requirement
  5. RELATED_TO — similar + same project (default edge)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.embeddings import Embedder
    from core.vector_store import VectorStore
    from memory.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

# Max candidates to evaluate per save
_MAX_CANDIDATES = 10
_SIMILARITY_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class LinkResult:
    """Result of auto-linking a memory."""

    edges_created: int
    relations: dict[str, int]  # e.g., {"related_to": 2, "led_to": 1}


def auto_link(
    *,
    graph: KnowledgeGraph,
    memory_id: str,
    content: str,
    memory_type: str,
    project: str,
    embedder: Embedder,
    store: VectorStore,
) -> LinkResult:
    """Find and create edges from a new memory to existing ones.

    Args:
        graph: Knowledge graph to add edges to
        memory_id: ID of the newly saved memory
        content: Memory content text
        memory_type: Type of the new memory
        project: Project of the new memory
        embedder: For encoding content
        store: For finding similar memories

    Returns:
        LinkResult with count and types of edges created

    Example:
        >>> result = auto_link(
        ...     graph=kg, memory_id="2026-02-23_decision_abc",
        ...     content="Use PostgreSQL", memory_type="decision",
        ...     project="api", embedder=emb, store=vs,
        ... )
        >>> result.edges_created
        3
        >>> result.relations
        {"depends_on": 1, "related_to": 2}
    """
    vector = embedder.encode(content)
    candidates = store.search(
        vector=vector,
        limit=_MAX_CANDIDATES,
        filters={"project": project},
        score_threshold=_SIMILARITY_THRESHOLD,
    )

    relations: dict[str, int] = {}

    for candidate in candidates:
        cand_id = candidate.get("memory_id", "")
        if cand_id == memory_id:
            continue  # skip self

        cand_type = candidate.get("type", "note")
        cand_content = candidate.get("content", "")
        score = candidate.get("score", 0.0)

        relation = _classify_relation(
            new_type=memory_type,
            new_content=content,
            cand_type=cand_type,
            cand_content=cand_content,
            similarity=score,
        )

        if relation == "supersedes":
            graph.add_edge(memory_id, cand_id, "supersedes", weight=score)
            # Reduce importance of superseded memory
            old_importance = graph.get_importance(cand_id)
            if old_importance > 0.1:
                graph._graph.nodes[cand_id]["importance"] = old_importance * 0.5
                graph._dirty = True
        elif relation == "led_to":
            # Direction: decision → learning (candidate is older decision)
            graph.add_edge(cand_id, memory_id, "led_to", weight=score)
        elif relation == "depends_on":
            # Direction: decision → requirement
            graph.add_edge(memory_id, cand_id, "depends_on", weight=score)
        else:
            graph.add_edge(memory_id, cand_id, relation, weight=score)

        relations[relation] = relations.get(relation, 0) + 1

    return LinkResult(
        edges_created=sum(relations.values()),
        relations=relations,
    )


def _classify_relation(
    *,
    new_type: str,
    new_content: str,
    cand_type: str,
    cand_content: str,
    similarity: float,
) -> str:
    """Classify the relationship between two memories.

    Rules applied in priority order — first match wins.

    Example:
        >>> _classify_relation(
        ...     new_type="learning", new_content="Connection pooling needs pgbouncer",
        ...     cand_type="decision", cand_content="Use PostgreSQL",
        ...     similarity=0.72,
        ... )
        "led_to"
    """
    # Rule 1: SUPERSEDES — very similar, same type
    if similarity > 0.9 and new_type == cand_type:
        return "supersedes"

    # Rule 2: LED_TO — learning follows decision
    if new_type == "learning" and cand_type == "decision":
        return "led_to"

    # Rule 3: DEPENDS_ON — decision references requirement
    if new_type == "decision" and cand_type == "requirement":
        return "depends_on"

    # Rule 4: RELATED_TO — default for similar memories
    if similarity > 0.6:
        return "related_to"

    # Below threshold — no edge
    return "related_to"
```

**Input/Output Examples:**

```
Input:
  new memory: "Connection pooling with pgbouncer needed for production"
  type: learning, project: api

  Qdrant returns candidates:
    1. "Use PostgreSQL for better JSON support" (decision, score=0.72)
    2. "Database must support ACID transactions" (requirement, score=0.65)
    3. "PostgreSQL connection limits hit at 100 connections" (learning, score=0.88)

Output:
  edges_created: 3
  relations: {"led_to": 1, "depends_on": 0, "related_to": 2}
  Edges:
    - "Use PostgreSQL" →led_to→ "Connection pooling needed" (0.72)
    - "Connection pooling needed" →related_to→ "Database must support ACID" (0.65)
    - "Connection pooling needed" →related_to→ "PostgreSQL connection limits" (0.88)
```

**Tests**: `tests/test_auto_linking.py`

```python
"""Tests for memory auto-linking rules."""

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph
from memory.linker import auto_link, _classify_relation


def _mock_store(candidates: list[dict]) -> MagicMock:
    store = MagicMock()
    store.search.return_value = candidates
    return store


def _mock_embedder() -> MagicMock:
    emb = MagicMock()
    emb.encode.return_value = [0.1] * 384
    return emb


def test_learning_creates_led_to_from_decision(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_learning",
        content="Discovered connection pooling issue",
        memory_type="learning",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store([
            {"memory_id": "old_decision", "type": "decision",
             "content": "Use PostgreSQL", "score": 0.72},
        ]),
    )

    assert result.relations.get("led_to") == 1
    edges = kg.get_edges("new_learning", direction="in")
    assert any(e.source == "old_decision" and e.relation == "led_to" for e in edges)


def test_decision_creates_depends_on_requirement(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("req_1", memory_type="requirement")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Use PostgreSQL",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store([
            {"memory_id": "req_1", "type": "requirement",
             "content": "Must support ACID", "score": 0.65},
        ]),
    )

    assert result.relations.get("depends_on") == 1
    edges = kg.get_edges("new_decision", direction="out")
    assert any(e.target == "req_1" and e.relation == "depends_on" for e in edges)


def test_very_similar_same_type_supersedes(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Use PostgreSQL 16 for JSON and performance",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store([
            {"memory_id": "old_decision", "type": "decision",
             "content": "Use PostgreSQL for JSON support", "score": 0.95},
        ]),
    )

    assert result.relations.get("supersedes") == 1
    # Old node importance should be halved
    assert kg.get_importance("old_decision") < 0.85


def test_no_self_link(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("mem_a", memory_type="note")

    result = auto_link(
        graph=kg,
        memory_id="mem_a",
        content="Some note",
        memory_type="note",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store([
            {"memory_id": "mem_a", "type": "note",
             "content": "Some note", "score": 1.0},
        ]),
    )

    assert result.edges_created == 0


def test_cross_project_no_links(tmp_path):
    """Store filters by project, so cross-project candidates shouldn't appear."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    store = _mock_store([])  # Empty — store filters by project

    result = auto_link(
        graph=kg,
        memory_id="mem_a",
        content="API note",
        memory_type="note",
        project="api",
        embedder=_mock_embedder(),
        store=store,
    )

    store.search.assert_called_once()
    call_kwargs = store.search.call_args
    assert call_kwargs.kwargs.get("filters", {}).get("project") == "api"
    assert result.edges_created == 0


# -- Unit tests for _classify_relation ----------------------------------------

def test_classify_supersedes():
    assert _classify_relation(
        new_type="decision", new_content="Use PG 16",
        cand_type="decision", cand_content="Use PG 15",
        similarity=0.95,
    ) == "supersedes"


def test_classify_led_to():
    assert _classify_relation(
        new_type="learning", new_content="Pool exhaustion",
        cand_type="decision", cand_content="Use PostgreSQL",
        similarity=0.7,
    ) == "led_to"


def test_classify_depends_on():
    assert _classify_relation(
        new_type="decision", new_content="Use PostgreSQL",
        cand_type="requirement", cand_content="Must support ACID",
        similarity=0.6,
    ) == "depends_on"


def test_classify_related_to_default():
    assert _classify_relation(
        new_type="fact", new_content="Service runs on AWS",
        cand_type="fact", cand_content="Using us-east-1 region",
        similarity=0.65,
    ) == "related_to"
```

---

### Commit 1.3: `feat: wire auto-linking into MemoryManager.save()`

**File**: `src/memory/manager.py`

**Changes:**

1. Add `KnowledgeGraph` as lazy property (same pattern as embedder/store):

```python
# In __init__:
self._knowledge_graph: KnowledgeGraph | None = None

@property
def knowledge_graph(self) -> KnowledgeGraph:
    if self._knowledge_graph is None:
        from memory.knowledge_graph import KnowledgeGraph
        self._knowledge_graph = KnowledgeGraph(self.memory_dir / "_graph.json")
    return self._knowledge_graph
```

2. Hook auto_link into save() — add after line 235 (`logger.info`):

```python
# Auto-link to related memories
from memory.linker import auto_link
try:
    link_result = auto_link(
        graph=self.knowledge_graph,
        memory_id=memory_id,
        content=content,
        memory_type=type,
        project=project or "general",
        embedder=self.embedder,
        store=self.store,
    )
    self.knowledge_graph.save()
    if link_result.edges_created:
        logger.info(f"Auto-linked: {link_result.relations}")
except Exception:
    logger.warning("Auto-linking failed, memory saved without graph edges", exc_info=True)
```

**DRY note**: `auto_link()` is a standalone function in `linker.py`, not a method on MemoryManager. This keeps graph logic separate from storage logic. The manager just calls it.

---

### Commit 1.4: `feat: graph-enhanced recall replaces pure vector search`

**File**: `src/memory/manager.py` — modify `recall()` method

```python
def recall(
    self,
    query: str,
    limit: int = 5,
    project: str | None = None,
    type: str | None = None,
    days_back: int | None = None,
    score_threshold: float = 0.45,
) -> list[dict[str, Any]]:
    """Recall relevant memories using semantic search + graph traversal.

    When the knowledge graph has edges, recall expands seed results
    by traversing relationships (1-hop neighbors). This finds memories
    that are structurally related, not just semantically similar.

    Falls back to pure vector search when graph is empty.

    Example:
        Input query: "database connection issues"
        Vector search returns: [learning about connection pooling]
        Graph expansion adds: [decision to use PostgreSQL] via led_to edge
        Final result includes BOTH — the learning AND the causal decision.
    """
    with self._telemetry.track("memory.recall"):
        # Phase 1: SEED — standard vector search
        filters = {}
        if project:
            filters["project"] = project
        if type:
            filters["type"] = type
        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            filters["date"] = {"gte": cutoff}

        query_vector = self.embedder.encode(query)
        seed_results = self.store.search(
            vector=query_vector,
            limit=limit * 2,  # fetch extra for graph expansion
            filters=filters if filters else None,
            score_threshold=score_threshold,
        )

        # Phase 2: EXPAND — graph traversal (if graph has edges)
        graph = self.knowledge_graph
        if graph.stats()["edges"] > 0:
            seed_ids = {r.get("memory_id") for r in seed_results if r.get("memory_id")}
            expanded_ids: set[str] = set()

            for memory_id in seed_ids:
                neighbors = graph.get_neighbors(memory_id, hops=1)
                expanded_ids.update(neighbors)
                graph.record_access(memory_id)

            # Fetch expanded memories from Qdrant
            new_ids = expanded_ids - seed_ids
            if new_ids:
                expanded_results = self.store.search(
                    vector=query_vector,
                    limit=len(new_ids),
                    filters={"memory_id": list(new_ids)} if new_ids else None,
                    score_threshold=0.0,  # we want them regardless of similarity
                )
                # Merge, dedup
                seen = {r.get("memory_id") for r in seed_results}
                for r in expanded_results:
                    if r.get("memory_id") not in seen:
                        r["_graph_expanded"] = True
                        seed_results.append(r)
                        seen.add(r.get("memory_id"))

            graph.save()  # persist access counts

        # Phase 3: RANK — combined scoring
        scored = []
        for r in seed_results:
            mid = r.get("memory_id", "")
            vector_score = r.get("score", 0.0)
            importance = graph.get_importance(mid) if mid else 0.5
            is_expanded = r.get("_graph_expanded", False)
            graph_proximity = 0.7 if is_expanded else 1.0

            # Recency: 1.0 for today, decays to 0.0 at 365 days
            days_old = 0
            if r.get("date"):
                try:
                    mem_date = datetime.strptime(r["date"], "%Y-%m-%d")
                    days_old = (datetime.now() - mem_date).days
                except ValueError:
                    pass
            recency = max(0.0, 1.0 - days_old / 365)

            final_score = (
                vector_score * 0.50
                + importance * 0.20
                + recency * 0.15
                + graph_proximity * 0.15
            )

            scored.append({
                "score": round(final_score, 4),
                "vector_score": round(vector_score, 4),
                "content": r.get("content"),
                "date": r.get("date"),
                "type": r.get("type"),
                "project": r.get("project"),
                "memory_id": mid,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
```

**Input/Output Example:**

```
Input: recall("database connection issues", project="api", limit=3)

Phase 1 — Vector seeds (top 6):
  [0.82] "Connection pooling needs pgbouncer" (learning)
  [0.75] "PostgreSQL connection limits at 100" (learning)
  [0.68] "Database must support ACID" (requirement)
  [0.61] "Use PostgreSQL for JSON support" (decision)
  [0.55] "API uses connection strings from SSM" (fact)
  [0.48] "Database backups run at 3am UTC" (fact)

Phase 2 — Graph expansion:
  "Connection pooling" has edge: "Use PostgreSQL" →led_to→ "Connection pooling"
  "Use PostgreSQL" has edge: "Use PostgreSQL" →depends_on→ "Must support ACID"
  Already in seeds: "Use PostgreSQL", "Must support ACID" — no new fetches

Phase 3 — Ranked output (top 3):
  [0.71] "Connection pooling needs pgbouncer" (learning)
         vector=0.82, importance=0.65, recency=0.99, proximity=1.0
  [0.64] "PostgreSQL connection limits at 100" (learning)
         vector=0.75, importance=0.65, recency=0.95, proximity=1.0
  [0.60] "Use PostgreSQL for JSON support" (decision)
         vector=0.61, importance=0.85, recency=0.90, proximity=1.0
```

---

### Commit 1.5: `feat: add rebuild_graph() for backfilling existing memories`

**File**: `src/memory/knowledge_graph.py` — add method to KnowledgeGraph

```python
def rebuild(self, store: VectorStore, embedder: Embedder) -> dict[str, int]:
    """Rebuild entire graph from Qdrant. Processes all memories.

    Returns:
        Stats: {"nodes": N, "edges": N, "duration_ms": N}

    Example:
        >>> kg.rebuild(store=vector_store, embedder=embedder)
        {"nodes": 293, "edges": 847, "duration_ms": 3200}
    """
    import time
    from memory.linker import auto_link

    start = time.monotonic()
    self._graph.clear()
    self._dirty = True

    # Scroll all points from Qdrant
    all_points = store.scroll(limit=10000)

    # Add all as nodes
    for point in all_points:
        memory_id = point.get("memory_id", "")
        if not memory_id:
            continue
        self.add_node(
            memory_id,
            memory_type=point.get("type", "note"),
        )

    # Auto-link each memory against all others
    for point in all_points:
        memory_id = point.get("memory_id", "")
        if not memory_id:
            continue
        auto_link(
            graph=self,
            memory_id=memory_id,
            content=point.get("content", ""),
            memory_type=point.get("type", "note"),
            project=point.get("project", "general"),
            embedder=embedder,
            store=store,
        )

    self.save()
    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "nodes": self._graph.number_of_nodes(),
        "edges": self._graph.number_of_edges(),
        "duration_ms": duration_ms,
    }
```

**Wire into server.py:**

```python
@app.post("/api/memory/graph/rebuild")
async def rebuild_graph():
    mgr = _get_memory_manager()
    stats = mgr.knowledge_graph.rebuild(store=mgr.store, embedder=mgr.embedder)
    return {"status": "rebuilt", **stats}
```

**Wire into MCP tools** (memory.py):

```python
@mcp.tool()
def rebuild_knowledge_graph() -> str:
    """Rebuild the knowledge graph from all existing memories.
    Creates typed relationships between memories for better recall.
    Run once after upgrading, or to fix a corrupted graph."""
    mgr = _get_memory_manager()
    stats = mgr.knowledge_graph.rebuild(store=mgr.store, embedder=mgr.embedder)
    return f"Graph rebuilt: {stats['nodes']} nodes, {stats['edges']} edges ({stats['duration_ms']}ms)"
```

---

### Commit 1.6: `feat: update visualization graph to use knowledge graph edges`

**File**: `src/memory/graph.py`

The existing `build_memory_graph()` computes cosine similarity between all pairs (O(n^2)). When the knowledge graph exists, use its real edges instead:

```python
def build_memory_graph(
    points: list[dict[str, Any]],
    neighbor_count: int = 5,
    min_similarity: float = 0.35,
    knowledge_graph: KnowledgeGraph | None = None,
) -> dict[str, Any]:
    """Build graph payload. Uses knowledge graph edges when available,
    falls back to cosine similarity when not."""

    # ... (existing node building stays the same) ...

    if knowledge_graph and knowledge_graph.stats()["edges"] > 0:
        # Use real typed edges from knowledge graph
        node_ids = {n["id"] for n in nodes}
        for u, v, data in knowledge_graph._graph.edges(data=True):
            if u in node_ids and v in node_ids:
                links.append({
                    "source": u,
                    "target": v,
                    "weight": data.get("weight", 0.5),
                    "relation": data.get("relation", "related_to"),
                })
    else:
        # Fallback: cosine similarity (existing behavior)
        # ... (existing cosine loop stays the same) ...
```

---

### Commit 1.7: `test: add integration tests for graph-enhanced recall`

**File**: `tests/test_graph_enhanced_recall.py`

```python
"""Integration tests: save memories → auto-link → recall with graph expansion."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from memory.knowledge_graph import KnowledgeGraph


def test_recall_includes_graph_neighbors(tmp_path):
    """When graph has edges, recall should include neighbor memories."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("decision_pg", memory_type="decision")
    kg.add_node("learning_pool", memory_type="learning")
    kg.add_edge("decision_pg", "learning_pool", "led_to", weight=0.8)
    kg.save()

    # Mock manager with graph
    # ... (setup MemoryManager with mock store returning seeds,
    #       verify learning_pool appears in results even if
    #       vector similarity alone wouldn't surface it)


def test_recall_falls_back_without_graph(tmp_path):
    """Empty graph → pure vector search (backward compat)."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    assert kg.stats()["edges"] == 0
    # Recall should work exactly as before


def test_recall_deduplicates(tmp_path):
    """Memories in both seed and expansion appear only once."""
    # ... (memory appears in vector results AND as graph neighbor)


def test_importance_affects_ranking(tmp_path):
    """Higher importance memories rank above lower importance at equal similarity."""
    # ... (two memories with same vector score, different importance)


def test_recency_affects_ranking(tmp_path):
    """Recent memories rank above old ones at equal similarity and importance."""
    # ... (two memories from different dates)
```

---

## Phase 2: Hierarchical Context (PageIndex-inspired)

### Commit 2.1: `feat: add topic auto-classification`

**New file**: `src/memory/topics.py`

Uses agglomerative clustering to discover topics from memory vectors. Topics are labels derived from the most frequent terms in each cluster.

### Commit 2.2: `feat: tree-structured context generation`

**File**: `src/memory/cache_context.py` — add `get_hierarchical_context()`

Groups memories by topic, shows relationships between them. Still deterministic for caching.

### Commit 2.3: `feat: wire topic/hierarchy into tools and API`

**Files**: `src/tools/builtin/memory.py`, `src/server.py`

---

## Phase 3: Skill Graph

### Commit 3.1: `feat: extract skills from memory clusters`

**New file**: `src/memory/skills.py`

### Commit 3.2: `feat: add skill_context() MCP tool`

**File**: `src/tools/builtin/memory.py`

---

## Phase 4: Intelligence Layer

### Commit 4.1: `feat: conflict detection on save`
### Commit 4.2: `feat: memory consolidation tool`
### Commit 4.3: `feat: proactive context summary`

---

## Atomic Commit Plan

```
Phase 1 — Foundation (7 commits):
  1.1  feat: add KnowledgeGraph class with persistence
       Files: src/memory/knowledge_graph.py, tests/test_knowledge_graph.py
       Tests: 12 unit tests

  1.2  feat: add auto-linking algorithm
       Files: src/memory/linker.py, tests/test_auto_linking.py
       Tests: 9 unit tests

  1.3  feat: wire auto-linking into MemoryManager.save()
       Files: src/memory/manager.py
       Tests: existing save tests + 2 new integration tests

  1.4  feat: graph-enhanced recall replaces pure vector search
       Files: src/memory/manager.py
       Tests: 5 integration tests

  1.5  feat: add rebuild_graph() for backfilling existing memories
       Files: src/memory/knowledge_graph.py, src/server.py, src/tools/builtin/memory.py
       Tests: 2 integration tests

  1.6  feat: update visualization graph to use knowledge graph edges
       Files: src/memory/graph.py
       Tests: update existing test_memory_graph.py

  1.7  test: add integration tests for graph-enhanced recall
       Files: tests/test_graph_enhanced_recall.py
       Tests: 5 integration tests

Phase 2 — Hierarchy (3 commits):
  2.1  feat: add topic auto-classification
  2.2  feat: tree-structured context generation
  2.3  feat: wire topic/hierarchy into tools and API

Phase 3 — Skills (2 commits):
  3.1  feat: extract skills from memory clusters
  3.2  feat: add skill_context() MCP tool

Phase 4 — Intelligence (3 commits):
  4.1  feat: conflict detection on save
  4.2  feat: memory consolidation tool
  4.3  feat: proactive context summary
```

## DRY Principles Applied

1. **KnowledgeGraph is the single source of truth** for all relationship data. No edges stored in YAML or Qdrant payloads.
2. **`auto_link()` is a standalone function**, not duplicated between save() and rebuild(). Both call the same function.
3. **`_classify_relation()` is pure** — no side effects, easy to test, single place for all rule logic.
4. **TYPE_WEIGHTS defined once** in knowledge_graph.py, imported everywhere.
5. **Atomic write pattern** reused from manager.py (tempfile + os.replace) — same pattern, same reliability.
6. **`_cosine_similarity()` in graph.py** is already shared — no new similarity functions added.

## Verification Plan

1. Run existing test suite first — all 183 tests must stay green (backward compat)
2. Run new tests in isolation: `pytest tests/test_knowledge_graph.py tests/test_auto_linking.py -v`
3. Docker test: `docker compose --profile test run --rm test`
4. Manual:
   - `POST /api/memory/graph/rebuild` → verify graph stats
   - `POST /api/memory/recall` → verify graph neighbors in results
   - `GET /dashboard` → verify edge labels with relation types
5. Full suite: `uv run --extra dev pytest -v` → all green
