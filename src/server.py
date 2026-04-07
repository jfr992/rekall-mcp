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

        fmt = query.get("format", "markdown")
        manager = _get_memory_manager()

        if fmt == "json":
            from memory.topics import topics_to_json

            clusters = manager.get_topic_clusters(
                project=project,
                limit=limit,
                max_topics=max_topics,
                similarity_threshold=similarity_threshold,
            )
            result = topics_to_json(clusters, project=project)
            result["params"] = {
                "limit": limit,
                "max_topics": max_topics,
                "similarity_threshold": similarity_threshold,
            }
            return JSONResponse(result)

        context = manager.get_hierarchical_project_context(
            project=project,
            limit=limit,
            max_topics=max_topics,
            similarity_threshold=similarity_threshold,
        )

        return JSONResponse(
            {
                "project": project or "all",
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


@mcp.custom_route("/dashboard", methods=["GET"])
async def api_memory_dashboard(_request):
    """Dashboard UI for visualizing memory embeddings."""
    from starlette.responses import HTMLResponse

    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Memento — Neural Memory</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}
body{
  font-family:"Inter","SF Pro Display",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#050510;color:#e2e8f0;
}
canvas#brain{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0}
.toolbar{
  position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:10;
  display:flex;gap:8px;align-items:center;
  padding:8px 16px;
  background:rgba(10,14,36,0.85);backdrop-filter:blur(20px);
  border:1px solid rgba(100,120,255,0.12);border-radius:14px;font-size:13px;
}
.toolbar .brand{
  font-weight:700;font-size:15px;
  background:linear-gradient(135deg,#818cf8,#38bdf8);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
  margin-right:8px;white-space:nowrap;
}
.toolbar label{display:flex;align-items:center;gap:4px;color:#94a3b8;font-size:12px;white-space:nowrap}
.toolbar input,.toolbar select{
  background:rgba(15,20,50,0.8);border:1px solid rgba(100,120,255,0.15);
  color:#e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;width:56px;
}
.toolbar select{width:auto}
.toolbar button{
  background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);
  color:#a5b4fc;border-radius:6px;padding:4px 12px;font-size:12px;cursor:pointer;
  transition:all 150ms;
}
.toolbar button:hover{background:rgba(99,102,241,0.3);color:#fff}
.detail-panel{
  position:fixed;top:70px;right:16px;width:320px;max-height:calc(100vh - 100px);
  z-index:10;
  background:rgba(10,14,36,0.88);backdrop-filter:blur(20px);
  border:1px solid rgba(100,120,255,0.1);border-radius:14px;
  padding:16px;overflow-y:auto;font-size:13px;
}
.detail-panel h3{
  font-size:12px;font-weight:600;color:#818cf8;
  text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;
}
.detail-panel .stats{color:#64748b;font-size:12px;line-height:1.8;margin-bottom:12px}
.detail-panel .stats span{font-weight:500}
.detail-panel .memory-content{
  color:#cbd5e1;line-height:1.6;white-space:pre-wrap;word-break:break-word;
  font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:11px;
}
.detail-panel .type-badge{
  display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:11px;font-weight:500;margin-bottom:10px;
}
.legend{
  position:fixed;bottom:16px;left:16px;z-index:10;
  display:flex;gap:14px;padding:8px 14px;
  background:rgba(10,14,36,0.8);backdrop-filter:blur(16px);
  border:1px solid rgba(100,120,255,0.08);border-radius:10px;
  font-size:11px;color:#64748b;
}
.legend .item{display:flex;align-items:center;gap:5px}
.legend .dot{width:8px;height:8px;border-radius:50%}
.status-bar{
  position:fixed;bottom:16px;right:16px;z-index:10;
  padding:6px 12px;
  background:rgba(10,14,36,0.8);backdrop-filter:blur(16px);
  border:1px solid rgba(100,120,255,0.08);border-radius:8px;
  font-size:11px;color:#475569;
}
#tooltip{
  display:none;position:fixed;z-index:20;
  background:rgba(10,14,36,0.95);backdrop-filter:blur(12px);
  border:1px solid rgba(100,120,255,0.2);border-radius:8px;
  padding:6px 10px;font-size:11px;color:#cbd5e1;
  max-width:300px;pointer-events:none;
}
#tooltip .tt-type{font-weight:600;margin-bottom:2px;font-size:10px;text-transform:uppercase;letter-spacing:0.05em}
#tooltip .tt-text{color:#94a3b8;line-height:1.4}
@media(max-width:900px){
  .toolbar{flex-wrap:wrap;top:8px;left:8px;right:8px;transform:none;width:auto}
  .detail-panel{width:calc(100% - 32px);right:16px;top:auto;bottom:56px;max-height:35vh}
  .legend{bottom:8px;left:8px;flex-wrap:wrap;gap:8px}
}
</style>
</head>
<body>
<canvas id="brain"></canvas>
<div class="toolbar">
  <span class="brand">MEMENTO</span>
  <label>Project <input id="project" placeholder="all"/></label>
  <label>Type
    <select id="memoryType">
      <option value="">all</option>
      <option value="fact">fact</option>
      <option value="decision">decision</option>
      <option value="learning">learning</option>
      <option value="preference">preference</option>
      <option value="requirement">requirement</option>
      <option value="session">session</option>
      <option value="note">note</option>
    </select>
  </label>
  <label>Limit <input id="limit" type="number" value="160" min="20" max="400"/></label>
  <label>Neighbors <input id="neighbors" type="number" value="5" min="1" max="12"/></label>
  <label>Score <input id="similarity" type="number" step="0.01" value="0.30" min="0" max="1"/></label>
  <label>Days
    <select id="days">
      <option value="">all</option>
      <option value="7">7d</option>
      <option value="30">30d</option>
      <option value="90">90d</option>
    </select>
  </label>
  <button id="refresh">Refresh</button>
  <button id="clear">Reset</button>
</div>
<div class="detail-panel" id="detailPanel">
  <h3>Neural Memory</h3>
  <div class="stats" id="stats">Loading neural network...</div>
  <div id="memoryDetail"><div style="color:#475569;font-size:12px">Click a neuron to inspect</div></div>
</div>
<div class="legend">
  <div class="item"><div class="dot" style="background:#38bdf8"></div>fact</div>
  <div class="item"><div class="dot" style="background:#fbbf24"></div>decision</div>
  <div class="item"><div class="dot" style="background:#34d399"></div>learning</div>
  <div class="item"><div class="dot" style="background:#f472b6"></div>preference</div>
  <div class="item"><div class="dot" style="background:#22d3ee"></div>requirement</div>
  <div class="item"><div class="dot" style="background:#a78bfa"></div>session</div>
  <div class="item"><div class="dot" style="background:#94a3b8"></div>note</div>
</div>
<div class="status-bar" id="statusBar">Initializing...</div>
<div id="tooltip"><div class="tt-type"></div><div class="tt-text"></div></div>
<script>
var COLORS={fact:"#38bdf8",decision:"#fbbf24",learning:"#34d399",
  preference:"#f472b6",requirement:"#22d3ee",session:"#a78bfa",note:"#94a3b8"};
var REGIONS={
  decision:{x:.22,y:.25,label:"Frontal"},
  requirement:{x:.16,y:.40,label:"Prefrontal"},
  fact:{x:.38,y:.58,label:"Temporal"},
  learning:{x:.56,y:.18,label:"Parietal"},
  preference:{x:.42,y:.38,label:"Limbic"},
  session:{x:.83,y:.34,label:"Occipital"},
  note:{x:.76,y:.55,label:"Cerebellum"}
};
var state={nodes:[],links:[],selected:null,w:0,h:0,pulses:[],time:0};
var nodeMap=new Map();
var hoveredNode=null;
var canvas=document.getElementById("brain");
var ctx=canvas.getContext("2d");
var tooltipEl=document.getElementById("tooltip");

function brainBounds(){
  var s=Math.min(state.w*.72,state.h*.82);
  var bw=s*1.28,bh=s;
  var bx=(state.w-bw)*.46,by=(state.h-bh)*.5;
  return{bx:bx,by:by,bw:bw,bh:bh};
}
function brainPath(c){
  var b=brainBounds(),x=function(p){return b.bx+b.bw*p},y=function(p){return b.by+b.bh*p};
  c.beginPath();
  c.moveTo(x(.10),y(.52));
  c.bezierCurveTo(x(.06),y(.42),x(.04),y(.30),x(.07),y(.20));
  c.bezierCurveTo(x(.10),y(.10),x(.20),y(.04),x(.32),y(.03));
  c.bezierCurveTo(x(.42),y(.01),x(.52),y(.02),x(.62),y(.06));
  c.bezierCurveTo(x(.72),y(.10),x(.80),y(.18),x(.86),y(.28));
  c.bezierCurveTo(x(.92),y(.36),x(.93),y(.44),x(.90),y(.50));
  c.bezierCurveTo(x(.88),y(.54),x(.84),y(.56),x(.82),y(.54));
  c.bezierCurveTo(x(.80),y(.58),x(.84),y(.62),x(.86),y(.67));
  c.bezierCurveTo(x(.88),y(.74),x(.82),y(.80),x(.74),y(.78));
  c.bezierCurveTo(x(.68),y(.80),x(.64),y(.85),x(.58),y(.82));
  c.bezierCurveTo(x(.48),y(.76),x(.36),y(.70),x(.26),y(.64));
  c.bezierCurveTo(x(.18),y(.60),x(.12),y(.56),x(.10),y(.52));
  c.closePath();
}
function drawSulci(c){
  var b=brainBounds(),x=function(p){return b.bx+b.bw*p},y=function(p){return b.by+b.bh*p};
  c.strokeStyle="rgba(100,140,255,0.06)";c.lineWidth=1.5;
  c.beginPath();c.moveTo(x(.42),y(.04));c.quadraticCurveTo(x(.40),y(.20),x(.37),y(.38));c.stroke();
  c.beginPath();c.moveTo(x(.20),y(.48));c.quadraticCurveTo(x(.35),y(.42),x(.55),y(.38));c.stroke();
  c.beginPath();c.moveTo(x(.32),y(.06));c.quadraticCurveTo(x(.30),y(.20),x(.28),y(.35));c.stroke();
  c.beginPath();c.moveTo(x(.24),y(.56));c.quadraticCurveTo(x(.37),y(.52),x(.50),y(.50));c.stroke();
  c.beginPath();c.moveTo(x(.68),y(.10));c.quadraticCurveTo(x(.70),y(.24),x(.72),y(.40));c.stroke();
  c.beginPath();c.moveTo(x(.14),y(.14));c.quadraticCurveTo(x(.16),y(.22),x(.14),y(.32));c.stroke();
}
function toCanvas(nx,ny){var b=brainBounds();return{x:b.bx+b.bw*nx,y:b.by+b.bh*ny}}
function resize(){
  var dpr=devicePixelRatio||1;
  state.w=innerWidth;state.h=innerHeight;
  canvas.width=state.w*dpr;canvas.height=state.h*dpr;
  ctx.setTransform(dpr,0,0,dpr,0,0);
}
function buildQuery(){
  var q=new URLSearchParams({
    limit:document.getElementById("limit").value||"160",
    neighbor_count:document.getElementById("neighbors").value||"5",
    min_similarity:document.getElementById("similarity").value||"0.30"
  });
  var p=document.getElementById("project").value.trim();
  var t=document.getElementById("memoryType").value;
  var d=document.getElementById("days").value;
  if(p)q.set("project",p);if(t)q.set("type",t);if(d)q.set("days",d);
  return q;
}
function initNodes(raw){
  var b=brainBounds();
  var cx=b.bx+b.bw*.45,cy=b.by+b.bh*.40;
  return raw.map(function(n){
    var jx=(Math.random()-.5)*b.bw*.12;
    var jy=(Math.random()-.5)*b.bh*.12;
    return Object.assign({},n,{x:cx+jx,y:cy+jy,vx:0,vy:0,
      radius:Math.max(3,2.5+Math.min(5,Math.sqrt((n.degree||0)+1)))});
  });
}
function loadGraph(){
  document.getElementById("statusBar").textContent="Syncing neural network...";
  fetch("/api/memory/graph?"+buildQuery())
    .then(function(r){return r.json()}).then(function(data){
      var g=data.graph||{};
      state.nodes=initNodes(g.nodes||[]);
      state.links=g.links||[];
      state.selected=null;state.pulses=[];
      nodeMap.clear();state.nodes.forEach(function(n){nodeMap.set(n.id,n)});
      document.getElementById("statusBar").textContent=
        state.nodes.length+" neurons \u00b7 "+state.links.length+" synapses";
      updatePanel();
    }).catch(function(e){
      document.getElementById("statusBar").textContent="Error: "+e.message;
    });
}
function updatePanel(){
  var el=document.getElementById("stats");
  var det=document.getElementById("memoryDetail");
  if(!state.nodes.length){el.textContent="No neurons loaded.";det.innerHTML="";return}
  var byType={};state.nodes.forEach(function(n){byType[n.type]=(byType[n.type]||0)+1});
  el.innerHTML=Object.entries(byType)
    .map(function(e){return'<span style="color:'+(COLORS[e[0]]||"#94a3b8")+'">'+e[1]+"</span> "+e[0]}).join(" \u00b7 ");
  if(state.selected){
    var s=state.selected,col=COLORS[s.type]||"#94a3b8";
    det.innerHTML='<div class="type-badge" style="background:'+col+'22;color:'+col+'">'+
      esc(s.type)+" \u00b7 "+esc(s.date)+"</div>"+
      '<div class="memory-content">'+esc(s.content)+"</div>";
  }else{
    det.innerHTML='<div style="color:#475569;font-size:12px">Click a neuron to inspect</div>';
  }
}
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function physics(){
  if(!state.nodes.length)return;
  var b=brainBounds();
  var damp=.88,repulse=6000,linkS=.004,regS=.008;
  var i,j,a,n,lk,s,t,dx,dy,d2,f,inv,dist,rest,nx,ny,reg,tx,ty,pad=25;
  for(i=0;i<state.nodes.length;i++){state.nodes[i].vx*=damp;state.nodes[i].vy*=damp}
  for(i=0;i<state.nodes.length;i++){
    for(j=i+1;j<state.nodes.length;j++){
      a=state.nodes[i];n=state.nodes[j];
      dx=a.x-n.x;dy=a.y-n.y;
      d2=Math.max(100,dx*dx+dy*dy);
      f=repulse/d2;inv=1/Math.sqrt(d2);
      a.vx+=f*dx*inv*.001;a.vy+=f*dy*inv*.001;
      n.vx-=f*dx*inv*.001;n.vy-=f*dy*inv*.001;
    }
  }
  for(i=0;i<state.links.length;i++){
    lk=state.links[i];s=nodeMap.get(lk.source);t=nodeMap.get(lk.target);
    if(!s||!t)continue;
    dx=t.x-s.x;dy=t.y-s.y;
    dist=Math.max(10,Math.sqrt(dx*dx+dy*dy));
    rest=100*(1-(lk.weight||.5));
    f=(dist-rest)*linkS;nx=dx/dist;ny=dy/dist;
    s.vx+=f*nx;s.vy+=f*ny;t.vx-=f*nx;t.vy-=f*ny;
  }
  for(i=0;i<state.nodes.length;i++){
    n=state.nodes[i];reg=REGIONS[n.type];if(!reg)continue;
    tx=b.bx+b.bw*reg.x;ty=b.by+b.bh*reg.y;
    n.vx+=(tx-n.x)*regS;n.vy+=(ty-n.y)*regS;
  }
  for(i=0;i<state.nodes.length;i++){
    n=state.nodes[i];
    n.x+=n.vx;n.y+=n.vy;
    n.x=Math.max(b.bx+pad,Math.min(b.bx+b.bw-pad,n.x));
    n.y=Math.max(b.by+pad,Math.min(b.by+b.bh-pad,n.y));
  }
}
function updatePulses(){
  if(state.pulses.length<14&&state.links.length>0&&Math.random()<.06){
    var lk=state.links[Math.floor(Math.random()*state.links.length)];
    var s=nodeMap.get(lk.source),t=nodeMap.get(lk.target);
    if(s&&t)state.pulses.push({sx:s.x,sy:s.y,tx:t.x,ty:t.y,p:0,
      spd:.012+Math.random()*.018,col:COLORS[s.type]||"#818cf8"});
  }
  for(var i=0;i<state.pulses.length;i++)state.pulses[i].p+=state.pulses[i].spd;
  state.pulses=state.pulses.filter(function(p){return p.p<1});
}
function render(){
  resize();state.time+=.016;
  var W=state.w,H=state.h;
  ctx.fillStyle="#050510";ctx.fillRect(0,0,W,H);
  var b=brainBounds();
  var pulse=.6+.15*Math.sin(state.time*.8);
  var grd=ctx.createRadialGradient(b.bx+b.bw*.45,b.by+b.bh*.4,b.bw*.1,b.bx+b.bw*.45,b.by+b.bh*.4,b.bw*.55);
  grd.addColorStop(0,"rgba(99,102,241,"+(0.07*pulse)+")");
  grd.addColorStop(.5,"rgba(56,189,248,"+(0.03*pulse)+")");
  grd.addColorStop(1,"transparent");
  ctx.fillStyle=grd;ctx.fillRect(0,0,W,H);
  brainPath(ctx);
  ctx.fillStyle="rgba(15,20,50,"+(0.45*pulse)+")";ctx.fill();
  ctx.save();
  ctx.shadowColor="rgba(99,102,241,"+(0.4*pulse)+")";ctx.shadowBlur=28;
  brainPath(ctx);
  ctx.strokeStyle="rgba(99,102,241,"+(0.18*pulse)+")";ctx.lineWidth=1.5;ctx.stroke();
  ctx.restore();
  drawSulci(ctx);
  var i,lk,s,t,w,dx,dy,d,off,cx,cy;
  for(i=0;i<state.links.length;i++){
    lk=state.links[i];s=nodeMap.get(lk.source);t=nodeMap.get(lk.target);
    if(!s||!t)continue;
    w=lk.weight||.5;
    dx=t.x-s.x;dy=t.y-s.y;d=Math.sqrt(dx*dx+dy*dy+1);
    off=Math.min(28,d*.14);
    cx=(s.x+t.x)/2-dy/d*off;cy=(s.y+t.y)/2+dx/d*off;
    ctx.beginPath();ctx.moveTo(s.x,s.y);ctx.quadraticCurveTo(cx,cy,t.x,t.y);
    ctx.strokeStyle="rgba(140,160,255,"+Math.max(.03,w*.22)+")";
    ctx.lineWidth=.5+w*.8;ctx.stroke();
  }
  if(state.selected){
    var sel=state.selected;
    for(i=0;i<state.links.length;i++){
      lk=state.links[i];
      if(lk.source!==sel.id&&lk.target!==sel.id)continue;
      s=nodeMap.get(lk.source);t=nodeMap.get(lk.target);
      if(!s||!t)continue;
      dx=t.x-s.x;dy=t.y-s.y;d=Math.sqrt(dx*dx+dy*dy+1);
      off=Math.min(28,d*.14);
      ctx.save();ctx.shadowColor=COLORS[sel.type]||"#818cf8";ctx.shadowBlur=10;
      ctx.beginPath();ctx.moveTo(s.x,s.y);
      ctx.quadraticCurveTo((s.x+t.x)/2-dy/d*off,(s.y+t.y)/2+dx/d*off,t.x,t.y);
      ctx.strokeStyle=COLORS[sel.type]||"#818cf8";ctx.lineWidth=1.8;
      ctx.globalAlpha=.55;ctx.stroke();ctx.restore();ctx.globalAlpha=1;
    }
  }
  var p,px,py,pa;
  for(i=0;i<state.pulses.length;i++){
    p=state.pulses[i];
    px=p.sx+(p.tx-p.sx)*p.p;py=p.sy+(p.ty-p.sy)*p.p;
    pa=Math.sin(p.p*Math.PI);
    ctx.save();ctx.shadowColor=p.col;ctx.shadowBlur=12;
    ctx.beginPath();ctx.arc(px,py,2.5,0,Math.PI*2);
    ctx.fillStyle=p.col;ctx.globalAlpha=pa*.85;ctx.fill();
    ctx.restore();ctx.globalAlpha=1;
  }
  var n,isSel,isHov,col,r,breathe;
  for(i=0;i<state.nodes.length;i++){
    n=state.nodes[i];
    isSel=state.selected&&state.selected.id===n.id;
    isHov=hoveredNode&&hoveredNode.id===n.id;
    col=COLORS[n.type]||"#94a3b8";
    breathe=1+.07*Math.sin(state.time*1.5+n.x*.01);
    r=n.radius*(isSel?1.6:isHov?1.3:1)*breathe;
    ctx.save();ctx.shadowColor=col;ctx.shadowBlur=isSel?22:isHov?14:7;
    ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);
    ctx.fillStyle=col;ctx.globalAlpha=isSel?1:isHov?.95:.82;ctx.fill();
    ctx.restore();
    ctx.beginPath();ctx.arc(n.x,n.y,r*.45,0,Math.PI*2);
    ctx.fillStyle="#fff";ctx.globalAlpha=isSel?.85:isHov?.5:.25;ctx.fill();
    ctx.globalAlpha=1;
    if(isSel){
      ctx.beginPath();ctx.arc(n.x,n.y,r+4,0,Math.PI*2);
      ctx.strokeStyle="rgba(255,255,255,.45)";ctx.lineWidth=1;ctx.stroke();
    }
  }
  ctx.save();ctx.font="600 10px Inter,sans-serif";ctx.textAlign="center";
  var shown=new Set();
  var entries=Object.entries(REGIONS);
  for(i=0;i<entries.length;i++){
    var type=entries[i][0],reg=entries[i][1];
    if(shown.has(reg.label))continue;shown.add(reg.label);
    var pos=toCanvas(reg.x,reg.y-.09);
    ctx.fillStyle=COLORS[type]||"#64748b";ctx.globalAlpha=.18;
    ctx.fillText(reg.label.toUpperCase(),pos.x,pos.y);
  }
  ctx.restore();
}
canvas.addEventListener("click",function(e){
  var r=canvas.getBoundingClientRect();
  var mx=e.clientX-r.left,my=e.clientY-r.top;
  var best=null,bestD=25;
  for(var i=0;i<state.nodes.length;i++){
    var n=state.nodes[i];
    var d=Math.hypot(n.x-mx,n.y-my);
    if(d<bestD){bestD=d;best=n}
  }
  state.selected=best;updatePanel();
});
canvas.addEventListener("mousemove",function(e){
  var r=canvas.getBoundingClientRect();
  var mx=e.clientX-r.left,my=e.clientY-r.top;
  var best=null,bestD=20;
  for(var i=0;i<state.nodes.length;i++){
    var n=state.nodes[i];
    var d=Math.hypot(n.x-mx,n.y-my);
    if(d<bestD){bestD=d;best=n}
  }
  hoveredNode=best;
  canvas.style.cursor=best?"pointer":"default";
  if(best){
    tooltipEl.style.display="block";
    tooltipEl.style.left=(e.clientX+14)+"px";
    tooltipEl.style.top=(e.clientY-10)+"px";
    tooltipEl.querySelector(".tt-type").textContent=best.type;
    tooltipEl.querySelector(".tt-type").style.color=COLORS[best.type]||"#94a3b8";
    var txt=best.content.length>120?best.content.substring(0,120)+"...":best.content;
    tooltipEl.querySelector(".tt-text").textContent=txt;
  }else{tooltipEl.style.display="none"}
});
document.getElementById("refresh").addEventListener("click",loadGraph);
document.getElementById("clear").addEventListener("click",function(){
  document.getElementById("project").value="";
  document.getElementById("memoryType").value="";
  document.getElementById("limit").value="160";
  document.getElementById("neighbors").value="5";
  document.getElementById("similarity").value="0.30";
  document.getElementById("days").value="";
  loadGraph();
});
function loop(){physics();updatePulses();render();requestAnimationFrame(loop)}
resize();loadGraph();loop();
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
