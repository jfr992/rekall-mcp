"""Wheel gate: build the wheel, install into a clean venv, drive it over stdio.

mcp 1.26 stdio framing is newline-delimited JSON-RPC (mcp/server/stdio.py reads
`async for line in stdin`, writes `model_dump_json() + "\\n"`) — no Content-Length.

Marked `wheel`: excluded from default runs (pyproject addopts), run explicitly
with `pytest -m wheel` (CI wheel-gate job / local pre-release check).
"""

import json
import os
import select
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.wheel
def test_wheel_installs_and_answers_stdio(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], check=True, cwd=REPO_ROOT)
    venv = tmp_path / "v"
    subprocess.run(["uv", "venv", str(venv)], check=True)
    wheel = next(tmp_path.glob("*.whl"))
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), str(wheel)],
        check=True,
    )

    # Minimal, explicit child env. A full os.environ copy inherits developer/CI
    # state (QDRANT_URL, pytest markers, HOME) and made the smoke behave
    # differently per machine — it once "passed" locally only because the child
    # fell back to whatever listened on :6333.
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "REKALL_DIR": str(tmp_path / "rekall"),
        "QDRANT_PATH": str(tmp_path / "rekall" / "qdrant"),
        "MEMORY_STORAGE_PATH": str(tmp_path / "m"),
        "MCP_TRANSPORT": "stdio",
        "PORT": str(_free_port()),  # a real daemon may own :8000 on dev machines
        # fastembed's default cache is <tempdir>/fastembed_cache — reuse the
        # machine cache (CI exports FASTEMBED_CACHE_PATH) instead of
        # re-downloading the model under the throwaway HOME.
        "FASTEMBED_CACHE_PATH": os.environ.get("FASTEMBED_CACHE_PATH")
        or str(Path(tempfile.gettempdir()) / "fastembed_cache"),
    }
    if os.environ.get("HF_HOME"):
        env["HF_HOME"] = os.environ["HF_HOME"]

    stderr_log = (tmp_path / "server-stderr.log").open("wb")
    # bufsize=0: select() must see exactly what readline() will read (no
    # Python-level buffer hiding bytes from the selector).
    proc = subprocess.Popen(
        [str(venv / "bin" / "rekall-mcp")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_log,
        env=env,
        cwd=str(tmp_path),
        bufsize=0,
    )

    def _send(message: dict) -> None:
        proc.stdin.write((json.dumps(message) + "\n").encode())
        proc.stdin.flush()

    def _readline(timeout: float = 180.0) -> bytes:  # first run downloads the model
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        assert ready, (
            "stdio server produced no output within timeout — stderr:\n"
            + (tmp_path / "server-stderr.log").read_text(errors="replace")[-4000:]
        )
        return proc.stdout.readline()

    try:
        _send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        assert b'"result"' in _readline()

        _send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "save_memory",
                    "arguments": {
                        "content": "wheel smoke: decided to test the wheel",
                        "memory_type": "decision",
                    },
                },
            }
        )
        save_line = _readline()
        assert b'"result"' in save_line and b'"isError":true' not in save_line, save_line

        _send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "recall_memories",
                    "arguments": {"query": "what did we decide about testing the wheel"},
                },
            }
        )
        recall_line = _readline()
        assert b"wheel smoke" in recall_line, recall_line
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        stderr_log.close()
