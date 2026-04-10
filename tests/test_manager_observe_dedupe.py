from unittest.mock import MagicMock, patch

from memory.observe import ObservationCandidate


def test_manager_observe_saves_when_salient(tmp_path):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = MagicMock()
    manager._embedder = MagicMock()
    manager._embedder.encode.return_value = [0.1] * 384

    with patch.object(manager, "_find_duplicate_memory_id", return_value=None):
        result = manager.observe("Decided to use PostgreSQL because reliability matters")

    assert isinstance(result, str)


def test_manager_observe_skips_when_not_salient(tmp_path):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._observer = MagicMock()
    manager._observer.evaluate.return_value = ObservationCandidate(
        content="working on file",
        memory_type="learning",
        salience=0.2,
        should_save=False,
        reason="low-signal",
    )

    result = manager.observe("working on file")

    assert isinstance(result, ObservationCandidate)
    assert result.should_save is False


def test_manager_save_returns_duplicate_existing_id(tmp_path):
    from memory.manager import MemoryManager

    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6333")
    manager._store = MagicMock()
    manager._embedder = MagicMock()
    manager._embedder.encode.return_value = [0.1] * 384

    with patch.object(manager, "_find_duplicate_memory_id", return_value="existing_123"):
        result = manager.save("User prefers concise responses", type="preference", project="proj")

    assert result == "existing_123"
    manager._store.save.assert_not_called()
