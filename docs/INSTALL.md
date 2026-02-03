# Memory Plugin Installation Guide

This guide walks you through installing the Memory Plugin for Claude Code, which enables automatic context preservation across sessions.

## Prerequisites

- Claude Code CLI installed and configured
- Docker and Docker Compose installed
- Memento-MCP server running (see main README)

## Quick Start (5 Minutes)

### 1. Start the Memento-MCP Server

```bash
cd /path/to/memento-mcp
docker compose up -d
```

Verify it's running:
```bash
curl http://localhost:8000/health
# Expected: {"status": "healthy", ...}
```

### 2. Install Global Skills

Copy the pre-built skills to your global Claude directory:

```bash
# Create skills directory structure
mkdir -p ~/.claude/skills/{memory-restore,memory-observe,memory-recall,memory-stats}

# Copy skills from this repo
cp -r .claude/skills/memory-* ~/.claude/skills/
```

Or create them manually (see Manual Installation below).

### 3. Configure Global Hook

Create the auto-restore hook:

```bash
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
```

### 4. Restart Claude Code

Exit and restart Claude Code for the new skills to load.

### 5. Verify Installation

```bash
# Test memory stats
/memory-stats

# Expected output:
# {
#   "total_memories": ...,
#   "memory_files": ...,
#   ...
# }
```

## Manual Installation

### Step 1: Create memory-restore Skill

```bash
mkdir -p ~/.claude/skills/memory-restore
cat > ~/.claude/skills/memory-restore/SKILL.md << 'EOF'
---
name: memory-restore
description: Restore cached memories from previous sessions automatically at session start or when resuming work. Use when you need historical project knowledge, past decisions, or learnings.
user-invocable: true
---

# Session Memory Restoration

!`curl -s http://localhost:8000/api/memory/context 2>/dev/null | jq -r '.context // "No memories available"'`

Synthesize the above memories naturally into your understanding. Don't list them explicitly.

## Stats
!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq '{total: .total_memories, files: .memory_files}' || echo "Stats unavailable"`
EOF
```

### Step 2: Create memory-observe Skill

```bash
mkdir -p ~/.claude/skills/memory-observe
cat > ~/.claude/skills/memory-observe/SKILL.md << 'EOF'
---
name: memory-observe
description: Record important architecture decisions and discoveries. Auto-triggers when detecting decision language like "decided to use", "chose", "going with". Use for significant choices worth remembering across sessions.
user-invocable: true
allowed-tools: Bash(curl *)
---

# Record Observation: $ARGUMENTS

Save this to memory with auto-classification:

!`echo "{\"summary\": \"$ARGUMENTS\", \"type\": \"auto\"}" | curl -s http://localhost:8000/api/memory/observe -X POST -H "Content-Type: application/json" -d @- 2>/dev/null | jq -r '.status' 2>/dev/null || echo "Failed to save"`

✓ Observation recorded and available for future sessions.
EOF
```

### Step 3: Create memory-recall Skill

```bash
mkdir -p ~/.claude/skills/memory-recall
cat > ~/.claude/skills/memory-recall/SKILL.md << 'EOF'
---
name: memory-recall
description: Search memories using semantic search. Use when stuck, needing historical context, or looking for past solutions to similar problems. Triggers on questions about past work.
user-invocable: true
context: fork
agent: Explore
---

# Search Results: $ARGUMENTS

!`echo "{\"query\": \"$ARGUMENTS\", \"limit\": 5}" | curl -s http://localhost:8000/api/memory/recall -X POST -H "Content-Type: application/json" -d @- 2>/dev/null | jq -r '.memories[] | "[\(.type)] \(.content) (score: \(.score))"' 2>/dev/null || echo "No results found"`

Analyze and synthesize the above memories into your response.
EOF
```

### Step 4: Create memory-stats Skill

```bash
mkdir -p ~/.claude/skills/memory-stats
cat > ~/.claude/skills/memory-stats/SKILL.md << 'EOF'
---
name: memory-stats
description: Check memory system health and statistics. Use for diagnostics or understanding what's been stored.
user-invocable: true
---

