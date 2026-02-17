# Memory Plugin for Claude Code

## Overview

The Memory Plugin transforms memento-mcp from a passive memory store into an intelligent, auto-triggering system that seamlessly preserves context across Claude Code sessions. Instead of manually calling MCP tools, the plugin uses **Claude Code skills** that automatically detect when to restore, save, or search memories.

Before wiring this in, review `docs/CLAUDE_MEMORY_SETTINGS.md` for the canonical policy and tuning knobs (project scoping, dashboard defaults, and recovery playbook).

## What Problem Does It Solve?

**Before**: Manual memory management
- Manually call `get_cached_context()` at session start
- Remember to call `observe()` after decisions
- Explicitly invoke `recall_memories()` when stuck
- Context lost between sessions

**After**: Automatic, invisible memory
- New session? Context auto-restored silently
- Made a decision? Auto-saved when detected
- Need past context? Auto-recalled when you ask questions
- Seamless experience across sessions

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Claude Code Session                      │
│                                                                │
│  ┌─────────────┐         ┌──────────────┐                    │
│  │   Hooks     │────────>│    Skills    │                    │
│  │  Auto-fire  │         │  /memory-*   │                    │
│  └─────────────┘         └───────┬──────┘                    │
│                                   │                            │
└───────────────────────────────────┼────────────────────────────┘
                                    │ HTTP REST API
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                   Memento-MCP Server (:8000)                  │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   /observe   │  │   /recall    │  │  /context    │       │
│  │ Auto-classify│  │   Semantic   │  │  Formatted   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │                │
└─────────┼──────────────────┼──────────────────┼────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────┐    ┌──────────────────────────┐
│  YAML Storage   │    │   Qdrant Vector Store    │
│  ~/.claude/     │    │  Semantic Search Index   │
│  memory/*.yaml  │    │  sentence-transformers   │
└─────────────────┘    └──────────────────────────┘
```

## Components

### 1. Skills (Global, ~/.claude/skills/)

Four specialized skills that interact with the REST API:

#### `/memory-restore` - Session Start Auto-Load
**Purpose**: Restore cached memories at session start
**Trigger**: New session, resume after compaction, explicit invocation
**Action**:
- Fetches `GET /api/memory/context`
- Silently injects memories into working context
- Shows stats summary

**Implementation**:
```yaml
---
name: memory-restore
user-invocable: true
---
!`curl -s http://localhost:8000/api/memory/context | jq -r '.context'`
```

#### `/memory-observe` - Auto-Save Significant Events
**Purpose**: Record architecture decisions, bug fixes, preferences
**Trigger**: Decision language ("decided to use", "chose", "going with")
**Action**:
- Posts to `/api/memory/observe` with auto-classification
- Saves to YAML + embeds in Qdrant
- Returns confirmation

**Implementation**:
```yaml
---
name: memory-observe
allowed-tools: Bash(curl *)
---
!`echo '{"summary": "$ARGUMENTS", "type": "auto"}' |
  curl -s http://localhost:8000/api/memory/observe -X POST -d @-`
```

#### `/memory-recall` - Intelligent Search
**Purpose**: Find relevant past context using semantic search
**Trigger**: Questions about past work, stuck situations
**Action**:
- Posts to `/api/memory/recall` with query
- Returns top 5 matches with scores
- Synthesizes results into response

**Implementation**:
```yaml
---
name: memory-recall
context: fork
agent: Explore
---
!`echo '{"query": "$ARGUMENTS", "limit": 5}' |
  curl -s http://localhost:8000/api/memory/recall -X POST -d @-`
```

#### `/memory-stats` - Health Check
**Purpose**: Diagnostics and health monitoring
**Trigger**: User requests stats, troubleshooting
**Action**: Fetches `GET /api/memory/stats`

### 2. Hooks (Global, ~/.claude/hooks.json)

Auto-triggers memory restoration on every new message:

```json
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
```

**How it works**:
- Fires on every user message (new session, resume, or post-compaction)
- Instructs Claude to check if restoration is needed
- Silently loads context without user-facing output

### 3. REST API (Memento-MCP Server)

#### `GET /api/memory/context`
Returns formatted project context for restoration.

**Query Params**: `?project=<name>` (optional, defaults to "general")
**Response**:
```json
{
  "project": "memento-mcp",
  "context": "# Project Context: memento-mcp\n\n## [2026-02-02] fact\n..."
}
```

#### `POST /api/memory/observe`
Auto-classifies and saves observations.

**Body**:
```json
{
  "summary": "Decided to use PostgreSQL for reliability",
  "type": "auto"
}
```

**Response**:
```json
{
  "memory_id": "2026-02-03_decision_a4044b26",
  "status": "observed",
  "classified_type": "decision"
}
```

**Auto-classification**: Uses embedding similarity to classify as:
- `decision` - Architecture/tech choices
- `learning` - Bug fixes, gotchas
- `preference` - User working style
- `requirement` - Hard constraints
- `fact` - Contextual info

#### `POST /api/memory/recall`
Semantic search across memories.

**Body**:
```json
{
  "query": "database choice",
  "limit": 5
}
```

**Response**:
```json
{
  "query": "database choice",
  "count": 3,
  "memories": [
    {
      "score": 0.85,
      "content": "Decided to use PostgreSQL for reliability",
      "type": "decision",
      "date": "2026-02-03",
      "memory_id": "..."
    }
  ]
}
```

#### `GET /api/memory/stats`
System health and statistics.

**Response**:
```json
{
  "total_memories": 1587,
  "memory_files": 2,
  "by_type": {
    "decision": 3,
    "learning": 11,
    "preference": 8
  }
}
```

## How Auto-Triggering Works

### Session Start Flow

1. User starts new Claude Code session
2. User sends first message
3. Hook fires: "If new session, invoke /memory-restore"
4. Claude detects new session, invokes skill
5. Skill executes: `curl http://localhost:8000/api/memory/context`
6. Memories loaded silently into context
7. Claude responds with full context awareness

### Auto-Observe Flow

1. User: "I've decided to use PostgreSQL for this project"
2. Claude detects decision language matching skill description
3. Claude invokes: `/memory-observe PostgreSQL chosen for reliability`
4. Skill posts to `/api/memory/observe` with auto-classification
5. Server embeds text, classifies as "decision", saves to YAML + Qdrant
6. Confirmation returned to Claude
7. Claude acknowledges decision (doesn't mention memory save)

### Auto-Recall Flow

1. User: "What database did we choose?"
2. Claude detects question about past context
3. Claude invokes: `/memory-recall database choice`
4. Skill queries semantic search
5. Returns: `[decision] Decided to use PostgreSQL (score: 0.85)`
6. Claude synthesizes and answers: "We chose PostgreSQL for reliability"

## Storage Layer

### YAML Files (~/.claude/memory/)

Human-readable, git-friendly storage:

```yaml
# 2026-02-03.yaml
- id: 2026-02-03_decision_a4044b26
  timestamp: '2026-02-03T02:07:15'
  type: decision
  project: memento-mcp
  content: Implemented memory plugin with 4 auto-triggering skills

- id: 2026-02-03_learning_b3921c45
  timestamp: '2026-02-03T01:15:32'
  type: learning
  project: memento-mcp
  content: Fixed context endpoint validation error by defaulting to 'general' project
```

### Qdrant Vector Store

Enables semantic search:
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
- **Index**: ~1500 memories indexed in <100ms
- **Search**: Cosine similarity with configurable threshold
- **Filters**: By type, project, date range

## Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| Context Restoration | <50ms | Simple file read |
| Semantic Search | 50-80ms | Local embedder, no API calls |
| Observe (Save) | 80-120ms | Embedding + dual write (YAML + Qdrant) |
| Stats | <20ms | In-memory aggregation |

**Total overhead per session**: ~100ms (one-time context load)

## What Gets Saved Automatically

### ✅ DO SAVE (High Value)

- **Decisions**: "Decided to use React instead of Vue for better TypeScript support"
- **Gotchas**: "Fixed bug where JWT validation failed with trailing slashes"
- **Preferences**: "User prefers Terraform over CloudFormation"
- **Requirements**: "API rate limit is 100 requests/hour"
- **Constraints**: "Must support offline mode for field technicians"

### ❌ DON'T SAVE (Low Value)

- Generic programming knowledge: "Python uses indentation for blocks"
- Temporary context: "Currently working on file X"
- Speculative ideas: "Maybe we could try GraphQL?"
- Redundant info: "The config file is in ./config/" (already in codebase)
- Obvious facts: "React is a JavaScript library"

## Advanced Features

### Project Isolation

Memories are tagged by project for context separation:

```bash
# Get memento-mcp specific context
curl 'http://localhost:8000/api/memory/context?project=memento-mcp'

# Get general memories (cross-project)
curl 'http://localhost:8000/api/memory/context?project=general'
```

### Memory Types and Usage

| Type | Use Case | Example |
|------|----------|---------|
| `decision` | Architecture choices | "Using gRPC for microservice communication" |
| `learning` | Bug fixes, discoveries | "CORS errors need `credentials: true` flag" |
| `preference` | User working style | "Prefers functional over class components" |
| `requirement` | Hard constraints | "Must support IE11 for enterprise clients" |
| `fact` | Contextual info | "Staging server is at staging.example.com" |
| `note` | General observations | "Team meeting notes from 2026-02-01" |

### Filtered Recall

Search with filters:

```bash
# Only decisions from last 7 days
curl -X POST http://localhost:8000/api/memory/recall \
  -d '{"query": "architecture", "type": "decision", "days": 7}'

# Project-specific search
curl -X POST http://localhost:8000/api/memory/recall \
  -d '{"query": "bug fixes", "project": "memento-mcp"}'
```

### Score Thresholds

Semantic search returns similarity scores (0.0 - 1.0):

- **0.8+**: Near-exact match
- **0.6-0.8**: Strong semantic similarity
- **0.4-0.6**: Moderate relevance
- **<0.4**: Weak match (usually filtered out)

Skills default to 0.6 threshold for quality results.

## Graceful Degradation

If the memento-mcp server is down:

```bash
/memory-recall architecture
# Output: "No results found" (not a crash)

/memory-stats
# Output: "Server not responding
#          Troubleshooting:
#          - Check: docker compose ps
#          - Start: docker compose up -d"
```

Skills fail silently and provide actionable diagnostics.

## Comparison: Manual vs Plugin

### Manual (MCP Tools Only)

```python
# User must remember to:
1. Call get_cached_context() at session start
2. Call observe() after every decision
3. Call recall_memories() when stuck
4. Understand when each tool is appropriate
```

**Cognitive load**: HIGH
**Adoption**: LOW (easy to forget)
**UX**: Mechanical, interrupts flow

### Plugin (Skills + Hooks)

```python
# Automatic:
1. Context restored on session start (hook)
2. Observations triggered by decision language (skill)
3. Recall triggered by questions (skill)
4. No user action required
```

**Cognitive load**: ZERO
**Adoption**: AUTOMATIC
**UX**: Invisible, feels like Claude "remembers"

## Extensibility

### Adding Custom Skills

Create new memory-related skills:

```bash
mkdir -p ~/.claude/skills/memory-export
cat > ~/.claude/skills/memory-export/SKILL.md << 'EOF'
---
name: memory-export
description: Export all memories to JSON for backup
user-invocable: true
---

!`curl -s http://localhost:8000/api/memory/stats | jq .`
EOF
```

### Customizing Auto-Triggers

Edit skill descriptions to change trigger sensitivity:

```yaml
# More aggressive (triggers more often)
description: Record any technical choice. Auto-triggers on words like "using", "with", "chose", "picked".

# More conservative (only major decisions)
description: Record major architecture decisions only. Auto-triggers on "decided to", "going with".
```

### Adding New API Endpoints

Extend the REST API in `src/server.py`:

```python
@mcp.custom_route("/api/memory/export", methods=["GET"])
async def api_export_memories(request):
    manager = _get_memory_manager()
    all_memories = manager.get_all_memories()
    return JSONResponse({"memories": all_memories})
```

Then create a skill that calls it.

## Security Considerations

### Local-First
- All data stays on your machine
- No external API calls
- YAML files are human-auditable

### Sensitive Data
- Skills have `allowed-tools: Bash(curl *)` restriction
- Can only call localhost:8000
- No network access beyond memento-mcp server

### Git Safety
- Add `~/.claude/memory/` to global gitignore
- Memories may contain API keys or credentials
- Review before committing YAML files

## Troubleshooting

### Skills Not Appearing

```bash
# Check skills directory
ls ~/.claude/skills/memory-*/SKILL.md

