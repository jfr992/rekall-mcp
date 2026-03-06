# Terminal Orchestra Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the `claude -p` chat orchestrator with real terminal sessions (xterm.js + tmux + WebSocket) so every agent has full skills, tools, and MCP access.

**Architecture:** tmux sessions as the persistence layer, a Python WebSocket relay in the Starlette server, and xterm.js in the browser. Each agent gets its own tmux session, visible as a tab in the dashboard.

**Tech Stack:** tmux, xterm.js (CDN), Starlette WebSocket, Python stdlib pty/fcntl, SQLite for session metadata.

---

## Task 1: Terminal Session Store — SQLite Schema

**Files:**
- Create: `src/tools/builtin/terminal_store.py`
- Test: `tests/test_terminal_store.py`

**Step 1: Write the failing test**

```python
# tests/test_terminal_store.py
"""Tests for terminal session SQLite store."""
import os
import tempfile
from pathlib import Path

import pytest

from tools.builtin.terminal_store import TerminalStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "terminal.db"
    return TerminalStore(db_path=db)


def test_create_session(store):
    session = store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main orchestrator",
        workspace="/tmp/test",
        cli_command="claude --mcp-config '{}'",
    )
    assert session["session_id"] == "jarvis-orch-abc123"
    assert session["type"] == "orchestrator"
    assert session["agent_name"] == "claude"
    assert session["status"] == "running"


def test_list_sessions(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    store.create_session(
        session_id="jarvis-agent-def456",
        session_type="agent-dispatched",
        agent_name="codex",
        task="implement auth",
        workspace="/tmp",
        cli_command="codex",
    )
    sessions = store.list_sessions()
    assert len(sessions) == 2


def test_get_session(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    session = store.get_session("jarvis-orch-abc123")
    assert session is not None
    assert session["agent_name"] == "claude"


def test_update_status(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    store.update_status("jarvis-orch-abc123", "dead")
    session = store.get_session("jarvis-orch-abc123")
    assert session["status"] == "dead"


def test_delete_session(store):
    store.create_session(
        session_id="jarvis-orch-abc123",
        session_type="orchestrator",
        agent_name="claude",
        task="main",
        workspace="/tmp",
        cli_command="claude",
    )
    assert store.delete_session("jarvis-orch-abc123") is True
    assert store.get_session("jarvis-orch-abc123") is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.builtin.terminal_store'`

**Step 3: Write minimal implementation**

```python
# src/tools/builtin/terminal_store.py
"""SQLite-backed terminal session metadata store."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class TerminalStore:
    """Stores terminal session metadata in SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".claude" / "memory" / "terminal.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS terminal_sessions (
                    session_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    task TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    cli_command TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
            """)

    def create_session(
        self,
        session_id: str,
        session_type: str,
        agent_name: str,
        task: str = "",
        workspace: str = "",
        cli_command: str = "",
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO terminal_sessions "
                "(session_id, type, agent_name, task, workspace, status, cli_command, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                (session_id, session_type, agent_name, task, workspace, cli_command, now),
            )
        return {
            "session_id": session_id,
            "type": session_type,
            "agent_name": agent_name,
            "task": task,
            "workspace": workspace,
            "status": "running",
            "cli_command": cli_command,
            "created_at": now,
        }

    def list_sessions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM terminal_sessions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM terminal_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_status(self, session_id: str, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE terminal_sessions SET status = ? WHERE session_id = ?",
                (status, session_id),
            )
        return cur.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM terminal_sessions WHERE session_id = ?",
                (session_id,),
            )
        return cur.rowcount > 0
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_store.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/tools/builtin/terminal_store.py tests/test_terminal_store.py
git commit -m "feat(terminal): add SQLite terminal session store"
```

---

## Task 2: Terminal Manager — tmux Session CRUD

**Files:**
- Create: `src/tools/builtin/terminal_manager.py`
- Test: `tests/test_terminal_manager.py`

**Step 1: Write the failing test**

