"""Tool registry for discovering and managing available tools."""

import os
from dataclasses import dataclass, field
from typing import Any

from core import Telemetry


@dataclass
class ToolInfo:
    """Information about a discovered tool."""

    name: str
    description: str
    builtin: bool = False
    requires: list[str] = field(default_factory=list)
    enabled: bool = False


class ToolRegistry:
    """Registry for discovering and managing tools.

    Singleton that maintains the list of available tools and their status.

    Usage:
        registry = ToolRegistry.get()
        available = registry.discover()
        registry.enable("spectro")
        enabled = registry.get_enabled()
    """

    _instance: "ToolRegistry | None" = None

    def __init__(self) -> None:
        self._tools: dict[str, ToolInfo] = {}
        self._telemetry = Telemetry.get()
        self._discovered = False

    @classmethod
    def get(cls) -> "ToolRegistry":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    def discover(self) -> dict[str, dict[str, Any]]:
        """Discover all available tools.

        Scans builtin and plugin directories for tool providers.

        Returns:
            Dict mapping tool names to their info.
        """
        with self._telemetry.track("tools.discover"):
            # Register builtin tools
            self._register_builtin_tools()

            # Mark as discovered
            self._discovered = True

            # Return serializable dict
            return {
                name: {
                    "description": info.description,
                    "builtin": info.builtin,
                    "requires": info.requires,
                    "enabled": info.enabled,
                }
                for name, info in self._tools.items()
            }

    def _register_builtin_tools(self) -> None:
        """Register the built-in tools."""
        # Memory tools - always available
        self._tools["memory"] = ToolInfo(
            name="memory",
            description="Persistent memory for AI assistants",
            builtin=True,
            requires=[],
            enabled=True,  # Enabled by default
        )

        # Spectro tools - requires API key
        self._tools["spectro"] = ToolInfo(
            name="spectro",
            description="Spectro Cloud Kubernetes management",
            builtin=False,
            requires=["SPECTRO_API_KEY"],
            enabled=False,  # Disabled by default
        )

    def enable(self, name: str) -> None:
        """Enable a tool.

        Args:
            name: Tool name to enable

        Raises:
            ValueError: If tool doesn't exist
        """
        if not self._discovered:
            self.discover()

        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")

        self._tools[name].enabled = True

    def disable(self, name: str) -> None:
        """Disable a tool.

        Args:
            name: Tool name to disable

        Raises:
            ValueError: If tool doesn't exist
        """
        if not self._discovered:
            self.discover()

        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")

        self._tools[name].enabled = False

    def can_enable(self, name: str) -> bool:
        """Check if a tool can be enabled.

        Verifies all requirements (env vars) are met.

        Args:
            name: Tool name to check

        Returns:
            True if all requirements are met
        """
        if not self._discovered:
            self.discover()

        if name not in self._tools:
            return False

        tool = self._tools[name]

        # Check all required environment variables
        for env_var in tool.requires:
            if not os.environ.get(env_var):
                return False

        return True

    def get_enabled(self) -> list[str]:
        """Get list of enabled tool names."""
        if not self._discovered:
            self.discover()

        return [name for name, info in self._tools.items() if info.enabled]

    def get_tool_info(self, name: str) -> ToolInfo | None:
        """Get info about a specific tool."""
        if not self._discovered:
            self.discover()

        return self._tools.get(name)
