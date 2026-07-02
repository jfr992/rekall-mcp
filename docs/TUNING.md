# Tuning Claude's Memory Behavior

Control what Claude remembers, how it recalls, and how the knowledge graph evolves.

---

See `docs/CLAUDE_MEMORY_SETTINGS.md` for the canonical policy reference (project scoping, endpoint defaults, graph internals, troubleshooting).

---

## Quick Setup

Add to `~/.claude/CLAUDE.md`:

```markdown
## Memory System

At session start:
1. Call `get_hierarchical_context()` for topic-grouped context
2. Fall back to `get_cached_context()` if hierarchy unavailable

During work:
- Call `observe(summary)` after completing tasks
- Auto-classifies type AND auto-links to knowledge graph

Maintenance:
- If graph has 0 edges: `rebuild_knowledge_graph()`
- To find duplicates: `consolidate_memories()`
```

---

## What to Save vs Skip

### Save (Worth Remembering)

| Category | Examples |
|----------|----------|
| **Decisions** | "Use PostgreSQL", "Serve MCP at root /" |
| **Patterns discovered** | "This codebase uses factory pattern for X" |
| **Bug fixes + root cause** | "Fixed by adding lifespan to session_manager" |
| **User preferences** | "Prefers Terraform over CloudFormation" |
| **Links shared** | URLs to docs, references, tools |
| **Code snippets** | Reusable patterns, configurations |
| **Learnings from failures** | "streamable_http_app() doesn't accept path param" |

### Skip (Not Worth Remembering)

| Category | Examples |
|----------|----------|
| **Simple Q&A** | "What is this?", "What does this script do?" |
| **Exploratory reads** | Reading code to understand it |
| **Temporary debugging** | Adding logs, checking values |
| **Routine commands** | `git status`, `docker ps` |
| **Work in progress** | Incomplete attempts, still iterating |

---

## Customizing Save Behavior

### Conservative (Default Recommendation)

```markdown
## Memory Preferences

Save to memory:
- Architectural decisions
- Patterns and interesting discoveries
- Bug fixes with learnings
- Links and snippets I share

Do NOT save:
- Simple questions/explanations
- Routine work
- Exploratory reads
```

### Aggressive (Capture Everything)

```markdown
## Memory Preferences

Save frequently:
- Every decision, even small ones
- All debugging sessions
- File locations discussed
- Tool preferences mentioned
```

### Manual Only

```markdown
## Memory Preferences

Only call observe() when I explicitly say:
- "Save this"
- "Remember this"
- "Update memory"
```

---

## Memory Types and Importance

| Type | Use For | AI Behavior | Graph Weight |
|------|---------|-------------|--------------|
| `requirement` | Hard constraints | **Must** follow | 1.0 |
| `decision` | Choices made | Reference, can revisit | 0.85 |
| `preference` | User likes/dislikes | Suggest, offer alternatives | 0.75 |
| `learning` | Bug fixes, discoveries | Apply to similar cases | 0.65 |
| `fact` | Project context | Background info | 0.55 |
| `note` | General info | Low-priority context | 0.35 |

Higher-weight memories rank higher in recall and decay more slowly.

---

## Tuning the Knowledge Graph

### Auto-Linking Rules

On every `save()` / `observe()`, the auto-linker searches for similar memories and classifies relationships:

| Rule | Condition | Effect |
|------|-----------|--------|
| Supersedes | similarity > 0.9 + same type | New replaces old (old importance halved) |
| Contradicts | Asymmetric negation + overlap >= 2 + proximity | Both flagged as conflicting |
| Led_to | New learning + existing decision | Causation edge |
| Depends_on | New decision + existing requirement | Dependency edge |
| Related_to | similarity > 0.5 + same project | Default association |

### Importance Decay

Memories that aren't accessed for 7+ days gradually lose importance:

```
importance *= 0.98^(days_idle - 7)
```

Floor: 0.1 (never fully forgotten). Access via recall resets the timer.

### Recall Scoring

The composite score balances five signals:

| Signal | Weight | What it measures |
|--------|--------|------------------|
| Vector similarity | 40% | Textual relevance to query |
| Importance | 20% | Type weight + graph centrality |
| Graph proximity | 15% | Whether found via graph expansion |
| Tier | 15% | Lifecycle tier (identity > semantic > episodic > working) |
| Recency | 10% | How recent the memory is |

### Rebuilding the Graph

Run after upgrades, bulk imports, or when graph stats show 0 edges:

```bash
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

Or via MCP tool: `rebuild_knowledge_graph()`

### Cleaning Up Duplicates

Find superseded and contradictory pairs:

```bash
curl http://localhost:8000/api/memory/consolidate
```

Bidirectional pairs (A supersedes B and B supersedes A) are deduplicated automatically. Review the output, remove stale entries from `~/.claude/memory/<project>/*.yaml`, sync, then rebuild.

---

## Verifying Memory

### Check What's Saved

```bash
# Today's memories (nested per project since v1.5)
cat ~/.claude/memory/<project>/$(date +%Y-%m-%d).yaml
# or across all projects:
find ~/.claude/memory -name "$(date +%Y-%m-%d).yaml"

# All memories
ls ~/.claude/memory/

# Search with graph enhancement
curl -X POST http://localhost:8000/api/memory/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "database decisions"}'
```

### Memory Stats

```bash
curl http://localhost:8000/api/memory/stats
```

Returns total memories, by-type breakdown, and a `knowledge_graph` object:

```json
{
  "knowledge_graph": {
    "nodes": 133,
    "edges": 286,
    "relations": {
      "related_to": 229,
      "contradicts": 28,
      "led_to": 21,
      "depends_on": 8
    }
  }
}
```

### Knowledge Graph Health

```bash
curl http://localhost:8000/api/memory/stats | jq '.knowledge_graph'
```

If edges = 0, rebuild: `curl -X POST http://localhost:8000/api/memory/graph/rebuild`

---

## Editing Memories

Memories are plain YAML. Edit directly:

```bash
code ~/.claude/memory/<project>/$(date +%Y-%m-%d).yaml
```

After editing YAML files, rebuild the graph to update relationships:

```bash
# Re-index into Qdrant
cd src && python -m memory.migrate

# Rebuild graph
curl -X POST http://localhost:8000/api/memory/graph/rebuild
```

---

## Clearing Memory

```bash
# Backup first
cp -r ~/.claude/memory ~/memory-backup-$(date +%Y%m%d)

# Clear specific day
rm ~/.claude/memory/2026-02-02.yaml

# Clear all
rm -rf ~/.claude/memory/*
rm -rf ~/.claude/qdrant/*
docker compose restart
```