```python
# tests/test_terminal_manager.py
"""Tests for terminal manager tmux operations."""
from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.builtin.terminal_manager import TerminalManager


@pytest.fixture
def manager(tmp_path):
    return TerminalManager(db_path=tmp_path / "terminal.db")


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro, loop=None):
    if loop is None:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        if loop is not asyncio.get_event_loop():
            pass


class TestCreateSession:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_create_orchestrator_session(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.create_session(
                session_type="orchestrator",
                agent_name="claude",
                workspace="/tmp/test",
                task="main orchestrator",
            )
        )

        assert result["type"] == "orchestrator"
        assert result["session_id"].startswith("jarvis-orch-")
        assert result["status"] == "running"

    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_create_agent_session(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.create_session(
                session_type="agent-dispatched",
                agent_name="codex",
                workspace="/tmp/test",
                task="implement auth TDD",
            )
        )

        assert result["type"] == "agent-dispatched"
        assert result["session_id"].startswith("jarvis-agent-")


class TestListSessions:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_list_returns_all(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            manager.create_session("orchestrator", "claude", "/tmp", "main")
        )
        loop.run_until_complete(
            manager.create_session("agent-dispatched", "codex", "/tmp", "auth")
        )

        result = loop.run_until_complete(manager.list_sessions())
        assert len(result) == 2


class TestCaptureOutput:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_capture_pane_output(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"line1\nline2\nline3\n", b"")
        )
        mock_exec.return_value = mock_proc

        result = asyncio.get_event_loop().run_until_complete(
            manager.capture_output("jarvis-agent-abc123", lines=20)
        )
        assert "line1" in result
        assert "line3" in result


class TestKillSession:
    @patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
    def test_kill_removes_from_store(self, mock_exec, manager):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = mock_proc

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            manager.create_session("orchestrator", "claude", "/tmp", "main")
        )
        session_id = result["session_id"]

        killed = loop.run_until_complete(manager.kill_session(session_id))
        assert killed is True

        sessions = loop.run_until_complete(manager.list_sessions())
        assert len(sessions) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.builtin.terminal_manager'`

**Step 3: Write minimal implementation**

```python
# src/tools/builtin/terminal_manager.py
"""Terminal manager — tmux session CRUD and MCP tool definitions."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from tools.builtin.agent_config import AgentConfigManager
from tools.builtin.terminal_store import TerminalStore


class TerminalManager:
    """Manages tmux-backed terminal sessions for the agent orchestra."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._store = TerminalStore(db_path=db_path)
        self._config = AgentConfigManager()

    def _generate_id(self, session_type: str) -> str:
        short = uuid.uuid4().hex[:6]
        prefix = "orch" if session_type == "orchestrator" else "agent"
        return f"jarvis-{prefix}-{short}"

    def _build_cli_command(
        self, agent_name: str, workspace: str, task: str, mcp_url: str = ""
    ) -> str:
        """Build the CLI command for a given agent."""
        if agent_name == "claude":
            if mcp_url:
                mcp_config = json.dumps(
                    {"memento": {"url": mcp_url, "transport": "streamable-http"}}
                )
                return f"claude --mcp-config '{mcp_config}'"
            return "claude"
        elif agent_name == "codex":
            return f"codex --quiet"
        elif agent_name == "gemini":
            return f"gemini"
        return agent_name

    async def create_session(
        self,
        session_type: str,
        agent_name: str,
        workspace: str,
        task: str = "",
        mcp_url: str = "",
    ) -> dict:
        """Create a new tmux session and store metadata."""
        session_id = self._generate_id(session_type)
        cli_command = self._build_cli_command(agent_name, workspace, task, mcp_url)

        # Create tmux session
        await asyncio.create_subprocess_exec(
            "tmux", "new-session", "-d", "-s", session_id,
            "-c", workspace,
            cli_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        return self._store.create_session(
            session_id=session_id,
            session_type=session_type,
            agent_name=agent_name,
            task=task,
            workspace=workspace,
            cli_command=cli_command,
        )

    async def list_sessions(self) -> list[dict]:
        """List all terminal sessions with current tmux status."""
        return self._store.list_sessions()

    async def capture_output(self, session_id: str, lines: int = 20) -> str:
        """Capture last N lines from a tmux session's pane."""
        proc = await asyncio.create_subprocess_exec(
            "tmux", "capture-pane", "-t", session_id, "-p", "-S", f"-{lines}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip()

    async def kill_session(self, session_id: str) -> bool:
        """Kill a tmux session and remove metadata."""
        await asyncio.create_subprocess_exec(
            "tmux", "kill-session", "-t", session_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self._store.delete_session(session_id)

    async def sync_status(self) -> None:
        """Sync session statuses with tmux reality."""
        proc = await asyncio.create_subprocess_exec(
            "tmux", "list-sessions", "-F", "#{session_name}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        live_sessions = set(stdout.decode().strip().split("\n")) if stdout else set()

        for session in self._store.list_sessions():
            sid = session["session_id"]
            if sid not in live_sessions and session["status"] == "running":
                self._store.update_status(sid, "dead")
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_manager.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/tools/builtin/terminal_manager.py tests/test_terminal_manager.py
git commit -m "feat(terminal): add terminal manager with tmux CRUD"
```

