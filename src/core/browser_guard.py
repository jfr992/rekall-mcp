"""Browser-security middleware for the localhost REST surface (U1 Task 5).

Localhost is not a browser auth boundary: any page in any tab can POST to
127.0.0.1 (CSRF), and DNS rebinding defeats same-origin assumptions once
destructive actions exist. This guard enforces exact-ORIGIN rules (every other
localhost port is same-site, so cross-site checks are useless here):

- State-changing methods (POST/PUT/DELETE/PATCH) carrying browser markers
  (Origin or Sec-Fetch-Site header) must present an allowlisted exact origin
  AND the ``X-Rekall-UI`` header AND ``application/json``, else 403.
- Requests without browser markers (hooks' curl, CLI, MCP clients) pass.
- All requests: Host must be allowlisted, else 421 (DNS-rebinding guard).
- A valid bearer token (re-verified against REKALL_API_TOKEN — the auth
  middleware exposes no state on scope) short-circuits origin rejection.
- GET/HEAD are untouched beyond the Host check.

Pure ASGI — never buffers the MCP stream.
"""

from __future__ import annotations

import os
import secrets

from starlette.responses import JSONResponse

_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_DEFAULT_ORIGINS = frozenset({"http://localhost:3333", "http://127.0.0.1:3333"})
_DEFAULT_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(v.strip() for v in os.getenv(name, "").split(",") if v.strip())


def _host_only(raw: str) -> str:
    """Hostname without port; brackets stripped from IPv6 literals."""
    if raw.startswith("["):
        return raw.split("]", 1)[0].lstrip("[")
    return raw.rsplit(":", 1)[0] if ":" in raw else raw


def _bearer_ok(headers: dict[bytes, bytes]) -> bool:
    token = os.getenv("REKALL_API_TOKEN")
    if not token:
        return False
    provided = headers.get(b"authorization", b"")
    return secrets.compare_digest(provided, b"Bearer " + token.encode())


class BrowserGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])

        host = _host_only(headers.get(b"host", b"").decode("latin-1"))
        if host not in (_DEFAULT_HOSTS | _csv_env("REKALL_ALLOWED_HOSTS")):
            await JSONResponse(
                {"error": f"Host {host!r} not allowed (set REKALL_ALLOWED_HOSTS to extend)"},
                status_code=421,
            )(scope, receive, send)
            return

        if scope.get("method", "").upper() in _MUTATING_METHODS:
            has_browser_markers = b"origin" in headers or b"sec-fetch-site" in headers
            if has_browser_markers and not _bearer_ok(headers):
                origin = headers.get(b"origin", b"").decode("latin-1")
                content_type = (
                    headers.get(b"content-type", b"").decode("latin-1").split(";")[0].strip()
                )
                allowed = origin in (_DEFAULT_ORIGINS | _csv_env("REKALL_UI_ORIGINS"))
                if not (
                    allowed
                    and b"x-rekall-ui" in headers
                    and content_type.lower() == "application/json"
                ):
                    await JSONResponse(
                        {
                            "error": "browser-originated mutation rejected: requires an "
                            "allowlisted Origin (REKALL_UI_ORIGINS), the X-Rekall-UI "
                            "header, and application/json"
                        },
                        status_code=403,
                    )(scope, receive, send)
                    return

        await self.app(scope, receive, send)
