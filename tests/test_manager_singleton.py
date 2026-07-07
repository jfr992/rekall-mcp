"""REST and MCP tool paths must share ONE MemoryManager.

Two instances = split-brain: seeds via REST create graph edges the MCP
recall path never sees (in-memory graphs drift until restart). Found by
the effectiveness eval: freshness edges were invisible to agent recalls.
"""


def test_rest_and_mcp_share_one_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(tmp_path))
    from memory import singleton

    singleton.reset_memory_manager()
    import server
    from tools.builtin.memory import OptimizedMemoryTools

    provider = OptimizedMemoryTools()
    assert provider.manager is server._get_memory_manager()
    singleton.reset_memory_manager()