---

## Task 3: MCP Tool Definitions for Orchestrator Dispatch

**Files:**
- Modify: `src/tools/builtin/terminal_manager.py` (add `get_tools()` method)
- Test: `tests/test_terminal_mcp_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_terminal_mcp_tools.py
"""Tests for terminal manager MCP tool definitions."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tools.builtin.terminal_manager import TerminalManager


@pytest.fixture
def manager(tmp_path):
    return TerminalManager(db_path=tmp_path / "terminal.db")


def test_get_tools_returns_four_tools(manager):
    tools = manager.get_tools()
    names = [t.name for t in tools]
    assert "dispatch_agent" in names
    assert "list_agents" in names
    assert "agent_output" in names
    assert "kill_agent" in names
    assert len(tools) == 4


@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
def test_dispatch_agent_tool(mock_exec, manager):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_exec.return_value = mock_proc

    tools = manager.get_tools()
    dispatch = next(t for t in tools if t.name == "dispatch_agent")
    result = asyncio.get_event_loop().run_until_complete(
        dispatch.handler(agent="codex", task="implement auth", workspace="/tmp")
    )
    assert "session_id" in result
    assert result["agent"] == "codex"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_mcp_tools.py -v`
Expected: FAIL with `AttributeError: 'TerminalManager' object has no attribute 'get_tools'`

**Step 3: Add `get_tools()` to TerminalManager**

Append to `src/tools/builtin/terminal_manager.py`:

```python
    def get_tools(self):
        """Return MCP tool definitions for orchestrator dispatch."""
        from tools.base import ToolDefinition

        async def dispatch_agent(agent: str, task: str, workspace: str) -> dict:
            """Spawn a new agent in its own terminal session."""
            result = await self.create_session(
                session_type="agent-dispatched",
                agent_name=agent,
                workspace=workspace,
                task=task,
            )
            return {
                "session_id": result["session_id"],
                "agent": agent,
                "task": task,
                "status": "running",
            }

        async def list_agents() -> list[dict]:
            """List all active terminal sessions and their status."""
            await self.sync_status()
            return await self.list_sessions()

        async def agent_output(session_id: str, lines: int = 20) -> dict:
            """Capture last N lines from an agent's terminal."""
            output = await self.capture_output(session_id, lines)
            return {"session_id": session_id, "output": output}

        async def kill_agent(session_id: str) -> dict:
            """Terminate an agent's terminal session."""
            killed = await self.kill_session(session_id)
            return {"session_id": session_id, "killed": killed}

        return [
            ToolDefinition(
                name="dispatch_agent",
                description="Spawn a new agent terminal session with a task",
                handler=dispatch_agent,
            ),
            ToolDefinition(
                name="list_agents",
                description="List active terminal sessions and their status",
                handler=list_agents,
            ),
            ToolDefinition(
                name="agent_output",
                description="Capture last N lines from an agent's terminal",
                handler=agent_output,
            ),
            ToolDefinition(
                name="kill_agent",
                description="Terminate an agent's terminal session",
                handler=kill_agent,
            ),
        ]
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_mcp_tools.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/tools/builtin/terminal_manager.py tests/test_terminal_mcp_tools.py
git commit -m "feat(terminal): add MCP tool definitions for dispatch/list/output/kill"
```

