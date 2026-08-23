# Agent Startup Guide

How Claude Code and Codex should consume the new memory system.

## Recommended startup flow

When broad project continuity can change the work, call **one** of these at session start. Otherwise skip broad startup context and use targeted recall only when a prompt or command supplies a useful cue:

1. `agent_startup` (broad-context default)
2. `resume_packet` (structured continuity)
3. `handoff_summary` (shorter human-readable momentum summary)

## Startup Contract

Startup order:

1. Decide whether broad continuity is useful for this task.
2. If it is, resolve and pass the current project explicitly, then load one startup view.
3. Skip full doctor scans; call `memory_doctor(project)` on demand when recall trust is in question.
4. Defer targeted recall until the user prompt or command supplies a cue.

## Conditional broad-context default

### Claude Code
- When broad continuity is useful, call `agent_startup(project="<repo-name>", agent="claude-code")`
- Read `startup_summary`
- Use `observe()` for durable decisions, learnings, preferences, and requirements
- Use `memory_pressure` periodically, not every turn
- Optional: install the `SessionStart` capsule hook with `bash claude/setup/install.sh --install-startup-capsule`

### Codex
- When broad continuity is useful, call `agent_startup(project="<repo-name>", agent="codex")`
- Read `startup_summary`
- Use `resume_packet` when you need the structured JSON payload
- Pass `project` explicitly in worktrees; keep repo/project boundaries strict when switching worktrees or repos

## Tool roles

### `agent_startup`
Broad-context entrypoint when project continuity is likely to affect the task.
Returns:
- scope
- startup_summary
- resume_packet
- project_capsule
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

When broad continuity is needed, use `agent_startup` at most once per session—not every turn. Otherwise skip it and use targeted recall only when relevant. That keeps startup coherent and avoids turning memory into prompt spam.

## Claude Code SessionStart Capsule

The shippable `claude/hooks/session-start-memory.sh` hook is opt-in. It prefers `/api/memory/capsule`, falls back to `/api/memory/context/startup`, infers project scope from Claude Code's `cwd` or `project_dir` JSON fields, and emits only a thin `SessionStart` `additionalContext` packet.

Default install preserves the existing `UserPromptSubmit` status line and safe-mode `Stop` autosave behavior, and adds bounded `SessionEnd` recall-utility accounting. The SessionEnd hook sends IDs and counts only, never transcript content. Add the capsule only when you explicitly want startup injection:

```bash
bash claude/setup/install.sh --install-startup-capsule
```

Before changing live files under `~/.claude`, copy the current files into `~/.claude/backups/rekall-live-config-<timestamp>/`. The shippable installer does not overwrite live hook files without preserving the previous copy.

## Codex lifecycle adapter

The Codex installer registers real lifecycle events, including `SessionEnd`; bounded recall-utility summaries are automatic when the transcript contains correlated recall and outcome evidence. `SessionEnd` may be delayed until Codex actually closes or idles the root session, and its transcript format is treated as unstable. Hooks are bounded and fail open. They may provide untrusted historical context, never executable instructions. Keep native Codex memory (`~/.codex/memories/`) separate and never edit it.
