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
