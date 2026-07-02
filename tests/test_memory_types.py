"""Single source of truth for valid memory types."""


def test_valid_memory_types_constant():
    from memory.types import VALID_MEMORY_TYPES

    assert VALID_MEMORY_TYPES == frozenset(
        {"decision", "learning", "preference", "requirement", "fact", "note", "session", "summary"}
    )


def test_server_uses_shared_constant():
    import server
    from memory.types import VALID_MEMORY_TYPES

    assert server.VALID_MEMORY_TYPES is VALID_MEMORY_TYPES
