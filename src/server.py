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
# stateless_http=True eliminates session management, preventing "Session not found"
# errors when Claude Code reconnects after context compaction or session resume.
# This is safe because we don't use elicitation or sampling features.
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
@mcp.tool()
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


@mcp.tool()
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
        import traceback
        logger.error(f"Error building memory graph: {e}\n{traceback.format_exc()}")
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


# --- Tracker API ---

# Shared instances for REST handlers
_tracker = None
_briefing = None
_orchestra = None
_chat_history: list[dict] = []


def _get_tracker():
    global _tracker
    if _tracker is None:
        from tools.builtin.tracker import TrackerTools
        _tracker = TrackerTools()
    return _tracker


def _get_briefing():
    global _briefing
    if _briefing is None:
        from tools.builtin.briefing import BriefingTools
        _briefing = BriefingTools()
    return _briefing


def _get_orchestra():
    global _orchestra
    if _orchestra is None:
        from tools.builtin.orchestra import AgentOrchestraTools
        _orchestra = AgentOrchestraTools()
    return _orchestra


def _get_workspace_roots() -> list[str]:
    """Load workspace roots from config or defaults."""
    config_path = Path.home() / ".memento" / "dashboard.json"
    if config_path.exists():
        import json

        try:
            with open(config_path) as f:
                config = json.load(f)
            return config.get("workspace_roots", [])
        except Exception:
            logger.debug("Failed to parse workspace config; using defaults", exc_info=True)

    return ["~/Repos", "~/scripts", "~/.config/superpowers/worktrees"]


@mcp.custom_route("/api/tracker/items", methods=["GET"])
async def _handle_get_pending(request):
    """GET /api/tracker/items - List pending items."""
    from starlette.responses import JSONResponse

    tracker = _get_tracker()
    overdue = request.query_params.get("overdue", "false").lower() == "true"
    result = await tracker._get_pending(overdue=overdue)
    return JSONResponse({"result": result})


@mcp.custom_route("/api/tracker/items", methods=["POST"])
async def _handle_track_item(request):
    """POST /api/tracker/items - Track a new item."""
    from starlette.responses import JSONResponse

    body = await request.json()
    tracker = _get_tracker()
    result = await tracker._track_item(
        title=body["title"],
        due_date=body.get("due_date"),
        context=body.get("context"),
        ticket_id=body.get("ticket_id"),
        priority=body.get("priority", "normal"),
    )
    return JSONResponse({"result": result})


@mcp.custom_route("/api/tracker/items/{item_id}/complete", methods=["POST"])
async def _handle_complete_item(request):
    """POST /api/tracker/items/{item_id}/complete - Complete an item."""
    from starlette.responses import JSONResponse

    tracker = _get_tracker()
    item_id = request.path_params["item_id"]
    result = await tracker._complete_item(item_id)
    return JSONResponse({"result": result})


@mcp.custom_route("/api/tracker/items/{item_id}/defer", methods=["POST"])
async def _handle_defer_item(request):
    """POST /api/tracker/items/{item_id}/defer - Defer an item."""
    from starlette.responses import JSONResponse

    tracker = _get_tracker()
    item_id = request.path_params["item_id"]
    body = await request.json()
    result = await tracker._defer_item(item_id, body["new_date"])
    return JSONResponse({"result": result})


# --- Briefing API ---


@mcp.custom_route("/api/briefing/session", methods=["GET"])
async def _handle_session_briefing(request):
    """GET /api/briefing/session - Quick session briefing."""
    from starlette.responses import JSONResponse

    briefing = _get_briefing()
    project = request.query_params.get("project")
    result = await briefing._session_briefing(project=project)
    return JSONResponse({"result": result})


@mcp.custom_route("/api/briefing/daily", methods=["GET"])
async def _handle_daily_briefing(request):
    """GET /api/briefing/daily - Full daily briefing."""
    from starlette.responses import JSONResponse

    briefing = _get_briefing()
    project = request.query_params.get("project")
    result = await briefing._daily_briefing(project=project)
    return JSONResponse({"result": result})


@mcp.custom_route("/api/orchestra/dispatch", methods=["POST"])
async def _handle_orchestra_dispatch(request):
    """POST /api/orchestra/dispatch - Dispatch a task to an AI agent."""
    from starlette.responses import JSONResponse

    orchestra = _get_orchestra()
    body = await request.json()
    result = await orchestra._dispatch_task(
        task=body["task"],
        agent=body.get("agent"),
        working_dir=body.get("working_dir", ""),
        context=body.get("context", ""),
    )
    return JSONResponse({"result": result})


@mcp.custom_route("/api/orchestra/status", methods=["GET"])
async def _handle_orchestra_status(request):
    """GET /api/orchestra/status - Show all agent runs."""
    from starlette.responses import JSONResponse

    orchestra = _get_orchestra()
    status_filter = request.query_params.get("status")
    result = await orchestra._agent_status(status=status_filter)
    return JSONResponse({"result": result})


@mcp.custom_route("/api/orchestra/runs/{run_id}/review", methods=["POST"])
async def _handle_orchestra_review(request):
    """POST /api/orchestra/runs/{run_id}/review - Review an agent run."""
    from starlette.responses import JSONResponse

    orchestra = _get_orchestra()
    run_id = request.path_params["run_id"]

    body = {}
    if request.headers.get("content-length", "0") != "0":
        body = await request.json()
    result = await orchestra._review_result(
        run_id=run_id,
        action=body.get("action"),
        feedback=body.get("feedback", ""),
    )
    return JSONResponse({"result": result})


@mcp.custom_route("/api/workspaces", methods=["GET"])
async def _handle_workspaces(_request):
    """GET /api/workspaces - List available workspaces (git repos)."""
    from starlette.responses import JSONResponse
    from tools.builtin.workspaces import WorkspaceScanner

    scanner = WorkspaceScanner(roots=_get_workspace_roots())
    workspaces = scanner.scan()
    return JSONResponse({"workspaces": workspaces})


@mcp.custom_route("/api/orchestra/chat", methods=["POST"])
async def _handle_orchestra_chat(request):
    """POST /api/orchestra/chat - Send message to orchestrator."""
    from starlette.responses import JSONResponse
    from tools.builtin.chat_orchestrator import ChatOrchestrator

    body = await request.json()
    message = body.get("message", "")
    workspace = body.get("workspace", "")
    history = body.get("history", [])

    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    orchestrator = ChatOrchestrator()
    result = await orchestrator.handle_chat(
        message=message,
        workspace=workspace,
        history=history,
    )

    _chat_history.append({"role": "user", "content": message})
    _chat_history.append({"role": "assistant", "content": result["message"]})

    return JSONResponse(result)


