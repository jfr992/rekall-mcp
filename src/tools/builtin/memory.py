"""Memory tools for MCP.

Provides persistent memory capabilities for AI assistants via MCP.

Tools:
- save_memory: Save a memory (decision, preference, learning, note)
- recall_memories: Search memories semantically
- get_project_context: Get all context for a project
- memory_stats: Get memory system statistics
"""

from typing import TYPE_CHECKING

from ..base import BaseToolProvider, ToolDefinition

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _get_manager():
    """Lazy import to avoid circular dependencies."""
    from memory import MemoryManager

    return MemoryManager()


class MemoryTools(BaseToolProvider):
    """Memory tools for persistent AI context.

    These tools allow AI assistants to:
    - Save important information (decisions, preferences, learnings)
    - Recall relevant context using semantic search
    - Get project-specific context
    - Monitor memory system health
    """

    name = "memory"
    description = "Persistent memory for AI assistants"
    requires = []  # No external requirements
    builtin = True

    def __init__(self):
        self._manager = None

    @property
    def manager(self):
        """Lazy-load the memory manager."""
        if self._manager is None:
            self._manager = _get_manager()
        return self._manager

    def get_tools(self) -> list[ToolDefinition]:
        """Return list of memory tools."""
        return [
            ToolDefinition(
                name="save_memory",
                description="Save a memory for future recall",
                handler=self.save_memory,
            ),
            ToolDefinition(
                name="recall_memories",
                description="Search memories semantically",
                handler=self.recall_memories,
            ),
            ToolDefinition(
                name="get_project_context",
                description="Get all context for a project",
                handler=self.get_project_context,
            ),
            ToolDefinition(
                name="get_cached_context",
                description="Get stable context optimized for prompt caching",
                handler=self.get_cached_context,
            ),
            ToolDefinition(
                name="memory_stats",
                description="Get memory system statistics",
                handler=self.memory_stats,
            ),
        ]

    async def save_memory(
        self,
        content: str,
        memory_type: str = "note",
        project: str | None = None,
    ) -> str:
        """Save a memory for future recall.

        Memories are automatically:
        - Sanitized (credentials removed)
        - Indexed for semantic search
        - Stored persistently

        Args:
            content: The content to save
            memory_type: Type of memory (decision, preference, learning, note)
            project: Optional project name to associate with

        Returns:
            Confirmation message with memory ID
        """
        memory_id = self.manager.save(
            content=content,
            type=memory_type,
            project=project,
        )

        return f"Saved memory: {memory_id}"

    async def recall_memories(
        self,
        query: str,
        limit: int = 5,
        memory_type: str | None = None,
        project: str | None = None,
        days: int | None = None,
        formatted: bool = True,
    ) -> str:
        """Search memories using semantic similarity.

        Finds memories that are semantically similar to the query,
        even if they don't contain the exact words.

        Args:
            query: What to search for
            limit: Maximum number of results
            memory_type: Filter by type (decision, preference, requirement, learning, note, fact)
            project: Filter by project
            days: Only include memories from last N days
            formatted: If True, returns with guidance on how to use each memory type

        Returns:
            Formatted list of matching memories with guidance
        """
        if formatted:
            # Use smart formatting that guides AI behavior
            return self.manager.recall_formatted(
                query=query,
                limit=limit,
                type=memory_type,
                project=project,
                days_back=days,
            )

        # Raw format for backward compatibility
        results = self.manager.recall(
            query=query,
            limit=limit,
            type=memory_type,
            project=project,
            days_back=days,
        )

        if not results:
            return "No memories found matching your query."

        output = f"Found {len(results)} memory/memories:\n\n"

        for r in results:
            score = r.get("score", 0)
            content = r.get("content", "")
            mem_type = r.get("type", "note")
            mem_project = r.get("project", "")
            date = r.get("date", "")

            output += f"**[{score:.2f}] {mem_type}**"
            if mem_project:
                output += f" ({mem_project})"
            if date:
                output += f" - {date}"
            output += f"\n{content}\n\n"

        return output

    async def get_project_context(self, project: str) -> str:
        """Get all context for a specific project.

        Returns all memories associated with a project,
        organized chronologically.

        Args:
            project: Project name

        Returns:
            Formatted project context
        """
        context = self.manager.get_project_context(project)

        if not context or context.strip() == f"# Project Context: {project}":
            return f"No memories found for project: {project}"

        return context

    async def get_cached_context(self, project: str | None = None) -> str:
        """Get stable context optimized for prompt caching.

        Unlike recall_memories (which varies by query), this returns
        IDENTICAL content each call - perfect for prompt cache hits.

        Use this at session start, then include in every message
        to get 90% discount on context tokens after turn 1.

        Args:
            project: Optional project to filter context

        Returns:
            Stable, cacheable context string
        """
        from memory.cache_context import CacheableContext, estimate_tokens

        ctx = CacheableContext(project=project)
        content = ctx.get_stable_context()
        tokens = estimate_tokens(content)

        return f"{content}\n<!-- Cache hash: {ctx.get_cache_hash()} | ~{tokens} tokens -->"

    async def memory_stats(self) -> str:
        """Get memory system statistics.

        Returns information about:
        - Total memories stored
        - Memories by type
        - Storage location
        - Performance metrics

        Returns:
            Formatted statistics
        """
        stats = self.manager.get_stats()

        output = "# Memory System Statistics\n\n"
        output += f"**Total Memories**: {stats.get('total', 0)}\n"
        output += f"**Memory Files**: {stats.get('files', 0)}\n"
        output += f"**Storage**: {stats.get('storage_path', 'N/A')}\n\n"

        by_type = stats.get("by_type", {})
        if by_type:
            output += "## By Type\n"
            for t, count in sorted(by_type.items()):
                output += f"- {t}: {count}\n"

        return output

    def register(self, mcp: "FastMCP") -> list[str]:
        """Register memory tools with MCP server.

        Args:
            mcp: FastMCP server instance

        Returns:
            List of registered tool names
        """
        registered = []

        @mcp.tool()
        async def save_memory(
            content: str,
            memory_type: str = "note",
            project: str | None = None,
        ) -> str:
            """Save a memory for future recall.

            Memories persist across sessions, helping AI assistants remember
            important context. Choose the right type:

            - **preference**: User's preferred way of doing things (flexible, offer alternatives)
            - **decision**: A choice that was made (established, but can be revisited)
            - **requirement**: A hard constraint that must be followed (non-negotiable)
            - **fact**: Contextual information about the environment (informational)
            - **learning**: Something learned during work (for future reference)
            - **note**: General information (default)

            Credentials are automatically sanitized before storage.

            Args:
                content: What to remember
                memory_type: Type (preference, decision, requirement, fact, learning, note)
                project: Optional project to associate with
            """
            return await self.save_memory(content, memory_type, project)

        registered.append("save_memory")

        @mcp.tool()
        async def recall_memories(
            query: str,
            limit: int = 5,
            memory_type: str | None = None,
            project: str | None = None,
            days: int | None = None,
        ) -> str:
            """Search memories using semantic similarity.

            Finds relevant memories even if they don't contain exact keywords.
            "What technology did we choose?" finds "Decided to use Python"

            Results are formatted with guidance on how to use each type:
            - Preferences: Show as default but offer alternatives
            - Decisions: Reference but ask if user wants to reconsider
            - Requirements: Must be followed
            - Facts: Informational context

            Args:
                query: What to search for
                limit: Maximum results (default: 5)
                memory_type: Filter by type
                project: Filter by project
                days: Only last N days
            """
            return await self.recall_memories(query, limit, memory_type, project, days)

        registered.append("recall_memories")

        @mcp.tool()
        async def get_project_context(project: str) -> str:
            """Get all context for a project.

            Returns all memories associated with a project,
            organized chronologically. Useful at the start of a session
            to understand what's been done before.

            Args:
                project: Project name
            """
            return await self.get_project_context(project)

        registered.append("get_project_context")

        @mcp.tool()
        async def memory_stats() -> str:
            """Get memory system statistics.

            Shows how many memories are stored, breakdown by type,
            and storage location.
            """
            return await self.memory_stats()

        registered.append("memory_stats")

        @mcp.tool()
        async def get_cached_context(project: str | None = None) -> str:
            """Get stable context optimized for prompt caching.

            Returns IDENTICAL content each call (unlike recall which varies).
            Perfect for prompt cache hits - 90% token discount after turn 1.

            Call once at session start, include in system prompt.
            Every subsequent turn hits the cache.

            Args:
                project: Optional project to filter context
            """
            return await self.get_cached_context(project)

        registered.append("get_cached_context")

        return registered