---

## Task 4: WebSocket Relay — PTY-to-WebSocket Bridge

**Files:**
- Create: `src/terminal_relay.py`
- Test: `tests/test_terminal_relay.py`

**Step 1: Write the failing test**

```python
# tests/test_terminal_relay.py
"""Tests for the WebSocket-to-PTY terminal relay."""
import asyncio
import os
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from terminal_relay import TerminalRelay


class TestTerminalRelay:
    def test_parse_resize_message(self):
        """Resize messages start with \\x01 prefix."""
        relay = TerminalRelay.__new__(TerminalRelay)
        # \x01 + JSON
        msg = b'\x01{"cols":120,"rows":40}'
        is_resize, data = relay._parse_input(msg)
        assert is_resize is True
        assert data["cols"] == 120
        assert data["rows"] == 40

    def test_parse_normal_input(self):
        """Normal input is just raw bytes."""
        relay = TerminalRelay.__new__(TerminalRelay)
        msg = b"ls -la\r"
        is_resize, data = relay._parse_input(msg)
        assert is_resize is False
        assert data == msg
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_relay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'terminal_relay'`

**Step 3: Write minimal implementation**

```python
# src/terminal_relay.py
"""WebSocket-to-PTY terminal relay for tmux sessions."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios
from typing import Any


class TerminalRelay:
    """Bridges a WebSocket connection to a tmux session via PTY."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._master_fd: int | None = None
        self._process: subprocess.Popen | None = None

    async def start(self) -> None:
        """Attach to tmux session via PTY."""
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        self._process = subprocess.Popen(
            ["tmux", "attach", "-t", self.session_id],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)

    def _parse_input(self, data: bytes) -> tuple[bool, Any]:
        """Parse incoming WebSocket data. \\x01 prefix = resize, else raw input."""
        if data and data[0:1] == b"\x01":
            payload = json.loads(data[1:])
            return True, payload
        return False, data

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY and tmux window."""
        if self._master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def write(self, data: bytes) -> None:
        """Write raw bytes to the PTY."""
        if self._master_fd is not None:
            os.write(self._master_fd, data)

    async def read(self) -> bytes:
        """Read available bytes from the PTY (non-blocking via asyncio)."""
        if self._master_fd is None:
            return b""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._blocking_read)

    def _blocking_read(self) -> bytes:
        """Blocking read from master fd."""
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    def stop(self) -> None:
        """Cleanup PTY and process."""
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._process is not None:
            try:
                self._process.terminate()
            except OSError:
                pass
            self._process = None
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_relay.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/terminal_relay.py tests/test_terminal_relay.py
git commit -m "feat(terminal): add PTY-to-WebSocket terminal relay"
```

---

## Task 5: Server Routes — WebSocket + REST Terminal API

**Files:**
- Modify: `src/server.py` (add WebSocket handler + REST routes)

This task adds the server-side WebSocket endpoint and REST API for terminal sessions. The server already uses Starlette which supports WebSocket natively.

**Step 1: Read `src/server.py` around the existing route registration**

Read lines 1-120 and 530-550 to understand how routes are registered and how the app is configured.

**Step 2: Add terminal manager singleton**

Add near line 538 (next to `_get_orchestra()`):

```python
_terminal_manager = None

def _get_terminal_manager():
    global _terminal_manager
    if _terminal_manager is None:
        from tools.builtin.terminal_manager import TerminalManager
        _terminal_manager = TerminalManager()
    return _terminal_manager
```

**Step 3: Add WebSocket route handler**

Add the WebSocket handler for `/api/terminal/{session_id}/ws`:

```python
async def terminal_ws(websocket):
    """WebSocket relay for terminal sessions."""
    from terminal_relay import TerminalRelay

    session_id = websocket.path_params["session_id"]
    await websocket.accept()

    relay = TerminalRelay(session_id)
    try:
        await relay.start()

        async def pty_to_ws():
            while True:
                data = await relay.read()
                if not data:
                    break
                await websocket.send_bytes(data)

        async def ws_to_pty():
            while True:
                data = await websocket.receive_bytes()
                is_resize, payload = relay._parse_input(data)
                if is_resize:
                    relay.resize(payload["cols"], payload["rows"])
                else:
                    relay.write(payload)

        await asyncio.gather(pty_to_ws(), ws_to_pty())
    except Exception:
        pass
    finally:
        relay.stop()
```

