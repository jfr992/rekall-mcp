"""Unified MCP Server with pluggable tools.

This is the main entry point for the MCP server.
Tools are discovered and loaded based on configuration.

Usage:
    # Start with default config (memory tools only)
    python -m server

    # Enable all available tools via environment
    TOOLS_ENABLED=memory,spectro python -m server

    # Use a config file
    MCP_CONFIG=tools.yaml python -m server
"""

import logging
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core import Telemetry
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


def _resolve_host() -> str:
    """Default to loopback. Memento has no auth — non-loopback binds are opt-in and loud."""
    host = os.getenv("HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            f"Binding to {host}: Memento has no authentication — "
            "anyone who can reach this interface can read and delete memories."
        )
    return host


# Create the MCP server
# Host defaults to loopback; Docker sets HOST=0.0.0.0 explicitly (compose line 48).
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


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint."""
    from starlette.responses import JSONResponse

    registry = ToolRegistry.get()
    enabled = registry.get_enabled()
    return JSONResponse(
        {"status": "healthy", "transport": "streamable-http", "tools_enabled": enabled}
    )


# =============================================================================
# REST API Endpoints for Memory Tools
# =============================================================================


_memory_manager_instance = None


def _get_memory_manager():
    """Get or create memory manager singleton for REST API."""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        from memory.manager import MemoryManager

        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance


class RequestValidationError(ValueError):
    """Invalid request parameter — mapped to HTTP 400."""


_PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

VALID_MEMORY_TYPES = frozenset(
    {"decision", "learning", "preference", "requirement", "fact", "note", "session", "summary"}
)


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
        memory_id = manager.save(content, type=mem_type, project=project)

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

        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)

        manager = _get_memory_manager()
        results = manager.recall(query, limit=limit, project=project, type=mem_type)

        return JSONResponse({"query": query, "count": len(results), "memories": results})
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error recalling memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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


@mcp.custom_route("/api/memory/{memory_id}", methods=["DELETE"])
async def api_delete_memory(request):
    """REST API: Delete a single memory by ID."""
    from starlette.responses import JSONResponse

    try:
        memory_id = request.path_params["memory_id"]
        if not memory_id:
            return JSONResponse({"error": "memory_id is required"}, status_code=400)

        manager = _get_memory_manager()
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
            None if body.get("max_age_days_facts") is None
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
        points = manager.store.scroll(filters=filters if filters else None, limit=limit, with_vectors=True)
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

        manager = _get_memory_manager()
        payload = manager.get_agent_startup(project=project, agent=agent, limit=limit)
        return JSONResponse(payload)
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error building agent startup payload: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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
        packet = manager.get_resume_packet(project=project, limit=limit)
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
        return _ok({
            "total": len(points),
            "projects": [{"name": name, "count": n} for name, n in sorted_projects],
            "truncated": len(points) >= cap,
        })
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
        contradiction_count = 0
        if graph_has_nodes:
            for m in memories:
                mid = m.get("memory_id", "")
                if mid and manager.knowledge_graph.count_contradicts(mid) > 0:
                    contradiction_count += 1

        return _ok({
            "project": project or "all",
            "load_score": load_score,
            "capacity": total,
            "flagged": {
                "stale_working_count": pressure.get("stale_working_count", 0),
                "low_value_count": pressure.get("low_value_count", 0),
                "contradiction_count": contradiction_count,
            },
            "candidates": pressure.get("candidates", [])[:50],
            "truncated": len(memories) >= cap,
        })
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

        return _ok({
            "project": project or "all",
            "decisions": decisions,
            "requirements": requirements,
            "preferences": preferences,
            "learnings": learnings,
            "truncated": len(points) >= cap,
        })
    except RequestValidationError as e:
        return _bad_request(str(e))
    except Exception as e:
        logger.error(f"Error fetching kb: {e}")
        return _server_error(str(e))


@mcp.custom_route("/api/memory/detail/{memory_id}", methods=["GET"])
async def api_memory_detail(request):
    """REST API: Get a single memory with its 1-hop graph neighbors."""
    try:
        memory_id = request.path_params["memory_id"]
        manager = _get_memory_manager()

        memory = manager.store.get_by_id(memory_id)
        if not memory:
            return _ok({"memory": None, "neighbors": [], "scope": None})

        graph = manager.knowledge_graph
        neighbors: list[dict] = []
        if graph.stats()["nodes"] > 0:
            for edge in graph.get_edges(memory_id, direction="out"):
                neighbor_payload = manager.store.get_by_id(edge.target)
                if neighbor_payload:
                    neighbors.append({
                        "relation": edge.relation,
                        "memory": neighbor_payload,
                    })

        return _ok({
            "memory": memory,
            "neighbors": neighbors,
            "scope": {
                "project": memory.get("project"),
                "agent": memory.get("agent"),
                "repo_name": memory.get("repo_name"),
            },
        })
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
        # own repo name (memento-mcp).
        from memory.scope import ScopeDetector

        scope = ScopeDetector.detect(project=caller_project, cwd=caller_cwd)
        memory_id = manager.save(content, type=mem_type, scope=scope)

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


def main() -> None:
    """Main entry point."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    host = _resolve_host()
    port = int(os.getenv("PORT", "8000"))

    logger.info(f"Starting MCP server with {transport} transport")

    if transport == "streamable-http":
        # Serve MCP at root / for Claude Code, include custom routes
        from contextlib import asynccontextmanager

        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Route

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

        # Mount MCP at root, plus all custom routes
        routes = [Route("/", endpoint=mcp_endpoint)] + custom_routes
        app = Starlette(routes=routes, lifespan=lifespan)

        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
