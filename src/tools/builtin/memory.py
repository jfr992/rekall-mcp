"""Optimized memory tools with automatic observation capture.

Based on best practices from:
- LangChain: Thread-based persistence, prompt caching patterns
- Qdrant: Payload filtering, keyword indexes
- Semantic Kernel: Hybrid short/long-term memory
- Anthropic: Tool-based memory with structured operations
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from memory.scope import ScopeDetector

from ..base import BaseToolProvider, ToolDefinition

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ==============================================================================
# TYPE CLASSIFICATION: Embedding-Enhanced Hybrid
# ==============================================================================

# Pre-computed example embeddings (loaded once, cached)
_TYPE_EMBEDDINGS_CACHE: dict[str, list[float]] | None = None


def _get_type_embeddings(embedder) -> dict[str, list[float]]:
    """Lazy-load and cache type centroid embeddings (3 examples per type, averaged)."""
    import numpy as np

    global _TYPE_EMBEDDINGS_CACHE

    if _TYPE_EMBEDDINGS_CACHE is None:
        examples = {
            "decision": [
                "Decided to use PostgreSQL over MySQL for better JSON support and performance",
                "Going with React instead of Vue for the frontend framework",
                "Chose to implement microservices rather than monolith architecture",
            ],
            "learning": [
                "Fixed bug where JWT validation fails when issuer URL has trailing slash",
                "Discovered that connection pool must be closed before shutdown",
                "Learned that pytest fixtures are shared across the module by default",
            ],
            "preference": [
                "User prefers Terraform over CloudFormation for infrastructure as code",
                "Likes using type hints extensively in all Python code",
                "Prefers short functions with clear names over lengthy comments",
            ],
            "requirement": [
                "Must use Python 3.11 or higher due to required type hint features",
                "Cannot deploy to production without passing all integration tests",
                "Required to encrypt all data at rest using AES-256",
            ],
            "fact": [
                "Production database runs on AWS RDS PostgreSQL in us-east-1 region",
                "The CI pipeline is configured in GitHub Actions with 3 parallel runners",
                "API gateway is hosted at api.example.com behind CloudFront",
            ],
        }
        _TYPE_EMBEDDINGS_CACHE = {}
        for mem_type, texts in examples.items():
            vecs = [embedder.encode(t) for t in texts]
            centroid = np.mean(vecs, axis=0).tolist()
            _TYPE_EMBEDDINGS_CACHE[mem_type] = centroid

    return _TYPE_EMBEDDINGS_CACHE


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two vectors using numpy."""
    import numpy as np

    a = np.asarray(vec1)
    b = np.asarray(vec2)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _classify_by_embedding(summary: str, embedder) -> str:
    """Classify using embedding similarity.

    Best practice from Qdrant: Use semantic similarity for classification
    when you have a small set of known categories.
    """
    summary_vec = embedder.encode(summary)
    type_embeddings = _get_type_embeddings(embedder)

    best_type = "learning"  # default
    best_score = 0.6  # threshold (tune based on testing)

    for mem_type, example_vec in type_embeddings.items():
        score = _cosine_similarity(summary_vec, example_vec)
        if score > best_score:
            best_score = score
            best_type = mem_type

    return best_type


def _classify_by_keywords(summary: str) -> str:
    """Fallback keyword-based classification.

    Best practice: Have a fast fallback for when embeddings aren't ready.
    """
    s = summary.lower()

    # Decision indicators (broader patterns from research)
    if any(
        w in s
        for w in [
            "decided",
            "chose",
            "selected",
            "using",
            "going with",
            "picked",
            "opted for",
            "switching to",
            "migrating to",
        ]
    ):
        return "decision"

    # Learning/Bug indicators
    if any(
        w in s
        for w in [
            "fixed",
            "bug",
            "issue",
            "gotcha",
            "discovered",
            "learned",
            "found out",
            "realized",
            "turns out",
            "doesn't work",
            "fails",
            "problem",
            "solution",
            "workaround",
        ]
    ):
        return "learning"

    # Preference indicators
    if any(
        w in s
        for w in ["prefer", "prefers", "likes", "wants", "favorite", "better to", "easier to"]
    ):
        return "preference"

    # Requirement indicators (explicit constraints)
    if any(
        w in s
        for w in ["must", "required", "need to", "has to", "mandatory", "cannot", "should not"]
    ):
        return "requirement"

    # Fact indicators
    if any(w in s for w in ["is located", "runs on", "uses", "has", "located at"]):
        return "fact"

    # Default to learning (most common auto-capture type)
    return "learning"


