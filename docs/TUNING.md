# Tuning Claude's Memory Behavior

Control what Claude remembers and when.

---

Use `docs/CLAUDE_MEMORY_SETTINGS.md` as the canonical policy reference for:
- what `observe` should run automatically,
- project scoping and endpoint defaults,
- dashboard defaults (`/api/memory/graph`) and CLAUDE.md fallback values,
- and the troubleshooting order when memory behavior degrades.

---

## Quick Setup

Add to `~/.claude/CLAUDE.md`:

```markdown
## Memory System

At the START of each session:
1. Call `get_cached_context()` to restore memory from previous sessions
2. Use the context to understand user preferences and project history

During work:
- Call `observe(summary)` after completing tasks to save what you learned
- The system automatically classifies memory type (decision/preference/learning/etc)
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

## Customizing Behavior

### Conservative (Default Recommendation)

Only save significant discoveries. Add to CLAUDE.md:

```markdown
## Memory Preferences

Save to memory:
- Architectural decisions
- Patterns and interesting discoveries
- Links and snippets I share
- Bug fixes with learnings

Do NOT save:
- Simple questions/explanations
- Routine work
- Exploratory reads
```

### Aggressive (Capture Everything)

Save more context. Add to CLAUDE.md:

```markdown
## Memory Preferences

Save frequently:
- Every decision, even small ones
- All debugging sessions
- File locations discussed
- Tool preferences mentioned
```

### Manual Only

Only save when explicitly requested:

```markdown
## Memory Preferences

Only call observe() when I explicitly say:
- "Save this"
- "Remember this"
- "Update memory"
```

---

## Memory Types

| Type | Use For | AI Behavior |
|------|---------|-------------|
| `requirement` | Hard constraints | **Must** follow |
| `decision` | Choices made | Reference, can revisit |
| `preference` | User likes/dislikes | Suggest, offer alternatives |
| `fact` | Project context | Background info |
| `learning` | Bug fixes, discoveries | Apply to similar cases |
| `note` | General info | Low-priority context |

---

## Explicit Commands

Tell Claude directly:

```
"Remember that I prefer TypeScript"
"Save this: we're using AWS Lambda for auth"
"Update memory with today's architecture decision"
"Don't save this - just exploring"
```

---

## Verifying Memory

### Check What's Saved

```bash
# Today's memories
cat ~/.claude/memory/$(date +%Y-%m-%d).yaml

# All memories
ls ~/.claude/memory/

# Search
curl -X POST http://localhost:8000/api/memory/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "database decisions"}'
```

### Memory Stats

```bash
curl http://localhost:8000/api/memory/stats
```

---

## Editing Memories

Memories are plain YAML - edit directly:

```bash
# Open today's file
code ~/.claude/memory/$(date +%Y-%m-%d).yaml
```

Format:
```yaml
date: "2026-02-02"
decisions:
  - id: 2026-02-02_decision_1234
    content: "Use PostgreSQL for JSON support"
    project: my-app
    timestamp: "2026-02-02T10:30:00"
preferences:
  - id: 2026-02-02_preference_5678
    content: "User prefers concise responses"
    project: general
    timestamp: "2026-02-02T11:00:00"
```

After editing, memories are automatically re-indexed on next search.

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
