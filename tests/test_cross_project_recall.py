from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


def test_cross_project_recall_labels_scope(tmp_path):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")

    def fake_recall(query, limit=5, project=None, type=None, days_back=None, score_threshold=0.45):
        if project == "byte-edge":
            return [
                {
                    "memory_id": "same",
                    "project": "byte-edge",
                    "content": "Same project Longhorn rule",
                    "score": 0.9,
                }
            ]
        if project is None:
            return [
                {
                    "memory_id": "same",
                    "project": "byte-edge",
                    "content": "Same project Longhorn rule",
                    "score": 0.9,
                },
                {
                    "memory_id": "related",
                    "project": "byte-secrets-operator",
                    "content": "Related namespace policy",
                    "score": 0.8,
                },
                {
                    "memory_id": "global",
                    "project": "general",
                    "content": "Back up hooks before editing",
                    "score": 0.7,
                },
            ]
        return []

    manager.recall = fake_recall

    result = manager.recall_cross_project(
        "Longhorn namespace policy",
        current_project="byte-edge",
        limit=3,
    )

    assert result["current_project"] == "byte-edge"
    assert result["same_project"][0]["memory_id"] == "same"
    assert result["same_project"][0]["scope"] == "same_project"
    assert result["related_projects"][0]["scope"] == "related_project"
    assert result["global"][0]["scope"] == "global"


@pytest.fixture
def fake_manager(monkeypatch):

    fake = MagicMock()
    fake.recall_cross_project.return_value = {
        "query": "Longhorn namespace policy",
        "current_project": "byte-edge",
        "same_project": [{"memory_id": "same", "scope": "same_project"}],
        "related_projects": [{"memory_id": "related", "scope": "related_project"}],
        "global": [{"memory_id": "global", "scope": "global"}],
    }
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.fixture
def client():
    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_cross_project_recall_endpoint_returns_grouped_results(client, fake_manager):
    response = client.post(
        "/api/memory/recall/cross-project",
        json={"query": "Longhorn namespace policy", "current_project": "byte-edge", "limit": 3},
    )

    assert response.status_code == 200
    assert response.json()["related_projects"][0]["scope"] == "related_project"
    fake_manager.recall_cross_project.assert_called_once_with(
        query="Longhorn namespace policy",
        current_project="byte-edge",
        limit=3,
    )


def test_cross_project_recall_endpoint_requires_current_project(client, fake_manager):
    response = client.post("/api/memory/recall/cross-project", json={"query": "Longhorn"})

    assert response.status_code == 400
    fake_manager.recall_cross_project.assert_not_called()


def test_cross_project_recall_endpoint_rejects_non_string_query(client, fake_manager):
    response = client.post(
        "/api/memory/recall/cross-project",
        json={"query": 123, "current_project": "byte-edge"},
    )

    assert response.status_code == 400
    fake_manager.recall_cross_project.assert_not_called()


@pytest.mark.asyncio
async def test_recall_across_projects_tool_formats_sections(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.recall_cross_project.return_value = {
        "same_project": [{"project": "byte-edge", "content": "Same project Longhorn rule"}],
        "related_projects": [
            {"project": "byte-secrets-operator", "content": "Related namespace policy"}
        ],
        "global": [{"project": "general", "content": "Back up hooks before editing"}],
    }

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    rendered = await registered_tools["recall_across_projects"](
        query="Longhorn namespace policy",
        current_project="byte-edge",
        limit=3,
    )

    assert "## Same Project" in rendered
    assert "## Related Projects" in rendered
    assert "## Global" in rendered
    manager.recall_cross_project.assert_called_once_with(
        query="Longhorn namespace policy",
        current_project="byte-edge",
        limit=3,
    )
