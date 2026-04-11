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


# Create the MCP server
# Set host to 0.0.0.0 for Docker container access
# stateless_http must be True for Claude Code compatibility.
# Claude Code sends each request independently without session tracking.
mcp = FastMCP(
    "AI Memory & Tools Server",
    lifespan=app_lifespan,
    host="0.0.0.0",
    port=8000,
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


def _read_int(query_params, key: str, default: int) -> int:
    value = query_params.get(key)
    if value is None:
        return default
    return int(value)


def _read_float(query_params, key: str, default: float) -> float:
    value = query_params.get(key)
    if value is None:
        return default
    return float(value)


def _parse_graph_filters(query_params) -> dict[str, str | dict[str, str]]:
    filters: dict[str, str | dict[str, str]] = {}

    project = query_params.get("project")
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
        mem_type = body.get("type", "note")
        project = body.get("project")

        if not content:
            return JSONResponse({"error": "content is required"}, status_code=400)

        manager = _get_memory_manager()
        memory_id = manager.save(content, type=mem_type, project=project)

        return JSONResponse({"memory_id": memory_id, "status": "saved", "type": mem_type})
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
        limit = body.get("limit", 5)
        project = body.get("project")
        mem_type = body.get("type")

        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)

        manager = _get_memory_manager()
        results = manager.recall(query, limit=limit, project=project, type=mem_type)

        return JSONResponse({"query": query, "count": len(results), "memories": results})
    except Exception as e:
        logger.error(f"Error recalling memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context", methods=["GET"])
async def api_get_context(request):
    """REST API: Get cached context for a project."""
    from starlette.responses import JSONResponse

    try:
        project = request.query_params.get("project") or "general"

        manager = _get_memory_manager()
        context = manager.get_project_context(project)

        return JSONResponse({"project": project, "context": context})
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
        project = query.get("project")
        limit = _read_int(query, "limit", 30)
        max_tokens = _read_int(query, "max_tokens", 2000)

        if limit < 1:
            limit = 1
        if max_tokens < 100:
            max_tokens = 100

        from memory.smart_context import get_smart_context

        manager = _get_memory_manager()
        result = get_smart_context(manager, project=project, limit=limit, max_tokens=max_tokens)

        return JSONResponse(result)
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
        project = query.get("project")
        limit = _read_int(query, "limit", 120)
        max_topics = _read_int(query, "max_topics", 8)
        similarity_threshold = _read_float(query, "similarity_threshold", 0.72)

        if limit < 1:
            limit = 1
        if max_topics < 1:
            max_topics = 1

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
        result = _get_memory_manager().cleanup(
            max_age_days_facts=body.get("max_age_days_facts"),
            prune_superseded=body.get("prune_superseded", False),
            dry_run=body.get("dry_run", False),
        )

        return JSONResponse(result)
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

        return JSONResponse({"query": {"limit": limit, "filters": filters}, "graph": graph})
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
        project = query.get("project")
        limit = _read_int(query, "limit", 240)
        save_summary_raw = query.get("save_summary", "").lower()
        save_summary = save_summary_raw in {"1", "true", "yes", "on"}

        if limit < 1:
            limit = 1

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
    except Exception as e:
        logger.error(f"Error consolidating memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/skills", methods=["GET"])
async def api_skill_context(request):
    """REST API: Get inferred skill context from memory clusters."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = query.get("project")
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
    except Exception as e:
        logger.error(f"Error building skill context: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/startup", methods=["GET"])
async def api_agent_startup(request):
    """REST API: Unified startup payload for Claude Code / Codex clients."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = query.get("project")
        agent = query.get("agent")
        limit = _read_int(query, "limit", 12)

        manager = _get_memory_manager()
        payload = manager.get_agent_startup(project=project, agent=agent, limit=limit)
        return JSONResponse(payload)
    except Exception as e:
        logger.error(f"Error building agent startup payload: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/resume", methods=["GET"])
