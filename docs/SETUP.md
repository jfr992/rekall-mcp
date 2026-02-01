# Setup Guide

Give Claude a memory that persists across conversations.

---

## What This Does

When you chat with Claude, it normally forgets everything when you close the conversation. This tool gives Claude:

- **Persistent memory** - Claude remembers your preferences, decisions, and project context
- **Smart search** - Claude can find relevant memories by meaning, not just keywords
- **Project awareness** - Claude knows which project you're working on

---

## Quick Start with Docker (Recommended)

Everything runs in containers. No Python install needed.

### Step 1: Start the Services

```bash
git clone <repo>
cd memento-mcp
docker compose up -d
```

This starts:
- **Qdrant** - Vector database for semantic search
- **MCP Server** - Memory tools with embeddings included

### Step 2: Tell Claude About It

Add this to your Claude Code config file (`~/.claude/claude_code_config.json`):

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

### Step 3: Verify It's Working

```bash
# Check services are running
docker compose ps

# Check health
curl http://localhost:8000/health
```

**Done.** Claude can now save and recall memories.

---

## Teaching Claude to Use Memory

Once the MCP server is running, add instructions to your project:

### Option A: Project-level (recommended)

Create `.claude/CLAUDE.md` in your project:

```markdown
## Memory System

This project uses persistent memory. At the START of each session:

1. Call `get_cached_context(project="my-project")` to load context
2. Include the result in your understanding of this project

When working, save important context:
- `save_memory("Must use Python 3.11+", type="requirement")`
- `save_memory("Chose PostgreSQL for JSON support", type="decision")`
- `save_memory("User prefers concise responses", type="preference")`
- `save_memory("AWS region is us-east-1", type="fact")`

Memory types guide AI behavior:
- **requirement**: Must be followed (non-negotiable)
- **decision**: Established choice (can be revisited if asked)
- **preference**: Show as default, offer alternatives
- **fact**: Informational context
```

### Option B: Global

Add to `~/.claude/CLAUDE.md` to use memory in all projects.

### Memory Tools Available

| Tool | Purpose |
|------|---------|
| `save_memory(content, type, project)` | Save something to remember |
| `recall_memories(query, ...)` | Search memories semantically |
| `get_project_context(project)` | Get all context for a project |
| `get_cached_context(project)` | Get stable context (for caching) |
| `memory_stats()` | Check storage statistics |

---

## Quick Start without Docker

If you prefer running locally:

### Step 1: Install

```bash
git clone <repo>
cd memento-mcp
pip install -e .
```

### Step 2: Start Qdrant

You still need Qdrant (easiest in Docker):

```bash
docker compose up -d qdrant
```

### Step 3: Tell Claude About It

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

### Step 4: Test It

```bash
cd src && python -c "
from config import get_config
print('Memory enabled:', get_config().tools.memory.enabled)
"
```

---

## How It Works (Simple Version)

```
You tell Claude something
        ↓
Claude saves it as a memory
        ↓
Memory gets converted to a "vector" (a list of numbers that capture meaning)
        ↓
Vector gets stored in Qdrant (a search database)
        ↓
Later, Claude can search by meaning to find relevant memories
```

**Your memories are stored in two places:**
1. **Files** (`~/.claude/memory/`) - Human-readable JSON, safe backup
2. **Qdrant** - Searchable vector database for fast semantic search

---

## Choosing an Embedding Provider

The "embedding" is what converts your text into searchable vectors. You have three options.

