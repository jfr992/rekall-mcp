"""Optimized memory tools with automatic observation capture.

Based on best practices from:
- LangChain: Thread-based persistence, prompt caching patterns
- Qdrant: Payload filtering, keyword indexes
- Semantic Kernel: Hybrid short/long-term memory
- Anthropic: Tool-based memory with structured operations
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

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
                description="Search memories semantically",
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
                name="memory_stats",
                description="Get memory system statistics",
                handler=None,
            ),
        ]

    def _get_current_project(self) -> str:
        """Extract project from working directory.

        Best practice from Semantic Kernel: Auto-detect context.
        """
        try:
            return Path(os.getcwd()).name
        except Exception:
            return "general"

    def register(self, mcp: FastMCP) -> list[str]:
        """Register optimized memory tools."""
        registered = []

        @mcp.tool()
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
            # Get current project (Semantic Kernel pattern)
            project = self._get_current_project()

            # Classify type (Qdrant + embedding best practice)
            if type == "auto":
                type = _classify_smart(summary, self.manager.embedder)

            # Build full content
            full_content = summary
            if context:
                full_content = f"{summary}\n\nContext: {context}"

            # Save (creates keyword indexes automatically)
            memory_id = self.manager.save(content=full_content, type=type, project=project)

            return f"✓ Observed as {type}: {memory_id}\n\nAvailable for recall in future sessions."

        registered.append("observe")

        @mcp.tool()
        async def recall_memories(
            query: str,
            limit: int = 5,
            memory_type: str | None = None,
            project: str | None = None,
            days: int | None = None,
        ) -> str:
            """Search memories using semantic similarity.

            Best practice from LangChain/Qdrant:
            - Semantic search finds meaning, not just keywords
            - Filter by type/project/date for precise results
            - Returns formatted with guidance on how to use each type

            Args:
                query: What to search for
                limit: Maximum results (default: 5)
                memory_type: Filter by type (decision, learning, preference, requirement, fact)
                project: Filter by project name
                days: Only include memories from last N days
            """
            return self.manager.recall_formatted(
                query=query, limit=limit, type=memory_type, project=project, days_back=days
            )

        registered.append("recall_memories")

        @mcp.tool()
        async def save_memory(
            content: str, memory_type: str = "note", project: str | None = None
        ) -> str:
            """Save a memory explicitly (manual mode).

            Use this when you want to save something important that doesn't
            fit the automatic observe() pattern (like session summaries).

            For regular operations (bug fixes, decisions), use observe() instead.

            Args:
                content: What to remember
                memory_type: Type (decision, learning, preference, requirement, fact, note)
                project: Optional project to associate with
            """
            memory_id = self.manager.save(content=content, type=memory_type, project=project)
            return f"Saved memory: {memory_id}"

        registered.append("save_memory")

        @mcp.tool()
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

        @mcp.tool()
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

        return registered
