# Terminal-Based Agent Orchestra Design

**Goal:** Replace the `claude -p` chat orchestrator with real terminal sessions (xterm.js + tmux + WebSocket) so every agent has full skills, tools, and MCP access.

**Architecture:** tmux sessions as the persistence layer, a Python WebSocket relay in the Starlette server, and xterm.js in the browser. Each agent gets its own tmux session, visible as a tab in the dashboard.

**Tech Stack:** tmux, xterm.js (CDN), Starlette WebSocket, Python stdlib pty/fcntl, SQLite for session metadata.

---

## 1. Architecture Overview

```
Browser (xterm.js per tab)
    |  WebSocket per tab
    v
Python Server (port 8002)
    |  WebSocket handler attaches to tmux via PTY
    v
tmux sessions (persist independently)
    |  jarvis-orch-{id}:  claude --mcp-config '...'
    |  jarvis-agent-{id}: codex ...
    |  jarvis-agent-{id}: gemini ...
```

- Each terminal tab = one tmux session + one WebSocket + one xterm.js instance
- Server is a byte relay -- does not interpret terminal data
- tmux sessions outlive the server, page reloads, and browser crashes
- Orchestrator is a full `claude` session (not `-p`), configured with MCP pointing to dashboard server
- Sub-agents spawned by orchestrator via MCP tools OR manually by user

## 2. Session Lifecycle

### Session Types

- **Orchestrator** -- auto-created on first visit, always the first tab. Runs `claude` with MCP config pointing to dashboard server (memory, dispatch tools).
- **Agent (dispatched)** -- created when orchestrator calls `dispatch_agent` MCP tool. Pre-loaded with task prompt as initial input.
- **Agent (manual)** -- created when user clicks `+ Agent`. Blank `claude` session.

### tmux Naming Convention

`jarvis-{type}-{short_id}` -- e.g., `jarvis-orch-a1b2c3`, `jarvis-agent-d4e5f6`

### Lifecycle States

```
CREATE   --> tmux new-session -d -s jarvis-agent-{id} '{cli_command}'
             Store metadata in SQLite, add tab to dashboard

CONNECT  --> User clicks tab
             WebSocket opens to /api/terminal/{id}/ws
             Server spawns: tmux attach -t jarvis-{id} in PTY
             Bytes flow: xterm.js <-> WebSocket <-> PTY <-> tmux

DISCONNECT -> User switches tab or closes browser
             WebSocket closes, PTY detaches from tmux
             tmux session keeps running in background

RECONNECT -> User clicks tab again (or page reloads)
             New WebSocket, new tmux attach
             Full scrollback preserved by tmux

DESTROY  --> User clicks X on tab, or orchestrator kills it
             tmux kill-session -t jarvis-{id}
             Server removes metadata, dashboard removes tab
```

### Session Metadata (SQLite)

| Field | Example |
|---|---|
| session_id | `jarvis-agent-d4e5f6` |
| type | `orchestrator` / `agent-dispatched` / `agent-manual` |
| agent_name | `claude` / `codex` / `gemini` |
| task | `"implement auth module TDD"` |
| workspace | `/Users/jfr9044/projects/myapp` |
| status | `running` / `detached` / `dead` |
| created_at | ISO timestamp |
| cli_command | `claude --mcp-config '...'` |

**Status detection:** Server periodically runs `tmux list-sessions` to sync status. If a tmux session dies, metadata updates to `dead` and the tab shows a completed/exited indicator.

## 3. WebSocket Relay and Terminal I/O

### Server-Side Relay

One async handler per connection:

```python
async def terminal_ws(websocket, session_id):
    # 1. Attach to tmux in a PTY
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        ["tmux", "attach", "-t", session_id],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        preexec_fn=os.setsid,
    )

    # 2. Bidirectional relay
    async with TaskGroup() as tg:
        tg.create_task(pty_to_ws(master_fd, websocket))   # terminal -> browser
        tg.create_task(ws_to_pty(websocket, master_fd))    # browser -> terminal

    # 3. Cleanup on disconnect
    os.close(master_fd)
    process.terminate()
```

### Resize Handling

Browser resize -> xterm.js sends resize event -> WebSocket -> server calls `fcntl.ioctl(master_fd, TIOCSWINSZ, ...)` + `tmux resize-window`.

### Binary Protocol

Raw bytes, no JSON wrapping. One special message type for resize:

| Direction | Type | Format |
|---|---|---|
| Browser -> Server | Input | raw bytes |
| Browser -> Server | Resize | `\x01` + JSON `{"cols":120,"rows":40}` |
| Server -> Browser | Output | raw bytes |

The `\x01` prefix (SOH control char) distinguishes resize messages from normal input.

### Concurrency

Each tab = one WebSocket = one PTY attachment. Multiple tabs can connect to the same tmux session (like two people watching one terminal), but typically one-to-one.

## 4. MCP Integration -- Orchestrator Dispatches Agents

The orchestrator `claude` session connects to the dashboard server's MCP. When it dispatches work, it calls MCP tools that the server handles by spawning tmux sessions.

### MCP Tools Exposed to Orchestrator

| Tool | Purpose |
|---|---|
| `dispatch_agent` | Spawn a new tmux session with a task |
| `list_agents` | List active tmux sessions and their status |
| `agent_output` | Capture last N lines from a tmux session's pane |
| `kill_agent` | Terminate a tmux session |

