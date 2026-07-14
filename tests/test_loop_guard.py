"""Feedback-loop guard (U1 Task 6, mem0 #4573).

At save time, candidates near-identical (cosine >= REKALL_LOOP_GUARD_COSINE,
default 0.9) to a memory recalled/surfaced for the same project within
REKALL_LOOP_GUARD_WINDOW hours (default 12) are reinforced, never re-saved.
The existing dedupe needs exact string equality after its 0.97 gate — a
paraphrased re-save walks straight through it.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from memory.events import EventLog, MemoryEvent
from memory.manager import MemoryManager
from memory.scope import MemoryScope

SCOPE = MemoryScope(project="proj-x")
CANDIDATE_VEC = [1.0, 0.0]


def _vec(cosine: float) -> list[float]:
    """A unit vector at exactly `cosine` similarity to CANDIDATE_VEC."""
    return [cosine, (1 - cosine**2) ** 0.5]


def _mgr(tmp_path, *, recalled_vec):
    mgr = object.__new__(MemoryManager)
    mgr.memory_dir = tmp_path
    mgr._qdrant_path = None
    mgr._event_log = None  # lazy property -> real EventLog under tmp_path
    mgr._embedder = MagicMock()
    mgr._embedder.encode.return_value = list(CANDIDATE_VEC)
    mgr._store = MagicMock()
    mgr._store.search.return_value = []  # exact-dupe gate finds nothing
    mgr._store.get_many.return_value = [{"memory_id": "m-old", "_vector": recalled_vec}]
    mgr._knowledge_graph = MagicMock()
    mgr._sparse_encoder = MagicMock()  # skips the BM25 bootstrap hook
    mgr._reinforce_existing_memory = MagicMock()

    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry
    return mgr


def _seed_recall_event(mgr, *, hours_ago: float, memory_ids=("m-old",)):
    log = EventLog(mgr.memory_dir / "_events.jsonl")
    log.append(
        MemoryEvent(
            event_type="memory_recalled",
            project="proj-x",
            agent="test",
            source="test",
            payload={"memory_ids": list(memory_ids), "session_id": None},
            observed_at=(datetime.now() - timedelta(hours=hours_ago)).isoformat(),
        )
    )


def test_paraphrased_recalled_memory_reinforced_not_saved(tmp_path):
    """cosine ~0.92, different string: past the exact dedupe, caught by the guard."""
    mgr = _mgr(tmp_path, recalled_vec=_vec(0.92))
    _seed_recall_event(mgr, hours_ago=1)

    result = mgr.save("prefers concise replies with diagrams", project="proj-x", scope=SCOPE)

    assert result == "m-old"
    mgr._reinforce_existing_memory.assert_called_once_with("m-old")
    mgr._store.save.assert_not_called()


def test_unrelated_content_below_threshold_saves_normally(tmp_path):
    mgr = _mgr(tmp_path, recalled_vec=_vec(0.5))
    _seed_recall_event(mgr, hours_ago=1)

    result = mgr.save("switched the build to bazel remote cache", project="proj-x", scope=SCOPE)

    assert result != "m-old"
    mgr._reinforce_existing_memory.assert_not_called()
    mgr._store.save.assert_called_once()


def test_recall_outside_window_saves_normally(tmp_path):
    """Same paraphrase-grade similarity, but the recall is 13h old (12h window)."""
    mgr = _mgr(tmp_path, recalled_vec=_vec(0.92))
    _seed_recall_event(mgr, hours_ago=13)

    result = mgr.save("prefers concise replies with diagrams", project="proj-x", scope=SCOPE)

    assert result != "m-old"
    mgr._reinforce_existing_memory.assert_not_called()
    mgr._store.save.assert_called_once()


def test_content_encoded_exactly_once_per_save(tmp_path):
    """The hoisted encode feeds dedupe, the guard, and the store write.

    auto_link is patched out: its internal encode is a separate concern,
    this pin covers the save path itself.
    """
    from unittest.mock import patch

    mgr = _mgr(tmp_path, recalled_vec=_vec(0.5))
    content = "prefers concise replies with diagrams"

    with patch("memory.manager.auto_link"):
        mgr.save(content, project="proj-x", scope=SCOPE)

    content_encodes = [c for c in mgr._embedder.encode.call_args_list if c.args[0] == content]
    assert len(content_encodes) == 1
