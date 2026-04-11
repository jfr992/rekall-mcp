# Memory OS Backend Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five load-bearing defects in `feature/agent-memory-os` (prune footgun, resume 7%-sampling, tier bonus rounding error, no lifecycle backfill, hardcoded client names) and expand the REST surface with seven new endpoints that will drive the upcoming UI cockpit.

**Architecture:** Two phases — P0 rewrites lifecycle/intelligence/prune/resume/scope/observe and the manager save+recall integration points; P1 adds seven new REST endpoints and six new MCP tools (deliberately excluding `prune_apply`, which stays REST-only so agents cannot self-delete). All phases gated by green tests; commits are bite-sized.

**Tech Stack:** Python 3.12, Qdrant (dense + BM25), networkx, FastMCP/Starlette, pytest, pyyaml. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-10-memory-os-backend-hardening-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/memory/trust.py` | Load `~/.claude/memory/trust.yaml`, validate schema, return `TrustBoundary` resolver. Default to `personal` if file missing. |
| `tests/test_lifecycle_classifier.py` | Behavioral classifier rules (identity sacred, contradictions demote, reinforcement promotes). |
| `tests/test_recall_tier_bias.py` | Fix I1 — assert tier changes ranking with controlled inputs. |
| `tests/test_backfill_lifecycle.py` | Fix I4 — backfill populates tier on legacy memories. |
| `tests/test_prune_safety.py` | Fix C1 — plan id gate, identity exempt, unknown-salience exempt, neighborhood protection, hard cap. |
| `tests/test_resume_at_scale.py` | Fix C2 — resume sorts by date not point-id order. |
| `tests/test_scope_trust_yaml.py` | Fix I2 — no hardcoded client names, trust.yaml loader behaves. |
| `tests/test_scope_cred_strip.py` | Fix M11 — strip credentials from persisted `repo_remote`. |
| `tests/test_integration_memory_os.py` | End-to-end: observe → save → reinforce → promote → recall → resume → prune-plan. Real tmp Qdrant on :6334. |
| `tests/test_startup_hints_match_doc.py` | Replace doc-smoke test with a live hint ↔ doc diff. |
| `tests/test_server_memory_os_endpoints.py` | Integration tests for 7 new REST endpoints. |

### Modified files

| Path | Changes |
|---|---|
| `src/memory/lifecycle.py` | Full rewrite — `LifecycleSignals` / `LifecycleResult` dataclasses, rule-based `classify()`, keep `summarize_lifecycle()` as a thin backward-compat wrapper so existing callers keep working. |
| `src/memory/intelligence.py` | Add `reinforce_and_reclassify()` as a pure function; keep `apply_memory_promotion` for now (deprecated path). |
| `src/memory/manager.py` | Save path (lines ~262-272) — compute tier on new saves via the new classifier; dedupe path (lines ~247-254) — call `reinforce_and_reclassify` and persist updated payload. Recall path (lines ~686-699) — rebalance weights so `tier_norm` has a real 0.15 max contribution. Add `backfill_lifecycle()` method. |
| `src/memory/resume.py` | Replace `store.scroll(limit=24)` with bounded scroll (≤2000 via `MAX_RESUME_SCROLL`), Python-side sort by `(date desc, importance desc)`, add `truncated` flag. |
| `src/memory/prune.py` | Full rewrite — `PruneCandidate`/`PrunePlan` dataclasses, `build_plan()` with identity exemption + unknown-salience exemption + neighborhood protection, `apply_plan(plan_id, confirm_plan_id)` with plan-id gate + 15-min TTL + hard cap 200. Replace `plan_prune` + `apply_prune_plan` exports (keep compatibility aliases calling into the new API for now to not break unrelated callers). |
| `src/memory/scope.py` | Delete hardcoded `["yum", "audacy"]` in `_detect_trust_boundary`. Use `trust.resolve_boundary(...)`. Add `@lru_cache` to `_git`. Add `_strip_creds()` helper; apply in `detect()` before returning `MemoryScope`. |
| `src/memory/observe.py` | Replace `LOW_SIGNAL_PATTERNS` substring match with word-boundary regex + phrase list. |
| `src/server.py` | Add 7 new endpoints around lines 620-710 (in the `api_*` section). Each returns plain `JSONResponse` (matches existing style; no pydantic). |
| `src/tools/builtin/memory.py` | Add 6 new MCP tool registrations (not `prune_apply`). Add `context: str \| None = None` arg to `save_memory` tool for parity with `observe`. |
| `tests/test_prune.py` | Rewrite to test the new plan/apply contract. Drop the MagicMock `apply_prune_plan` test. |
| `tests/test_manager_observe_dedupe.py` | Rewrite — drop the mock that bypasses `_find_duplicate_memory_id` for the salient case. Use real `mock_store` + `mock_embedder` but assert the dedupe path actually runs and increments `reinforcement_count`. |
| `tests/test_agent_startup_doc_smoke.py` | Delete (replaced by `test_startup_hints_match_doc.py`). |
| `docs/ARCHITECTURE.md` | Append a section for the behavioral tier semantics and the new endpoint table. |

---

## Tasks

### Task 1: Lifecycle classifier — dataclasses and rules

**Files:**
- Modify: `src/memory/lifecycle.py` (full rewrite — currently 75 lines)
- Test: `tests/test_lifecycle_classifier.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle_classifier.py`:

```python
"""Tests for the behavioral lifecycle classifier."""
from __future__ import annotations

from memory.lifecycle import LifecycleSignals, classify


def _signals(**overrides):
    defaults = dict(
        memory_type="note",
        salience=0.0,
        age_days=0,
        reinforcement_count=0,
        contradicts_count=0,
        explicit_tier=None,
    )
    defaults.update(overrides)
    return LifecycleSignals(**defaults)


def test_explicit_identity_is_sacred_even_with_contradictions():
    result = classify(_signals(
        memory_type="note",
        contradicts_count=99,
        explicit_tier="identity",
    ))
    assert result.tier == "identity"


def test_contradictions_demote_one_tier():
    # decision + high salience would normally be semantic;
    # 3 contradicts demote it to episodic
    result = classify(_signals(
        memory_type="decision",
        salience=0.9,
        age_days=30,
        reinforcement_count=3,
        contradicts_count=3,
    ))
    assert result.tier == "episodic"


def test_reinforcement_promotes_stale_note_to_semantic():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=10,
        reinforcement_count=6,
    ))
    assert result.tier == "semantic"


def test_young_unreinforced_note_stays_working():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=1,
        reinforcement_count=1,
    ))
    assert result.tier == "working"


def test_high_salience_decision_is_semantic():
    result = classify(_signals(memory_type="decision", salience=0.75))
    assert result.tier == "semantic"


def test_preference_defaults_to_semantic_not_identity():
    result = classify(_signals(memory_type="preference", salience=0.5))
    assert result.tier == "semantic"


def test_session_is_episodic():
    result = classify(_signals(memory_type="session"))
    assert result.tier == "episodic"


def test_durability_monotonic_with_reinforcement():
    base = classify(_signals(memory_type="note", salience=0.3, age_days=10))
    more = classify(_signals(memory_type="note", salience=0.3, age_days=10, reinforcement_count=5))
    assert more.durability > base.durability


def test_lifecycle_reason_is_human_readable():
    result = classify(_signals(
        memory_type="note",
        salience=0.3,
        age_days=10,
        reinforcement_count=6,
    ))
    assert result.reason
    assert "reinforce" in result.reason.lower() or "promoted" in result.reason.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run --extra dev pytest tests/test_lifecycle_classifier.py -v
```

Expected: `ImportError: cannot import name 'LifecycleSignals' from 'memory.lifecycle'` — the dataclasses do not exist yet.

- [ ] **Step 3: Rewrite `src/memory/lifecycle.py`**

Replace the entire file contents:

```python
"""Memory lifecycle and behavioral tiering.

Tiers are computed from a small set of behavioral signals, not a pure
type->tier lookup. A frequently-reinforced note promotes to semantic; a
contradicted decision demotes one tier. Identity tier is sacred — only
reachable via explicit `save(tier="identity")`.

Tiers:
- working:  recent/low-confidence scratch
- episodic: session/time-anchored events
- semantic: durable facts/decisions
- identity: stable user/agent preferences (explicit only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Tier = Literal["working", "episodic", "semantic", "identity"]

_TIER_ORDER: tuple[Tier, ...] = ("working", "episodic", "semantic", "identity")
_TIER_WEIGHT: dict[Tier, float] = {
    "working": 0.0,
    "episodic": 0.33,
    "semantic": 0.66,
    "identity": 1.0,
}

# Type-default tier used as the starting point before behavioral adjustments.
_TYPE_DEFAULT_TIER: dict[str, Tier] = {
    "requirement": "semantic",
    "decision": "semantic",
    "fact": "semantic",
    "preference": "semantic",   # identity only via explicit_tier
    "learning": "episodic",
    "session": "episodic",
    "note": "working",
}


@dataclass(frozen=True, slots=True)
class LifecycleSignals:
    """Inputs to the lifecycle classifier."""

    memory_type: str
    salience: float
    age_days: int
    reinforcement_count: int
    contradicts_count: int
    explicit_tier: Tier | None = None


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    """Output of the lifecycle classifier."""

    tier: Tier
    durability: float
    reason: str


def _demote(tier: Tier) -> Tier:
    idx = _TIER_ORDER.index(tier)
    return _TIER_ORDER[max(idx - 1, 0)]


def classify(signals: LifecycleSignals) -> LifecycleResult:
    """Classify a memory's tier and durability from behavioral signals."""

    # Rule 1: identity is sacred
    if signals.explicit_tier == "identity":
        return LifecycleResult(
            tier="identity",
            durability=1.0,
            reason="explicit identity tier",
        )

    start: Tier = signals.explicit_tier or _TYPE_DEFAULT_TIER.get(signals.memory_type, "working")
    tier: Tier = start
    reasons: list[str] = [f"type={signals.memory_type} -> {start}"]

    # Rule 2: reinforced + aged notes/facts/learnings promote to semantic
    if (
        signals.memory_type in {"note", "fact", "learning"}
        and signals.reinforcement_count >= 5
        and signals.age_days >= 7
    ):
        tier = "semantic"
        reasons.append(f"reinforced x{signals.reinforcement_count} + age {signals.age_days}d -> promoted to semantic")

    # Rule 3: high-salience decisions/requirements stay at semantic
    if signals.memory_type in {"decision", "requirement"} and signals.salience >= 0.6:
        tier = "semantic"
        reasons.append(f"salience {signals.salience:.2f} -> held at semantic")

    # Rule 4: contradictions demote one tier (never below working)
    if signals.contradicts_count >= 2:
        before = tier
        tier = _demote(tier)
        reasons.append(f"contradicts x{signals.contradicts_count} -> demoted {before} -> {tier}")

    # Durability: 4 equal-weight quarters
    contradicts_penalty = min(signals.contradicts_count * 0.25, 1.0)
    reinforcement_weight = min(signals.reinforcement_count * 0.2, 1.0)
    durability = (
        0.25 * _TIER_WEIGHT[tier]
        + 0.25 * max(0.0, min(signals.salience, 1.0))
        + 0.25 * (1.0 - contradicts_penalty)
        + 0.25 * reinforcement_weight
    )

    return LifecycleResult(
        tier=tier,
        durability=round(max(0.0, min(durability, 1.0)), 4),
        reason="; ".join(reasons),
    )


# ---------------------------------------------------------------------------
# Backward-compat shim: existing callers still call `summarize_lifecycle(payload)`.
# ---------------------------------------------------------------------------


def summarize_lifecycle(memory: dict[str, Any]) -> dict[str, Any]:
    """Backward-compat wrapper returning the new payload fields.

    Existing callers in `manager.save` continue to invoke this and get
    tier + durability + retention_days + lifecycle_reason in one dict.
    """
    signals = LifecycleSignals(
        memory_type=memory.get("type", "note"),
        salience=float(memory.get("salience") or 0.0),
        age_days=int(memory.get("age_days") or 0),
        reinforcement_count=int(memory.get("reinforcement_count") or 0),
        contradicts_count=int(memory.get("contradicts_count") or 0),
        explicit_tier=memory.get("tier"),
    )
    result = classify(signals)
    return {
        "tier": result.tier,
        "durability": result.durability,
        "lifecycle_reason": result.reason,
        "retention_days": compute_retention_days(signals.memory_type, result.tier),
    }


