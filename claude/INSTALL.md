# Claude Code Bundle for Memento

This folder is a **portable Claude Code config bundle** that ships with Memento. None of it is auto-loaded — you opt in by copying pieces into your global `~/.claude/` setup.

## What's in here

```
claude/
├── INSTALL.md              ← this file
├── settings.example.json   ← drop-in snippet for ~/.claude/settings.json
├── hooks/
│   ├── memento-restore.sh       UserPromptSubmit — once-per-session "Memento ready" status line
│   └── memento-observe.sh       Stop — gated Haiku judge that auto-saves durable observations
└── skills/
    ├── memory-observe/SKILL.md      /memory-observe <text>     — manual save shortcut
    ├── memory-recall/SKILL.md       /memory-recall <query>     — graph-enhanced recall
    ├── memory-restore/SKILL.md      /memory-restore            — load proactive context (manual)
    ├── memory-stats/SKILL.md        /memory-stats              — health + counts
    ├── memory-skills/SKILL.md       /memory-skills             — extracted skill clusters
    ├── memory-rebuild/SKILL.md      /memory-rebuild            — rebuild knowledge graph
    └── memory-consolidate/SKILL.md  /memory-consolidate        — find duplicates + conflicts
```

## Install (3 steps)

### 1. Copy the hooks

```bash
mkdir -p ~/.claude/hooks
cp claude/hooks/*.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh
```

### 2. Wire them into `~/.claude/settings.json`

Open `~/.claude/settings.json` and merge the `hooks` block from `claude/settings.example.json`. If you already have hooks, append the new entries to the matching event arrays (`PreToolUse` Bash matcher, `PostToolUse` Bash matcher, `UserPromptSubmit`, `Stop`).

If you don't have a `~/.claude/settings.json` yet, just copy the example:

```bash
cp claude/settings.example.json ~/.claude/settings.json
```

### 3. (Optional) Install the slash command skills

```bash
mkdir -p ~/.claude/skills
cp -r claude/skills/* ~/.claude/skills/
```

After this, `/memory-observe`, `/memory-recall`, `/memory-restore`, etc. are available in any Claude Code session.

## Required runtime

The hooks talk to the Memento backend over HTTP. Both must be running:

```bash
docker compose up -d                                                      # Qdrant
MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/memento-backend.log 2>&1 &
```

If the backend is down, every hook bails out silently (`exit 0`). They never block Claude Code.

## What each hook does

### `memento-restore.sh` — UserPromptSubmit

Fires once per session (gated by `/tmp/memento-restored-${CLAUDE_SESSION_ID}` marker). Outputs a single status line:

```
Memento ready — 292 memories · 272 nodes · 1525 edges. Use recall_memories() on demand.
```

That's all — no context injection, no token bloat. The model uses `mcp__memento__recall_memories` on demand instead.

**Why no injection?** Earlier versions injected ~3KB of proactive memories per session. The signal-to-noise ratio was bad once bulk-imported markdown blobs polluted the rankings. Status-line-only is the lowest-cost honest signal.

Kill switch: `MEMENTO_AUTOSAVE=0`.

### `memento-observe.sh` — Stop

Fires after every assistant turn but **gates the expensive Haiku call** behind cheap signal detection:

1. New git commits since last fire
2. Keyword in last user message (`remember`, `let's go`, `decided`, `prefer`, `gotcha`, `fix root cause`, `hard rule`, `always`, `never`)
3. 5+ assistant turns AND zero saves today

If none match, hook exits silently. Without the gate, this would fire Haiku on every "thanks" / "ok" turn at ~$0.001 each = $0.05/session. With the gate: ~$0.005/session.

When Haiku does fire, it returns strict JSON `{observe, type, content}` and POSTs durable observations to `/api/memory/observe` with the caller's `cwd` (so the observation gets the correct project scope).

Kill switch: `MEMENTO_AUTOSAVE=0`. Re-entrancy guard: `MEMENTO_JUDGE_INFLIGHT=1`.

## Settings example

See `claude/settings.example.json` for a copy-pastable JSON snippet wiring both hooks. `Stop` and `UserPromptSubmit` don't need a matcher.

## Uninstall

```bash
rm ~/.claude/hooks/memento-*.sh
# Then remove the matching entries from ~/.claude/settings.json
```

The backend (`docker compose down`) and the YAML data at `~/clawd/memory/` are unaffected.
