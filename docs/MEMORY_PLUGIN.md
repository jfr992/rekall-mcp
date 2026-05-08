# Memory Plugin for Claude Code

## Overview

The Memory Plugin transforms memento-mcp from a passive memory store into an intelligent, auto-triggering system with a knowledge graph layer. Instead of manually calling MCP tools, the plugin uses **Claude Code skills** and **hooks** that automatically restore, save, and search memories.

See `docs/CLAUDE_MEMORY_SETTINGS.md` for the canonical policy and tuning knobs.

## What Problem Does It Solve?

**Before**: Manual memory management
- Manually call `get_cached_context()` at session start
- Remember to call `observe()` after decisions
- Explicitly invoke `recall_memories()` when stuck
- No relationships between memories

**After**: Automatic, graph-enhanced memory
- Context auto-restored (hierarchical + flat) at session start
- Auto-saved when decisions detected
- Graph-enhanced recall surfaces structurally related memories
- Knowledge graph connects decisions to learnings to requirements

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Claude Code Session                     │
│                                                              │
│  ┌─────────────┐         ┌──────────────┐                   │
│  │   Hooks     │────────>│    Skills    │                   │
│  │  Auto-fire  │         │  /memory-*   │                   │
│  └─────────────┘         └───────┬──────┘                   │
│                                  │                           │
└──────────────────────────────────┼───────────────────────────┘
                                   │ HTTP REST API
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                  Memento-MCP Server (:8000)                   │
│                                                              │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │  /observe  │ │  /recall   │ │  /context   │ │  /graph  │ │
│  │ Auto-class │ │ Graph-     │ │ Flat +      │ │ Rebuild  │ │
│  │ + autolink │ │ enhanced   │ │ Hierarchical│ │ Visualize│ │
│  └─────┬──────┘ └─────┬─────┘ └─────┬───────┘ └────┬─────┘ │
│        │              │              │               │       │
└────────┼──────────────┼──────────────┼───────────────┼───────┘
         │              │              │               │
         ▼              ▼              ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌──────────────────┐
