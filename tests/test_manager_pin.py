"""set_identity_pin: human-only identity grant/revoke (PLAN.md Identity pinning).

pinned=True sets explicit_tier="identity" + pinned=true; classify() already
treats explicit identity as permanent (lifecycle.py:73). pinned=False clears
both flags and reclassifies at the memory's ordinary tier. No new events are
emitted — the tier change flows through the existing payload update, same as
backfill_lifecycle's read-reclassify-write (manager.py ~830-869).
"""

import pytest

from memory import MemoryManager

pytestmark = pytest.mark.integration


def test_pin_sets_identity_tier_and_pinned_flag(memory_manager: MemoryManager):
    memory_id = memory_manager.save("Ottawa timezone is EST", type="note", project="proj-a")

    result = memory_manager.set_identity_pin(memory_id, pinned=True)

    assert result is True
    stored = memory_manager.store.get_by_id(memory_id)
    assert stored["tier"] == "identity"
    assert stored["pinned"] is True
    assert stored["explicit_tier"] == "identity"


def test_unpin_clears_flags_and_reverts_to_classified_tier(memory_manager: MemoryManager):
    memory_id = memory_manager.save("Ottawa timezone is EST", type="note", project="proj-a")
    memory_manager.set_identity_pin(memory_id, pinned=True)

    result = memory_manager.set_identity_pin(memory_id, pinned=False)

    assert result is True
    stored = memory_manager.store.get_by_id(memory_id)
    assert stored["tier"] != "identity"
    assert stored.get("pinned") is not True
    assert stored.get("explicit_tier") != "identity"


def test_pin_unknown_memory_id_returns_false(memory_manager: MemoryManager):
    result = memory_manager.set_identity_pin("2026-01-01_note_deadbeef", pinned=True)
    assert result is False


def test_pin_emits_no_new_event(memory_manager: MemoryManager):
    """The tier change flows through the payload update only; pinning itself
    is not a reinforcement-pass promotion, so no memory_promoted/demoted
    duplication belongs to this call site."""
    memory_id = memory_manager.save("pin no-event test", type="note", project="proj-a")

    before_events, _, _ = memory_manager.event_log.read_from(None, limit=1000)
    memory_manager.set_identity_pin(memory_id, pinned=True)
    after_events, _, _ = memory_manager.event_log.read_from(None, limit=1000)

    assert len(after_events) == len(before_events)
