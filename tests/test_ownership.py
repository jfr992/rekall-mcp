"""Ownership protocol matrix: probe, active-backend staleness, lock, acquire."""

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import pytest


class _StubHandler(http.server.BaseHTTPRequestHandler):
    payload: dict = {}

    def do_GET(self):
        body = json.dumps(self.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextmanager
def _stub_server(payload: dict):
    """Threaded /health stub. Socket is bound in the constructor (before the
    thread starts), so the port answers as soon as we yield; teardown joins."""
    handler = type("Handler", (_StubHandler,), {"payload": payload})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_probe_detects_rekall_signature():
    from core.ownership import probe_daemon

    with _stub_server({"server": "rekall", "version": "x"}) as url:
        assert probe_daemon(url) == "rekall"


def test_probe_flags_foreign_responder():
    from core.ownership import probe_daemon

    with _stub_server({"status": "ok"}) as url:
        assert probe_daemon(url) == "foreign"


def test_probe_absent_when_connection_refused():
    from core.ownership import probe_daemon

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
    # Socket is closed — nothing listens on free_port anymore.
    assert probe_daemon(f"http://127.0.0.1:{free_port}") == "absent"


def test_stale_active_backend_taken_over(tmp_path):
    from core import ownership

    ownership.write_active_backend(tmp_path, "embedded", str(tmp_path / "other-q"))
    state_file = tmp_path / "active-backend.json"
    stale = json.loads(state_file.read_text())
    stale["pid"] = 999999  # beyond macOS/Linux default pid ranges — never alive
    state_file.write_text(json.dumps(stale))

    result = ownership.check_active_backend(tmp_path, "embedded", str(tmp_path / "q"))

    assert result == "stale-taken-over"
    rewritten = json.loads(state_file.read_text())
    assert rewritten["target"] == str(tmp_path / "q")
    assert rewritten["pid"] == os.getpid()


def test_live_mismatch_refused(tmp_path):
    from core import ownership

    with _stub_server({"server": "rekall", "version": "x"}) as url:
        ownership.write_active_backend(tmp_path, "url", url)
        result = ownership.check_active_backend(tmp_path, "embedded", str(tmp_path / "q"))

    assert result == "mismatch"
    # A live owner is never overwritten.
    record = json.loads((tmp_path / "active-backend.json").read_text())
    assert record["backend"] == "url" and record["target"] == url


_LOCK_HOLDER_SCRIPT = """
import sys, time
from qdrant_client import QdrantClient
client = QdrantClient(path=sys.argv[1])
open(sys.argv[2], "w").write("ready")
time.sleep(60)
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_second_locker_gets_clean_error(tmp_path):
    from core import ownership

    qdrant_path = tmp_path / "qdrant"
    sentinel = tmp_path / "holder-ready"
    holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_SCRIPT, str(qdrant_path), str(sentinel)]
    )
    try:
        deadline = time.monotonic() + 10
        while not sentinel.exists():
            assert holder.poll() is None, "lock-holder subprocess died before acquiring"
            assert time.monotonic() < deadline, "lock-holder never signalled ready"
            time.sleep(0.05)
        with pytest.raises(ownership.RekallStoreLockedError, match="rekall serve"):
            ownership.acquire(tmp_path, port=_free_port())
    finally:
        holder.terminate()
        holder.wait(timeout=10)


def test_acquire_embedded_writes_and_cleans_file(tmp_path):
    from core import ownership

    acquisition = ownership.acquire(tmp_path, port=_free_port())

    assert acquisition.mode == "embedded"
    assert acquisition.path == tmp_path / "qdrant"
    state_file = tmp_path / "active-backend.json"
    record = json.loads(state_file.read_text())
    assert record["backend"] == "embedded"
    assert record["target"] == str(tmp_path / "qdrant")
    assert record["pid"] == os.getpid()

    ownership.release(tmp_path)  # the registered atexit handler, called directly
    assert not state_file.exists()


def test_acquire_routes_to_daemon(tmp_path):
    from core import ownership

    with _stub_server({"server": "rekall", "version": "x"}) as url:
        port = int(url.rsplit(":", 1)[1])
        acquisition = ownership.acquire(tmp_path, port=port)

    assert acquisition.mode == "daemon"
    assert acquisition.base_url == url
    # Routing to the daemon takes no lock and records nothing.
    assert not (tmp_path / "active-backend.json").exists()
    assert not (tmp_path / "qdrant").exists()


def test_acquire_refuses_live_backend_mismatch(tmp_path):
    from core import ownership

    with _stub_server({"server": "rekall", "version": "x"}) as live_daemon_url:
        # A live rekall owns the store via an external URL backend; an embedded
        # acquire against the same YAML is the split-brain the protocol prevents.
        ownership.write_active_backend(tmp_path, "url", live_daemon_url)
        with pytest.raises(ownership.RekallDaemonRunningError):
            ownership.acquire(tmp_path, port=_free_port())