def _classify_smart(summary: str, embedder) -> str:
    """Hybrid classification: embeddings → keywords → default.

    Best practice from research:
    - Try embedding similarity first (better quality, ~11ms)
    - Fallback to keywords if embeddings fail (fast, always works)
    - Always have a safe default
    """
    try:
        # Try embedding-based classification (better quality)
        return _classify_by_embedding(summary, embedder)
    except Exception:
        # Fallback to keywords (faster, simpler)
        return _classify_by_keywords(summary)


# ==============================================================================
# OPTIMIZED MEMORY TOOLS
# ==============================================================================


class OptimizedMemoryTools(BaseToolProvider):
    """Memory tools with automatic observation capture and optimizations.

    Architecture based on research:
    - Automatic capture via tool (like Anthropic memory tool)
    - Embedding-enhanced classification (Qdrant best practices)
    - Keyword indexes on type/project/date (Qdrant optimization)
    - Thread-aware for future conversation support (LangChain pattern)
    """

    name = "memory"
    description = "Persistent memory with automatic observation capture"
    requires = []
    builtin = True

    def __init__(self):
        self._manager = None

    @property
    def manager(self):
        """Lazy-load the memory manager."""
        if self._manager is None:
            from memory import MemoryManager

            self._manager = MemoryManager()
        return self._manager

    def get_tools(self) -> list[ToolDefinition]:
        """Return list of memory tools."""
        from tools.base import ToolDefinition

        return [
            ToolDefinition(
                name="observe",
                description="Record what was just accomplished (automatic memory capture)",
                handler=None,  # Registered via mcp.tool() in register()
            ),
            ToolDefinition(
                name="recall_memories",
                description="Search memories using hybrid BM25 + semantic search (exact terms AND meaning)",
                handler=None,
            ),
            ToolDefinition(
                name="save_memory",
                description="Manually save a memory for future recall",
                handler=None,
            ),
            ToolDefinition(
                name="get_cached_context",
                description="Get stable context optimized for prompt caching",
                handler=None,
            ),
            ToolDefinition(
                name="get_hierarchical_context",
                description="Get hierarchy of memories grouped by inferred topics",
                handler=None,
            ),
            ToolDefinition(
                name="skill_context",
                description="Infer skills from recurring memory themes",
                handler=None,
            ),
            ToolDefinition(
                name="memory_stats",
                description="Get memory system statistics",
                handler=None,
            ),
            ToolDefinition(
                name="consolidate_memories",
                description="Find superseded or contradictory memories and return consolidation hints",
                handler=None,
            ),
            ToolDefinition(
                name="proactive_context_summary",
                description="Generate a proactive memory summary ordered by signal strength",
                handler=None,
            ),
            ToolDefinition(
                name="resume_packet",
                description="Get a continuity-oriented resume packet for Claude Code or Codex session start",
                handler=None,
            ),
            ToolDefinition(
                name="memory_lifecycle",
                description="Explain memory tiers and retention behavior for the current project",
                handler=None,
            ),
            ToolDefinition(
                name="handoff_summary",
                description="Get a startup handoff summary with next steps and recent momentum",
                handler=None,
            ),
            ToolDefinition(
                name="memory_pressure",
                description="Inspect memory pressure and cleanup candidates for the current project",
                handler=None,
            ),
            ToolDefinition(
                name="agent_startup",
                description="Get a single startup payload for Claude Code or Codex sessions",
                handler=None,
            ),
            ToolDefinition(
                name="prune_plan",
                description="Build a safe prune plan (does not delete). Apply is REST-only.",
                handler=None,
            ),
            ToolDefinition(
                name="memory_detail",
                description="Fetch a single memory by id with its 1-hop graph neighbors",
                handler=None,
            ),
            ToolDefinition(
                name="memory_kb",
                description="Typed semantic slices of the knowledge base: decisions, requirements, preferences, learnings",
                handler=None,
            ),
            ToolDefinition(
                name="memory_pressure_snapshot",
                description="Structured memory pressure snapshot (load_score, capacity, flagged, candidates)",
                handler=None,
            ),
            ToolDefinition(
                name="backfill_lifecycle",
                description="One-shot backfill: compute tier/durability for existing memories (dry_run by default)",
                handler=None,
            ),
        ]

    def _get_current_scope(self, project: str | None = None):
        """Detect full scope, not just cwd basename."""
        return ScopeDetector.detect(project=project)

    def register(self, mcp: FastMCP) -> list[str]:
        """Register optimized memory tools."""
        registered = []

        @mcp.tool(structured_output=False)
        async def observe(summary: str, type: str = "auto", context: str | None = None) -> str:
            """Record what was just accomplished for future reference.

            **AUTOMATIC USAGE (call after operations):**
            - After fixing bugs/issues
            - After making architectural/design decisions
            - After discovering gotchas or limitations
            - When user states preferences or requirements

            **Smart Classification:**
            The system uses embedding similarity to classify observations:
            - "decision": Technical/architectural choices
            - "learning": Bug fixes, discoveries, gotchas
            - "preference": User's preferred way of working
            - "requirement": Hard constraints (must/cannot)
            - "fact": Contextual information (locations, configs)
            - "auto": Let system detect (default)

            **Examples:**
            observe("Fixed JWT validation bug with trailing slash")
            observe("Decided to use React for frontend", type="decision")
            observe("User prefers Terraform over CloudFormation")
            observe("API rate limit is 100/hour", type="fact")

            Args:
                summary: What was accomplished (1-2 sentences)
                type: Memory type or "auto" for automatic classification
                context: Optional: Why this matters or what prompted it
            """
            scope = self._get_current_scope()

            if type == "auto":
                type = _classify_smart(summary, self.manager.embedder)

            result = self.manager.observe(
                summary=summary,
                type=type,
                project=scope.project,
                scope=scope,
                context=context,
            )

            if isinstance(result, str):
                return f"✓ Observed as {type}: {result}\n\nAvailable for recall in future sessions."

            return f"Skipped memory save ({result.reason}, salience={result.salience:.2f})"

        registered.append("observe")

        @mcp.tool(structured_output=False)
        async def recall_memories(
            query: str,
            limit: int = 5,
            memory_type: str | None = None,
            project: str | None = None,
            days: int | None = None,
        ) -> str:
            """Search memories using hybrid BM25 + semantic search.

            Uses RRF (Reciprocal Rank Fusion) to combine:
            - BM25 sparse vectors: exact term matching (great for ticket IDs, error codes, names)
            - Dense semantic vectors: meaning-based similarity (great for concepts, paraphrasing)

            Use this for:
            - Exact lookups: "TOPE-123", "SCRAM-SHA-256", "stable_hash_id"
            - Semantic queries: "authentication problems", "database connection issues"
            - Mixed: "pgbouncer connection pooling" (finds both exact and semantic matches)

            Args:
                query: What to search for (exact terms or conceptual queries both work)
                limit: Maximum results (default: 5)
                memory_type: Filter by type (decision, learning, preference, requirement, fact)
                project: Filter by project name
                days: Only include memories from last N days
            """
            return self.manager.recall_formatted(
                query=query, limit=limit, type=memory_type, project=project, days_back=days
            )

        registered.append("recall_memories")

        @mcp.tool(structured_output=False)
        async def save_memory(
            content: str,
            memory_type: str = "note",
            project: str | None = None,
            context: str | None = None,
        ) -> str:
            """Save a memory explicitly (manual mode).

            Use this when you want to save something important that doesn't
            fit the automatic observe() pattern (like session summaries).

            For regular operations (bug fixes, decisions), use observe() instead.

            Args:
                content: What to remember
                memory_type: Type (decision, learning, preference, requirement, fact, note)
                project: Optional project to associate with
                context: Optional: why this matters, appended to content as "Context: ..."
            """
            scope = self._get_current_scope(project=project)
            full_content = content if not context else f"{content}\n\nContext: {context}"
            memory_id = self.manager.save(
                content=full_content,
                type=memory_type,
                project=scope.project,
                scope=scope,
            )
            return f"Saved memory: {memory_id}"

        registered.append("save_memory")

        @mcp.tool(structured_output=False)
        async def get_cached_context(project: str | None = None) -> str:
            """Get stable context optimized for prompt caching.

            Best practice from LangChain:
            - Returns IDENTICAL content each call (unlike recall which varies)
            - Perfect for prompt cache hits (90% token discount after turn 1)
            - Call once at session start, include in system prompt

            Args:
                project: Optional project to filter context
            """
            from memory.cache_context import CacheableContext, estimate_tokens

            ctx = CacheableContext(project=project, storage_path=str(self.manager.memory_dir))
            content = ctx.get_stable_context()
            tokens = estimate_tokens(content)

            return f"{content}\n<!-- Cache hash: {ctx.get_cache_hash()} | ~{tokens} tokens -->"

        registered.append("get_cached_context")

        @mcp.tool(structured_output=False)
        async def get_hierarchical_context(
            project: str | None = None,
            max_topics: int = 8,
            similarity_threshold: float = 0.72,
        ) -> str:
            """Get topic-grouped memory context.

            Best practice from knowledge management:
            - Cluster related memories by vector similarity
            - Render stable sections by inferred topics
            - Helps with large context retrieval and dashboard workflows

            Args:
                project: Optional project filter.
                max_topics: Maximum number of topics to return.
                similarity_threshold: Vector similarity needed for topic merges.
            """
            return self.manager.get_hierarchical_project_context(
                project=project,
                max_topics=max_topics,
                similarity_threshold=similarity_threshold,
            )

        registered.append("get_hierarchical_context")

        @mcp.tool(structured_output=False)
        async def skill_context(
            project: str | None = None,
            min_mentions: int = 2,
            max_skills: int = 8,
        ) -> str:
            """Infer likely skills from memory clusters.

            Repetitive technical terms across memories are grouped as candidate
            skills to support planning and handoff workflows.
            """
            return self.manager.get_skill_context(
                project=project,
                min_mentions=min_mentions,
                max_skills=max_skills,
            )

        registered.append("skill_context")

        @mcp.tool(structured_output=False)
        async def memory_stats() -> str:
            """Get memory system statistics and health."""
            stats = self.manager.get_stats()

            output = "# Memory System Statistics\n\n"
            output += f"**Total Memories**: {stats.get('total_memories', 0)}\n"
            output += f"**Memory Files**: {stats.get('memory_files', 0)}\n"
            output += f"**Storage**: {stats.get('memory_dir', 'N/A')}\n\n"

            by_type = stats.get("by_type", {})
            if by_type:
                output += "## By Type\n"
                for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
                    output += f"- {t}: {count}\n"

            return output

        registered.append("memory_stats")

        @mcp.tool(structured_output=False)
        async def consolidate_memories(
            project: str | None = None,
            limit: int = 240,
            save_summary: bool = False,
        ) -> str:
            """Detect potential duplicate, superseded, and contradictory memories.

            Returns:
                Markdown summary of consolidation candidates.
            """
            return self.manager.consolidate_memories(
                project=project,
                limit=limit,
                save_summary=save_summary,
            )

        registered.append("consolidate_memories")

        @mcp.tool(structured_output=False)
        async def proactive_context_summary(
            project: str | None = None,
            limit: int = 120,
        ) -> str:
            """Generate a proactive memory summary ordered by likely signal value."""
            return self.manager.get_proactive_context_summary(
                project=project,
                limit=limit,
            )

        registered.append("proactive_context_summary")

        @mcp.tool(structured_output=False)
        async def resume_packet(project: str | None = None, limit: int = 12) -> str:
            """Return a session-start continuity packet for the current agent scope."""
            scope = self._get_current_scope(project=project)
            packet = self.manager.get_resume_packet(project=scope.project, scope=scope, limit=limit)
            return packet["summary"]

        registered.append("resume_packet")

        @mcp.tool(structured_output=False)
        async def memory_lifecycle(project: str | None = None, limit: int = 20) -> str:
            """Summarize tiering and retention for recent project memories."""
            scope = self._get_current_scope(project=project)
            points = self.manager.store.scroll(filters={"project": scope.project}, limit=limit)
            if not points:
                return "No memories found."

            lines = [f"# Memory Lifecycle: {scope.project}", ""]
            for point in points:
                tier = point.get("tier", "working")
                retention = point.get("retention_days", "?")
                lines.append(
                    f"- [{tier}] [{point.get('type', 'note')}] {point.get('content', '')[:120]} (retention={retention}d)"
                )
            return "\n".join(lines)

        registered.append("memory_lifecycle")

        @mcp.tool(structured_output=False)
        async def handoff_summary(project: str | None = None, limit: int = 12) -> str:
            """Return a momentum-oriented handoff summary for session startup."""
            scope = self._get_current_scope(project=project)
            packet = self.manager.get_resume_packet(project=scope.project, scope=scope, limit=limit)
            return packet.get("handoff", packet["summary"])

        registered.append("handoff_summary")

        @mcp.tool(structured_output=False)
        async def memory_pressure(project: str | None = None, limit: int = 40) -> str:
            """Inspect memory pressure for the current project."""
            from memory.pressure import identify_pressure, render_pressure_report

            scope = self._get_current_scope(project=project)
            points = self.manager.store.scroll(filters={"project": scope.project}, limit=limit)
            pressure = identify_pressure(points)
            return render_pressure_report(pressure)

        registered.append("memory_pressure")

        @mcp.tool(structured_output=False)
        async def agent_startup(
            project: str | None = None, agent: str | None = None, limit: int = 12
        ) -> str:
            """Get one startup summary for agent clients."""
            payload = self.manager.get_agent_startup(project=project, agent=agent, limit=limit)
            return payload["startup_summary"]

        registered.append("agent_startup")

        @mcp.tool(structured_output=False)
        async def prune_plan(project: str | None = None, limit: int = 200) -> str:
            """Build a safe prune plan. Identity tier and memories without explicit
            salience are never selected. Returns a plan_id that the UI (NOT an agent)
            can later apply via the REST endpoint.

            Args:
                project: Project to plan prune for (defaults to current scope)
                limit: Max candidates (default 200)
            """
            scope = self._get_current_scope(project=project)
            from memory.prune import build_plan

            plan = build_plan(self.manager, project=scope.project, limit=limit)
            return (
                f"Plan {plan.plan_id} — {len(plan.candidates)} candidates "
                f"(expires {plan.expires_at.isoformat()})\n"
                f"(Apply via REST only: POST /api/memory/prune/apply)"
            )

        registered.append("prune_plan")

        @mcp.tool(structured_output=False)
        async def rebuild_knowledge_graph() -> str:
            """Rebuild the knowledge graph from all existing memories."""
            stats = self.manager.knowledge_graph.rebuild(
                store=self.manager.store,
                embedder=self.manager.embedder,
            )
            return (
                f"Graph rebuilt: {stats['nodes']} nodes, {stats['edges']} edges "
                f"({stats['duration_ms']}ms)"
            )

        registered.append("rebuild_knowledge_graph")

        @mcp.tool(structured_output=False)
        async def backfill_lifecycle(dry_run: bool = True, project: str | None = None) -> str:
            """Backfill tier/durability on existing memories.

            Args:
                dry_run: If True, report what would change without writing (default True)
                project: Optional project filter
            """
            report = self.manager.backfill_lifecycle(dry_run=dry_run, project=project)
            return f"Backfill (dry_run={dry_run}) — total {report['total']}: " + ", ".join(
                f"{k}={v}" for k, v in report["updated_by_tier"].items()
            )

        registered.append("backfill_lifecycle")

        @mcp.tool(structured_output=False)
        async def memory_pressure_snapshot(project: str | None = None) -> str:
            """Return structured memory pressure for the current project.

            Args:
                project: Optional project filter
            """
            from memory.pressure import identify_pressure, render_pressure_report

            scope = self._get_current_scope(project=project)
            filters = {"project": scope.project} if scope.project else None
            memories = self.manager.store.scroll(filters=filters, limit=2000)
            pressure = identify_pressure(memories)
            return render_pressure_report(pressure)

        registered.append("memory_pressure_snapshot")

        @mcp.tool(structured_output=False)
        async def memory_kb(project: str | None = None) -> str:
            """Return typed KB slices: decisions, requirements, preferences, learnings.

            Args:
                project: Optional project filter
            """
            scope = self._get_current_scope(project=project)
            filters = {"project": scope.project} if scope.project else None
            points = self.manager.store.scroll(filters=filters, limit=2000)
            slices = {
                "decisions": [p for p in points if p.get("type") == "decision"],
                "requirements": [p for p in points if p.get("type") == "requirement"],
                "preferences": [p for p in points if p.get("type") == "preference"],
                "learnings": [p for p in points if p.get("type") == "learning"],
            }
            lines = [f"# KB: {scope.project}"]
            for name, items in slices.items():
                lines.append(f"\n## {name.title()} ({len(items)})")
                for item in items[:10]:
                    lines.append(
                        f"- [{item.get('tier', 'working')}] {item.get('content', '')[:140]}"
                    )
            return "\n".join(lines)

        registered.append("memory_kb")

        @mcp.tool(structured_output=False)
        async def memory_detail(memory_id: str) -> str:
            """Fetch a single memory by id with its 1-hop graph neighbors.

            Args:
                memory_id: The memory id to fetch
            """
            memory = self.manager.store.get_by_id(memory_id)
            if not memory:
                return f"Memory not found: {memory_id}"
            return str(memory)

        registered.append("memory_detail")

        @mcp.tool(structured_output=False)
        async def publish_memory(project: str | None = None, format: str = "okf") -> str:
            """Use when exporting memory to a shareable knowledge bundle (OKF markdown).

            Builds an OKF v0.1 bundle from memory (one project or all) and returns
            the file tree. For a downloadable .tar.gz or writing to disk, use the
            /api/memory/publish endpoint or the cockpit Export tab.

            Args:
                project: Scope to one project, or omit for all memory
                format: Export format (default: okf)
            """
            from memory.publish import publish_from_manager

            bundle = publish_from_manager(self.manager, project=project, fmt=format)
            header = (
                f"OKF bundle — {bundle.stats.get('concepts', 0)} concepts, "
                f"{bundle.stats.get('clusters', 0)} clusters, "
                f"titled by {bundle.stats.get('titled_by', 'slug')}"
            )
            return "\n".join([header, ""] + bundle.tree)

        registered.append("publish_memory")

        return registered
