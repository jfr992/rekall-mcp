"""Tests for KnowledgeGraph persistence, traversal, and analysis."""

import json
from pathlib import Path

from memory.knowledge_graph import TYPE_WEIGHTS, KnowledgeGraph


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

    kg2 = _tmp_graph(tmp_path)
    assert kg2.stats()["nodes"] == 2
    assert kg2.stats()["edges"] == 1

    edges = kg2.get_edges("mem_a", direction="out")
    assert len(edges) == 1
    assert edges[0].relation == "led_to"
    assert edges[0].weight == 0.8


def test_atomic_write_no_partial(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a", memory_type="fact")
    kg.save()

    original = (tmp_path / "_graph.json").read_text()
    assert not list(tmp_path.glob("*.json.tmp"))
    assert json.loads(original)["nodes"]


# -- Node Operations ----------------------------------------------------------


def test_add_node_uses_type_weight(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("mem_a", memory_type="requirement")

    assert kg.get_importance("mem_a") == TYPE_WEIGHTS["requirement"]


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

    kg.save()
    with open(tmp_path / "_graph.json") as file:
        data = json.load(file)

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
    kg.add_edge("a", "b", "led_to", 0.8)

    assert kg.stats()["edges"] == 1


def test_invalid_relation_raises(tmp_path):
    kg = _tmp_graph(tmp_path)
    kg.add_node("a")
    kg.add_node("b")

    import pytest

    with pytest.raises(ValueError, match="Unknown relation"):
        kg.add_edge("a", "b", "invented_relation", 0.5)


# -- Traversal ----------------------------------------------------------------


def test_get_neighbors_one_hop(tmp_path):
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)
    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("b", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=1)

    assert set(neighbors) == {"b"}


def test_get_neighbors_two_hops(tmp_path):
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)

    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("b", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=2)

    assert set(neighbors) == {"b", "c"}


def test_get_neighbors_with_relation_filter(tmp_path):
    kg = _tmp_graph(tmp_path)
    for n in "abc":
        kg.add_node(n)

    kg.add_edge("a", "b", "related_to", 0.7)
    kg.add_edge("a", "c", "led_to", 0.6)

    neighbors = kg.get_neighbors("a", hops=1, relation_filter=["led_to"])

    assert neighbors == ["c"]


def test_get_chain_follows_relation(tmp_path):
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
    from datetime import date as date_cls
    from unittest.mock import patch

    kg = _tmp_graph(tmp_path)
    kg.add_node("old_mem", memory_type="decision")
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
    assert stats["relations"] == {
        "related_to": 1,
        "led_to": 1,
        "depends_on": 1,
    }
