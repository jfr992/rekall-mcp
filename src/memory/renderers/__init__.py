"""Export-format renderers. Add a new file here per format; no registry needed."""

from __future__ import annotations

from memory.publish_types import Renderer


def get_renderer(fmt: str) -> Renderer:
    if fmt == "okf":
        from memory.renderers.okf import OkfRenderer

        return OkfRenderer()
    raise ValueError(f"Unknown export format: {fmt}")
