"""Tests for memory auto-linking rules."""

from unittest.mock import MagicMock

from memory.knowledge_graph import KnowledgeGraph
from memory.linker import _classify_relation, auto_link


def _mock_store(candidates: list[dict]) -> MagicMock:
    store = MagicMock()
    store.search.return_value = candidates
    return store


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 384
    return embedder


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
            {
                "memory_id": "old_decision",
                "type": "decision",
                "content": "Use PostgreSQL",
                "score": 0.72,
            },
        ]),
    )

    assert result.relations.get("led_to") == 1
    edges = kg.get_edges("new_learning", direction="in")
    assert any(edge.source == "old_decision" and edge.relation == "led_to" for edge in edges)


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
            {
                "memory_id": "req_1",
                "type": "requirement",
                "content": "Must support ACID",
                "score": 0.65,
            },
        ]),
    )

    assert result.relations.get("depends_on") == 1
    edges = kg.get_edges("new_decision", direction="out")
    assert any(edge.target == "req_1" and edge.relation == "depends_on" for edge in edges)


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
            {
                "memory_id": "old_decision",
                "type": "decision",
                "content": "Use PostgreSQL for JSON support",
                "score": 0.95,
            },
        ]),
    )

    assert result.relations.get("supersedes") == 1
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
            {
                "memory_id": "mem_a",
                "type": "note",
                "content": "Some note",
                "score": 1.0,
            },
        ]),
    )

    assert result.edges_created == 0


def test_cross_project_no_links(tmp_path):
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    store = _mock_store([])

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


def test_classify_supersedes():
    assert _classify_relation(
        new_type="decision",
        new_content="Use PG 16",
        cand_type="decision",
        cand_content="Use PG 15",
        similarity=0.95,
    ) == "supersedes"


def test_classify_led_to():
    assert _classify_relation(
        new_type="learning",
        new_content="Pool exhaustion",
        cand_type="decision",
        cand_content="Use PostgreSQL",
        similarity=0.7,
    ) == "led_to"


def test_classify_depends_on():
    assert _classify_relation(
        new_type="decision",
        new_content="Use PostgreSQL",
        cand_type="requirement",
        cand_content="Must support ACID",
        similarity=0.6,
    ) == "depends_on"


def test_classify_related_to_default():
    assert _classify_relation(
        new_type="fact",
        new_content="Service runs on AWS",
        cand_type="fact",
        cand_content="Using us-east-1 region",
        similarity=0.65,
    ) == "related_to"
