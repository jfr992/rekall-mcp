"""Memory: Persistent cross-session context for AI agents.

Usage:
    from memory import MemoryManager

    memory = MemoryManager()

    # Save what you learn
    memory.save("User prefers concise responses", type="preference")
    memory.save("Decided to use Python", type="decision", project="my-app")

    # Recall when needed
    memories = memory.recall("user preferences")

    # Get project context (cache-friendly)
    context = memory.get_project_context("my-app")

All operations:
- Sanitize credentials automatically
- Store to both file (durable) and Qdrant (searchable)
- Emit telemetry for observability
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from core import Embedder, Telemetry, VectorStore

logger = logging.getLogger(__name__)


# =============================================================================
# SANITIZER: Keep credentials out of memory
# =============================================================================


class Sanitizer:
    """Remove sensitive information before storing.

    Patterns detect:
    - API keys (generic, GitHub, OpenAI, Anthropic, AWS)
    - Passwords and secrets
    - Bearer tokens and auth headers
    - Private keys (PEM format)
    """

    PATTERNS = [
        # Generic keys
        r'(?i)(api[_-]?key|apikey)["\s:=]+["\']?[\w\-]+["\']?',
        r'(?i)(password|passwd|pwd)["\s:=]+["\']?[^\s"\']+["\']?',
        r'(?i)(secret|token)["\s:=]+["\']?[\w\-]+["\']?',
        # Auth headers
        r"(?i)(bearer\s+)[\w\-\.]+",
        r"(?i)(authorization:\s*)(basic|bearer)\s+[\w\-\.=]+",
        # Provider-specific
        r"(?i)ghp_[a-zA-Z0-9]{36}",  # GitHub PAT
        r"(?i)gho_[a-zA-Z0-9]{36}",  # GitHub OAuth
        r"(?i)sk-[a-zA-Z0-9]{48}",  # OpenAI
        r"(?i)sk-ant-[a-zA-Z0-9\-]+",  # Anthropic
        r"(?i)xox[baprs]-[\w\-]+",  # Slack
        r"(?i)AKIA[0-9A-Z]{16}",  # AWS
        # Private keys
        r"-----BEGIN[A-Z ]+-----[\s\S]+?-----END[A-Z ]+-----",
        # Generic hex (API keys)
        r"(?i)[a-f0-9]{32}",
    ]

    @classmethod
    def sanitize(cls, content: str) -> str:
        """Remove sensitive patterns from content."""
        for pattern in cls.PATTERNS:
            content = re.sub(pattern, "[REDACTED]", content)
        return content


# =============================================================================
# MEMORY MANAGER: The main interface
# =============================================================================


class MemoryManager:
    """Persistent memory with semantic search.

    Stores memories in two places:
    - Local files (~/.claude/memory/) for durability
    - Qdrant vector DB for semantic search

    All content is sanitized (credentials removed).
    All operations emit telemetry metrics.

    Example:
        memory = MemoryManager()

        # Save a decision
        memory.save("Use Python for ML ecosystem", type="decision")

        # Recall relevant memories
        results = memory.recall("technology choices")

        # Check metrics
        from core import Telemetry
        print(Telemetry.get().summary())
    """

    COLLECTION = "agent_memory"

    def __init__(
        self,
        memory_dir: str | Path = "~/.claude/memory",
        qdrant_url: str = "http://localhost:6333",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        """Initialize memory manager.

        Args:
            memory_dir: Where to store memory files
            qdrant_url: Qdrant server URL
            embedding_model: Model for embeddings
        """
        # File storage
        self.memory_dir = Path(memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Vector store (uses core infrastructure)
        self._store: VectorStore | None = None
        self._qdrant_url = qdrant_url

        # Embeddings (uses core infrastructure)
        self._embedder: Embedder | None = None
        self._embedding_model = embedding_model

        # Telemetry
        self._telemetry = Telemetry.get()

    # -------------------------------------------------------------------------
    # LAZY INITIALIZATION: Load on first use
    # -------------------------------------------------------------------------

    @property
    def store(self) -> VectorStore:
        """Get vector store, initializing if needed."""
        if self._store is None:
            self._store = VectorStore(
                collection=self.COLLECTION,
                url=self._qdrant_url,
            )
            # Create indexes for filtering
            for field in ["date", "project", "type"]:
                try:
                    self._store.create_index(field)
                except Exception:
                    pass  # Index may already exist
        return self._store

    @property
    def embedder(self) -> Embedder:
        """Get embedder, initializing if needed."""
        if self._embedder is None:
            self._embedder = Embedder(model=self._embedding_model)
        return self._embedder

    # -------------------------------------------------------------------------
    # SAVE: Store memories
    # -------------------------------------------------------------------------

    def save(
        self,
        content: str,
        type: str = "note",
        project: str | None = None,
        **metadata: Any,
    ) -> str:
        """Save a memory.

        Args:
            content: What to remember (will be sanitized)
            type: Memory type (note, decision, learning, preference, session)
            project: Project name
            **metadata: Additional metadata

        Returns:
            Memory ID

        Example:
            memory.save("User prefers diagrams", type="preference")
            memory.save("Chose hybrid architecture", type="decision", project="my-app")
        """
        with self._telemetry.track("memory.save"):
            # Sanitize
            content = Sanitizer.sanitize(content)

            # Generate ID and timestamps
            date = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().isoformat()
            memory_id = f"{date}_{type}_{hash(content) % 10000:04d}"

            # Build payload
            payload = {
                "memory_id": memory_id,
                "content": content,
                "date": date,
                "timestamp": timestamp,
                "type": type,
                "project": project or "general",
                **metadata,
            }

            # Save to file (durability)
            self._save_to_file(memory_id, content, payload, type, date)

            # Save to vector store (searchability)
            vector = self.embedder.encode(content)
            self.store.save(id=memory_id, vector=vector, payload=payload)

            logger.info(f"Saved memory: {memory_id}")
            return memory_id

    def _save_to_file(
        self,
        memory_id: str,
        content: str,
        metadata: dict,
        memory_type: str,
        date: str,
    ) -> None:
        """Save memory to human-readable YAML file."""
        yaml_file = self.memory_dir / f"{date}.yaml"

        # Load existing data for this date
        if yaml_file.exists():
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"date": date}

        # Ensure type section exists
        type_key = f"{memory_type}s"
        if type_key not in data:
            data[type_key] = []

        # Add new memory
        memory_entry = {
            "id": memory_id,
            "content": content,
            "project": metadata.get("project", "general"),
            "timestamp": metadata.get("timestamp"),
        }

        # Add any extra metadata (excluding duplicates)
        for key, value in metadata.items():
            if key not in ["memory_id", "content", "date", "timestamp", "type", "project"]:
                memory_entry[key] = value

        data[type_key].append(memory_entry)

        # Write back
        with open(yaml_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Alias for backwards compatibility
    def save_memory(
        self,
        content: str,
        memory_type: str = "note",
        project: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save a memory (alias for save())."""
        return self.save(content, type=memory_type, project=project, **(metadata or {}))

    # -------------------------------------------------------------------------
    # RECALL: Find relevant memories
    # -------------------------------------------------------------------------

    def recall(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
        type: str | None = None,
        days_back: int | None = None,
        score_threshold: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Recall relevant memories using semantic search.

        Args:
            query: What to search for
            limit: Max results
            project: Filter by project
            type: Filter by memory type
            days_back: Only search last N days
            score_threshold: Minimum similarity (0-1)

        Returns:
            List of memories with scores

        Example:
            memories = memory.recall("architecture decisions")
            memories = memory.recall("preferences", project="my-app")
        """
        with self._telemetry.track("memory.recall"):
            # Build filters
            filters = {}
            if project:
                filters["project"] = project
            if type:
                filters["type"] = type
            if days_back:
                cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                filters["date"] = {"gte": cutoff}

            # Search
            query_vector = self.embedder.encode(query)
            results = self.store.search(
                vector=query_vector,
                limit=limit,
                filters=filters if filters else None,
                score_threshold=score_threshold,
            )

            # Format results
            return [
                {
                    "score": r.get("score"),
                    "content": r.get("content"),
                    "date": r.get("date"),
                    "type": r.get("type"),
                    "project": r.get("project"),
                    "memory_id": r.get("memory_id"),
                }
                for r in results
            ]

    def recall_formatted(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
        type: str | None = None,
        days_back: int | None = None,
    ) -> str:
        """Recall memories with smart formatting that guides AI behavior.

        Unlike recall(), this returns a formatted string with:
        - Type-specific guidance (preferences are suggestions, not rules)
        - Clear indication of what's flexible vs fixed
        - Context for when memories were created

        Args:
            query: What to search for
            limit: Max results
            project: Filter by project
            type: Filter by memory type
            days_back: Only search last N days

        Returns:
            Formatted string with guidance for AI

        Example:
            context = memory.recall_formatted("deployment options")
        """
        memories = self.recall(
            query=query,
            limit=limit,
            project=project,
            type=type,
            days_back=days_back,
        )

        if not memories:
            return "No relevant memories found."

        return self._format_with_guidance(memories)

    def _format_with_guidance(self, memories: list[dict]) -> str:
        """Format memories with type-specific guidance."""
        # Group by type
        by_type: dict[str, list[dict]] = {}
        for mem in memories:
            t = mem.get("type", "note")
            by_type.setdefault(t, []).append(mem)

        sections = []

        # Preferences - explicitly mark as flexible
        if "preference" in by_type:
            prefs = by_type.pop("preference")
            lines = ["## User Preferences (suggestions, not requirements)"]
            lines.append("*Show these as the default, but always offer alternatives.*\n")
            for p in prefs:
                lines.append(f"- {p['content']} ({p.get('date', 'unknown date')})")
            sections.append("\n".join(lines))

        # Decisions - these are more fixed but can be revisited
        if "decision" in by_type:
            decisions = by_type.pop("decision")
            lines = ["## Past Decisions (established, but can be changed)"]
            lines.append("*Reference these but ask if user wants to reconsider.*\n")
            for d in decisions:
                lines.append(f"- {d['content']} ({d.get('date', 'unknown date')})")
            sections.append("\n".join(lines))

        # Requirements - these are hard constraints
        if "requirement" in by_type:
            reqs = by_type.pop("requirement")
            lines = ["## Requirements (must follow)"]
            lines.append("*These are constraints that must be respected.*\n")
            for r in reqs:
                lines.append(f"- {r['content']} ({r.get('date', 'unknown date')})")
            sections.append("\n".join(lines))

        # Facts/context - informational
        if "fact" in by_type:
            facts = by_type.pop("fact")
            lines = ["## Known Facts (context)"]
            for f in facts:
                lines.append(f"- {f['content']}")
            sections.append("\n".join(lines))

        # Everything else (notes, learnings, etc.)
        for mem_type, mems in by_type.items():
            lines = [f"## {mem_type.title()}s"]
            for m in mems:
                lines.append(f"- {m['content']} ({m.get('date', 'unknown date')})")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    # -------------------------------------------------------------------------
    # PROJECT CONTEXT: Stable, cache-friendly
    # -------------------------------------------------------------------------

    def get_project_context(self, project: str, limit: int = 5) -> str:
        """Get project context as formatted string.

        Returns stable content (good for caching).

        Args:
            project: Project name
            limit: Max memories to include

        Returns:
            Formatted markdown string
        """
        with self._telemetry.track("memory.get_project_context"):
            results = self.store.scroll(
                filters={"project": project},
                limit=limit,
            )

            if not results:
                return ""

            # Sort by timestamp for consistent ordering
            results = sorted(
                results,
                key=lambda x: x.get("timestamp", ""),
                reverse=True,
            )

            # Format
            lines = [f"# Project Context: {project}\n"]
            for r in results:
                lines.append(
                    f"## [{r.get('date', '')}] {r.get('type', '')}\n{r.get('content', '')}\n"
                )

            return "\n".join(lines)

    # -------------------------------------------------------------------------
    # SESSION SUMMARY: End-of-session snapshot
    # -------------------------------------------------------------------------

    def save_session_summary(
        self,
        tasks_completed: list[str] | None = None,
        decisions_made: list[str] | None = None,
        learnings: list[str] | None = None,
        preferences: list[str] | None = None,
        project: str | None = None,
    ) -> str:
        """Save end-of-session summary.

        Args:
            tasks_completed: What was done
            decisions_made: Key decisions
            learnings: Things learned
            preferences: User preferences observed
            project: Project name

        Returns:
            Memory ID (empty string if nothing to save)
        """
        sections = []

        if tasks_completed:
            sections.append("## Tasks Completed\n" + "\n".join(f"- {t}" for t in tasks_completed))
        if decisions_made:
            sections.append("## Decisions\n" + "\n".join(f"- {d}" for d in decisions_made))
        if learnings:
            sections.append("## Learnings\n" + "\n".join(f"- {item}" for item in learnings))
        if preferences:
            sections.append("## Preferences\n" + "\n".join(f"- {p}" for p in preferences))

        if not sections:
            return ""

        return self.save(
            content="\n\n".join(sections),
            type="session",
            project=project,
        )

    # -------------------------------------------------------------------------
    # STATS: System information
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        with self._telemetry.track("memory.get_stats"):
            # Vector store count
            try:
                vector_count = self.store.count()
            except Exception:
                vector_count = 0

            # File counts
            file_count = sum(1 for _ in self.memory_dir.rglob("*.jsonl"))

            type_counts: dict[str, int] = {}
            for jsonl_file in self.memory_dir.rglob("*.jsonl"):
                memory_type = jsonl_file.stem.rstrip("s")
                with open(jsonl_file) as f:
                    count = sum(1 for _ in f)
                type_counts[memory_type] = type_counts.get(memory_type, 0) + count

            return {
                "total_memories": vector_count,
                "memory_files": file_count,
                "memory_dir": str(self.memory_dir),
                "by_type": type_counts,
            }

    # -------------------------------------------------------------------------
    # CLEANUP: Remove memories
    # -------------------------------------------------------------------------

    def clear_project(self, project: str) -> None:
        """Delete all memories for a project."""
        with self._telemetry.track("memory.clear_project"):
            self.store.delete(filters={"project": project})
            logger.info(f"Cleared memories for project: {project}")

    # -------------------------------------------------------------------------
    # BACKWARD COMPATIBILITY
    # -------------------------------------------------------------------------

    def sanitize(self, content: str) -> str:
        """Sanitize content (for backwards compatibility)."""
        return Sanitizer.sanitize(content)

    # Direct access to underlying components (for testing)
    @property
    def qdrant(self):
        """Get Qdrant client (for backwards compatibility)."""
        return self.store.client