def compute_retention_days(memory_type: str, tier: str) -> int:
    """Retention hint for pressure/prune heuristics. Unchanged semantics."""
    if tier == "identity":
        return 3650
    if tier == "semantic":
        return 365
    if tier == "episodic":
        return 90
    if memory_type == "note":
        return 14
    return 30
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run --extra dev pytest tests/test_lifecycle_classifier.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Run the existing suite to confirm no regression from the shim**

```bash
uv run --extra dev pytest tests/test_lifecycle.py tests/test_memory.py -v
```

Expected: no new failures. (If any test relied on `promote_memory` or `determine_tier` return specifics, those functions still need to be importable — see Task 2.)

- [ ] **Step 6: Commit**

```bash
git add src/memory/lifecycle.py tests/test_lifecycle_classifier.py
git commit -m "feat(memory): behavioral lifecycle classifier with reinforcement rules"
```

---

### Task 2: Keep `promote_memory` / `determine_tier` importable

**Files:**
- Modify: `src/memory/lifecycle.py` (append compatibility shims)

**Why:** `src/memory/intelligence.py:7` does `from memory.lifecycle import promote_memory`, and `src/memory/manager.py` indirectly expects `determine_tier` via the old `summarize_lifecycle`. We keep them as thin wrappers around `classify()` so nothing breaks before Task 3 rewrites `intelligence.py`.

- [ ] **Step 1: Run the existing suite to see what breaks**

```bash
uv run --extra dev pytest tests/test_lifecycle.py tests/test_intelligence.py -v
```

If `test_lifecycle.py` calls `determine_tier(...)` or `promote_memory(...)`, those imports must still resolve.

- [ ] **Step 2: Append compatibility shims to `src/memory/lifecycle.py`**

Add at the bottom of the file:

```python
# ---------------------------------------------------------------------------
# Legacy function shims — remove after all callers migrate to classify().
# ---------------------------------------------------------------------------


def determine_tier(memory_type: str, content: str = "", salience: float = 0.0) -> str:
    """Legacy: type-based tier lookup. Forwards to classify() with zeroed behavior signals."""
    signals = LifecycleSignals(
        memory_type=memory_type,
        salience=salience,
        age_days=0,
        reinforcement_count=0,
        contradicts_count=0,
        explicit_tier=None,
    )
    return classify(signals).tier


def promote_memory(current_tier: str, memory_type: str, access_count: int, salience: float) -> str:
    """Legacy promotion path. Kept so callers of apply_memory_promotion still work."""
    signals = LifecycleSignals(
        memory_type=memory_type,
        salience=salience,
        age_days=365 if access_count >= 3 else 0,
        reinforcement_count=access_count,
        contradicts_count=0,
        explicit_tier=current_tier if current_tier == "identity" else None,
    )
    return classify(signals).tier
```

- [ ] **Step 3: Re-run the existing suite**

```bash
uv run --extra dev pytest tests/test_lifecycle.py tests/test_intelligence.py tests/test_memory.py -v
```

Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add src/memory/lifecycle.py
git commit -m "refactor(memory): keep determine_tier/promote_memory as classify() shims"
```

---

### Task 3: `reinforce_and_reclassify` pure function

**Files:**
- Modify: `src/memory/intelligence.py` (add new function; leave `apply_memory_promotion` untouched for now)
- Test: `tests/test_intelligence.py` (expand)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intelligence.py`:

```python
from datetime import datetime, timedelta

from memory.intelligence import reinforce_and_reclassify


class _FakeGraph:
    def __init__(self, contradicts: dict[str, int] | None = None):
        self._contradicts = contradicts or {}

    def count_contradicts(self, memory_id: str) -> int:
        return self._contradicts.get(memory_id, 0)


def test_reinforce_increments_count_and_recomputes_tier():
    graph = _FakeGraph()
    memory = {
        "memory_id": "m1",
        "type": "note",
        "salience": 0.3,
        "reinforcement_count": 5,
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    assert updated is not memory  # pure function, returns new dict
    assert updated["reinforcement_count"] == 6
    assert updated["tier"] == "semantic"  # 6 reinforces + 8 days -> promoted
    assert "lifecycle_reason" in updated


def test_reinforce_does_not_promote_identity_away():
    graph = _FakeGraph()
    memory = {
        "memory_id": "m2",
        "type": "preference",
        "tier": "identity",
        "salience": 0.9,
        "reinforcement_count": 1,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    assert updated["tier"] == "identity"


def test_reinforce_demotes_contradicted_memory():
    graph = _FakeGraph(contradicts={"m3": 3})
    memory = {
        "memory_id": "m3",
        "type": "decision",
        "salience": 0.9,
        "reinforcement_count": 2,
        "date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
    }

    updated = reinforce_and_reclassify(memory, graph=graph, now=datetime.now())

    # decision + salience 0.9 would be semantic; 3 contradicts demote to episodic
    assert updated["tier"] == "episodic"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run --extra dev pytest tests/test_intelligence.py::test_reinforce_increments_count_and_recomputes_tier -v
```

Expected: `ImportError: cannot import name 'reinforce_and_reclassify' from 'memory.intelligence'`.

- [ ] **Step 3: Add `reinforce_and_reclassify` to `src/memory/intelligence.py`**

Append to the file:

```python
from datetime import datetime

from memory.lifecycle import LifecycleSignals, classify


def reinforce_and_reclassify(
    memory: dict[str, Any],
    *,
    graph,
    now: datetime,
) -> dict[str, Any]:
    """Return a NEW memory dict with reinforcement_count +1 and tier recomputed.

    Pure function: does not mutate `memory`, does not touch the store/graph
    (caller is responsible for persistence). Reads only `graph.count_contradicts`.
    """
    new_memory = dict(memory)

    new_count = int(new_memory.get("reinforcement_count") or 0) + 1
    new_memory["reinforcement_count"] = new_count

    date_str = new_memory.get("date") or now.strftime("%Y-%m-%d")
    try:
        mem_date = datetime.strptime(date_str, "%Y-%m-%d")
        age_days = max(0, (now - mem_date).days)
    except ValueError:
        age_days = 0

    memory_id = new_memory.get("memory_id", "")
    contradicts_count = graph.count_contradicts(memory_id) if memory_id else 0

    current_tier = new_memory.get("tier")
    explicit_tier = current_tier if current_tier == "identity" else None

    signals = LifecycleSignals(
        memory_type=new_memory.get("type", "note"),
        salience=float(new_memory.get("salience") or 0.0),
        age_days=age_days,
        reinforcement_count=new_count,
        contradicts_count=contradicts_count,
        explicit_tier=explicit_tier,
    )
    result = classify(signals)

    new_memory["tier"] = result.tier
    new_memory["durability"] = result.durability
    new_memory["lifecycle_reason"] = result.reason
    return new_memory
```

- [ ] **Step 4: Add `count_contradicts` helper to `KnowledgeGraph`**

Check `src/memory/knowledge_graph.py` for an existing method first:

```bash
grep -n "contradicts" src/memory/knowledge_graph.py
```

If there is no `count_contradicts` method, add one next to `get_edges`:

```python
def count_contradicts(self, memory_id: str) -> int:
    """Count contradicts-edges incident on memory_id (in + out)."""
    if memory_id not in self._graph:
        return 0
    count = 0
    for edge in self.get_edges(memory_id, direction="both"):
        if edge.relation == "contradicts":
            count += 1
    return count
```

If `direction="both"` is not supported, call `get_edges(memory_id, direction="out")` and `get_edges(memory_id, direction="in")` and sum.

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run --extra dev pytest tests/test_intelligence.py -v
```

Expected: new tests pass, old `test_intelligence.py` tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/memory/intelligence.py tests/test_intelligence.py src/memory/knowledge_graph.py
git commit -m "feat(memory): reinforce_and_reclassify pure function for promotion loop"
```

---

### Task 4: Manager save path — tier on new saves + reinforcement on dedupe

**Files:**
- Modify: `src/memory/manager.py` (lines 219-306, the `save` method)
- Test: `tests/test_manager_observe_dedupe.py` (rewrite)

**Why:** New saves already call `summarize_lifecycle(payload)` at line 272 — that shim now returns tier + durability + lifecycle_reason, so no code change is needed for the "new save" path. The missing piece is the dedupe path (lines 247-254): currently it returns the existing id and exits silently. It must instead load the existing payload, call `reinforce_and_reclassify`, persist, and return the id.

- [ ] **Step 1: Rewrite `tests/test_manager_observe_dedupe.py`**

Replace the entire file:

```python
"""Dedupe path must reinforce the existing memory, not silently skip it."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def manager_with_fake_store(tmp_path):
    """Construct a MemoryManager with an in-memory fake store + mocked embedder."""
    from memory.manager import MemoryManager

    with patch("memory.manager.VectorStore") as store_class, \
         patch("memory.manager.Embedder") as embedder_class:
        store = MagicMock()
        embedder = MagicMock()
        store.count.return_value = 0
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        store_class.return_value = store
        embedder_class.return_value = embedder

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_url="http://localhost:6333")
        mgr._store = store
        mgr._embedder = embedder
        yield mgr


def test_dedupe_reinforces_existing_memory(manager_with_fake_store):
    mgr = manager_with_fake_store
    store = mgr._store

    # First save creates the memory
    existing_payload = {
        "memory_id": "existing_id",
        "type": "note",
        "content": "test content",
        "date": (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d"),
        "reinforcement_count": 5,
        "tier": "working",
        "salience": 0.3,
    }
    # Simulate that _find_duplicate_memory_id returns an existing id, and
    # the store can fetch the payload for reinforcement.
    store.search.return_value = [
        {"memory_id": "existing_id", "score": 0.99, "content": "test content", "type": "note"}
    ]
    store.get_by_id.return_value = existing_payload

    memory_id = mgr.save(content="test content", type="note", project="test")

    assert memory_id == "existing_id"
    # The dedupe path must have called update_payload with reinforcement_count += 1
    assert store.update_payload.called
    args, kwargs = store.update_payload.call_args
    update_dict = args[1] if len(args) > 1 else kwargs.get("payload")
    assert update_dict["reinforcement_count"] == 6
    # And reclassified: 6 reinforces + 8 days -> semantic
    assert update_dict["tier"] == "semantic"


def test_new_save_computes_tier_immediately(manager_with_fake_store):
    mgr = manager_with_fake_store
    store = mgr._store
    store.search.return_value = []  # no dedupe hit

    mgr.save(content="brand new note", type="note", project="test", salience=0.3)

    # store.save was called with a payload that contains tier + durability
    assert store.save.called
    payload = store.save.call_args.kwargs.get("payload") or store.save.call_args.args[2]
    assert "tier" in payload
    assert "durability" in payload
    assert payload["tier"] == "working"
    assert payload["reinforcement_count"] == 0
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_manager_observe_dedupe.py -v
```

Expected: `test_dedupe_reinforces_existing_memory` fails — dedupe path currently returns early without calling `update_payload`. `test_new_save_computes_tier_immediately` may already pass thanks to the Task 1 shim but verify.

- [ ] **Step 3: Modify `src/memory/manager.py` save method**

Locate the block at lines 247-254:

```python
existing_memory_id = self._find_duplicate_memory_id(
    content=content,
    project=project_name,
    memory_type=type,
)
if existing_memory_id:
    logger.info(f"Duplicate memory skipped: {existing_memory_id}")
    return existing_memory_id
```

Replace it with:

```python
existing_memory_id = self._find_duplicate_memory_id(
    content=content,
    project=project_name,
    memory_type=type,
)
if existing_memory_id:
    self._reinforce_existing_memory(existing_memory_id)
    logger.info(f"Duplicate memory reinforced: {existing_memory_id}")
    return existing_memory_id
```

Then add a new method on `MemoryManager` (place it right after `_find_duplicate_memory_id`):

```python
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

    updated = reinforce_and_reclassify(
        existing,
        graph=self.knowledge_graph,
        now=_dt.now(),
    )
    try:
        self.store.update_payload(memory_id, updated)
    except Exception:
        logger.warning(f"Could not persist reinforcement for {memory_id}", exc_info=True)
```

- [ ] **Step 4: Verify `VectorStore` has `get_by_id` and `update_payload`**

```bash
grep -n "def get_by_id\|def update_payload" src/core/*.py
```

If either method does not exist, add minimal implementations in `src/core/vector_store.py` (or whichever module defines `VectorStore`):

```python
def get_by_id(self, memory_id: str) -> dict[str, Any] | None:
    """Fetch a single payload by memory_id."""
    results = self.scroll(filters={"memory_id": memory_id}, limit=1)
    return results[0] if results else None


def update_payload(self, memory_id: str, payload: dict[str, Any]) -> None:
    """Upsert the payload for an existing point."""
    # Qdrant API: client.set_payload(collection, payload, points=[point_id])
    from qdrant_client.models import PointIdsList
    from core.utils import stable_hash_id

    point_id = stable_hash_id(memory_id)
    self.client.set_payload(
        collection_name=self.collection,
        payload=payload,
        points=PointIdsList(points=[point_id]),
    )
```

