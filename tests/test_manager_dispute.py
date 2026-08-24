"""set_disputed: minimal un-dispute affordance (PLAN.md T5 deliverable 4).

disputed=true is set by reinforce.py on a `wrong` feedback verdict and
suppresses the memory from recall ranking pending human review. This is the
resolution action: clear the flag via the same read-update-write path as
set_identity_pin, no new mutation machinery, no tier/reclassification since
disputed doesn't feed classify().
"""

import pytest

from memory import MemoryManager

pytestmark = pytest.mark.integration


def test_set_disputed_false_clears_flag(memory_manager: MemoryManager):
    memory_id = memory_manager.save("wrong fact about MetalLB", type="fact", project="proj-a")
    memory_manager.store.update_payload(memory_id, {"disputed": True})

    result = memory_manager.set_disputed(memory_id, disputed=False)

    assert result is True
    stored = memory_manager.store.get_by_id(memory_id)
    assert stored["disputed"] is False


def test_set_disputed_unknown_memory_id_returns_false(memory_manager: MemoryManager):
    result = memory_manager.set_disputed("2026-01-01_note_deadbeef", disputed=False)
    assert result is False
