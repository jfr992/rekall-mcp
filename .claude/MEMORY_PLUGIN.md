# Memory Plugin Usage

This project uses auto-triggering memory skills for seamless context preservation across sessions.

## How It Works

The memory plugin operates through 4 intelligent skills that interact with the memento-mcp REST API:

### Automatic Operations

- **Session Start**: Memory automatically restored via global hook
- **After Decisions**: Say "I've decided..." → auto-observes
- **When Stuck**: Ask "what did we...?" → auto-recalls
- **Health Checks**: System monitors memory availability

### Manual Invocation

When you need explicit control:

```bash
/memory-restore              # Load all cached memories
/memory-observe <note>       # Save a specific observation
/memory-recall <query>       # Search for past context
/memory-stats                # Check system health
```

## Architecture

```
Claude Skills                 REST API                   Storage
─────────────────            ──────────────             ─────────────
/memory-restore   ──GET──>   /api/memory/context        ~/.claude/memory/*.yaml
/memory-observe   ──POST──>  /api/memory/observe    ──> Qdrant vector DB
/memory-recall    ──POST──>  /api/memory/recall     <── sentence-transformers
/memory-stats     ──GET──>   /api/memory/stats
```

## Behind the Scenes

Skills call memento-mcp REST API at `http://localhost:8000`

**Server Management:**
```bash
# Start server
docker compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker compose logs -f memento-mcp
```

## What Gets Saved Automatically

✅ **DO SAVE:**
- Architecture/tool decisions ("decided to use PostgreSQL")
- Bug fixes and gotchas discovered
- User preferences and requirements
- Project-specific constraints

❌ **DON'T SAVE:**
- Generic programming knowledge
- Temporary context ("working on file X")
- Speculative conclusions
- Information already in codebase/docs

## Global vs Local

- **Skills**: Installed globally (`~/.claude/skills/memory-*`)
- **Hook**: Global (`~/.claude/hooks.json`) for cross-project use
- **Server**: Project-specific (requires memento-mcp running)
- **Storage**: User-level (`~/.claude/memory/`)

## Troubleshooting

**Memory not restoring?**
- Check server: `docker compose ps`
- Verify hook: `cat ~/.claude/hooks.json`
- Test API: `curl http://localhost:8000/health`

**Skills not appearing?**
- Restart Claude Code session
- Verify: `ls ~/.claude/skills/memory-*`

**Observations not saving?**
- Check disk space: `df -h ~/.claude/memory`
- Verify Qdrant: `docker compose logs qdrant`
