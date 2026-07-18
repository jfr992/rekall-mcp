"""Unified MCP Server with pluggable tools.

This is the main entry point for the MCP server.
Tools are discovered and loaded based on configuration.

Usage:
    # Start with default config (memory tools only)
    python -m server

    # Enable all available tools via environment
    TOOLS_ENABLED=memory python -m server

    # Use a config file
    MCP_CONFIG=tools.yaml python -m server
"""

import asyncio
import logging
import os
import re
import sys
import time
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core import Telemetry
from memory.insights import EVENT_WINDOW
from memory.types import VALID_MEMORY_TYPES
from tools import ToolConfig, ToolLoader, ToolRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def get_config() -> ToolConfig:
    """Load tool configuration.

    Priority:
    1. MCP_CONFIG environment variable (path to YAML)
    2. Default tools.yaml in current directory
    3. Environment variables (TOOLS_ENABLED)
    4. Defaults (memory enabled)
    """
    # Check for config file
    config_path = os.environ.get("MCP_CONFIG")
    if config_path:
        return ToolConfig.from_file(config_path)

    # Check for default config file
    default_config = Path("tools.yaml")
    if default_config.exists():
        return ToolConfig.from_file(default_config)

    # Fall back to environment variables
    return ToolConfig.from_env()


def _initialize_tools() -> ToolRegistry:
    """Discover tools and apply configuration. Single source of truth."""
    config = get_config()
    registry = ToolRegistry.get()
    discovered = registry.discover()

    logger.info(f"Discovered tools: {list(discovered.keys())}")

    for name in discovered:
        if config.is_enabled(name):
            if registry.can_enable(name):
                registry.enable(name)
                logger.info(f"Enabled tool: {name}")
            else:
                logger.warning(f"Cannot enable {name}: missing requirements")
        else:
            registry.disable(name)

    logger.info(f"Enabled tools: {registry.get_enabled()}")
    return registry


@asynccontextmanager
async def app_lifespan(_server: FastMCP) -> AsyncIterator[dict]:
    """Manage application lifecycle."""
    telemetry = Telemetry.get()
    logger.info("Starting MCP server with pluggable tools")

    registry = _initialize_tools()

    yield {"telemetry": telemetry, "registry": registry}

    logger.info("Shutting down MCP server")
    metrics = telemetry.get_metrics()
    total_ops = sum(m.get("count", 0) for m in metrics.get("operations", {}).values())
    logger.info(f"Total operations processed: {total_ops}")