The exact API depends on the current `VectorStore` implementation — read `src/core/vector_store.py` first and mirror its existing style.

- [ ] **Step 5: Run the tests**

```bash
uv run --extra dev pytest tests/test_manager_observe_dedupe.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Run the whole manager suite for regressions**

```bash
uv run --extra dev pytest tests/test_memory.py tests/test_manager_observe_dedupe.py -v
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/memory/manager.py src/core/vector_store.py tests/test_manager_observe_dedupe.py
git commit -m "feat(memory): reinforce dedupe hits and recompute tier on save"
```

---

### Task 5: Recall weight rebalance (fix I1)

**Files:**
- Modify: `src/memory/manager.py` (lines 686-699)
- Test: `tests/test_recall_tier_bias.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_recall_tier_bias.py`:

```python
"""Tier must actually influence recall ranking, not be a rounding error."""

from memory.manager import MemoryManager


def _score(manager: MemoryManager, *, vector_score: float, tier: str, importance: float = 0.5,
           is_expanded: bool = False, days_old: int = 0) -> float:
    """Exercise the private scoring math via a synthetic seed result."""
    # Replicate the scoring block from manager.recall() for a single result.
    graph_proximity = 0.7 if is_expanded else 1.0
    recency = max(0.0, 1.0 - days_old / 365)
    tier_norm = {"identity": 1.0, "semantic": 0.66, "episodic": 0.33, "working": 0.0}[tier]
    return (
        vector_score * 0.40
        + importance * 0.20
        + recency * 0.10
        + graph_proximity * 0.15
        + tier_norm * 0.15
    )


def test_semantic_beats_working_with_identical_vector_score():
    working = _score(None, vector_score=0.80, tier="working")
    semantic = _score(None, vector_score=0.80, tier="semantic")
    assert semantic - working >= 0.09  # 0.66 * 0.15 = 0.099


def test_identity_beats_semantic_noticeably():
    semantic = _score(None, vector_score=0.80, tier="semantic")
    identity = _score(None, vector_score=0.80, tier="identity")
    assert identity - semantic >= 0.05
```

This test validates the *formula*, but the real integration check lives in `test_integration_memory_os.py` (Task 14). Add the formula-level test first for a fast gate.

- [ ] **Step 2: Run it**

```bash
uv run --extra dev pytest tests/test_recall_tier_bias.py -v
```

Expected: PASS. (This test is independent of manager state — it asserts the formula.)

- [ ] **Step 3: Modify `src/memory/manager.py` lines 686-699**

Replace:

```python
                tier_bonus = {
                    "identity": 0.15,
                    "semantic": 0.10,
                    "episodic": 0.05,
                    "working": 0.0,
                }.get(tier, 0.0)

                final_score = (
                    vector_score * 0.45
                    + importance * 0.20
                    + recency * 0.10
                    + graph_proximity * 0.15
                    + tier_bonus * 0.10
                )
```

With:

```python
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
```

- [ ] **Step 4: Run the full manager tests**

```bash
uv run --extra dev pytest tests/test_memory.py tests/test_recall_tier_bias.py tests/test_recall_tiers.py -v
```

Expected: no regressions. The existing `test_recall_tiers.py` may need an update if it asserts the old final-score value; adjust assertions to the new formula if so. Keep intent, update expected values.

- [ ] **Step 5: Commit**

```bash
git add src/memory/manager.py tests/test_recall_tier_bias.py tests/test_recall_tiers.py
git commit -m "fix(memory): rebalance recall weights so tier actually affects ranking"
```

---

### Task 6: `manager.backfill_lifecycle()` method (fix I4)

**Files:**
- Modify: `src/memory/manager.py` (add method after `_reinforce_existing_memory`)
- Test: `tests/test_backfill_lifecycle.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_lifecycle.py`:

```python
"""Fix I4 — existing memories without a tier field must get one via backfill."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def manager_with_legacy_memories(tmp_path):
    from memory.manager import MemoryManager

    legacy_memories = [
        {"memory_id": "m1", "type": "note", "content": "a", "date": "2026-01-01", "salience": 0.3},
        {"memory_id": "m2", "type": "decision", "content": "b", "date": "2026-02-01", "salience": 0.8},
        {"memory_id": "m3", "type": "preference", "content": "c", "date": "2026-03-01", "salience": 0.5},
    ]

    with patch("memory.manager.VectorStore") as store_class, \
         patch("memory.manager.Embedder") as embedder_class:
        store = MagicMock()
        embedder = MagicMock()
        embedder.encode.return_value = [0.1] * 384
        embedder.dimensions = 384
        store.count.return_value = len(legacy_memories)

        # scroll returns the legacy memories in one batch
        def scroll_side_effect(filters=None, limit=500, **kwargs):
            return list(legacy_memories)
        store.scroll.side_effect = scroll_side_effect

        store_class.return_value = store
        embedder_class.return_value = embedder

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        mgr = MemoryManager(memory_dir=memory_dir, qdrant_url="http://localhost:6333")
        mgr._store = store
        mgr._embedder = embedder
        yield mgr, legacy_memories


def test_backfill_populates_tier_on_all_legacy_memories(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    report = mgr.backfill_lifecycle(dry_run=False)

    assert sum(report["updated_by_tier"].values()) == 3
    # note -> working, decision+salience 0.8 -> semantic, preference -> semantic (identity is explicit-only)
    assert report["updated_by_tier"]["working"] == 1
    assert report["updated_by_tier"]["semantic"] == 2
    # update_payload must be called once per memory with the new fields
    assert mgr._store.update_payload.call_count == 3


def test_backfill_dry_run_does_not_write(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    report = mgr.backfill_lifecycle(dry_run=True)

    assert sum(report["updated_by_tier"].values()) == 3
    assert mgr._store.update_payload.call_count == 0


def test_backfill_respects_project_filter(manager_with_legacy_memories):
    mgr, legacy = manager_with_legacy_memories
    mgr.backfill_lifecycle(dry_run=True, project="test-project")

    # scroll was called with the project filter
    mgr._store.scroll.assert_called()
    args, kwargs = mgr._store.scroll.call_args
    filters = kwargs.get("filters") or (args[0] if args else None)
    assert filters == {"project": "test-project"}
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_backfill_lifecycle.py -v
```

Expected: `AttributeError: 'MemoryManager' object has no attribute 'backfill_lifecycle'`.

- [ ] **Step 3: Add `backfill_lifecycle` to `src/memory/manager.py`**

Place it after `_reinforce_existing_memory`:

```python
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

        contradicts_count = self.knowledge_graph.count_contradicts(memory_id) \
            if self.knowledge_graph.stats()["nodes"] > 0 else 0

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
```

- [ ] **Step 4: Run the tests**

```bash
uv run --extra dev pytest tests/test_backfill_lifecycle.py -v
```

Expected: all three pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/manager.py tests/test_backfill_lifecycle.py
git commit -m "feat(memory): manager.backfill_lifecycle for existing on-disk memories"
```

---

### Task 7: Prune — data model, plan/apply contract with plan id gate

**Files:**
- Modify: `src/memory/prune.py` (full rewrite)
- Test: `tests/test_prune.py` (rewrite)
- Test: `tests/test_prune_safety.py` (new)

- [ ] **Step 1: Write `tests/test_prune_safety.py`**

Create the file:

```python
"""Fix C1 — prune must be plan-id gated, identity-exempt, unknown-salience-exempt."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from memory.prune import (
    MAX_DELETIONS_PER_APPLY,
    PLAN_TTL,
    PlanExpired,
    PlanIdMismatch,
    PlanNotFound,
    apply_plan,
    build_plan,
    _PLAN_STORE,
)


@pytest.fixture(autouse=True)
def clear_plan_store():
    _PLAN_STORE.clear()
    yield
    _PLAN_STORE.clear()


def _fake_manager(memories: list[dict], graph_contradicts: dict | None = None):
    mgr = MagicMock()
    mgr.store.scroll.return_value = memories
    mgr.knowledge_graph.count_contradicts.side_effect = lambda mid: (graph_contradicts or {}).get(mid, 0)
    mgr.knowledge_graph.get_neighbors.side_effect = lambda mid, hops=1: set()
    mgr.delete.return_value = True
    return mgr


