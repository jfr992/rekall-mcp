"""Code-level test-isolation guard: prod storage/Qdrant refused under pytest.

Fixtures in conftest.py already steer tests toward tmp paths and test Qdrant,
but fixtures can be bypassed (module-level code, direct construction). These
tests assert the guard baked into the constructors themselves — the mechanism
that would have prevented the March 2026 prod-fixture and the 2026-07-07
prod _events.jsonl incidents.
"""

from pathlib import Path

import pytest

from memory import MemoryManager

PROD_MEMORY_DIR = Path.home() / ".claude" / "memory"


def test_memory_manager_refuses_prod_storage_under_pytest():
    with pytest.raises(RuntimeError, match="test-isolation"):
        MemoryManager(memory_dir=PROD_MEMORY_DIR)


def test_event_log_refuses_prod_path_under_pytest():
    from memory.events import EventLog

    with pytest.raises(RuntimeError, match="test-isolation"):
        EventLog(PROD_MEMORY_DIR / "_events.jsonl")


def test_refuses_relocated_prod_storage_from_env(monkeypatch):
    """MEMORY_STORAGE_PATH pointing at a non-tmp prod location is refused too."""
    relocated = Path.home() / "relocated-rekall-memory"
    monkeypatch.setenv("MEMORY_STORAGE_PATH", str(relocated))
    with pytest.raises(RuntimeError, match="test-isolation"):
        MemoryManager(memory_dir=relocated / "sub")


def test_tmp_paths_pass_the_guard(tmp_path):
    """Regression: the guard must not reject the isolation pattern every test uses."""
    from memory.events import EventLog

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    assert manager.memory_dir == tmp_path
    log = EventLog(tmp_path / "_events.jsonl")
    assert log.tail() == []


def test_is_prod_qdrant_url_truth_table():
    """Prod = :6333, except the docker compose test hostnames (qdrant-test:6333)."""
    from core.utils import is_prod_qdrant_url

    assert is_prod_qdrant_url("http://localhost:6333")
    assert not is_prod_qdrant_url("http://localhost:6334")
    assert not is_prod_qdrant_url("http://qdrant-test:6333")


def test_vector_store_connect_refuses_prod_qdrant_under_pytest(monkeypatch):
    """The guard lives in _connect itself, not only in the conftest fixture."""
    from core.vector_store import VectorStore

    # conftest's autouse fixture wraps _connect; recover the real method so this
    # exercises the code-level guard, not the fixture.
    original = getattr(VectorStore._connect, "__wrapped__", VectorStore._connect)
    monkeypatch.setattr(VectorStore, "_connect", original)
    store = VectorStore(collection="isolation-guard-check", url="http://localhost:6333")
    with pytest.raises(RuntimeError, match="test-isolation"):
        store._connect()