**Step 4: Add REST routes for terminal CRUD**

```python
async def terminal_list(request):
    """GET /api/terminal/list — list all terminal sessions."""
    manager = _get_terminal_manager()
    sessions = await manager.list_sessions()
    return JSONResponse(sessions)

async def terminal_create(request):
    """POST /api/terminal/create — create a new terminal session."""
    body = await request.json()
    manager = _get_terminal_manager()
    result = await manager.create_session(
        session_type=body.get("type", "agent-manual"),
        agent_name=body.get("agent", "claude"),
        workspace=body.get("workspace", ""),
        task=body.get("task", ""),
        mcp_url=body.get("mcp_url", ""),
    )
    return JSONResponse(result)

async def terminal_kill(request):
    """POST /api/terminal/{session_id}/kill — kill a terminal session."""
    session_id = request.path_params["session_id"]
    manager = _get_terminal_manager()
    killed = await manager.kill_session(session_id)
    return JSONResponse({"session_id": session_id, "killed": killed})
```

**Step 5: Register routes in the Starlette app**

Add these route registrations alongside the existing `@mcp.custom_route` patterns (or as Starlette routes depending on how the app is built):

```python
# Terminal API routes — add to route list
Route("/api/terminal/list", terminal_list, methods=["GET"]),
Route("/api/terminal/create", terminal_create, methods=["POST"]),
Route("/api/terminal/{session_id}/kill", terminal_kill, methods=["POST"]),
WebSocketRoute("/api/terminal/{session_id}/ws", terminal_ws),
```

**Step 6: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/server.py
git commit -m "feat(terminal): add WebSocket relay and REST API routes"
```

---

## Task 6: Frontend — xterm.js Terminal Tab UI

**Files:**
- Modify: `src/server.py` (HTML/CSS/JS sections)

This task replaces the center chat panel with terminal tabs + xterm.js. The existing dashboard uses inline HTML in `server.py`.

**Step 1: Add xterm.js CDN script tags**

Add to the `<head>` section of the HTML (near existing CSS/JS):

```html
<!-- xterm.js terminal emulator -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css" />
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js"></script>
```

**Step 2: Replace center panel HTML**

Replace the existing chat center panel (lines ~1268-1290 area) with:

```html
<div class="center-panel" id="center-panel">
  <div id="terminal-tabs" class="terminal-tab-bar">
    <div class="tab-list" id="tab-list">
      <!-- tabs rendered by JS -->
    </div>
    <button class="tab-add-btn" onclick="addManualAgent()" title="Add agent">+</button>
  </div>
  <div id="terminal-container" class="terminal-container">
    <!-- xterm.js panes rendered by JS -->
  </div>
  <div id="terminal-status" class="terminal-status-bar">
    <span id="status-text">No sessions</span>
  </div>
</div>
```

**Step 3: Add terminal CSS**

```css
.terminal-tab-bar {
  display: flex;
  align-items: center;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  padding: 4px 8px;
  gap: 4px;
  overflow-x: auto;
}
.terminal-tab-bar .tab-list {
  display: flex;
  gap: 4px;
  flex: 1;
  overflow-x: auto;
}
.terminal-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #16213e;
  border: 1px solid #333;
  border-radius: 6px 6px 0 0;
  color: #a0a0b0;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}