async def api_resume_packet(request):
    """REST API: Continuity-oriented resume packet for session start."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = query.get("project")
        limit = _read_int(query, "limit", 12)

        manager = _get_memory_manager()
        packet = manager.get_resume_packet(project=project, limit=limit)
        return JSONResponse(packet)
    except Exception as e:
        logger.error(f"Error building resume packet: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/context/proactive", methods=["GET"])
async def api_proactive_context_summary(request):
    """REST API: Get proactive context summary by relevance."""
    from starlette.responses import JSONResponse

    try:
        query = request.query_params
        project = query.get("project")
        limit = _read_int(query, "limit", 120)

        if limit < 1:
            limit = 1

        manager = _get_memory_manager()
        summary = manager.get_proactive_context_summary(project=project, limit=limit)
        return JSONResponse(
            {
                "project": project or "all",
                "limit": limit,
                "summary": summary,
            }
        )
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
        older_than_days = int(body.get("older_than_days", 30))
        dry_run = bool(body.get("dry_run", True))
        project = body.get("project")
        llm_provider = body.get("llm_provider", "anthropic")

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
    except Exception as e:
        logger.error(f"Error compacting memories: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/memory/pressure", methods=["GET"])
async def api_memory_pressure(request):
    """REST API: Structured memory pressure snapshot."""
    from memory.pressure import identify_pressure

    try:
        query = request.query_params
        project = query.get("project")

        manager = _get_memory_manager()
        filters = {"project": project} if project else None
        memories = manager.store.scroll(filters=filters, limit=2000)
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
        })
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
        project = query.get("project")
        full = query.get("full", "false").lower() == "true"

        manager = _get_memory_manager()
        filters = {"project": project} if project else None
        points = manager.store.scroll(filters=filters, limit=2000)

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
        })
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


@mcp.custom_route("/dashboard", methods=["GET"])
async def api_memory_dashboard(_request):
    """Dashboard UI for visualizing memory embeddings."""
    from starlette.responses import HTMLResponse

    html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Memento Memory Brain</title>
    <style>
      :root {
        --bg-1: #0b1020;
        --bg-2: #121935;
        --line: rgba(255, 255, 255, 0.15);
        --accent: #9f7aea;
        --accent-2: #63b3ed;
        --text: #eaf0ff;
      }
      html, body {
        margin: 0;
        height: 100%;
      }
      body {
        font-family: "Space Grotesk", "Manrope", "Fira Sans", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at 15% 10%, #202b58 0%, transparent 40%),
          radial-gradient(circle at 85% 90%, #13263e 0%, transparent 45%),
          linear-gradient(140deg, var(--bg-1), var(--bg-2));
      }
      .shell {
        max-width: 1200px;
        margin: 0 auto;
        padding: 18px;
        box-sizing: border-box;
      }
      h1 { margin: 0 0 12px; }
      .panel {
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(12, 19, 42, 0.5);
        backdrop-filter: blur(10px);
      }
      .controls {
        padding: 12px;
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }
      .controls input,
      .controls select,
      .controls button {
        background: rgba(16, 23, 52, 0.7);
        border: 1px solid var(--line);
        color: var(--text);
        border-radius: 8px;
        padding: 8px 10px;
      }
      .controls button {
        cursor: pointer;
      }
      .controls button:hover { color: #fff; border-color: var(--accent); }
      .grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 12px;
      }
      .card {
        padding: 12px;
      }
      .legend { font-size: 12px; color: #d1d8ff; }
      .legend span { display: inline-block; margin-right: 10px; }
      #brain {
        width: 100%;
        aspect-ratio: 16 / 10;
        border: 1px solid var(--line);
        border-radius: 10px;
        background:
          radial-gradient(circle at 50% 50%, rgba(99, 179, 237, 0.08), transparent 45%);
      }
      #info {
        white-space: pre-wrap;
        max-height: 540px;
        overflow: auto;
        font-size: 13px;
      }
      .muted { color: #8f98bf; }
      @media (max-width: 960px) {
        .grid { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <h1>Memento Memory Brain</h1>
      <div class="panel">
        <div class="controls">
          <label>Project: <input id="project" placeholder="general" /></label>
          <label>Type:
            <select id="memoryType">
              <option value="">all</option>
              <option value="requirement">requirement</option>
              <option value="fact">fact</option>
              <option value="decision">decision</option>
              <option value="preference">preference</option>
              <option value="learning">learning</option>
              <option value="session">session</option>
              <option value="note">note</option>
            </select>
          </label>
          <label>Limit: <input id="limit" type="number" value="160" min="20" max="400" /></label>
          <label>Neighbors: <input id="neighbors" type="number" value="4" min="1" max="12" /></label>
          <label>Min Score: <input id="similarity" type="number" step="0.01" value="0.35" min="0" max="1" /></label>
          <label>Days:
            <select id="days">
              <option value="">all</option>
              <option value="7">7</option>
              <option value="30">30</option>
              <option value="90">90</option>
            </select>
          </label>
          <button id="refresh">Refresh</button>
          <button id="clear">Clear</button>
        </div>
      </div>
      <div style="height: 10px;"></div>
      <div class="grid">
        <div class="panel card">
          <canvas id="brain" width="900" height="560"></canvas>
          <div class="legend">
            <span>🔵 fact</span>
            <span>🟣 preference</span>
            <span>🟠 decision</span>
            <span>🔴 requirement</span>
            <span>🟢 learning</span>
            <span>⚪ note</span>
            <span>⚪ session</span>
          </div>
          <p class="muted" id="status">Loading graph…</p>
        </div>
        <div class="panel card">
          <h3>Memory</h3>
          <div id="info" class="muted">Click a node to inspect memory details.</div>
        </div>
      </div>
    </div>
    <script>
      const colorByType = {
        requirement: "#f56565",
        fact: "#63b3ed",
        decision: "#ed8936",
        preference: "#9f7aea",
        learning: "#48bb78",
        session: "#a0aec0",
        note: "#CBD5E0"
      };

      const state = {
        width: 0,
        height: 0,
        nodes: [],
        links: [],
        selected: null,
      };

      const canvas = document.getElementById("brain");
      const ctx = canvas.getContext("2d");
      const statusEl = document.getElementById("status");
      const infoEl = document.getElementById("info");

      function typeCount(nodes) {
        const byType = {};
        for (const node of nodes) {
          byType[node.type] = (byType[node.type] || 0) + 1;
        }
        return byType;
      }

      function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        const scale = window.devicePixelRatio || 1;
        canvas.width = rect.width * scale;
        canvas.height = rect.height * scale;
        ctx.setTransform(scale, 0, 0, scale, 0, 0);
        state.width = rect.width;
        state.height = rect.height;
      }

      function buildQuery() {
        const project = document.getElementById("project").value.trim();
        const memoryType = document.getElementById("memoryType").value;
        const limit = Number(document.getElementById("limit").value || 160);
        const neighbors = Number(document.getElementById("neighbors").value || 4);
        const similarity = Number(document.getElementById("similarity").value || 0.35);
        const days = document.getElementById("days").value;
        const q = new URLSearchParams({
          limit: String(limit),
          neighbor_count: String(neighbors),
          min_similarity: String(similarity),
        });
        if (project) q.set("project", project);
        if (memoryType) q.set("type", memoryType);
        if (days) q.set("days", days);
        return q.toString();
      }

      function normalizeNodes(dataNodes) {
        return dataNodes.map((n) => {
          const velocity = {x: (Math.random() - 0.5) * 0.5, y: (Math.random() - 0.5) * 0.5};
          const x = (n.position.x + 1) * 0.5 * (state.width - 80) + 40;
          const y = (n.position.y + 1) * 0.5 * (state.height - 80) + 40;
          return {...n, x, y, vx: velocity.x, vy: velocity.y, fx: x, fy: y};
        });
      }

      function loadGraph() {
        statusEl.textContent = "Loading graph…";
        fetch("/api/memory/graph?" + buildQuery())
          .then((res) => res.json())
          .then((payload) => {
            const graph = payload.graph || {};
            const rawNodes = graph.nodes || [];
            const rawLinks = graph.links || [];
            state.nodes = normalizeNodes(rawNodes);
            state.links = rawLinks;
            state.selected = null;
            statusEl.textContent = `Nodes: ${state.nodes.length}, Links: ${state.links.length}`;
            renderInfo();
          })
          .catch((err) => {
            statusEl.textContent = `Failed to load graph: ${err.message}`;
          });
      }

      function renderInfo() {
        if (!state.nodes.length) {
          infoEl.textContent = "No nodes loaded. Try increasing limit or loosening filters.";
          return;
        }
        const total = state.nodes.length;
        const types = typeCount(state.nodes);
        const selected = state.selected
          ? `${state.selected.type} · ${state.selected.date}\n\n${state.selected.content}`
          : "Click a node to inspect memory details.";
        infoEl.textContent =
          `Total nodes: ${total}\n` +
          `Requirements: ${types.requirement || 0}\n` +
          `Facts: ${types.fact || 0}\n` +
          `Decisions: ${types.decision || 0}\n` +
          `Preferences: ${types.preference || 0}\n` +
          `Learnings: ${types.learning || 0}\n\n` +
          selected;
      }

      function stepPhysics() {
        if (!state.nodes.length) {
          requestAnimationFrame(stepPhysics);
          return;
        }

        const linkStrength = 0.0025;
        const damping = 0.85;
        const repulsion = 9000;

        for (let i = 0; i < state.nodes.length; i++) {
          state.nodes[i].vx *= damping;
          state.nodes[i].vy *= damping;
        }

        for (let i = 0; i < state.nodes.length; i++) {
          for (let j = i + 1; j < state.nodes.length; j++) {
            const a = state.nodes[i];
            const b = state.nodes[j];
            const dx = a.x - b.x;
            const dy = a.y - b.y;
            const dist2 = Math.max(80, dx * dx + dy * dy);
            const force = repulsion / dist2;
            const invDist = 1 / Math.sqrt(dist2);
            const fx = force * dx * invDist;
            const fy = force * dy * invDist;
            a.vx += fx * 0.001;
            a.vy += fy * 0.001;
            b.vx -= fx * 0.001;
            b.vy -= fy * 0.001;
          }
        }

        for (const link of state.links) {
          const source = state.nodes.find((n) => n.id === link.source);
          const target = state.nodes.find((n) => n.id === link.target);
          if (!source || !target) continue;

          const dx = target.x - source.x;
          const dy = target.y - source.y;
          const dist = Math.max(20, Math.sqrt(dx * dx + dy * dy));
          const rest = 120 * (1 - link.weight);
          const force = (dist - rest) * linkStrength;
          const nx = dx / dist;
          const ny = dy / dist;
          const fx = force * nx;
          const fy = force * ny;
          source.vx += fx;
          source.vy += fy;
          target.vx -= fx;
          target.vy -= fy;
        }

        for (const node of state.nodes) {
          node.x += node.vx;
          node.y += node.vy;
          node.x = Math.min(state.width - 20, Math.max(20, node.x));
          node.y = Math.min(state.height - 20, Math.max(20, node.y));
        }
      }

      function render() {
        resizeCanvas();
        ctx.clearRect(0, 0, state.width, state.height);
        ctx.save();
        ctx.fillStyle = "rgba(0, 0, 0, 0)";
        ctx.fillRect(0, 0, state.width, state.height);

        for (const link of state.links) {
          const source = state.nodes.find((n) => n.id === link.source);
          const target = state.nodes.find((n) => n.id === link.target);
          if (!source || !target) continue;
          const alpha = Math.min(0.85, Math.max(0.1, link.weight));
          ctx.strokeStyle = `rgba(156, 163, 175, ${alpha})`;
          ctx.lineWidth = 1 + alpha * 2;
          ctx.beginPath();
          ctx.moveTo(source.x, source.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();
        }

        for (const node of state.nodes) {
          const selected = state.selected && state.selected.id === node.id;
          const radius = Math.max(3.5, 3 + Math.min(6, Math.sqrt((node.degree || 0) + 1)));
          const color = colorByType[node.type] || "#a0aec0";
          ctx.beginPath();
          ctx.fillStyle = color;
          ctx.globalAlpha = selected ? 1 : 0.85;
          ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
          ctx.fill();

          if (selected) {
            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
          ctx.globalAlpha = 1;
        }

        ctx.restore();
      }

      function loop() {
        stepPhysics();
        render();
        requestAnimationFrame(loop);
      }

      function pickNode(evt) {
        const bounds = canvas.getBoundingClientRect();
        const x = evt.clientX - bounds.left;
        const y = evt.clientY - bounds.top;
        let closest = null;
        let closestDist = 100000;
        for (const node of state.nodes) {
          const dx = node.x - x;
          const dy = node.y - y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < closestDist && dist < 20) {
            closestDist = dist;
            closest = node;
          }
        }
        if (closest) {
          state.selected = closest;
          renderInfo();
        }
      }

      document.getElementById("refresh").addEventListener("click", () => {
        loadGraph();
      });
      document.getElementById("clear").addEventListener("click", () => {
        document.getElementById("project").value = "";
        document.getElementById("memoryType").value = "";
        document.getElementById("limit").value = "160";
        document.getElementById("neighbors").value = "4";
        document.getElementById("similarity").value = "0.35";
        document.getElementById("days").value = "";
        loadGraph();
      });
      canvas.addEventListener("click", pickNode);
      window.addEventListener("resize", resizeCanvas);

      resizeCanvas();
      loadGraph();
      loop();
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)


@mcp.custom_route("/api/memory/observe", methods=["POST"])
async def api_observe(request):
    """REST API: Observe and auto-classify a memory."""
    from starlette.responses import JSONResponse

    try:
        body = await request.json()
        summary = body.get("summary")
        mem_type = body.get("type", "auto")
        context = body.get("context")

        if not summary:
            return JSONResponse({"error": "summary is required"}, status_code=400)

        manager = _get_memory_manager()

        # Auto-classify if type is "auto"
        if mem_type == "auto":
            from core import Embedder
            from tools.builtin.memory import _classify_by_embedding, _classify_by_keywords

            try:
                embedder = Embedder()
                mem_type = _classify_by_embedding(summary, embedder)
            except Exception:
                mem_type = _classify_by_keywords(summary)

        # Build content with context if provided
        content = summary
        if context:
            content = f"{summary}\n\nContext: {context}"

        memory_id = manager.save(content, type=mem_type)

        return JSONResponse(
            {"memory_id": memory_id, "status": "observed", "classified_type": mem_type}
        )
    except Exception as e:
        logger.error(f"Error observing: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def main() -> None:
    """Main entry point."""
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    host = os.getenv("HOST", "127.0.0.1")
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
