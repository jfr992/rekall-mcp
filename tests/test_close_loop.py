"""close_loop MCP tool: explicit closure, project-guarded (spec 2026-07-08)."""

from datetime import date
from unittest.mock import MagicMock

import pytest


def _provider(manager, scope_project="my-app"):
    from tools.builtin.memory import OptimizedMemoryTools

    provider = OptimizedMemoryTools()
    provider._manager = manager
    scope = MagicMock()
    scope.project = scope_project
    provider._get_current_scope = lambda project=None: scope
    return provider


def _bind(provider, tool_registry):
    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider.register(FakeMCP())
    return registered_tools


@pytest.mark.asyncio
async def test_close_loop_appends_resolved_stamp(tool_registry):
    manager = MagicMock()
    manager.store.get_many.return_value = [
        {"memory_id": "m1", "content": "TODO: wire auth retry", "project": "my-app"}
    ]
    manager.update_memory_content.return_value = {"memory_id": "m1"}
    tools = _bind(_provider(manager), tool_registry)

    out = await tools["close_loop"](memory_id="m1", note="merged in PR #46")

    stamp = f"RESOLVED {date.today().isoformat()}: merged in PR #46"
    manager.update_memory_content.assert_called_once_with("m1", stamp)
    assert "m1" in out


@pytest.mark.asyncio
async def test_close_loop_project_guard_refuses_cross_project(tool_registry):
    manager = MagicMock()
    manager.store.get_many.return_value = [
        {"memory_id": "m1", "content": "TODO: wire auth retry", "project": "other-app"}
    ]
    tools = _bind(_provider(manager, scope_project="my-app"), tool_registry)

    out = await tools["close_loop"](memory_id="m1")

    assert "Refused" in out
    manager.update_memory_content.assert_not_called()


@pytest.mark.asyncio
async def test_close_loop_already_resolved_is_noop(tool_registry):
    manager = MagicMock()
    manager.store.get_many.return_value = [
        {
            "memory_id": "m1",
            "content": "TODO: wire auth retry\n\nRESOLVED 2026-07-01",
            "project": "my-app",
        }
    ]
    tools = _bind(_provider(manager), tool_registry)

    out = await tools["close_loop"](memory_id="m1")

    assert "already resolved" in out
    manager.update_memory_content.assert_not_called()


@pytest.mark.asyncio
async def test_close_loop_unknown_id(tool_registry):
    manager = MagicMock()
    manager.store.get_many.return_value = []
    tools = _bind(_provider(manager), tool_registry)

    out = await tools["close_loop"](memory_id="nope")

    assert "No memory found" in out
    manager.update_memory_content.assert_not_called()


@pytest.mark.integration
def test_closed_loop_exits_capsule_bucket(memory_manager):
    """End-to-end on :6334: a closed TODO leaves open_loops while an
    unrelated TODO remains."""
    from memory.capsules import build_project_capsule

    mgr = memory_manager
    closed_id = mgr.save("TODO: wire the auth retry", type="note", project="test-project")
    open_id = mgr.save("TODO: paginate the export endpoint", type="note", project="test-project")

    before = build_project_capsule(mgr, "test-project")
    before_ids = {i["memory_id"] for i in before["open_loops"]}
    assert {closed_id, open_id} <= before_ids

    mgr.update_memory_content(closed_id, "RESOLVED 2026-07-09: retry shipped")

    after = build_project_capsule(mgr, "test-project")
    after_ids = {i["memory_id"] for i in after["open_loops"]}
    assert open_id in after_ids
    assert closed_id not in after_ids
