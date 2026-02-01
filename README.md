# Memento MCP

**Persistent memory for AI assistants.** Give Claude (or any MCP-compatible AI) the ability to remember context across sessions.

> *"The people who are crazy enough to think they can change the world are the ones who do."*

---

## Philosophy

Every conversation with an AI starts from zero. You explain the same context, repeat the same preferences, re-establish the same decisions. It's like working with a brilliant colleague who has amnesia.

**Memento changes that.**

We believe AI assistants should:
- **Remember** what matters across sessions
- **Understand** context, not just keywords
- **Respect** privacy by keeping data local
- **Guide** behavior based on memory type (preferences suggest, requirements constrain)

This isn't just about saving tokens. It's about building a relationship with your AI where continuity exists.

---

## Quick Start

### 1. Clone and Start

```bash
git clone https://github.com/jfr992/memento-mcp.git
cd memento-mcp
docker compose up -d
```

### 2. Configure Claude

Add to `~/.claude/claude_code_config.json`:

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

### 3. Verify

```bash
curl http://localhost:8000/health
```

**Done.** Claude now has persistent memory.

---

## How It Works

```
You: "Let's use PostgreSQL for its JSON support"
AI:  *saves decision to memory*

[3 days later]

You: "What database did we choose?"
AI:  *semantic search finds the memory*
     "We chose PostgreSQL for its JSON support"
```

Memories are:
- **Stored locally** in `~/.claude/memory/` (JSON files you own)
- **Searchable** via Qdrant vector database (semantic, not just keywords)
- **Sanitized** automatically (credentials are redacted)

---

## Memory Types

Not all memories are equal. The type guides how AI should use them:

| Type | Purpose | AI Behavior |
|------|---------|-------------|
| `requirement` | Hard constraints | **Must** follow |
| `decision` | Past choices | Reference, can revisit if asked |
| `preference` | User preferences | Show as default, offer alternatives |
| `fact` | Context/environment | Informational background |
| `learning` | Lessons learned | Apply to similar situations |

**Example:**
```
"Must use Python 3.11+" (requirement) → AI will not suggest Python 3.10
"Prefers Terraform" (preference) → AI suggests Terraform but mentions alternatives
"Chose PostgreSQL" (decision) → AI references it, asks before changing
```

---

## Tools Available

| Tool | Purpose |
|------|---------|
| `save_memory(content, type, project)` | Save context for future recall |
| `recall_memories(query)` | Semantic search across memories |
| `get_project_context(project)` | All memories for a project |
| `get_cached_context(project)` | Stable context for prompt caching |
| `memory_stats()` | Storage statistics |

---

## Data Safety

Your data stays on your machine:

```
~/.claude/
├── memory/     # Your memories (JSON files, human-readable)
└── qdrant/     # Search index (can be rebuilt from memory/)
```

- **Credentials** are automatically redacted before storage
- **Backup** is just `cp -r ~/.claude ~/backup`
- **Nothing leaves your machine** unless you configure it to

---

## Cost Savings

### Token Savings
Less re-explaining context = fewer input tokens.
- ~80% reduction in repetitive context tokens

### Prompt Cache Savings
`get_cached_context()` returns identical content each call.
- Put at the start of every prompt
- After turn 1, you get 90% discount on those tokens
- 10k tokens cached = ~$54/month savings at high usage

---

## Documentation

| Document | Purpose |
|----------|---------|
| [Setup Guide](docs/SETUP.md) | Installation, embedding providers, backups |
| [Vision](docs/VISION.md) | Why this exists, where we're going |
| [Architecture](docs/ARCHITECTURE.md) | Technical design |
| [Tools](docs/TOOLS.md) | Adding your own tools |

---

## Requirements

- Docker (recommended) or Python 3.11+
- ~500MB disk for embedding model
- Works on macOS, Linux, Windows (WSL)

---

## License

MIT - Use it however you want.

---

<details>
<summary><b>For Developers</b></summary>

### Local Development

```bash
pip install -e ".[dev]"
docker compose up -d qdrant  # Need vector database
cd src && python -m server
```

### Running Tests

```bash
docker compose run --rm memento-test
# or locally
pytest tests/ -v
```

### Project Structure

```
src/
├── server.py     # MCP server entry point
├── config.py     # Configuration
├── core/         # Shared infrastructure (embeddings, vector store, telemetry)
├── memory/       # Memory system (manager, cleanup, migration)
└── tools/        # Pluggable tool system
```

</details>