@mcp.custom_route("/api/orchestra/chat/history", methods=["GET"])
async def _handle_chat_history(request):
    """GET /api/orchestra/chat/history - Retrieve chat message history."""
    from starlette.responses import JSONResponse

    limit = _read_int(request.query_params, "limit", 100)
    return JSONResponse({"messages": _chat_history[-limit:]})


@mcp.custom_route("/api/orchestra/runs/{run_id}/output", methods=["GET"])
async def _handle_run_output(request):
    """GET /api/orchestra/runs/{run_id}/output - Get run output."""
    from starlette.responses import JSONResponse

    orchestra = _get_orchestra()
    run_id = request.path_params["run_id"]

    if run_id not in orchestra._runs:
        return JSONResponse({"error": f"Unknown run: {run_id}"}, status_code=404)

    run = orchestra._runs[run_id]
    return JSONResponse(
        {
            "run_id": run.run_id,
            "agent": run.agent,
            "task": run.task,
            "status": run.status.value,
            "output": run.output,
            "error": run.error,
        }
    )


@mcp.custom_route("/api/config", methods=["GET"])
async def _handle_get_config(request):
    """GET /api/config - Return current agent and MCP configs."""
    from starlette.responses import JSONResponse
    from tools.builtin.agent_config import AgentConfigManager

    del request
    manager = AgentConfigManager()
    return JSONResponse(
        {
            "agents": manager.get_all_configs(),
            "workspace_roots": _get_workspace_roots(),
        }
    )


@mcp.custom_route("/api/config", methods=["PUT"])
async def _handle_put_config(request):
    """PUT /api/config - Update agent configs."""
    from starlette.responses import JSONResponse
    from tools.builtin.agent_config import AgentConfigManager

    body = await request.json()
    manager = AgentConfigManager()

    if "agents" in body:
        for agent_name, config in body["agents"].items():
            manager.save_config(agent_name, config)

    return JSONResponse({"status": "updated"})


@mcp.custom_route("/dashboard", methods=["GET"])
async def api_memory_dashboard(_request):
    """Dashboard UI for visualizing memory embeddings."""
    from starlette.responses import HTMLResponse

    html = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MEMENTO // Command</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Anybody:wght@400;700;900&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080a0f;
  --surface:#0d1117;
  --surface-2:#131922;
  --border:#1e2a3a;
  --border-hi:#2d4a6f;
  --text:#c9d6e3;
  --text-dim:#5a6b7f;
  --text-bright:#e8f0fa;
  --cyan:#00d4aa;
  --cyan-dim:rgba(0,212,170,0.15);
  --amber:#f0a030;
  --amber-dim:rgba(240,160,48,0.12);
  --red:#ff4d4d;
  --red-dim:rgba(255,77,77,0.12);
  --blue:#4d9fff;
  --purple:#a78bfa;
  --green:#34d399;
  --orange:#fb923c;
  --mono:"JetBrains Mono",ui-monospace,monospace;
  --display:"Anybody","JetBrains Mono",monospace;
}
html,body{height:100%;overflow:hidden}
body{
  font-family:var(--mono);font-size:12px;color:var(--text);
  background:var(--bg);
  background-image:
    repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,212,170,0.008) 2px,rgba(0,212,170,0.008) 3px);
}
/* --- GRAIN OVERLAY --- */
body::before{
  content:'';position:fixed;top:0;left:0;width:100%;height:100%;
  pointer-events:none;z-index:9999;opacity:0.03;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
/* --- PANEL REVEAL --- */
@keyframes panelReveal{
  from{opacity:0;transform:translateY(8px)}
  to{opacity:1;transform:translateY(0)}
}
@keyframes shimmer{
  0%{background-position:-200% 0}
  100%{background-position:200% 0}
}
.panel,.center{animation:panelReveal 0.4s ease-out both}
.panel:nth-child(1){animation-delay:0.05s}
.center{animation-delay:0.15s}
.panel:nth-child(3){animation-delay:0.25s}

/* --- LAYOUT --- */
.hud{display:grid;height:100vh;grid-template-rows:42px 1fr;grid-template-columns:1fr;overflow:hidden}
.topbar{
  display:flex;align-items:center;justify-content:space-between;
  padding:0 16px;border-bottom:1px solid var(--border);
  background:var(--surface);position:relative;
}
.topbar-left{display:flex;align-items:center;gap:16px}
.logo{font-family:var(--display);font-weight:900;font-size:15px;letter-spacing:3px;color:var(--cyan);text-transform:uppercase}
.logo span{color:var(--text-dim);font-weight:400;letter-spacing:1px;font-size:11px;margin-left:8px}
.clock{font-size:11px;color:var(--text-dim);letter-spacing:1px}
.topbar-right{display:flex;align-items:center;gap:12px}
.topbar::after{
  content:'';position:absolute;bottom:0;left:0;width:100%;height:1px;
  background:linear-gradient(90deg,transparent 0%,var(--cyan) 30%,var(--cyan) 70%,transparent 100%);
  opacity:0.4;
}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.status-label{font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1.5px}

.main{display:grid;grid-template-columns:320px 1fr 340px;grid-template-rows:1fr;overflow:hidden}

/* --- PANELS --- */
.panel{
  border-right:1px solid var(--border);overflow:hidden;
  display:flex;flex-direction:column;
}
.panel:last-child{border-right:none}
.panel-head{
  padding:10px 14px;border-bottom:1px solid var(--border);
  background:var(--surface);
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;
}
.panel-title{
  font-family:var(--display);font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:2px;color:var(--text-dim);
}
.panel-badge{
  font-size:9px;padding:2px 7px;border-radius:3px;
  background:var(--cyan-dim);color:var(--cyan);font-weight:500;
  letter-spacing:0.5px;
}
.panel-badge.warn{background:var(--amber-dim);color:var(--amber)}
.panel-badge.crit{background:var(--red-dim);color:var(--red)}
.panel-body{flex:1;overflow-y:auto;padding:10px 14px}
.panel-body::-webkit-scrollbar{width:4px}
.panel-body::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* --- TRACKER --- */
.tracker-section{margin-bottom:14px}
.tracker-section-title{
  font-size:9px;text-transform:uppercase;letter-spacing:1.5px;
  color:var(--text-dim);margin-bottom:6px;padding-bottom:4px;
  border-bottom:1px solid var(--border);
}
.tracker-item{
  padding:8px 10px;margin-bottom:4px;border-radius:4px;
  background:var(--surface-2);border-left:3px solid var(--border);
  transition:border-color 0.15s,background 0.15s;
  cursor:default;
}
.tracker-item:hover{background:rgba(0,212,170,0.04);border-left-color:var(--cyan)}
.tracker-item.overdue{border-left-color:var(--red);background:var(--red-dim)}
.tracker-item.high{border-left-color:var(--amber)}
.tracker-item-id{font-size:9px;color:var(--text-dim);letter-spacing:0.5px}
.tracker-item-title{font-size:12px;color:var(--text-bright);margin:2px 0}
.tracker-item-meta{font-size:10px;color:var(--text-dim);display:flex;gap:8px;flex-wrap:wrap}
.tracker-item-meta .tag{
  padding:1px 5px;border-radius:2px;font-size:9px;
  background:var(--surface);border:1px solid var(--border);
}
.tracker-item-meta .tag.ticket{color:var(--blue);border-color:rgba(77,159,255,0.3)}
.tracker-item-meta .tag.due{color:var(--amber);border-color:rgba(240,160,48,0.3)}
.tracker-item-meta .tag.overdue{color:var(--red);border-color:rgba(255,77,77,0.3)}
.tracker-empty{color:var(--text-dim);font-style:italic;padding:20px 0;text-align:center;font-size:11px}
.tracker-item-actions{
  display:none;gap:4px;margin-top:5px;
}
.tracker-item:hover .tracker-item-actions{display:flex}
.tracker-action{
  padding:2px 8px;font-size:9px;font-family:var(--mono);
  border:1px solid var(--border);border-radius:2px;
  background:var(--surface);color:var(--text-dim);
  cursor:pointer;text-transform:uppercase;letter-spacing:0.5px;
  transition:all 0.15s;
}
.tracker-action:hover{border-color:var(--cyan);color:var(--cyan)}
.tracker-action.complete:hover{border-color:var(--green);color:var(--green)}
.tracker-action.defer:hover{border-color:var(--amber);color:var(--amber)}
/* skeleton loader */
.skeleton{
  background:linear-gradient(90deg,var(--surface-2) 25%,var(--border) 50%,var(--surface-2) 75%);
  background-size:200% 100%;animation:shimmer 1.5s infinite;
  border-radius:3px;height:42px;margin-bottom:4px;
}
/* glow on selected node info */
.memory-detail.has-selection{
  border-color:rgba(0,212,170,0.3);
  box-shadow:0 0 20px rgba(0,212,170,0.05),inset 0 0 20px rgba(0,212,170,0.02);
}

/* --- TRACK FORM --- */
.track-form{
  padding:10px 14px;border-top:1px solid var(--border);
  background:var(--surface);flex-shrink:0;
}
.track-form input,.track-form select{
  width:100%;padding:6px 8px;margin-bottom:4px;
  background:var(--surface-2);border:1px solid var(--border);
  color:var(--text);font-family:var(--mono);font-size:11px;
  border-radius:3px;outline:none;
}
.track-form input:focus,.track-form select:focus{border-color:var(--cyan)}
.track-form .row{display:flex;gap:4px}
.track-form .row>*{flex:1}
.track-btn{
  width:100%;padding:6px;margin-top:4px;cursor:pointer;
  background:var(--cyan-dim);color:var(--cyan);
  border:1px solid rgba(0,212,170,0.3);border-radius:3px;
  font-family:var(--mono);font-size:10px;font-weight:500;
  text-transform:uppercase;letter-spacing:1.5px;
  transition:background 0.15s;
}
.track-btn:hover{background:rgba(0,212,170,0.25)}

/* --- CENTER: BRAIN --- */
.center{display:flex;flex-direction:column;overflow:hidden;background:var(--bg)}
.brain-controls{
  padding:8px 14px;border-bottom:1px solid var(--border);
  display:flex;flex-wrap:wrap;gap:6px;align-items:center;
  background:var(--surface);flex-shrink:0;
}
.brain-controls label{font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px}
.brain-controls input,.brain-controls select{
  background:var(--surface-2);border:1px solid var(--border);
  color:var(--text);font-family:var(--mono);font-size:10px;
  padding:4px 6px;border-radius:3px;outline:none;
}
.brain-controls input:focus,.brain-controls select:focus{border-color:var(--cyan)}
.brain-controls input[type="number"]{width:50px}
.brain-controls button{
  padding:4px 10px;cursor:pointer;font-family:var(--mono);font-size:10px;
  background:var(--surface-2);border:1px solid var(--border);
  color:var(--text);border-radius:3px;text-transform:uppercase;letter-spacing:1px;
  transition:border-color 0.15s;
}
.brain-controls button:hover{border-color:var(--cyan);color:var(--cyan)}
.brain-wrap{flex:1;position:relative;overflow:hidden}
#brain{width:100%;height:100%;display:block}
.brain-status{
  position:absolute;bottom:8px;left:14px;
  font-size:10px;color:var(--text-dim);letter-spacing:0.5px;
}
.brain-legend{
  position:absolute;bottom:8px;right:14px;
  display:flex;gap:10px;font-size:10px;
}
.brain-legend .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle}

