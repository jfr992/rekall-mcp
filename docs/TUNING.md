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

## Hybrid Recall Reindex

Run this only after backing up the memory YAML directory and Qdrant volume you
actually use. The bundled Codex install uses `~/.Codex`; Claude Code installs
often use `~/.claude`.

```bash
# Codex-local default stack
tar czf ~/backups/pre-hybrid-memory.tar.gz -C ~ .Codex/memory
tar czf ~/backups/pre-hybrid-qdrant.tar.gz -C ~ .Codex/qdrant
uv run python -m memory.migrate_hybrid --memory-dir ~/.Codex/memory --dry-run
uv run python -m memory.migrate_hybrid --memory-dir ~/.Codex/memory

# Claude Code-local stack
tar czf ~/backups/pre-hybrid-claude-memory.tar.gz -C ~ .claude/memory
tar czf ~/backups/pre-hybrid-claude-qdrant.tar.gz -C ~ .claude/qdrant
uv run python -m memory.migrate_hybrid --memory-dir ~/.claude/memory --dry-run
uv run python -m memory.migrate_hybrid --memory-dir ~/.claude/memory
```

The migration reads nested project YAML, backfills missing `entities`,
`embedding_text`, and lifecycle fields into YAML, builds `_bm25_vocab.json`, and
reindexes Qdrant (dense vectors from raw `content` — repr v2 — and BM25 sparse
from `embedding_text`). Dense vectors remain required; BM25 is an additional
exact-cue path for project names, file paths, flags, ticket IDs, and tool names.

## Nervous-System Recall Surfaces

- Use `project_capsule(project)` or `agent_startup(agent="claude-code")` once at session start for broad familiarity.
- Use `recall_memories(query)` only after the prompt supplies a concrete topic.
- Use `recall_across_projects(query, current_project)` when a lesson from another repo may transfer.
- Use `reflex_recall(text, project)` before risky infrastructure, memory-data, hook, or deployment work.
- Use `memory_doctor(project)` before trusting recall completeness after migrations, compaction, or Qdrant repairs.

Do not turn every turn into proactive recall. The nervous-system model is familiarity first, targeted recall second, save only durable lessons third.

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
rm ~/.claude/memory/<project>/2026-02-02.yaml

# Clear all
rm -rf ~/.claude/memory/*
rm -rf ~/.claude/qdrant/*
docker compose restart
```

## Resolving contradictions

When the cockpit's memory inspector shows *"This memory has contradicting relationships"*, the knowledge graph holds a `contradicts` edge between this memory and another — two memories make claims that can't both be current. Contradictions are **flagged, never auto-deleted**: the system won't guess which claim is true, but it does serve its best guess at recall (newest wins; the older memory's content is stubbed as outdated).

Four ways to resolve, in order of frequency:

1. **Do nothing** — if the newest memory is correct, recall already serves the right answer. The badge is informational.
2. **Re-state the truth** — tell your agent the correct fact ("the retry limit is 3 — remember that"). The fresh save becomes newest and wins all future recalls; history is preserved.
3. **Delete the wrong one** — when the *older* memory is correct, recency is lying. `curl -X DELETE http://localhost:8000/api/memory/<memory_id>` (id shown in the inspector) removes it from YAML, vectors, and graph.
4. **Superseded pairs** (clear replacement rather than disagreement) are retired automatically by the gated prune — no action needed.

Review all pairs at once: `curl http://localhost:8000/api/memory/consolidate` or the Hygiene page.

Bulk repair of machine-made conflict flags: `QDRANT_URL=http://localhost:6333 uv run python scripts/repair_contradicts.py` re-judges every unrefined `contradicts` edge (LLM per pair when `ANTHROPIC_API_KEY` is set, negation heuristic otherwise) and downgrades the unsupported ones to `related_to` — dry-run by default, `--apply` to write.

## Inspector warnings

`missing provenance` on a memory means it was saved before provenance tracking existed (2026-07-18) — its origin (agent, source tool, working directory) was never recorded and is not fabricated retroactively. Memories saved after that date carry provenance automatically; the warning marks legacy data, not a fault.

## BM25 vocab lifecycle (hybrid search)

Hybrid search fuses dense vectors with a BM25 sparse index whose IDF vocabulary is built at fit time. Token IDs are assigned by insertion order, which means **a refit reassigns every ID — the vocab and all stored sparse vectors must change together, in one transaction**. That transaction is `POST /api/memory/resparse`: it refits a fresh encoder on the full corpus, rewrites every point's sparse vector (dense untouched), verifies the count, then atomically publishes the vocab and swaps the live encoder. A sentinel guards the whole run — if it's interrupted, search degrades to dense-only (never wrong matches) and the doctor reports `resparse_incomplete`; the fix is always to rerun resparse, never to delete the marker.

Drift is surfaced, not hidden: the doctor's `bm25` block reports vocab age, size, a rolling OOV-rate window over recent saves, and an `oov_identifier_seen` flag that trips the moment a hyphen/underscore-shaped identifier (an instance ID, an error class, a pack name) is saved that the vocab can't encode. Verdict `stale` means exact-token recall is silently degraded for anything saved since the last fit — run resparse. There is deliberately no auto-trigger yet; the manual endpoint plus a loud doctor covers the current save cadence.
