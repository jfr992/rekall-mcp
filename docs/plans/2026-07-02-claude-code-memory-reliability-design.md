# Claude Code Memory Reliability Design

## Goal

Make Rekall safe and trustworthy enough for Claude Code to use as an initial
agent memory substrate, while preserving a clear path to team deployments and
later Codex support.

## Design Principles

- Local-first by default: a single developer running Claude Code should not
  accidentally expose memory over the network.
- YAML remains the human-inspectable source of truth.
- Qdrant is the recall index, not the only copy of memory.
- Project identity is resolved once and reused everywhere.
- Graph recall must explain itself to the agent.
- Every saved memory must carry enough provenance to answer who saved it, from
  where, with which tool, and why.

## Approaches Considered

### Approach A: Patch the Known Bugs Only

Fix `glob("*.yaml")`, `asyncio.run()`, and the project validation mismatch,
then document the remaining security and provenance caveats.

This is the fastest path, but it keeps the system in a fragile shape. Claude
Code would still need to infer whether recall results are complete, why graph
neighbors appeared, and whether the deployment is safe for real memories.

### Approach B: Claude Code Reliability Layer

Treat Claude Code as the first supported agent profile. Make storage, project
identity, local deployment defaults, graph evidence, and provenance into an
explicit contract around the existing manager, MCP tools, REST endpoints, and
startup packet.

This is the recommended path. It keeps the architecture small, reuses the
existing `agent_startup`, `MemoryScope`, YAML, Qdrant, and knowledge graph
modules, and creates a stable foundation before adding Codex-specific behavior.

### Approach C: Multi-Agent Memory Platform

Design a full multi-agent, multi-user memory service now, including account
identity, shared workspaces, role-based access, audit logs, and remote Qdrant as
the default production mode.

This may be valuable later, but it is too much surface area for the first
trustworthy Claude Code release. It would add product and security choices
before the local agent contract is proven.

## Recommended Architecture

Use Approach B.

Claude Code gets one blessed startup path:

```text
agent_startup(project?, agent="claude-code")
```

That startup packet should include scope, trust boundary, recent memories,
important memories, unresolved contradictions, graph-backed related context,
memory health warnings, and save/recall policy hints.

The write path should flow through one identity and provenance envelope:

```text
Claude Code tool call
  -> ScopeDetector.detect(...)
  -> ProjectIdentity.resolve(...)
  -> ProvenanceEnvelope.from_scope(...)
  -> MemoryManager.save/observe(...)
  -> YAML + Qdrant + knowledge graph
```

The read path should expose why each memory is present:

```text
recall_memories(query)
  -> vector seed search
  -> graph neighbor expansion
  -> composite ranking
  -> results with recall evidence
```

## Local And Team Modes

### Local Mode

Local mode is the default.

- Backend default host is loopback.
- Docker-published backend and Qdrant ports bind to loopback.
- Qdrant is not reachable from the LAN.
- HTTP token auth may remain optional for purely local use.
- Claude Code MCP tools remain the primary interface.

### Team Mode

Team mode is explicit.

- A user must opt in through a named setting such as `REKALL_TEAM_MODE=1` or a
  compose override.
- Non-loopback backend exposure requires a bearer token unless an explicit
  unsafe override is set.
- Qdrant remote or LAN access must support `QDRANT_API_KEY`.
- Documentation must describe what is exposed, how to rotate credentials, and
  how to return to local mode.

## Storage Reliability

All memory readers that scan YAML must support the nested project layout. Use
`Path.rglob("*.yaml")` and skip internal files deliberately rather than
assuming flat files.

Sync must never delete Qdrant memories after a suspicious YAML discovery result.
If Qdrant contains memories and YAML discovery returns zero, sync should return a
blocked/unsafe result unless the caller passes an explicit force flag.

Compaction should be async-safe when called from async REST routes. It should
mark nested YAML originals as compacted before deleting originals from Qdrant,
and it should report partial failures instead of swallowing them.

## Project Identity

Introduce one project identity module.

The canonical project key is the value used for filtering, Qdrant payloads, and
storage paths. It must be path-safe and API-safe.

The display name preserves what the human or agent supplied. Existing safe
project names should remain unchanged. Unsafe names should be normalized to a
stable key while preserving `project_display_name`.

REST, MCP tools, UI project selection, YAML writes, Qdrant filters, and startup
scope detection must call the same resolver. The system should provide
compatibility for legacy project names already present on disk or in Qdrant.

## Graph Evidence

Recall already uses graph expansion. The next version should make graph use
observable.

Each recalled memory should include a `recall_evidence` payload:

- `source`: `vector`, `graph`, or `vector+graph`
- `seed_memory_id`
- `relation`
- `relation_weight`
- `vector_score`
- `importance_score`
- `recency_score`
- `tier_score`
- `graph_score`
- `final_score`

Formatted Claude Code output should include a short reason line, for example:

```text
Why: vector hit; linked by led_to from 2026-07-01_decision_abcd1234
```

## Provenance

Extend `MemoryScope` into a durable provenance envelope.

Minimum fields:

- `agent`
- `created_by`
- `source_tool`
- `source_event`
- `save_reason`
- `cwd`
- `workspace_root`
- `repo_root`
- `repo_name`
- `repo_remote`
- `branch`
- `trust_boundary`
- `session_id`
- `observed_at`

Every memory saved through `observe`, `save_memory`, REST save, and future
Claude Code hooks should persist this metadata to both YAML and Qdrant.

## Claude Code MVP Contract

Claude Code should use:

- `agent_startup(project?, agent="claude-code")` once at session start.
- `recall_memories(query, project=...)` for targeted lookup.
- `observe(summary, context=...)` for durable decisions, root causes,
  requirements, preferences, and important learnings.
- `memory_pressure(project=...)` occasionally for hygiene.

Claude Code should not use destructive maintenance paths by default. Prune and
compaction apply operations remain REST/admin actions until the safety contract
is stronger.

## Codex Later

Codex support should reuse the same project identity, provenance, recall
evidence, and local/team security modes. The Codex-specific work should mostly
be policy and startup copy, not a second memory architecture.