/* --- RIGHT PANEL --- */
.briefing-section{margin-bottom:16px}
.briefing-section-title{
  font-size:9px;text-transform:uppercase;letter-spacing:1.5px;
  color:var(--text-dim);margin-bottom:8px;padding-bottom:4px;
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
}
.briefing-item{
  padding:6px 8px;margin-bottom:3px;border-radius:3px;
  background:var(--surface-2);font-size:11px;line-height:1.5;
}
.briefing-item .type-tag{
  display:inline-block;font-size:8px;padding:1px 4px;border-radius:2px;
  text-transform:uppercase;letter-spacing:0.5px;margin-right:4px;
  vertical-align:middle;
}
.briefing-item .type-tag.decision{background:rgba(251,146,60,0.15);color:var(--orange)}
.briefing-item .type-tag.learning{background:rgba(52,211,153,0.15);color:var(--green)}
.briefing-item .type-tag.requirement{background:rgba(255,77,77,0.15);color:var(--red)}
.briefing-item .type-tag.fact{background:rgba(77,159,255,0.15);color:var(--blue)}

.orchestra-output{
  white-space:pre-wrap;
  font-size:11px;
  line-height:1.4;
  color:var(--text-dim);
  padding:8px;
  background:var(--surface-2);
  border:1px solid var(--border);
  border-radius:3px;
  min-height:120px;
  max-height:180px;
  overflow:auto;
}

.orchestra-controls{
  display:flex;
  gap:6px;
  margin-bottom:8px;
}

.orchestra-controls button{
  font-size:9px;
  padding:2px 8px;
  background:var(--surface-2);
  border:1px solid var(--border);
  color:var(--text-dim);
  border-radius:3px;
  cursor:pointer;
  font-family:var(--mono);
  letter-spacing:1px;
}

