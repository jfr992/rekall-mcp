"""Tests for memory graph generation."""


def _graph(points, **kwargs):
    """Build graph from memory points with helpers."""
    from memory.graph import build_memory_graph

    return build_memory_graph(points, **kwargs)


def test_build_memory_graph_returns_nodes_and_links():
    """Graph builder should emit nodes and links for embeddable points."""
    points = [
        {
            "memory_id": "a",
            "content": "Decision: use PostgreSQL",
            "project": "api",
            "type": "decision",
            "date": "2026-02-01",
            "vector": [0.1, 0.2, 0.3, 0.4],
        },
        {
            "memory_id": "b",
            "content": "Learning: issue with trailing slash",
            "project": "api",
            "type": "learning",
            "date": "2026-02-02",
            "vector": [0.11, 0.19, 0.31, 0.42],
        },
        {
            "memory_id": "c",
            "content": "Fact: service is in AWS",
            "project": "api",
            "type": "fact",
            "date": "2026-02-03",
            "vector": [-0.22, 0.01, 0.13, -0.4],
        },
    ]

    result = _graph(points)

    assert "nodes" in result
    assert "links" in result
    assert len(result["nodes"]) == 3
    assert result["stats"]["nodes"] == 3
    assert result["stats"]["dimensions"] == 4
    assert all("position" in node for node in result["nodes"])


def test_build_memory_graph_filters_similarity_threshold():
    """Links should honor minimum similarity threshold."""
    points = [
        {
            "memory_id": "a",
            "content": "same meaning 1",
            "vector": [1.0, 0.0, 0.0],
            "type": "note",
        },
        {
            "memory_id": "b",
            "content": "same meaning 2",
            "vector": [1.0, 0.0, 0.0],
            "type": "note",
        },
        {
            "memory_id": "c",
            "content": "opposite",
            "vector": [-1.0, 0.0, 0.0],
            "type": "note",
        },
    ]

    result = _graph(points, neighbor_count=2, min_similarity=0.9)

    assert len(result["nodes"]) == 3
    assert any(link["source"] == "a" and link["target"] == "b" for link in result["links"])
    assert not any(link["source"] == "a" and link["target"] == "c" for link in result["links"])


def test_graph_ignores_missing_vectors():
    """Points without vectors are ignored."""
    points = [
        {"memory_id": "a", "content": "has vector", "vector": [0.1, 0.2, 0.3]},
        {"memory_id": "b", "content": "missing vector"},
    ]

    result = _graph(points, min_similarity=0.1)

    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == "a"


def test_build_memory_graph_prefers_knowledge_graph_edges(tmp_path):
    """Graph builder should prefer explicit knowledge graph edges when available."""
    from memory.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(tmp_path / "_graph.json")
    kg.add_node("a")
    kg.add_node("b")
    kg.add_edge("a", "b", "led_to", weight=0.9)

    result = _graph(
        [
            {
                "memory_id": "a",
                "vector": [1.0, 0.0],
                "type": "decision",
            },
            {
                "memory_id": "b",
                "vector": [1.0, 0.0],
                "type": "learning",
            },
        ],
        knowledge_graph=kg,
        min_similarity=1.0,
    )

    assert len(result["links"]) == 1
    assert result["links"][0]["source"] == "a"
    assert result["links"][0]["target"] == "b"
    assert result["links"][0]["relation"] == "led_to"
