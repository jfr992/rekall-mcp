"""Optional bearer-token auth: off by default, enforced when REKALL_API_TOKEN is set."""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _app():
    from server import BearerAuthMiddleware

    async def health(_request):
        return JSONResponse({"status": "healthy"})

    async def protected(_request):
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/api/memory/stats", protected),
        ],
        middleware=[Middleware(BearerAuthMiddleware)],
    )


def test_no_token_env_means_no_auth(monkeypatch):
    monkeypatch.delenv("REKALL_API_TOKEN", raising=False)
    client = TestClient(_app())
    assert client.get("/api/memory/stats").status_code == 200
    assert client.get("/health").status_code == 200


def test_token_set_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("REKALL_API_TOKEN", "s3cret")
    client = TestClient(_app())
    assert client.get("/api/memory/stats").status_code == 401


def test_token_set_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("REKALL_API_TOKEN", "s3cret")
    client = TestClient(_app())
    r = client.get("/api/memory/stats", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_token_set_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("REKALL_API_TOKEN", "s3cret")
    client = TestClient(_app())
    r = client.get("/api/memory/stats", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_health_open_even_with_token(monkeypatch):
    monkeypatch.setenv("REKALL_API_TOKEN", "s3cret")
    client = TestClient(_app())
    assert client.get("/health").status_code == 200
