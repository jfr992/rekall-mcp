# Measurable Memory (sub-project A) — design

**Date:** 2026-10-09
**Status:** Draft for review
**Branch:** `feat/measurable-memory-a`
**Depends on:** PR #100 (read-time pollution fixes), merged first.

## Problem

Rekall delivers memories to agents, but nobody can tell whether a delivered
memory changed the work. Measured on 2026-10-08:

| Finding | Value |
|---|---|
| Delivered memory instances, 39 main sessions, 5 weeks | 2109 |
| Referenced later by exact id | 0.4% |
| Echoed later by content, explicit recall / capsule / reflex | 14.4% / 3.6% / 0.7% |
| Capsule injected into subagents on `SessionStart:compact` | 169 attachments, 1641 memories, 1 echo |
| Recalls in `unattributed:general` | 191 recalls, ~316k tokens |
| Memories saved under container cwd `app` with `agent: unknown` | 89 (266 under project `app` overall) |

Root causes, all verified in code:

1. Recall and capsule output print no memory ids (`manager._format_with_guidance`,
   `claude/hooks/session-start-memory.sh`), so an id can never be cited.
2. `rekall-session-end.sh` extracts *exposure* ids only; it never computes
   references. The utility loop has measured nothing for explicit recall and
   capsule since it shipped.
3. MCP `observe` accepts no `project`; `observe` and `save_memory` accept no
   `cwd`, `session_id`, `agent`; scope falls back to the backend cwd.
4. `session-start-memory.sh` has no subagent guard; hooks fire inside
   subagents and carry `agent_id` on stdin (documented) when they do.
5. `fold_sessions` creates a session only from `session_summary` or
   `memory_surfaced` events, so a correctly tagged recall can still land
   unattributed.
6. `scripts/utility_report.py` credits every recalled memory when any edit or
   test follows in the session. Reinforcement has a top-1 margin guard; the
   report does not.
7. The MCP server is registered as `memory` in this install (41,963 calls vs
   33 for `rekall`). CLAUDE.md's namespace note is wrong for it.

## Goals

- Every write and recall carries caller project, session, agent.
- Every delivered memory is traceable by id, in both clients.
- No capsule delivery to subagents.
- A measurement contract that records delivered vs referenced per session
  without inflating reinforcement credit.
- One decision-grade number, produced offline from existing transcripts,
  that says whether delivered memories helped.

## Non-goals

Reflex changes (parked). Judge prompt (sub-project C). Demote, remap, agent
backfill, resparse (sub-project B, ops). Cockpit UI. Claude Code mod. A
"used / shown" headline: citation is telemetry, not utility.

## Design

### 1. Subagent guard

`claude/hooks/session-start-memory.sh`: read `agent_id` from the hook payload
before any network call; exit 0 when present. `memory-prune.sh` unchanged
(daily-gated, harmless). Codex adapter: same check on its SessionStart
subcommand if Codex exposes an equivalent field; otherwise no change.

### 2. Provenance on write tools

`src/tools/builtin/memory.py`:

- `observe(summary, type, context, project=None, cwd=None, session_id=None, agent=None)`
- `save_memory(content, memory_type, project=None, context=None, cwd=None, session_id=None, agent=None)`
- `recall_memories` gains `agent`.

Scope resolves through `ScopeDetector.detect(project=, cwd=, agent=)`, the
same call the REST observe route makes. `cwd`, `session_id`, `agent` are also
forwarded into `manager.save(...)` so the record and the event carry them;
populating `MemoryScope` alone is not enough. Docstrings: one trigger-shaped
line per field.

### 3. Printed ids

Recall bullets: `- content (date) [memory_id]`. Capsule bullets, server
renderer (`capsules.py`) and hook fallback renderer: `- [date] content
[memory_id]`. Ids survive truncation (truncate content, append id after).
Labeled in docs as traceability: lets an agent `close_loop`, pin, or dispute
by id. Not a usage metric.

### 4. Provenance hook (replaces the mod)

New `claude/hooks/rekall-provenance.sh`, PreToolUse, matcher
`mcp__memory__.*|mcp__rekall__.*`. Reads `tool_name`, `tool_input`,
`session_id`, `cwd` from stdin; returns `updatedInput = tool_input + {fields}`
where `fields` is a per-tool allowlist:

| tool | adds |
|---|---|
| `recall_memories`, `observe`, `save_memory` | `cwd`, `session_id`, `agent: "claude-code"` |
| everything else | nothing (hook exits 0 with no output) |

Never sets `permissionDecision`. Never adds a field the model already set.
Fails open on any error. Kill switch `REKALL_AUTOSAVE=0`.

**Spike first (task 1 of the plan):** one live call proving Claude Code
delivers `updatedInput` to an MCP tool and FastMCP accepts the added field.
If it fails, fall back to a Claude Code mod `tool.call` rewrite with the same
allowlist; nothing else in this design changes.

### 5. Measurement contract

`POST /api/memory/events`, `session_summary` payload gains:

```json
{
  "session_id": "...", "project": "...", "client": "claude-code|codex",
  "delivered": {"explicit": [...ids], "capsule": [...ids], "reflex": [...ids]},
  "referenced": [...ids],
  "coverage": {"transcript_tail_bytes": 1048576, "truncated": false}
}
```

- The event log stays append-only; dedupe happens at read time in
  `fold_sessions` and `utility_report.collapse_sessions`: the latest summary
  per `session_id` wins for `referenced` (resumed sessions, retries).
- `fold_sessions` also creates a session from any `memory_recalled` event
  carrying a `session_id`.
- `rekall-session-end.sh` and the Codex adapter compute `referenced` as ids
  appearing in assistant text or tool_use input after delivery. Delivered
  counts are taken after rendering, not from server selection.
- `utility_report.py`: per-memory outcome credit requires the memory id in
  `referenced` or an explicit `close_loop`/pin; otherwise the session
  outcome is recorded as `unknown` for that memory. The ratio is named
  **citation coverage** everywhere it is printed. Reinforcement
  (`reinforce.py`) is untouched by this change.

### 6. Decision metric and capsule default

Computed offline on 2026-10-09 from 36 sessions, 120 hand-labeled delivered
instances (archive: `~/backups/rekall-eval-2026-10-09.tar.gz`):

| Surface | Sampled | Helpful | Harmful |
|---|---|---|---|
| Explicit `recall_memories` | 40 | 4 | 0 |
| Startup capsule | 40 | 0 | 0 |
| Reflex | 40 | 0 | 0 |

About 2,000 delivered tokens per helpful application frame-wide; capsule and
reflex delivered about 63k tokens with no helpful hit. Echo is a weak proxy
(2 of 4 helpful never echoed; 23 of 25 echoed not helpful).

Consequence, in scope for A: **the startup capsule stays off by default.**
The installer already treats `session-start-memory.sh` as opt-in
(`INSTALL_STARTUP_CAPSULE`, pinned by a test); the maintainer's machine has
it installed and removes that SessionStart entry at rollout. No new env flag.
Explicit recall unchanged. The following week with the capsule off, with the
measurement contract live, is the controlled check that nothing was lost;
if explicit recall usage or the helpful rate drops, the default flips back.

The labeling method is kept as the reusable decision metric: stratified
sample across surfaces, labels helpful / harmful / irrelevant /
indeterminate with the cited later action, information already present
before delivery is not helpful. Reported as helpful per 100 sessions,
harmful per 100 sessions, delivered tokens per helpful application.

## Testing

- pytest: scope resolution from a temp git repo path via the MCP tools;
  `agent` persisted; defaults unchanged; renderer snapshots with ids;
  event ingestion dedupe; `fold_sessions` from a tagged recall;
  `utility_report` marks unknown without a reference.
- Hook tests (existing bash fixtures under `tests/`): guard exits on
  `agent_id`; provenance hook emits the allowlisted fields only and nothing
  for other tools.
- Spike result recorded in the plan before task 2 starts.

## Rollout

1. Spike (task 1). 2. Server changes behind no flag; fields optional.
3. Hooks installed via the existing installer; `rekall-provenance.sh` added
to `~/.claude/settings.json` PreToolUse. 4. `docs/CLAUDE_MEMORY_SETTINGS.md`
and README REST table updated. 5. Fix CLAUDE.md namespace note.

## Risks

- `updatedInput` on MCP tools is inferred from docs, not stated. Spike.
- Printed ids may teach the model to cite ids; the metric is labeled
  coverage, not utility, to keep that from reading as success.
- Two clients, two hooks computing `referenced`; the contract is the
  shared surface. Codex parity tracked in the plan.
