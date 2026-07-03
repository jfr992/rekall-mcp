# Claude Code Bundle for Rekall

This folder is a **portable Claude Code config bundle** that ships with Rekall. None of it is auto-loaded — you opt in by copying pieces into your global `~/.claude/` setup.

## What's in here

```
claude/
├── INSTALL.md              ← this file
├── settings.example.json   ← drop-in snippet for ~/.claude/settings.json
├── setup/
│   └── install.sh          ← one-shot installer (idempotent, with backup)
├── hooks/
│   ├── rekall-restore.sh       UserPromptSubmit — once-per-session "Rekall ready" status line
│   ├── rekall-observe.sh       Stop — gated Haiku judge that auto-saves durable observations
│   └── session-start-memory.sh SessionStart — optional thin project capsule injection
└── skills/
    ├── rekall-setup/SKILL.md       /rekall-setup             — re-run installer from inside Claude Code
    ├── rekall-publish/SKILL.md     /rekall-publish           — export memory to an OKF knowledge bundle
    ├── memory-observe/SKILL.md      /memory-observe <text>     — manual save shortcut
    ├── memory-recall/SKILL.md       /memory-recall <query>     — graph-enhanced recall
    ├── memory-restore/SKILL.md      /memory-restore            — load proactive context (manual)
    ├── memory-stats/SKILL.md        /memory-stats              — health + counts
    ├── memory-skills/SKILL.md       /memory-skills             — extracted skill clusters
    ├── memory-rebuild/SKILL.md      /memory-rebuild            — rebuild knowledge graph
    └── memory-consolidate/SKILL.md  /memory-consolidate        — find duplicates + conflicts
```

## Install — one command (recommended)

```bash
bash claude/setup/install.sh
```

What it does (all idempotent):
- Preflight: checks `docker`, `jq`, `curl`, `python3`
- Starts Qdrant + backend if not already running
- Copies the 2 default hooks to `~/.claude/hooks/`
- Backs up `~/.claude/settings.json` then merges in `UserPromptSubmit` + `Stop` entries (deduped — won't duplicate if already wired)
- Copies all 9 slash commands to `~/.claude/skills/`
- Verifies backend health + reports memory count

**Restart your Claude Code session** after install for slash commands to load.

Flags:
- `--skip-backend` — only do Layer 1 wiring (skip docker + python startup)
- `--skills-only` — only copy slash commands
- `--hooks-only` — only install hooks + patch settings.json
- `--install-startup-capsule` — opt in to the `SessionStart` capsule hook and settings entry

The `SessionStart` capsule hook is **not installed by default**. It injects a small `additionalContext` packet at session start, so it is explicit opt-in:

```bash
bash claude/setup/install.sh --install-startup-capsule
```

Before changing live files under `~/.claude`, copy the current files into `~/.claude/backups/rekall-live-config-<timestamp>/`. The shippable installer does not overwrite live hook files without preserving the previous copy.

After install, you can re-run from inside Claude Code via `/rekall-setup`.

## Install — manual (if you prefer to see every step)

```bash
# 1. Default hooks
mkdir -p ~/.claude/hooks
cp claude/hooks/rekall-restore.sh ~/.claude/hooks/
cp claude/hooks/rekall-observe.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/rekall-restore.sh ~/.claude/hooks/rekall-observe.sh

# Optional: SessionStart capsule hook
cp claude/hooks/session-start-memory.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/session-start-memory.sh
# Then add a SessionStart command entry for ~/.claude/hooks/session-start-memory.sh
# to ~/.claude/settings.json.

# 2. Settings — see claude/settings.example.json for the snippet to merge into
#    ~/.claude/settings.json (or copy it directly if you have no existing settings)
cp claude/settings.example.json ~/.claude/settings.json

# 3. Slash commands (optional)
mkdir -p ~/.claude/skills
cp -r claude/skills/* ~/.claude/skills/
```

## Required runtime

The hooks talk to the Rekall backend over HTTP. Both must be running:

```bash
docker compose up -d                                                      # Qdrant
MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/rekall-backend.log 2>&1 &
```

If the backend is down, every hook bails out silently (`exit 0`). They never block Claude Code.

## What each hook does

### `rekall-restore.sh` — UserPromptSubmit

Fires once per session (gated by `/tmp/rekall-restored-${CLAUDE_SESSION_ID}` marker). Outputs a single status line:

```
Rekall ready — 292 memories · 272 nodes · 1525 edges. Use recall_memories() on demand.
```

That's all — no context injection, no token bloat. The model uses `mcp__rekall__recall_memories` on demand instead.

**Why no injection?** Earlier versions injected ~3KB of proactive memories per session. The signal-to-noise ratio was bad once bulk-imported markdown blobs polluted the rankings. Status-line-only is the lowest-cost honest signal.

Kill switch: `REKALL_AUTOSAVE=0`.

### `rekall-observe.sh` — Stop

Fires after every assistant turn but **gates the expensive Haiku call** behind cheap signal detection:

1. New git commits since last fire
2. Keyword in last user message (`remember`, `let's go`, `decided`, `prefer`, `gotcha`, `fix root cause`, `hard rule`, `always`, `never`)
3. 5+ assistant turns AND zero saves today

If none match, hook exits silently. Without the gate, this would fire Haiku on every "thanks" / "ok" turn at ~$0.001 each = $0.05/session. With the gate: ~$0.005/session.

When Haiku does fire, it returns strict JSON `{observe, type, content}` and POSTs durable observations to `/api/memory/observe` with the caller's `cwd` (so the observation gets the correct project scope).

Kill switch: `REKALL_AUTOSAVE=0`. Re-entrancy guard: `REKALL_JUDGE_INFLIGHT=1`.

### `session-start-memory.sh` — SessionStart (opt-in)

Installs only when you pass `--install-startup-capsule`. It reads Claude Code's SessionStart JSON from stdin, infers the project from `cwd` or `project_dir`, calls `/api/memory/capsule` first, and falls back to `/api/memory/context/startup`.

It prints a thin JSON packet with `hookSpecificOutput.hookEventName = "SessionStart"` and `additionalContext` containing the project capsule or startup summary plus a short save instruction. It honors `REKALL_AUTOSAVE=0`. Run `memory_doctor(project)` separately when you need a full trust check.

## Settings example

See `claude/settings.example.json` for a copy-pastable JSON snippet wiring the default hooks. `Stop`, `UserPromptSubmit`, and the opt-in `SessionStart` hook don't need a matcher.

## Uninstall

```bash
rm ~/.claude/hooks/rekall-*.sh
# Then remove the matching entries from ~/.claude/settings.json
```

The backend (`docker compose down`) and the YAML data at `$MEMORY_STORAGE_PATH` (default `~/.claude/memory/`) are unaffected.
