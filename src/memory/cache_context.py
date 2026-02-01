"""Cache-optimized memory context.

Designed to maximize prompt cache hits by providing STABLE context
that doesn't change between turns.

How prompt caching works:
- Cache matches on PREFIX (start of prompt)
- Any change in prefix = cache miss
- Same prefix = 90% discount on those tokens

Strategy:
1. Load project context ONCE at session start
2. Put it at the START of every prompt
3. Keep it IDENTICAL across turns
4. Dynamic queries come AFTER the cached prefix

Usage:
    from memory.cache_context import CacheableContext

    # At session start
    ctx = CacheableContext(project="my-app")
    cached_prefix = ctx.get_stable_context()

    # Every turn - same prefix, cache hits
    prompt = cached_prefix + user_message
"""

import hashlib
import json
from pathlib import Path


class CacheableContext:
    """Generate stable, cacheable memory context.

    Key design choices for cache hits:
    - Sorted by date (not score) = deterministic order
    - Fixed format = byte-identical each time
    - No timestamps that change = stable content
    - Grouped by type = predictable structure
    """

    def __init__(
        self,
        project: str | None = None,
        storage_path: str = "~/.claude/memory",
        include_types: list[str] | None = None,
        max_memories: int = 50,
    ):
        """Initialize cacheable context.

        Args:
            project: Filter to specific project (None = all)
            storage_path: Where memories are stored
            include_types: Memory types to include (None = all)
            max_memories: Maximum memories to include
        """
        self.project = project
        self.storage_path = Path(storage_path).expanduser()
        self.include_types = include_types or [
            "requirement",
            "fact",
            "decision",
            "preference",
            "learning",
        ]
        self.max_memories = max_memories

        self._cached_context: str | None = None
        self._cache_hash: str | None = None

    def get_stable_context(self, force_refresh: bool = False) -> str:
        """Get stable, cacheable context string.

        Returns identical string each call (unless memories change).

        Args:
            force_refresh: Reload from disk even if cached

        Returns:
            Stable context string for prompt prefix
        """
        if self._cached_context and not force_refresh:
            return self._cached_context

        memories = self._load_memories()
        self._cached_context = self._format_stable(memories)
        self._cache_hash = self._compute_hash(self._cached_context)

        return self._cached_context

    def get_cache_hash(self) -> str:
        """Get hash of current context (for cache invalidation checks)."""
        if not self._cache_hash:
            self.get_stable_context()
        return self._cache_hash or ""

    def _load_memories(self) -> list[dict]:
        """Load memories from storage."""
        if not self.storage_path.exists():
            return []

        memories = []
        for file_path in self.storage_path.glob("**/*.json"):
            try:
                with open(file_path) as f:
                    mem = json.load(f)

                # Filter by project
                if self.project and mem.get("project") != self.project:
                    continue

                # Filter by type
                if mem.get("type") not in self.include_types:
                    continue

                memories.append(mem)
            except Exception:
                continue

        # Sort by date (STABLE ORDER - critical for caching)
        memories.sort(key=lambda m: m.get("created_at", ""), reverse=True)

        # Limit
        return memories[: self.max_memories]

    def _format_stable(self, memories: list[dict]) -> str:
        """Format memories in a STABLE way for caching.

        Critical: Output must be byte-identical given same input.
        - No timestamps
        - No random elements
        - Fixed order
        - Fixed formatting
        """
        if not memories:
            return self._empty_context()

        # Group by type (fixed order)
        by_type: dict[str, list[dict]] = {}

        for mem in memories:
            t = mem.get("type", "note")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(mem)

        # Build output in FIXED order
        sections = []

        # Header
        if self.project:
            sections.append(f"# Context: {self.project}")
        else:
            sections.append("# Context")
        sections.append("")

        # Requirements first (must follow)
        if "requirement" in by_type:
            sections.append("## Requirements (must follow)")
            for m in by_type["requirement"]:
                sections.append(f"- {m['content']}")
            sections.append("")

        # Facts (environment context)
        if "fact" in by_type:
            sections.append("## Known Facts")
            for m in by_type["fact"]:
                sections.append(f"- {m['content']}")
            sections.append("")

        # Decisions (established choices)
        if "decision" in by_type:
            sections.append("## Past Decisions")
            for m in by_type["decision"]:
                sections.append(f"- {m['content']}")
            sections.append("")

        # Preferences (defaults, offer alternatives)
        if "preference" in by_type:
            sections.append("## User Preferences (show as default, offer alternatives)")
            for m in by_type["preference"]:
                sections.append(f"- {m['content']}")
            sections.append("")

        # Learnings
        if "learning" in by_type:
            sections.append("## Learnings")
            for m in by_type["learning"]:
                sections.append(f"- {m['content']}")
            sections.append("")

        return "\n".join(sections)

    def _empty_context(self) -> str:
        """Return empty context (still stable)."""
        if self.project:
            return f"# Context: {self.project}\n\nNo memories yet.\n"
        return "# Context\n\nNo memories yet.\n"

    def _compute_hash(self, content: str) -> str:
        """Compute hash for cache invalidation."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def has_changed(self) -> bool:
        """Check if context has changed since last load.

        Useful for cache invalidation.
        """
        old_hash = self._cache_hash
        self.get_stable_context(force_refresh=True)
        return self._cache_hash != old_hash


def get_session_context(project: str | None = None) -> str:
    """Convenience function to get cacheable context.

    Call once at session start, reuse for every turn.

    Args:
        project: Optional project filter

    Returns:
        Stable context string
    """
    ctx = CacheableContext(project=project)
    return ctx.get_stable_context()


# Token estimation for cache planning
def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)."""
    return len(text) // 4


def format_for_cache(context: str, min_tokens: int = 1024) -> str:
    """Ensure context meets minimum size for caching.

    Anthropic requires 1024+ tokens for prompt caching.
    Pads with whitespace if needed (doesn't change semantics).
    """
    current_tokens = estimate_tokens(context)

    if current_tokens >= min_tokens:
        return context

    # Pad to meet minimum (comments don't affect behavior)
    padding_needed = (min_tokens - current_tokens) * 4
    padding = "\n" + "<!-- padding for cache -->\n" * (padding_needed // 25)

    return context + padding