### dispatch_agent Flow

```
Orchestrator (claude session):
  "I'll dispatch codex to implement the auth module"
  -> calls dispatch_agent(agent="codex", task="implement auth TDD", workspace="/path")

Server handles MCP call:
  1. Generate session_id: jarvis-agent-f7g8h9
  2. Build CLI command with MCP config + system prompt
  3. tmux new-session -d -s jarvis-agent-f7g8h9 'codex ...'
  4. Store metadata in SQLite
  5. Return: {"session_id": "jarvis-agent-f7g8h9", "status": "running"}

Dashboard (via polling):
  - Detects new session in metadata
  - Adds tab to tab bar with agent name + task
  - Tab pulses to indicate new activity
```

### agent_output -- Orchestrator Monitors Sub-Agents

```
Orchestrator:
  -> calls agent_output(session_id="jarvis-agent-f7g8h9", lines=20)

Server:
  -> tmux capture-pane -t jarvis-agent-f7g8h9 -p -S -20
  -> Returns last 20 lines of terminal output as text
```

### Orchestrator Startup Command

```bash
tmux new-session -d -s jarvis-orch-{id} \
  'claude --mcp-config '"'"'{"memento":{"url":"http://localhost:8002/mcp","transport":"streamable-http"}}'"'"''
```

The orchestrator gets `dispatch_agent`, `list_agents`, `agent_output`, `kill_agent`, plus all existing memento tools -- all through a single MCP connection to the dashboard server.

## 5. Frontend -- Tab Bar and Terminal Rendering

### Tab Bar

```
[* Orchestrator] [o codex: auth TDD] [* gemini] [+]
```

- `*` = active/running, `o` = idle/detached, check = completed, `x` = failed
- Active tab highlighted with cyan border (matches dashboard aesthetic)
- `[+]` spawns manual agent -- inline picker for agent type
- Right-click tab -> "Take Control" / "Watch Only" / "Kill" / "Detach"
- Tab shows agent name + truncated task
- New dispatched tabs pulse briefly to draw attention

### Terminal Container

```html
<div id="terminal-tabs"><!-- tab bar --></div>
<div id="terminal-container">
  <!-- one hidden div per session, xterm.js attaches here -->
  <div class="terminal-pane" data-session="jarvis-orch-abc123"></div>
  <div class="terminal-pane" data-session="jarvis-agent-def456" hidden></div>
</div>
```

- Switching tabs: hide current pane, show target pane. xterm.js instance stays alive.
- WebSocket stays open for all tabs. Background tabs buffer data.

### xterm.js Addons

- `xterm-addon-fit` -- auto-resize to container
- `xterm-addon-web-links` -- clickable URLs in terminal output

### Status Bar

```
3 sessions | orch: active | codex: running | ws: connected
```

Polls `/api/terminal/list` every 5s to sync tab state.

### Future Enhancement: Floating/Detachable Panels

v1 ships with tabs. v2 adds drag-to-detach into floating panels with snap-to-grid tiling (like i3wm zones).

## 6. What Changes, What Stays

### Replaces

- `chat_orchestrator.py` -- `_call_claude_cli` (no more `claude -p`), `_fetch_recent_memories` (orchestrator uses MCP directly), `_execute_dispatch` (tmux replaces subprocess)
- Chat bubble UI in `server.py` -- replaced by xterm.js terminals
- `orchestra.py` `_execute_run` -- subprocess spawning replaced by tmux session creation
- HTTP polling for agent status -- replaced by tmux session queries + WebSocket live output

### Stays

- SQLite store -- repurposed for terminal session metadata
- Agent config (`agent_config.py`) -- still defines CLI commands and MCP configs per agent type
- Memory tools -- orchestrator accesses via MCP instead of server-side HTTP fetch
- Workspace picker -- still needed to set working directory for new sessions
- REST API pattern -- new routes alongside existing ones
- Starlette server framework -- add WebSocket support (native in Starlette)

### New Dependencies

- `xterm.js` + `xterm-addon-fit` + `xterm-addon-web-links` (CDN, no build step)
- `tmux` (already installed on macOS)
- No new Python packages -- `pty`, `fcntl`, `asyncio` are stdlib

### New Files

- `tools/builtin/terminal_manager.py` -- tmux session CRUD, PTY relay, MCP tool definitions

### Migration Path

Existing `/api/orchestra/*` endpoints stay working. New `/api/terminal/*` endpoints added alongside. Chat UI and terminal UI coexist until terminal is stable, then chat UI removed.

## Design Decisions

| Decision | Rationale |
|---|---|
| tmux over raw PTY | Full persistence across server restarts; battle-tested scrollback |
| WebSocket over HTTP polling | Real-time terminal I/O; polling adds unacceptable latency for interactive use |
| Binary protocol over JSON | Terminal data is bytes; JSON wrapping adds overhead for no benefit |
| Tabs over floating panels (v1) | Ship faster; floating layout is a v2 enhancement |
| CDN for xterm.js | No build step; consistent with current inline HTML pattern |
| Single MCP connection | Orchestrator gets dispatch + memory tools through one server |
| Hybrid interaction (watch + take control) | Users can observe agents but intervene when needed |
