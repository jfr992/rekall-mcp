import json
from unittest.mock import MagicMock

import pytest


def _capsule(project: str = "byte-edge") -> dict:
    return {
        "project": project,
        "entities": ["Longhorn"],
        "standing_context": [
            {"content": "Use tuned Longhorn settings.", "date": "2026-07-01"}
        ],
        "active_workstreams": [],
        "operating_rules": [],
        "danger_zones": [],
        "open_loops": [],
    }


def test_team_publish_excludes_private_event_log():
    from memory.publish import build_team_memory_bundle

    bundle = build_team_memory_bundle(
        capsule=_capsule(),
        playbooks=[{"title": "Longhorn tuning", "steps": ["Review replica pressure"]}],
    )

    assert bundle["schema"] == "rekall.team-memory.v1"
    assert bundle["project"] == "byte-edge"
    assert bundle["capsule"]["entities"] == ["Longhorn"]
    assert bundle["playbooks"][0]["title"] == "Longhorn tuning"
    assert "events" not in bundle
    assert "raw_sessions" not in bundle
    assert "private_prompts" not in bundle
    assert "raw_hook_payloads" not in bundle
    assert bundle["privacy"] == {
        "raw_event_log_included": False,
        "raw_session_transcripts_included": False,
        "private_prompts_included": False,
        "raw_hook_payloads_included": False,
    }


def test_team_publish_strips_private_keys_from_inputs():
    from memory.publish import build_team_memory_bundle

    capsule = {
        **_capsule(),
        "events": [{"payload": "raw event"}],
        "raw_sessions": ["private transcript"],
        "private_prompts": ["secret prompt"],
        "raw_hook_payloads": [{"tool": "bash"}],
    }
    playbooks = [
        {
            "title": "Safe runbook",
            "steps": ["Review known danger zones"],
            "raw_hook_payloads": [{"private": True}],
        }
    ]

    bundle = build_team_memory_bundle(capsule=capsule, playbooks=playbooks)
    serialized = json.dumps(bundle)

    assert "raw event" not in serialized
    assert "private transcript" not in serialized
    assert "secret prompt" not in serialized
    assert '"raw_hook_payloads"' not in serialized
    assert bundle["playbooks"] == [{"title": "Safe runbook", "steps": ["Review known danger zones"]}]


@pytest.mark.asyncio
async def test_publish_team_memory_tool_uses_project_capsule(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.get_project_capsule.return_value = _capsule("rekall-mcp")

    provider = OptimizedMemoryTools()
    provider._manager = manager
    registered = provider.register(FakeMCP())

    rendered = await registered_tools["publish_team_memory"](project="rekall-mcp")
    bundle = json.loads(rendered)

    assert "publish_team_memory" in registered
    manager.get_project_capsule.assert_called_once_with(project="rekall-mcp")
    assert bundle["schema"] == "rekall.team-memory.v1"
    assert bundle["project"] == "rekall-mcp"
    assert bundle["playbooks"] == []
    assert bundle["privacy"]["raw_event_log_included"] is False
