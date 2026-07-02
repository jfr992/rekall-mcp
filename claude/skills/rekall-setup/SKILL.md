---
name: rekall-setup
description: Install or re-verify Rekall's Claude Code wiring — hooks, slash commands, and settings.json entries. Idempotent. Run from inside a rekall-mcp checkout. User-invocable only.
user-invocable: true
allowed-tools: Bash(*)
---

# Rekall Setup

Runs the bundled installer at `claude/setup/install.sh`. Safe to re-run; it backs up `~/.claude/settings.json` before any patch and skips files that are already up-to-date.

## What it does

1. Preflight: checks `docker`, `jq`, `curl`, `python3`
2. Starts Qdrant + backend (skip with `--skip-backend`)
3. Copies `rekall-restore.sh` + `rekall-observe.sh` to `~/.claude/hooks/`
4. Backs up + patches `~/.claude/settings.json` with `UserPromptSubmit` and `Stop` hook entries (deduped — won't add if already wired)
5. Copies all 9 slash commands to `~/.claude/skills/`
6. Verifies backend health + reports memory count

## Run

!`bash "$CLAUDE_PROJECT_DIR/claude/setup/install.sh" 2>&1 | tail -40`

If you see "backend not reachable" at the end, start it manually:

```bash
docker compose up -d
MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/rekall-backend.log 2>&1 &
```

Or re-run with the backend flag:

```bash
bash claude/setup/install.sh --skip-backend
```

## Restart Claude Code

Slash commands and hooks load at session start. After install, exit Claude Code and reopen for `/memory-stats`, `/memory-recall`, etc. to become available.
