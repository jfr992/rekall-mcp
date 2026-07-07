"""Process-wide MemoryManager singleton.

REST routes and MCP tools MUST share one manager: separate instances hold
separate in-memory knowledge graphs, so edges created through one path are
invisible to recalls through the other until restart (split-brain, found by
the effectiveness eval 2026-07-07).
"""

from __future__ import annotations

_instance = None


def get_memory_manager():
    global _instance
    if _instance is None:
        from memory.manager import MemoryManager

        _instance = MemoryManager()
    return _instance


def reset_memory_manager() -> None:
    """Test hook — drop the shared instance."""
    global _instance
    _instance = None
