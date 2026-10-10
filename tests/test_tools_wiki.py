"""wiki_lookup / wiki_read MCP tools emit wiki_delivered events (spec: Read path, Measurement)."""

from unittest.mock import MagicMock

import pytest

from memory.wiki.pages import Page
from memory.wiki.store import WikiStore

BODY = (
    "## When {#when}\nkey expired [source: 2026-01-01_fact_a1]\n## Preconditions {#preconditions}\nadmin\n"
    "## Steps {#steps}\n1. export key [source: 2026-01-01_fact_a1]\n## Expected output {#expected}\nok\n"
    "## Verify {#verify}\ncurl 200\n## Stop conditions {#stop}\n401\n## Rollback {#rollback}\nrestore\n## Known limitations {#limits}\nnone\n"
)


def _bind(provider, tool_registry):
    capture_tool, registered = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider.register(FakeMCP())
    return registered


@pytest.fixture
def tools(tmp_path, tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    manager = MagicMock()
    manager.wiki = WikiStore(tmp_path / "wiki")
    manager.store.get_many.side_effect = lambda ids, **kw: [{"memory_id": i} for i in ids]
    manager.knowledge_graph.get_edges.return_value = []
    fm = {
        "title": "Rotate gateway key",
        "description": "d",
        "page_id": "demo/process/rotate-key",
        "type": "process",
        "project": "demo",
        "sources": ["2026-01-01_fact_a1"],
    }
    manager.wiki.write_draft(Page(frontmatter=fm, body=BODY))
    manager.wiki.approve("demo/process/rotate-key")
    provider = OptimizedMemoryTools()
    provider._manager = manager
    return _bind(provider, tool_registry), manager


@pytest.mark.asyncio
async def test_wiki_lookup_returns_hits_and_emits_event(tools):
    registered, manager = tools
    out = await registered["wiki_lookup"](
        query="rotate gateway key", session_id="s1", agent="codex"
    )
    assert "wiki:demo/process/rotate-key#" in out and "rev 1" in out and "ok" in out
    kw = manager.record_event.call_args.kwargs
    assert kw["event_type"] == "wiki_delivered" and kw["payload"]["surface"] == "wiki_lookup"
    assert (
        kw["payload"]["page_ids"] == ["demo/process/rotate-key"]
        and kw["payload"]["session_id"] == "s1"
        and kw["agent"] == "codex"
    )


@pytest.mark.asyncio
async def test_wiki_lookup_no_match(tools):
    registered, manager = tools
    assert await registered["wiki_lookup"](query="zzz qqq") == "No wiki match."
    manager.record_event.assert_not_called()


@pytest.mark.asyncio
async def test_wiki_read_section_and_withdrawn_warning_first(tools):
    registered, manager = tools
    out = await registered["wiki_read"](page_id="demo/process/rotate-key", session_id="s1")
    assert (
        out.startswith("# Rotate gateway key (demo/process/rotate-key rev 1)")
        and "export key" in out
    )
    manager.store.get_many.side_effect = lambda ids, **kw: [
        {"memory_id": i, "disputed": True} for i in ids
    ]
    out = await registered["wiki_read"](page_id="demo/process/rotate-key")
    lines = out.splitlines()
    assert "withdrawn" in lines[0] and lines[1].startswith("> WARNING") and "export key" in out
    assert manager.record_event.call_args.kwargs["payload"]["section_id"] == "steps"


@pytest.mark.asyncio
async def test_wiki_read_unknown_page(tools):
    registered, _ = tools
    assert "not found" in await registered["wiki_read"](page_id="demo/process/nope")
