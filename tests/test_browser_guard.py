"""Browser-security middleware: exact-origin rules for state-changing requests (U1 Task 5).

Contract (SPEC U1 item 5): mutations carrying browser markers (Origin or
Sec-Fetch-Site) must present an allowlisted exact origin AND the X-Rekall-UI
header AND application/json, else 403. No markers (hooks/CLI/MCP curl) pass.
All requests: Host allowlist else 421. Valid bearer short-circuits origin
rejection. GET/HEAD untouched.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _app():
    from core.browser_guard import BrowserGuardMiddleware

    async def handler(_request):
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/api/x", handler, methods=["GET", "POST", "PUT", "DELETE", "PATCH"]),
        ],
        middleware=[Middleware(BrowserGuardMiddleware)],
    )


def test_cross_origin_text_plain_post_rejected():
    """The CSRF simulation: a cross-origin form/fetch POST gets a 403 JSON error."""
    client = TestClient(_app())
    r = client.post(
        "/api/x",
        content="x=1",
        headers={"Origin": "http://localhost:9999", "Content-Type": "text/plain"},
    )
    assert r.status_code == 403
    assert "error" in r.json()


def test_allowed_origin_with_ui_header_and_json_passes():
    client = TestClient(_app())
    r = client.post(
        "/api/x",
        json={"a": 1},
        headers={"Origin": "http://localhost:3333", "X-Rekall-UI": "1"},
    )
    assert r.status_code == 200


def test_no_browser_markers_passes():
    """Hooks' curl / CLI / MCP clients send no Origin or Sec-Fetch-Site."""
    client = TestClient(_app())
    r = client.post("/api/x", json={"a": 1})
    assert r.status_code == 200


def test_unlisted_host_gets_421_on_any_method():
    """DNS-rebinding guard: a Host outside the allowlist is misdirected."""
    client = TestClient(_app())
    assert client.get("/api/x", headers={"Host": "evil.example.com"}).status_code == 421
    r = client.post("/api/x", json={"a": 1}, headers={"Host": "evil.example.com:8000"})
    assert r.status_code == 421
    assert "error" in r.json()
