"""Server defaults to 127.0.0.1; Docker sets HOST=0.0.0.0 explicitly in compose."""

import logging


def test_resolve_host_defaults_to_loopback(monkeypatch):
    # Unauthenticated API must not default to all-interfaces on bare metal.
    # Docker deployments set HOST=0.0.0.0 explicitly (docker-compose.yaml / Dockerfile).
    monkeypatch.delenv("HOST", raising=False)
    from server import _resolve_host

    assert _resolve_host() == "127.0.0.1"


def test_resolve_host_warns_on_public_bind(monkeypatch, caplog):
    monkeypatch.setenv("HOST", "0.0.0.0")
    from server import _resolve_host

    with caplog.at_level(logging.WARNING, logger="server"):
        host = _resolve_host()

    assert host == "0.0.0.0"
    assert any("no authentication" in r.message for r in caplog.records)


def test_resolve_host_respects_loopback_override(monkeypatch, caplog):
    monkeypatch.setenv("HOST", "127.0.0.1")
    from server import _resolve_host

    with caplog.at_level(logging.WARNING, logger="server"):
        host = _resolve_host()

    assert host == "127.0.0.1"
    assert not any("no authentication" in r.message for r in caplog.records)
