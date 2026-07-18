import json
from unittest.mock import MagicMock

import pytest


def test_detect_reflex_cues_for_iac_and_memory():
    from memory.reflex import detect_reflex_cues

    cues = detect_reflex_cues("Run terraform apply after backing up Qdrant memory")

    assert "iac" in cues
    assert "memory_data" in cues


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /var/lib/data",
        "DROP TABLE users;",
        "force-delete the volume",
        "forcedelete the volume",
        "rotate the credentials",
        "prune old snapshots",
        "kubectl delete pod my-pod",
        "terraform destroy -auto-approve",
        "tofu destroy -auto-approve",
        "helm uninstall my-release",
    ],
)
def test_detect_reflex_cues_matches_destructive_commands(command):
    from memory.reflex import detect_reflex_cues

    cues = detect_reflex_cues(command)

    assert "destructive" in cues


def test_destructive_is_first_declared_cue_group():
    from memory.reflex import _CUES

    assert next(iter(_CUES)) == "destructive"


def test_reflex_packet_single_merged_recall_call():
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
        text="terraform apply touches qdrant memory sync and claude hooks",
        project="rekall-mcp",
    )

    assert "memory_data" in packet["cues"]
    assert len(calls) == 1
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


def test_reflex_packet_caps_at_three_cues_destructive_first_then_declaration_order():
    from memory.reflex import build_reflex_packet

    class Manager:
        def recall(self, query, limit=4, project=None, score_threshold=0.45, **kwargs):
            return []

    # Matches all four groups: destructive, iac, memory_data, hooks.
    text = "rm -rf the terraform state after qdrant memory cleanup and update claude hooks"
    packet = build_reflex_packet(Manager(), text=text, project="rekall-mcp", limit=4)

    assert packet["cues"] == ["destructive", "iac", "memory_data"]
    assert packet["dropped_cues"] == ["hooks"]


def test_reflex_packet_passes_cwd_through_to_manager_recall():
    from memory.reflex import build_reflex_packet

    calls = []

    class Manager:
        def recall(self, query, limit=4, project=None, score_threshold=0.45, **kwargs):
            calls.append(kwargs.get("cwd"))
            return []

    build_reflex_packet(
        Manager(),
        text="terraform apply",
        project=None,
        limit=4,
        cwd="/Users/dev/some-project",
    )

    assert calls == ["/Users/dev/some-project"]


def test_reflex_packet_shape_is_stable_for_hook():
    from memory.reflex import build_reflex_packet

    class Manager:
        def recall(self, query, limit=4, project=None, score_threshold=0.45, **kwargs):
            return [
                {"memory_id": "m1", "type": "learning", "content": "Back up first", "score": 0.9}
            ]

    packet = build_reflex_packet(
        Manager(),
        text="terraform apply",
        project="rekall-mcp",
        limit=4,
    )

    assert set(packet.keys()) >= {"cues", "dropped_cues", "memories"}
    memory = packet["memories"][0]
    assert memory["memory_id"] == "m1"
    assert memory["type"] == "learning"
    assert memory["content"] == "Back up first"
    assert memory["score"] == 0.9


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
    manager.reflex.assert_called_once_with(
        text="terraform apply", project="rekall-mcp", limit=2, cwd=None
    )


@pytest.mark.asyncio
async def test_api_memory_reflex_passes_cwd_to_manager(monkeypatch):
    from server import api_memory_reflex

    manager = MagicMock()
    manager.reflex.return_value = {"cues": [], "dropped_cues": [], "memories": []}
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    await api_memory_reflex(JsonRequest({"text": "terraform apply", "cwd": "/Users/dev/proj"}))

    manager.reflex.assert_called_once_with(
        text="terraform apply", project=None, limit=4, cwd="/Users/dev/proj"
    )


@pytest.mark.asyncio
async def test_api_memory_reflex_accepts_workspace_root_alias(monkeypatch):
    from server import api_memory_reflex

    manager = MagicMock()
    manager.reflex.return_value = {"cues": [], "dropped_cues": [], "memories": []}
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    await api_memory_reflex(
        JsonRequest({"text": "terraform apply", "workspace_root": "/Users/dev/proj"})
    )

    manager.reflex.assert_called_once_with(
        text="terraform apply", project=None, limit=4, cwd="/Users/dev/proj"
    )


@pytest.mark.asyncio
async def test_api_memory_reflex_explicit_project_wins_over_cwd(monkeypatch):
    from server import api_memory_reflex

    manager = MagicMock()
    manager.reflex.return_value = {"cues": [], "dropped_cues": [], "memories": []}
    monkeypatch.setattr("server._get_memory_manager", lambda: manager)

    await api_memory_reflex(
        JsonRequest(
            {
                "text": "terraform apply",
                "project": "rekall-mcp",
                "cwd": "/Users/dev/other-project",
            }
        )
    )

    manager.reflex.assert_called_once_with(
        text="terraform apply", project="rekall-mcp", limit=4, cwd="/Users/dev/other-project"
    )


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
        "dropped_cues": [],
        "memories": [{"content": "Back up Terraform state before apply"}],
    }

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    rendered = await registered_tools["reflex_recall"](
        text="terraform apply",
        project="rekall-mcp",
    )

    assert "Reflex cues: iac" in rendered
    assert "- Back up Terraform state before apply" in rendered
    manager.reflex.assert_called_once_with(text="terraform apply", project="rekall-mcp")


@pytest.mark.asyncio
async def test_reflex_recall_tool_reports_no_matches(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.reflex.return_value = {"cues": [], "dropped_cues": [], "memories": []}

    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    rendered = await registered_tools["reflex_recall"](text="say hello")

    assert rendered == "No reflex cues matched."