# Restart Claude Code session
# Skills are loaded at startup
```

### Auto-Restore Not Working

```bash
# Verify hook exists
cat ~/.claude/hooks.json

# Check if hook is firing (look for invocation in conversation)

# Test manual invocation
/memory-restore
```

### Memories Not Saving

```bash
# Check server health
curl http://localhost:8000/health

# Check disk space
df -h ~/.claude/memory

# Check Qdrant logs
docker compose logs qdrant
```

### Poor Search Results

```bash
# Lower score threshold in skill
# Edit: ~/.claude/skills/memory-recall/SKILL.md
# Change: "score_threshold": 0.6 → "score_threshold": 0.4

# Add more context to query
/memory-recall "database choice for user authentication system"
# vs
/memory-recall "database"
```

## Performance Tuning

### Reduce Context Load Time

```yaml
# In memory-restore skill, limit results
!`curl -s 'http://localhost:8000/api/memory/context?limit=10'`
```

### Batch Operations

Instead of individual observations:

```bash
# Save multiple at once via API
curl -X POST http://localhost:8000/api/memory/save \
  -d '{"content": "Batch memory 1", "type": "note"}'
```

### Qdrant Optimization

For >10k memories, configure Qdrant indexing:

```yaml
# docker-compose.yml
qdrant:
  environment:
    - QDRANT__STORAGE__OPTIMIZERS__INDEXING_THRESHOLD=5000
```

## Roadmap

Potential future enhancements:

- [ ] **Smart project detection**: Auto-tag memories with current git repo
- [ ] **Confidence scores**: Show when Claude is uncertain about triggers
- [ ] **Memory deduplication**: Detect and merge similar observations
- [ ] **Export/import**: Backup and restore memory sets
- [ ] **Analytics**: Track memory usage patterns over time
- [ ] **Multi-agent**: Share memories across different AI assistants

## See Also

- [Setup Guide](./SETUP.md) - Detailed setup, embedding providers, migration
- [Tuning Guide](./TUNING.md) - Customize what Claude remembers
- [Architecture](./ARCHITECTURE.md) - Technical design
