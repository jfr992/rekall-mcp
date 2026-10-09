"""MCP write tools carry caller provenance (spec 2026-10-09, section 2)."""

import subprocess
from unittest.mock import MagicMock

import pytest


def _bind(provider, tool_registry):
    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider.register(FakeMCP())
    return registered_tools


def _provider(manager):
    from tools.builtin.memory import OptimizedMemoryTools

    provider = OptimizedMemoryTools()
    provider._manager = manager
    return provider


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "caller-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    from memory.scope import ScopeDetector

    ScopeDetector.reset_trust_cache()
    yield repo
    ScopeDetector.reset_trust_cache()


@pytest.mark.asyncio
async def test_save_memory_resolves_project_from_caller_cwd(tool_registry, git_repo):
    manager = MagicMock()
    manager.save.return_value = "2026-10-09_note_abcd1234"
    tools = _bind(_provider(manager), tool_registry)

    await tools["save_memory"](
        content="x", cwd=str(git_repo), session_id="sess-1", agent="codex"
    )

    kw = manager.save.call_args.kwargs
    assert kw["project"] == "caller-repo"
    assert kw["scope"].project == "caller-repo"
    assert kw["scope"].agent == "codex"
    assert kw["cwd"] == str(git_repo)
    assert kw["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_observe_resolves_project_from_caller_cwd(tool_registry, git_repo, monkeypatch):
    monkeypatch.setattr("tools.builtin.memory._classify_smart", lambda *a, **k: "fact")
    manager = MagicMock()
    manager.observe.return_value = "2026-10-09_fact_abcd1234"
    tools = _bind(_provider(manager), tool_registry)

    await tools["observe"](summary="x", cwd=str(git_repo), session_id="sess-2", agent="codex")

    kw = manager.observe.call_args.kwargs
    assert kw["project"] == "caller-repo"
    assert kw["scope"].agent == "codex"
    assert kw["cwd"] == str(git_repo)
    assert kw["session_id"] == "sess-2"


@pytest.mark.asyncio
async def test_observe_accepts_explicit_project(tool_registry, git_repo, monkeypatch):
    monkeypatch.setattr("tools.builtin.memory._classify_smart", lambda *a, **k: "fact")
    manager = MagicMock()
    manager.observe.return_value = "2026-10-09_fact_abcd1234"
    tools = _bind(_provider(manager), tool_registry)

    await tools["observe"](summary="x", project="explicit-proj", cwd=str(git_repo))

    assert manager.observe.call_args.kwargs["project"] == "explicit-proj"


@pytest.mark.asyncio
async def test_save_memory_without_provenance_passes_no_scope_kwargs(tool_registry):
    """Old tests mock the helper with a one-arg lambda; omitted fields must not reach it."""
    manager = MagicMock()
    provider = _provider(manager)
    scope = MagicMock()
    scope.project = "fallback"
    calls = []

    def fake_scope(project=None, **kw):
        calls.append(kw)
        return scope

    provider._get_current_scope = fake_scope
    tools = _bind(provider, tool_registry)

    await tools["save_memory"](content="x")

    assert calls == [{}]
    kw = manager.save.call_args.kwargs
    assert kw["project"] == "fallback"
    assert kw["cwd"] is None
    assert kw["session_id"] is None


@pytest.mark.asyncio
async def test_recall_memories_forwards_agent(tool_registry):
    manager = MagicMock()
    manager.recall_formatted.return_value = "ok"
    tools = _bind(_provider(manager), tool_registry)

    await tools["recall_memories"](query="q", agent="codex")

    assert manager.recall_formatted.call_args.kwargs["agent"] == "codex"
