# Pluggable Tool System

Add tools incrementally. Configure what's enabled. Keep everything observable.

---

## Quick Start

```bash
# Start with memory tools (default)
python -m server
```

---

## Available Tools

### Memory (Built-in)
Persistent context for AI assistants. Always available.

| Tool | Description |
|------|-------------|
| `save_memory` | Save a memory (decision, preference, requirement, fact, learning, note) |
| `recall_memories` | Search memories semantically |
| `get_project_context` | Get all context for a project |
| `get_cached_context` | Get stable context for prompt caching |
| `memory_stats` | Get memory system statistics |

---

## Configuration

### Option 1: YAML File

Create `config.yaml`:

```yaml
tools:
  memory:
    enabled: true
    storage_path: ~/.claude/memory
    embedding_provider: sentence-transformers
```

### Option 2: Environment Variables

```bash
# Configure memory
MEMORY_STORAGE_PATH=~/.claude/memory python -m server
```

### Option 3: Custom Config Path

```bash
MCP_CONFIG=/path/to/config.yaml python -m server
```

---

## Adding New Tools

### 1. Create a Tool Provider

```python
# tools/builtin/my_tool.py
from tools.base import BaseToolProvider, ToolDefinition

class MyToolProvider(BaseToolProvider):
    name = "my_tool"
    description = "What it does"

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="do_something",
                description="Does something useful",
                handler=self.do_something,
            ),
        ]

    async def do_something(self, arg: str) -> str:
        return f"Did something with {arg}"
```

### 2. Register It

```python
# tools/builtin/__init__.py
from .my_tool import MyToolProvider

BUILTIN_PROVIDERS = [
    # ... existing
    MyToolProvider,
]
```

### 3. Enable in Config

```yaml
tools:
  my_tool:
    enabled: true
```

---

## MCP Server Integration

### HTTP Mode (Docker)

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://localhost:8000"
    }
  }
}
```

### stdio Mode (Local)

```json
{
  "mcpServers": {
    "memory": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "/path/to/memento-mcp"
    }
  }
}
```

---

## Architecture

```
tools/
├── base.py         # BaseToolProvider interface
├── registry.py     # Tool discovery
├── loader.py       # Registration with MCP
└── builtin/
    └── memory.py   # Memory tools
```

Each tool provider:
1. Inherits from `BaseToolProvider`
2. Defines `name`, `description`
3. Implements `get_tools()` returning `ToolDefinition` list
4. Implements `register(mcp)` to add tools to server
