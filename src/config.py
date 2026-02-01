"""Unified configuration for the MCP server.

All settings in one place. Loads from:
1. config.yaml (recommended)
2. Environment variables (override)
3. Defaults (fallback)

Example config.yaml:
    qdrant:
      url: http://localhost:6333

    tools:
      memory:
        enabled: true
        storage_path: ~/.claude/memory

      spectro:
        enabled: true
        api_url: https://api.spectrocloud.com
        api_key: ${SPECTRO_API_KEY}  # Reference env var

Usage:
    from config import Config

    config = Config.load()
    print(config.qdrant.url)
    print(config.tools.memory.storage_path)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class QdrantConfig:
    """Qdrant vector database settings."""

    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_prefix: str = ""  # e.g., "prod_" for prod_agent_memory


@dataclass
class MemoryToolConfig:
    """Memory tool settings."""

    enabled: bool = True
    storage_path: str = "~/.claude/memory"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_provider: str = "sentence-transformers"  # or "ollama", "gemini"
    embedding_api_key: str = ""  # For Gemini
    embedding_base_url: str = ""  # For Ollama (default: http://localhost:11434)
    collection: str = "agent_memory"
    # Storage limits (0 = unlimited)
    max_memories: int = 0  # Maximum number of memories to keep
    max_age_days: int = 0  # Delete memories older than this


@dataclass
class SpectroToolConfig:
    """Spectro Cloud tool settings."""

    enabled: bool = False  # Disabled by default (needs API key)
    api_url: str = "https://api.spectrocloud.com"
    api_key: str = ""
    project_uid: str = ""
    search_api_url: str = ""  # Optional semantic search API
    collection: str = "spectro_docs"
    docs_index: str = "spectro"  # Which docs index to use (data/{name}_docs.yaml)
    custom_docs_path: str = ""  # Or provide custom YAML path


@dataclass
class ToolsConfig:
    """All tool configurations."""

    memory: MemoryToolConfig = field(default_factory=MemoryToolConfig)
    spectro: SpectroToolConfig = field(default_factory=SpectroToolConfig)


@dataclass
class ServerConfig:
    """MCP server settings."""

    transport: str = "stdio"  # or "streamable-http"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class Config:
    """Unified configuration."""

    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load configuration from file and environment.

        Priority:
        1. Explicit path argument
        2. CONFIG_PATH environment variable
        3. ./config.yaml
        4. ~/.config/spectro-mcp/config.yaml
        5. Defaults
        """
        config = cls()

        # Find config file
        config_path = cls._find_config_file(path)

        # Load from file if exists
        if config_path and config_path.exists():
            config = cls._load_from_file(config_path)

        # Override with environment variables
        config = cls._apply_env_overrides(config)

        return config

    @classmethod
    def _find_config_file(cls, explicit_path: str | Path | None) -> Path | None:
        """Find the config file to use."""
        if explicit_path:
            return Path(explicit_path)

        # Check environment
        env_path = os.environ.get("CONFIG_PATH")
        if env_path:
            return Path(env_path)

        # Check current directory
        local_config = Path("config.yaml")
        if local_config.exists():
            return local_config

        # Check user config directory
        user_config = Path.home() / ".config" / "spectro-mcp" / "config.yaml"
        if user_config.exists():
            return user_config

        return None

    @classmethod
    def _load_from_file(cls, path: Path) -> "Config":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Expand environment variable references
        data = cls._expand_env_vars(data)

        config = cls()

        # Qdrant
        if "qdrant" in data:
            q = data["qdrant"]
            config.qdrant = QdrantConfig(
                url=q.get("url", config.qdrant.url),
                api_key=q.get("api_key"),
                collection_prefix=q.get("collection_prefix", ""),
            )

        # Tools
        if "tools" in data:
            tools = data["tools"]

            if "memory" in tools:
                m = tools["memory"]
                config.tools.memory = MemoryToolConfig(
                    enabled=m.get("enabled", True),
                    storage_path=m.get("storage_path", "~/.claude/memory"),
                    embedding_model=m.get("embedding_model", "all-MiniLM-L6-v2"),
                    embedding_dim=m.get("embedding_dim", 384),
                    embedding_provider=m.get("embedding_provider", "sentence-transformers"),
                    embedding_api_key=m.get("embedding_api_key", ""),
                    embedding_base_url=m.get("embedding_base_url", ""),
                    collection=m.get("collection", "agent_memory"),
                    max_memories=m.get("max_memories", 0),
                    max_age_days=m.get("max_age_days", 0),
                )

            if "spectro" in tools:
                s = tools["spectro"]
                config.tools.spectro = SpectroToolConfig(
                    enabled=s.get("enabled", False),
                    api_url=s.get("api_url", "https://api.spectrocloud.com"),
                    api_key=s.get("api_key", ""),
                    project_uid=s.get("project_uid", ""),
                    search_api_url=s.get("search_api_url", ""),
                    collection=s.get("collection", "spectro_docs"),
                )

        # Server
        if "server" in data:
            srv = data["server"]
            config.server = ServerConfig(
                transport=srv.get("transport", "stdio"),
                log_level=srv.get("log_level", "INFO"),
                host=srv.get("host", "0.0.0.0"),
                port=srv.get("port", 8000),
            )

        return config

    @classmethod
    def _expand_env_vars(cls, data: Any) -> Any:
        """Recursively expand ${VAR} references in config values."""
        if isinstance(data, dict):
            return {k: cls._expand_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls._expand_env_vars(v) for v in data]
        elif isinstance(data, str):
            # Expand ${VAR} patterns
            import re

            pattern = r"\$\{([^}]+)\}"

            def replace(match):
                var_name = match.group(1)
                return os.environ.get(var_name, "")

            return re.sub(pattern, replace, data)
        return data

    @classmethod
    def _apply_env_overrides(cls, config: "Config") -> "Config":
        """Override config with environment variables."""
        # Qdrant
        if url := os.environ.get("QDRANT_URL"):
            config.qdrant.url = url
        if api_key := os.environ.get("QDRANT_API_KEY"):
            config.qdrant.api_key = api_key

        # Spectro
        if api_key := os.environ.get("SPECTRO_API_KEY"):
            config.tools.spectro.api_key = api_key
            # Auto-enable if API key is provided
            config.tools.spectro.enabled = True
        if api_url := os.environ.get("SPECTRO_API_URL"):
            config.tools.spectro.api_url = api_url
        if project_uid := os.environ.get("SPECTRO_PROJECT_UID"):
            config.tools.spectro.project_uid = project_uid
        if search_url := os.environ.get("SPECTRO_SEARCH_API_URL"):
            config.tools.spectro.search_api_url = search_url

        # Memory
        if storage := os.environ.get("MEMORY_STORAGE_PATH"):
            config.tools.memory.storage_path = storage
        if provider := os.environ.get("EMBEDDING_PROVIDER"):
            config.tools.memory.embedding_provider = provider
        if api_key := os.environ.get("GEMINI_API_KEY"):
            config.tools.memory.embedding_api_key = api_key
        if base_url := os.environ.get("OLLAMA_URL"):
            config.tools.memory.embedding_base_url = base_url

        # Server
        if transport := os.environ.get("MCP_TRANSPORT"):
            config.server.transport = transport
        if log_level := os.environ.get("LOG_LEVEL"):
            config.server.log_level = log_level

        # TOOLS_ENABLED override
        if enabled := os.environ.get("TOOLS_ENABLED"):
            for name in enabled.split(","):
                name = name.strip()
                if name == "memory":
                    config.tools.memory.enabled = True
                elif name == "spectro":
                    config.tools.spectro.enabled = True

        # TOOLS_DISABLED override
        if disabled := os.environ.get("TOOLS_DISABLED"):
            for name in disabled.split(","):
                name = name.strip()
                if name == "memory":
                    config.tools.memory.enabled = False
                elif name == "spectro":
                    config.tools.spectro.enabled = False

        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (for serialization)."""
        return {
            "qdrant": {
                "url": self.qdrant.url,
                "api_key": "***" if self.qdrant.api_key else None,
                "collection_prefix": self.qdrant.collection_prefix,
            },
            "tools": {
                "memory": {
                    "enabled": self.tools.memory.enabled,
                    "storage_path": self.tools.memory.storage_path,
                    "collection": self.tools.memory.collection,
                },
                "spectro": {
                    "enabled": self.tools.spectro.enabled,
                    "api_url": self.tools.spectro.api_url,
                    "api_key": "***" if self.tools.spectro.api_key else "",
                    "collection": self.tools.spectro.collection,
                },
            },
            "server": {
                "transport": self.server.transport,
                "log_level": self.server.log_level,
            },
        }

    def save(self, path: str | Path) -> None:
        """Save config to YAML file (without secrets)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Don't save actual secrets
        data = {
            "qdrant": {
                "url": self.qdrant.url,
                "collection_prefix": self.qdrant.collection_prefix,
            },
            "tools": {
                "memory": {
                    "enabled": self.tools.memory.enabled,
                    "storage_path": self.tools.memory.storage_path,
                    "embedding_model": self.tools.memory.embedding_model,
                    "collection": self.tools.memory.collection,
                },
                "spectro": {
                    "enabled": self.tools.spectro.enabled,
                    "api_url": self.tools.spectro.api_url,
                    "api_key": "${SPECTRO_API_KEY}",  # Reference, not value
                    "project_uid": self.tools.spectro.project_uid or "${SPECTRO_PROJECT_UID}",
                    "collection": self.tools.spectro.collection,
                },
            },
            "server": {
                "transport": self.server.transport,
                "log_level": self.server.log_level,
            },
        }

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# Singleton instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def reload_config() -> Config:
    """Reload configuration from disk."""
    global _config
    _config = Config.load()
    return _config
