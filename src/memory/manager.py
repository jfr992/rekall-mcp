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

import hashlib
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core import Embedder, Telemetry, VectorStore
from memory.lifecycle import summarize_lifecycle
from memory.linker import auto_link
from memory.observe import ObservationCandidate, ObservationEngine
from memory.resume import build_resume_packet
from memory.scope import MemoryScope, ScopeDetector
from memory.skills import extract_skills, render_skill_context
from memory.startup import build_agent_startup

if TYPE_CHECKING:
    from memory.knowledge_graph import KnowledgeGraph

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
        # Generic hex only when preceded by key/secret/token/password context
        r"(?i)(?:key|secret|token|password)[\"'\s:=]+[a-f0-9]{32,}",
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
        memory_dir: str | Path | None = None,
        qdrant_url: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        """Initialize memory manager.

        Args:
            memory_dir: Where to store memory files (default: MEMORY_STORAGE_PATH or ~/.claude/memory)
            qdrant_url: Qdrant server URL (default: QDRANT_URL or http://localhost:6333)
            embedding_model: Model for embeddings (default: EMBEDDING_MODEL or all-MiniLM-L6-v2)
        """
        # Read from environment with sensible defaults
        memory_dir = memory_dir or os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
        qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        embedding_model = embedding_model or os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

        # File storage
        self.memory_dir = Path(memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Vector store (uses core infrastructure)
        self._store: VectorStore | None = None
        self._qdrant_url = qdrant_url

        # Embeddings (uses core infrastructure)
        self._embedder: Embedder | None = None
        self._embedding_model = embedding_model

        # BM25 sparse encoder for hybrid search
        self._sparse_encoder = None
        self._bm25_path = self.memory_dir / "_bm25_vocab.json"

        self._knowledge_graph: KnowledgeGraph | None = None

        # Telemetry
        self._telemetry = Telemetry.get()
        self._observer = ObservationEngine()

    # -------------------------------------------------------------------------
    # LAZY INITIALIZATION: Load on first use
    # -------------------------------------------------------------------------

    @property
    def sparse_encoder(self):
        """Get BM25 encoder, loading from disk if available."""
        if self._sparse_encoder is None and self._bm25_path.exists():
            from core import BM25Encoder

            enc = BM25Encoder()
            enc.load(str(self._bm25_path))
            self._sparse_encoder = enc
        return self._sparse_encoder

    @property
    def store(self) -> VectorStore:
        """Get vector store, initializing if needed."""
        if self._store is None:
            self._store = VectorStore(
                collection=self.COLLECTION,
                url=self._qdrant_url,
                sparse_encoder=self.sparse_encoder,
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

    @property
    def knowledge_graph(self) -> KnowledgeGraph:
        """Get graph, initializing lazily on first use."""
        if self._knowledge_graph is None:
            from memory.knowledge_graph import KnowledgeGraph

            self._knowledge_graph = KnowledgeGraph(self.memory_dir / "_graph.json")
        return self._knowledge_graph

    # -------------------------------------------------------------------------
    # SAVE: Store memories
    # -------------------------------------------------------------------------

    def save(
        self,
        content: str,
        type: str = "note",
        project: str | None = None,
        scope: MemoryScope | None = None,
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
            content = Sanitizer.sanitize(content)
            scope = scope or ScopeDetector.detect(project=project)
            project_name = project or scope.project or "general"

            if "/" in project_name or "\\" in project_name or ".." in project_name:
                raise ValueError(f"Invalid project name: {project_name!r}")

            existing_memory_id = self._find_duplicate_memory_id(
                content=content,
                project=project_name,
                memory_type=type,
            )
            if existing_memory_id:
                self._reinforce_existing_memory(existing_memory_id)
                logger.info(f"Duplicate memory reinforced: {existing_memory_id}")
                return existing_memory_id

            date = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().isoformat()
            unique_string = f"{content}|{timestamp}"
            content_hash = hashlib.sha256(unique_string.encode()).hexdigest()[:8]
            memory_id = f"{date}_{type}_{content_hash}"

            payload = {
                "memory_id": memory_id,
                "content": content,
                "date": date,
                "timestamp": timestamp,
                "type": type,
                "project": project_name,
                "reinforcement_count": 0,
                **scope.to_metadata(),
                **metadata,
            }
            payload.update(summarize_lifecycle(payload))

            # Save to file (durability)
            self._save_to_file(memory_id, content, payload, type, date)

            # Save to vector store (searchability)
            vector = self.embedder.encode(content)
            self.store.save(id=memory_id, vector=vector, payload=payload, content=content)

            # Build/refresh graph node for this memory
            self.knowledge_graph.add_node(
                memory_id,
                topic=project_name,
                memory_type=type,
            )

            # Auto-link to related memories
            try:
                link_result = auto_link(
                    graph=self.knowledge_graph,
                    memory_id=memory_id,
                    content=content,
                    memory_type=type,
                    project=project_name,
                    embedder=self.embedder,
                    store=self.store,
                )
                self.knowledge_graph.save()
                if link_result.edges_created:
                    logger.info(f"Auto-linked: {link_result.relations}")
            except Exception:
                logger.warning("Auto-linking failed, memory saved without graph edges", exc_info=True)

            logger.info(f"Saved memory: {memory_id}")
            return memory_id

    def observe(
        self,
        summary: str,
        type: str = "auto",
        project: str | None = None,
        scope: MemoryScope | None = None,
        context: str | None = None,
        **metadata: Any,
    ) -> ObservationCandidate | str:
        """Evaluate and persist a memory-worthy observation.

        Returns the saved memory ID when persisted, otherwise the candidate verdict.
        """
        candidate = self._observer.evaluate(summary, memory_type=type)
        if not candidate.should_save:
            return candidate

        content = candidate.content if not context else f"{candidate.content}\n\nContext: {context}"
        return self.save(
            content=content,
            type=candidate.memory_type,
            project=project,
            scope=scope,
            salience=candidate.salience,
            **metadata,
        )

    def _find_duplicate_memory_id(
        self,
        *,
        content: str,
        project: str,
        memory_type: str,
    ) -> str | None:
        """Return existing memory id for near-identical memories in same project/type."""
        try:
            matches = self.store.search(
                vector=self.embedder.encode(content),
                limit=3,
                filters={"project": project, "type": memory_type},
                score_threshold=0.97,
                query_text=content,
            )
        except Exception:
            return None

        normalized = " ".join(content.split()).strip().lower()
        for match in matches:
            existing = " ".join((match.get("content") or "").split()).strip().lower()
            if existing == normalized:
                return match.get("memory_id")
        return None

    def _reinforce_existing_memory(self, memory_id: str) -> None:
        """Load, reinforce, reclassify, and persist the updated payload."""
        from datetime import datetime as _dt

        from memory.intelligence import reinforce_and_reclassify

        try:
            existing = self.store.get_by_id(memory_id)
        except Exception:
            logger.warning(f"Could not load memory for reinforcement: {memory_id}", exc_info=True)
            return
        if not existing:
            return

        try:
            updated = reinforce_and_reclassify(
                existing,
                graph=self.knowledge_graph,
                now=_dt.now(),
            )
        except Exception:
            logger.warning(f"Reinforce/reclassify failed for {memory_id}", exc_info=True)
            return

        try:
            self.store.update_payload(memory_id, updated)
        except Exception:
            logger.warning(f"Could not persist reinforcement for {memory_id}", exc_info=True)

    def backfill_lifecycle(
        self,
        *,
        dry_run: bool = True,
        project: str | None = None,
        batch_size: int = 500,
    ) -> dict[str, Any]:
        """Backfill tier/durability/lifecycle_reason on existing memories.

        Scrolls all points (optionally filtered by project), computes
        LifecycleSignals + classify() for each, and (unless dry_run) writes the
        updated payload back to the store.

        Returns a report with counts by tier, skipped ids, and errors.
        """
        from datetime import datetime as _dt

        from memory.lifecycle import LifecycleSignals, classify, compute_retention_days

        filters = {"project": project} if project else None
        now = _dt.now()

        updated_by_tier: dict[str, int] = {"working": 0, "episodic": 0, "semantic": 0, "identity": 0}
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        points = self.store.scroll(filters=filters, limit=batch_size)
        graph_has_nodes = self.knowledge_graph.stats()["nodes"] > 0

        for point in points:
            memory_id = point.get("memory_id", "")
            if not memory_id:
                skipped.append("<missing_id>")
                continue

            date_str = point.get("date") or now.strftime("%Y-%m-%d")
            try:
                mem_date = _dt.strptime(date_str, "%Y-%m-%d")
                age_days = max(0, (now - mem_date).days)
            except ValueError:
                age_days = 0

            contradicts_count = (
                self.knowledge_graph.count_contradicts(memory_id) if graph_has_nodes else 0
            )

            existing_tier = point.get("tier")
            explicit = existing_tier if existing_tier == "identity" else None

            signals = LifecycleSignals(
                memory_type=point.get("type", "note"),
                salience=float(point.get("salience") or 0.0),
                age_days=age_days,
                reinforcement_count=int(point.get("reinforcement_count") or 0),
                contradicts_count=contradicts_count,
                explicit_tier=explicit,
            )
            result = classify(signals)

            updated_by_tier[result.tier] += 1
            if dry_run:
                continue

            new_payload = dict(point)
            new_payload.update({
                "tier": result.tier,
                "durability": result.durability,
                "lifecycle_reason": result.reason,
                "retention_days": compute_retention_days(signals.memory_type, result.tier),
            })
            try:
                self.store.update_payload(memory_id, new_payload)
            except Exception as e:  # noqa: BLE001
                errors.append({"memory_id": memory_id, "error": str(e)})

        return {
            "dry_run": dry_run,
            "project": project,
            "updated_by_tier": updated_by_tier,
            "skipped": skipped,
            "errors": errors,
            "total": sum(updated_by_tier.values()),
        }

    def _save_to_file(
        self,
        memory_id: str,
        content: str,
        metadata: dict,
        memory_type: str,
        date: str,
    ) -> None:
        """Save memory to human-readable YAML file, organized by project."""
        project = metadata.get("project", "general")
        project_dir = self.memory_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)
        yaml_file = project_dir / f"{date}.yaml"

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

        # Atomic write: write to temp file, then os.replace() (POSIX atomic)
        fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            os.replace(tmp_path, yaml_file)
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # -------------------------------------------------------------------------
    # DELETE: Remove memories
    # -------------------------------------------------------------------------

    def delete(self, memory_id: str) -> bool:
        """Delete a memory from YAML, vector store, and knowledge graph.

        Args:
            memory_id: The memory ID (e.g., "2026-04-01_fact_aaa")

        Returns:
            True if deleted, False if not found
        """
        # Parse date from memory_id: "2026-04-01_fact_hash" → "2026-04-01"
        date = memory_id[:10] if len(memory_id) >= 10 else None
        if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
            return False

        # Search across all project subdirs for the YAML file
        yaml_file = None
        for candidate in self.memory_dir.rglob(f"{date}.yaml"):
            with open(candidate) as f:
                check = yaml.safe_load(f) or {}
            for type_key in check:
                if isinstance(check[type_key], list):
                    if any(m.get("id") == memory_id for m in check[type_key]):
                        yaml_file = candidate
                        break
            if yaml_file:
                break
        if not yaml_file:
            # Also try flat (legacy) path
            flat = self.memory_dir / f"{date}.yaml"
            if flat.exists():
                yaml_file = flat
            else:
                return False

        with open(yaml_file) as f:
            data = yaml.safe_load(f) or {}

        found = False
        for type_key in list(data.keys()):
            if not isinstance(data[type_key], list):
                continue
            original_len = len(data[type_key])
            data[type_key] = [m for m in data[type_key] if m.get("id") != memory_id]
            if len(data[type_key]) < original_len:
                found = True
                if not data[type_key]:
                    del data[type_key]

        if not found:
            return False

        # Check if file is now empty (only 'date' key or nothing)
        has_memories = any(isinstance(v, list) and v for v in data.values())
        if not has_memories:
            yaml_file.unlink()
        else:
            fd, tmp = tempfile.mkstemp(dir=self.memory_dir, suffix=".yaml.tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                os.replace(tmp, yaml_file)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

        # Best-effort: delete from vector store
        try:
            from qdrant_client.models import PointIdsList

            from core import stable_hash_id

            self.store.client.delete(
                collection_name=self.store.collection,
                points_selector=PointIdsList(points=[stable_hash_id(memory_id)]),
            )
        except Exception:
            logger.warning(f"Failed to delete {memory_id} from vector store", exc_info=True)

        # Best-effort: delete from knowledge graph
        try:
            self.knowledge_graph.remove_node(memory_id)
            self.knowledge_graph.save()
        except Exception:
            logger.warning(f"Failed to delete {memory_id} from knowledge graph", exc_info=True)

        logger.info(f"Deleted memory: {memory_id}")
        return True

    def cleanup(
        self,
        max_age_days_facts: int | None = None,
        prune_superseded: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Clean up stale and redundant memories.

        Args:
            max_age_days_facts: Delete facts older than N days
            prune_superseded: Delete memories superseded in knowledge graph
            dry_run: Report what would be deleted without deleting

        Returns:
            Stats dict with pruning counts and flagged contradictions
        """
        stats: dict[str, Any] = {
            "facts_pruned": 0,
            "superseded_pruned": 0,
            "contradictions_flagged": 0,
            "contradictions": [],
            "dry_run": dry_run,
        }

        # 1. Prune old facts
        if max_age_days_facts is not None:
            cutoff = (datetime.now() - timedelta(days=max_age_days_facts)).strftime("%Y-%m-%d")

            for yaml_file in sorted(self.memory_dir.rglob("*.yaml")):
                file_date = yaml_file.stem
                if file_date.startswith("_") or file_date >= cutoff:
                    continue

                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}

                if "facts" in data and isinstance(data["facts"], list):
                    count = len(data["facts"])
                    if not dry_run:
                        for fact in list(data["facts"]):
                            self.delete(fact["id"])
                    stats["facts_pruned"] += count

        # 2. Prune superseded memories
        if prune_superseded:
            graph = self.knowledge_graph
            superseded_ids = set()
            for _source, target, edge_data in graph._graph.edges(data=True):
                if edge_data.get("relation") == "supersedes":
                    superseded_ids.add(target)

            for memory_id in superseded_ids:
                if not dry_run:
                    self.delete(memory_id)
                stats["superseded_pruned"] += 1

            # 3. Flag contradictions (do NOT delete)
            seen_pairs: set[tuple[str, str]] = set()
            for source, target, edge_data in graph._graph.edges(data=True):
                if edge_data.get("relation") == "contradicts":
                    pair = tuple(sorted([source, target]))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    stats["contradictions_flagged"] += 1
                    stats["contradictions"].append({
                        "memory_a": source,
                        "memory_b": target,
                    })

        return stats

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
        score_threshold: float = 0.45,
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
            # Note: date filtering is done post-retrieval (dates stored as strings,
            # Qdrant Range filter requires numeric values)
            cutoff_date = (
                (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
                if days_back
                else None
            )

            # Phase 1: SEED — standard vector search
            query_vector = self.embedder.encode(query)
            graph = self.knowledge_graph
            graph_stats = graph.stats()
            graph_has_edges = graph_stats["edges"] > 0
            graph_has_nodes = graph_stats["nodes"] > 0
            seed_results = self.store.search(
                vector=query_vector,
                limit=limit * 2 if limit and graph_has_edges else limit,
                filters=filters if filters else None,
                score_threshold=score_threshold,
                query_text=query,
            )

            # Phase 2: EXPAND — graph traversal
            if graph_has_edges:
                seed_ids = {r.get("memory_id") for r in seed_results if r.get("memory_id")}
                expanded_ids: set[str] = set()

                for memory_id in seed_ids:
                    if not isinstance(memory_id, str):
                        continue
                    graph.record_access(memory_id)
                    neighbors = graph.get_neighbors(memory_id, hops=1)
                    expanded_ids.update(neighbors)

                # Deduplicate expanded items and ignore seed IDs.
                new_ids = expanded_ids - seed_ids
                for expanded_id in list(new_ids):
                    expanded_results = self.store.search(
                        vector=query_vector,
                        limit=1,
                        filters={"memory_id": expanded_id},
                        score_threshold=0.0,
                    )

                    for result in expanded_results:
                        memory_id = result.get("memory_id")
                        if memory_id not in seed_ids:
                            seed_results.append({**result, "_graph_expanded": True})
                            seed_ids.add(memory_id)

                graph.save()

            # Phase 3: RANK — combined scoring
            scored: list[dict[str, float]] = []
            for result in seed_results:
                memory_id = result.get("memory_id", "")
                vector_score = float(result.get("score", 0.0))

                if not graph_has_nodes:
                    scored.append(
                        {
                            "score": round(vector_score, 4),
                            "content": result.get("content"),
                            "date": result.get("date"),
                            "type": result.get("type"),
                            "project": result.get("project"),
                            "memory_id": memory_id,
                        }
                    )
                    continue

                importance = graph.get_importance(memory_id) if memory_id else 0.5
                is_expanded = bool(result.get("_graph_expanded"))
                graph_proximity = 0.7 if is_expanded else 1.0
                tier = result.get("tier", "working")

                days_old = 0
                if result.get("date"):
                    try:
                        mem_date = datetime.strptime(result["date"], "%Y-%m-%d")
                        days_old = (datetime.now() - mem_date).days
                    except ValueError:
                        days_old = 0

                recency = max(0.0, 1.0 - days_old / 365)

                tier_norm = {
                    "identity": 1.0,
                    "semantic": 0.66,
                    "episodic": 0.33,
                    "working": 0.0,
                }.get(tier, 0.0)

                final_score = (
                    vector_score * 0.40
                    + importance * 0.20
                    + recency * 0.10
                    + graph_proximity * 0.15
                    + tier_norm * 0.15
                )

                scored.append(
                    {
                        "score": round(final_score, 4),
                        "vector_score": round(vector_score, 4),
                        "content": result.get("content"),
                        "date": result.get("date"),
                        "type": result.get("type"),
                        "project": result.get("project"),
                        "memory_id": memory_id,
                        "tier": tier,
                    }
                )

            scored.sort(key=lambda item: item["score"], reverse=True)

            # Post-filter by date (string comparison works since format is YYYY-MM-DD)
            if cutoff_date:
                scored = [r for r in scored if (r.get("date") or "") >= cutoff_date]

            return scored[:limit]

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
    # HIERARCHICAL CONTEXT: Topic-aware structure
    # -------------------------------------------------------------------------

    def get_hierarchical_project_context(
        self,
        project: str | None = None,
        limit: int = 120,
        max_topics: int = 8,
        similarity_threshold: float = 0.72,
    ) -> str:
        """Get project context grouped into topics.

        Args:
            project: Optional project filter.
            limit: Max memories to analyze.
            max_topics: Maximum number of topics to return.
            similarity_threshold: Similarity cutoff for agglomerative clustering.

        Returns:
            Topic-grouped markdown context.
        """
        with self._telemetry.track("memory.get_hierarchical_project_context"):
            filters = {}
            if project:
                filters["project"] = project

            points = self.store.scroll(filters=filters if filters else None, limit=limit, with_vectors=True)
            if not points:
                return ""

            from memory.topics import build_topic_clusters, render_hierarchical_context

            topics = build_topic_clusters(
                points,
                similarity_threshold=similarity_threshold,
                max_topics=max_topics,
            )
            return render_hierarchical_context(topics, project=project)

    # -------------------------------------------------------------------------
    # SKILL CONTEXT: Inferred capabilities
    # -------------------------------------------------------------------------

    def get_skill_context(
        self,
        project: str | None = None,
        limit: int = 200,
        min_mentions: int = 2,
        max_skills: int = 8,
    ) -> str:
        """Get inferred skill context from memory evidence."""
        with self._telemetry.track("memory.get_skill_context"):
            filters = {}
            if project:
                filters["project"] = project

            points = self.store.scroll(filters=filters if filters else None, limit=limit)
            if not points:
                return ""

            skills = extract_skills(
                points,
                min_mentions=min_mentions,
                max_skills=max_skills,
            )
            return render_skill_context(skills, project=project)

    # -------------------------------------------------------------------------
    # MEMORY CONSOLIDATION: Detect superseded/contradictory memories
    # -------------------------------------------------------------------------

    def consolidate_memories(
        self,
        project: str | None = None,
        limit: int = 240,
        save_summary: bool = False,
    ) -> str:
        """Build a consolidation report for likely redundant or conflicting memories."""
        with self._telemetry.track("memory.consolidate_memories"):
            filters = {}
            if project:
                filters["project"] = project

            points = self.store.scroll(filters=filters if filters else None, limit=limit)
            if not points:
                return "No memories found for consolidation."

            points_by_id = {point.get("memory_id", ""): point for point in points}
            memory_ids = {mid for mid in points_by_id if mid}
            graph = self.knowledge_graph

            superseded: list[tuple[str, str, float]] = []
            contradictions: list[tuple[str, str, float]] = []
            for source_id in memory_ids:
                for edge in graph.get_edges(source_id, direction="out"):
                    if edge.target not in memory_ids:
                        continue

                    if edge.relation == "supersedes":
                        superseded.append((edge.source, edge.target, edge.weight))
                    elif edge.relation == "contradicts":
                        contradictions.append((edge.source, edge.target, edge.weight))

            # Deduplicate: normalize pairs to (min, max) so A→B and B→A collapse.
            seen_supersedes: dict[tuple[str, str], float] = {}
            for source_id, target_id, weight in superseded:
                key = (min(source_id, target_id), max(source_id, target_id))
                seen_supersedes[key] = max(seen_supersedes.get(key, 0.0), weight)

            seen_conflicts: dict[tuple[str, str], float] = {}
            for source_id, target_id, weight in contradictions:
                # Normalize to (min, max) so A→B and B→A collapse into one entry
                key = (min(source_id, target_id), max(source_id, target_id))
                seen_conflicts[key] = max(seen_conflicts.get(key, 0.0), weight)

            lines = [f"# Memory Consolidation: {project or 'all projects'}"]

            if seen_supersedes:
                lines.append("## Superseded Memories")
                for (source_id, target_id), weight in sorted(
                    seen_supersedes.items(), key=lambda item: item[1], reverse=True
                ):
                    target = points_by_id.get(target_id, {})
                    snippet = self._memory_snippet(target.get("content", ""))
                    lines.append(
                        f"- `{source_id}` supersedes `{target_id}` "
                        f"(score: {weight:.3f})"
                    )
                    if snippet:
                        lines.append(f"  - {snippet}")

            if seen_conflicts:
                lines.append("## Conflicting Memories")
                for (source_id, target_id), weight in sorted(
                    seen_conflicts.items(), key=lambda item: item[1], reverse=True
                ):
                    source = points_by_id.get(source_id, {})
                    target = points_by_id.get(target_id, {})
                    source_snippet = self._memory_snippet(source.get("content", ""))
                    target_snippet = self._memory_snippet(target.get("content", ""))
                    lines.append(
                        f"- `{source_id}` and `{target_id}` may conflict "
                        f"(score: {weight:.3f})"
                    )
                    if source_snippet:
                        lines.append(f"  - {source_id}: {source_snippet}")
                    if target_snippet:
                        lines.append(f"  - {target_id}: {target_snippet}")

            if not seen_supersedes and not seen_conflicts:
                lines.append("## Consolidation Signals")
                lines.append("No clear supersedes/contradiction signals detected yet.")

            result = "\n".join(lines)

            if save_summary:
                summary_id = self.save(
                    content=result,
                    type="session",
                    project=project,
                )
                result = f"{result}\n\nSaved consolidation summary as `{summary_id}`."

            return result

    def get_proactive_context_summary(
        self,
        project: str | None = None,
        limit: int = 120,
    ) -> str:
        """Generate a proactive summary of high-signal memories."""
        with self._telemetry.track("memory.proactive_context_summary"):
            filters = {}
            if project:
                filters["project"] = project

            points = self.store.scroll(filters=filters if filters else None, limit=limit)
            if not points:
                return "No memories available for a proactive summary."

            points_by_id = {point.get("memory_id", ""): point for point in points}
            memory_ids = {mid for mid in points_by_id if mid}
            graph = self.knowledge_graph

            def _score_memory(point: dict) -> float:
                memory_id = point.get("memory_id", "")
                if not memory_id:
                    return 0.0

                importance = graph.get_importance(memory_id) if graph.stats()["nodes"] else 0.5
                item_date = point.get("date")
                days_old = 0
                if item_date:
                    try:
                        parsed = datetime.strptime(item_date, "%Y-%m-%d")
                        days_old = (datetime.now() - parsed).days
                    except ValueError:
                        days_old = 0
                recency = max(0.0, 1.0 - days_old / 365)
                return importance * 0.6 + recency * 0.4

            conflict_edges = []
            for source_id in memory_ids:
                for edge in graph.get_edges(source_id, direction="out"):
                    if edge.relation == "contradicts" and edge.target in memory_ids:
                        conflict_edges.append((edge.source, edge.target))

            ranked_points = sorted(
                points,
                key=_score_memory,
                reverse=True,
            )

            lines = [
                f"# Proactive Context: {project or 'all projects'}",
                "",
                "## Top Signals",
            ]

            for point in ranked_points[:8]:
                snippet = self._memory_snippet(point.get("content", ""), max_length=160)
                if not snippet:
                    continue
                lines.append(
                    f"- [{point.get('type', 'note')}] {snippet} (memory: {point.get('memory_id', 'n/a')})"
                )

            if conflict_edges:
                lines.append("")
                lines.append("## Conflicts to Review")
                for source_id, target_id in sorted(set(conflict_edges)):
                    source = self._memory_snippet(points_by_id.get(source_id, {}).get("content", ""))
                    target = self._memory_snippet(points_by_id.get(target_id, {}).get("content", ""))
                    lines.append(f"- `{source_id}` conflicts with `{target_id}`")
                    if source:
                        lines.append(f"  - {source}")
                    if target:
                        lines.append(f"  - {target}")

            if not conflict_edges:
                lines.append("")
                lines.append("## Conflicts to Review")
                lines.append("No contradictions detected among ranked memories.")

            return "\n".join(lines)

    @staticmethod
    def _memory_snippet(content: str, max_length: int = 120) -> str:
        """Create a compact inline memory snippet for summaries."""
        normalized = (content or "").strip().replace("\n", " ")
        if not normalized:
            return ""

        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[: max_length - 3]}..."

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

    def get_resume_packet(
        self,
        project: str | None = None,
        scope: MemoryScope | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Return a continuity-oriented startup packet for an agent session."""
        scope = scope or ScopeDetector.detect(project=project)
        return build_resume_packet(self, scope=scope, limit=limit)

    def get_agent_startup(
        self,
        project: str | None = None,
        agent: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Return a single startup payload for agent clients."""
        return build_agent_startup(self, project=project, agent=agent, limit=limit)

    def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        with self._telemetry.track("memory.get_stats"):
            # Vector store count
            try:
                vector_count = self.store.count()
            except Exception:
                vector_count = 0

            # File counts (YAML daily files)
            yaml_files = list(self.memory_dir.rglob("*.yaml"))
            file_count = len(yaml_files)

            # Count by type from YAML files
            type_counts: dict[str, int] = {}
            for yaml_file in yaml_files:
                try:
                    with open(yaml_file) as f:
                        data = yaml.safe_load(f) or {}
                    for key, value in data.items():
                        if key != "date" and isinstance(value, list):
                            # Key is like "decisions", "preferences", etc.
                            mem_type = key.rstrip("s")
                            type_counts[mem_type] = type_counts.get(mem_type, 0) + len(value)
                except Exception:
                    pass

            # Knowledge graph metrics
            try:
                graph_stats = self.knowledge_graph.stats()
            except Exception:
                graph_stats = {"nodes": 0, "edges": 0, "relations": {}}

            return {
                "total_memories": vector_count,
                "memory_files": file_count,
                "memory_dir": str(self.memory_dir),
                "by_type": type_counts,
                "knowledge_graph": {
                    "nodes": graph_stats.get("nodes", 0),
                    "edges": graph_stats.get("edges", 0),
                    "relations": graph_stats.get("relations", {}),
                },
            }

    # -------------------------------------------------------------------------
    # CLEANUP: Remove memories
    # -------------------------------------------------------------------------

    def clear_project(self, project: str) -> None:
        """Delete all memories for a project."""
        with self._telemetry.track("memory.clear_project"):
            self.store.delete(filters={"project": project})
            logger.info(f"Cleared memories for project: {project}")
