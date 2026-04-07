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

    def test_topics_to_json_can_have_params_merged(self):
        result = topics_to_json([], project="test")
        result["params"] = {"limit": 200, "max_topics": 12, "similarity_threshold": 0.72}
        assert result["params"]["limit"] == 200
        assert result["params"]["max_topics"] == 12
        assert result["params"]["similarity_threshold"] == 0.72


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

    def test_returns_project_field(self, manager):
        manager._store.scroll.return_value = []
        result = manager.consolidate_memories_json(project="my-proj", limit=10)

        assert result["project"] == "my-proj"

    def test_project_all_when_none(self, manager):
        manager._store.scroll.return_value = []
        result = manager.consolidate_memories_json(project=None, limit=10)

        assert result["project"] == "all"

    def test_superseded_entry_shape(self, manager):
        """Superseded entries have newer/older/score keys with memory summaries."""
        from unittest.mock import MagicMock

        # Set up two points in the scroll result
        manager._store.scroll.return_value = [
            {
                "memory_id": "2026-01-02_decision_bbb",
                "content": "New decision",
                "type": "decision",
                "date": "2026-01-02",
                "project": "test",
            },
            {
                "memory_id": "2026-01-01_decision_aaa",
                "content": "Old decision",
                "type": "decision",
                "date": "2026-01-01",
                "project": "test",
            },
        ]

        # Inject a fake edge: bbb supersedes aaa
        mock_edge = MagicMock()
        mock_edge.source = "2026-01-02_decision_bbb"
        mock_edge.target = "2026-01-01_decision_aaa"
        mock_edge.relation = "supersedes"
        mock_edge.weight = 0.9

        manager.knowledge_graph.get_edges = MagicMock(
            side_effect=lambda mid, direction: [mock_edge] if mid == "2026-01-02_decision_bbb" else []
        )

        result = manager.consolidate_memories_json(project=None, limit=10)

        assert len(result["superseded"]) == 1
        entry = result["superseded"][0]
        assert "newer" in entry
        assert "older" in entry
        assert "score" in entry
        assert entry["score"] == 0.9
        assert entry["newer"]["memory_id"] == "2026-01-02_decision_bbb"
        assert entry["older"]["memory_id"] == "2026-01-01_decision_aaa"

    def test_conflicts_entry_shape(self, manager):
        """Conflict entries have a/b/score keys."""
        from unittest.mock import MagicMock

        manager._store.scroll.return_value = [
            {
                "memory_id": "2026-01-01_fact_aaa",
                "content": "Fact A",
                "type": "fact",
                "date": "2026-01-01",
                "project": "test",
            },
            {
                "memory_id": "2026-01-02_fact_bbb",
                "content": "Fact B",
                "type": "fact",
                "date": "2026-01-02",
                "project": "test",
            },
        ]

        mock_edge = MagicMock()
        mock_edge.source = "2026-01-01_fact_aaa"
        mock_edge.target = "2026-01-02_fact_bbb"
        mock_edge.relation = "contradicts"
        mock_edge.weight = 0.75

        manager.knowledge_graph.get_edges = MagicMock(
            side_effect=lambda mid, direction: [mock_edge] if mid == "2026-01-01_fact_aaa" else []
        )

        result = manager.consolidate_memories_json(project=None, limit=10)

        assert len(result["conflicts"]) == 1
        entry = result["conflicts"][0]
        assert "a" in entry
        assert "b" in entry
        assert "score" in entry
        assert entry["score"] == 0.75


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

    def test_get_topic_detail_returns_structure(self, manager):
        from memory.topics import TopicCluster

        cluster = TopicCluster(
            topic_id="topic_0",
            label="Database",
            memories=[
                {
                    "memory_id": "2026-01-01_decision_aaa",
                    "content": "Chose PostgreSQL",
                    "type": "decision",
                    "date": "2026-01-01",
                    "project": "test",
                },
                {
                    "memory_id": "2026-01-02_fact_bbb",
                    "content": "PostgreSQL on port 5432",
                    "type": "fact",
                    "date": "2026-01-02",
                    "project": "test",
                },
            ],
        )
        result = manager.get_topic_detail(cluster)

        assert result["topic"] == "Database"
        assert result["memory_count"] == 2
        assert len(result["memories"]) == 2
        assert "connections" in result["memories"][0]
        assert isinstance(result["memories"][0]["connections"], list)
        assert result["memories"][0]["memory_id"] == "2026-01-01_decision_aaa"
        assert result["memories"][0]["content"] == "Chose PostgreSQL"

    def test_get_topic_detail_with_connections(self, manager):
        from memory.topics import TopicCluster
        from unittest.mock import MagicMock
        from types import SimpleNamespace

        cluster = TopicCluster(
            topic_id="topic_0",
            label="Database",
            memories=[
                {
                    "memory_id": "mem_aaa",
                    "content": "Chose PostgreSQL",
                    "type": "decision",
                    "date": "2026-01-01",
                    "project": "test",
                },
            ],
        )

        # Mock knowledge graph with an edge
        mock_graph = MagicMock()
        edge = SimpleNamespace(
            source="mem_aaa",
            target="mem_bbb",
            relation="led_to",
            weight=0.85,
        )
        mock_graph.get_edges.return_value = [edge]
        manager._knowledge_graph = mock_graph

        # Mock store to return the neighbor
        manager._store.scroll.return_value = [
            {
                "memory_id": "mem_bbb",
                "content": "PostgreSQL JSONB indexing is fast",
                "type": "learning",
                "date": "2026-01-05",
                "project": "test",
            }
        ]

        result = manager.get_topic_detail(cluster)

        assert len(result["memories"]) == 1
        conns = result["memories"][0]["connections"]
        assert len(conns) == 1
        assert conns[0]["memory_id"] == "mem_bbb"
        assert conns[0]["relation"] == "led_to"
        assert conns[0]["weight"] == 0.85
        assert conns[0]["type"] == "learning"
        assert "PostgreSQL JSONB" in conns[0]["content"]
