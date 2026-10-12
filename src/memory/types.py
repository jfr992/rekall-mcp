"""Valid memory type names, shared by server validation and the CLI."""

VALID_MEMORY_TYPES: frozenset[str] = frozenset(
    {"decision", "learning", "preference", "requirement", "fact", "note", "session", "summary"}
)

MAX_MEMORY_CONTENT_CHARS = 20_000
