"""Disposable Codex-to-Rekall lifecycle smoke across real HTTP/storage boundaries."""

import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "codex" / "setup" / "install.sh"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(url: str, path: str, body: dict[str, object] | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url + path,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.loads(response.read())
    assert isinstance(value, dict)
    return value


def _wait_healthy(process: subprocess.Popen, url: str, log_file: Path) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(log_file.read_text(encoding="utf-8", errors="replace"))
        try:
            if _request(url, "/health").get("status") in {"healthy", "degraded"}:
                return
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(0.2)
    raise AssertionError("disposable Rekall server did not become healthy")


def _install_with_fake_codex(tmp_path: Path, codex_home: Path, mcp_url: str) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "codex"
    fake.write_text(
        """#!/bin/sh
if [ "$1 $2 $3 $4" = "mcp get rekall --json" ]; then
  if [ -f "$FAKE_CODEX_STATE" ]; then
    cat "$FAKE_CODEX_STATE"
    exit 0
  fi
  echo "Error: No MCP server named 'rekall' found." >&2
  exit 1
fi
if [ "$1 $2 $3 $4" = "mcp add rekall --url" ] && [ -n "$5" ]; then
  printf '{"name":"rekall","transport":{"type":"streamable_http","url":"%s"}}\n' \
    "$5" > "$FAKE_CODEX_STATE"
  exit 0
fi
if [ "$1 $2 $3" = "mcp remove rekall" ]; then
  rm -f "$FAKE_CODEX_STATE"
  exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "CODEX_HOME": str(codex_home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "FAKE_CODEX_STATE": str(tmp_path / "fake-codex-state.json"),
        }
    )
    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "--mcp-url", mcp_url],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_disposable_codex_memory_lifecycle(tmp_path):
    codex_home = tmp_path / "codex-home"
    native_memory = codex_home / "memories"
    native_memory.mkdir(parents=True)
    native_sentinel = native_memory / "generated.json"
    native_sentinel.write_text("owned by Codex", encoding="utf-8")
    native_before = (native_sentinel.read_bytes(), native_sentinel.stat().st_mtime_ns)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    _install_with_fake_codex(tmp_path, codex_home, base_url)
    memory_path = tmp_path / "memory"
    qdrant_path = tmp_path / "qdrant"
    project_path = tmp_path / "sentinel-project"
    project_path.mkdir()
    log_path = tmp_path / "server.log"
    env = os.environ.copy()
    for name in ("QDRANT_URL", "REKALL_API_TOKEN"):
        env.pop(name, None)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "MEMORY_STORAGE_PATH": str(memory_path),
            "QDRANT_PATH": str(qdrant_path),
            "REKALL_DIR": str(tmp_path / "rekall-home"),
            "MCP_TRANSPORT": "streamable-http",
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "PYTHONPATH": str(ROOT / "src"),
            "EMBEDDING_PROVIDER": "fastembed",
            "REKALL_REINFORCE": "0",
        }
    )

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "server"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_healthy(process, base_url, log_path)
        summary = (
            "Terraform infrastructure safety rule: create backups before terraform destroy "
            "to prevent data loss incidents and repeat prior failures."
        )
        observed = _request(
            base_url,
            "/api/memory/observe",
            {"summary": summary, "type": "decision", "cwd": str(project_path)},
        )
        memory_id = observed["memory_id"]
        assert observed["project"] == project_path.name

        recalled = _request(
            base_url,
            "/api/memory/recall",
            {
                "query": "terraform destroy backups data loss",
                "project": project_path.name,
                "cwd": str(project_path),
                "limit": 5,
            },
        )
        assert memory_id in {item["memory_id"] for item in recalled["memories"]}

        hook_env = env | {"REKALL_MARKER_DIR": str(tmp_path / "markers")}
        installed_hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
        hook_command = installed_hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        hook = subprocess.run(
            shlex.split(hook_command),
            input=json.dumps(
                {
                    "session_id": "smoke-session",
                    "cwd": str(project_path),
                    "tool_name": "Bash",
                    "tool_input": {"command": "terraform destroy smoke"},
                }
            ),
            env=hook_env,
            capture_output=True,
            text=True,
            check=True,
        )
        packet = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        assert memory_id in packet
        assert len(packet) <= 800
        assert "untrusted" in packet.lower()

        event = _request(
            base_url,
            "/api/memory/events",
            {
                "event_type": "session_summary",
                "session_id": "smoke-session",
                "project": project_path.name,
                "recalled_ids": [memory_id],
                "edits_after_recall": 1,
                "test_passes_after_recall": 1,
            },
        )
        assert event == {"status": "recorded"}
        assert "session_summary" in (memory_path / "_events.jsonl").read_text(encoding="utf-8")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert (native_sentinel.read_bytes(), native_sentinel.stat().st_mtime_ns) == native_before
    inspected = "\n".join(
        (
            log_path.read_text(encoding="utf-8", errors="replace"),
            (codex_home / "hooks.json").read_text(encoding="utf-8"),
        )
    )
    for production_reference in ("localhost:6333", "/.Codex/memory", "/.codex/memories"):
        assert production_reference not in inspected
