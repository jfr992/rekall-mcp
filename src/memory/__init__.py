"""Memory system for persistent AI agent context.

Usage:
    from memory import MemoryManager

    memory = MemoryManager()
    memory.save("User prefers concise responses", type="preference")
    results = memory.recall("preferences")
"""

# Lazy import to avoid loading heavy dependencies at package import time
def __getattr__(name: str):
    if name == "MemoryManager":
        from .manager import MemoryManager
        return MemoryManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["MemoryManager"]