│  YAML Storage   │ │  Qdrant Vector  │ │ Knowledge Graph  │
│  ~/.claude/     │ │  Store          │ │ _graph.json      │
│  memory/*.yaml  │ │  384-dim cosine │ │ networkx DiGraph  │
└─────────────────┘ └─────────────────┘ └──────────────────┘
```

## Components

### 1. Skills (Global, ~/.claude/skills/)

Seven specialized skills that interact with the REST API:

#### `/memory-restore` - Session Start Auto-Load
**Purpose**: Restore context at session start using hierarchical + flat context
**Trigger**: New session, resume after compaction, explicit invocation
**Action**:
- Fetches `GET /api/memory/context/hierarchy` (primary)
- Falls back to `GET /api/memory/context` (flat)
- Silently injects memories into working context

#### `/memory-observe` - Auto-Save Events
**Purpose**: Record architecture decisions, bug fixes, preferences
**Action**:
- Posts to `/api/memory/observe` with auto-classification
- Server auto-links to related memories in knowledge graph
- Returns confirmation with classified type

#### `/memory-recall` - Graph-Enhanced Search
**Purpose**: Find relevant past context using semantic search + graph traversal
**Action**:
- Posts to `/api/memory/recall` with query (default limit=8)
- Results include graph-expanded neighbors ranked by composite score
- Scoring: vector(50%) + importance(20%) + recency(15%) + proximity(15%)

#### `/memory-stats` - Health Check
**Purpose**: Diagnostics and health monitoring
**Action**: Fetches `GET /api/memory/stats` including knowledge graph node/edge counts

#### `/memory-rebuild` - Rebuild Knowledge Graph
**Purpose**: Create typed relationships between all existing memories
**Action**: Posts to `/api/memory/graph/rebuild`
**When**: After upgrades, corrupted graph, or 0 edges in stats

#### `/memory-consolidate` - Detect Duplicates
**Purpose**: Find superseded and contradictory memory pairs
**Action**: Fetches `GET /api/memory/consolidate`
**When**: After bulk imports, to clean up memory drift

#### `/memory-skills` - Show Extracted Skills
**Purpose**: Display capabilities learned from memory clusters
**Action**: Fetches `GET /api/memory/context/skills`
**When**: Understanding what knowledge is available

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

### 3. REST API

#### Core Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/memory/save` | POST | Save a memory |
| `/api/memory/recall` | POST | Graph-enhanced semantic search |
| `/api/memory/observe` | POST | Auto-classify and save |
| `/api/memory/stats` | GET | Statistics + graph metrics |
| `/api/memory/context` | GET | Flat project context |

#### Knowledge Graph Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/memory/graph` | GET | Graph visualization data (nodes + edges) |
| `/api/memory/graph/rebuild` | POST | Rebuild knowledge graph from all memories |
| `/api/memory/context/hierarchy` | GET | Topic-grouped hierarchical context |
| `/api/memory/context/proactive` | GET | Top signals + conflict detection |
| `/api/memory/context/skills` | GET | Inferred skills from memory clusters |
| `/api/memory/consolidate` | GET | Detect superseded/conflicting pairs |

#### API Details

**`POST /api/memory/recall`**
```json
{
  "query": "database choice",
  "limit": 5,
  "project": "my-app"
}
```
Response includes `score` (composite), `vector_score`, `content`, `type`, `date`, `memory_id`.

Graph-enhanced: seeds expanded via 1-hop traversal, re-ranked by composite score.

**`POST /api/memory/observe`**
```json
{
  "summary": "Decided to use PostgreSQL for reliability",
  "type": "auto"
}
```
Response: `memory_id`, `status`, `classified_type`. Auto-links to related memories in knowledge graph.

**`GET /api/memory/graph`**
Query params: `limit` (default 120), `neighbor_count` (default 5), `min_similarity` (default 0.35), `project`, `type`, `days`.

> **Note on `days` filtering**: The `date` field is stored as a `YYYY-MM-DD` string. Since Qdrant's `Range` filter requires numeric values, date filtering is applied post-retrieval in Python. Results are fetched first, then filtered by `date >= cutoff`. This is transparent to callers.

When knowledge graph has edges, returns real typed edges instead of cosine similarity.

**`POST /api/memory/graph/rebuild`**
Returns: `{status, nodes, edges, duration_ms}`.

## How Auto-Triggering Works

### Session Start Flow

1. User starts new Claude Code session
2. User sends first message
3. Hook fires: "If new session, invoke /memory-restore"
4. Claude detects new session, invokes skill
5. Skill fetches hierarchical context (topic-grouped tree)
6. Falls back to flat context if hierarchy unavailable
7. Memories loaded silently into context
8. Claude responds with full context awareness

### Auto-Observe Flow

1. User: "I've decided to use PostgreSQL for this project"
2. Claude detects decision language
3. Claude invokes: `/memory-observe PostgreSQL chosen for reliability`
4. Skill posts to `/api/memory/observe`
5. Server: embeds text, classifies as "decision", saves to YAML + Qdrant
6. Server: auto-links to related memories (requirements, past learnings)
7. Knowledge graph updated with typed edges
8. Claude acknowledges decision

### Graph-Enhanced Recall Flow

1. User: "What database did we choose?"
2. Claude invokes: `/memory-recall database choice`
3. Server: vector search finds seed results
4. Server: expands seeds via 1-hop graph traversal
5. Server: ranks by composite score (vector + importance + recency + proximity)
6. Returns: decision about PostgreSQL + related requirements and learnings
7. Claude synthesizes and answers

## Storage Layer

### YAML Files (~/.claude/memory/)

Human-readable, git-friendly:

```yaml
- id: 2026-02-23_decision_a4044b26
  timestamp: '2026-02-23T02:07:15'
  type: decision
  project: memento-mcp
  content: Implemented knowledge graph with typed relationships
```

### Qdrant Vector Store

- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
- **Search**: Cosine similarity with configurable threshold
- **Filters**: By type, project, date range

### Knowledge Graph (~/.claude/memory/_graph.json)

- **Backend**: networkx DiGraph
- **Nodes**: memory_id with importance score, access count, last accessed date
- **Edges**: typed (related_to, led_to, depends_on, contradicts, supersedes, part_of)
- **Persistence**: Atomic writes (tempfile + os.replace)

## Memory Types

| Type | Use Case | Importance Weight |
|------|----------|-------------------|
| `requirement` | Hard constraints | 1.0 |
| `decision` | Architecture choices | 0.85 |
| `preference` | User working style | 0.75 |
| `learning` | Bug fixes, discoveries | 0.65 |
| `fact` | Contextual info | 0.55 |
| `note` | General observations | 0.35 |
| `session` | Session summaries | 0.25 |

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

## Security

- **Local-first**: All data stays on your machine
- **No external API calls**: Embeddings run locally by default
- **Skills restricted**: `allowed-tools: Bash(curl *)` — can only call localhost
- **YAML auditable**: Human-readable, version-controllable
- **Credential sanitization**: API keys, tokens, passwords auto-redacted

## Troubleshooting

### Skills Not Appearing

```bash
ls ~/.claude/skills/memory-*/SKILL.md
# Restart Claude Code session (skills loaded at startup)
```

### Auto-Restore Not Working

```bash
cat ~/.claude/hooks.json   # Verify hook exists
/memory-restore            # Test manual invocation
```

### Knowledge Graph Empty

```bash
curl http://localhost:8000/api/memory/stats | jq '.knowledge_graph'
# If edges = 0:
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

### Duplicate Memories

```bash
curl http://localhost:8000/api/memory/consolidate | jq .
# Review superseded pairs, remove stale YAML entries, rebuild graph
```

### Poor Search Results

- Increase limit: `/memory-recall "database choice" --limit 10`
- Check if graph has edges (graph expansion improves recall significantly)
- Rebuild graph if stale: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`

## See Also

- [Setup Guide](./SETUP.md) - Installation and embedding providers
- [Tuning Guide](./TUNING.md) - Customize what Claude remembers
- [Architecture](./ARCHITECTURE.md) - Technical design and knowledge graph internals
- [Claude Memory Settings](./CLAUDE_MEMORY_SETTINGS.md) - Policy reference and tuning knobs
