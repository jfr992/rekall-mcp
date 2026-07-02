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


def test_cli_save_accepts_all_valid_types():
    import click

    from memory.cli import save
    from memory.types import VALID_MEMORY_TYPES

    type_option = next(p for p in save.params if p.name == "memory_type")
    assert isinstance(type_option.type, click.Choice)
    assert set(type_option.type.choices) == set(VALID_MEMORY_TYPES)
