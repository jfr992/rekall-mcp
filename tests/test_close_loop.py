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
    tools = _bind(_provider(manager), tool_registry)

    out = await tools["close_loop"](memory_id="m1", project="my-app")

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


@pytest.mark.asyncio
async def test_close_loop_without_project_param_does_not_false_refuse(tool_registry):
    """The backend server's cwd is NOT the caller's project (v1.5.0 pitfall).
    With no explicit project from the caller, the guard must not compare
    against the backend's own scope and refuse legitimate closes."""
    from tools.builtin.memory import OptimizedMemoryTools

    manager = MagicMock()
    manager.store.get_many.return_value = [
        {"memory_id": "m1", "content": "TODO: wire auth retry", "project": "some-user-app"}
    ]
    manager.update_memory_content.return_value = {"memory_id": "m1"}
    provider = OptimizedMemoryTools()
    provider._manager = manager  # scope detection left REAL — backend cwd

    tools = _bind(provider, tool_registry)
    out = await tools["close_loop"](memory_id="m1")

    manager.update_memory_content.assert_called_once()
    assert "Closed loop" in out


@pytest.mark.asyncio
async def test_close_loop_unresolved_wording_is_still_closeable(tool_registry):
    """Pasted alert text containing UNRESOLVED must not trip the no-op guard —
    only the structured stamp counts as closed (adversarial review finding)."""
    manager = MagicMock()
    manager.store.get_many.return_value = [
        {
            "memory_id": "m1",
            "content": "TODO: fix pager alert 'DNS UNRESOLVED for 3h'",
            "project": "my-app",
        }
    ]
    manager.update_memory_content.return_value = {"memory_id": "m1"}
    tools = _bind(_provider(manager), tool_registry)

    out = await tools["close_loop"](memory_id="m1")

    manager.update_memory_content.assert_called_once()
    assert "Closed loop" in out


def test_unresolved_todo_stays_in_open_loops():
    """'unresolved' contains 'resolved' — substring exclusion would silently
    drop the strongest open-loop signal (adversarial review finding)."""
    from memory.capsules import build_project_capsule

    manager = MagicMock()
    manager.store.scroll.return_value = [
        {
            "memory_id": "m1",
            "content": "DNS flapping still unresolved — TODO: escalate to netops",
            "type": "note",
            "date": "2026-07-08",
        }
    ]
    manager.knowledge_graph.get_importance.return_value = 0.5

    cap = build_project_capsule(manager, "p")

    assert [i["memory_id"] for i in cap["open_loops"]] == ["m1"]


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
