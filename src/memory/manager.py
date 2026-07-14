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
from core.utils import assert_test_isolation
from memory.events import EventLog, MemoryEvent
from memory.lifecycle import summarize_lifecycle
from memory.linker import auto_link
from memory.observe import ObservationCandidate, ObservationEngine, sanitize_observation_metadata
from memory.representation import build_embedding_text, extract_entities
from memory.resume import build_resume_packet
from memory.scope import MemoryScope, ScopeDetector, strip_remote_creds
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


def _is_project_shaped(project: str) -> bool:
    """True when a project name is safe to strip from a dense query.

    Only a hyphen/underscore/digit marks a token as project-shaped. Deliberate
    ceiling: single-word project names ("payments", "rekallmcp") are never
    stripped — no length or dictionary heuristic reliably separates them from
    real query semantics, and the full-query probe always runs regardless.
    """
    return any(c in "-_" or c.isdigit() for c in project)


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
        qdrant_path: str | None = None,
        embedding_model: str | None = None,
        qdrant_client: Any | None = None,
    ) -> None:
        """Initialize memory manager.

        Args:
            memory_dir: Where to store memory files (default: MEMORY_STORAGE_PATH or ~/.claude/memory)
            qdrant_url: Qdrant server URL (default: QDRANT_URL or http://localhost:6333)
            qdrant_path: Local directory for embedded Qdrant (default: QDRANT_PATH env).
                Mutually exclusive with qdrant_url — both set raises when the store connects.
            embedding_model: Model for embeddings (default: EMBEDDING_MODEL or all-MiniLM-L6-v2)
            qdrant_client: Pre-connected client (ownership.acquire holds the embedded
                flock through it — reuse, never construct a second one on the path)
        """
        # Read from environment with sensible defaults.
        # Resolution: explicit args → QDRANT_PATH env → QDRANT_URL env → url default.
        memory_dir = memory_dir or os.environ.get("MEMORY_STORAGE_PATH", "~/.claude/memory")
        if qdrant_url is None and qdrant_path is None:
            qdrant_path = os.environ.get("QDRANT_PATH") or None
            qdrant_url = os.environ.get("QDRANT_URL") or None
            if qdrant_path is None and qdrant_url is None:
                qdrant_url = "http://localhost:6333"
        embedding_model = embedding_model or os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

        # File storage
        self.memory_dir = Path(memory_dir).expanduser()
        assert_test_isolation(storage_path=self.memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Vector store (uses core infrastructure)
        self._store: VectorStore | None = None
        self._qdrant_url = qdrant_url
        self._qdrant_path = qdrant_path
        self._qdrant_client = qdrant_client

        # Embeddings (uses core infrastructure)
        self._embedder: Embedder | None = None
        self._embedding_model = embedding_model

        # BM25 sparse encoder for hybrid search
        self._sparse_encoder = None
        self._sparse_vocab_rejected = False
        self._bm25_path = self.memory_dir / "_bm25_vocab.json"
        self._event_log: EventLog | None = None

        self._knowledge_graph: KnowledgeGraph | None = None

        # Telemetry
        self._telemetry = Telemetry.get()
        self._observer = ObservationEngine()

    # -------------------------------------------------------------------------
    # LAZY INITIALIZATION: Load on first use
    # -------------------------------------------------------------------------

    @property
    def sparse_encoder(self):
        """Get BM25 encoder, loading from disk if available.

        A vocab carrying a ``_binding`` for a different store is refused
        (dense-only, logged once) — decoding with the wrong vocab would return
        silently wrong sparse matches. Headerless vocabs load as always.
        """
        if (
            self._sparse_encoder is None
            and not self._sparse_vocab_rejected
            and self._bm25_path.exists()
        ):
            import json

            from core import BM25Encoder

            try:
                binding = (json.loads(self._bm25_path.read_text()) or {}).get("_binding")
            except (OSError, ValueError):
                binding = None
            target = str(self._qdrant_path or self._qdrant_url)
            if binding is not None and (
                binding.get("target") != target or binding.get("collection") != self.COLLECTION
            ):
                logger.warning(
                    f"BM25 vocab at {self._bm25_path} is bound to "
                    f"{binding.get('target')}/{binding.get('collection')}, not this store "
                    f"({target}/{self.COLLECTION}) — running dense-only; "
                    "run `rekall reindex` to rebuild the vocab for this store"
                )
                self._sparse_vocab_rejected = True
                return None
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
                path=self._qdrant_path,
                sparse_encoder=self.sparse_encoder,
                client=self._qdrant_client,
                embedding_dim=self.embedder.dimensions,
            )
            # Create indexes for filtering
            for field in ["date", "project", "type", "memory_id"]:
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

    @property
    def event_log(self) -> EventLog:
        if self._event_log is None:
            self._event_log = EventLog(self.memory_dir / "_events.jsonl")
        return self._event_log

    @property
    def reindex_sentinel(self) -> Path:
        """In-progress reindex marker: inside the embedded store, or next to YAML."""
        if getattr(self, "_qdrant_path", None):
            return Path(self._qdrant_path) / ".rekall-reindex-in-progress"
        return self.memory_dir / ".reindex-sentinel"

    def _assert_reindex_complete(self) -> None:
        # Bare test doubles (object.__new__) have no storage roots to check.
        if getattr(self, "memory_dir", None) is None:
            return
        if self.reindex_sentinel.exists():
            raise RuntimeError(
                f"an interrupted reindex left {self.reindex_sentinel} — the vector "
                "store may be incomplete; run `rekall reindex` to rebuild it"
            )

    def record_event(
        self,
        *,
        event_type: str,
        project: str,
        agent: str = "unknown",
        source: str = "memory_manager",
        memory_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            merged: dict[str, Any] = dict(payload or {})
            merged.setdefault("memory_ids", list(memory_ids or []))
            self.event_log.append(
                MemoryEvent(
                    event_type=event_type,
                    project=project,
                    agent=agent,
                    source=source,
                    payload=merged,
                )
            )
        except Exception:
            logger.warning("record_event failed silently", exc_info=True)

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
            self._assert_reindex_complete()
            content = Sanitizer.sanitize(content)
            scope = scope or ScopeDetector.detect(project=project)
            project_name = project or scope.project or "general"

            if "/" in project_name or "\\" in project_name or ".." in project_name:
                raise ValueError(f"Invalid project name: {project_name!r}")

            payload = {
                "content": content,
                "type": type,
                "project": project_name,
                "reinforcement_count": 0,
                **scope.to_metadata(),
                **metadata,
            }
            payload.update(summarize_lifecycle(payload))
            payload["entities"] = extract_entities(content)
            payload["embedding_text"] = build_embedding_text(content, payload)
            # Dense-representation version: 2 = encode(content). Migration skip-marker.
            payload["repr_version"] = 2

            existing_memory_id = self._find_duplicate_memory_id(
                content=content,
                query_text=payload["embedding_text"],
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
                **payload,
                "date": date,
                "timestamp": timestamp,
            }

            # Save to file (durability)
            self._save_to_file(memory_id, content, payload, type, date)

            # Save to vector store (searchability). Dense = raw content (repr v2:
            # boilerplate diluted query cosines by ~0.2); sparse BM25 keeps the
            # enriched embedding_text for lexical entity/project matching.
            embedding_text = payload["embedding_text"]
            vector = self.embedder.encode(content)
            self.store.save(
                id=memory_id,
                vector=vector,
                payload=payload,
                content=embedding_text,
            )

            self.record_event(
                event_type="memory_saved",
                project=project_name,
                agent=str(payload.get("agent") or scope.agent or "unknown"),
                source=str(
                    payload.get("source_tool")
                    or payload.get("source_event")
                    or "memory_manager.save"
                ),
                payload={
                    "memory_id": memory_id,
                    "type": type,
                    "tier": payload.get("tier"),
                    "cwd": payload.get("cwd"),
                    "repo_name": payload.get("repo_name"),
                },
            )

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
                logger.warning(
                    "Auto-linking failed, memory saved without graph edges", exc_info=True
                )

            # Post-save hook: fires only AFTER the vector write completed.
            self._maybe_bootstrap_sparse()

            logger.info(f"Saved memory: {memory_id}")
            return memory_id

    def _maybe_bootstrap_sparse(self) -> None:
        """BM25 bootstrap: 50th vector write on a vocab-less store goes hybrid."""
        if self._sparse_encoder is not None or self._bm25_path.exists():
            return

        from memory.reindex import BOOTSTRAP_THRESHOLD, bootstrap_sparse

        # Test doubles may lack count() or return non-ints — a real store never does.
        counter = getattr(self.store, "count", None)
        count = counter() if callable(counter) else None
        if not isinstance(count, int) or count < BOOTSTRAP_THRESHOLD:
            return
        bootstrap_sparse(self)

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

        metadata = sanitize_observation_metadata(metadata)
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
        query_text: str | None = None,
        project: str,
        memory_type: str,
    ) -> str | None:
        """Return existing memory id for near-identical memories in same project/type.

        Raw content first: repr v2 stores encode(content), so that's the dense
        leg's match. embedding_text second: BM25 leg + pre-migration vectors.
        """
        search_texts = [content]
        if query_text and query_text != content:
            search_texts.append(query_text)

        normalized = " ".join(content.split()).strip().lower()

        def _match_exact(matches: list[dict[str, Any]]) -> str | None:
            for match in matches:
                existing = " ".join((match.get("content") or "").split()).strip().lower()
                if existing == normalized:
                    return match.get("memory_id")
            return None

        for search_text in search_texts:
            try:
                matches = self.store.search(
                    vector=self.embedder.encode(search_text),
                    limit=3,
                    filters={"project": project, "type": memory_type},
                    score_threshold=0.97,
                    query_text=search_text,
                )
            except Exception:
                continue

            duplicate_id = _match_exact(matches)
            if duplicate_id:
                return duplicate_id

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

        updated_by_tier: dict[str, int] = {
            "working": 0,
            "episodic": 0,
            "semantic": 0,
            "identity": 0,
        }
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
            new_payload.update(
                {
                    "tier": result.tier,
                    "durability": result.durability,
                    "lifecycle_reason": result.reason,
                    "retention_days": compute_retention_days(signals.memory_type, result.tier),
                }
            )
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

    def update_memory_content(self, memory_id: str, appended_text: str) -> dict[str, Any]:
        """Append text to a memory's content, id-stable (spec 2026-07-08).

        memory_id = sha256(content|save-timestamp) with the timestamp frozen at
        save — appending content never changes the id, so graph edges stay
        valid. The vector IS re-encoded: store.save upserts at the same point
        id (set_payload would leave a stale embedding).
        """
        self._assert_reindex_complete()
        found = self.store.get_many([memory_id])
        if not found:
            raise ValueError(f"Memory not found: {memory_id}")
        payload = dict(found[0])

        appended_text = Sanitizer.sanitize(appended_text)
        new_content = f"{payload['content']}\n\n{appended_text}"
        payload["content"] = new_content
        payload["entities"] = extract_entities(new_content)
        payload["embedding_text"] = build_embedding_text(new_content, payload)

        self._mutate_in_yaml(memory_id, new_content, payload)

        # Repr v2: dense re-encodes raw content; embedding_text feeds the sparse leg.
        payload["repr_version"] = 2
        vector = self.embedder.encode(new_content)
        self.store.save(
            id=memory_id,
            vector=vector,
            payload=payload,
            content=payload["embedding_text"],
        )
        return payload

    def _mutate_in_yaml(self, memory_id: str, new_content: str, payload: dict) -> None:
        """Find the YAML entry by id across nested project dirs, rewrite atomically.

        Narrowed to the date embedded in the id (same trick as delete()) —
        scanning every YAML per close is a free 100x saved.
        """
        date_prefix = memory_id.split("_")[0]
        pattern = f"{date_prefix}.yaml" if date_prefix.count("-") == 2 else "*.yaml"
        for yaml_file in self.memory_dir.rglob(pattern):
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
            entry = next(
                (
                    e
                    for entries in data.values()
                    if isinstance(entries, list)
                    for e in entries
                    if isinstance(e, dict) and e.get("id") == memory_id
                ),
                None,
            )
            if entry is None:
                continue
            entry["content"] = new_content
            for key in ("entities", "embedding_text"):
                if key in entry:
                    entry[key] = payload[key]
            fd, tmp_path = tempfile.mkstemp(dir=yaml_file.parent, suffix=".yaml.tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    yaml.dump(
                        data, f, default_flow_style=False, sort_keys=False, allow_unicode=True
                    )
                os.replace(tmp_path, yaml_file)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            return
        logger.warning(f"YAML entry not found for {memory_id}; only the vector will be updated")

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
        self._assert_reindex_complete()
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
                    yaml.dump(
                        data, f, default_flow_style=False, sort_keys=False, allow_unicode=True
                    )
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
            prune_superseded: Raises ValueError — use POST /api/memory/prune/superseded instead
            dry_run: Report what would be deleted without deleting

        Returns:
            Stats dict with pruning counts and flagged contradictions
        """
        self._assert_reindex_complete()
        if prune_superseded:
            raise ValueError(
                "prune_superseded is gated: use POST /api/memory/prune/superseded "
                "(backup + age/reinforcement/cap gates). Direct supersedes pruning "
                "caused the 2026-07-05 99-memory data loss."
            )

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

        # 2. Flag contradictions (do NOT delete) — always runs, not gated on prune_superseded
        graph = self.knowledge_graph
        seen_pairs: set[tuple[str, str]] = set()
        for source, target, edge_data in graph._graph.edges(data=True):
            if edge_data.get("relation") == "contradicts":
                pair = tuple(sorted([source, target]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                stats["contradictions_flagged"] += 1
                stats["contradictions"].append(
                    {
                        "memory_a": source,
                        "memory_b": target,
                    }
                )

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
        score_threshold: float = 0.35,
        task_hint: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recall relevant memories using semantic search.

        Args:
            query: What to search for
            limit: Max results
            project: Filter by project
            type: Filter by memory type
            days_back: Only search last N days
            score_threshold: Minimum similarity (0-1)
            task_hint: Short phrase (2+ words) for the caller's current task;
                matching results surface first, survivor floor ceil(limit/2)

        Returns:
            List of memories with scores

        Example:
            memories = memory.recall("architecture decisions")
            memories = memory.recall("preferences", project="my-app")
        """
        with self._telemetry.track("memory.recall"):
            self._assert_reindex_complete()
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

            # Phase 1: SEED — dense search. With a project filter, the project
            # token in the query may be filter metadata (pure noise against
            # repr v2 content vectors: measured 0.662 -> 0.763 without it) or
            # the query's only semantic anchor ("what were we working on in
            # svc-api" collapses 0.55 -> 0.10 without it). Probe with BOTH and
            # keep each memory's best cosine; BM25 keeps the full query.
            dense_queries = [query]
            if project and _is_project_shaped(project):
                normalized_query = " ".join(query.split())
                stripped = " ".join(
                    re.sub(rf"\b{re.escape(project)}\b", " ", query, flags=re.IGNORECASE).split()
                )
                if stripped and stripped != normalized_query:
                    dense_queries.append(stripped)

            graph = self.knowledge_graph
            graph_stats = graph.stats()
            graph_has_edges = graph_stats["edges"] > 0
            graph_has_nodes = graph_stats["nodes"] > 0

            seeds_by_id: dict[str, dict[str, Any]] = {}
            unkeyed: list[dict[str, Any]] = []
            for probe_index, dense_query in enumerate(dense_queries):
                for result in self.store.search(
                    vector=self.embedder.encode(dense_query),
                    limit=limit * 2 if limit and graph_has_edges else limit,
                    filters=filters if filters else None,
                    score_threshold=score_threshold,
                    query_text=query,
                ):
                    memory_id = result.get("memory_id")
                    if not memory_id:
                        # No stable key to max-fuse on; keep first-probe copies only.
                        if probe_index == 0:
                            unkeyed.append(result)
                    elif memory_id not in seeds_by_id or result.get("score", 0.0) > seeds_by_id[
                        memory_id
                    ].get("score", 0.0):
                        seeds_by_id[memory_id] = result
            seed_results = [*seeds_by_id.values(), *unkeyed]

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

                # Batch-fetch all expanded neighbors in ONE retrieve call
                # (was N+1: one vector search per neighbor). Graph-expanded
                # items are ranked by the composite scorer via graph_proximity,
                # not vector similarity, so their vector score is 0.
                new_ids = [mid for mid in (expanded_ids - seed_ids) if isinstance(mid, str)]
                for result in self.store.get_many(new_ids):
                    memory_id = result.get("memory_id")
                    if memory_id and memory_id not in seed_ids:
                        seed_results.append({**result, "score": 0.0, "_graph_expanded": True})
                        seed_ids.add(memory_id)

                # record_access() mutates in-memory and marks the graph dirty;
                # the next save()/delete() flushes it. Recall stays read-only on
                # disk — no fsync-per-query write amplification, no read/read race.

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
                            "timestamp": result.get("timestamp"),
                            "type": result.get("type"),
                            "project": result.get("project"),
                            "memory_id": memory_id,
                            "entities": result.get("entities") or [],
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
                        "timestamp": result.get("timestamp"),
                        "type": result.get("type"),
                        "project": result.get("project"),
                        "memory_id": memory_id,
                        "tier": tier,
                        "entities": result.get("entities") or [],
                    }
                )

            scored.sort(key=lambda item: item["score"], reverse=True)

            # Post-filter by date (string comparison works since format is YYYY-MM-DD)
            if cutoff_date:
                scored = [r for r in scored if (r.get("date") or "") >= cutoff_date]

            # Context partition (spec 2026-07-08): post-score deterministic
            # reorder with survivor floor; task_hint=None is identity.
            from memory.context_match import partition_by_context

            results = partition_by_context(scored, task_hint, limit)

            # Stage B freshness annotation (read-only; spec 2026-07-06)
            try:
                from memory.freshness import detect_conflict_groups, mark_outdated

                top_ids = [m["memory_id"] for m in results if m.get("memory_id")]
                vecs = {
                    r.get("memory_id"): r.get("_vector")
                    for r in self.store.get_many(top_ids, with_vectors=True)
                    if r.get("memory_id")
                }
                groups = detect_conflict_groups(results, self.knowledge_graph, vecs)
                mark_outdated(results, groups)
            except Exception:
                logger.debug("freshness annotation skipped", exc_info=True)

            return results

    def recall_cross_project(
        self,
        query: str,
        *,
        current_project: str,
        limit: int = 8,
        related_limit: int = 8,
    ) -> dict[str, Any]:
        """Recall relevant memories from the current project, related projects, and global memory."""
        same_project = [
            {**item, "scope": "same_project"}
            for item in self.recall(query=query, project=current_project, limit=limit)
        ]
        same_ids = {item.get("memory_id") for item in same_project if item.get("memory_id")}

        related_projects: list[dict[str, Any]] = []
        global_hits: list[dict[str, Any]] = []

        for item in self.recall(query=query, project=None, limit=related_limit):
            memory_id = item.get("memory_id")
            project = item.get("project") or "general"
            if memory_id in same_ids:
                continue

            enriched = {**item}
            if project == "general":
                enriched["scope"] = "global"
                global_hits.append(enriched)
            elif project != current_project:
                enriched["scope"] = "related_project"
                related_projects.append(enriched)

        return {
            "query": query,
            "current_project": current_project,
            "same_project": same_project,
            "related_projects": related_projects[:limit],
            "global": global_hits[:limit],
        }

    def recall_formatted(
        self,
        query: str,
        limit: int = 5,
        project: str | None = None,
        type: str | None = None,
        days_back: int | None = None,
        task_hint: str | None = None,
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
            task_hint=task_hint,
        )

        if not memories:
            return "No relevant memories found."

        return self._format_with_guidance(memories)

    def _format_with_guidance(self, memories: list[dict]) -> str:
        """Format memories with type-specific guidance."""
        # Context-matched first (spec 2026-07-08), then newest-first freshness
        # (spec 2026-07-06). Two stable passes: timestamp, then matched flag.
        memories = sorted(
            memories,
            key=lambda m: m.get("timestamp") or m.get("date") or "",
            reverse=True,
        )
        # Outdated entries stay in timestamp position — their stub text points
        # at "the newer entry above", which promotion would falsify.
        memories = sorted(
            memories,
            key=lambda m: 0 if m.get("_context_matched") and not m.get("_outdated") else 1,
        )

        from collections import Counter

        type_counts = Counter(m.get("type", "note") for m in memories)
        header = ""
        if any(c >= 2 for c in type_counts.values()):
            header = (
                "*Entries are newest-first. If entries conflict, "
                "the newest is correct — ignore older values.*\n\n"
            )

        # Group by type
        by_type: dict[str, list[dict]] = {}
        for mem in memories:
            t = mem.get("type", "note")
            by_type.setdefault(t, []).append(mem)

        def _line(m: dict) -> str:
            if m.get("_outdated"):
                return "- [outdated — replaced by the newer entry above]"
            return f"- {m['content']} ({m.get('date', 'unknown date')})"

        sections = []

        # Preferences - explicitly mark as flexible
        if "preference" in by_type:
            prefs = by_type.pop("preference")
            lines = ["## User Preferences (suggestions, not requirements)"]
            lines.append("*Show these as the default, but always offer alternatives.*\n")
            for p in prefs:
                lines.append(_line(p))
            sections.append("\n".join(lines))

        # Decisions - these are more fixed but can be revisited
        if "decision" in by_type:
            decisions = by_type.pop("decision")
            lines = ["## Past Decisions (established, but can be changed)"]
            lines.append("*Reference these but ask if user wants to reconsider.*\n")
            for d in decisions:
                lines.append(_line(d))
            sections.append("\n".join(lines))

        # Requirements - these are hard constraints
        if "requirement" in by_type:
            reqs = by_type.pop("requirement")
            lines = ["## Requirements (must follow)"]
            lines.append("*These are constraints that must be respected.*\n")
            for r in reqs:
                lines.append(_line(r))
            sections.append("\n".join(lines))

        # Facts/context - informational
        if "fact" in by_type:
            facts = by_type.pop("fact")
            lines = ["## Known Facts (context)"]
            for f in facts:
                lines.append(_line(f))
            sections.append("\n".join(lines))

        # Everything else (notes, learnings, etc.)
        for mem_type, mems in by_type.items():
            lines = [f"## {mem_type.title()}s"]
            for m in mems:
                lines.append(_line(m))
            sections.append("\n".join(lines))

        return header + "\n\n".join(sections)

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

            points = self.store.scroll(
                filters=filters if filters else None, limit=limit, with_vectors=True
            )
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
                    lines.append(f"- `{source_id}` supersedes `{target_id}` (score: {weight:.3f})")
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
                        f"- `{source_id}` and `{target_id}` may conflict (score: {weight:.3f})"
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
                    source = self._memory_snippet(
                        points_by_id.get(source_id, {}).get("content", "")
                    )
                    target = self._memory_snippet(
                        points_by_id.get(target_id, {}).get("content", "")
                    )
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

    def get_project_capsule(self, project: str, limit: int = 300) -> dict[str, Any]:
        from memory.capsules import build_project_capsule

        return build_project_capsule(self, project=project, limit=limit)

    def doctor(self, project: str | None = None) -> dict[str, Any]:
        from memory.doctor import run_memory_doctor

        return run_memory_doctor(self, project=project)

    def reflex(
        self,
        *,
        text: str,
        project: str | None = None,
        limit: int = 4,
    ) -> dict[str, Any]:
        from memory.reflex import build_reflex_packet

        return build_reflex_packet(self, text=text, project=project, limit=limit)

    def get_memory_detail(
        self,
        memory_id: str,
        current_project: str | None = None,
    ) -> dict[str, Any]:
        """Enriched single-memory detail: relationships, provenance, lifecycle, storage.

        Backward-compatible: memory, neighbors, scope keep their existing shapes.
        Missing-memory contract: memory=None, neighbors=[], scope=None.
        """
        # 1. Qdrant lookup
        memory = self.store.get_by_id(memory_id)
        qdrant_hit = memory is not None

        # 2. YAML presence — always check (date-scoped for performance)
        yaml_entry = self._find_in_yaml(memory_id)
        yaml_hit = yaml_entry is not None

        # 3. YAML fallback when not in Qdrant
        if not qdrant_hit and yaml_hit:
            memory = yaml_entry

        storage: dict[str, bool] = {"qdrant": qdrant_hit, "yaml": yaml_hit}

        # 3. Not found anywhere — preserve old contract exactly
        if not memory:
            return {
                "memory": None,
                "neighbors": [],
                "scope": None,
                "relationships": [],
                "provenance": None,
                "lifecycle": None,
                "storage": storage,
                "warnings": [],
            }

        # 4. Graph edges — both directions
        graph = self.knowledge_graph
        edges = (
            graph.get_edges(memory_id, direction="both")
            if graph.stats().get("nodes", 0) > 0
            else []
        )

        relationships: list[dict[str, Any]] = []
        missing_neighbor_ids: list[str] = []

        for edge in edges:
            if edge.source == memory_id:
                direction = "out"
                neighbor_id = edge.target
            else:
                direction = "in"
                neighbor_id = edge.source

            neighbor_memory = self.store.get_by_id(neighbor_id)
            if neighbor_memory is None:
                missing_neighbor_ids.append(neighbor_id)

            relationships.append(
                {
                    "source_id": edge.source,
                    "target_id": edge.target,
                    "neighbor_id": neighbor_id,
                    "direction": direction,
                    "relation": edge.relation,
                    "weight": edge.weight,
                    "auto": edge.auto,
                    "created": edge.created,
                    "memory": neighbor_memory,
                }
            )

        # 5. Backward-compat alias: neighbors = outgoing edges with resolved memories
        neighbors = [
            {"relation": r["relation"], "memory": r["memory"]}
            for r in relationships
            if r["direction"] == "out" and r["memory"] is not None
        ]

        # 6. Provenance (null for any missing field)
        provenance: dict[str, Any] = {
            "agent": memory.get("agent"),
            "source_tool": memory.get("source_tool"),
            "source_event": memory.get("source_event"),
            "timestamp": memory.get("timestamp"),
            "session_id": memory.get("session_id"),
            "repo_name": memory.get("repo_name"),
            "repo_remote": strip_remote_creds(memory.get("repo_remote")),
            "branch": memory.get("branch"),
            "trust_boundary": memory.get("trust_boundary"),
        }

        # 7. Lifecycle (null for any missing field)
        lifecycle: dict[str, Any] = {
            "tier": memory.get("tier"),
            "durability": memory.get("durability"),
            "retention_days": memory.get("retention_days"),
            "lifecycle_reason": memory.get("lifecycle_reason"),
        }

        # 8. Warnings
        warnings: list[str] = []
        if current_project is not None and memory.get("project") != current_project:
            warnings.append("scope_mismatch")
        _agent_absent = memory.get("agent") in (None, "", "unknown")
        if (
            _agent_absent
            and memory.get("source_tool") is None
            and memory.get("source_event") is None
        ):
            warnings.append("missing_provenance")
        if yaml_hit and not qdrant_hit:
            warnings.append("missing_index")
        if memory.get("durability") is None and memory.get("lifecycle_reason") is None:
            warnings.append("missing_lifecycle")

        result: dict[str, Any] = {
            "memory": memory,
            "neighbors": neighbors,
            "scope": {
                "project": memory.get("project"),
                "agent": memory.get("agent"),
                "repo_name": memory.get("repo_name"),
            },
            "relationships": relationships,
            "provenance": provenance,
            "lifecycle": lifecycle,
            "storage": storage,
            "warnings": warnings,
        }
        if missing_neighbor_ids:
            result["missing_neighbor_ids"] = missing_neighbor_ids

        return result

    def _find_in_yaml(self, memory_id: str) -> dict[str, Any] | None:
        """Search YAML files for a memory by id. Date-scoped when id follows YYYY-MM-DD_ format.

        Accepts both production shape ('id' key from _save_to_file) and legacy shape
        ('memory_id' key). Read-only; never writes.
        """
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})_", memory_id)
        if date_match:
            candidates = self.memory_dir.rglob(f"{date_match.group(1)}.yaml")
        else:
            candidates = self.memory_dir.rglob("*.yaml")

        for yaml_file in candidates:
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                for entries in data.values():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if (
                            isinstance(entry, dict)
                            and (entry.get("id") or entry.get("memory_id")) == memory_id
                        ):
                            return entry
            except Exception:
                continue
        return None

    def vector_health(self, sample_size: int = 256) -> dict[str, int]:
        """Sample stored vectors and count degenerate (all-zero) ones.

        Zero vectors mean embeddings were never written — semantic search is
        silently dead for those memories (real incident: 2026-07).
        """
        from memory.graph import _coerce_vector

        try:
            sample = self.store.scroll(limit=sample_size, with_vectors=True)
        except Exception:
            return {"sampled": 0, "zero_vectors": 0}

        zero_vectors = 0
        for point in sample:
            vector = _coerce_vector(point.get("vector"))
            if not vector or not any(v != 0 for v in vector):
                zero_vectors += 1
        return {"sampled": len(sample), "zero_vectors": zero_vectors}

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
                "vector_health": self.vector_health(),
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

    def clear_project(self, project: str) -> dict[str, int]:
        """Delete all memories for a project from YAML, vector store, AND knowledge graph."""
        self._assert_reindex_complete()
        with self._telemetry.track("memory.clear_project"):
            points = self.store.scroll(filters={"project": project}, limit=10000)
            ids = [p["memory_id"] for p in points if p.get("memory_id")]
            deleted = sum(1 for memory_id in ids if self.delete(memory_id))

            # Vector points whose YAML was already gone aren't reachable via delete().
            self.store.delete(filters={"project": project})

            # YAML entries that never reached the vector store.
            strays = 0
            project_dir = self.memory_dir / project
            if project_dir.is_dir():
                for yaml_file in list(project_dir.rglob("*.yaml")):
                    data = yaml.safe_load(yaml_file.read_text()) or {}
                    for value in data.values():
                        if isinstance(value, list):
                            for entry in value:
                                if entry.get("id"):
                                    self.knowledge_graph.remove_node(entry["id"])
                                    strays += 1
                    yaml_file.unlink()
                self.knowledge_graph.save()

            logger.info(
                f"Cleared project {project}: {deleted} deleted, {strays} stray YAML entries"
            )
            return {"deleted": deleted, "strays_removed": strays}