# Memory System Status

!`curl -s http://localhost:8000/api/memory/stats 2>/dev/null | jq . || echo "Server not responding"`

**Troubleshooting:**
- Check: `docker compose ps`
- Start: `docker compose up -d`
- Health: `curl http://localhost:8000/health`
EOF
```

### Step 5: Configure Global Hook

```bash
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
```

### Step 6: Restart Claude Code

Exit and restart Claude Code to load the new configuration.

## Verification

### Test 1: Server Health

```bash
curl http://localhost:8000/health | jq .
```

Expected output:
```json
{
  "status": "healthy",
  "transport": "streamable-http",
  "tools_enabled": ["memory"]
}
```

### Test 2: Skills Loaded

Start Claude Code and check available skills:
- `/memory-restore` should appear in autocomplete
- `/memory-observe` should appear in autocomplete
- `/memory-recall` should appear in autocomplete
- `/memory-stats` should appear in autocomplete

### Test 3: Manual Invocation

```bash
/memory-stats
```

Expected: JSON output showing memory counts

### Test 4: Auto-Restore

1. Start a new Claude Code session
2. Send any message
3. Behind the scenes, `/memory-restore` should trigger
4. You should NOT see any mention of memory loading

### Test 5: Auto-Observe

In Claude Code, say:
```
I've decided to use PostgreSQL for this project
```

Expected: Claude acknowledges the decision (doesn't explicitly mention saving to memory)

Verify it saved:
```bash
/memory-recall PostgreSQL
```

Expected: Returns the decision you just made

### Test 6: Auto-Recall

In Claude Code, ask:
```
What database did we choose?
```

Expected: Claude recalls the PostgreSQL decision from memory

## Installation Modes

### Global Installation (Recommended)

**Location**: `~/.claude/skills/` and `~/.claude/hooks.json`

**Pros**:
- Works across all projects
- Single configuration
- Consistent experience

**Cons**:
- Requires memento-mcp server running locally
- May trigger even in non-memento projects

**Best for**: Users who want memory across all Claude Code sessions

### Project-Local Installation

**Location**: `.claude/skills/` and `.claude/hooks.json` (in project root)

**Pros**:
- Project-specific configuration
- No global pollution
- Git-committable (for teams)

**Cons**:
- Must configure per project
- Inconsistent across projects

**Best for**: Teams sharing Claude Code configurations via git

### Hybrid Installation

**Skills**: Global (`~/.claude/skills/`)
**Hook**: Project-local (`.claude/hooks.json`)

**Pros**:
- Skills available everywhere
- Auto-restore only in memento projects

**Best for**: Users working on multiple projects, only some using memento

## Configuration Options

### Change Auto-Restore Frequency

Edit `~/.claude/hooks.json`:

```json
{
  "user-prompt-submit": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "prompt",
          "prompt": "Only on new sessions (not every message), invoke /memory-restore if you haven't already this session."
        }
      ]
    }
  ]
}
```

### Disable Auto-Restore (Manual Mode)

Remove or comment out the hook:

```json
{
  "user-prompt-submit": []
}
```

Skills will still work manually: `/memory-restore`

### Customize Project Default

Edit `~/.claude/skills/memory-restore/SKILL.md`:

```bash
# Change this line:
!`curl -s http://localhost:8000/api/memory/context`

# To specify project:
!`curl -s 'http://localhost:8000/api/memory/context?project=my-project'`
```

### Adjust Search Sensitivity

Edit `~/.claude/skills/memory-recall/SKILL.md`:

```bash
# Change limit (default: 5)
!`echo "{\"query\": \"$ARGUMENTS\", \"limit\": 10}" | ...`

