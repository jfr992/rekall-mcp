"""Tests for topic discovery and hierarchy rendering."""

from memory.topics import build_topic_clusters, render_hierarchical_context


def test_vectors_form_fewer_clusters_when_similar():
    """Agglomerative similarity should merge close vectors into one topic."""
    points = [
        {"memory_id": "a", "content": "PostgreSQL JSON query tuning", "vector": [1.0, 0.01, 0.0]},
        {"memory_id": "b", "content": "PostgreSQL indexing and tuning", "vector": [0.99, 0.02, 0.01]},
        {"memory_id": "c", "content": "CSS button layout", "vector": [-1.0, 0.0, 0.0]},
    ]

    topics = build_topic_clusters(points, similarity_threshold=0.75)

    assert len(topics) == 2
    assert any("postgre" in topic.label.lower() for topic in topics)


def test_topic_label_derived_from_frequent_terms():
    """Labels should include frequent terms from cluster contents."""
    points = [
        {"memory_id": "a", "content": "PostgreSQL query planner", "vector": [1.0, 0.0, 0.0]},
        {"memory_id": "b", "content": "PostgreSQL partition planning", "vector": [0.99, 0.01, 0.0]},
    ]

    topics = build_topic_clusters(points, similarity_threshold=0.8)

    assert len(topics) == 1
    assert "postgresql" in topics[0].label


def test_topics_honour_max_topic_limit():
    """max_topics should cap returned cluster count."""
    points = [
        {"memory_id": "a", "content": "Memory about auth", "vector": [1.0, 0.0, 0.0]},
        {"memory_id": "b", "content": "Memory about billing", "vector": [0.0, 1.0, 0.0]},
        {"memory_id": "c", "content": "Memory about caching", "vector": [0.0, 0.0, 1.0]},
        {"memory_id": "d", "content": "Memory about deploy", "vector": [-1.0, 0.0, 0.0]},
    ]

    topics = build_topic_clusters(points, similarity_threshold=0.95, max_topics=2)

    assert len(topics) == 2


def test_render_hierarchical_context_is_stable():
    """Renderer should always return markdown headings and memory entries."""
    topics = build_topic_clusters(
        [
            {"memory_id": "a", "content": "PostgreSQL query tuning", "vector": [1.0, 0.0, 0.0]},
            {"memory_id": "b", "content": "PostgreSQL partition planning", "vector": [0.98, 0.0, 0.0]},
        ],
        similarity_threshold=0.9,
    )

    context = render_hierarchical_context(topics, project="api")

    assert "# Hierarchical Context: api" in context
    assert "##" in context
    assert "PostgreSQL" in context
