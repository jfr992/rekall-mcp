"""main_stdio (uvx entry): ownership refusals + eager warmup, acquire mocked."""

from pathlib import Path

import pytest

from core.ownership import Acquisition


@pytest.fixture
def stdio_env(monkeypatch, tmp_path):
    """Pin the env keys main_stdio setdefaults so nothing escapes tmp."""
    monkeypatch.setenv("REKALL_DIR", str(tmp_path / "rekall"))
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "rekall" / "qdrant"))
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    return tmp_path


def test_main_stdio_exits_2_when_daemon_running(stdio_env, monkeypatch, capsys):
    import server

    monkeypatch.setattr(
        "core.ownership.acquire",
        lambda *a, **k: Acquisition(mode="daemon", base_url="http://127.0.0.1:8000"),
    )

    with pytest.raises(SystemExit) as exc:
        server.main_stdio()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "daemon is running" in err
    assert "claude mcp add" in err


def test_main_stdio_exits_2_on_foreign_service(stdio_env, monkeypatch, capsys):
    import server
    from core.ownership import ForeignServiceError

    def _raise(*a, **k):
        raise ForeignServiceError("something is serving on http://127.0.0.1:8000 — set PORT.")

    monkeypatch.setattr("core.ownership.acquire", _raise)

    with pytest.raises(SystemExit) as exc:
        server.main_stdio()

    assert exc.value.code == 2
    assert "set PORT" in capsys.readouterr().err


def test_main_stdio_exits_2_on_live_backend_mismatch(stdio_env, monkeypatch, capsys):
    import server
    from core.ownership import RekallDaemonRunningError

    def _raise(*a, **k):
        raise RekallDaemonRunningError("a live rekall owns this store through another backend")

    monkeypatch.setattr("core.ownership.acquire", _raise)

    with pytest.raises(SystemExit) as exc:
        server.main_stdio()

    assert exc.value.code == 2
    assert "owns this store" in capsys.readouterr().err


def test_main_stdio_embedded_warms_up_then_serves(stdio_env, monkeypatch, capsys):
    """Embedded acquisition: eager warmup happens BEFORE main() advertises tools."""
    import server

    calls: list[str] = []
    qdrant_path = Path(stdio_env) / "rekall" / "qdrant"

    monkeypatch.setattr(
        "core.ownership.acquire",
        lambda *a, **k: Acquisition(mode="embedded", path=qdrant_path),
    )

    class _FakeEmbedder:
        def encode(self, text: str) -> list[float]:
            calls.append(f"warmup:{text}")
            return [0.0] * 384

    class _FakeManager:
        embedder = _FakeEmbedder()

    monkeypatch.setattr("memory.singleton.get_memory_manager", lambda: _FakeManager())
    monkeypatch.setattr(server, "main", lambda: calls.append("main"))

    server.main_stdio()

    assert calls == ["warmup:warmup", "main"]
    err = capsys.readouterr().err
    assert "warming up" in err
    assert "ready" in err


def test_main_stdio_qdrant_url_set_skips_path_default(monkeypatch, tmp_path):
    """QDRANT_URL set: no QDRANT_PATH default — both set would trip mutual exclusion."""
    import os

    import server

    rekall_dir = tmp_path / "rekall"
    monkeypatch.setenv("REKALL_DIR", str(rekall_dir))
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6334")
    monkeypatch.delenv("QDRANT_PATH", raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setattr(
        "core.ownership.acquire",
        lambda *a, **k: Acquisition(mode="embedded", path=rekall_dir / "qdrant"),
    )

    class _FakeEmbedder:
        def encode(self, text):
            return [0.0]

    class _FakeManager:
        embedder = _FakeEmbedder()

    monkeypatch.setattr("memory.singleton.get_memory_manager", lambda: _FakeManager())
    monkeypatch.setattr(server, "main", lambda: None)

    server.main_stdio()

    assert "QDRANT_PATH" not in os.environ


def test_main_stdio_defaults_qdrant_path_and_stdio_transport(monkeypatch, tmp_path):
    """With no env set, QDRANT_PATH defaults under REKALL_DIR; setdefault never overrides."""
    import os

    import server

    rekall_dir = tmp_path / "rekall"
    monkeypatch.setenv("REKALL_DIR", str(rekall_dir))
    monkeypatch.delenv("QDRANT_URL", raising=False)  # conftest autouse sets it
    monkeypatch.delenv("QDRANT_PATH", raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")  # setdefault must NOT override
    monkeypatch.setattr(
        "core.ownership.acquire",
        lambda *a, **k: Acquisition(mode="embedded", path=rekall_dir / "qdrant"),
    )

    class _FakeEmbedder:
        def encode(self, text):
            return [0.0]

    class _FakeManager:
        embedder = _FakeEmbedder()

    monkeypatch.setattr("memory.singleton.get_memory_manager", lambda: _FakeManager())
    monkeypatch.setattr(server, "main", lambda: None)

    server.main_stdio()

    assert os.environ["QDRANT_PATH"] == str(rekall_dir / "qdrant")
    assert os.environ["MCP_TRANSPORT"] == "streamable-http"