/* --- CHAT --- */
.chat-messages{display:flex;flex-direction:column;gap:8px;}
.chat-msg{padding:8px 12px;border-radius:6px;max-width:85%;word-wrap:break-word;font-size:12px;line-height:1.5;}
.chat-msg.user{align-self:flex-end;background:var(--cyan-dim);border:1px solid rgba(0,212,170,0.3);color:var(--text-bright);}
.chat-msg.assistant{align-self:flex-start;background:var(--surface-2);border:1px solid var(--border);color:var(--text);}
.chat-msg.system-message{align-self:center;color:var(--text-dim);font-size:11px;font-style:italic;}
.agent-run-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px 0;}
.agent-run-card .run-header{display:flex;align-items:center;gap:8px;cursor:pointer;}
.agent-run-card .run-status{font-size:10px;padding:2px 6px;border-radius:3px;text-transform:uppercase;}
.agent-run-card .run-status.pending{background:var(--amber-dim);color:var(--amber);}
.agent-run-card .run-status.running{background:var(--cyan-dim);color:var(--cyan);}
.agent-run-card .run-status.completed{background:rgba(52,211,153,0.12);color:var(--green);}
.agent-run-card .run-status.failed{background:var(--red-dim);color:var(--red);}
.agent-run-card .run-status.review{background:rgba(167,139,250,0.12);color:var(--purple);}
.agent-run-card .run-output{display:none;margin-top:8px;padding:8px;background:var(--bg);border-radius:4px;font-size:11px;white-space:pre-wrap;max-height:200px;overflow-y:auto;}
.agent-run-card.expanded .run-output{display:block;}
.agent-run-card .run-actions{display:none;margin-top:8px;gap:8px;}
.agent-run-card.review .run-actions{display:flex;}

dialog{
  border:1px solid var(--border-hi);
  background:var(--surface);
  color:var(--text);
  padding:14px;
  border-radius:6px;
  max-width:420px;
}

dialog form{
  display:flex;
  flex-direction:column;
  gap:10px;
  min-width:320px;
}

dialog label{
  display:flex;
  flex-direction:column;
  font-size:10px;
  letter-spacing:1px;
  text-transform:uppercase;
  color:var(--text-dim);
}

dialog textarea,
dialog input,
dialog select{
  margin-top:4px;
  border:1px solid var(--border);
  background:var(--surface-2);
  color:var(--text);
  border-radius:3px;
  padding:6px;
}

dialog textarea{
  min-height:72px;
  resize:vertical;
}

dialog .dialog-actions{
  display:flex;
  justify-content:flex-end;
  gap:8px;
}

dialog .dialog-actions button{
  padding:4px 10px;
}

.memory-detail{
  white-space:pre-wrap;font-size:11px;line-height:1.6;color:var(--text);
  padding:10px;background:var(--surface-2);border-radius:4px;
  border:1px solid var(--border);min-height:120px;
}
.memory-detail .mem-type{color:var(--cyan);font-weight:500}
.memory-detail .mem-date{color:var(--text-dim)}

/* --- JIRA/GITLAB --- */
.ext-item{
  padding:5px 8px;margin-bottom:3px;border-radius:3px;
  background:var(--surface-2);font-size:11px;
  display:flex;align-items:flex-start;gap:6px;
}
.ext-item .ext-key{
  font-size:9px;color:var(--blue);white-space:nowrap;
  font-weight:500;min-width:60px;padding-top:1px;
}
.ext-item .ext-title{color:var(--text);line-height:1.4}
.ext-item .ext-status{
  font-size:8px;padding:1px 4px;border-radius:2px;
  background:var(--surface);border:1px solid var(--border);
  color:var(--text-dim);white-space:nowrap;margin-left:auto;
}

/* --- RESPONSIVE --- */
@media(max-width:1100px){
  .main{grid-template-columns:280px 1fr 280px}
}
@media(max-width:900px){
  .main{grid-template-columns:1fr;grid-template-rows:auto 400px auto}
  .panel{border-right:none;border-bottom:1px solid var(--border)}
}
</style>
</head>
<body>
<div class="hud">
  <!-- TOP BAR -->
  <div class="topbar">
    <div class="topbar-left">
      <div class="logo">MEMENTO<span>// command</span></div>
      <select id="workspace-select" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:11px;padding:4px 8px;border-radius:4px;">
        <option value="">Select workspace...</option>
      </select>
    </div>
    <div class="topbar-right">
      <button id="brain-toggle" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text-dim);font-family:var(--mono);font-size:10px;padding:4px 10px;border-radius:4px;cursor:pointer;letter-spacing:1px">[BRAIN]</button>
      <div class="status-dot"></div>
      <div class="status-label">System Active</div>
      <div class="clock" id="clock"></div>
    </div>
  </div>

  <!-- MAIN 3-COLUMN -->
  <div class="main">
    <!-- LEFT: TRACKER -->
    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">Tracker</div>
        <div class="panel-badge" id="pending-badge">0</div>
      </div>
      <div class="panel-body" id="tracker-body">
        <div class="tracker-empty">Loading tracker...</div>
      </div>
      <div class="track-form">
        <input type="text" id="track-title" placeholder="Track new item..."/>
        <div class="row">
          <input type="date" id="track-due"/>
          <input type="text" id="track-ticket" placeholder="TOPE-000"/>
        </div>
        <div class="row">
          <select id="track-priority">
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="low">Low</option>
          </select>
          <input type="text" id="track-context" placeholder="Context..."/>
        </div>
        <button class="track-btn" id="track-submit">+ Track Item</button>
      </div>
    </div>

    <!-- CENTER: Orchestra Chat -->
    <div class="center" style="display:flex;flex-direction:column;height:100%;overflow:hidden">
      <div class="chat-messages" id="chat-messages" style="flex:1;overflow-y:auto;padding:12px;">
        <div class="chat-msg system-message">Welcome to Orchestra. Type a message to start.</div>
      </div>
      <div style="border-top:1px solid var(--border);padding:8px 12px;display:flex;gap:8px;flex-shrink:0;">
        <textarea id="chat-input" rows="1" placeholder="Ask the orchestrator..." style="flex:1;resize:none;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:var(--mono);font-size:12px;padding:8px;outline:none;"></textarea>
        <button id="chat-send" style="background:var(--cyan);color:var(--bg);border:none;border-radius:4px;padding:8px 16px;cursor:pointer;font-family:var(--mono);font-weight:700;font-size:11px;letter-spacing:1px;">SEND</button>
      </div>
    </div>

    <!-- RIGHT: BRIEFING + DETAIL -->
    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">Briefing</div>
        <button id="briefing-refresh" style="font-size:9px;padding:2px 8px;background:var(--surface-2);border:1px solid var(--border);color:var(--text-dim);border-radius:3px;cursor:pointer;font-family:var(--mono);letter-spacing:1px">DAILY</button>
      </div>
      <div class="panel-body" id="briefing-body">
        <div class="briefing-section" id="briefing-findings">
          <div class="briefing-section-title">Recent Findings</div>
          <div class="tracker-empty">Loading briefing...</div>
        </div>
        <div class="briefing-section" id="briefing-jira" style="display:none">
          <div class="briefing-section-title">Jira Tickets</div>
          <div id="jira-items"></div>
        </div>
        <div class="briefing-section" id="briefing-mrs" style="display:none">
          <div class="briefing-section-title">Open MRs</div>
          <div id="mr-items"></div>
        </div>
        <div class="briefing-section">
          <div class="briefing-section-title">Memory Detail</div>
          <div class="memory-detail" id="info">Click a node in the graph to inspect memory details.</div>
        </div>
        <div class="briefing-section">
          <div class="briefing-section-title">Config</div>
          <div id="config-panel" style="font-size:11px;">
            <div style="color:var(--text-dim);margin-bottom:6px;">MCPs</div>
            <div id="config-mcps">Loading...</div>
            <div style="color:var(--text-dim);margin:8px 0 6px;">Agent Configs</div>
            <div id="config-agents">Loading...</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- BRAIN GRAPH MODAL -->
