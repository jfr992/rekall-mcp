## Memory — Rekall

The Rekall MCP server registers under whatever name you chose (`memory` or `rekall`); the hooks match both, so tools appear as `mcp__memory__*` or `mcp__rekall__*`.

The restore hook prints a one-line status once per session (memories, nodes, edges). It injects no context.

**Recall on demand** when stuck, referencing prior work, or needing cross-project context:
- `recall_memories(query="...")` for semantic plus graph search
- `/memory-recall <query>` as the slash-command form

**Auto-save is owned by the Stop hook.** A Haiku judge runs only when a gate opens: new git commits since the last fire, a durability keyword in your last message (`remember`, `decided`, `prefer`, `gotcha`, `always`, `never`), or 5+ turns with zero saves today. Do not duplicate it per turn.

**Manual save** only when the user asks ("remember this") or the gate would miss something durable. Use `save_memory(content, type)`:
- user correction -> `learning`
- design or architecture decision -> `decision`
- tooling or workflow preference -> `preference`
- non-obvious root cause -> `learning`
- deployment or config outcome -> `fact`

Save the WHY, one sentence per memory. Skip routine edits, test runs, and commits.

Native `MEMORY.md` under `~/.claude/projects/<project>/memory/` is separate and hand-curated; Rekall never writes it.

Kill switch: `REKALL_AUTOSAVE=0` disables startup injection, the restore status line, and Stop-hook auto-save.
