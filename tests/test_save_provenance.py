"""Provenance write-path contract: save() persists what get_memory_detail reads.

The detail extractor (manager.get_memory_detail) reads agent / source_tool /
source_event from the memory payload. These tests pin that the write paths
actually populate those keys — and that legacy memories without them keep
the honest missing_provenance warning (no backfill fabrication).
"""

from unittest.mock import MagicMock

import pytest

from memory.scope import MemoryScope


@pytest.fixture
def rest_client():
    from starlette.testclient import TestClient

    from server import mcp

    return TestClient(mcp.streamable_http_app())


@pytest.fixture
def fake_rest_manager(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


@pytest.mark.integration
def test_save_with_source_tool_clears_missing_provenance(memory_manager):
    """agent='unknown' (honest server-side detection) + source_tool → no warning."""
    scope = MemoryScope(agent="unknown", project="prov-e2e")
    memory_id = memory_manager.save(
        "Provenance round trip decision one",
        type="decision",
        scope=scope,
        source_tool="observe",
        cwd="/tmp/caller-repo",
    )

    detail = memory_manager.get_memory_detail(memory_id)

    assert detail["provenance"]["source_tool"] == "observe"
    assert "missing_provenance" not in detail["warnings"]
    # cwd is stored on the memory record (caller context, honest when present)
    assert detail["memory"]["cwd"] == "/tmp/caller-repo"


@pytest.mark.integration
def test_save_without_source_tool_still_warns(memory_manager):
    """No provenance signal at save time → the warning stays. Never fabricated."""
    scope = MemoryScope(agent="unknown", project="prov-e2e")
    memory_id = memory_manager.save(
        "Provenance round trip decision two",
        type="decision",
        scope=scope,
    )

    detail = memory_manager.get_memory_detail(memory_id)

    assert detail["provenance"]["source_tool"] is None
    assert "missing_provenance" in detail["warnings"]
    # absent cwd stays absent — honest for callers that have none
    assert "cwd" not in detail["memory"]


@pytest.mark.integration
def test_save_scope_agent_lands_in_provenance(memory_manager):
    """scope.agent flows to provenance.agent verbatim — no coercion either way."""
    scope = MemoryScope(agent="claude-code", project="prov-e2e")
    memory_id = memory_manager.save(
        "Provenance round trip decision three",
        type="decision",
        scope=scope,
        source_tool="mcp",
    )

    detail = memory_manager.get_memory_detail(memory_id)

    assert detail["provenance"]["agent"] == "claude-code"
    assert detail["provenance"]["source_tool"] == "mcp"
    assert "missing_provenance" not in detail["warnings"]


def test_observe_route_passes_source_tool_and_cwd(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "decided to ship provenance", "type": "decision", "cwd": "/Users/x/repo"},
    )
    assert r.status_code == 200
    kwargs = fake_rest_manager.save.call_args.kwargs
    assert kwargs["source_tool"] == "observe"
    assert kwargs["cwd"] == "/Users/x/repo"


def test_observe_route_without_cwd_passes_none(rest_client, fake_rest_manager):
    """Old hooks send no cwd → None, never fabricated from the backend's own cwd."""
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "decided to ship provenance", "type": "decision"},
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["cwd"] is None


def test_rest_save_route_passes_source_tool(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post("/api/memory/save", json={"content": "remember this"})
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["source_tool"] == "rest"


@pytest.mark.asyncio
async def test_mcp_tools_pass_source_tool(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.observe.return_value = "mid"
    manager.save.return_value = "mid"
    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    await registered_tools["save_memory"](content="remember this", memory_type="note")
    assert manager.save.call_args.kwargs["source_tool"] == "mcp"

    await registered_tools["observe"](summary="fixed the bug", type="learning")
    assert manager.observe.call_args.kwargs["source_tool"] == "mcp"


def test_observation_sanitization_preserves_provenance_fields():
    from memory.observe import sanitize_observation_metadata

    metadata = {
        "source_tool": "mcp",
        "cwd": "/Users/x/repo",
        "embedding_text": "generated",
        "entities": ["X"],
    }
    sanitized = sanitize_observation_metadata(metadata)

    assert sanitized["source_tool"] == "mcp"
    assert sanitized["cwd"] == "/Users/x/repo"
    assert "embedding_text" not in sanitized
    assert "entities" not in sanitized


def test_lifecycle_defaults_do_not_fabricate_provenance():
    from memory.lifecycle import summarize_lifecycle

    result = summarize_lifecycle({"content": "some note", "type": "note"})

    for key in ("agent", "source_tool", "source_event", "cwd"):
        assert key not in result, f"lifecycle defaults must not fabricate {key}"