.terminal-tab.active {
  background: #0f3460;
  color: #00d2ff;
  border-color: #00d2ff;
}
.terminal-tab .tab-close {
  opacity: 0.5;
  cursor: pointer;
  font-size: 10px;
}
.terminal-tab .tab-close:hover { opacity: 1; color: #ff4444; }
.terminal-tab .tab-status {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #4caf50;
}
.terminal-tab .tab-status.dead { background: #666; }
.tab-add-btn {
  background: none;
  border: 1px dashed #555;
  color: #888;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
.tab-add-btn:hover { color: #00d2ff; border-color: #00d2ff; }
.terminal-container {
  flex: 1;
  position: relative;
  background: #000;
}
.terminal-pane {
  position: absolute;
  inset: 0;
}
.terminal-pane[hidden] { display: none; }
.terminal-status-bar {
  display: flex;
  align-items: center;
  padding: 4px 12px;
  background: #1a1a2e;
  border-top: 1px solid #333;
  font-size: 11px;
  color: #666;
}
```

**Step 4: Add terminal JavaScript**

```javascript
// Terminal state
const terminals = {};   // session_id -> { term, ws, fitAddon }
let activeTab = null;

function createTerminalPane(sessionId) {
  const container = document.getElementById('terminal-container');
  const pane = document.createElement('div');
  pane.className = 'terminal-pane';
  pane.id = `pane-${sessionId}`;
  pane.dataset.session = sessionId;
  pane.hidden = true;
  container.appendChild(pane);

  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"JetBrains Mono", "Fira Code", monospace',
    theme: { background: '#0a0a1a', foreground: '#e0e0e0', cursor: '#00d2ff' },
  });
  const fitAddon = new FitAddon.FitAddon();
  const webLinksAddon = new WebLinksAddon.WebLinksAddon();
  term.loadAddon(fitAddon);
  term.loadAddon(webLinksAddon);
  term.open(pane);
  fitAddon.fit();

  // WebSocket connection
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/terminal/${sessionId}/ws`);
  ws.binaryType = 'arraybuffer';

  ws.onmessage = (e) => { term.write(new Uint8Array(e.data)); };
  ws.onclose = () => { term.write('\r\n\x1b[33m[session disconnected]\x1b[0m\r\n'); };

  term.onData((data) => { ws.readyState === 1 && ws.send(new TextEncoder().encode(data)); });
  term.onResize(({ cols, rows }) => {
    if (ws.readyState === 1) {
      const msg = new Uint8Array([1, ...new TextEncoder().encode(JSON.stringify({ cols, rows }))]);
      ws.send(msg);
    }
  });

  terminals[sessionId] = { term, ws, fitAddon, pane };
  return terminals[sessionId];
}

function switchTab(sessionId) {
  // Hide current
  if (activeTab && terminals[activeTab]) {
    terminals[activeTab].pane.hidden = true;
    document.querySelector(`.terminal-tab[data-session="${activeTab}"]`)?.classList.remove('active');
  }
  // Show target
  activeTab = sessionId;
  if (terminals[sessionId]) {
    terminals[sessionId].pane.hidden = false;
    terminals[sessionId].fitAddon.fit();
    terminals[sessionId].term.focus();
    document.querySelector(`.terminal-tab[data-session="${sessionId}"]`)?.classList.add('active');
  }
}

function renderTabBar(sessions) {
  const tabList = document.getElementById('tab-list');
  tabList.innerHTML = '';
  sessions.forEach(s => {
    const tab = document.createElement('div');
    tab.className = `terminal-tab${s.session_id === activeTab ? ' active' : ''}`;
    tab.dataset.session = s.session_id;
    tab.onclick = () => switchTab(s.session_id);
    const label = s.type === 'orchestrator' ? 'Orchestrator' : `${s.agent_name}: ${s.task.slice(0, 30)}`;
    tab.innerHTML = `
      <span class="tab-status ${s.status === 'dead' ? 'dead' : ''}"></span>
      <span>${label}</span>
      <span class="tab-close" onclick="event.stopPropagation(); killSession('${s.session_id}')">&times;</span>
    `;
    tabList.appendChild(tab);

    // Create terminal if not yet attached
    if (!terminals[s.session_id]) {
      createTerminalPane(s.session_id);
    }
  });

  // Auto-select first tab if none active
  if (!activeTab && sessions.length > 0) {
    switchTab(sessions[0].session_id);
  }

  // Update status bar
  const running = sessions.filter(s => s.status === 'running').length;
  document.getElementById('status-text').textContent =
    `${sessions.length} session${sessions.length !== 1 ? 's' : ''} | ${running} running`;
}

async function pollSessions() {
  try {
    const resp = await fetch('/api/terminal/list');
    const sessions = await resp.json();
    renderTabBar(sessions);
  } catch (e) { /* silent */ }
}

async function addManualAgent() {
  const agent = prompt('Agent type (claude, codex, gemini):', 'claude');
  if (!agent) return;
  const workspace = document.getElementById('workspace-select')?.value || '/tmp';
  await fetch('/api/terminal/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: 'agent-manual', agent, workspace }),
  });
  pollSessions();
}

async function killSession(sessionId) {
  await fetch(`/api/terminal/${sessionId}/kill`, { method: 'POST' });
  if (terminals[sessionId]) {
    terminals[sessionId].ws.close();
    terminals[sessionId].pane.remove();
    delete terminals[sessionId];
  }
  if (activeTab === sessionId) activeTab = null;
  pollSessions();
}

// Resize handler
window.addEventListener('resize', () => {
  if (activeTab && terminals[activeTab]) {
    terminals[activeTab].fitAddon.fit();
  }
});

// Poll every 5 seconds
setInterval(pollSessions, 5000);
```

**Step 5: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/server.py
git commit -m "feat(terminal): add xterm.js tab UI with WebSocket terminal"
```

---

## Task 7: Orchestrator Auto-Creation on Dashboard Visit

**Files:**
- Modify: `src/server.py` (dashboard route + JS)

**Step 1: Add auto-create orchestrator endpoint**

Add a REST endpoint that creates the orchestrator session if one doesn't exist:

```python
async def terminal_ensure_orchestrator(request):
    """POST /api/terminal/orchestrator — ensure orchestrator session exists."""
    manager = _get_terminal_manager()
    sessions = await manager.list_sessions()
    orch = next((s for s in sessions if s["type"] == "orchestrator" and s["status"] == "running"), None)
    if orch:
        return JSONResponse(orch)

    body = await request.json()
    workspace = body.get("workspace", str(Path.home()))
    mcp_url = body.get("mcp_url", "http://localhost:8002/mcp")
    result = await manager.create_session(
        session_type="orchestrator",
        agent_name="claude",
        workspace=workspace,
        task="main orchestrator",
        mcp_url=mcp_url,
    )
    return JSONResponse(result)
```

Register route:
```python
Route("/api/terminal/orchestrator", terminal_ensure_orchestrator, methods=["POST"]),
```

**Step 2: Add auto-init JS on page load**

Add to the JavaScript section, called on `DOMContentLoaded`:

```javascript
async function initOrchestrator() {
  const workspace = document.getElementById('workspace-select')?.value || '/tmp';
  await fetch('/api/terminal/orchestrator', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace }),
  });
  await pollSessions();
}

