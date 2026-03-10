"""WebSocket-to-PTY terminal relay for tmux sessions."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import select
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
        # Verify tmux session exists before attaching
        check = subprocess.run(
            ["tmux", "has-session", "-t", self.session_id],
            capture_output=True,
        )
        if check.returncode != 0:
            raise RuntimeError(f"tmux session {self.session_id} does not exist")

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
        """Parse incoming WebSocket data. \x01 prefix = resize, else raw input."""
        if data and data[0:1] == b"\x01":
            payload = json.loads(data[1:].decode("utf-8"))
            return True, payload
        return False, data

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY and tmux window."""
        if self._master_fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        # Also resize the tmux window so it matches the PTY
        subprocess.run(
            ["tmux", "resize-window", "-t", self.session_id, "-x", str(cols), "-y", str(rows)],
            capture_output=True,
        )

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
        """Blocking read from master fd with timeout to avoid hanging threads."""
        try:
            # Check if the tmux process died
            if self._process and self._process.poll() is not None:
                return b""
            # Use select with 2s timeout so we never block a thread forever
            ready, _, _ = select.select([self._master_fd], [], [], 2.0)
            if not ready:
                return b"__timeout__"  # sentinel: no data yet, keep looping
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
