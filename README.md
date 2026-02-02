# Memento MCP

**Give Claude a memory.** Three steps, five minutes.

---

## Install

### 1. Download and Start

```bash
git clone https://github.com/jfr992/memento-mcp.git
cd memento-mcp
docker compose up -d
```

> **Need Docker?** Get it free at [docker.com/get-started](https://www.docker.com/get-started/)

### 2. Tell Claude

```bash
claude mcp add --transport http memory http://localhost:8000
```

### 3. Verify

```bash
curl http://localhost:8000/health
```

**Done.** Claude now remembers things between sessions.

---

## How to Use

Just talk normally. Claude automatically remembers:

- **Decisions** → "Let's use PostgreSQL"
- **Preferences** → "I prefer TypeScript"
- **Lessons** → "That bug was caused by..."

To check memories: *"What do you remember about this project?"*

---

## Your Data

Everything stays on your computer in editable files:

```
~/.claude/memory/2026-02-02.yaml   ← Open in any text editor
```

Nothing is sent anywhere. Backup = copy the folder.

---

## How Search Works

Memories are converted to **embeddings** (vectors that capture meaning) for semantic search:

```
"Use PostgreSQL" → [0.12, 0.45, 0.78, ...]  ← Numbers that represent meaning
```

When you ask "what database?", Claude searches by meaning, not keywords.

**Embedding options** (see [docs/SETUP.md](docs/SETUP.md)):
| Provider | Runs on | Cost | Quality |
|----------|---------|------|---------|
| `sentence-transformers` | Your computer | Free | Good (default) |
| `ollama` | Your computer | Free | Better |
| `gemini` | Google Cloud | Free tier | Best |

---

## Troubleshooting

**"Connection refused"** → Make sure Docker is running: `docker compose ps`

**"Claude forgets"** → Add to `~/.claude/CLAUDE.md`:
```
At session start, call get_cached_context() to restore memory.
```

**Restart everything:** `docker compose down && docker compose up -d`

---

<details>
<summary><b>How It Works</b></summary>

### The Flow

```
You say something important
        ↓
Claude saves it → YAML file (~/.claude/memory/)
        ↓
Text → Embedding (vector of numbers capturing meaning)
        ↓
Vector → Qdrant (search database)
        ↓
Later: Claude searches by meaning, finds relevant memories
```

### Example

```
You: "Let's use PostgreSQL for JSON support"
AI:  *saves to memory + creates embedding*

[3 days later]

You: "What database did we choose?"
AI:  *semantic search finds the memory*
     "We chose PostgreSQL for its JSON support"
```

### Memory Types

| Type | Example | AI Behavior |
|------|---------|-------------|
| `requirement` | "Must use Python 3.11+" | **Must** follow |
| `decision` | "Chose PostgreSQL" | Reference, can revisit |
| `preference` | "Prefers Terraform" | Suggest, offer alternatives |
| `fact` | "Project uses AWS" | Background context |
| `learning` | "JWT bug fix" | Apply to similar cases |

### Tools

| Tool | Purpose |
|------|---------|
| `observe(summary)` | Auto-save what was accomplished |
| `recall_memories(query)` | Search memories |
| `get_cached_context(project)` | Get all context (for prompt caching) |
| `memory_stats()` | Storage stats |

</details>

---

<details>
<summary><b>Cost Savings</b></summary>

### Token Savings
- ~80% reduction in repetitive context

### Prompt Cache Savings
`get_cached_context()` returns identical content → 90% discount after turn 1

At high usage: **~$54/month savings** per 10k cached tokens

</details>

---

<details>
<summary><b>For Developers</b></summary>

### Local Development

```bash
pip install -e ".[dev]"
docker compose up -d qdrant
cd src && python -m server
```

### Tests

```bash
docker compose --profile test run --rm test
```

### Project Structure

```
src/
├── server.py       # MCP entry point
├── core/           # Embeddings, vector store, telemetry
├── memory/         # Memory manager, cleanup, migration
├── crawler/        # Documentation crawler (optional)
├── indexer/        # Document chunker + Qdrant indexer
└── tools/          # Pluggable tool system
```

### Documentation

| Doc | Purpose |
|-----|---------|
| [docs/SETUP.md](docs/SETUP.md) | Detailed setup, embedding providers, migration |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical design |
| [docs/TOOLS.md](docs/TOOLS.md) | Adding custom tools |
| [docs/EXAMPLES.md](docs/EXAMPLES.md) | Real-world usage patterns |
| [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) | Metrics and monitoring |

</details>

---

## Requirements

- Docker (or Python 3.11+)
- ~500MB disk (embedding model downloads on first use)
- macOS, Linux, or Windows (WSL)

---

## License

MIT