# Add score threshold (only high-quality matches)
!`echo "{\"query\": \"$ARGUMENTS\", \"limit\": 5, \"score_threshold\": 0.7}" | ...`
```

## Troubleshooting

### Skills Not Appearing

**Symptom**: `/memory-restore` not in autocomplete

**Fix**:
1. Verify files exist: `ls ~/.claude/skills/memory-*/SKILL.md`
2. Check permissions: `chmod 644 ~/.claude/skills/memory-*/SKILL.md`
3. Restart Claude Code
4. Check Claude Code logs for skill loading errors

### Hook Not Firing

**Symptom**: Memory not auto-restoring at session start

**Fix**:
1. Verify hook file: `cat ~/.claude/hooks.json`
2. Check JSON syntax: `jq . ~/.claude/hooks.json`
3. Restart Claude Code
4. Test manually: `/memory-restore` should work even if hook doesn't

### Server Connection Failed

**Symptom**: "Server not responding" or connection errors

**Fix**:
```bash
# Check if server is running
docker compose ps

# Check health
curl http://localhost:8000/health

# View logs
docker compose logs memento-mcp

# Restart server
docker compose restart mcp
```

### Empty Memory Results

**Symptom**: `/memory-recall` returns "No results found"

**Fix**:
```bash
# Check if memories exist
curl http://localhost:8000/api/memory/stats | jq .

# Check memory files
ls -la ~/.claude/memory/

# Test with broader query
/memory-recall project  # Instead of very specific terms
```

### Auto-Observe Not Saving

**Symptom**: Decisions not being saved automatically

**Fix**:
1. Test manual save: `/memory-observe test memory`
2. Check server logs: `docker compose logs mcp | grep observe`
3. Verify Qdrant: `docker compose ps | grep qdrant`
4. Check disk space: `df -h ~/.claude/memory`

### Permission Errors

**Symptom**: "Permission denied" when skills try to write

**Fix**:
```bash
# Ensure memory directory exists and is writable
mkdir -p ~/.claude/memory
chmod 755 ~/.claude/memory

# Check Docker volume permissions
docker compose down
docker volume rm memento-mcp_qdrant-data
docker compose up -d
```

## Uninstallation

### Remove Skills

```bash
rm -rf ~/.claude/skills/memory-*
```

### Remove Hook

```bash
# Remove entire hooks file
rm ~/.claude/hooks.json

# Or edit to remove memory-related hooks
nano ~/.claude/hooks.json
```

### Stop Server

```bash
cd /path/to/memento-mcp
docker compose down
```

### Remove Data (Optional)

```bash
# Remove YAML memories
rm -rf ~/.claude/memory/

# Remove Qdrant vector store
docker volume rm memento-mcp_qdrant-data
```

## Advanced Setup

### Multi-Project Configuration

Use project-specific contexts:

```bash
# In project A
/memory-observe Using React for frontend  # Saves to project: general

# Override in skill for project-specific
# Edit: ~/.claude/skills/memory-observe/SKILL.md
# Detect git repo name and pass as project parameter
```

### Team Sharing

Commit project-local skills to git:

```bash
cd your-project
mkdir -p .claude/skills
cp -r ~/.claude/skills/memory-* .claude/skills/
git add .claude/
git commit -m "Add memory plugin skills"
```

Team members can then:
```bash
git pull
# Skills automatically available (project-local mode)
```

### Custom Memory Server URL

For remote memento-mcp servers:

```bash
# Edit all skills, change:
http://localhost:8000

# To:
http://your-server.com:8000

# Or use environment variable in skill:
!`curl -s ${MEMORY_SERVER_URL:-http://localhost:8000}/api/memory/stats`
```

## Next Steps

After installation:

1. **Test the system**: Try the verification tests above
2. **Read the guide**: See [MEMORY_PLUGIN.md](./MEMORY_PLUGIN.md) for detailed usage
3. **Explore memories**: Check `~/.claude/memory/*.yaml` to see saved data
4. **Customize**: Adjust skill triggers and hook behavior to your workflow

## Support

If you encounter issues:

1. Check [Troubleshooting](#troubleshooting) section
2. Review server logs: `docker compose logs mcp`
3. Test API directly: `curl http://localhost:8000/health`
4. Open an issue on GitHub with logs and error messages
