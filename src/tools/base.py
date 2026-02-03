"""Base class for tool providers.

Each tool provider implements this interface to register its tools with MCP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@dataclass
class ToolDefinition:
    """Definition of a single tool."""

    name: str
    description: str
    handler: Callable
    parameters: dict[str, Any] = field(default_factory=dict)


class BaseToolProvider(ABC):
    """Base class for tool providers.

    Implement this to create a new tool provider that can be
    registered with the MCP server.

    Example:
        class MyTools(BaseToolProvider):
            name = "my_tools"
            description = "Custom tools for XYZ"
            requires = ["MY_API_KEY"]

            def get_tools(self) -> list[ToolDefinition]:
                return [
                    ToolDefinition(
                        name="do_something",
                        description="Does something useful",
                        handler=self.do_something
                    )
                ]

            async def do_something(self, param: str) -> str:
                return f"Did something with {param}"
    """

    # Override in subclasses
    name: str = "base"
    description: str = "Base tool provider"
    requires: list[str] = []  # Environment variables required
    builtin: bool = False  # True for core tools (always available)

    @abstractmethod
    def get_tools(self) -> list[ToolDefinition]:
        """Return list of tools this provider offers."""
        ...

    def register(self, mcp: FastMCP) -> list[str]:
        """Register all tools with the MCP server.

        Returns list of registered tool names.
        """
        registered = []

        for tool in self.get_tools():
            # Create the tool decorator with proper metadata
            mcp.tool()(tool.handler)
            registered.append(tool.name)

        return registered