<div id="brain-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;z-index:1000;">
  <div id="brain-backdrop" style="position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);"></div>
  <div style="position:relative;margin:40px auto;width:80%;height:calc(100% - 80px);background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;">
    <div class="brain-controls" style="padding:8px 14px;border-bottom:1px solid var(--border);display:flex;flex-wrap:wrap;gap:6px;align-items:center;background:var(--surface);flex-shrink:0;">
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Proj <input id="project" placeholder="all" style="width:60px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;"/></label>
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Type
        <select id="memoryType" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;">
          <option value="">all</option>
          <option value="requirement">req</option>
          <option value="fact">fact</option>
          <option value="decision">dec</option>
          <option value="preference">pref</option>
          <option value="learning">learn</option>
          <option value="session">sess</option>
          <option value="note">note</option>
        </select>
      </label>
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Lim <input id="limit" type="number" value="160" min="20" max="400" style="width:50px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;"/></label>
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Nbr <input id="neighbors" type="number" value="4" min="1" max="12" style="width:50px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;"/></label>
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Sim <input id="similarity" type="number" step="0.01" value="0.35" min="0" max="1" style="width:45px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;"/></label>
      <label style="font-size:10px;color:var(--text-dim);display:flex;align-items:center;gap:4px">Days
        <select id="days" style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:3px;">
          <option value="">all</option>
          <option value="7">7d</option>
          <option value="30">30d</option>
          <option value="90">90d</option>
        </select>
      </label>
      <button id="refresh" style="padding:4px 10px;cursor:pointer;font-family:var(--mono);font-size:10px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:3px;text-transform:uppercase;letter-spacing:1px;">Refresh</button>
      <button id="clear" style="padding:4px 10px;cursor:pointer;font-family:var(--mono);font-size:10px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:3px;text-transform:uppercase;letter-spacing:1px;">Reset</button>
    </div>
    <div style="flex:1;position:relative;overflow:hidden;">
      <canvas id="brain" style="width:100%;height:100%;display:block;"></canvas>
      <div id="status" style="position:absolute;bottom:8px;left:14px;font-size:10px;color:var(--text-dim);letter-spacing:0.5px;">Initializing...</div>
      <div style="position:absolute;bottom:8px;right:14px;display:flex;gap:10px;font-size:10px;">
        <span><span class="dot" style="background:#4d9fff;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>fact</span>
        <span><span class="dot" style="background:#a78bfa;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>pref</span>
        <span><span class="dot" style="background:#fb923c;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>dec</span>
        <span><span class="dot" style="background:#ff4d4d;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>req</span>
        <span><span class="dot" style="background:#34d399;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>learn</span>
        <span><span class="dot" style="background:#94a3b8;width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px;vertical-align:middle"></span>other</span>
      </div>
    </div>
  </div>
</div>

<script>
// --- CLOCK ---
function updateClock(){
  const now=new Date();
  const h=String(now.getHours()).padStart(2,'0');
  const m=String(now.getMinutes()).padStart(2,'0');
  const s=String(now.getSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent=`${h}:${m}:${s}`;
}
setInterval(updateClock,1000);updateClock();

// --- COLORS ---
const colorByType={
  requirement:"#ff4d4d",fact:"#4d9fff",decision:"#fb923c",
  preference:"#a78bfa",learning:"#34d399",session:"#94a3b8",note:"#94a3b8"
};

// --- BRAIN GRAPH STATE (lazy init) ---
const state={width:0,height:0,nodes:[],links:[],selected:null};
let canvas=null,ctx=null,brainInitialized=false;

function typeCount(nodes){
  const m={};for(const n of nodes)m[n.type]=(m[n.type]||0)+1;return m;
}

// --- CANVAS ---
function resizeCanvas(){
  if(!canvas)return;
  const r=canvas.parentElement.getBoundingClientRect();
  const s=window.devicePixelRatio||1;
  canvas.width=r.width*s;canvas.height=r.height*s;
  ctx.setTransform(s,0,0,s,0,0);
  state.width=r.width;state.height=r.height;
}

// --- TRACKER ---
async function loadTracker(){
  const body=document.getElementById("tracker-body");
  body.innerHTML='<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  try{
    const resp=await fetch("/api/tracker/items");
    const data=await resp.json();
    renderTracker(data.result);
  }catch(e){
    body.innerHTML='<div class="tracker-empty">Failed to load tracker</div>';
  }
}

function renderTracker(raw){
  const body=document.getElementById("tracker-body");
  const badge=document.getElementById("pending-badge");

  // Parse the markdown-ish response
  const lines=raw.split('\n').filter(l=>l.trim());
  if(lines.length<=1 && raw.includes("No pending")){
    body.innerHTML='<div class="tracker-empty">All clear - no pending items</div>';
    badge.textContent="0";badge.className="panel-badge";
    return;
  }

  const items=[];
  let currentItem=null;
  for(const line of lines){
    if(line.startsWith("# "))continue;
    const itemMatch=line.match(/^- \*\*([^*]+)\*\*(?:\s*\[([^\]]+)\])?\s*:\s*(.+?)(?:\s*\(due\s+([^)]+)\))?\s*(\*\*OVERDUE\*\*)?$/);
    if(itemMatch){
      currentItem={id:itemMatch[1],ticket:itemMatch[2]||null,title:itemMatch[3].trim(),due:itemMatch[4]||null,overdue:!!itemMatch[5],context:null};
      items.push(currentItem);
    }else if(line.trim().startsWith("_")&&currentItem){
      currentItem.context=line.trim().replace(/^_|_$/g,'');
    }
  }

  const overdue=items.filter(i=>i.overdue);
  const upcoming=items.filter(i=>!i.overdue);

  badge.textContent=String(items.length);
  badge.className=overdue.length>0?"panel-badge crit":"panel-badge";

  let html='';
  if(overdue.length){
    html+='<div class="tracker-section"><div class="tracker-section-title">Overdue</div>';
    for(const i of overdue)html+=renderTrackerItem(i,true);
    html+='</div>';
  }
  if(upcoming.length){
    html+='<div class="tracker-section"><div class="tracker-section-title">Upcoming</div>';
    for(const i of upcoming)html+=renderTrackerItem(i,false);
    html+='</div>';
  }
  body.innerHTML=html;
}