document.addEventListener('DOMContentLoaded', () => {
  initOrchestrator();
});
```

**Step 3: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/server.py
git commit -m "feat(terminal): auto-create orchestrator session on dashboard visit"
```

---

## Task 8: Register MCP Tools on Server Startup

**Files:**
- Modify: `src/server.py` (register terminal manager tools alongside existing tools)

**Step 1: Find where existing MCP tools are registered**

Read `server.py` to find where `get_tools()` results are registered with the FastMCP server.

**Step 2: Add terminal manager tool registration**

Add alongside existing tool registration:

```python
# Register terminal dispatch tools
terminal_mgr = _get_terminal_manager()
for tool_def in terminal_mgr.get_tools():
    @mcp.tool(name=tool_def.name, description=tool_def.description)
    async def _handler(**kwargs, _h=tool_def.handler):
        return await _h(**kwargs)
```

**Step 3: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add src/server.py
git commit -m "feat(terminal): register dispatch MCP tools on server startup"
```

---

## Task 9: Integration Test — End-to-End Terminal Flow

**Files:**
- Create: `tests/test_terminal_integration.py`

**Step 1: Write integration test**

```python
# tests/test_terminal_integration.py
"""Integration test for terminal session lifecycle."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tools.builtin.terminal_manager import TerminalManager


@pytest.fixture
def manager(tmp_path):
    return TerminalManager(db_path=tmp_path / "terminal.db")


@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
def test_full_lifecycle(mock_exec, manager):
    """Test CREATE -> LIST -> OUTPUT -> KILL lifecycle."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"test output\n", b""))
    mock_exec.return_value = mock_proc

    loop = asyncio.get_event_loop()

    # CREATE
    session = loop.run_until_complete(
        manager.create_session("orchestrator", "claude", "/tmp", "test")
    )
    sid = session["session_id"]
    assert sid.startswith("jarvis-orch-")

    # LIST
    sessions = loop.run_until_complete(manager.list_sessions())
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == sid

    # OUTPUT
    output = loop.run_until_complete(manager.capture_output(sid, 20))
    assert "test output" in output

    # KILL
    killed = loop.run_until_complete(manager.kill_session(sid))
    assert killed is True

    # VERIFY GONE
    sessions = loop.run_until_complete(manager.list_sessions())
    assert len(sessions) == 0


