"""End-to-end integration test: observe -> save -> reinforce -> promote -> recall -> resume -> prune.

Requires a real Qdrant at localhost:6334.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from memory.manager import MemoryManager
from memory.prune import PlanIdMismatch, _PLAN_STORE, apply_plan, build_plan
from memory.resume import build_resume_packet
from memory.scope import MemoryScope


pytestmark = pytest.mark.integration


@pytest.fixture
def integration_manager(tmp_path):
    """MemoryManager wired to the test Qdrant on :6334 with an isolated collection."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    collection_name = f"memento_test_{uuid4().hex[:12]}"

    mgr = MemoryManager(
        memory_dir=memory_dir,
        qdrant_url="http://localhost:6334",
    )
    # Override COLLECTION on the instance BEFORE the lazy store is first accessed.
    # The store property uses `self.COLLECTION`, so this redirect is picked up correctly.
    mgr.COLLECTION = collection_name

    yield mgr

    # Cleanup: drop the isolated collection so the test Qdrant stays clean.
    try:
        mgr.store.delete_collection()
    except Exception:
        pass


def _scope(project: str) -> MemoryScope:
    return MemoryScope(agent="claude-code", project=project, trust_boundary="personal")


def test_full_lifecycle_observe_to_resume_to_prune(integration_manager):
    """Full chain: observe -> dedupe-reinforce -> recall -> resume -> prune-plan -> apply-rejection."""
    _PLAN_STORE.clear()
    mgr = integration_manager
    project = "memento-it"

    # -------------------------------------------------------------------------
    # Step 1: observe a high-salience decision and verify it is persisted
    # -------------------------------------------------------------------------
    content = (
        "Use Go over Rust for the backend rewrite because team familiarity and tooling maturity"
    )
    result = mgr.observe(
        content,
        type="decision",
        project=project,
        scope=_scope(project),
    )
    assert isinstance(result, str), f"Expected memory_id str, got {type(result)}: {result}"
    memory_id = result

    fetched = mgr.store.get_by_id(memory_id)
    assert fetched is not None, "Memory not found in store immediately after observe"
    assert "tier" in fetched, f"Payload missing 'tier': {fetched}"
    original_tier = fetched["tier"]
    # A decision with explicit high-salience observe should land at semantic via Rule 3.
    assert original_tier == "semantic", (
        f"Expected initial tier=semantic for decision; got {original_tier}"
    )

    # -------------------------------------------------------------------------
    # Step 2: backdate the date field so reinforce_and_reclassify sees age >= 7 days
    # -------------------------------------------------------------------------
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    updated_payload = dict(fetched)
    updated_payload["date"] = old_date
    mgr.store.update_payload(memory_id, updated_payload)

    # Verify the backdate landed.
    after_backdate = mgr.store.get_by_id(memory_id)
    assert after_backdate["date"] == old_date, (
        f"Backdate did not persist; got {after_backdate['date']}"
    )

    # -------------------------------------------------------------------------
    # Step 3: reinforce 5 times via duplicate observe — dedupe path must fire
    # -------------------------------------------------------------------------
    for i in range(5):
        reinforced = mgr.observe(
            content,
            type="decision",
            project=project,
            scope=_scope(project),
        )
        assert reinforced == memory_id, (
            f"Iteration {i}: expected dedupe to return {memory_id!r}, got {reinforced!r}"
        )

    promoted = mgr.store.get_by_id(memory_id)
    assert promoted["reinforcement_count"] >= 5, (
        f"Expected reinforcement_count >= 5 after 5 reinforcements, "
        f"got {promoted.get('reinforcement_count')}"
    )
    # Original tier was semantic; reinforcement should keep it there or promote to identity.
    assert promoted["tier"] in {"semantic", "identity"}, (
        f"Expected tier in {{semantic, identity}} after reinforcement; got {promoted['tier']}"
    )

    # -------------------------------------------------------------------------
    # Step 4: recall must surface this memory
    # -------------------------------------------------------------------------
    hits = mgr.recall(
        "Go Rust backend rewrite",
        limit=5,
        project=project,
        score_threshold=0.0,
    )
    assert hits, "recall returned empty list — memory not findable"
    assert any(h["memory_id"] == memory_id for h in hits), (
        f"Expected {memory_id!r} in recall hits; got {[h['memory_id'] for h in hits]}"
    )

    # -------------------------------------------------------------------------
    # Step 5: resume packet must include the memory in `important`
    # -------------------------------------------------------------------------
    packet = build_resume_packet(mgr, scope=_scope(project))
    important_ids = [m["memory_id"] for m in packet["important"]]
    assert memory_id in important_ids, (
        f"Expected {memory_id!r} in resume packet['important']; got {important_ids}"
    )

    # -------------------------------------------------------------------------
    # Step 6: prune plan must NOT include this memory
    #   - reinforcement_count >= 5 → excluded by reinforcement gate
    #   - tier is semantic (or identity) → excluded by identity/tier check
    # -------------------------------------------------------------------------
    plan = build_plan(mgr, project=project)
    candidate_ids = {c.memory_id for c in plan.candidates}
    assert memory_id not in candidate_ids, (
        f"Reinforced semantic memory {memory_id!r} should not appear in prune plan"
    )

    # -------------------------------------------------------------------------
    # Step 7: apply_plan with wrong confirm id must raise PlanIdMismatch
    # -------------------------------------------------------------------------
    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id="wrong-id-sentinel")


def test_unknown_salience_never_in_plan_end_to_end(integration_manager):
    """Unknown-salience memories must never appear in a prune plan (regression: the bug test)."""
    _PLAN_STORE.clear()
    mgr = integration_manager
    project = "memento-it-2"

    # Save directly via manager.save — bypasses observe so salience is absent from payload.
    memory_id = mgr.save(
        content="A raw hand-saved note that must never be pruned",
        type="note",
        project=project,
        scope=_scope(project),
    )

    # Backdate it so the age gate (>= 7 days) is satisfied.
    fetched = mgr.store.get_by_id(memory_id)
    old_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    updated = dict(fetched)
    updated["date"] = old_date
    # CRITICAL: do NOT add 'salience' — that's the whole point of the test.
    updated.pop("salience", None)
    mgr.store.update_payload(memory_id, updated)

    # Confirm salience is absent from the stored payload.
    refetched = mgr.store.get_by_id(memory_id)
    assert "salience" not in refetched, (
        f"Test precondition invalid: salience unexpectedly present as {refetched.get('salience')}"
    )

    # Prune plan must NOT include this memory — unknown salience means "protected".
    plan = build_plan(mgr, project=project)
    candidate_ids = {c.memory_id for c in plan.candidates}
    assert memory_id not in candidate_ids, (
        f"REGRESSION: unknown-salience memory {memory_id!r} appeared in prune plan candidates"
    )