function renderTrackerItem(item,isOverdue){
  let meta='';
  if(item.ticket)meta+=`<span class="tag ticket">${escHtml(item.ticket)}</span>`;
  if(item.due)meta+=`<span class="tag ${isOverdue?'overdue':'due'}">${escHtml(item.due)}</span>`;
  return`<div class="tracker-item ${isOverdue?'overdue':''} ${item.priority==='high'?'high':''}">
    <div class="tracker-item-id">${escHtml(item.id)}</div>
    <div class="tracker-item-title">${escHtml(item.title)}</div>
    <div class="tracker-item-meta">${meta}</div>
    ${item.context?`<div style="font-size:10px;color:var(--text-dim);margin-top:3px">${escHtml(item.context)}</div>`:''}
    <div class="tracker-item-actions">
      <button class="tracker-action complete" onclick="completeItem('${escHtml(item.id)}')">Done</button>
      <button class="tracker-action defer" onclick="deferItem('${escHtml(item.id)}')">Defer</button>
    </div>
  </div>`;
}

async function completeItem(id){
  try{
    await fetch("/api/tracker/items/"+encodeURIComponent(id)+"/complete",{method:"POST"});
    loadTracker();
  }catch(e){console.error("Complete failed",e)}
}

async function deferItem(id){
  const newDate=prompt("Defer to date (YYYY-MM-DD):");
  if(!newDate||!/^\d{4}-\d{2}-\d{2}$/.test(newDate))return;
  try{
    await fetch("/api/tracker/items/"+encodeURIComponent(id)+"/defer",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({new_date:newDate})
    });
    loadTracker();
  }catch(e){console.error("Defer failed",e)}
}

// --- TRACK NEW ITEM ---
document.getElementById("track-submit").addEventListener("click",async()=>{
  const title=document.getElementById("track-title").value.trim();
  if(!title)return;
  const payload={title,priority:document.getElementById("track-priority").value};
  const due=document.getElementById("track-due").value;
  const ticket=document.getElementById("track-ticket").value.trim();
  const context=document.getElementById("track-context").value.trim();
  if(due)payload.due_date=due;
  if(ticket)payload.ticket_id=ticket;
  if(context)payload.context=context;
  try{
    await fetch("/api/tracker/items",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    document.getElementById("track-title").value="";
    document.getElementById("track-due").value="";
    document.getElementById("track-ticket").value="";
    document.getElementById("track-context").value="";
    loadTracker();
  }catch(e){console.error("Track failed",e)}
});

// --- BRIEFING ---
async function loadBriefing(mode){
  const endpoint=mode==="daily"?"/api/briefing/daily":"/api/briefing/session";
  document.getElementById("briefing-findings").innerHTML='<div class="briefing-section-title">Recent Findings</div><div class="skeleton"></div><div class="skeleton" style="height:28px"></div>';
  try{
    const resp=await fetch(endpoint);
    const data=await resp.json();
    renderBriefing(data.result,mode);
  }catch(e){
    document.getElementById("briefing-findings").innerHTML='<div class="tracker-empty">Failed to load briefing</div>';
  }
}

function renderBriefing(raw,mode){
  const findingsEl=document.getElementById("briefing-findings");
  const jiraEl=document.getElementById("briefing-jira");
  const mrsEl=document.getElementById("briefing-mrs");

  // Parse sections from the briefing markdown
  const sections=raw.split(/^## /m).filter(Boolean);
  let findingsHtml='<div class="briefing-section-title">Recent Findings</div>';
  let hasFindings=false;
  let jiraHtml='';
  let mrsHtml='';

  for(const section of sections){
    const lines=section.split('\n');
    const title=lines[0].trim().replace(/^#+\s*/,'');

    if(title.includes("OVERDUE")||title.includes("Pending")||title.includes("Recent")){
      const items=lines.slice(1).filter(l=>l.startsWith("- "));
      if(items.length){
        hasFindings=true;
        for(const item of items){
          const typeMatch=item.match(/\[(decision|learning|requirement|fact)\]/i);
          const type=typeMatch?typeMatch[1].toLowerCase():'';
          const content=item.replace(/^-\s*/,'').replace(/\[.*?\]\s*/,'').trim();
          findingsHtml+=`<div class="briefing-item">${type?`<span class="type-tag ${type}">${type}</span>`:''}${escHtml(content)}</div>`;
        }
      }
    }
    if(title.includes("Jira")){
      const items=lines.slice(1).filter(l=>l.startsWith("- "));
      if(items.length){
        for(const item of items){
          const match=item.match(/\*\*([^*]+)\*\*:\s*(.+?)(?:\s*\(([^)]+)\))?$/);
          if(match){
            jiraHtml+=`<div class="ext-item"><span class="ext-key">${escHtml(match[1])}</span><span class="ext-title">${escHtml(match[2])}</span>${match[3]?`<span class="ext-status">${escHtml(match[3])}</span>`:''}</div>`;
          }
        }
      }
    }
    if(title.includes("MR")){
      const items=lines.slice(1).filter(l=>l.startsWith("- "));
      if(items.length){
        for(const item of items){
          const match=item.match(/\*\*([^*]+)\*\*\s*\(([^)]+)\)\s*(.*)/);
          if(match){
            mrsHtml+=`<div class="ext-item"><span class="ext-title">${escHtml(match[1])}</span><span class="ext-status">${escHtml(match[2])}</span></div>`;
          }
        }
      }
    }
  }

  if(!hasFindings)findingsHtml+='<div class="tracker-empty">All clear</div>';
  findingsEl.innerHTML=findingsHtml;

  if(jiraHtml){jiraEl.style.display="block";document.getElementById("jira-items").innerHTML=jiraHtml;}
  else{jiraEl.style.display="none"}

  if(mrsHtml){mrsEl.style.display="block";document.getElementById("mr-items").innerHTML=mrsHtml;}
  else{mrsEl.style.display="none"}
}

// --- WORKSPACE SELECTOR ---
async function loadWorkspaces() {
  try {
    const res = await fetch('/api/workspaces');
    const data = await res.json();
    const select = document.getElementById('workspace-select');
    select.innerHTML = '<option value="">Select workspace...</option>';
    data.workspaces.forEach(ws => {
      const opt = document.createElement('option');
      opt.value = ws.path;
      opt.textContent = ws.name;
      select.appendChild(opt);
    });
    const saved = localStorage.getItem('activeWorkspace');
    if (saved) select.value = saved;
  } catch (e) {
    console.error('Failed to load workspaces:', e);
  }
}

document.getElementById('workspace-select').addEventListener('change', function() {
  localStorage.setItem('activeWorkspace', this.value);
  appendSystemMessage('Workspace changed to: ' + this.value);
});

// --- CHAT ---
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
let chatHistory = JSON.parse(localStorage.getItem('chatHistory') || '[]');

function appendMessage(role, content) {
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  div.textContent = content;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendSystemMessage(text) {
  const div = document.createElement('div');
  div.className = 'chat-msg system-message';
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendRunCard(dispatch) {
  const card = document.createElement('div');
  card.className = 'agent-run-card';
  card.id = 'run-' + dispatch.run_id;
  card.innerHTML =
    '<div class="run-header" onclick="toggleRunCard(this.parentElement)">' +
      '<span style="color:var(--cyan);font-weight:700;">' + escHtml(dispatch.agent) + '</span> ' +
      '<span class="run-status ' + dispatch.status + '">' + escHtml(dispatch.status) + '</span> ' +
      '<span style="color:var(--text-dim);font-size:11px;">' + escHtml(dispatch.run_id) + '</span>' +
    '</div>' +
    '<div style="font-size:11px;color:var(--text-dim);margin-top:4px;">' + escHtml(dispatch.task || '') + '</div>' +
    '<div class="run-output">Loading...</div>' +
    '<div class="run-actions">' +
      '<button onclick="reviewRun(\'' + escHtml(dispatch.run_id) + '\',\'approve\')">APPROVE</button>' +
      '<button onclick="reviewRun(\'' + escHtml(dispatch.run_id) + '\',\'reject\')">REJECT</button>' +
    '</div>';
  chatMessages.appendChild(card);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  pollRunStatus(dispatch.run_id);
}

function toggleRunCard(card) {
  card.classList.toggle('expanded');
  if (card.classList.contains('expanded')) {
    loadRunOutput(card.id.replace('run-', ''));
  }
}

async function loadRunOutput(runId) {
  try {
    const res = await fetch('/api/orchestra/runs/' + runId + '/output');
    const data = await res.json();
    const card = document.getElementById('run-' + runId);
    if (card) {
      card.querySelector('.run-output').textContent = data.output || 'No output yet.';
    }
  } catch (e) {
    console.error('Failed to load run output:', e);
  }
}

async function pollRunStatus(runId) {
  const poll = setInterval(async () => {
    try {
      const res = await fetch('/api/orchestra/runs/' + runId + '/output');
      const data = await res.json();
      const card = document.getElementById('run-' + runId);
      if (!card) { clearInterval(poll); return; }
      const badge = card.querySelector('.run-status');
      badge.className = 'run-status ' + data.status;
      badge.textContent = data.status;
      if (data.status === 'review') card.classList.add('review');
      if (['completed', 'failed'].includes(data.status)) {
        clearInterval(poll);
        card.querySelector('.run-output').textContent = data.output || data.error || 'Done.';
      }
    } catch (e) { clearInterval(poll); }
  }, 3000);
}

async function reviewRun(runId, action) {
  try {
    await fetch('/api/orchestra/runs/' + runId + '/review', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: action}),
    });
    appendSystemMessage(runId + ' ' + action + 'd.');
  } catch (e) {
    appendSystemMessage('Failed to ' + action + ' ' + runId);
  }
}

