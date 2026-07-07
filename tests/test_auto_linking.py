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
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL",
                    "score": 0.72,
                },
            ]
        ),
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
        store=_mock_store(
            [
                {
                    "memory_id": "req_1",
                    "type": "requirement",
                    "content": "Must support ACID",
                    "score": 0.65,
                },
            ]
        ),
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
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for JSON support",
                    "score": 0.95,
                },
            ]
        ),
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
        store=_mock_store(
            [
                {
                    "memory_id": "mem_a",
                    "type": "note",
                    "content": "Some note",
                    "score": 1.0,
                },
            ]
        ),
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


def test_new_memory_contradicts_existing_memory(tmp_path):
    """A negated statement should create a contradicts relation."""
    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("old_decision", memory_type="decision")

    result = auto_link(
        graph=kg,
        memory_id="new_decision",
        content="Do not use PostgreSQL for this service anymore",
        memory_type="decision",
        project="api",
        embedder=_mock_embedder(),
        store=_mock_store(
            [
                {
                    "memory_id": "old_decision",
                    "type": "decision",
                    "content": "Use PostgreSQL for this service",
                    "score": 0.85,
                },
            ]
        ),
    )

    assert result.relations.get("contradicts") == 1
    edges = kg.get_edges("new_decision", direction="out")
    assert any(edge.target == "old_decision" and edge.relation == "contradicts" for edge in edges)


def test_classify_supersedes():
    assert (
        _classify_relation(
            new_type="decision",
            new_content="Use PG 16",
            cand_type="decision",
            cand_content="Use PG 15",
            similarity=0.95,
        )[0]
        == "supersedes"
    )


def test_classify_led_to():
    assert (
        _classify_relation(
            new_type="learning",
            new_content="Pool exhaustion",
            cand_type="decision",
            cand_content="Use PostgreSQL",
            similarity=0.7,
        )[0]
        == "led_to"
    )


def test_classify_depends_on():
    assert (
        _classify_relation(
            new_type="decision",
            new_content="Use PostgreSQL",
            cand_type="requirement",
            cand_content="Must support ACID",
            similarity=0.6,
        )[0]
        == "depends_on"
    )


def test_classify_related_to_default():
    assert (
        _classify_relation(
            new_type="fact",
            new_content="Service runs on AWS",
            cand_type="fact",
            cand_content="Using us-east-1 region",
            similarity=0.65,
        )[0]
        == "related_to"
    )


def test_classify_contradicts():
    assert (
        _classify_relation(
            new_type="decision",
            new_content="Do not enable this endpoint",
            cand_type="decision",
            cand_content="Enable this endpoint for admin users",
            similarity=0.8,
        )[0]
        == "contradicts"
    )


def test_classify_no_contradiction_without_overlap():
    assert (
        _classify_relation(
            new_type="decision",
            new_content="Do not use Redis cache",
            cand_type="note",
            cand_content="Deploy with two-node Postgres cluster",
            similarity=0.9,
        )[0]
        == "related_to"
    )


# -- Contradiction false positive regression tests ----------------------------


def test_complementary_learnings_not_contradictions():
    """Two learnings about the same topic (LogFleet) that complement each other
    should NOT be classified as contradictions, even if one contains 'removed'."""
    assert (
        _classify_relation(
            new_type="learning",
            new_content=(
                "Deployed LogFleet cloud stack to kind cluster: built API image, "
                "loaded with kind load docker-image, created deploy manifests"
            ),
            cand_type="learning",
            cand_content=(
                "LogFleet kind cluster setup requires: Build local image with "
                "docker build, create namespace, apply manifests"
            ),
            similarity=0.82,
        )[0]
        == "related_to"
    )


def test_requirement_and_plan_not_contradictions():
    """A requirement and its implementation plan should not conflict."""
    assert (
        _classify_relation(
            new_type="requirement",
            new_content=(
                "REMINDER: Create tickets for Phase 1 observability implementation. "
                "Required tickets: Configure infrastructure alerts"
            ),
            cand_type="decision",
            cand_content=(
                "Observability stack requires 3 phases to reach full production "
                "readiness: Phase 1 - Configure infrastructure alerting"
            ),
            similarity=0.76,
        )[0]
        == "related_to"
    )


def test_similar_learnings_about_same_tool_not_contradictions():
    """Two ACLI Jira learnings that add detail should not conflict."""
    assert (
        _classify_relation(
            new_type="learning",
            new_content=(
                "ACLI Jira bulk ticket creation: descriptions must be single-line, "
                "Spike is not a standard issue type - use Story instead"
            ),
            cand_type="learning",
            cand_content=(
                "Special characters backticks quotes in Jira ticket summaries "
                "cause ACLI bulk creation failures"
            ),
            similarity=0.70,
        )[0]
        == "related_to"
    )


def test_real_contradiction_still_detected():
    """Genuinely opposing statements should still be caught."""
    assert (
        _classify_relation(
            new_type="learning",
            new_content=(
                "Port deployment_time timestamps are stored in UTC. "
                "To schedule for EST time, add 5 hours before sending."
            ),
            cand_type="learning",
            cand_content=(
                "Port deployment_time must be in EST not UTC. Use TZ=America/New_York date format."
            ),
            similarity=0.70,
        )[0]
        == "contradicts"
    )


def test_low_overlap_negation_not_contradiction():
    """A negation in content with only 1 shared word should not trigger contradiction."""
    assert (
        _classify_relation(
            new_type="fact",
            new_content="Removed the old logging configuration from the server",
            cand_type="fact",
            cand_content="Server runs on port 8000 with HTTP transport",
            similarity=0.65,
        )[0]
        == "related_to"
    )
