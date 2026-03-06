"""Tool loader for registering tools with MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core import Telemetry

from .registry import ToolRegistry

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class ToolLoader:
    """Loads and registers tools with the MCP server.

    Usage:
        loader = ToolLoader(mcp)
        loader.load("memory")
        loader.load_all()
    """

    def __init__(self, mcp: FastMCP):
        self._mcp = mcp
        self._telemetry = Telemetry.get()
        self._loaded: dict[str, list[str]] = {}

    def load(self, name: str) -> list[str]:
        """Load a specific tool provider.

        Args:
            name: Tool provider name

        Returns:
            List of registered tool names

        Raises:
            ValueError: If tool provider doesn't exist
        """
        with self._telemetry.track(f"tools.load.{name}"):
            provider = self._get_provider(name)
            registered = provider.register(self._mcp)
            self._loaded[name] = registered
            return registered

    def load_all(self, registry: ToolRegistry | None = None) -> dict[str, list[str]]:
        """Load all enabled tools.

        Args:
            registry: Tool registry (uses default if not provided)

        Returns:
            Dict mapping provider names to registered tool names
        """
        if registry is None:
            registry = ToolRegistry.get()

        with self._telemetry.track("tools.load_all"):
            enabled = registry.get_enabled()

            for name in enabled:
                if name not in self._loaded:
                    try:
                        self.load(name)
                    except ValueError:
                        # Skip unknown tools
                        pass

            return self._loaded

    def _get_provider(self, name: str):
        """Get a tool provider instance by name.

        Args:
            name: Provider name

        Returns:
            Tool provider instance

        Raises:
            ValueError: If provider doesn't exist
        """
        if name == "memory":
            from .builtin import MemoryTools

            return MemoryTools()
        elif name == "tracker":
            from .builtin.tracker import TrackerTools

            return TrackerTools()
        elif name == "briefing":
            from .builtin.briefing import BriefingTools

            return BriefingTools()
        elif name == "spectro":
            from .builtin.spectro import SpectroTools

            return SpectroTools()
        else:
            raise ValueError(f"Unknown tool: {name}")

    def get_loaded(self) -> dict[str, list[str]]:
        """Get dict of loaded providers and their tools."""
        return self._loaded.copy()
