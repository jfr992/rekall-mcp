# Claude Code Test Handoff

How to test the agent nervous-system branch with Claude Code.

## Goal

Verify that Claude Code can use Rekall as a local-first memory nervous system:

- startup familiarity comes from `agent_startup` / project capsules
- degraded memory state is visible through `memory_doctor`
- targeted recall still happens on demand, not as prompt spam
- cross-project and reflex recall work from Claude Code
- hooks remain safe, small, and rollbackable

## 1. Run the PR Backend

From the Rekall checkout:

```bash
cd ~/Repos/rekall-mcp
git fetch origin
git checkout codex/rekall-agent-nervous-system
git pull

docker compose up -d --build mcp
curl -s http://localhost:8000/health | jq .
```

Expected: the backend is healthy on `localhost:8000`.

## 2. Check Startup Payload Directly

Before touching Claude Code, confirm the new API shape:

```bash
curl -s 'http://localhost:8000/api/memory/context/startup?project=byte-edge&agent=claude-code&limit=8' \
  | jq '{
      project: .scope.project,
      has_capsule: (.project_capsule.project != null),
      summary: .startup_summary[0:700]
    }'
```

Expected:

- `project` is `byte-edge`
- `has_capsule` is `true` when memories exist for the project
- `summary` is short enough to read, not a raw memory dump

## 3. Ensure Claude Code Sees Rekall

```bash
claude mcp list | rg rekall || claude mcp add --transport http rekall http://localhost:8000
```

If Rekall already exists but points somewhere else, update the Claude Code MCP config or remove/re-add the `rekall` entry.

## 4. Install Claude Code Wiring

This installer is idempotent and backs up live files under `~/.claude/backups/rekall-live-config-<timestamp>/`.

```bash
cd ~/Repos/rekall-mcp
bash claude/setup/install.sh --skip-backend --install-startup-capsule
```

What this installs:

- `rekall-restore.sh` as `UserPromptSubmit`
- `rekall-observe.sh` as `Stop`
- `session-start-memory.sh` as opt-in `SessionStart`
- slash commands under `~/.claude/skills/`

Restart Claude Code after installing so hooks and slash commands reload.

## 5. Test the SessionStart Hook Directly

Run this before starting Claude Code:

```bash
printf '{"cwd":"%s"}' "$HOME/Repos/byte-edge" \
  | REKALL_API_URL=http://127.0.0.1:8000 ~/.claude/hooks/session-start-memory.sh \
  | jq -r '.hookSpecificOutput.additionalContext'
```

Expected output starts with:

```text
== REKALL STARTUP (byte-edge) ==
```

It should contain a thin project capsule and the save instruction. It should not dump a large wall of raw memories.

Note: the hook prefers `/api/memory/capsule` first. Full doctor status is available through `memory_doctor`.

## 6. Test Inside Claude Code

Start Claude Code from the target repo:

```bash
cd ~/Repos/byte-edge
claude
```

Use these prompts:

```text
Use Rekall agent_startup for this project. Summarize the startup_summary.
```

```text
Use memory_doctor for project byte-edge. Is recall trustworthy?
```

```text
Use recall_across_projects with query "terraform terragrunt qdrant hooks safety" and current_project "byte-edge". Show transferable lessons by project.
```

```text
Use reflex_recall on "terraform apply touches qdrant hooks memory cleanup" for byte-edge. Show cues and recalled memories.
```

Also test slash commands:

```text
/memory-stats
/memory-recall qdrant hook startup
```

## Pass Criteria

- Claude Code sees the Rekall MCP server.
- Tools include `agent_startup`, `memory_doctor`, `recall_across_projects`, and `reflex_recall`.
- Startup scope resolves to `byte-edge`, not `rekall-mcp`.
- `memory_doctor` reports YAML/Qdrant/vector/graph/provenance status.
- Cross-project recall labels which project each memory came from.
- Reflex recall returns cues for infra, memory-data, hook, Qdrant, or deployment text.
- SessionStart injection is small and useful.
- Stop hook does not save low-signal chatter.

## Rollback

Use the backup paths printed by the installer.

Restore settings:

```bash
cp ~/.claude/settings.json.bak-YYYYMMDD-HHMMSS ~/.claude/settings.json
```

Remove only the opt-in startup capsule hook:

```bash
rm -f ~/.claude/hooks/session-start-memory.sh
```

Emergency kill switch for all Rekall Claude hooks:

```bash
export REKALL_AUTOSAVE=0
```

To make the kill switch persistent, add it to your shell profile or Claude Code launch environment.
