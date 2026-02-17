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

### Python API

```python
from memory import MemoryManager

memory = MemoryManager()

# Save
memory.save("Chose PostgreSQL for JSON support", type="decision", project="my-app")
memory.save("User prefers concise responses", type="preference")

# Recall (semantic search)
results = memory.recall("what database did we choose?")
for r in results:
    print(f"[{r['score']:.2f}] {r['content']}")

# Project context
context = memory.get_project_context("my-app")
```

### CLI

```bash
# Save
python -m memory.cli save "Decided to use PostgreSQL" --type decision --project my-app

# Recall
python -m memory.cli recall "database choices"
python -m memory.cli recall "recent work" --limit 3 --days 7

# Stats
python -m memory.cli stats
```

---

## Memory Plugin (Auto-Triggering Skills)

Make memory completely automatic with the Memory Plugin.

Instead of manually calling memory tools, the plugin:
- **Auto-restores** context at session start (silently)
- **Auto-saves** decisions when detected ("decided to use...")
- **Auto-recalls** memories when you ask questions
- **Works invisibly** - feels like Claude naturally "remembers"

### Quick Install

```bash
# 1. Copy pre-built skills
cp -r .claude/skills/memory-* ~/.claude/skills/

# 2. Enable auto-restore hook
cat > ~/.claude/hooks.json << 'EOF'
{
  "user-prompt-submit": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "prompt",
          "prompt": "If this is a new session or after context compaction, silently invoke /memory-restore to load cached memories. Never mention the memory system to the user."
        }
      ]
    }
  ]
}
EOF

# 3. Restart Claude Code
```

### Available Skills

- `/memory-restore` - Load cached memories (auto-triggered at session start)
- `/memory-observe <note>` - Save an observation manually
- `/memory-recall <query>` - Search memories semantically
- `/memory-stats` - Check system health

### Installation Modes

| Mode | Skills location | Hook location | Best for |
|------|----------------|---------------|----------|
| **Global** | `~/.claude/skills/` | `~/.claude/hooks.json` | Memory across all projects |
| **Project-local** | `.claude/skills/` | `.claude/hooks.json` | Teams sharing config via git |
| **Hybrid** | `~/.claude/skills/` | `.claude/hooks.json` (project) | Multi-project, selective auto-restore |

See **[How It Works](docs/MEMORY_PLUGIN.md)** for architecture and technical details.

---

## Your Data

Everything stays on your computer in editable files:

```
~/.claude/memory/2026-02-02.yaml   <- Open in any text editor
```

Nothing is sent anywhere. Backup = copy the folder.

Credentials are automatically sanitized before storage:

```
Input:  "Set api_key to sk-abc123def456"
Stored: "Set api_key to [REDACTED]"
```

---

## How Search Works

Memories are converted to **embeddings** (vectors that capture meaning) for semantic search:

```
"Use PostgreSQL" -> [0.12, 0.45, 0.78, ...]  <- Numbers that represent meaning
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

**Memories not found** → Rebuild the search index: `cd src && python -m memory.migrate`

**"Rate limit exceeded" (Gemini)** → Switch to sentence-transformers (free, unlimited), then run `python -m memory.migrate`

**Restart everything:** `docker compose down && docker compose up -d`

---

<details>
<summary><b>How It Works</b></summary>

### The Flow

```
You say something important
        |
Claude saves it -> YAML file (~/.claude/memory/)
        |
Text -> Embedding (vector of numbers capturing meaning)
        |
Vector -> Qdrant (search database)
        |
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
| `GET /api/memory/graph` | Memory nodes + semantic edges for the brain dashboard |
| `/dashboard` | Browser UI for exploring memory clusters as a neural network |

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

Tests run in an isolated environment and **never affect your production data**.

```bash
# Run all tests
docker compose --profile test run --rm test

# Run specific test file
docker compose --profile test run --rm test pytest tests/test_memory.py -v

# Cleanup
docker compose --profile test down
```

**What happens:**
- `qdrant-test` starts on port 6334 with ephemeral tmpfs storage
- Tests use `/tmp/test_memory` for YAML files (inside container)
- Your production data at `~/.claude/memory/` and `~/.claude/qdrant/` stays untouched
- Everything auto-deletes when tests finish

### Observability

Every operation is tracked via the Telemetry singleton:

```python
from core import Telemetry

telemetry = Telemetry.get()
print(telemetry.summary())
# memory.save      | 20 calls | p50=12.2ms | 100.0% ok
# memory.recall    | 15 calls | p50=10.7ms | 100.0% ok
# embedder.encode  | 35 calls | p50= 6.1ms | 100.0% ok

# OTEL-compatible metrics dict
metrics = telemetry.get_metrics()

# Track custom operations
with telemetry.track("my_operation"):
    pass
```

### Project Structure

```
src/
├── server.py       # MCP entry point
├── core/           # Embeddings, vector store, telemetry, utils
├── memory/         # Memory manager, cleanup, migration
├── crawler/        # Documentation crawler (optional)
├── indexer/        # Document chunker + Qdrant indexer
└── tools/          # Pluggable tool system
```

### Documentation

| Doc | Purpose |
|-----|---------|
| [docs/MEMORY_PLUGIN.md](docs/MEMORY_PLUGIN.md) | Memory Plugin architecture and features |
| [docs/SETUP.md](docs/SETUP.md) | Detailed setup, embedding providers, migration |
| [docs/TUNING.md](docs/TUNING.md) | Customize what Claude remembers |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical design, adding tools |
| [docs/example-memory.yaml](docs/example-memory.yaml) | Example YAML memory file |

</details>

---

## Requirements

- Docker (or Python 3.11+)
- ~500MB disk (embedding model downloads on first use)
- macOS, Linux, or Windows (WSL)

---

## License

MIT
