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
    out = await registered["wiki_read"](page_id="demo/process/nope")
    assert "not found" in out and "demo/process/nope" not in out


def _write_page(manager, page_id, ptype, body, **extra):
    fm = {
        "title": "T " + page_id,
        "description": "d",
        "page_id": page_id,
        "type": ptype,
        "project": "demo",
        "sources": ["2026-01-01_fact_a1"],
        **extra,
    }
    manager.wiki.write_draft(Page(frontmatter=fm, body=body))
    manager.wiki.approve(page_id)


@pytest.mark.asyncio
async def test_wiki_read_trims_non_process_full_page(tools):
    registered, manager = tools
    paras = "\n\n".join(f"paragraph {i} " + "x" * 190 for i in range(100))
    body = "## Facts {#facts}\n" + paras + "\n## Sources {#sources}\n[source: 2026-01-01_fact_a1]\n"
    _write_page(manager, "demo/reference/big", "reference", body)
    out = await registered["wiki_read"](page_id="demo/reference/big", full=True)
    assert len(out) // 4 <= 3100 and len(body) // 4 > 4000 and "paragraph 0" in out


@pytest.mark.asyncio
async def test_wiki_read_never_truncates_process(tools):
    registered, manager = tools
    steps = "\n".join(
        f"{i}. step-{i} " + "y" * 190 + " [source: 2026-01-01_fact_a1]" for i in range(1, 40)
    )
    body = BODY.replace("1. export key [source: 2026-01-01_fact_a1]", steps)
    _write_page(manager, "demo/process/long", "process", body)
    out = await registered["wiki_read"](page_id="demo/process/long")
    assert all(f"step-{i} " in out for i in range(1, 40))
    assert out.splitlines()[-1].startswith("> NOTE: over budget (") and out.endswith(
        "read by section"
    )


@pytest.mark.asyncio
async def test_wiki_read_full_and_named_section(tools):
    registered, _ = tools
    full = await registered["wiki_read"](page_id="demo/process/rotate-key", full=True)
    assert "## When" in full and "## Rollback" in full
    verify = await registered["wiki_read"](page_id="demo/process/rotate-key", section="verify")
    assert "curl 200" in verify and "export key" not in verify


@pytest.mark.asyncio
async def test_wiki_lookup_attribution_never_uses_backend_cwd(tools):
    registered, manager = tools
    await registered["wiki_lookup"](query="rotate gateway key")
    assert manager.record_event.call_args.kwargs["project"] == "general"
    await registered["wiki_lookup"](query="rotate gateway key", project="demo")
    assert manager.record_event.call_args.kwargs["project"] == "demo"


@pytest.mark.asyncio
async def test_wiki_lookup_limit_is_clamped(tools, monkeypatch):
    import memory.wiki.search as search

    registered, _ = tools
    seen = []
    monkeypatch.setattr(search, "search_index", lambda *a, **kw: seen.append(kw["limit"]) or [])
    await registered["wiki_lookup"](query="x", limit=50)
    await registered["wiki_lookup"](query="x", limit=0)
    assert seen == [3, 1]


@pytest.mark.asyncio
async def test_wiki_read_accepts_wiki_link_with_fragment(tools):
    registered, _ = tools
    linked = await registered["wiki_read"](page_id="wiki:demo/process/rotate-key#verify")
    plain = await registered["wiki_read"](page_id="demo/process/rotate-key", section="verify")
    assert linked == plain and "not found" not in linked
    explicit = await registered["wiki_read"](
        page_id="wiki:demo/process/rotate-key#verify", section="steps"
    )
    assert explicit == await registered["wiki_read"](
        page_id="demo/process/rotate-key", section="steps"
    )