class BearerAuthMiddleware:
    """Optional bearer-token auth for the HTTP server (pure ASGI — does not
    buffer the MCP stream).

    Enabled only when REKALL_API_TOKEN is set. When set, every HTTP request
    except /health must carry `Authorization: Bearer <token>` (constant-time
    compared). Unset → no auth, identical to default behavior.
    """

    OPEN_PATHS = frozenset({"/health"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = os.getenv("REKALL_API_TOKEN")
            if token and scope.get("path", "") not in self.OPEN_PATHS:
                import secrets

                from starlette.responses import JSONResponse

                headers = dict(scope.get("headers") or [])
                provided = headers.get(b"authorization", b"")
                expected = b"Bearer " + token.encode()
                if not secrets.compare_digest(provided, expected):
                    await JSONResponse({"error": "unauthorized"}, status_code=401)(
                        scope, receive, send
                    )
                    return
        await self.app(scope, receive, send)


def _resolve_host() -> str:
    """Default to 127.0.0.1 — Rekall has no auth, so bare metal must not bind
    all interfaces. Docker sets HOST=0.0.0.0 explicitly (compose + Dockerfile)
    because port-mapped / namespaced networks can't reach a loopback-only bind.

    A non-loopback bind is logged loudly: on an untrusted network, keep the
    default or put the server behind a reverse proxy with auth.
    """
    host = os.getenv("HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            f"Binding to {host}: Rekall has no authentication — anyone who can reach "
            "this interface can read and delete memories. Set HOST=127.0.0.1 on untrusted networks."
        )
    return host


# Create the MCP server
# Host defaults to 127.0.0.1; Docker sets HOST=0.0.0.0 for port-mapping.
# stateless_http must be True for Claude Code compatibility.
# Claude Code sends each request independently without session tracking.
mcp = FastMCP(
    "AI Memory & Tools Server",
    lifespan=app_lifespan,
    host=_resolve_host(),
    port=int(os.getenv("PORT", "8000")),
    stateless_http=True,
)


def setup_tools() -> None:
    """Set up tools based on configuration."""
    registry = _initialize_tools()

    loader = ToolLoader(mcp)
    loaded = loader.load_all(registry)

    for provider, tools in loaded.items():
        logger.info(f"Loaded {provider}: {len(tools)} tools")


# Register tools at module load time (skip during testing)
# Check if we're in a test environment
_is_testing = "pytest" in sys.modules or "PYTEST_VERSION" in os.environ
if not _is_testing:
    setup_tools()


# Add server management tools
@mcp.tool(structured_output=False)
async def list_available_tools() -> str:
    """List all available tools and their status.

    Shows which tools are enabled, disabled, and what
    requirements they have.
    """
    registry = ToolRegistry.get()
    discovered = registry.discover()

    output = "# Available Tools\n\n"

    for name, info in discovered.items():
        status = "✅ Enabled" if info["enabled"] else "❌ Disabled"
        output += f"## {name}\n"
        output += f"- **Status**: {status}\n"
        output += f"- **Description**: {info['description']}\n"

        if info["requires"]:
            output += f"- **Requires**: {', '.join(info['requires'])}\n"

        if info["builtin"]:
            output += "- **Type**: Built-in (always available)\n"

        output += "\n"

    return output


@mcp.tool(structured_output=False)
async def get_telemetry_summary() -> str:
    """Get performance telemetry for all operations.

    Shows operation counts, latencies, and success rates
    for all tool operations.
    """
    telemetry = Telemetry.get()
    return telemetry.summary()


_vector_health_cache: dict[str, object] = {"at": 0.0, "value": None}
_VECTOR_HEALTH_TTL_S = 60.0


def _reset_vector_health_cache() -> None:
    _vector_health_cache["at"] = 0.0
    _vector_health_cache["value"] = None


def _vector_health() -> dict[str, int]:
    """Sampled zero-vector check, cached — /health is polled by the cockpit."""
    now = time.monotonic()
    if (
        _vector_health_cache["value"] is None
        or now - _vector_health_cache["at"] > _VECTOR_HEALTH_TTL_S
    ):
        try:
            _vector_health_cache["value"] = _get_memory_manager().vector_health()
        except Exception:
            _vector_health_cache["value"] = {"sampled": 0, "zero_vectors": 0}
        _vector_health_cache["at"] = now
    return _vector_health_cache["value"]


_embedder_health_cache: dict[str, object] = {"at": 0.0, "value": None, "probe": None}
_EMBEDDER_HEALTH_TTL_S = 60.0
_EMBEDDER_PROBE_TIMEOUT_S = 5.0


def _reset_embedder_health_cache() -> None:
    _embedder_health_cache["at"] = 0.0
    _embedder_health_cache["value"] = None
    _embedder_health_cache["probe"] = None


def _embedder_health() -> str | dict[str, str]:
    """Probe the embedder, cached — a broken provider means dead recall (#57).

    First-run encode may load (or download) the model, so the probe runs in a
    worker thread bounded by _EMBEDDER_PROBE_TIMEOUT_S. A timeout is reported
    distinctly and not cached — the still-running probe is re-checked next poll.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    now = time.monotonic()
    if (
        _embedder_health_cache["value"] is not None
        and now - _embedder_health_cache["at"] <= _EMBEDDER_HEALTH_TTL_S
    ):
        return _embedder_health_cache["value"]

    probe = _embedder_health_cache["probe"]
    if probe is None:
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rekall-embedder-probe")
        probe = pool.submit(lambda: _get_memory_manager().embedder.encode("rekall embedder probe"))
        pool.shutdown(wait=False)
        _embedder_health_cache["probe"] = probe
    try:
        probe.result(timeout=_EMBEDDER_PROBE_TIMEOUT_S)
        value: str | dict[str, str] = "ok"
    except FutureTimeoutError:
        return {
            "error": f"timeout: probe still running after {_EMBEDDER_PROBE_TIMEOUT_S:.0f}s "
            "(model load/download in progress?)"
        }
    except Exception as e:
        value = {"error": f"{type(e).__name__}: {e}"}
    _embedder_health_cache["probe"] = None
    _embedder_health_cache["value"] = value
    _embedder_health_cache["at"] = now
    return value


def _rekall_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("rekall-mcp")
    except PackageNotFoundError:
        return "dev"


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint."""
    from starlette.responses import JSONResponse

    registry = ToolRegistry.get()
    enabled = registry.get_enabled()
    vectors = _vector_health()
    embedder = _embedder_health()
    status = "degraded" if vectors["zero_vectors"] > 0 or embedder != "ok" else "healthy"
    return JSONResponse(
        {
            "status": status,
            "server": "rekall",
            "version": _rekall_version(),
            "transport": "streamable-http",
            "tools_enabled": enabled,
            "vectors": vectors,
            "embedder": embedder,
        }
    )


# =============================================================================
# REST API Endpoints for Memory Tools
# =============================================================================


def _get_memory_manager():
    """Process-wide manager shared with the MCP tool path (memory.singleton).

    Two instances = split-brain graphs: edges written via REST were invisible
    to MCP recalls until restart (found by the effectiveness eval 2026-07-07).
    """
    from memory.singleton import get_memory_manager

    return get_memory_manager()


class RequestValidationError(ValueError):
    """Invalid request parameter — mapped to HTTP 400."""


_PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _safe_project(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _PROJECT_RE.match(value):
        raise RequestValidationError(
            "project must be 1-64 characters of letters, digits, dot, dash, underscore"
        )
    return value


def _safe_type(value: str, *, allow_auto: bool = False) -> str:
    if allow_auto and value == "auto":
        return value
    if value not in VALID_MEMORY_TYPES:
        raise RequestValidationError(f"type must be one of {sorted(VALID_MEMORY_TYPES)}")
    return value


def _read_int(query_params, key: str, default: int, lo: int = 1, hi: int = 10000) -> int:
    raw = query_params.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise RequestValidationError(f"{key} must be an integer") from e
    return max(lo, min(value, hi))


_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_day(query_params, key: str) -> str | None:
    raw = query_params.get(key)
    if raw is None:
        return None
    if not _DAY_RE.match(raw):
        raise RequestValidationError(f"{key} must be a YYYY-MM-DD date")
    return raw


def _read_float(query_params, key: str, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
    raw = query_params.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise RequestValidationError(f"{key} must be a number") from e
    return max(lo, min(value, hi))


def _body_int(body: dict, key: str, default: int, lo: int = 0, hi: int = 10000) -> int:
    try:
        value = int(body.get(key, default))
    except (TypeError, ValueError) as e:
        raise RequestValidationError(f"{key} must be an integer") from e
    return max(lo, min(value, hi))


def _parse_graph_filters(query_params) -> dict[str, str | dict[str, str]]:
    filters: dict[str, str | dict[str, str]] = {}

    project = _safe_project(query_params.get("project"))
    if project:
        filters["project"] = project

    mem_type = query_params.get("type")
    if mem_type:
        filters["type"] = mem_type

    # Note: date is stored as a string (YYYY-MM-DD) in Qdrant; Range filter requires
    # numeric fields. Date cutoff is returned separately for post-retrieval filtering.
    days = query_params.get("days")
    filters["_cutoff_date"] = (
        (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d") if days else None
    )

    return filters


# Shared JSON response helpers for the memory-os endpoint family.


def _ok(data: dict):
    from starlette.responses import JSONResponse

    return JSONResponse(data)


def _bad_request(message: str):
    from starlette.responses import JSONResponse

    return JSONResponse({"error": message}, status_code=400)


def _server_error(message: str):
    from starlette.responses import JSONResponse

    return JSONResponse({"error": message}, status_code=500)


# Exclusive maintenance barrier: resparse holds this for its whole transaction,
# so mutation routes (save/observe/delete) queue behind it and land on the new
# vocab generation. Single-process daemon makes an in-process lock sufficient.
# Per-loop because asyncio.Lock binds to the first loop that contends on it.
_maintenance_barriers: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _maintenance_barrier() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _maintenance_barriers.get(loop)
    if lock is None:
        lock = _maintenance_barriers[loop] = asyncio.Lock()
    return lock


@mcp.custom_route("/api/memory/resparse", methods=["POST"])
async def api_memory_resparse(request):
    """REST API: transactional BM25 vocab refit. Maintenance op — REST only, no MCP tool."""
    from memory.resparse import resparse

    try:
        manager = _get_memory_manager()
        async with _maintenance_barrier():
            result = await asyncio.to_thread(resparse, manager)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error running resparse: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/save", methods=["POST"])
async def api_save_memory(request):
    """REST API: Save a memory."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        content = body.get("content")
        mem_type = _safe_type(body.get("type", "note"))
        project = _safe_project(body.get("project"))

        if not content:
            return JSONResponse({"error": "content is required"}, status_code=400)

        manager = _get_memory_manager()
        async with _maintenance_barrier():
            memory_id = manager.save(
                content,
                type=mem_type,
                project=project,
                capture_origin="rest",
                source_tool="rest",
            )

        return JSONResponse({"memory_id": memory_id, "status": "saved", "type": mem_type})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error saving memory: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/recall", methods=["POST"])
async def api_recall_memories(request):
    """REST API: Search memories."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        query = body.get("query")
        limit = _body_int(body, "limit", 5, lo=1, hi=100)
        project = _safe_project(body.get("project"))
        mem_type = body.get("type")
        if mem_type:
            mem_type = _safe_type(mem_type)
        task_hint = body.get("task_hint")
        if task_hint is not None:
            if not isinstance(task_hint, str):
                return JSONResponse({"error": "task_hint must be a string"}, status_code=400)
            task_hint = task_hint[:256]
        # Caller's cwd, not the backend's — attribution only (v1.5.0 scope pitfall)
        caller_cwd = body.get("cwd") or body.get("workspace_root") or None

        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)

        manager = _get_memory_manager()
        results = manager.recall(
            query, limit=limit, project=project, type=mem_type, task_hint=task_hint, cwd=caller_cwd
        )

        # memory_recalled emission lives in manager.recall (event contract v2)
        return JSONResponse({"query": query, "count": len(results), "memories": results})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error recalling memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/recall/cross-project", methods=["POST"])
async def api_cross_project_recall(request):
    """REST API: Search current-project, related-project, and global memories."""
    try:
        body = await request.json()
        raw_query = body.get("query")
        if not isinstance(raw_query, str):
            return _bad_request("query is required")
        query = raw_query.strip()
        current_project = _safe_project(body.get("current_project")) or _safe_project(
            body.get("project")
        )
        limit = _body_int(body, "limit", 8, lo=1, hi=50)

        if not query:
            return _bad_request("query is required")
        if not current_project:
            return _bad_request("current_project is required")

        manager = _get_memory_manager()
        result = manager.recall_cross_project(
            query=query,
            current_project=current_project,
            limit=limit,
        )

        # memory_recalled emission lives in manager.recall (event contract v2)
        return _ok(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error in cross-project recall: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/reflex", methods=["POST"])
async def api_memory_reflex(request):
    """REST API: Build an action-aware reflex recall packet."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return _bad_request("body must be an object")

        raw_text = body.get("text")
        if not isinstance(raw_text, str):
            return _bad_request("text is required")

        text = raw_text.strip()
        project = _safe_project(body.get("project"))
        limit = _body_int(body, "limit", 4, lo=1, hi=12)

        if not text:
            return _bad_request("text is required")

        manager = _get_memory_manager()
        result = manager.reflex(text=text, project=project, limit=limit)

        # memory_recalled emission lives in manager.recall (event contract v2)
        return _ok(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building reflex packet: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/events", methods=["POST"])
async def api_record_events(request):
    """REST API: Append a client-side event (e.g. session_summary) to the event log."""
    _ALLOWED_EVENT_TYPES = frozenset({"session_summary"})

    try:
        body = await request.json()
        if not isinstance(body, dict):
            return _bad_request("body must be an object")

        event_type = body.get("event_type")
        if event_type not in _ALLOWED_EVENT_TYPES:
            return _bad_request(f"event_type must be one of {sorted(_ALLOWED_EVENT_TYPES)}")

        session_id = body.get("session_id")
        project = _safe_project(body.get("project"))
        recalled_ids = body.get("recalled_ids", [])
        edits_after_recall = body.get("edits_after_recall", 0)
        test_passes_after_recall = body.get("test_passes_after_recall", 0)

        if not isinstance(recalled_ids, list) or not all(isinstance(i, str) for i in recalled_ids):
            return _bad_request("recalled_ids must be a list of strings")
        if (
            isinstance(edits_after_recall, bool)
            or not isinstance(edits_after_recall, int)
            or edits_after_recall < 0
        ):
            return _bad_request("edits_after_recall must be a non-negative integer")
        if (
            isinstance(test_passes_after_recall, bool)
            or not isinstance(test_passes_after_recall, int)
            or test_passes_after_recall < 0
        ):
            return _bad_request("test_passes_after_recall must be a non-negative integer")

        manager = _get_memory_manager()
        manager.record_event(
            event_type=event_type,
            project=project or "general",
            memory_ids=recalled_ids,
            source="client",
            payload={
                "session_id": session_id,
                "edits_after_recall": edits_after_recall,
                "test_passes_after_recall": test_passes_after_recall,
            },
        )
        return _ok({"status": "recorded"})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error recording event: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/events", methods=["GET"])
async def api_read_events(request):
    """REST API: Cursor-paginated read of the event log.

    Coexists with POST /api/memory/events (session_summary append) via
    Starlette method routing. No cursor → bounded tail; a rewritten/restored
    log returns truncated=True plus a reset cursor.
    """
    from dataclasses import asdict

    from memory.events import CursorError

    try:
        cursor = request.query_params.get("cursor")
        limit = _read_int(request.query_params, "limit", 100, lo=1, hi=1000)

        manager = _get_memory_manager()
        try:
            events, next_cursor, truncated = manager.event_log.read_from(cursor, limit=limit)
        except CursorError:
            return _bad_request("invalid cursor")

        return _ok(
            {
                "events": [asdict(e) for e in events],
                "cursor": next_cursor,
                "truncated": truncated,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error reading events: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/review", methods=["POST"])
async def api_memory_review(request):
    """REST API: record a review verdict for a memory. Server-only writer.

    keep → record only; kill → delete then record (mutate-then-record);
    fix → 501 until supersede semantics land in U3.
    """
    from starlette.responses import JSONResponse

    from memory import review_state
    from memory.events import MemoryEvent

    try:
        body = await request.json()
        memory_id = body.get("memory_id")
        verdict = body.get("verdict")
        editor = body.get("editor")

        if not memory_id or not isinstance(memory_id, str):
            return _bad_request("memory_id is required")
        if verdict not in ("keep", "fix", "kill"):
            return _bad_request("verdict must be one of ['fix', 'keep', 'kill']")
        if editor not in ("ui", "agent"):
            return _bad_request("editor must be one of ['agent', 'ui']")
        if verdict == "fix":
            return JSONResponse(
                {
                    "error": "verdict=fix is not implemented in U1 — fix means supersede "
                    "(corrected memory + superseded edge), which arrives in U3. "
                    "Use keep or kill for now."
                },
                status_code=501,
            )

        manager = _get_memory_manager()
        found = manager.store.get_many([memory_id])
        if not found:
            return JSONResponse({"error": "not found", "memory_id": memory_id}, status_code=404)
        project = found[0].get("project") or "general"

        if verdict == "kill" and not manager.delete(memory_id):
            return JSONResponse({"error": "not found", "memory_id": memory_id}, status_code=404)

        # Mutate-then-record: the event lands only after the mutation did.
        event_recorded = True
        try:
            manager.event_log.append(
                MemoryEvent(
                    event_type="memory_reviewed",
                    project=project,
                    agent="unknown",
                    source="review_endpoint",
                    payload={
                        "memory_id": memory_id,
                        "verdict": verdict,
                        "editor": editor,
                        "memory_ids": [memory_id],
                        "session_id": None,
                    },
                )
            )
        except Exception:
            event_recorded = False
            logger.error(
                f"memory_reviewed event write FAILED for {memory_id} (verdict={verdict}) "
                "— the mutation stands but audit/projection missed this review",
                exc_info=True,
            )

        if event_recorded:
            try:
                review_state.load(manager.memory_dir)
            except Exception:
                logger.error("review-state projection refresh failed", exc_info=True)

        result = {"memory_id": memory_id, "verdict": verdict, "event_recorded": event_recorded}
        if verdict == "kill":
            result["deleted"] = True
        return _ok(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error recording review: {e}")
        return _server_error(str(e))


# Bounded event tail shared by sessions/insights/stream — 5k events covers
# weeks at current volumes; the cap is surfaced so the UI can say what it
# can't see. One cached snapshot serves all three routes (memory.insights).
_SESSIONS_EVENT_WINDOW = EVENT_WINDOW


def _folded_sessions(limit: int = 50):
    """Fold the shared event snapshot into sessions; returns (sessions, snapshot)."""
    from memory.insights import event_snapshot
    from memory.sessions import fold_sessions

    manager = _get_memory_manager()
    snapshot = event_snapshot(manager.event_log)
    return fold_sessions(list(snapshot.events), limit=limit), snapshot


@mcp.custom_route("/api/memory/sessions", methods=["GET"])
async def api_list_sessions(request):
    """REST API: Session transparency list — U1 events folded into sessions."""
    try:
        limit = _read_int(request.query_params, "limit", 50, lo=1, hi=500)
        project = request.query_params.get("project")
        after = _read_day(request.query_params, "after")
        before = _read_day(request.query_params, "before")
        # Fold the full window, filter, then limit — the recall join needs all
        # events, and a pre-filter limit would starve the scoped list.
        sessions, snapshot = _folded_sessions(limit=_SESSIONS_EVENT_WINDOW)
        if project and project != "all":
            sessions = [s for s in sessions if s["project"] == project]
        # Inclusive day bounds on each session's last activity — string compare
        # on the date part, never a Range on the string date (known pitfall).
        if after is not None:
            sessions = [s for s in sessions if (s["last_at"] or "")[:10] >= after]
        if before is not None:
            sessions = [s for s in sessions if (s["last_at"] or "")[:10] <= before]
        sessions = sessions[:limit]
        # U2 phase metric: server-side hit counter for the transparency view.
        _get_memory_manager().record_event(
            event_type="view_opened",
            project="general",
            source="sessions_view",
            payload={"view": "sessions"},
        )
        rows = [
            {key: s[key] for key in ("session_id", "project", "started_at", "last_at", "totals")}
            for s in sessions
        ]
        # Same honest marker the stream carries, from the snapshot the fold
        # used — taken before the view_opened append above.
        return _ok(
            {
                "sessions": rows,
                "window": _SESSIONS_EVENT_WINDOW,
                "event_window": {"events": len(snapshot.events), "oldest_at": snapshot.oldest_at},
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/sessions/{session_id}", methods=["GET"])
async def api_session_detail(request):
    """REST API: Full session object — injected memories + recall cards."""
    from starlette.responses import JSONResponse

    try:
        session_id = request.path_params["session_id"]
        # Detail lookup must not be blinded by the list limit.
        match = next(
            (
                s
                for s in _folded_sessions(limit=_SESSIONS_EVENT_WINDOW)[0]
                if s["session_id"] == session_id
            ),
            None,
        )
        if match is None:
            return JSONResponse({"error": "not found", "session_id": session_id}, status_code=404)
        return _ok({**match, "window": _SESSIONS_EVENT_WINDOW})
    except Exception as e:
        logger.error(f"Error fetching session detail: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/insights", methods=["GET"])
async def api_memory_insights(request):
    """REST API: cockpit aggregates from one filtered store scroll + the
    shared bounded event tail. Honest numbers only (see memory.insights)."""
    from memory.insights import build_insights, event_snapshot

    try:
        project = _safe_project(request.query_params.get("project"))
        scoped = project not in (None, "all")
        manager = _get_memory_manager()

        records = manager.store.scroll_all(filters={"project": project} if scoped else None)
        try:
            total = int(manager.store.count())
        except Exception:
            total = len(records)

        snapshot = event_snapshot(manager.event_log)
        return _ok(build_insights(records, snapshot, total=total, project=project))
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building insights: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/stream", methods=["GET"])
async def api_memory_stream(request):
    """REST API: newest-first merged activity feed (saved|recalled|promoted|
    consolidated) from memory records + the shared bounded event tail."""
    from memory.insights import build_stream, event_snapshot

    try:
        project = _safe_project(request.query_params.get("project"))
        scoped = project not in (None, "all")
        limit = _read_int(request.query_params, "limit", 50, lo=1, hi=500)
        after = _read_day(request.query_params, "after")
        before = _read_day(request.query_params, "before")
        manager = _get_memory_manager()

        records = manager.store.scroll_all(filters={"project": project} if scoped else None)
        snapshot = event_snapshot(manager.event_log)
        return _ok(
            build_stream(
                records, snapshot, project=project, limit=limit, after=after, before=before
            )
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building stream: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/feedback", methods=["POST"])
async def api_memory_feedback(request):
    """REST API: one-click recall feedback (useful|wrong|stale).

    Labeled evidence only — nothing reads memory_feedback into ranking
    (weights frozen until the 500-pair gate; grep-pinned in tests).
    """
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        memory_id = body.get("memory_id")
        verdict = body.get("verdict")
        session_id = body.get("session_id")

        if not memory_id or not isinstance(memory_id, str):
            return _bad_request("memory_id is required")
        if verdict not in ("useful", "wrong", "stale"):
            return _bad_request("verdict must be one of ['stale', 'useful', 'wrong']")

        manager = _get_memory_manager()
        found = manager.store.get_many([memory_id])
        if not found:
            return JSONResponse({"error": "not found", "memory_id": memory_id}, status_code=404)

        manager.record_event(
            event_type="memory_feedback",
            project=found[0].get("project") or "general",
            memory_ids=[memory_id],
            source="feedback_endpoint",
            session_id=session_id,
            payload={"verdict": verdict, "editor": "ui"},
        )
        return _ok({"recorded": True})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error recording feedback: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/context", methods=["GET"])
async def api_get_context(request):
    """REST API: Get cached context for a project."""
    from starlette.responses import JSONResponse

    try:
        project = _safe_project(request.query_params.get("project")) or "general"

        manager = _get_memory_manager()
        context = manager.get_project_context(project)

        return JSONResponse({"project": project, "context": context})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error getting context: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/smart", methods=["GET"])
async def api_smart_context(request):
    """REST API: Smart, project-aware, token-capped context for session injection.

    Query params:
        project: Filter by project name (optional)
        limit: Max memories to consider (default: 30)
        max_tokens: Token budget (default: 2000)
    """
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 30, lo=1, hi=1000)
        max_tokens = _read_int(query, "max_tokens", 2000, lo=100, hi=20000)

        from memory.smart_context import get_smart_context

        manager = _get_memory_manager()
        result = get_smart_context(manager, project=project, limit=limit, max_tokens=max_tokens)

        return JSONResponse(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building smart context: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/recall/quick", methods=["GET"])
async def api_quick_recall(request):
    """REST API: Fast, high-threshold recall for per-prompt injection.

    Returns at most 2 highly relevant memories. Designed for <100ms response.

    Query params:
        q: Query text (required)
        limit: Max results (default: 2, max: 3)
        threshold: Minimum similarity score (default: 0.7)
    """
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        q = query.get("q", "").strip()
        limit = min(_read_int(query, "limit", 2), 3)
        threshold = _read_float(query, "threshold", 0.7)

        if not q:
            return JSONResponse({"error": "q is required"}, status_code=400)

        manager = _get_memory_manager()
        results = manager.recall(
            query=q,
            limit=limit,
            score_threshold=threshold,
        )

        # Return minimal payload for prompt injection
        memories = [
            {
                "content": r.get("content", ""),
                "type": r.get("type", ""),
                "date": r.get("date", ""),
                "score": r.get("score", 0.0),
            }
            for r in results
        ]

        return JSONResponse({"query": q, "memories": memories, "count": len(memories)})
    except Exception as e:
        logger.error(f"Error in quick recall: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/hierarchy", methods=["GET"])
async def api_get_hierarchical_context(request):
    """REST API: Get topic-grouped context for a project."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 120, lo=1, hi=10000)
        max_topics = _read_int(query, "max_topics", 8, lo=1, hi=100)
        similarity_threshold = _read_float(query, "similarity_threshold", 0.72)

        manager = _get_memory_manager()
        context = manager.get_hierarchical_project_context(
            project=project,
            limit=limit,
            max_topics=max_topics,
            similarity_threshold=similarity_threshold,
        )

        return JSONResponse(
            {
                "project": project or "general",
                "context": context,
                "params": {
                    "limit": limit,
                    "max_topics": max_topics,
                    "similarity_threshold": similarity_threshold,
                },
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error getting hierarchical context: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/stats", methods=["GET"])
async def api_memory_stats(request):
    """REST API: Get memory statistics."""
    from starlette.responses import JSONResponse

    try:
        manager = _get_memory_manager()
        stats = manager.get_stats()

        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/doctor", methods=["GET"])
async def api_memory_doctor(request):
    try:
        project = _safe_project(request.query_params.get("project"))
        manager = _get_memory_manager()
        return _ok(manager.doctor(project=project))
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error running memory doctor: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/{memory_id}", methods=["DELETE"])
async def api_delete_memory(request):
    """REST API: Delete a single memory by ID."""
    from starlette.responses import JSONResponse

    try:
        memory_id = request.path_params["memory_id"]
        if not memory_id:
            return JSONResponse({"error": "memory_id is required"}, status_code=400)

        manager = _get_memory_manager()
        async with _maintenance_barrier():
            deleted = manager.delete(memory_id)

        if not deleted:
            return JSONResponse(
                {"deleted": False, "memory_id": memory_id, "error": "not found"},
                status_code=404,
            )

        return JSONResponse({"deleted": True, "memory_id": memory_id})
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/cleanup", methods=["POST"])
async def api_cleanup_memories(request):
    """REST API: Batch cleanup stale and redundant memories."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        max_age = (
            None
            if body.get("max_age_days_facts") is None
            else _body_int(body, "max_age_days_facts", 0, lo=0, hi=36500)
        )
        result = _get_memory_manager().cleanup(
            max_age_days_facts=max_age,
            prune_superseded=body.get("prune_superseded", False),
            dry_run=body.get("dry_run", False),
        )

        return JSONResponse(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/graph", methods=["GET"])
async def api_memory_graph(request):
    """REST API: Build graph data for memory visualization."""
    from starlette.responses import JSONResponse

    try:
        query_params = request.query_params
        limit = _read_int(query_params, "limit", 120)
        neighbor_count = _read_int(query_params, "neighbor_count", 5)
        min_similarity = _read_float(query_params, "min_similarity", 0.35)

        if limit < 1:
            limit = 1
        if neighbor_count < 1:
            neighbor_count = 1

        filters = _parse_graph_filters(query_params)
        cutoff_date = filters.pop("_cutoff_date", None)

        manager = _get_memory_manager()
        points = manager.store.scroll(
            filters=filters if filters else None, limit=limit, with_vectors=True
        )
        truncated = len(points) >= limit
        if cutoff_date:
            points = [p for p in points if (p.get("date") or "") >= cutoff_date]

        # Local import keeps route tests easy and avoids import-time coupling.
        from memory.graph import build_memory_graph

        graph = build_memory_graph(
            points,
            neighbor_count=neighbor_count,
            min_similarity=min_similarity,
            knowledge_graph=manager.knowledge_graph,
        )

        return JSONResponse(
            {"query": {"limit": limit, "filters": filters}, "graph": graph, "truncated": truncated}
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Error building memory graph: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/publish", methods=["GET", "POST"])
async def api_memory_publish(request):
    """REST API: export memory to an OKF bundle (mode=preview|tar|dir)."""
    import io
    import tarfile
    from pathlib import Path

    from starlette.responses import Response

    from memory.publish import publish_from_manager

    try:
        q = request.query_params
        project = _safe_project(q.get("project"))
        fmt = q.get("format", "okf")
        mode = q.get("mode", "preview")

        manager = _get_memory_manager()
        try:
            bundle = publish_from_manager(manager, project=project, fmt=fmt)
        except ValueError as e:
            return _bad_request(str(e))

        if mode == "preview":
            return _ok({"tree": bundle.tree, "files": bundle.files, "stats": bundle.stats})

        if mode == "tar":
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for path, content in bundle.files.items():
                    data = content.encode()
                    info = tarfile.TarInfo(name=path)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            buf.seek(0)
            return Response(
                buf.read(),
                media_type="application/gzip",
                headers={"Content-Disposition": 'attachment; filename="okf-bundle.tar.gz"'},
            )

        if mode == "dir":
            base = Path(
                os.getenv("REKALL_PUBLISH_DIR", os.path.expanduser("~/.claude/publish"))
            ).resolve()
            dest = q.get("dest")
            if not dest:
                return _bad_request("dest required for mode=dir")
            target = Path(dest).resolve() if os.path.isabs(dest) else (base / dest).resolve()
            if base != target and base not in target.parents:
                return _bad_request("dest must be within REKALL_PUBLISH_DIR")
            tmp = target.with_suffix(".tmp")
            for path, content in bundle.files.items():
                fp = tmp / path
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content)
            if target.exists():
                import shutil

                shutil.rmtree(target)
            tmp.rename(target)
            return _ok({"written": len(bundle.files), "path": str(target)})

        return _bad_request(f"unknown mode: {mode}")
    except Exception as e:
        logger.error(f"Error building publish bundle: {e}")
        return _server_error(str(e))


# In-memory synthesis job registry. Keyed by project; a job warms the synthesis
# cache in a background thread so the async loop is never blocked.
_PUBLISH_JOBS: dict[str, dict] = {}


@mcp.custom_route("/api/memory/publish/synthesize", methods=["POST"])
async def api_memory_publish_synthesize(request):
    """Start (or report) a background synthesis job for a project scope."""
    import threading

    from memory.publish import publish_from_manager

    q = request.query_params
    project = _safe_project(q.get("project")) or ""
    key = project or "__all__"

    job = _PUBLISH_JOBS.get(key)
    if job and job.get("status") == "running":
        return _ok({"status": "running", "done": job["done"], "total": job["total"]})

    _PUBLISH_JOBS[key] = {"status": "running", "done": 0, "total": 0}

    def _run():
        try:
            manager = _get_memory_manager()

            def _progress(done, total):
                _PUBLISH_JOBS[key]["done"] = done
                _PUBLISH_JOBS[key]["total"] = total

            publish_from_manager(
                manager, project=project or None, synthesize=True, progress=_progress
            )
            _PUBLISH_JOBS[key]["status"] = "done"
        except Exception as e:  # noqa: BLE001
            logger.error(f"Synthesis job failed for {key}: {e}")
            _PUBLISH_JOBS[key]["status"] = "error"
            _PUBLISH_JOBS[key]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return _ok({"status": "started"})


@mcp.custom_route("/api/memory/publish/status", methods=["GET"])
async def api_memory_publish_status(request):
    """Poll a synthesis job's progress."""
    q = request.query_params
    project = _safe_project(q.get("project")) or ""
    key = project or "__all__"
    job = _PUBLISH_JOBS.get(key)
    if not job:
        return _ok({"status": "idle"})
    return _ok(job)


@mcp.custom_route("/api/memory/graph/rebuild", methods=["POST"])
async def api_rebuild_memory_graph(_request):
    """REST API: Rebuild the memory knowledge graph."""
    from starlette.responses import JSONResponse

    try:
        manager = _get_memory_manager()
        stats = manager.knowledge_graph.rebuild(
            store=manager.store,
            embedder=manager.embedder,
        )
        return JSONResponse({"status": "rebuilt", **stats})
    except Exception as e:
        logger.error(f"Error rebuilding memory graph: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/consolidate", methods=["GET"])
async def api_consolidate_memories(request):
    """REST API: Return consolidated view of conflicting or superseded memories."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 240, lo=1, hi=10000)
        save_summary_raw = query.get("save_summary", "").lower()
        save_summary = save_summary_raw in {"1", "true", "yes", "on"}

        manager = _get_memory_manager()
        summary = manager.consolidate_memories(
            project=project,
            limit=limit,
            save_summary=save_summary,
        )
        return JSONResponse(
            {
                "project": project or "all",
                "limit": limit,
                "save_summary": save_summary,
                "summary": summary,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error consolidating memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/skills", methods=["GET"])
async def api_skill_context(request):
    """REST API: Get inferred skill context from memory clusters."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        min_mentions = _read_int(query, "min_mentions", 2)
        max_skills = _read_int(query, "max_skills", 8)

        manager = _get_memory_manager()
        summary = manager.get_skill_context(
            project=project,
            min_mentions=min_mentions,
            max_skills=max_skills,
        )
        return JSONResponse(
            {
                "project": project or "all",
                "min_mentions": min_mentions,
                "max_skills": max_skills,
                "summary": summary,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building skill context: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/startup", methods=["GET"])
async def api_agent_startup(request):
    """REST API: Unified startup payload for Claude Code / Codex clients."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        agent = query.get("agent")
        limit = _read_int(query, "limit", 12)
        session_id = query.get("session_id") or None

        manager = _get_memory_manager()
        payload = manager.get_agent_startup(
            project=project, agent=agent, limit=limit, session_id=session_id
        )

        # memory_surfaced emission lives in build_project_capsule (event contract v2)
        return JSONResponse(payload)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building agent startup payload: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/capsule", methods=["GET"])
async def api_project_capsule(request):
    """REST API: Thin project familiarity capsule."""
    try:
        project = _safe_project(request.query_params.get("project")) or "general"
        limit = _read_int(request.query_params, "limit", 300, lo=1, hi=2000)
        session_id = request.query_params.get("session_id") or None
        manager = _get_memory_manager()
        result = manager.get_project_capsule(project=project, limit=limit, session_id=session_id)

        # memory_surfaced emission lives in build_project_capsule (event contract v2)
        return _ok(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building project capsule: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/context/proactive", methods=["GET"])
async def api_proactive_context_summary(request):
    """REST API: Get proactive context summary by relevance."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 120, lo=1, hi=10000)

        manager = _get_memory_manager()
        summary = manager.get_proactive_context_summary(project=project, limit=limit)
        return JSONResponse(
            {
                "project": project or "all",
                "limit": limit,
                "summary": summary,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building proactive context summary: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/compact", methods=["POST"])
async def api_compact_memories(request):
    """REST API: Compact old memories by summarizing groups with an LLM.

    Body (JSON):
        older_than_days: Age threshold in days (default: 30)
        dry_run: Preview without executing (default: true)
        project: Limit to a specific project (optional)
        llm_provider: "anthropic" or "openai" (default: "anthropic")
    """
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        older_than_days = _body_int(body, "older_than_days", 30, lo=1, hi=36500)
        dry_run = bool(body.get("dry_run", True))
        project = _safe_project(body.get("project"))
        llm_provider = body.get("llm_provider", "anthropic")
        if llm_provider not in {"anthropic", "openai"}:
            raise RequestValidationError("llm_provider must be anthropic or openai")

        manager = _get_memory_manager()

        # Load all memories from vector store
        filters = {"project": project} if project else None
        memories = manager.store.scroll(filters=filters, limit=1000)

        from memory.compact import compact_memories

        result = compact_memories(
            memories,
            dry_run=dry_run,
            older_than_days=older_than_days,
            manager=manager if not dry_run else None,
            llm_provider=llm_provider,
            memory_dir=manager.memory_dir if not dry_run else None,
        )

        return JSONResponse(result)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error compacting memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/resume", methods=["GET"])
async def api_memory_resume(request):
    """REST API: Continuity-oriented resume packet, propagating truncated flag."""
    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 12)

        manager = _get_memory_manager()
        packet = manager.get_resume_packet(project=project, limit=limit, all_scopes=project is None)
        return _ok(packet)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building resume packet: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/lifecycle/backfill", methods=["POST"])
async def api_lifecycle_backfill(request):
    """REST API: Backfill tier/durability on existing memories."""
    try:
        body = await request.json()
        dry_run = bool(body.get("dry_run", True))
        project = _safe_project(body.get("project"))

        manager = _get_memory_manager()
        report = manager.backfill_lifecycle(dry_run=dry_run, project=project)
        return _ok(report)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error during lifecycle backfill: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/prune/apply", methods=["POST"])
async def api_memory_prune_apply(request):
    """REST API: Apply a previously-built prune plan. REST ONLY — no MCP tool.

    Requires the body to echo the plan_id as `confirm`.
    """
    from memory.prune import PlanExpired, PlanIdMismatch, PlanNotFound, apply_plan

    try:
        body = await request.json()
        plan_id = body.get("plan_id")
        confirm = body.get("confirm")
        if not plan_id or not confirm:
            return _bad_request("plan_id and confirm are both required")

        manager = _get_memory_manager()
        try:
            result = apply_plan(manager, plan_id=plan_id, confirm_plan_id=confirm)
        except PlanNotFound:
            return _bad_request("plan not found (may have expired or been consumed)")
        except PlanIdMismatch:
            return _bad_request("confirm does not match plan_id")
        except PlanExpired:
            return _bad_request("plan expired")

        return _ok(result)
    except Exception as e:
        logger.error(f"Error applying prune plan: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/prune/plan", methods=["POST"])
async def api_memory_prune_plan(request):
    """REST API: Build a prune plan. Does not delete anything."""
    from memory.prune import build_plan

    try:
        body = await request.json()
        project = _safe_project(body.get("project"))
        if not project:
            return _bad_request("project is required")
        limit = _body_int(body, "limit", 200, lo=1, hi=1000)

        manager = _get_memory_manager()
        plan = build_plan(manager, project=project, limit=limit)
        return _ok(plan.to_dict())
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building prune plan: {e}")
        return _server_error(str(e))


_prune_daily_count: dict[str, int] = {}


def _today_str() -> str:
    from datetime import date

    return date.today().isoformat()


def _prune_backup(out_dir):
    from memory.cli import _do_backup

    return _do_backup(out_dir)


@mcp.custom_route("/api/memory/prune/superseded", methods=["POST"])
async def api_prune_superseded(request):
    """Gated auto-prune of superseded memories. REST-only (destructive)."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()

        # Gate 1: intentionality token
        if body.get("confirm_date") != _today_str():
            return _bad_request("confirm_date must be today's date (intentionality token)")

        from datetime import date

        from memory.prune_superseded import MAX_PER_DAY, MAX_PER_FIRE, build_candidates

        # Gate 2: per-day cap
        today_key = _today_str()
        used = _prune_daily_count.get(today_key, 0)
        if used >= MAX_PER_DAY:
            return JSONResponse(
                {"error": "daily prune cap reached", "daily_remaining": 0}, status_code=429
            )

        # Build candidates via graph edges
        manager = _get_memory_manager()
        graph = manager.knowledge_graph
        edges = list(graph._graph.edges(data=True))

        def get_memory(mid: str):
            hits = manager.store.get_many([mid])
            return hits[0] if hits else None

        candidates = build_candidates(edges, get_memory, date.today())
        if not candidates:
            return _ok({"deleted": [], "message": "no eligible candidates"})

        # Gate 3: dry_run preview
        if body.get("dry_run", False):
            return _ok(
                {
                    "dry_run": True,
                    "candidates": [c.memory_id for c in candidates],
                    "would_delete": len(candidates),
                }
            )

        # Gate 4: per-fire cap
        if len(candidates) > MAX_PER_FIRE:
            from starlette.responses import JSONResponse as _JSONResponse

            return _JSONResponse(
                {
                    "error": f"{len(candidates)} candidates exceeds {MAX_PER_FIRE}/fire cap — review via prune_plan",
                    "candidates": [c.memory_id for c in candidates],
                },
                status_code=400,
            )

        budget = min(MAX_PER_FIRE, MAX_PER_DAY - used)
        candidates = candidates[:budget]

        # Gate 5: backup-first
        from pathlib import Path

        backup_dir = Path.home() / "backups"
        try:
            artifacts = _prune_backup(backup_dir)
        except Exception as e:
            msg = f"backup failed: {e}"
            logger.error(msg)
            return _server_error(msg)

        # Delete and verify
        deleted: list[str] = []
        partially_failed: list[str] = []
        for cand in candidates:
            manager.delete(cand.memory_id)
            still = manager.store.get_many([cand.memory_id])
            if still:
                partially_failed.append(cand.memory_id)
            else:
                deleted.append(cand.memory_id)
                logger.info(f"pruned superseded {cand.memory_id} (by {cand.superseded_by})")

        _prune_daily_count[today_key] = used + len(deleted)

        try:
            manager.record_event(
                event_type="superseded_pruned",
                project="general",
                memory_ids=deleted,
                source="prune_superseded",
            )
        except Exception:
            logger.debug("event emission skipped", exc_info=True)

        return _ok(
            {
                "deleted": deleted,
                "partially_failed": partially_failed,
                "backup": [str(p) for p in artifacts],
                "daily_remaining": MAX_PER_DAY - _prune_daily_count[today_key],
            }
        )
    except Exception as e:
        logger.error(f"Error in superseded prune: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/projects", methods=["GET"])
async def api_memory_projects(_request):
    """REST API: Distinct projects with their memory counts, sorted desc."""
    try:
        manager = _get_memory_manager()
        cap = 5000
        points = manager.store.scroll(limit=cap)
        counts: dict[str, int] = {}
        for p in points:
            project = p.get("project") or "unknown"
            counts[project] = counts.get(project, 0) + 1
        sorted_projects = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return _ok(
            {
                "total": len(points),
                "projects": [{"name": name, "count": n} for name, n in sorted_projects],
                "truncated": len(points) >= cap,
            }
        )
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/pressure", methods=["GET"])
async def api_memory_pressure(request):
    """REST API: Structured memory pressure snapshot."""
    from memory.pressure import identify_pressure

    try:
        query = request.query_params
        project = _safe_project(query.get("project"))

        manager = _get_memory_manager()
        cap = 2000
        filters = {"project": project} if project else None
        memories = manager.store.scroll(filters=filters, limit=cap)
        pressure = identify_pressure(memories)

        total = max(len(memories), 1)
        load_score = round(
            (pressure.get("low_value_count", 0) + pressure.get("stale_working_count", 0)) / total,
            4,
        )

        graph_has_nodes = manager.knowledge_graph.stats()["nodes"] > 0
        conflict: list[dict] = []
        if graph_has_nodes:
            for m in memories:
                mid = m.get("memory_id", "")
                if mid and manager.knowledge_graph.count_contradicts(mid) > 0:
                    conflict.append(m)

        def _slim(items: list[dict]) -> list[dict]:
            return [
                {
                    "memory_id": m.get("memory_id"),
                    "content": (m.get("content") or "")[:160],
                    "type": m.get("type"),
                    "tier": m.get("tier"),
                    "date": m.get("date"),
                }
                for m in items[:50]
            ]

        return _ok(
            {
                "project": project or "all",
                "load_score": load_score,
                "capacity": total,
                "flagged": {
                    "stale_working_count": pressure.get("stale_working_count", 0),
                    "low_value_count": pressure.get("low_value_count", 0),
                    "contradiction_count": len(conflict),
                    "stale_working": _slim(pressure.get("stale_working", [])),
                    "low_value": _slim(pressure.get("low_value", [])),
                    "conflict": _slim(conflict),
                },
                "candidates": pressure.get("candidates", [])[:50],
                "truncated": len(memories) >= cap,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error fetching pressure: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/kb", methods=["GET"])
async def api_memory_kb(request):
    """REST API: Typed semantic slices of the KB.

    Returns four lists: decisions, requirements, preferences, learnings.
    Each item is a summary (no raw content unless ?full=true).
    """
    try:
        query = request.query_params
        project = _safe_project(query.get("project"))
        full = query.get("full", "false").lower() == "true"

        manager = _get_memory_manager()
        cap = 2000
        filters = {"project": project} if project else None
        points = manager.store.scroll(filters=filters, limit=cap)
        # Newest-first within each slice; date is YYYY-MM-DD so string sort works.
        points.sort(key=lambda m: m.get("date") or "", reverse=True)

        def _summarize(m: dict) -> dict:
            out = {
                "memory_id": m.get("memory_id"),
                "type": m.get("type"),
                "tier": m.get("tier"),
                "date": m.get("date"),
                "summary": (m.get("content", "") or "")[:160],
            }
            if full:
                out["content"] = m.get("content")
            return out

        decisions = [_summarize(m) for m in points if m.get("type") == "decision"]
        requirements = [_summarize(m) for m in points if m.get("type") == "requirement"]
        preferences = [_summarize(m) for m in points if m.get("type") == "preference"]
        learnings = [_summarize(m) for m in points if m.get("type") == "learning"]
        # facts is the largest type; note/reference/session folded in so no
        # memory is invisible in the KB view.
        _sliced = {"decision", "requirement", "preference", "learning"}
        facts = [_summarize(m) for m in points if m.get("type") not in _sliced]

        return _ok(
            {
                "project": project or "all",
                "decisions": decisions,
                "requirements": requirements,
                "preferences": preferences,
                "learnings": learnings,
                "facts": facts,
                "truncated": len(points) >= cap,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error fetching kb: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/by-entity", methods=["GET"])
async def api_memory_by_entity(request):
    """REST API: Backlinks — memories whose entities array contains ?entity=."""
    try:
        query = request.query_params
        entity = (query.get("entity") or "").strip()
        if not entity:
            return _bad_request("entity is required")
        project = _safe_project(query.get("project"))
        limit = _read_int(query, "limit", 20, lo=1, hi=100)

        manager = _get_memory_manager()
        memories = manager.find_by_entity(entity, project=project, limit=limit)
        return _ok(
            {
                "entity": entity,
                "project": project or "all",
                "count": len(memories),
                "memories": memories,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error fetching by-entity backlinks: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/detail/{memory_id}", methods=["GET"])
async def api_memory_detail(request):
    """REST API: Enriched single-memory detail (v2).

    Returns memory, neighbors (compat alias), scope (compat alias),
    plus relationships (both directions), provenance, lifecycle, storage, warnings.
    """
    try:
        memory_id = request.path_params["memory_id"]
        current_project = request.query_params.get("current_project") or None
        manager = _get_memory_manager()

        result = manager.get_memory_detail(memory_id, current_project=current_project)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error fetching memory detail: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/observe", methods=["POST"])
async def api_observe(request):
    """REST API: Observe and auto-classify a memory."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        summary = body.get("summary")
        mem_type = _safe_type(body.get("type", "auto"), allow_auto=True)
        context = body.get("context")
        caller_cwd = body.get("cwd") or body.get("workspace_root")
        caller_project = _safe_project(body.get("project"))

        if not summary:
            return JSONResponse({"error": "summary is required"}, status_code=400)

        manager = _get_memory_manager()

        if mem_type == "auto":
            from tools.builtin.memory import _classify_by_embedding, _classify_by_keywords

            try:
                mem_type = _classify_by_embedding(summary, manager.embedder)
            except Exception:
                mem_type = _classify_by_keywords(summary)

        content = summary
        if context:
            content = f"{summary}\n\nContext: {context}"

        # Resolve scope from CALLER'S cwd, not the backend's. Without this,
        # every observation from every Claude session lands under the backend's
        # own repo name (rekall-mcp).
        from memory.scope import ScopeDetector

        scope = ScopeDetector.detect(project=caller_project, cwd=caller_cwd)
        # The observe endpoint's caller is the rekall-observe.sh Stop hook.
        # Old hooks send no session_id/evidence_class -> null (version skew is
        # safe both ways: an old server simply ignores the extra body keys).
        # Unknown evidence_class values also null out — null is honest;
        # null is NEVER coerced to "inferred" downstream.
        evidence_class = body.get("evidence_class")
        if evidence_class not in ("confirmed_artifact", "explicit_user", "inferred"):
            evidence_class = None
        async with _maintenance_barrier():
            memory_id = manager.save(
                content,
                type=mem_type,
                scope=scope,
                capture_origin="hook",
                session_id=body.get("session_id") or None,
                evidence_class=evidence_class,
                source_tool="observe",
                cwd=caller_cwd,
            )

        return JSONResponse(
            {
                "memory_id": memory_id,
                "status": "observed",
                "classified_type": mem_type,
                "project": scope.project,
            }
        )
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error observing: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def build_app():
    """Production ASGI app: MCP at root, custom routes, security middleware.

    Used by main() AND imported by contract tests, so the middleware stack is
    exercised exactly as deployed (SPEC U1 item 5 wiring decision).
    """
    # Serve MCP at root / for Claude Code, include custom routes
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route

    from core.browser_guard import BrowserGuardMiddleware

    original_app = mcp.streamable_http_app()
    mcp_endpoint = original_app.routes[0].endpoint  # StreamableHTTPASGIApp
    session_manager = mcp_endpoint.session_manager

    # Get all custom routes (health, API endpoints)
    custom_routes = [r for r in original_app.routes if r.path != "/mcp"]

    @asynccontextmanager
    async def lifespan(app):
        # session_manager.run() is still needed for task group initialization,
        # but stateless_http=True prevents "Session not found" errors on reconnect
        async with session_manager.run():
            yield

    # Mount MCP at root, plus all custom routes. Optional bearer auth
    # (no-op unless REKALL_API_TOKEN is set) guards everything but /health;
    # the browser guard enforces origin/host rules on state-changing requests.
    routes = [Route("/", endpoint=mcp_endpoint)] + custom_routes
    return Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(BearerAuthMiddleware), Middleware(BrowserGuardMiddleware)],
    )


def main() -> None:
    """Main entry point."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    host = _resolve_host()
    port = int(os.getenv("PORT", "8000"))

    logger.info(f"Starting MCP server with {transport} transport")

    if transport == "streamable-http":
        import uvicorn

        app = build_app()
        if os.getenv("REKALL_API_TOKEN"):
            logger.info("Bearer auth enabled (REKALL_API_TOKEN set) — /health stays open")

        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run(transport="stdio")


def main_stdio() -> None:
    """uvx entry: embedded storage default, eager warmup, stdio transport."""
    rekall_dir = Path(os.environ.get("REKALL_DIR", str(Path.home() / ".rekall"))).expanduser()
    qdrant_url = os.environ.get("QDRANT_URL")
    # QDRANT_URL set = server-backed store; defaulting QDRANT_PATH too would
    # trip the mutual-exclusion guard (mirrors memory/cli.py).
    if not qdrant_url:
        os.environ.setdefault("QDRANT_PATH", str(rekall_dir / "qdrant"))
    # Forced, not setdefault: an inherited streamable-http would leave the MCP
    # client hanging on stdio. `rekall serve` is the explicit HTTP entry.
    os.environ["MCP_TRANSPORT"] = "stdio"
    from core import ownership

    try:
        acq = ownership.acquire(
            rekall_dir, port=int(os.environ.get("PORT", "8000")), qdrant_url=qdrant_url
        )
    except ownership.ForeignServiceError as exc:
        sys.stderr.write(f"rekall: {exc}\n")
        sys.exit(2)
    except ownership.RekallOwnershipError as exc:
        sys.stderr.write(f"rekall: {exc}\n")
        sys.exit(2)
    if acq.mode == "daemon":
        sys.stderr.write(
            "rekall: daemon is running — register with: "
            f"claude mcp add --transport http rekall {acq.base_url}/  (or stop the daemon)\n"
        )
        sys.exit(2)
    # acquire() already wrote active-backend.json (embedded or url backend).
    if acq.mode == "embedded" and acq.client is not None:
        # The acquire-held client IS the store flock — the singleton must reuse it.
        from memory.manager import MemoryManager
        from memory.singleton import set_memory_manager

        set_memory_manager(MemoryManager(qdrant_path=str(acq.path), qdrant_client=acq.client))
    sys.stderr.write("rekall: warming up embedder (first run downloads ~90MB)...\n")
    from memory.singleton import get_memory_manager

    get_memory_manager().embedder.encode("warmup")  # eager, before tools advertised
    sys.stderr.write("rekall: ready\n")
    main()


if __name__ == "__main__":
    main()
