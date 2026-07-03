# Agent Startup Guide

How Claude Code and Codex should consume the new memory system.

## Recommended startup flow

Call **one** of these at session start:

1. `agent_startup` (best default)
2. `resume_packet` (structured continuity)
3. `handoff_summary` (shorter human-readable momentum summary)

## Startup Contract

Startup order:

1. Resolve current project from the harness cwd.
2. Load the project capsule.
3. Add memory doctor warnings when degraded.
4. Defer targeted recall until the user prompt or command supplies a cue.

## Best default

### Claude Code
- Call `agent_startup(project?, agent="claude-code")`
- Read `startup_summary`
- Use `observe()` for durable decisions, learnings, preferences, and requirements
- Use `memory_pressure` periodically, not every turn
- Optional: install the `SessionStart` capsule hook with `bash claude/setup/install.sh --install-startup-capsule`

### Codex
- Call `agent_startup(project?, agent="codex")`
- Read `startup_summary`
- Use `resume_packet` when you need the structured JSON payload
- Keep repo/project boundaries strict when switching worktrees or repos

## Tool roles

### `agent_startup`
Single best entrypoint for startup.
Returns:
- scope
- startup_summary
- resume_packet
- system_hints

### `resume_packet`
Structured continuity payload.
Returns:
- recent
- important
- unresolved
- next_steps
- handoff
- pressure
- promotion

### `handoff_summary`
Human-readable short startup summary.
Good for prompt injection or quick rehydration.

### `memory_pressure`
Memory hygiene report.
Use occasionally to find low-value/stale working memories.

## Save policy

Save when the information is durable and high-signal:
- architecture decisions
- root causes
- user preferences
- requirements
- important learnings

Do not save:
- routine command output
- temporary exploration
- speculative thoughts
- repeated noise

## Operational rule

Prefer `agent_startup` once per session, not every turn.
That keeps startup coherent and avoids turning memory into prompt spam.

## Claude Code SessionStart Capsule

The shippable `claude/hooks/session-start-memory.sh` hook is opt-in. It prefers `/api/memory/capsule`, falls back to `/api/memory/context/startup`, infers project scope from Claude Code's `cwd` or `project_dir` JSON fields, and emits only a thin `SessionStart` `additionalContext` packet.

Default install preserves the existing `UserPromptSubmit` status line and `Stop` autosave behavior. Add the capsule only when you explicitly want startup injection:

```bash
bash claude/setup/install.sh --install-startup-capsule
```

Before changing live files under `~/.claude`, copy the current files into `~/.claude/backups/rekall-live-config-<timestamp>/`. The shippable installer does not overwrite live hook files without preserving the previous copy.
