"""Pluggable tool registry system.

This module provides a configurable way to register tools with the MCP server.

Usage:
    from tools import ToolRegistry, ToolLoader, ToolConfig

    # Discover available tools
    registry = ToolRegistry.get()
    available = registry.discover()

    # Load configuration
    config = ToolConfig.from_file("tools.yaml")

    # Load tools into MCP
    loader = ToolLoader(mcp)
    loader.load_all(config)
"""

from .config import ToolConfig
from .loader import ToolLoader
from .registry import ToolRegistry

__all__ = ["ToolRegistry", "ToolLoader", "ToolConfig"]