@patch("tools.builtin.terminal_manager.asyncio.create_subprocess_exec")
def test_dispatch_via_tools(mock_exec, manager):
    """Test dispatching via MCP tool interface."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_exec.return_value = mock_proc

    tools = manager.get_tools()
    dispatch = next(t for t in tools if t.name == "dispatch_agent")
    list_agents = next(t for t in tools if t.name == "list_agents")

    loop = asyncio.get_event_loop()

    # Dispatch
    result = loop.run_until_complete(
        dispatch.handler(agent="codex", task="implement auth", workspace="/tmp")
    )
    assert result["agent"] == "codex"
    assert result["status"] == "running"

    # List
    agents = loop.run_until_complete(list_agents.handler())
    assert len(agents) == 1
    assert agents[0]["agent_name"] == "codex"
```

**Step 2: Run integration tests**

Run: `cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode && python -m pytest tests/test_terminal_integration.py -v`
Expected: 2 passed

**Step 3: Commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add tests/test_terminal_integration.py
git commit -m "test(terminal): add integration test for full session lifecycle"
```

---

## Task 10: Run All Tests and Final Verification

**Step 1: Run the full test suite**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
python -m pytest tests/ -v
```

Expected: All tests pass (test_terminal_store, test_terminal_manager, test_terminal_mcp_tools, test_terminal_relay, test_terminal_integration).

**Step 2: Manual smoke test**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
python -m src.server
# Open http://localhost:8002 in browser
# Verify: orchestrator tab appears, terminal loads, can type in terminal
# Click + to add agent, verify new tab appears
# Kill a session, verify tab removed
```

**Step 3: Final commit**

```bash
cd /Users/jfr9044/.config/superpowers/worktrees/memento-mcp/jarvis-mode
git add -A
git commit -m "feat(terminal): complete terminal orchestra v1 implementation"
```

---

## Summary of New/Modified Files

| File | Action | Purpose |
|------|--------|---------|
| `src/tools/builtin/terminal_store.py` | Create | SQLite session metadata store |
| `src/tools/builtin/terminal_manager.py` | Create | tmux CRUD + MCP tool definitions |
| `src/terminal_relay.py` | Create | PTY-to-WebSocket bridge |
| `src/server.py` | Modify | WebSocket route, REST API, xterm.js UI, auto-orchestrator |
| `tests/test_terminal_store.py` | Create | Store unit tests |
| `tests/test_terminal_manager.py` | Create | Manager unit tests |
| `tests/test_terminal_mcp_tools.py` | Create | MCP tool tests |
| `tests/test_terminal_relay.py` | Create | Relay unit tests |
| `tests/test_terminal_integration.py` | Create | End-to-end lifecycle test |

## What Stays Unchanged

- `src/tools/builtin/agent_config.py` — still defines CLI commands and MCP configs
- `src/tools/builtin/chat_store.py` — kept for backward compat during migration
- `src/tools/builtin/chat_orchestrator.py` — kept until terminal is stable, then removed
- Existing `/api/orchestra/*` endpoints — coexist during migration

## Migration Path

1. Deploy terminal features alongside existing chat UI
2. Verify terminal orchestra works reliably
3. Remove chat orchestrator code (`chat_orchestrator.py`, chat routes, chat UI)
4. Remove `orchestra.py` subprocess-based dispatch