> **Important:** Once you start using one provider, switching to another requires a migration step. See [Switching Providers](#switching-providers-important) below. Pick one and stick with it if possible.

### Option A: sentence-transformers (Default)

**Best for:** Getting started, development, testing

- Runs entirely on your computer
- Free, no limits
- Fast
- Just works out of the box

```yaml
# config.yaml
tools:
  memory:
    embedding_provider: sentence-transformers
```

### Option B: Ollama

**Best for:** Better quality without cloud costs

- Runs on your computer
- Free, no limits
- Needs Ollama installed
- Better quality than sentence-transformers

> **Switching to this?** If you already have memories saved with another provider, you'll need to run `python -m memory.migrate` after changing your config.

Setup:
```bash
# Install Ollama
brew install ollama

# Download the embedding model
ollama pull nomic-embed-text

# Make sure Ollama is running
ollama serve
```

Config:
```yaml
tools:
  memory:
    embedding_provider: ollama
    embedding_model: nomic-embed-text
```

### Option C: Gemini

**Best for:** Best quality, light usage

- Runs in Google's cloud
- Free tier: 1,500 requests per day
- Best quality embeddings
- Needs internet connection

> **Switching to this?** If you already have memories saved with another provider, you'll need to run `python -m memory.migrate` after changing your config.

Setup:
1. Go to https://ai.google.dev/
2. Get a free API key
3. Set it in your environment: `export GEMINI_API_KEY=your-key`

Config:
```yaml
tools:
  memory:
    embedding_provider: gemini
    embedding_api_key: ${GEMINI_API_KEY}
```

---

## Switching Providers (Important!)

> **This requires extra steps.** You can't just change the config and expect it to work.

Each embedding provider creates vectors in its own "language." If you save memories with one provider and search with another, the search won't work - it's like asking someone who only speaks French to find a book in a Spanish library.

**What happens if you just change the config without migrating:**
- Your saved memory files are fine (they're just text)
- But searches will return wrong results or fail completely
- Claude won't be able to find your memories

**To switch providers safely:**

```bash
# Step 1: Update your config.yaml with the new provider
# (change embedding_provider to the new value)

# Step 2: Run the migration tool
cd src && python -m memory.migrate

# Step 3: Verify it worked
python -m memory.migrate --dry-run
# Should show "Found: X, Migrated: X"
```

**What the migration does:**
1. Reads all your memory files from `~/.claude/memory/`
2. Converts each one to a vector using the NEW provider
3. Rebuilds the search index from scratch
4. Your original files are never modified

**How long does it take?**
- Depends on how many memories you have
- ~100 memories: a few seconds (local) to ~1 minute (Gemini)
- The tool shows progress as it runs

**Preview before migrating:**
```bash
python -m memory.migrate --dry-run
```
This shows how many memories would be migrated without actually doing it.

---

## Data Safety & Backups

Your data is stored on your machine, not hidden in Docker volumes:

```
~/.claude/
├── memory/     # Your memories (JSON files)
└── qdrant/     # Search index (can be rebuilt)
```

### Backup

Just copy the folder:

```bash
cp -r ~/.claude ~/claude-backup-$(date +%Y%m%d)
```

### What if I lose the Qdrant data?

No problem. Your memory files are the source of truth. Rebuild the search index:

```bash
cd src && python -m memory.migrate
```

### What if I lose the memory files?

That's the real data. **Back them up.** The Qdrant index alone isn't enough.

### Changing the storage location

Set environment variables before starting:

```bash
export MEMORY_STORAGE_PATH=~/my-backup-location/memory
export QDRANT_DATA_PATH=~/my-backup-location/qdrant
docker compose up -d
```

---

## Storage Management

Without limits, memories accumulate forever. Here's how to manage growth.

### Check current usage

```bash
python -m memory.cleanup --stats
```

Output:
```
MEMORY STORAGE STATS
============================================================
Path: /home/user/.claude/memory
Memories: 423
Size: 1.2 MB
Oldest: 2024-01-15T10:30:00Z
Newest: 2024-06-01T14:22:00Z

Projections (at current average size):
  1,000 memories: ~2.8 MB
  10,000 memories: ~28 MB
```

### Set limits in config

```yaml
# config.yaml
tools:
  memory:
    max_memories: 1000    # Keep only the newest 1000
    max_age_days: 180     # Delete memories older than 6 months
```

### Manual cleanup

```bash
# Preview what would be deleted (safe)
python -m memory.cleanup --max-memories 1000 --dry-run

# Actually delete old memories
python -m memory.cleanup --max-memories 1000

# Delete by age
python -m memory.cleanup --max-age-days 90

# After cleanup, rebuild search index
python -m memory.migrate
```

### Recommended limits

| Use case | max_memories | max_age_days | Estimated size |
|----------|--------------|--------------|----------------|
| Light use | 500 | 90 | ~1 MB |
| Normal use | 1000 | 180 | ~3 MB |
| Heavy use | 5000 | 365 | ~15 MB |
| Unlimited | 0 | 0 | Grows forever |

---

## Configuration

### Using a Config File (Recommended)

Create `config.yaml` in the project root:

```yaml
qdrant:
  url: http://localhost:6333

tools:
  memory:
    enabled: true
    storage_path: ~/.claude/memory
    embedding_provider: sentence-transformers
```

### Using Environment Variables

```bash
export QDRANT_URL=http://localhost:6333
export MEMORY_STORAGE_PATH=~/.claude/memory
export EMBEDDING_PROVIDER=sentence-transformers
```

### Where Config Files Live

The system looks for config in this order:
1. Path you specify with `CONFIG_PATH` environment variable
2. `./config.yaml` in the current directory
3. `~/.config/memento-mcp/config.yaml` in your home directory
4. Built-in defaults

---

## Troubleshooting

### "Connection refused" to Qdrant

Qdrant isn't running. Start it:
```bash
docker compose up -d qdrant
```

### Memories not being found

Your search index might be out of sync. Rebuild it:
```bash
cd src && python -m memory.migrate
```

### "Rate limit exceeded" (Gemini)

You've hit the free tier limit (1,500/day). Options:
1. Wait until tomorrow
2. Switch to Ollama or sentence-transformers (free, unlimited) - **remember to run `python -m memory.migrate`**
3. Upgrade to Gemini paid tier

### Want to see what's happening?

```bash
LOG_LEVEL=DEBUG python -m server
```

---

## Reference

### All Configuration Options

<details>
<summary>Click to expand full reference</summary>

#### Qdrant Settings

| Setting | Default | What it does |
|---------|---------|--------------|
| `url` | `http://localhost:6333` | Where Qdrant is running |
| `api_key` | (none) | For Qdrant Cloud |

#### Memory Settings

| Setting | Default | What it does |
|---------|---------|--------------|
| `enabled` | `true` | Turn memory on/off |
| `storage_path` | `~/.claude/memory` | Where memory files are saved |
| `embedding_provider` | `sentence-transformers` | Which embedding service to use |
| `embedding_model` | `all-MiniLM-L6-v2` | Model name (varies by provider) |
| `embedding_api_key` | (none) | API key for cloud providers |
| `collection` | `agent_memory` | Qdrant collection name |

#### Server Settings

| Setting | Default | What it does |
|---------|---------|--------------|
| `transport` | `stdio` | How Claude connects (`stdio` or `http`) |
| `log_level` | `INFO` | How much logging to show |

#### Environment Variables

| Variable | Overrides |
|----------|-----------|
| `QDRANT_URL` | `qdrant.url` |
| `MEMORY_STORAGE_PATH` | `tools.memory.storage_path` |
| `EMBEDDING_PROVIDER` | `tools.memory.embedding_provider` |
| `GEMINI_API_KEY` | `tools.memory.embedding_api_key` |
| `OLLAMA_URL` | `tools.memory.embedding_base_url` |
| `LOG_LEVEL` | `server.log_level` |
| `CONFIG_PATH` | Path to config file |

</details>

---

## What's Next?

Once memory is working, Claude can:
- Remember your coding style preferences
- Track project decisions and why they were made
- Recall context from previous conversations
- Learn your naming conventions and patterns

Just start chatting with Claude and it will automatically save important context.