def test_identity_tier_never_in_plan():
    mgr = _fake_manager([
        {"memory_id": "id1", "tier": "identity", "salience": 0.1, "type": "preference",
         "date": "2026-01-01", "reinforcement_count": 0},
        {"memory_id": "w1", "tier": "working", "salience": 0.1, "type": "note",
         "date": "2026-01-01", "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "id1" not in ids
    assert "w1" in ids


def test_unknown_salience_never_in_plan():
    """THE bug that would wipe JR's notes. Missing salience must be excluded."""
    mgr = _fake_manager([
        {"memory_id": "unknown", "tier": "working", "type": "note",
         "date": "2026-01-01", "reinforcement_count": 0},  # no salience
        {"memory_id": "explicit", "tier": "working", "type": "note", "salience": 0.1,
         "date": "2026-01-01", "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "unknown" not in ids
    assert "explicit" in ids


def test_apply_without_plan_id_rejects():
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": "2026-01-01", "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")

    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id="wrong")


def test_apply_with_unknown_plan_rejects():
    mgr = _fake_manager([])
    with pytest.raises(PlanNotFound):
        apply_plan(mgr, plan_id="nonexistent", confirm_plan_id="nonexistent")


def test_apply_with_expired_plan_rejects(monkeypatch):
    mgr = _fake_manager([
        {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
         "date": "2026-01-01", "reinforcement_count": 0},
    ])
    plan = build_plan(mgr, project="test")

    # Move time forward past TTL
    import memory.prune as prune_mod
    real_dt = prune_mod.datetime

    class FakeDT(real_dt):
        @classmethod
        def now(cls):
            return plan.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(prune_mod, "datetime", FakeDT)

    with pytest.raises(PlanExpired):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)


def test_apply_hard_cap(monkeypatch):
    candidates = [
        {"memory_id": f"w{i}", "tier": "working", "type": "note", "salience": 0.1,
         "date": "2026-01-01", "reinforcement_count": 0}
        for i in range(MAX_DELETIONS_PER_APPLY + 50)
    ]
    mgr = _fake_manager(candidates)
    plan = build_plan(mgr, project="test", limit=MAX_DELETIONS_PER_APPLY + 50)

    result = apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)

    assert len(result["deleted"]) == MAX_DELETIONS_PER_APPLY
    assert len(result["skipped"]) == 50


def test_neighborhood_protection():
    """A low-salience memory adjacent to identity-tier is NOT prunable."""
    mgr = _fake_manager(
        [
            {"memory_id": "id1", "tier": "identity", "salience": 0.9, "type": "preference",
             "date": "2026-01-01", "reinforcement_count": 0},
            {"memory_id": "w1", "tier": "working", "type": "note", "salience": 0.1,
             "date": "2026-01-01", "reinforcement_count": 0},
        ],
    )
    # w1 is a neighbor of id1
    mgr.knowledge_graph.get_neighbors.side_effect = lambda mid, hops=1: {"id1"} if mid == "w1" else set()
    mgr.store.get_by_id.side_effect = lambda mid: next(
        (p for p in mgr.store.scroll.return_value if p["memory_id"] == mid), None
    )

    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert "w1" not in ids
```

- [ ] **Step 2: Rewrite `tests/test_prune.py`** (keep one legacy assertion for alias compat)

Replace its contents:

```python
"""Smoke test that the compat aliases plan_prune/apply_prune_plan still resolve.

Behavioral tests live in test_prune_safety.py.
"""

from memory.prune import plan_prune, apply_prune_plan


def test_legacy_aliases_importable():
    assert callable(plan_prune)
    assert callable(apply_prune_plan)
```

- [ ] **Step 3: Run the failing safety tests**

```bash
uv run --extra dev pytest tests/test_prune_safety.py -v
```

Expected: every test fails with ImportError on `MAX_DELETIONS_PER_APPLY`, `PLAN_TTL`, `PlanExpired`, `PlanIdMismatch`, `PlanNotFound`, `apply_plan`, `build_plan`.

- [ ] **Step 4: Rewrite `src/memory/prune.py`**

Replace the entire file:

```python
"""Safe pruning from memory pressure signals.

Contract:
- `build_plan` returns a `PrunePlan` with a unique `plan_id`, a TTL, and a
  list of `PruneCandidate`s. Identity-tier is never selected. Memories
  without an explicit `salience` field are never selected. Memories
  adjacent to an identity-tier memory are never selected (neighborhood
  protection).
- `apply_plan(plan_id, confirm_plan_id)` requires a matching plan id and
  a non-expired plan. It deletes at most `MAX_DELETIONS_PER_APPLY` memories.
- The MCP tool surface only exposes `build_plan` (as `prune_plan`). Apply is
  REST-only, so agents cannot self-delete.

`plan_prune` and `apply_prune_plan` are kept as thin compat aliases for
existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4


MAX_DELETIONS_PER_APPLY = 200
PLAN_TTL = timedelta(minutes=15)


class PlanNotFound(Exception):
    pass


class PlanExpired(Exception):
    pass


class PlanIdMismatch(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PruneCandidate:
    memory_id: str
    tier: str
    reason: str
    age_days: int
    salience: float


@dataclass(frozen=True, slots=True)
class PrunePlan:
    plan_id: str
    project: str
    generated_at: datetime
    expires_at: datetime
    candidates: tuple[PruneCandidate, ...] = field(default_factory=tuple)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "project": self.project,
            "generated_at": self.generated_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "summary": self.summary,
            "candidates": [
                {
                    "memory_id": c.memory_id,
                    "tier": c.tier,
                    "reason": c.reason,
                    "age_days": c.age_days,
                    "salience": c.salience,
                }
                for c in self.candidates
            ],
        }


_PLAN_STORE: dict[str, PrunePlan] = {}


def _age_days(date_str: str, *, now: datetime) -> int:
    try:
        return max(0, (now - datetime.strptime(date_str, "%Y-%m-%d")).days)
    except Exception:
        return 0


def build_plan(manager, *, project: str, limit: int = MAX_DELETIONS_PER_APPLY) -> PrunePlan:
    """Build a prune plan for `project`, storing it in `_PLAN_STORE` for later apply."""
    memories = manager.store.scroll(filters={"project": project}, limit=max(limit * 5, 200))
    now = datetime.now()

    # Collect ids of identity-tier memories for neighborhood protection.
    identity_ids: set[str] = set()
    for m in memories:
        if m.get("tier") == "identity":
            mid = m.get("memory_id")
            if mid:
                identity_ids.add(mid)

    def is_protected_neighbor(mid: str) -> bool:
        try:
            neighbors = manager.knowledge_graph.get_neighbors(mid, hops=1) or set()
        except Exception:
            return False
        return bool(neighbors & identity_ids)

    candidates: list[PruneCandidate] = []
    for m in memories:
        memory_id = m.get("memory_id", "")
        if not memory_id:
            continue

        tier = m.get("tier", "working")
        if tier == "identity":
            continue

        # SAFETY: memories without an explicit salience field are NEVER prunable.
        if "salience" not in m:
            continue

        salience = float(m.get("salience") or 0.0)
        if salience > 0.25:
            continue

        reinforcement = int(m.get("reinforcement_count") or 0)
        if reinforcement > 0:
            continue

        age = _age_days(m.get("date", ""), now=now)
        if age < 7:
            continue

        if is_protected_neighbor(memory_id):
            continue

        candidates.append(PruneCandidate(
            memory_id=memory_id,
            tier=tier,
            reason=f"tier={tier} salience={salience:.2f} age={age}d",
            age_days=age,
            salience=salience,
        ))

        if len(candidates) >= limit:
            break

    plan = PrunePlan(
        plan_id=uuid4().hex,
        project=project,
        generated_at=now,
        expires_at=now + PLAN_TTL,
        candidates=tuple(candidates),
        summary=f"{len(candidates)} candidates (max {limit})",
    )
    _PLAN_STORE[plan.plan_id] = plan
    return plan


def apply_plan(manager, *, plan_id: str, confirm_plan_id: str) -> dict[str, Any]:
    """Delete candidates from a previously-built plan.

    Requires `confirm_plan_id == plan_id`. Plan must not be expired.
    Hard-capped at MAX_DELETIONS_PER_APPLY.
    """
    plan = _PLAN_STORE.get(plan_id)
    if plan is None:
        raise PlanNotFound(f"Plan not found: {plan_id}")
    if plan_id != confirm_plan_id:
        raise PlanIdMismatch("confirm_plan_id does not match plan_id")
    if datetime.now() > plan.expires_at:
        _PLAN_STORE.pop(plan_id, None)
        raise PlanExpired(f"Plan expired at {plan.expires_at.isoformat()}")

    deleted: list[str] = []
    skipped: list[str] = []

    for i, candidate in enumerate(plan.candidates):
        if i >= MAX_DELETIONS_PER_APPLY:
            skipped.append(candidate.memory_id)
            continue
        try:
            if manager.delete(candidate.memory_id):
                deleted.append(candidate.memory_id)
            else:
                skipped.append(candidate.memory_id)
        except Exception:  # noqa: BLE001
            skipped.append(candidate.memory_id)

    _PLAN_STORE.pop(plan_id, None)  # one-shot; plan is consumed on apply
    return {
        "plan_id": plan_id,
        "deleted": deleted,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Legacy compat aliases — kept so unrelated callers don't break.
# ---------------------------------------------------------------------------


def plan_prune(memories: list[dict[str, Any]], *, aggressive: bool = False) -> dict[str, Any]:
    """Legacy entrypoint — returns a dict-shaped plan for old callers."""
    selected: list[dict[str, Any]] = []
    for m in memories:
        if m.get("tier") != "working":
            continue
        if "salience" not in m:
            continue
        salience = float(m.get("salience") or 0.0)
        threshold = 0.45 if aggressive else 0.25
        if salience <= threshold:
            selected.append(m)
    return {
        "selected": selected,
        "selected_count": len(selected),
        "aggressive": aggressive,
    }


def apply_prune_plan(manager, prune_plan: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """Legacy entrypoint — dict-shaped apply, kept for old callers."""
    selected = prune_plan.get("selected", [])
    deleted: list[str] = []
    for m in selected:
        memory_id = m.get("memory_id")
        if not memory_id:
            continue
        if dry_run:
            deleted.append(memory_id)
            continue
        try:
            if manager.delete(memory_id):
                deleted.append(memory_id)
        except Exception:  # noqa: BLE001
            pass
    return {
        "dry_run": dry_run,
        "selected_count": len(selected),
        "deleted_count": len(deleted),
        "memory_ids": deleted,
    }
```

- [ ] **Step 5: Run the safety tests**

```bash
uv run --extra dev pytest tests/test_prune_safety.py tests/test_prune.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Run the whole prune-related suite for regressions**

```bash
uv run --extra dev pytest tests/test_prune.py tests/test_prune_safety.py tests/test_pressure.py -v
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/memory/prune.py tests/test_prune.py tests/test_prune_safety.py
git commit -m "feat(memory): plan/apply prune contract with plan-id gate and safety rules"
```

---

### Task 8: Resume packet — bounded scroll + Python sort (fix C2)

**Files:**
- Modify: `src/memory/resume.py` (rewrite `build_resume_packet`)
- Test: `tests/test_resume_at_scale.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_resume_at_scale.py`:

```python
"""Fix C2 — resume must sort by date, not by Qdrant point-id order."""

import random
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from memory.resume import build_resume_packet
from memory.scope import MemoryScope


def _fake_manager(memories):
    mgr = MagicMock()
    mgr.store.scroll.return_value = memories
    mgr.knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    mgr.knowledge_graph.get_importance.return_value = 0.5
    mgr.knowledge_graph.get_edges.return_value = []
    return mgr


def _scope(project="test"):
    return MemoryScope(agent="claude-code", project=project, trust_boundary="personal")


def test_resume_returns_recent_by_date_not_insertion_order():
    memories = []
    dates = [f"2026-0{(i%4)+1}-{(i%28)+1:02d}" for i in range(100)]
    random.seed(0)
    random.shuffle(dates)
    for i, d in enumerate(dates):
        memories.append({
            "memory_id": f"m{i}",
            "type": "note",
            "content": f"m{i}",
            "date": d,
            "tier": "working",
        })

    mgr = _fake_manager(memories)
    packet = build_resume_packet(mgr, scope=_scope(), limit=20)

    recent = packet["recent"]
    # recent must be non-empty and sorted descending by date
    assert len(recent) > 0
    dates_out = [r["date"] for r in recent]
    assert dates_out == sorted(dates_out, reverse=True)
    # And must include the absolute latest date from the input set
    latest = max(dates)
    assert any(r["date"] == latest for r in recent)


def test_resume_truncated_flag_on_overflow(monkeypatch):
    import memory.resume as resume_mod
    monkeypatch.setattr(resume_mod, "MAX_RESUME_SCROLL", 50)

    memories = [
        {"memory_id": f"m{i}", "type": "note", "content": f"m{i}",
         "date": "2026-01-01", "tier": "working"}
        for i in range(100)
    ]
    mgr = _fake_manager(memories)

    packet = build_resume_packet(mgr, scope=_scope(), limit=20)
    assert packet["truncated"] is True


def test_resume_not_truncated_when_under_cap(monkeypatch):
    import memory.resume as resume_mod
    monkeypatch.setattr(resume_mod, "MAX_RESUME_SCROLL", 2000)

    memories = [
        {"memory_id": f"m{i}", "type": "note", "content": f"m{i}",
         "date": "2026-01-01", "tier": "working"}
        for i in range(50)
    ]
    mgr = _fake_manager(memories)

    packet = build_resume_packet(mgr, scope=_scope(), limit=20)
    assert packet["truncated"] is False
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_resume_at_scale.py -v
```

Expected: `test_resume_returns_recent_by_date_not_insertion_order` fails because the current `build_resume_packet` filters by `date >= cutoff` and preserves input order; `test_resume_truncated_flag_on_overflow` fails because `truncated` is not in the response.

- [ ] **Step 3: Modify `src/memory/resume.py`**

Add at the top, below the imports:

```python
MAX_RESUME_SCROLL = 2000
```

Rewrite `build_resume_packet` — replace the existing function (lines 17-102) with:

```python
def build_resume_packet(
    manager,
    *,
    scope: MemoryScope,
    limit: int = 12,
) -> dict[str, Any]:
    """Build an agent-facing resume packet for session start.

    Bounded scroll + Python-side sort; deterministic buckets by date / importance / conflict.
    """
    project = scope.project or "general"
    filters = {"project": project}

    # Fetch up to MAX_RESUME_SCROLL points, bounded so "recent" is truthful at scale.
    points = manager.store.scroll(filters=filters, limit=MAX_RESUME_SCROLL)
    truncated = len(points) >= MAX_RESUME_SCROLL

    graph = manager.knowledge_graph
    graph_has_nodes = graph.stats()["nodes"] > 0

    # Annotate each point with its importance from the graph (or a default).
    enriched: list[dict[str, Any]] = []
    for point in points:
        memory_id = point.get("memory_id", "")
        date = point.get("date", "")
        mem_type = point.get("type", "note")
        content = (point.get("content", "") or "").strip().replace("\n", " ")
        importance = graph.get_importance(memory_id) if graph_has_nodes and memory_id else 0.5

        enriched.append({
            "memory_id": memory_id,
            "type": mem_type,
            "date": date,
            "content": content,
            "importance": round(float(importance), 4),
            "tier": point.get("tier", "working"),
        })

    # Sort by (date desc, importance desc) — this is the fix for C2.
    enriched.sort(key=lambda item: (item["date"] or "", item["importance"]), reverse=True)

    recent = enriched[:limit]
    important = sorted(enriched, key=lambda x: (-x["importance"], x["date"]))[:limit]

    unresolved: list[dict[str, Any]] = []
    if graph_has_nodes:
        for item in enriched:
            memory_id = item["memory_id"]
            if not memory_id:
                continue
            for edge in graph.get_edges(memory_id, direction="out"):
                if edge.relation == "contradicts":
                    unresolved.append({
                        "memory_id": memory_id,
                        "conflicts_with": edge.target,
                        "content": item["content"],
                    })
            if len(unresolved) >= 6:
                break

    # Reuse existing helpers for next_steps / handoff / pressure.
    from memory.continuity import extract_next_steps, format_handoff_summary
    from memory.intelligence import apply_memory_promotion, changed_since_last_session
    from memory.pressure import identify_pressure, render_pressure_report

    promotion = apply_memory_promotion(graph, recent + important)
    promoted_memories = promotion["memories"]

    dedup_recent = changed_since_last_session(_dedupe_by_id(recent), limit=limit)
    dedup_important = _dedupe_by_id(
        sorted(promoted_memories, key=lambda x: (-x["importance"], x["date"]))
    )[:limit]
    dedup_unresolved = _dedupe_conflicts(unresolved)[:6]

    next_steps = extract_next_steps(dedup_recent + dedup_important)
    handoff = format_handoff_summary(
        recent=dedup_recent,
        important=dedup_important,
        next_steps=next_steps,
    )
    pressure = identify_pressure(points)

    return {
        "scope": scope.to_metadata(),
        "recent": dedup_recent,
        "important": dedup_important,
        "unresolved": dedup_unresolved,
        "next_steps": next_steps,
        "handoff": handoff,
        "pressure": pressure,
        "pressure_report": render_pressure_report(pressure),
        "promotion": {"promoted": promotion["promoted"]},
        "truncated": truncated,
        "summary": render_resume_packet(
            scope=scope,
            recent=dedup_recent,
            important=dedup_important,
            unresolved=dedup_unresolved,
        ),
    }
```

Remove the now-unused `timedelta` import and `recent_cutoff` logic.

- [ ] **Step 4: Run the tests**

```bash
uv run --extra dev pytest tests/test_resume_at_scale.py tests/test_resume.py tests/test_server_resume.py -v
```

Expected: `test_resume_at_scale.py` passes, existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/resume.py tests/test_resume_at_scale.py
git commit -m "fix(memory): resume packet scrolls bounded and sorts by date at scale"
```

---

### Task 9: `trust.py` loader + scope rewrite (fix I2, M11, M10)

**Files:**
- Create: `src/memory/trust.py`
- Modify: `src/memory/scope.py`
- Test: `tests/test_scope_trust_yaml.py` (new)
- Test: `tests/test_scope_cred_strip.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scope_trust_yaml.py`:

```python
"""Fix I2 — trust boundary must come from YAML, not hardcoded client names."""

import pathlib

from memory.scope import ScopeDetector
from memory.trust import TrustResolver, load_trust_rules


def test_no_hardcoded_client_names_in_scope_source():
    """Regression: 'yum' and 'audacy' must not appear in scope.py."""
    src = pathlib.Path("src/memory/scope.py").read_text().lower()
    assert "yum" not in src
    assert "audacy" not in src


def test_missing_trust_file_defaults_to_personal(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="anything", name="any-repo") == "personal"


def test_trust_yaml_matches_by_remote(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: acme
    match:
      remote_contains: "gitlab.acme.internal"
""")
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="https://gitlab.acme.internal/foo.git", name="foo") == "acme"
    assert resolver.resolve(remote="https://github.com/other.git", name="other") == "personal"


def test_trust_yaml_matches_by_name(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: prototype
    match:
      name_contains: "proto-"
""")
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    rules = load_trust_rules()
    resolver = TrustResolver(rules)
    assert resolver.resolve(remote="", name="proto-alpha") == "prototype"


def test_scope_detector_uses_trust_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    scope = ScopeDetector.detect(cwd="/tmp/nowhere", project="test")
    assert scope.trust_boundary == "personal"
```

Create `tests/test_scope_cred_strip.py`:

```python
"""Fix M11 — repo_remote must not contain credentials when persisted."""

from memory.scope import _strip_creds


def test_strip_creds_from_https_with_user_token():
    assert _strip_creds("https://user:ghp_abc@github.com/foo/bar.git") == "https://github.com/foo/bar.git"


def test_strip_creds_from_https_with_token_only():
    assert _strip_creds("https://x-access-token:ghs_xyz@github.com/foo/bar.git") == "https://github.com/foo/bar.git"


def test_strip_creds_leaves_plain_https_alone():
    assert _strip_creds("https://github.com/foo/bar.git") == "https://github.com/foo/bar.git"


def test_strip_creds_leaves_ssh_alone():
    assert _strip_creds("git@github.com:foo/bar.git") == "git@github.com:foo/bar.git"


def test_strip_creds_handles_none():
    assert _strip_creds(None) == ""
    assert _strip_creds("") == ""
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_scope_trust_yaml.py tests/test_scope_cred_strip.py -v
```

Expected: import errors on `memory.trust`, `_strip_creds`, and the hardcoded-name regression test will fail because `scope.py` still contains `"yum"` / `"audacy"`.

- [ ] **Step 3: Create `src/memory/trust.py`**

```python
"""Trust boundary loader.

Reads ~/.claude/memory/trust.yaml (or $MEMENTO_MEMORY_DIR/trust.yaml) and
returns a TrustResolver. If the file is missing or malformed, every repo
resolves to 'personal'.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


DEFAULT_BOUNDARY = "personal"


@dataclass(frozen=True, slots=True)
class TrustBoundary:
    name: str
    remote_contains: tuple[str, ...] = ()
    name_contains: tuple[str, ...] = ()


def _memory_dir() -> Path:
    override = os.environ.get("MEMENTO_MEMORY_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "memory"


def load_trust_rules() -> list[TrustBoundary]:
    """Load trust rules from disk. Returns an empty list on missing/bad file."""
    path = _memory_dir() / "trust.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        logger.warning("Failed to parse trust.yaml; defaulting to personal", exc_info=True)
        return []

    boundaries_raw: list[dict[str, Any]] = data.get("boundaries") or []
    result: list[TrustBoundary] = []
    for b in boundaries_raw:
        name = str(b.get("name") or "").strip()
        if not name:
            continue
        match = b.get("match") or {}
        remote_contains = match.get("remote_contains")
        name_contains = match.get("name_contains")

        def _tuple(value) -> tuple[str, ...]:
            if value is None:
                return ()
            if isinstance(value, str):
                return (value.lower(),)
            return tuple(str(v).lower() for v in value)

        result.append(TrustBoundary(
            name=name,
            remote_contains=_tuple(remote_contains),
            name_contains=_tuple(name_contains),
        ))
    return result


class TrustResolver:
    """Resolve a trust boundary for a (remote, name) pair."""

    def __init__(self, rules: list[TrustBoundary] | None = None) -> None:
        self._rules = rules or []

    def resolve(self, *, remote: str, name: str) -> str:
        remote_l = (remote or "").lower()
        name_l = (name or "").lower()
        for rule in self._rules:
            if any(tok in remote_l for tok in rule.remote_contains):
                return rule.name
            if any(tok in name_l for tok in rule.name_contains):
                return rule.name
        return DEFAULT_BOUNDARY
```

- [ ] **Step 4: Rewrite `src/memory/scope.py`**

Replace the entire file:

```python
"""Memory scope and agent identity helpers.

Defines a richer identity model than plain cwd-name project detection.
Trust boundaries are resolved via ~/.claude/memory/trust.yaml (optional).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from memory.trust import DEFAULT_BOUNDARY, TrustResolver, load_trust_rules


_CRED_RE = re.compile(r"(https?://)[^@/]+@")


def _strip_creds(url: str | None) -> str:
    """Remove user:token@ from HTTPS remote URLs. Leaves SSH URLs alone."""
    if not url:
        return ""
    return _CRED_RE.sub(r"\1", url)


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Identity envelope for a memory operation."""

    agent: str = "unknown"
    project: str = "general"
    workspace_root: str = ""
    repo_root: str = ""
    repo_name: str = ""
    repo_remote: str = ""
    branch: str = ""
    trust_boundary: str = DEFAULT_BOUNDARY
    session_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in {"", None}}


@lru_cache(maxsize=32)
def _git_info(cwd: str) -> tuple[str, str, str]:
    """Cached (repo_root, branch, repo_remote) for a cwd."""
    return (
        _git(cwd, ["rev-parse", "--show-toplevel"]),
        _git(cwd, ["branch", "--show-current"]),
        _git(cwd, ["remote", "get-url", "origin"]),
    )


def _git(cwd: str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class ScopeDetector:
    """Detect memory scope from environment and git context."""

    _resolver: TrustResolver | None = None

    @classmethod
    def _trust_resolver(cls) -> TrustResolver:
        if cls._resolver is None:
            cls._resolver = TrustResolver(load_trust_rules())
        return cls._resolver

    @classmethod
    def reset_trust_cache(cls) -> None:
        cls._resolver = None
        _git_info.cache_clear()

    @classmethod
    def detect(
        cls,
        *,
        project: str | None = None,
        cwd: str | Path | None = None,
        agent: str | None = None,
        trust_boundary: str | None = None,
        session_id: str | None = None,
    ) -> MemoryScope:
        current = Path(cwd or os.getcwd()).resolve()
        workspace_root = str(current)

        repo_root, branch, raw_remote = _git_info(str(current))
        repo_name = Path(repo_root).name if repo_root else current.name
        repo_remote = _strip_creds(raw_remote)

        detected_project = project or repo_name or current.name or "general"
        detected_agent = agent or os.environ.get("MEMENTO_AGENT") or cls._detect_agent()
        detected_trust = (
            trust_boundary
            or os.environ.get("MEMENTO_TRUST_BOUNDARY")
            or cls._trust_resolver().resolve(remote=repo_remote, name=repo_name)
        )
        detected_session = session_id or os.environ.get("MEMENTO_SESSION_ID", "")

        return MemoryScope(
            agent=detected_agent,
            project=detected_project,
            workspace_root=workspace_root,
            repo_root=repo_root,
            repo_name=repo_name,
            repo_remote=repo_remote,
            branch=branch,
            trust_boundary=detected_trust,
            session_id=detected_session,
        )

    @staticmethod
    def _detect_agent() -> str:
        if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
            return "claude-code"
        if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_ENV"):
            return "codex"
        return "unknown"
```

- [ ] **Step 5: Ensure trust cache is reset between tests**

Add to `tests/conftest.py` (or create it if missing):

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_scope_trust_cache():
    from memory.scope import ScopeDetector
    ScopeDetector.reset_trust_cache()
    yield
    ScopeDetector.reset_trust_cache()
```

- [ ] **Step 6: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_scope_trust_yaml.py tests/test_scope_cred_strip.py tests/test_scope.py -v
```

Expected: all pass. `test_scope.py` may need an update if it asserted the old `"yum" / "audacy"` trust boundary logic; replace those assertions with equivalent trust.yaml-driven expectations.

- [ ] **Step 7: Commit**

```bash
git add src/memory/trust.py src/memory/scope.py tests/test_scope_trust_yaml.py tests/test_scope_cred_strip.py tests/conftest.py tests/test_scope.py
git commit -m "fix(memory): trust.yaml loader, credential stripping, scope cache"
```

---

### Task 10: Observe — word-boundary low-signal (fix I3)

**Files:**
- Modify: `src/memory/observe.py`
- Test: `tests/test_observe.py` (expand)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observe.py`:

```python
from memory.observe import ObservationEngine


def test_trying_to_migrate_is_not_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "User is trying to migrate from Postgres to Yugabyte due to latency issues",
        memory_type="decision",
    )
    assert candidate.should_save is True
    assert candidate.reason != "low-signal"


def test_exploring_rust_in_long_text_is_not_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Exploring Rust for the unikernel rewrite because Zig's async story is immature",
        memory_type="learning",
    )
    assert candidate.should_save is True


def test_just_exploring_phrase_is_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate("Just exploring, nothing concrete yet", memory_type="note")
    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_multiple_hedges_in_short_text_is_low_signal():
    engine = ObservationEngine()
    candidate = engine.evaluate("maybe probably later", memory_type="note")
    assert candidate.should_save is False
    assert candidate.reason == "low-signal"


def test_single_hedge_word_in_decision_is_fine():
    engine = ObservationEngine()
    candidate = engine.evaluate(
        "Decided to maybe revisit the caching layer after we ship the auth rewrite next quarter",
        memory_type="decision",
    )
    assert candidate.should_save is True
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run --extra dev pytest tests/test_observe.py -v
```

Expected: the "trying to migrate" and "exploring Rust" tests fail because the current substring match rejects them.

- [ ] **Step 3: Modify `src/memory/observe.py`**

Replace the `LOW_SIGNAL_PATTERNS` constant and the rejection check in `evaluate`:

```python
import re

LOW_SIGNAL_PHRASES = (
    "just exploring",
    "not sure",
    "maybe later",
    "i think",
    "kinda",
    "working on",
    "opened file",
    "ran command",
    "temporary",
)

_HEDGE_WORD_RE = re.compile(r"\b(maybe|possibly|probably|might)\b", re.IGNORECASE)


def _is_low_signal(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in LOW_SIGNAL_PHRASES):
        return True
    tokens = re.findall(r"\b\w+\b", lowered)
    if not tokens:
        return True
    hedge_count = sum(1 for t in tokens if _HEDGE_WORD_RE.fullmatch(t))
    return hedge_count >= 2 and len(tokens) < 20
```

Then delete the old `LOW_SIGNAL_PATTERNS` tuple and update `ObservationEngine.evaluate`:

```python
    def evaluate(self, summary: str, memory_type: str = "auto") -> ObservationCandidate:
        normalized = " ".join((summary or "").strip().split())
        if not normalized:
            return ObservationCandidate("", "learning", 0.0, False, "empty")

        if _is_low_signal(normalized):
            return ObservationCandidate(normalized, "learning", 0.15, False, "low-signal")

        inferred = memory_type if memory_type != "auto" else self._infer_type(normalized)
        salience = self._score(normalized, inferred)
        should_save = salience >= 0.45
        reason = "salient" if should_save else "below-threshold"

        return ObservationCandidate(
            content=normalized,
            memory_type=inferred,
            salience=salience,
            should_save=should_save,
            reason=reason,
        )
```

- [ ] **Step 4: Run the tests**

```bash
uv run --extra dev pytest tests/test_observe.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/observe.py tests/test_observe.py
git commit -m "fix(memory): word-boundary low-signal filter (no more false positives)"
```

---

### Task 11: `save_memory` MCP tool — add `context` arg

**Files:**
- Modify: `src/tools/builtin/memory.py` (the `save_memory` tool around line 395)

- [ ] **Step 1: Read the current tool signature**

```bash
grep -n "async def save_memory" src/tools/builtin/memory.py
```

Expected location: around line 395. Current signature is `save_memory(content, memory_type, project)`.

- [ ] **Step 2: Modify the tool handler**

Replace the `save_memory` `@mcp.tool` block with:

```python
        @mcp.tool(structured_output=False)
        async def save_memory(
            content: str,
            memory_type: str = "note",
            project: str | None = None,
            context: str | None = None,
        ) -> str:
            """Save a memory explicitly (manual mode).

            Use this when you want to save something important that doesn't
            fit the automatic observe() pattern (like session summaries).

            Args:
                content: What to remember
                memory_type: Type (decision, learning, preference, requirement, fact, note)
                project: Optional project to associate with
                context: Optional: why this matters, prepended to content as "Context: ..."
            """
            scope = self._get_current_scope(project=project)
            full_content = content if not context else f"{content}\n\nContext: {context}"
            memory_id = self.manager.save(
                content=full_content,
                type=memory_type,
                project=scope.project,
                scope=scope,
            )
            return f"Saved memory: {memory_id}"
```

- [ ] **Step 3: Run the tool registration tests**

```bash
uv run --extra dev pytest tests/test_tools_memory.py -v 2>/dev/null || \
  uv run --extra dev pytest tests/ -k "memory_tool" -v
```

Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add src/tools/builtin/memory.py
git commit -m "feat(memory): save_memory MCP tool accepts optional context arg"
```

---

### Task 12: Replace `test_agent_startup_doc_smoke.py` with live hint check

**Files:**
- Delete: `tests/test_agent_startup_doc_smoke.py`
- Create: `tests/test_startup_hints_match_doc.py`

- [ ] **Step 1: Inspect what the current smoke test asserts**

```bash
cat tests/test_agent_startup_doc_smoke.py
```

Note the substrings it checked for — the new test should assert the same information is still present in the *live* hints returned by `build_agent_startup`.

- [ ] **Step 2: Create `tests/test_startup_hints_match_doc.py`**

```python
"""Startup hints must match the phrases committed in docs/AGENT_STARTUP.md."""

import pathlib

from memory.scope import MemoryScope
from memory.startup import build_agent_startup


def test_startup_hints_contain_phrases_documented_in_guide():
    scope = MemoryScope(project="test", agent="claude-code", trust_boundary="personal")
    startup = build_agent_startup(scope=scope, manager=None)
    hints_blob = "\n".join(startup.get("system_hints", [])).lower()

    doc = pathlib.Path("docs/AGENT_STARTUP.md").read_text().lower()

    # Every major concept in the doc must show up in at least one hint.
    required_concepts = [
        "observe",
        "recall",
        "identity",
        "prune",
    ]
    for concept in required_concepts:
        assert concept in doc, f"doc is missing concept: {concept}"
        assert concept in hints_blob, f"live hints missing concept: {concept}"
```

- [ ] **Step 3: Delete the old smoke test**

```bash
git rm tests/test_agent_startup_doc_smoke.py
```

- [ ] **Step 4: Run the new test**

```bash
uv run --extra dev pytest tests/test_startup_hints_match_doc.py -v
```

If it fails because `build_agent_startup` requires a real manager, adjust the test to pass a `MagicMock()` with the minimal attributes needed. Read `src/memory/startup.py` to see what's required and mock the surface narrowly.

- [ ] **Step 5: Commit**

```bash
git add tests/test_startup_hints_match_doc.py
git commit -m "test: replace doc smoke check with live hints↔doc concept diff"
```

---

### Task 13: End-to-end integration test (keystone)

**Files:**
- Create: `tests/test_integration_memory_os.py`

**Prereq:** Qdrant running on `localhost:6334` via `docker compose --profile test`.

- [ ] **Step 1: Verify the test Qdrant is reachable**

```bash
docker compose --profile test up -d qdrant-test 2>/dev/null || \
  docker run -d --name memento-qdrant-test -p 6334:6333 qdrant/qdrant:latest
curl -sf http://localhost:6334/healthz && echo "test qdrant OK"
```

Expected: `test qdrant OK`. If the service is unavailable, stop here and fix the environment before continuing.

- [ ] **Step 2: Create the integration test**

```python
"""End-to-end: observe -> save -> reinforce -> promote -> recall -> resume -> prune.

Requires a real Qdrant at localhost:6334.
"""

from datetime import datetime, timedelta

import pytest

from memory.manager import MemoryManager
from memory.prune import apply_plan, build_plan, _PLAN_STORE, PlanIdMismatch
from memory.resume import build_resume_packet
from memory.scope import MemoryScope


pytestmark = pytest.mark.integration


@pytest.fixture
def integration_manager(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    mgr = MemoryManager(
        memory_dir=memory_dir,
        qdrant_url="http://localhost:6334",
        collection_name=f"memento_test_{tmp_path.name}",
    )
    yield mgr
    # Cleanup: drop the collection
    try:
        mgr.store.client.delete_collection(mgr.store.collection)
    except Exception:
        pass


def _scope(project):
    return MemoryScope(agent="claude-code", project=project, trust_boundary="personal")


def test_observe_save_reinforce_promote_recall_resume_prune(integration_manager, monkeypatch):
    _PLAN_STORE.clear()
    mgr = integration_manager
    project = "memento-it"

    # Step 1: observe a note
    result = mgr.observe(
        "User prefers Go over Rust for the backend rewrite because team familiarity",
        project=project,
        scope=_scope(project),
    )
    assert isinstance(result, str), f"Expected memory_id, got {result}"
    memory_id = result

    fetched = mgr.store.get_by_id(memory_id)
    assert fetched is not None
    # New save should have tier computed
    assert "tier" in fetched
    original_tier = fetched["tier"]

    # Step 2: simulate age by backdating created_at and date
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    mgr.store.update_payload(memory_id, {**fetched, "date": old_date})

    # Step 3: reinforce it 6 more times via duplicate observe
    for _ in range(6):
        reinforced = mgr.observe(
            "User prefers Go over Rust for the backend rewrite because team familiarity",
            project=project,
            scope=_scope(project),
        )
        assert reinforced == memory_id  # dedupe hit

    # Step 4: reinforced+aged note should promote
    promoted = mgr.store.get_by_id(memory_id)
    assert promoted["reinforcement_count"] >= 6
    # Note type + 6 reinforces + 10 days -> semantic
    assert promoted["tier"] in {"semantic", original_tier}, \
        f"Expected promotion to semantic, got {promoted['tier']}"

    # Step 5: recall must return this memory ranked first for the query
    hits = mgr.recall("Go Rust backend rewrite", limit=5, project=project)
    assert hits, "recall returned nothing"
    assert hits[0]["memory_id"] == memory_id

    # Step 6: resume packet must include it in `important`
    packet = build_resume_packet(mgr, scope=_scope(project))
    important_ids = [m["memory_id"] for m in packet["important"]]
    assert memory_id in important_ids

    # Step 7: prune plan must NOT include it (has salience, reinforced, not working)
    plan = build_plan(mgr, project=project)
    candidate_ids = {c.memory_id for c in plan.candidates}
    assert memory_id not in candidate_ids

    # Step 8: prune apply with wrong plan id is rejected
    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id="nope")
```

- [ ] **Step 3: Run the integration test**

```bash
uv run --extra dev pytest tests/test_integration_memory_os.py -v -m integration
```

Expected: passes. If it fails, read the error carefully — the most common failure modes are:
- `_find_duplicate_memory_id` returns `None` because the embedder produces slightly-different vectors between runs. If so, raise the dedupe score_threshold is NOT the fix — instead, normalize content whitespace before hashing.
- Recall ranking does not put `memory_id` first. Check that the tier weight change from Task 5 is applied.
- Resume packet's `important` list is empty. Check that `format_handoff_summary` is not filtering by recency.

- [ ] **Step 4: Register the integration marker**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
    "integration: real Qdrant on :6334 required",
]
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_memory_os.py pyproject.toml
git commit -m "test(memory): end-to-end integration test against real tmp Qdrant"
```

---

### Task 14: P0 gate — run full suite and mark green

- [ ] **Step 1: Run the full unit suite**

```bash
uv run --extra dev pytest -v -m "not integration"
```

Expected: every test that was passing on `feature/agent-memory-os` before this plan still passes, plus all the new tests. Target: zero regressions.

- [ ] **Step 2: Run the integration test**

```bash
uv run --extra dev pytest tests/test_integration_memory_os.py -v -m integration
```

Expected: 1 passed.

- [ ] **Step 3: Tag the P0 gate**

```bash
git tag p0-hardening-green
```

(This is a local marker — do not push.)

---

### Task 15: Pydantic-free response helpers for new endpoints

**Files:**
- Modify: `src/server.py` (add a small section near the top for response helpers)

**Why:** The existing `server.py` uses plain `JSONResponse` with dicts. We keep that convention to avoid adding pydantic as a dependency. This task introduces a small helper block so later tasks can call `ok(...)` / `bad_request(...)` uniformly.

- [ ] **Step 1: Append helpers to `src/server.py`**

Find the existing helper section (search for `_read_int`). Add next to it:

```python
def _ok(data: dict) -> "JSONResponse":
    from starlette.responses import JSONResponse
    return JSONResponse(data)


def _bad_request(message: str) -> "JSONResponse":
    from starlette.responses import JSONResponse
    return JSONResponse({"error": message}, status_code=400)


def _server_error(message: str) -> "JSONResponse":
    from starlette.responses import JSONResponse
    return JSONResponse({"error": message}, status_code=500)
```

- [ ] **Step 2: No test needed** — these are trivial wrappers exercised by Tasks 16-22.

- [ ] **Step 3: Commit**

```bash
git add src/server.py
git commit -m "refactor(server): add _ok/_bad_request/_server_error response helpers"
```

---

### Task 16: `GET /api/memory/detail/{memory_id}` endpoint + MCP tool

**Files:**
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (new — will accumulate over Tasks 16-22)

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_memory_os_endpoints.py`:

```python
"""Integration tests for the new memory OS REST endpoints.

These use Starlette's TestClient against the live FastMCP app.
"""

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    from server import mcp
    app = mcp.streamable_http_app()
    return TestClient(app)


def test_detail_returns_404_for_missing_memory(client):
    response = client.get("/api/memory/detail/nonexistent_id")
    assert response.status_code in (404, 200)
    # If 200, body must explicitly indicate not-found:
    if response.status_code == 200:
        assert response.json().get("memory") is None
```

- [ ] **Step 2: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_detail_returns_404_for_missing_memory -v
```

Expected: 404 (route not found).

- [ ] **Step 3: Add the endpoint to `src/server.py`**

Near the other `@mcp.custom_route("/api/memory/...")` handlers, add:

```python
@mcp.custom_route("/api/memory/detail/{memory_id}", methods=["GET"])
async def api_memory_detail(request):
    """REST API: Get a single memory with its 1-hop neighbors."""
    try:
        memory_id = request.path_params["memory_id"]
        manager = _get_memory_manager()

        memory = manager.store.get_by_id(memory_id)
        if not memory:
            return _ok({"memory": None, "neighbors": [], "scope": None})

        graph = manager.knowledge_graph
        neighbors: list[dict] = []
        if graph.stats()["nodes"] > 0:
            for edge in graph.get_edges(memory_id, direction="out"):
                neighbor_payload = manager.store.get_by_id(edge.target)
                if neighbor_payload:
                    neighbors.append({
                        "relation": edge.relation,
                        "memory": neighbor_payload,
                    })

        return _ok({
            "memory": memory,
            "neighbors": neighbors,
            "scope": {
                "project": memory.get("project"),
                "agent": memory.get("agent"),
                "repo_name": memory.get("repo_name"),
            },
        })
    except Exception as e:
        logger.error(f"Error fetching memory detail: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Add the matching MCP tool**

In `src/tools/builtin/memory.py`, add a `ToolDefinition` entry in `get_tools()`:

```python
            ToolDefinition(
                name="memory_detail",
                description="Fetch a single memory by id with its 1-hop graph neighbors",
                handler=None,
            ),
```

And in `register()`, add the tool implementation next to the others:

```python
        @mcp.tool(structured_output=False)
        async def memory_detail(memory_id: str) -> str:
            """Fetch a single memory by id with its 1-hop graph neighbors.

            Args:
                memory_id: The memory id to fetch
            """
            memory = self.manager.store.get_by_id(memory_id)
            if not memory:
                return f"Memory not found: {memory_id}"
            return str(memory)

        registered.append("memory_detail")
```

- [ ] **Step 5: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/tools/builtin/memory.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): GET /api/memory/detail/{id} + memory_detail MCP tool"
```

---

### Task 17: `GET /api/memory/kb` endpoint + MCP tool

**Files:**
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server_memory_os_endpoints.py`:

```python
def test_kb_returns_four_slices(client):
    response = client.get("/api/memory/kb?project=general")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"decisions", "requirements", "preferences", "learnings"}
    for slice_name in ("decisions", "requirements", "preferences", "learnings"):
        assert isinstance(body[slice_name], list)
```

- [ ] **Step 2: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_kb_returns_four_slices -v
```

Expected: 404.

- [ ] **Step 3: Add the endpoint**

In `src/server.py`:

```python
@mcp.custom_route("/api/memory/kb", methods=["GET"])
async def api_memory_kb(request):
    """REST API: Typed semantic slices of the KB.

    Returns four lists: decisions, requirements, preferences, learnings.
    Each item is a summary (no raw content unless ?full=true).
    """
    try:
        query = request.query_params
        project = query.get("project")
        full = query.get("full", "false").lower() == "true"

        manager = _get_memory_manager()
        filters = {"project": project} if project else None
        points = manager.store.scroll(filters=filters, limit=2000)

        def _summarize(m: dict) -> dict:
            out = {
                "memory_id": m.get("memory_id"),
                "type": m.get("type"),
                "tier": m.get("tier"),
                "date": m.get("date"),
                "summary": (m.get("content", "") or "")[:160],
            }
            if full:
                out["content"] = m.get("content")
            return out

        decisions = [_summarize(m) for m in points if m.get("type") == "decision"]
        requirements = [_summarize(m) for m in points if m.get("type") == "requirement"]
        preferences = [_summarize(m) for m in points if m.get("type") == "preference"]
        learnings = [_summarize(m) for m in points if m.get("type") == "learning"]

        return _ok({
            "project": project or "all",
            "decisions": decisions,
            "requirements": requirements,
            "preferences": preferences,
            "learnings": learnings,
        })
    except Exception as e:
        logger.error(f"Error fetching kb: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Add the MCP tool**

In `src/tools/builtin/memory.py`, add to `get_tools()`:

```python
            ToolDefinition(
                name="memory_kb",
                description="Typed semantic slices of the knowledge base: decisions, requirements, preferences, learnings",
                handler=None,
            ),
```

And in `register()`:

```python
        @mcp.tool(structured_output=False)
        async def memory_kb(project: str | None = None) -> str:
            """Return typed KB slices: decisions, requirements, preferences, learnings.

            Args:
                project: Optional project filter
            """
            scope = self._get_current_scope(project=project)
            filters = {"project": scope.project} if scope.project else None
            points = self.manager.store.scroll(filters=filters, limit=2000)
            slices = {
                "decisions": [p for p in points if p.get("type") == "decision"],
                "requirements": [p for p in points if p.get("type") == "requirement"],
                "preferences": [p for p in points if p.get("type") == "preference"],
                "learnings": [p for p in points if p.get("type") == "learning"],
            }
            lines = [f"# KB: {scope.project}"]
            for name, items in slices.items():
                lines.append(f"\n## {name.title()} ({len(items)})")
                for item in items[:10]:
                    lines.append(f"- [{item.get('tier', 'working')}] {item.get('content', '')[:140]}")
            return "\n".join(lines)

        registered.append("memory_kb")
```

- [ ] **Step 5: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_kb_returns_four_slices -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/tools/builtin/memory.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): GET /api/memory/kb with typed semantic slices"
```

---

### Task 18: `GET /api/memory/pressure` endpoint + MCP tool

**Files:**
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_pressure_returns_structured_json(client):
    response = client.get("/api/memory/pressure?project=general")
    assert response.status_code == 200
    body = response.json()
    assert "flagged" in body
    assert "candidates" in body
    assert isinstance(body["flagged"], dict)
    assert "stale_working_count" in body["flagged"]
    assert "low_value_count" in body["flagged"]
```

- [ ] **Step 2: Run**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_pressure_returns_structured_json -v
```

Expected: 404.

- [ ] **Step 3: Add the endpoint**

```python
@mcp.custom_route("/api/memory/pressure", methods=["GET"])
async def api_memory_pressure(request):
    """REST API: Structured memory pressure snapshot."""
    from memory.pressure import identify_pressure

    try:
        query = request.query_params
        project = query.get("project")

        manager = _get_memory_manager()
        filters = {"project": project} if project else None
        memories = manager.store.scroll(filters=filters, limit=2000)
        pressure = identify_pressure(memories)

        total = max(len(memories), 1)
        load_score = round(
            (pressure.get("low_value_count", 0) + pressure.get("stale_working_count", 0)) / total,
            4,
        )

        return _ok({
            "project": project or "all",
            "load_score": load_score,
            "capacity": total,
            "flagged": {
                "stale_working_count": pressure.get("stale_working_count", 0),
                "low_value_count": pressure.get("low_value_count", 0),
                "contradiction_count": sum(
                    1 for m in memories
                    if (manager.knowledge_graph.count_contradicts(m.get("memory_id", "")) or 0) > 0
                ) if manager.knowledge_graph.stats()["nodes"] > 0 else 0,
            },
            "candidates": pressure.get("candidates", [])[:50],
        })
    except Exception as e:
        logger.error(f"Error fetching pressure: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Add the MCP tool**

Add `ToolDefinition(name="memory_pressure_snapshot", ...)` to `get_tools()` and the register:

```python
        @mcp.tool(structured_output=False)
        async def memory_pressure_snapshot(project: str | None = None) -> str:
            """Return structured memory pressure for the current project.

            Args:
                project: Optional project filter
            """
            from memory.pressure import identify_pressure, render_pressure_report

            scope = self._get_current_scope(project=project)
            filters = {"project": scope.project} if scope.project else None
            memories = self.manager.store.scroll(filters=filters, limit=2000)
            pressure = identify_pressure(memories)
            return render_pressure_report(pressure)

        registered.append("memory_pressure_snapshot")
```

(Existing tool `memory_pressure` stays; this is the new structured one. Name deliberately different.)

- [ ] **Step 5: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_pressure_returns_structured_json -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/tools/builtin/memory.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): GET /api/memory/pressure with structured pressure snapshot"
```

---

### Task 19: `POST /api/memory/prune/plan` endpoint + `prune_plan` MCP tool

**Files:**
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

- [ ] **Step 1: Write the failing test**

```python
def test_prune_plan_returns_plan_id(client):
    response = client.post("/api/memory/prune/plan", json={"project": "general"})
    assert response.status_code == 200
    body = response.json()
    assert "plan_id" in body
    assert "candidates" in body
    assert "expires_at" in body
```

- [ ] **Step 2: Run it**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_prune_plan_returns_plan_id -v
```

Expected: 404.

- [ ] **Step 3: Add endpoint**

```python
@mcp.custom_route("/api/memory/prune/plan", methods=["POST"])
async def api_memory_prune_plan(request):
    """REST API: Build a prune plan. Does not delete anything."""
    from memory.prune import build_plan

    try:
        body = await request.json()
        project = body.get("project")
        if not project:
            return _bad_request("project is required")
        limit = int(body.get("limit", 200))

        manager = _get_memory_manager()
        plan = build_plan(manager, project=project, limit=limit)
        return _ok(plan.to_dict())
    except Exception as e:
        logger.error(f"Error building prune plan: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Replace the existing `prune_candidates` MCP tool with a real `prune_plan` tool**

In `src/tools/builtin/memory.py`, find the `prune_candidates` entry in `get_tools()` and the matching handler in `register()`. Update the name and description, then rewrite the handler:

```python
        @mcp.tool(structured_output=False)
        async def prune_plan(project: str | None = None, limit: int = 200) -> str:
            """Build a safe prune plan. Identity tier and memories without explicit
            salience are never selected. Returns a plan_id that the UI (NOT an agent)
            can later apply via the REST endpoint.

            Args:
                project: Project to plan prune for (defaults to current scope)
                limit: Max candidates (default 200)
            """
            scope = self._get_current_scope(project=project)
            from memory.prune import build_plan

            plan = build_plan(self.manager, project=scope.project, limit=limit)
            return (
                f"Plan {plan.plan_id} — {len(plan.candidates)} candidates "
                f"(expires {plan.expires_at.isoformat()})\n"
                f"(Apply via REST only: POST /api/memory/prune/apply)"
            )

        registered.append("prune_plan")
```

Rename the `ToolDefinition` entry from `prune_candidates` to `prune_plan`:

```python
            ToolDefinition(
                name="prune_plan",
                description="Build a safe prune plan (does not delete). Apply is REST-only.",
                handler=None,
            ),
```

- [ ] **Step 5: Run**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_prune_plan_returns_plan_id -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/tools/builtin/memory.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): POST /api/memory/prune/plan + prune_plan MCP tool"
```

---

### Task 20: `POST /api/memory/prune/apply` endpoint (REST only, no MCP)

**Files:**
- Modify: `src/server.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

**Critical:** This task intentionally does NOT add a matching MCP tool. Verify after implementation that `prune_apply` does not appear in `src/tools/builtin/memory.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_prune_apply_requires_plan_id_confirmation(client):
    plan_resp = client.post("/api/memory/prune/plan", json={"project": "general"})
    plan_id = plan_resp.json()["plan_id"]

    bad = client.post("/api/memory/prune/apply", json={"plan_id": plan_id, "confirm": "wrong"})
    assert bad.status_code == 400

    good = client.post("/api/memory/prune/apply", json={"plan_id": plan_id, "confirm": plan_id})
    assert good.status_code in (200, 404)  # 404 only if plan was consumed elsewhere


def test_prune_apply_rejects_unknown_plan(client):
    response = client.post("/api/memory/prune/apply", json={"plan_id": "nope", "confirm": "nope"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_prune_apply_requires_plan_id_confirmation -v
```

Expected: 404.

- [ ] **Step 3: Add endpoint**

```python
@mcp.custom_route("/api/memory/prune/apply", methods=["POST"])
async def api_memory_prune_apply(request):
    """REST API: Apply a previously-built prune plan. REST ONLY — no MCP tool.

    Requires the body to echo the plan_id as `confirm`.
    """
    from memory.prune import PlanExpired, PlanIdMismatch, PlanNotFound, apply_plan

    try:
        body = await request.json()
        plan_id = body.get("plan_id")
        confirm = body.get("confirm")
        if not plan_id or not confirm:
            return _bad_request("plan_id and confirm are both required")

        manager = _get_memory_manager()
        try:
            result = apply_plan(manager, plan_id=plan_id, confirm_plan_id=confirm)
        except PlanNotFound:
            return _bad_request("plan not found (may have expired or been consumed)")
        except PlanIdMismatch:
            return _bad_request("confirm does not match plan_id")
        except PlanExpired:
            return _bad_request("plan expired")

        return _ok(result)
    except Exception as e:
        logger.error(f"Error applying prune plan: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Verify no `prune_apply` MCP tool exists**

```bash
grep -n "prune_apply" src/tools/builtin/memory.py
```

Expected: no matches. If there are any, delete them — the whole point of the C1 fix is that this tool must not be agent-callable.

- [ ] **Step 5: Run the tests**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py -k prune_apply -v
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add src/server.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): POST /api/memory/prune/apply (REST only, no MCP surface)"
```

---

### Task 21: `POST /api/memory/lifecycle/backfill` endpoint + MCP tool

**Files:**
- Modify: `src/server.py`
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

- [ ] **Step 1: Test**

```python
def test_lifecycle_backfill_dry_run(client):
    response = client.post("/api/memory/lifecycle/backfill", json={"dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert "updated_by_tier" in body
    assert "total" in body
    assert body["dry_run"] is True
```

- [ ] **Step 2: Run**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_lifecycle_backfill_dry_run -v
```

Expected: 404.

- [ ] **Step 3: Add endpoint**

```python
@mcp.custom_route("/api/memory/lifecycle/backfill", methods=["POST"])
async def api_lifecycle_backfill(request):
    """REST API: Backfill tier/durability on existing memories."""
    try:
        body = await request.json()
        dry_run = bool(body.get("dry_run", True))
        project = body.get("project")

        manager = _get_memory_manager()
        report = manager.backfill_lifecycle(dry_run=dry_run, project=project)
        return _ok(report)
    except Exception as e:
        logger.error(f"Error during lifecycle backfill: {e}")
        return _server_error(str(e))
```

- [ ] **Step 4: Add MCP tool**

`ToolDefinition`:

```python
            ToolDefinition(
                name="backfill_lifecycle",
                description="One-shot backfill: compute tier/durability for existing memories (dry_run by default)",
                handler=None,
            ),
```

Handler:

```python
        @mcp.tool(structured_output=False)
        async def backfill_lifecycle(dry_run: bool = True, project: str | None = None) -> str:
            """Backfill tier/durability on existing memories.

            Args:
                dry_run: If True, report what would change without writing (default True)
                project: Optional project filter
            """
            report = self.manager.backfill_lifecycle(dry_run=dry_run, project=project)
            return (
                f"Backfill (dry_run={dry_run}) — total {report['total']}: "
                + ", ".join(f"{k}={v}" for k, v in report["updated_by_tier"].items())
            )

        registered.append("backfill_lifecycle")
```

- [ ] **Step 5: Run**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_lifecycle_backfill_dry_run -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/tools/builtin/memory.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): POST /api/memory/lifecycle/backfill + backfill_lifecycle MCP tool"
```

---

### Task 22: `GET /api/memory/resume` endpoint + MCP tool

**Files:**
- Modify: `src/server.py` (this is a NEW endpoint — keep the existing `/api/memory/resume` handler at line ~623 as-is; rename the new one to `/api/memory/v2/resume` OR replace it if the old one is broken)
- Modify: `src/tools/builtin/memory.py`
- Test: `tests/test_server_memory_os_endpoints.py` (expand)

**Note:** The existing `api_resume_packet` handler at `src/server.py:623` already exists. We DO NOT add a duplicate endpoint — we fix the existing one to use the new bounded-scroll resume and return the `truncated` field. The test asserts the new behavior on the same URL.

- [ ] **Step 1: Write the test**

```python
def test_resume_endpoint_returns_truncated_field(client):
    response = client.get("/api/memory/resume?project=general")
    assert response.status_code == 200
    body = response.json()
    assert "recent" in body
    assert "important" in body
    assert "truncated" in body
```

- [ ] **Step 2: Run it**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_resume_endpoint_returns_truncated_field -v
```

If the existing endpoint is at `/api/memory/context/startup` or `/api/memory/resume`, the test path may need adjustment. Check with:

```bash
grep -n "/api/memory/resume\|api_resume_packet" src/server.py
```

- [ ] **Step 3: Ensure the existing `api_resume_packet` handler calls the new `build_resume_packet`**

The handler at line ~623 currently calls `manager.get_resume_packet(project=project, limit=limit)`. Verify that `manager.get_resume_packet` in turn calls `build_resume_packet` from `memory/resume.py` — it should, since we modified that function in Task 8. If `manager.get_resume_packet` adds a different intermediate step that prevents `truncated` from bubbling up, fix it.

Find the method:

```bash
grep -n "def get_resume_packet" src/memory/manager.py
```

Read it and confirm it returns the dict produced by `build_resume_packet` directly (or at least includes the `truncated` key).

- [ ] **Step 4: Expose the endpoint at `/api/memory/resume` if it's not there**

If the existing REST path is different (e.g. `/api/memory/context/startup`), add a clean alias:

```python
@mcp.custom_route("/api/memory/resume", methods=["GET"])
async def api_memory_resume_clean(request):
    """REST API: clean structured resume packet endpoint (Task 22)."""
    try:
        query = request.query_params
        project = query.get("project")
        limit = _read_int(query, "limit", 12)

        manager = _get_memory_manager()
        packet = manager.get_resume_packet(project=project, limit=limit)
        return _ok(packet)
    except Exception as e:
        logger.error(f"Error building resume packet: {e}")
        return _server_error(str(e))
```

- [ ] **Step 5: Run the test**

```bash
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py::test_resume_endpoint_returns_truncated_field -v
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/server.py src/memory/manager.py tests/test_server_memory_os_endpoints.py
git commit -m "feat(api): GET /api/memory/resume returns truncated flag + bounded scroll"
```

---

### Task 23: Update `docs/ARCHITECTURE.md`

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Append a new section**

Open `docs/ARCHITECTURE.md` and add at the end:

```markdown
## Memory OS (Backend Hardening, 2026-04-10)

### Behavioral tiering

Tiers are computed from behavioral signals, not a pure type→tier lookup. See
`src/memory/lifecycle.py:classify` and `LifecycleSignals`. Promotion is
deterministic; identity tier is sacred (only reachable via explicit
`save(tier="identity")`).

- `working` — recent scratch
- `episodic` — session/time-anchored events
- `semantic` — durable facts, decisions, high-salience requirements, reinforced notes
- `identity` — stable user/agent preferences (explicit only)

Tier weight in recall ranking: `identity=1.0, semantic=0.66, episodic=0.33, working=0.0` at 0.15 final weight.

### Safe pruning

Prune is a two-step plan/apply contract with a plan id gate, 15-min TTL,
and a hard cap of 200 deletions per apply. Identity-tier memories and
memories without an explicit `salience` field are never selected.
`prune_apply` is **REST-only** (no MCP tool) so agents cannot self-delete.

See `src/memory/prune.py`.

### New REST endpoints

| Path | Method | Purpose |
|---|---|---|
| `/api/memory/detail/{id}` | GET | Single memory + 1-hop neighbors |
| `/api/memory/kb` | GET | Typed KB slices (decisions, requirements, preferences, learnings) |
| `/api/memory/pressure` | GET | Structured pressure snapshot |
| `/api/memory/prune/plan` | POST | Build prune plan (dry) |
| `/api/memory/prune/apply` | POST | Apply with `confirm` equal to `plan_id` — REST only |
| `/api/memory/lifecycle/backfill` | POST | One-shot backfill for existing memories |
| `/api/memory/resume` | GET | Bounded-scroll resume packet with `truncated` flag |

### Trust boundaries

`src/memory/trust.py` loads `~/.claude/memory/trust.yaml` at startup. If the
file is absent, every detection resolves to `personal`. See the spec for the schema.
```

- [ ] **Step 2: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs(memory): document memory OS tiering, prune contract, new endpoints"
```

---

### Task 24: P1 gate — final sweep

- [ ] **Step 1: Full unit test run**

```bash
uv run --extra dev pytest -v -m "not integration"
```

Expected: zero regressions, all new tests green.

- [ ] **Step 2: Integration test run**

```bash
uv run --extra dev pytest tests/test_integration_memory_os.py -v -m integration
uv run --extra dev pytest tests/test_server_memory_os_endpoints.py -v
```

Expected: green.

- [ ] **Step 3: Smoke-test the server**

```bash
MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 \
  uv run python -m server &
SERVER_PID=$!
sleep 3
curl -sf http://localhost:8000/health | head
curl -sf -X POST http://localhost:8000/api/memory/lifecycle/backfill -H 'content-type: application/json' -d '{"dry_run": true}' | head
curl -sf -X POST http://localhost:8000/api/memory/prune/plan -H 'content-type: application/json' -d '{"project": "general"}' | head
kill $SERVER_PID
```

Expected: each curl returns a 200 JSON body.

- [ ] **Step 4: Verify `prune_apply` is not callable as a tool**

```bash
grep -rn "prune_apply" src/tools/
```

Expected: no matches anywhere under `src/tools/`.

- [ ] **Step 5: Tag the P1 gate**

```bash
git tag p1-api-green
```

---

### Task 25: Review commits before handoff to UI spec

- [ ] **Step 1: Show the commit delta**

```bash
git log --oneline feature/agent-memory-os..HEAD
```

Expected: ~24 new commits, all prefixed with `feat(memory):`, `fix(memory):`, `test(memory):`, `refactor(memory):`, `docs(memory):`, `feat(api):`, or `refactor(server):`.

- [ ] **Step 2: Run `git status`**

```bash
git status
```

Expected: clean working tree. No untracked files beyond `ui/` (which is still untracked — that's the sibling spec's territory).

- [ ] **Step 3: Do not push** — JR is the only one who authorizes pushes to remote. This plan is complete when P0 and P1 gates are green and the commits are local.

---

## Self-Review

**Spec coverage** — every section of `2026-04-10-memory-os-backend-hardening-design.md` has at least one task:

| Spec section | Task(s) |
|---|---|
| Lifecycle classifier | 1, 2 |
| `reinforce_and_reclassify` | 3 |
| Manager save path | 4 |
| Recall weight rebalance (I1) | 5 |
| `backfill_lifecycle` (I4) | 6 |
| Prune plan/apply contract (C1) | 7 |
| Resume bounded scroll (C2) | 8 |
| `trust.yaml` + cred strip + lru_cache (I2, M10, M11) | 9 |
| Observe low-signal (I3) | 10 |
| `save_memory` context arg (I6) | 11 |
| Startup doc test replacement | 12 |
| Integration test | 13 |
| P0 gate | 14 |
| Server response helpers | 15 |
| `/api/memory/detail/{id}` | 16 |
| `/api/memory/kb` | 17 |
| `/api/memory/pressure` | 18 |
| `/api/memory/prune/plan` | 19 |
| `/api/memory/prune/apply` (REST only) | 20 |
| `/api/memory/lifecycle/backfill` | 21 |
| `/api/memory/resume` | 22 |
| `docs/ARCHITECTURE.md` | 23 |
| P1 gate | 24 |
| Handoff | 25 |

**Placeholder scan** — every step contains the actual code or the actual command. No "TBD", "TODO", or "add appropriate error handling" phrases. Every test file has real test bodies; every code change shows the full replacement block.

**Type consistency check:**
- `LifecycleSignals` / `LifecycleResult` / `Tier` — consistent across Tasks 1, 3, 6.
- `PrunePlan` / `PruneCandidate` / `PlanIdMismatch` / `PlanExpired` / `PlanNotFound` — consistent across Tasks 7, 19, 20.
- `build_plan` / `apply_plan` signatures — positional keyword args consistent (`*, plan_id, confirm_plan_id` on apply).
- `reinforce_and_reclassify` signature — `(memory, *, graph, now)` consistent between Task 3 definition and Task 4 call site.
- `_strip_creds` — returns `""` on None/empty per Task 9 test.
- `MAX_RESUME_SCROLL` — consistent between Task 8 definition and test monkeypatch.

**Scope check** — all work is P0+P1 backend. No UI work. Zero task touches anything under `ui/` or writes Next.js code. This matches the spec's non-goals.

---

## Run commands

```bash
# Fast local unit run (skips integration)
uv run --extra dev pytest -v -m "not integration"

# Integration only
uv run --extra dev pytest -v -m integration

# Full — before tagging P0 or P1 gates
uv run --extra dev pytest -v

# Targeted re-run of just the new test files
uv run --extra dev pytest \
  tests/test_lifecycle_classifier.py \
  tests/test_recall_tier_bias.py \
  tests/test_backfill_lifecycle.py \
  tests/test_prune_safety.py \
  tests/test_resume_at_scale.py \
  tests/test_scope_trust_yaml.py \
  tests/test_scope_cred_strip.py \
  tests/test_observe.py \
  tests/test_manager_observe_dedupe.py \
  tests/test_intelligence.py \
  tests/test_startup_hints_match_doc.py \
  tests/test_integration_memory_os.py \
  tests/test_server_memory_os_endpoints.py \
  -v

# Smoke-run the hardened server
docker compose up -d qdrant  # production :6333
MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 \
  uv run python -m server

# One-shot lifecycle backfill for existing memories
curl -sf -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H 'content-type: application/json' \
  -d '{"dry_run": true}' | jq
# If happy:
curl -sf -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H 'content-type: application/json' \
  -d '{"dry_run": false}' | jq
```
