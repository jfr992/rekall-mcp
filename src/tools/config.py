"""Tool configuration management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ToolConfig:
    """Configuration for which tools are enabled.

    Can be loaded from:
    - YAML file
    - Environment variables
    - Default settings

    Example YAML:
        tools:
          memory:
            enabled: true
          spectro:
            enabled: false
    """

    _enabled: dict[str, bool] = field(default_factory=dict)
    _settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def is_enabled(self, name: str) -> bool:
        """Check if a tool is enabled."""
        return self._enabled.get(name, False)

    def get_settings(self, name: str) -> dict[str, Any]:
        """Get settings for a specific tool."""
        return self._settings.get(name, {})

    def enable(self, name: str) -> None:
        """Enable a tool."""
        self._enabled[name] = True

    def disable(self, name: str) -> None:
        """Disable a tool."""
        self._enabled[name] = False

    @classmethod
    def from_file(cls, path: str | Path) -> ToolConfig:
        """Load config from a YAML file.

        Args:
            path: Path to YAML config file

        Returns:
            ToolConfig instance
        """
        path = Path(path)
        config = cls()

        if not path.exists():
            return config

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        tools = data.get("tools", {})
        for name, settings in tools.items():
            if isinstance(settings, dict):
                config._enabled[name] = settings.get("enabled", False)
                config._settings[name] = settings
            elif isinstance(settings, bool):
                config._enabled[name] = settings

        return config

    @classmethod
    def from_env(cls) -> ToolConfig:
        """Load config from environment variables.

        Environment variables:
        - TOOLS_ENABLED: Comma-separated list of enabled tools
        - TOOLS_DISABLED: Comma-separated list of disabled tools

        Example:
            TOOLS_ENABLED=memory,spectro
            TOOLS_DISABLED=experimental

        Returns:
            ToolConfig instance
        """
        config = cls.default()

        # Override with enabled tools
        enabled = os.environ.get("TOOLS_ENABLED", "")
        if enabled:
            for name in enabled.split(","):
                name = name.strip()
                if name:
                    config._enabled[name] = True

        # Override with disabled tools
        disabled = os.environ.get("TOOLS_DISABLED", "")
        if disabled:
            for name in disabled.split(","):
                name = name.strip()
                if name:
                    config._enabled[name] = False

        return config

    @classmethod
    def default(cls) -> ToolConfig:
        """Get default configuration.

        Memory is enabled by default.
        Spectro is disabled by default.

        Returns:
            ToolConfig instance with defaults
        """
        config = cls()

        # Memory always enabled by default
        config._enabled["memory"] = True

        # Spectro disabled by default (requires API key)
        config._enabled["spectro"] = False

        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"tools": {name: {"enabled": enabled} for name, enabled in self._enabled.items()}}
