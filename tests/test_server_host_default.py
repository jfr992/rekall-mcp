"""The server must default to loopback; non-loopback binds must warn loudly."""

import logging


def test_resolve_host_defaults_to_loopback(monkeypatch):
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
