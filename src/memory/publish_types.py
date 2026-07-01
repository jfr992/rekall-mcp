"""Shared data types for the memory publish/export pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Concept:
    """One OKF concept: a bundle-relative path + frontmatter + markdown body."""

    path: str  # bundle-relative, ends with .md
    frontmatter: dict[str, Any]  # MUST include a non-empty "type"
    body: str


@dataclass(frozen=True, slots=True)
class Bundle:
    """The rendered export: file tree, file contents, and summary stats."""

    tree: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


class Renderer(Protocol):
    def render(self, concepts: list[Concept]) -> Bundle: ...