async function sendChat() {
  const msg = chatInput.value.trim();
  if (!msg) return;

  const workspace = document.getElementById('workspace-select').value;
  chatInput.value = '';
  chatInput.style.height = 'auto';
  appendMessage('user', msg);

  chatHistory.push({role: 'user', content: msg});

  try {
    const res = await fetch('/api/orchestra/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: msg,
        workspace: workspace,
        history: chatHistory.slice(-20),
      }),
    });
    const data = await res.json();

    if (data.error) {
      appendSystemMessage('Error: ' + data.error);
      return;
    }

    appendMessage('assistant', data.message);
    chatHistory.push({role: 'assistant', content: data.message});

    if (data.dispatches && data.dispatches.length > 0) {
      data.dispatches.forEach(d => appendRunCard(d));
    }

    localStorage.setItem('chatHistory', JSON.stringify(chatHistory.slice(-100)));
  } catch (e) {
    appendSystemMessage('Failed to reach orchestrator: ' + e.message);
  }
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

chatInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// --- CONFIG PANEL ---
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    const mcpDiv = document.getElementById('config-mcps');
    const seen = {};
    mcpDiv.innerHTML = '';
    Object.entries(data.agents).forEach(([name, cfg]) => {
      if (cfg.mcpServers) {
        Object.keys(cfg.mcpServers).forEach(mcp => {
          if (!seen[mcp]) {
            seen[mcp] = true;
            mcpDiv.innerHTML += '<div style="margin:2px 0;">' + escHtml(mcp) + ' <span style="color:var(--green);">[active]</span></div>';
          }
        });
      }
    });
    const agentsDiv = document.getElementById('config-agents');
    agentsDiv.innerHTML = '';
    Object.entries(data.agents).forEach(([name, cfg]) => {
      const mcpCount = cfg.mcpServers ? Object.keys(cfg.mcpServers).length : 0;
      agentsDiv.innerHTML += '<div style="margin:2px 0;">' + escHtml(name) + ' <span style="color:var(--text-dim);">[' + mcpCount + ' MCP]</span></div>';
    });
  } catch (e) {
    console.error('Failed to load config:', e);
  }
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

let briefingMode="session";
document.getElementById("briefing-refresh").addEventListener("click",()=>{
  briefingMode=briefingMode==="session"?"daily":"session";
  const btn=document.getElementById("briefing-refresh");
  btn.textContent=briefingMode==="session"?"DAILY":"SESSION";
  loadBriefing(briefingMode);
});

// --- BRAIN GRAPH MODAL ---
document.getElementById('brain-toggle').addEventListener('click', function() {
  const modal = document.getElementById('brain-modal');
  modal.style.display = modal.style.display === 'none' ? 'block' : 'none';
  if (modal.style.display === 'block') initBrainGraph();
});

document.getElementById('brain-backdrop').addEventListener('click', function() {
  document.getElementById('brain-modal').style.display = 'none';
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.getElementById('brain-modal').style.display = 'none';
  }
});

