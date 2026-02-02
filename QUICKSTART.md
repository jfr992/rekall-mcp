# Quick Start: Fresh Memory Setup

Your old memories are backed up in `~/memento-backup-20260202/`

---

## Step 1: Start Docker with Persistent Storage

```bash
cd /Users/dev-box/Repos/memento-mcp

# Start everything (Qdrant + MCP server)
docker compose up -d

# Wait 5 seconds for startup
sleep 5

# Verify running
docker compose ps
```

Expected output:
```
NAME             STATUS
memento-mcp      Up
memento-qdrant   Up
```

**Where data is stored:**
- Memory files: `~/.claude/memory/` (YAML files you can edit)
- Search index: `~/.claude/qdrant/` (rebuilt from YAML if deleted)

---

## Step 2: Configure Claude (Single Command)

```bash
claude mcp add memory --type http --url http://localhost:8000
```

**Verify it worked:**
```bash
claude mcp list
```

Should show:
```
memory (http) - http://localhost:8000
```

<details>
<summary><b>Alternative: Manual config</b> (if `claude mcp` command doesn't exist)</summary>

Edit `~/.claude/claude_code_config.json`:

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

</details>

---

## Step 3: Tell Claude to Use Memory Automatically

Add to `~/.claude/CLAUDE.md` (creates if doesn't exist):

```bash
cat >> ~/.claude/CLAUDE.md << 'EOF'

## Memory System

At the START of each session:
1. Call `get_cached_context()` to restore memory from previous sessions
2. Use the context to understand user preferences and project history

During work:
- Call `observe(summary)` after completing tasks to save what you learned
- The system automatically classifies memory type (decision/preference/learning/etc)

EOF

echo "✅ Added memory instructions to ~/.claude/CLAUDE.md"
```

---

## Step 4: Test It Works

### Test 1: Health Check
```bash
curl http://localhost:8000/health
```

Expected: `{"status":"healthy"}`

### Test 2: Save a Memory
```bash
curl -X POST http://localhost:8000/tools/save_memory \
  -H "Content-Type: application/json" \
  -d '{
    "content": "User prefers concise responses without fluff",
    "type": "preference",
    "project": "general"
  }'
```

Expected: `{"memory_id":"2026-02-02_preference_XXXX","status":"saved"}`

### Test 3: Check Memory File Created
```bash
ls -lh ~/.claude/memory/
cat ~/.claude/memory/$(date +%Y-%m-%d).yaml
```

Expected: You'll see today's YAML file with your saved memory

### Test 4: Search Memory
```bash
curl -X POST http://localhost:8000/tools/recall_memories \
  -H "Content-Type: application/json" \
  -d '{"query": "how should I respond to the user"}'
```

Expected: Returns your "prefers concise responses" memory with a score

---

## Step 5: Use with Claude

**Restart Claude Code** to pick up the config, then:

```
You: "Remember that I prefer TypeScript over JavaScript"
Claude: *calls observe()* → Saved to memory

You: "What are my preferences?"
Claude: *calls recall_memories()* → Finds your preferences

You: "What do you know about me?"
Claude: *calls get_cached_context()* → Shows all your memories
```

---

## How to Verify Claude is Using Memory

### Check 1: Watch Docker Logs
```bash
docker compose logs -f mcp
```

You'll see:
```
INFO: Memory saved: 2026-02-02_preference_XXXX
INFO: Recall query: "user preferences"
INFO: Found 3 memories
```

### Check 2: Look at Memory Files
```bash
# See what was saved today
cat ~/.claude/memory/$(date +%Y-%m-%d).yaml

# Count total memories
grep -r "^  - id:" ~/.claude/memory/ | wc -l
```

### Check 3: Memory Stats
```bash
curl http://localhost:8000/tools/memory_stats
```

Shows:
```json
{
  "total_memories": 5,
  "by_type": {
    "preference": 2,
    "decision": 1,
    "learning": 2
  },
  "storage_size_mb": 0.002,
  "qdrant_status": "healthy"
}
```

---

## Metrics & Observability

### Real-time Metrics
```bash
# Watch what's happening
docker compose logs -f mcp | grep -E "save_memory|recall|observe"
```

### Storage Stats
```bash
# How much space
du -sh ~/.claude/memory ~/.claude/qdrant

# How many memories
find ~/.claude/memory -name "*.yaml" -exec grep -c "^  - id:" {} + | awk '{s+=$1} END {print s " memories"}'
```

### Qdrant Admin UI
```bash
# Open in browser
open http://localhost:6333/dashboard
```

Shows:
- Collection: `agent_memory`
- Vectors count
- Dimension: 384 (sentence-transformers) or 768 (ollama/gemini)

---

## Troubleshooting

### Memory not saving?
```bash
# Check MCP server logs
docker compose logs mcp --tail 50

# Check if Qdrant is reachable from MCP
docker compose exec mcp curl -s http://qdrant:6333/healthz
```

### Claude not finding memories?
```bash
# Rebuild search index
docker compose exec mcp python -c "
from memory.manager import MemoryManager
m = MemoryManager()
print('Rebuilding index...')
# Index gets rebuilt automatically on next search
"
```

### Clear everything and start over?
```bash
# Backup first
cp -r ~/.claude/memory ~/memory-backup-$(date +%Y%m%d-%H%M)

# Clear
rm -rf ~/.claude/memory/*
rm -rf ~/.claude/qdrant/*

# Restart
docker compose restart
```

---

## What to Watch For

**Signs it's working:**
1. Files appear in `~/.claude/memory/YYYY-MM-DD.yaml`
2. Docker logs show "Memory saved" and "Recall query"
3. Qdrant dashboard shows vectors in `agent_memory` collection
4. Claude mentions "I remember..." or "Based on our previous conversation..."

**Signs it's NOT working:**
1. No files in `~/.claude/memory/`
2. Claude says "I don't have access to previous conversations"
3. `curl http://localhost:8000/health` fails
4. Qdrant dashboard shows 0 vectors

---

## Example Session

```bash
# Start fresh
docker compose up -d

# Wait for startup
sleep 5

# Save some preferences
curl -X POST http://localhost:8000/tools/save_memory \
  -H "Content-Type: application/json" \
  -d '{"content": "User is working on memento-mcp project", "type": "fact"}'

curl -X POST http://localhost:8000/tools/save_memory \
  -H "Content-Type: application/json" \
  -d '{"content": "Decided to use Docker for deployment", "type": "decision"}'

# Check what was saved
cat ~/.claude/memory/$(date +%Y-%m-%d).yaml

# Search
curl -X POST http://localhost:8000/tools/recall_memories \
  -H "Content-Type: application/json" \
  -d '{"query": "what project am I working on"}'
```

Now talk to Claude - it will remember everything you just saved.
