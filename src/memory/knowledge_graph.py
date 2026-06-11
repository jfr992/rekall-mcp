"""Persistent knowledge graph for memory relationships.

Stores typed, weighted edges between memory nodes and persists to JSON.
The graph is loaded lazily and written atomically to avoid partial writes.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    from core.embeddings import Embedder
    from core.vector_store import VectorStore


RELATION_TYPES = frozenset({
    "related_to",
    "led_to",
    "depends_on",
    "contradicts",
    "supersedes",
    "part_of",
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


class KnowledgeGraph:
    """Persistent directed graph of memory relationships."""

    def __init__(self, graph_path: Path | str) -> None:
        self._path = Path(graph_path)
        self._graph = nx.DiGraph()
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return

        with open(self._path) as file:
            data = json.load(file)

        for node_id, attrs in data.get("nodes", {}).items():
            self._graph.add_node(node_id, **attrs)

        for edge in data.get("edges", []):
            self._graph.add_edge(
                edge["source"],
                edge["target"],
                relation=edge["relation"],
                weight=edge["weight"],
                auto=edge.get("auto", True),
                created=edge.get("created", date.today().isoformat()),
            )

    def save(self) -> None:
        if not self._dirty:
            return

        data = {
            "version": GRAPH_VERSION,
            "nodes": {
                node_id: dict(self._graph.nodes[node_id]) for node_id in self._graph.nodes
            },
            "edges": [
                {
                    "source": source,
                    "target": target,
                    **self._graph.edges[source, target],
                }
                for source, target in self._graph.edges
            ],
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".json.tmp")

        try:
            with os.fdopen(fd, "w") as file:
                json.dump(data, file, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
            self._dirty = False
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

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

        if memory_id not in self._graph:
            self._graph.add_node(
                memory_id,
                topic=topic,
                importance=importance,
                access_count=0,
                last_accessed=date.today().isoformat(),
            )
            self._dirty = True
            return

        # Refresh access metadata when existing node is referenced again.
        self._graph.nodes[memory_id]["last_accessed"] = date.today().isoformat()
        self._graph.nodes[memory_id]["topic"] = topic
        self._dirty = True

    def record_access(self, memory_id: str) -> None:
        if memory_id not in self._graph:
            return

        self._graph.nodes[memory_id]["access_count"] += 1
        self._graph.nodes[memory_id]["last_accessed"] = date.today().isoformat()
        self._dirty = True

    def remove_node(self, memory_id: str) -> None:
        if memory_id in self._graph:
            self._graph.remove_node(memory_id)
            self._dirty = True

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

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
            return
        if self._graph.has_edge(source, target):
            return

        self._graph.add_edge(
            source,
            target,
            relation=relation,
            weight=weight,
            auto=auto,
            created=date.today().isoformat(),
        )
        self._dirty = True

    def get_edges(self, memory_id: str, direction: str = "both") -> list[Edge]:
        edges: list[Edge] = []

        if direction in {"out", "both"}:
            for _, target, data in self._graph.out_edges(memory_id, data=True):
                edges.append(Edge(source=memory_id, target=target, **data))

        if direction in {"in", "both"}:
            for source, _, data in self._graph.in_edges(memory_id, data=True):
                edges.append(Edge(source=source, target=memory_id, **data))

        return edges

    def count_contradicts(self, memory_id: str) -> int:
        """Count contradicts-edges incident on memory_id (in + out)."""
        if memory_id not in self._graph:
            return 0
        count = 0
        for edge in self.get_edges(memory_id, direction="both"):
            if edge.relation == "contradicts":
                count += 1
        return count

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def get_neighbors(
        self,
        memory_id: str,
        hops: int = 1,
        relation_filter: list[str] | None = None,
    ) -> list[str]:
        if memory_id not in self._graph or hops <= 0:
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

        return sorted(visited)

    def get_chain(self, memory_id: str, relation: str = "led_to", max_depth: int = 5) -> list[str]:
        chain: list[str] = []
        current = memory_id

        for _ in range(max_depth):
            successors = [
                target
                for _, target, data in self._graph.out_edges(current, data=True)
                if data["relation"] == relation
            ]

            if not successors:
                break

            current = successors[0]
            chain.append(current)

        return chain

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_importance(self, memory_id: str) -> float:
        if memory_id not in self._graph:
            return 0.0
        return self._graph.nodes[memory_id].get("importance", 0.5)

    def decay_importance(self) -> int:
        today = date.today()
        decayed = 0

        for _node_id, data in self._graph.nodes(data=True):
            last_accessed_raw = data.get("last_accessed", str(today))
            try:
                last = date.fromisoformat(last_accessed_raw)
            except ValueError:
                last = today

            days_idle = (today - last).days
            if days_idle <= 7:
                continue

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
            relation = data.get("relation", "unknown")
            relation_counts[relation] = relation_counts.get(relation, 0) + 1

        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "relations": relation_counts,
            "avg_degree": (
                sum(degree for _, degree in self._graph.degree())
                / max(self._graph.number_of_nodes(), 1)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph state for inspection."""
        return {
            "version": GRAPH_VERSION,
            "nodes": [
                {"id": node_id, **attrs}
                for node_id, attrs in self._graph.nodes(data=True)
            ],
            "edges": [
                {
                    "source": source,
                    "target": target,
                    **edge_data,
                }
                for source, target, edge_data in self._graph.edges(data=True)
            ],
        }

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def rebuild(self, store: VectorStore, embedder: Embedder) -> dict[str, int]:
        """Rebuild graph from all memories in vector store."""
        import time

        from memory.linker import auto_link

        start = time.monotonic()
        self._graph.clear()
        self._dirty = True

        all_points = store.scroll(limit=10000)

        for point in all_points:
            memory_id = point.get("memory_id", "")
            if not memory_id:
                continue
            self.add_node(
                memory_id,
                topic=point.get("project", "general"),
                memory_type=point.get("type", "note"),
            )

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

        # Apply idle-based importance decay as part of maintenance so the
        # advertised decay actually runs (previously dead code).
        decayed = self.decay_importance()

        self.save()
        duration_ms = int((time.monotonic() - start) * 1000)

        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "decayed": decayed,
            "duration_ms": duration_ms,
        }