// --- GRAPH (wrapped in initBrainGraph) ---
function initBrainGraph(){
  if(brainInitialized)return;
  brainInitialized=true;
  canvas=document.getElementById("brain");
  ctx=canvas.getContext("2d");
  resizeCanvas();
  loadGraph();
  loop();
  canvas.addEventListener("click",evt=>{
    const b=canvas.parentElement.getBoundingClientRect();
    const x=evt.clientX-b.left,y=evt.clientY-b.top;
    let closest=null,cd=1e6;
    for(const n of state.nodes){
      const d=Math.sqrt((n.x-x)**2+(n.y-y)**2);
      if(d<cd&&d<20){cd=d;closest=n}
    }
    if(closest){state.selected=closest;renderInfo()}
  });
  document.getElementById("refresh").addEventListener("click",loadGraph);
  document.getElementById("clear").addEventListener("click",()=>{
    document.getElementById("project").value="";
    document.getElementById("memoryType").value="";
    document.getElementById("limit").value="160";
    document.getElementById("neighbors").value="4";
    document.getElementById("similarity").value="0.35";
    document.getElementById("days").value="";
    loadGraph();
  });
  window.addEventListener("resize",resizeCanvas);
}

function buildQuery(){
  const p=document.getElementById("project").value.trim();
  const t=document.getElementById("memoryType").value;
  const l=Number(document.getElementById("limit").value||160);
  const n=Number(document.getElementById("neighbors").value||4);
  const s=Number(document.getElementById("similarity").value||0.35);
  const d=document.getElementById("days").value;
  const q=new URLSearchParams({limit:String(l),neighbor_count:String(n),min_similarity:String(s)});
  if(p)q.set("project",p);if(t)q.set("type",t);if(d)q.set("days",d);
  return q.toString();
}

function normalizeNodes(dataNodes){
  return dataNodes.map(n=>{
    const vx=(Math.random()-0.5)*0.5,vy=(Math.random()-0.5)*0.5;
    const x=(n.position.x+1)*0.5*(state.width-80)+40;
    const y=(n.position.y+1)*0.5*(state.height-80)+40;
    return{...n,x,y,vx,vy,fx:x,fy:y};
  });
}

function loadGraph(){
  document.getElementById("status").textContent="Loading...";
  fetch("/api/memory/graph?"+buildQuery())
    .then(r=>r.json()).then(p=>{
      const g=p.graph||{};
      state.nodes=normalizeNodes(g.nodes||[]);
      state.links=g.links||[];
      state.selected=null;
      const tc=typeCount(state.nodes);
      document.getElementById("status").textContent=
        `${state.nodes.length} nodes / ${state.links.length} edges`;
      renderInfo();
    }).catch(e=>{
      document.getElementById("status").textContent=`Error: ${e.message}`;
    });
}

function renderInfo(){
  const el=document.getElementById("info");
  if(state.selected){
    el.classList.add("has-selection");
    el.innerHTML=
      `<span class="mem-type">${escHtml(state.selected.type)}</span> <span class="mem-date">${escHtml(state.selected.date||'')}</span>\n\n${escHtml(state.selected.content||'')}`;
  }else{
    el.classList.remove("has-selection");
    el.textContent="Click a node in the graph to inspect memory details.";
  }
}

// --- PHYSICS ---
function stepPhysics(){
  if(!state.nodes.length)return;
  const damping=0.85,repulsion=9000,linkStr=0.0025;
  for(const n of state.nodes){n.vx*=damping;n.vy*=damping}
  for(let i=0;i<state.nodes.length;i++){
    for(let j=i+1;j<state.nodes.length;j++){
      const a=state.nodes[i],b=state.nodes[j];
      const dx=a.x-b.x,dy=a.y-b.y;
      const d2=Math.max(80,dx*dx+dy*dy);
      const f=repulsion/d2,inv=1/Math.sqrt(d2);
      const fx=f*dx*inv*0.001,fy=f*dy*inv*0.001;
      a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;
    }
  }
  for(const link of state.links){
    const src=state.nodes.find(n=>n.id===link.source);
    const tgt=state.nodes.find(n=>n.id===link.target);
    if(!src||!tgt)continue;
    const dx=tgt.x-src.x,dy=tgt.y-src.y;
    const dist=Math.max(20,Math.sqrt(dx*dx+dy*dy));
    const rest=120*(1-link.weight),f=(dist-rest)*linkStr;
    const nx=dx/dist,ny=dy/dist;
    src.vx+=f*nx;src.vy+=f*ny;tgt.vx-=f*nx;tgt.vy-=f*ny;
  }
  for(const n of state.nodes){
    n.x+=n.vx;n.y+=n.vy;
    n.x=Math.min(state.width-20,Math.max(20,n.x));
    n.y=Math.min(state.height-20,Math.max(20,n.y));
  }
}

function render(){
  resizeCanvas();
  ctx.clearRect(0,0,state.width,state.height);

  // Draw subtle grid
  ctx.strokeStyle="rgba(30,42,58,0.5)";ctx.lineWidth=0.5;
  for(let x=0;x<state.width;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,state.height);ctx.stroke()}
  for(let y=0;y<state.height;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(state.width,y);ctx.stroke()}

  // Links
  for(const link of state.links){
    const src=state.nodes.find(n=>n.id===link.source);
    const tgt=state.nodes.find(n=>n.id===link.target);
    if(!src||!tgt)continue;
    const a=Math.min(0.6,Math.max(0.08,link.weight));
    ctx.strokeStyle=`rgba(0,212,170,${a})`;
    ctx.lineWidth=0.5+a*1.5;
    ctx.beginPath();ctx.moveTo(src.x,src.y);ctx.lineTo(tgt.x,tgt.y);ctx.stroke();
  }

  // Nodes
  for(const node of state.nodes){
    const sel=state.selected&&state.selected.id===node.id;
    const r=Math.max(3,2.5+Math.min(5,Math.sqrt((node.degree||0)+1)));
    const color=colorByType[node.type]||"#94a3b8";

    // Outer glow for selected
    if(sel){
      const glow=ctx.createRadialGradient(node.x,node.y,r,node.x,node.y,r*4);
      glow.addColorStop(0,color.replace(')',',0.3)').replace('rgb','rgba'));
      glow.addColorStop(1,"transparent");
      ctx.beginPath();ctx.fillStyle=glow;
      ctx.arc(node.x,node.y,r*4,0,Math.PI*2);ctx.fill();
    }

    ctx.beginPath();ctx.fillStyle=color;
    ctx.globalAlpha=sel?1:0.7;
    ctx.arc(node.x,node.y,r,0,Math.PI*2);ctx.fill();
    if(sel){
      ctx.strokeStyle="#00d4aa";ctx.lineWidth=2;ctx.stroke();
      ctx.beginPath();ctx.arc(node.x,node.y,r+4,0,Math.PI*2);
      ctx.strokeStyle="rgba(0,212,170,0.3)";ctx.lineWidth=1;ctx.stroke();
    }
    ctx.globalAlpha=1;
  }
}

function loop(){stepPhysics();render();requestAnimationFrame(loop)}

// --- INIT ---
loadTracker();
loadBriefing("session");
loadWorkspaces();
loadConfig();
setInterval(loadTracker,30000);
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
