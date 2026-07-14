"""Tool registration must not construct the MemoryManager.

The uvx entry (server:main_stdio) imports server, which registers tools at
module load — BEFORE main_stdio() applies the embedded-storage env defaults.
A manager built during register() therefore resolves Qdrant from a bare env
and falls back to http://localhost:6333 (the wheel-gate CI failure; on dev
machines it silently hit production Qdrant).
"""

from tools.builtin.memory import OptimizedMemoryTools


class _StubMCP:
    def tool(self, *args, **kwargs):
        def deco(fn):
            return fn

        return deco


def test_register_does_not_construct_manager():
    provider = OptimizedMemoryTools()

    registered = provider.register(_StubMCP())

    assert "save_memory" in registered
    assert provider._manager is None, (
        "register() constructed the MemoryManager before main_stdio() could "
        "apply QDRANT_PATH defaults — the manager locks in http://localhost:6333"
    )
