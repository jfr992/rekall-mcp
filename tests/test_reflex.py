import json
from unittest.mock import MagicMock

import pytest


def test_detect_reflex_cues_for_iac_and_memory():
    from memory.reflex import detect_reflex_cues

    cues = detect_reflex_cues("Run terraform apply after backing up Qdrant memory")

    assert "iac" in cues
    assert "memory_data" in cues


def test_reflex_packet_queries_cue_specific_memory():
    from memory.reflex import build_reflex_packet

    calls = []

    class Manager:
        def recall(self, query, limit=4, project=None, score_threshold=0.45, **kwargs):
            calls.append((query, project, limit, score_threshold))
            return [
                {
                    "memory_id": "m1",
                    "content": "Back up memory before Qdrant cleanup",
                    "project": project or "general",
                }
            ]

    packet = build_reflex_packet(
        Manager(),
        text="docker compose stop qdrant before cleanup",
        project="rekall-mcp",
    )

    assert "memory_data" in packet["cues"]
    assert packet["memories"][0]["reason"] == "memory_data"
    assert calls[0][1] == "rekall-mcp"


def test_reflex_packet_deduplicates_memories_and_respects_limit():
    from memory.reflex import build_reflex_packet

    class Manager:
        def recall(self, query, limit=4, project=None, score_threshold=0.45, **kwargs):
            return [
                {"memory_id": "shared", "content": "Back up before risky changes"},
                {"memory_id": query, "content": query},
            ]

    packet = build_reflex_packet(
        Manager(),
        text="terraform touches qdrant and hooks",
        project="rekall-mcp",
        limit=2,
    )

    assert len(packet["memories"]) == 2
    assert [memory["memory_id"] for memory in packet["memories"]].count("shared") == 1


class JsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_api_memory_reflex_returns_packet(monkeypatch):
    from server import api_memory_reflex

    manager = MagicMock()
    manager.reflex.return_value = {
        "text": "terraform apply",
        "project": "rekall-mcp",
        "cues": ["iac"],
        "memories": [],
    }
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_reflex(
        JsonRequest({"text": " terraform apply ", "project": "rekall-mcp", "limit": 2})
    )

    assert response.status_code == 200
    assert json.loads(response.body)["cues"] == ["iac"]
    manager.reflex.assert_called_once_with(text="terraform apply", project="rekall-mcp", limit=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": 123}])
async def test_api_memory_reflex_rejects_missing_or_non_string_text(monkeypatch, payload):
    from server import api_memory_reflex

    manager = MagicMock()
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_reflex(JsonRequest(payload))

    assert response.status_code == 400
    manager.reflex.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        ["terraform apply"],
        {"text": "terraform apply", "project": "bad project"},
        {"text": "terraform apply", "limit": "many"},
    ],
)
async def test_api_memory_reflex_rejects_invalid_params(monkeypatch, payload):
    from server import api_memory_reflex

    manager = MagicMock()
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    response = await api_memory_reflex(JsonRequest(payload))

    assert response.status_code == 400
    manager.reflex.assert_not_called()


@pytest.mark.asyncio
async def test_reflex_recall_tool_formats_memories(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.reflex.return_value = {
        "cues": ["iac"],
        "memories": [{"reason": "iac", "content": "Back up Terraform state before apply"}],
    }

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    rendered = await registered_tools["reflex_recall"](
        text="terraform apply",
        project="rekall-mcp",
    )

    assert "Reflex cues: iac" in rendered
    assert "- [iac] Back up Terraform state before apply" in rendered
    manager.reflex.assert_called_once_with(text="terraform apply", project="rekall-mcp")


@pytest.mark.asyncio
async def test_reflex_recall_tool_reports_no_matches(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.reflex.return_value = {"cues": [], "memories": []}

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    rendered = await registered_tools["reflex_recall"](text="say hello")

    assert rendered == "No reflex cues matched."
