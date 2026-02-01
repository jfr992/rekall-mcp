# Examples

Real-world usage scenarios to get you started.

---

## Basic Memory Operations

### Saving Memories

```python
from memory import MemoryManager

memory = MemoryManager()

# Save a decision
memory.save(
    "We chose Python because of the ML ecosystem",
    type="decision",
    project="my-app"
)

# Save a preference
memory.save(
    "User prefers concise explanations with diagrams",
    type="preference"
)

# Save a learning
memory.save(
    "JWT validation fails silently with trailing slash in issuer URL",
    type="learning",
    project="auth-service"
)

# Save a note
memory.save(
    "Need to review the caching strategy next week",
    type="note"
)
```

### Recalling Memories

```python
# Simple recall
results = memory.recall("what technology decisions did we make?")
for r in results:
    print(f"[{r['score']:.2f}] {r['content']}")

# Filter by project
results = memory.recall("architecture", project="my-app")

# Filter by type
results = memory.recall("user preferences", type="preference")

# Limit results
results = memory.recall("recent work", limit=3)
```

### Project Context

```python
# Get all context for a project
context = memory.get_project_context("my-app")
print(context)

# Output:
# # Project Context: my-app
#
# ## [2026-02-01] decision
# We chose Python because of the ML ecosystem
#
# ## [2026-01-30] learning
# The cache invalidation was causing the bug
```

---

## CLI Usage

### Save from Command Line

```bash
# Save a decision
python -m memory.cli save "Decided to use PostgreSQL for persistence" \
    --type decision \
    --project backend-api

# Save a preference
python -m memory.cli save "User likes bullet points" --type preference

# Save a learning
python -m memory.cli save "Batch processing is 3x faster" --type learning
```

### Recall from Command Line

```bash
# Simple recall
python -m memory.cli recall "database choices"

# With project filter
python -m memory.cli recall "architecture" --project my-app

# Limit results
python -m memory.cli recall "recent decisions" --limit 3

# Last 7 days only
python -m memory.cli recall "what did we do" --days 7
```

### Check Stats

```bash
python -m memory.cli stats

# Output:
# 📊 Memory System Stats
# ────────────────────────────────────
# Total memories:  42
# Memory files:    8
# Storage:         /Users/you/.claude/memory
#
# By type:
#   decision: 15
#   note: 12
#   learning: 10
#   preference: 5
```

---

## End of Session Summary

Save a summary at the end of each work session:

```python
memory.save_session_summary(
    tasks_completed=[
        "Implemented user authentication",
        "Fixed the caching bug",
        "Added unit tests for auth module"
    ],
    decisions_made=[
        "Use JWT for session tokens",
        "Store refresh tokens in Redis"
    ],
    learnings=[
        "Redis connection pooling improves performance by 40%"
    ],
    preferences=[
        "User prefers detailed error messages in dev mode"
    ],
    project="auth-service"
)
```

Or from CLI:

```bash
python -m memory.cli end-session \
    --tasks "Built API, Fixed bug" \
    --decisions "Use Redis for caching" \
    --learnings "Batch is faster" \
    --project my-app
```

---

## Observability

### Check Telemetry

```python
from core import Telemetry

# After some operations
telemetry = Telemetry.get()

# Human-readable summary
print(telemetry.summary())

# Detailed metrics (OTEL-compatible)
metrics = telemetry.get_metrics()
print(f"Total operations: {sum(m['count'] for m in metrics['operations'].values())}")
```

### Monitor Performance

```python
from core import Telemetry

telemetry = Telemetry.get()

# Check for slow operations
for name, op in telemetry.get_metrics()["operations"].items():
    if op["p95_ms"] > 100:
        print(f"⚠️  {name} is slow: p95={op['p95_ms']}ms")

# Check for errors
for name, op in telemetry.get_metrics()["operations"].items():
    if op["errors"] > 0:
        print(f"❌ {name} has errors: {op['errors']}")
```

---

## Integration with AI Assistants

### Claude Code Hook (Future)

```bash
# ~/.claude/hooks/session_end.sh
#!/bin/bash

# Auto-save session summary when Claude Code session ends
python -m memory.cli end-session \
    --tasks "$CLAUDE_SESSION_TASKS" \
    --project "$(basename $PWD)"
```

### Manual Integration

```python
# At the start of a session
context = memory.get_project_context("my-project")
print(f"Previous context:\n{context}")

# During the session - save important things
memory.save("Discovered a race condition in the queue processor", type="learning")

# At the end of the session
memory.save_session_summary(
    tasks_completed=["Fixed race condition", "Added tests"],
    project="my-project"
)
```

---

## Security Example

Credentials are automatically removed:

```python
# Input with secrets
memory.save("""
Configuration:
  api_key: sk-abc123def456
  password: mysecretpassword
  token: ghp_1234567890abcdef
""", type="note")

# What gets stored:
# Configuration:
#   api_key: [REDACTED]
#   password: [REDACTED]
#   token: [REDACTED]
```

---

## Cleanup

### Clear a Project

```bash
# With confirmation
python -m memory.cli clear old-project

# Skip confirmation
python -m memory.cli clear old-project --yes
```

### Reset Everything

```bash
# Delete all memory files
rm -rf ~/.claude/memory/*

# Optionally restart Qdrant to clear vectors
docker compose restart qdrant
```
