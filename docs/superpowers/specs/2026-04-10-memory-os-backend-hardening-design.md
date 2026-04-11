# Memory OS — Backend Hardening & API Expansion

| Field | Value |
|---|---|
| **Status** | Draft — awaiting user review |
| **Date** | 2026-04-10 |
| **Spec ID** | `2026-04-10-memory-os-backend-hardening` |
| **Branch** | `feature/agent-memory-os` |
| **Phase** | P0 (hardening) + P1 (API expansion) |
| **Touches** | `src/memory/*`, `src/server.py`, `src/tools/builtin/memory.py`, `tests/*` |
| **Migration** | One-shot `backfill_lifecycle` on existing memories; `trust.yaml` optional file |
| **Author** | Claude (brainstormed with JR) |
| **Pair spec** | `2026-04-10-memory-cockpit-ui-design.md` (to be written after this ships) |

---

## The Problem

The branch `feature/agent-memory-os` landed an ambitious backend — nine modules (`scope`, `observe`, `lifecycle`, `intelligence`, `continuity`, `pressure`, `prune`, `resume`, `startup`) that collectively promise an "agent memory OS" with tiers, promotion, continuity, and safe pruning. A full code review found that the architecture is sound and the module boundaries are respected, but the system has five load-bearing defects that make it unsafe, silently degrade at scale, or render key features as no-ops on real data:

1. The **prune tool can wipe most hand-saved notes in one call**, because the default plan targets `tier="working"` with `salience<=0.25`, every memory saved via the existing `save_memory` tool has no `salience` field (treated as `0.0`), and `apply=True` is exposed at the MCP surface with no confirmation step.
2. The **resume packet samples an arbitrary ~7%** of project memories — `store.scroll(limit=24)` returns points in Qdrant internal point-id order, not by date or importance, so "recent/important/unresolved/next_steps" are computed against a fixed-size random slice. On a 500-memory project the resume packet is effectively noise.
3. The **tier bonus in recall scoring is a rounding error** — `tier_bonus * 0.10` caps identity-tier contribution at 0.015, less than one month of recency drift. The test passes only because of pre-existing type-importance weights, so the "tier system" is a no-op on ranking.
4. **Existing on-disk memories have no tier field**. `summarize_lifecycle` only runs on new saves, so every memory from before this branch defaults to `working` and loses any bias the tier system would give it. On deploy, weeks of memories are silently demoted.
5. **`scope.py` hardcodes personal client names** (`["yum", "audacy"]`) inside a module that is supposed to be a generic agent-memory fabric shared by Claude and Codex. It also leaks `repo_remote` URLs (possibly with credentials) into every memory payload.

Secondary defects: `observe.py` rejects legitimate content via substring-match on `"trying"`/`"maybe"`/`"exploring"`; `scope.py` shells out to `git` three times per `detect()` call with no cache; the new test suite mocks the store or the graph in every test and has zero end-to-end integration coverage; the `save_memory` MCP tool lost its `context` enrichment during refactor. None of these alone are critical, but collectively they make it impossible to trust the backend on real data.

The backend also does not expose enough structured JSON to drive a real UI cockpit. `/api/memory/context/startup` returns pre-formatted strings; there is no endpoint for memory detail with neighbors, no typed KB slices, no structured pressure snapshot, no two-step prune contract, and no way to trigger a lifecycle backfill. The UI scaffold in `ui/` has worked around this by rendering `<pre>{string}</pre>` blocks — which is why the KB panel looks like "metadata chips in a trenchcoat".

This spec fixes the five defects, closes the secondary gaps, and introduces the seven new REST endpoints (all mirrored as MCP tools where safe) needed to drive the Brain + KB cockpit spec that follows.

---

## Goals

1. **Make the tier system real**: behavioral classification (type + salience + age + reinforcement + contradictions), meaningful recall bias, explicit one-shot backfill for existing memories. Promotion is observable and debuggable.
2. **Make prune safe**: two-step plan/apply contract with a plan id gate, identity-tier exemption, hard deletion cap, and prune-apply removed from the MCP tool surface entirely. An agent cannot delete; only the UI (or a human calling REST directly) can.
3. **Make the resume packet truthful at scale**: bounded scroll (≤2000), Python-side sort by date + importance, deterministic buckets. A 500-memory project's resume packet should be identical run-to-run (barring new memories) and actually surface the important items.
4. **Remove personal data and credential leaks from `scope.py`**: externalize trust-boundary rules to an optional `trust.yaml`, strip credentials from persisted `repo_remote`, cache `git` shell-outs per cwd.
5. **Expose a structured API surface sufficient for the UI cockpit**: seven new REST endpoints (detail, kb, pressure, prune/plan, prune/apply, lifecycle/backfill, resume), all returning typed JSON, not pre-formatted strings.
6. **Prove it with real tests**: at least one true integration test that exercises observe → save → tier-computed → reinforce → promote → recall → resume → prune-plan end-to-end against a tmp Qdrant, plus targeted unit tests for every fix above.

## Non-goals

- **No UI work.** That is the sibling spec. This spec only produces REST responses that the UI can later consume.
- **No rewrite of the memory model.** Tiers stay at four. Semantic search stays at 384-dim. Graph relations stay the same. We are making what exists work, not rebuilding it.
- **No new agent startup semantics.** The existing `startup.py` flow stays. We only add a cleaner `/api/memory/resume` endpoint alongside it and fix the sampling bug inside `resume.build_resume_packet`.
- **No removal of existing endpoints.** Every current endpoint continues to exist and behave the same (or better) after this spec.
- **No batch nightly jobs.** Promotion is on-save in the dedupe path, not a cron.
- **No new dependencies.** Everything ships on the existing stack (FastAPI, Qdrant, networkx, pydantic, pyyaml).

---

## Architecture

```mermaid
graph TD
    subgraph Agent["Agent (Claude / Codex)"]
        MCP[MCP Tools]
    end

    subgraph UI["Cockpit (Next.js, future spec)"]
        REST[REST Client]
    end

    subgraph Server["src/server.py (FastAPI)"]
        E_detail["/api/memory/detail/:id"]
        E_kb["/api/memory/kb"]
        E_pressure["/api/memory/pressure"]
        E_plan["/api/memory/prune/plan"]
        E_apply["/api/memory/prune/apply"]
        E_backfill["/api/memory/lifecycle/backfill"]
        E_resume["/api/memory/resume"]
    end

    subgraph Core["src/memory (hardened)"]
        Manager[manager.MemoryManager]
        Scope[scope.ScopeDetector<br/>+ trust.yaml]
        Lifecycle[lifecycle.Classifier<br/>behavioral tiering]
        Intelligence[intelligence.Promoter<br/>reinforcement loop]
        Resume[resume.build_packet<br/>bounded scroll]
        Prune[prune.plan/apply<br/>plan-id gated]
        Pressure[pressure.snapshot]
        Observe[observe.LowSignal<br/>word-boundary]
    end

    subgraph Store["Persistence"]
        Qdrant[(Qdrant<br/>384-dim)]
        YAML[(~/.claude/memory/*.yaml)]
        Graph[(_graph.json)]
    end

    MCP -->|plan, detail, kb, ...| Server
    MCP -.->|prune_apply: BLOCKED| E_apply
    REST --> Server
    Server --> Core
    Core --> Store

    Manager --> Lifecycle
    Manager --> Intelligence
    Manager --> Scope
    Manager --> Observe
    Resume --> Manager
    Prune --> Manager
    Pressure --> Manager

    style E_apply stroke:#ff6b6b,stroke-width:3px
    style MCP stroke:#f5b041,stroke-width:2px
```

The red border on `/api/memory/prune/apply` indicates it is deliberately unreachable from the MCP tool layer. Agents can call `prune_plan` (mirrored as an MCP tool) but cannot apply a plan — only the REST endpoint can execute the delete, and only when given a confirmation matching the plan id. The orange border on MCP highlights that the agent surface is strictly smaller than the REST surface.

---

## Components

### 1. `src/memory/lifecycle.py` — behavioral classifier

**Current**: pure `type → tier` lookup. One function, ~70 lines.

**New**: classifier computes tier from a dataclass of signals. Same four tier names. Promotion rules documented in code.

```python
from dataclasses import dataclass
from typing import Literal

Tier = Literal["working", "episodic", "semantic", "identity"]

@dataclass(frozen=True)
class LifecycleSignals:
    memory_type: str              # "note", "decision", "preference", ...
    salience: float               # 0.0–1.0, explicit or type-default
    age_days: int                 # (now - created_at).days
    reinforcement_count: int      # times this memory has been re-observed
    contradicts_count: int        # contradicts-edges in the graph
    explicit_tier: Tier | None    # set via save(tier=...) — overrides everything except identity sanctity

@dataclass(frozen=True)
class LifecycleResult:
    tier: Tier
    durability: float             # 0.0–1.0, for UI gradient
    reason: str                   # human-readable explanation, for debugging

def classify(signals: LifecycleSignals) -> LifecycleResult: ...
```

**Rules (in priority order)**:
1. If `explicit_tier == "identity"` → `identity` (sacred, only set by explicit save).
2. If `contradicts_count >= 2` → demote one tier from the type default. Max demotion is `working`.
3. If `reinforcement_count >= 5 AND age_days >= 7 AND type in {"note","fact","learning"}` → promote to `semantic`.
4. If `type in {"decision","requirement"}` AND `salience >= 0.6` → `semantic`.
5. If `type == "preference"` AND not explicitly demoted → `semantic` (identity only when explicit).
6. If `type == "session"` → `episodic`.
7. Otherwise → `working`.

`durability = clamp(0, 1, 0.25*tier_weight + 0.25*salience + 0.25*(1-contradicts_penalty) + 0.25*reinforcement_weight)` where `tier_weight ∈ {0.0, 0.33, 0.66, 1.0}`.

### 2. `src/memory/intelligence.py` — promotion loop

**Current**: `apply_memory_promotion` mutates its input list in place with no clear contract.

**New**: takes a single memory dict + graph handle, returns a new dict with updated tier/durability/reinforcement. No mutation of inputs. Called from the dedupe path in `manager.save`.

```python
def reinforce_and_reclassify(
    memory: dict,
    graph: KnowledgeGraph,
    now: datetime,
) -> dict:
    """Return a new dict with reinforcement_count += 1 and tier recomputed."""
```

**Contract**: pure function, deterministic given inputs, never writes to store/graph directly — caller persists.

### 3. `src/memory/manager.py` — save path changes

**Current**: `save` → dedupe check → if dup, return existing id; if new, write to store + graph.

**New**: `save` → dedupe check → if dup, `reinforce_and_reclassify` + persist the updated payload (new tier, new durability, incremented reinforcement); if new, compute `LifecycleSignals(reinforcement_count=0, age_days=0, contradicts_count=0)` and classify before write. All memories land with tier + durability set.

**Recall path (fix I1)**: rebalance weights so tier is meaningful.

```python
# Before
final = 0.45*vector + 0.20*importance + 0.10*recency + 0.15*graph_proximity + 0.10*tier_bonus
# where tier_bonus maxed at 0.15 → effective max contribution 0.015

# After
tier_norm = {"identity": 1.0, "semantic": 0.66, "episodic": 0.33, "working": 0.0}[tier]
final = 0.40*vector + 0.20*importance + 0.10*recency + 0.15*graph_proximity + 0.15*tier_norm
# effective max contribution from tier = 0.15
```

**New method**: `manager.backfill_lifecycle(dry_run: bool = True, project: str | None = None) -> BackfillReport`. Scrolls Qdrant in 500-point batches, computes `LifecycleSignals` from each existing payload (age = now - created_at; reinforcement = payload.get("reinforcement_count", 0); contradicts via graph), writes back `tier` + `durability` + `reinforcement_count` + `lifecycle_reason` to both Qdrant and the YAML file. Returns counts by tier and any errors.

### 4. `src/memory/resume.py` — bounded scroll (fix C2)

**Current**: `store.scroll(limit=24)` — arbitrary 7% slice.

**New**:

```python
MAX_RESUME_SCROLL = 2000  # configurable via env MEMENTO_RESUME_MAX_POINTS

def build_resume_packet(manager, project: str, *, now: datetime) -> ResumePacket:
    all_points = manager.store.scroll(
        filters={"project": project},
        limit=MAX_RESUME_SCROLL,
    )
    # sort in Python (Qdrant point-id order is meaningless here)
    all_points.sort(key=lambda p: (p["date"], p.get("importance", 0.0)), reverse=True)

    recent = all_points[:20]
    important = sorted(all_points, key=lambda p: p.get("importance", 0), reverse=True)[:20]
    unresolved = [p for p in all_points if manager.graph.has_contradicts(p["id"])][:20]
    return ResumePacket(
        recent=recent,
        important=important,
        unresolved=unresolved,
        pressure=pressure.snapshot(manager, project),
        next_steps=continuity.extract_next_steps(all_points),
    )
```

If the project has > 2000 memories, log a warning and return the most recent 2000 by date. Document in the response that `truncated: bool` is set.

### 5. `src/memory/prune.py` — plan/apply with plan id (fix C1)

**Current**: `build_plan` returns a list, `apply_plan(dry_run=False)` just deletes. `apply` exposed as MCP tool.

**New**:

```python
from uuid import uuid4
from datetime import datetime, timedelta

PLAN_TTL = timedelta(minutes=15)
MAX_DELETIONS_PER_APPLY = 200
_PLAN_STORE: dict[str, PrunePlan] = {}  # in-memory, per-process

@dataclass(frozen=True)
class PruneCandidate:
    memory_id: str
    tier: str
    reason: str
    age_days: int
    salience: float

@dataclass(frozen=True)
class PrunePlan:
    plan_id: str
    project: str
    generated_at: datetime
    expires_at: datetime
    candidates: tuple[PruneCandidate, ...]
    summary: str

def build_plan(manager, project: str, *, limit: int = 200) -> PrunePlan:
    """
    Select candidates where:
    - tier != "identity"               # identity is sacred
    - "salience" is explicit in payload # unknown-salience is NEVER selected
    - salience <= 0.25
    - reinforcement_count == 0
    - age_days >= 7
    - NOT connected via any edge to an identity-tier memory (protect neighborhoods)
    Hard cap at `limit`, max 200.
    """

def apply_plan(manager, plan_id: str, confirm_plan_id: str) -> PruneApplyResult:
    """
    Raises PlanNotFound / PlanExpired / PlanIdMismatch.
    Deletes up to MAX_DELETIONS_PER_APPLY memories.
    Removes from Qdrant, graph, and YAML atomically (best-effort: log + continue on YAML error).
    """
```

**Key safeties**:
- **Identity-tier never in a plan** — enforced in `build_plan`.
- **Unknown-salience never in a plan** — `if "salience" not in payload: skip` (this is the fix for the "all hand-saved notes get selected" bug).
- **Neighborhood protection** — a low-salience memory adjacent to an identity-tier memory is skipped (don't delete context that supports an identity memory).
- **Plan id gate** — `apply_plan` requires `confirm_plan_id == plan_id`; any mismatch raises.
- **TTL** — plans older than 15 min are evicted from `_PLAN_STORE`.
- **Hard cap** — cannot delete more than 200 in one apply, even if the plan has more candidates (rest are skipped with a log line).

### 6. `src/memory/scope.py` — trust.yaml + caching + cred strip

**I2 fix** — load trust rules from disk:

```python
# ~/.claude/memory/trust.yaml (optional, default = personal)
boundaries:
  - name: personal
    match:
      default: true
  - name: work-client-a
    match:
      remote: "gitlab.client-a.internal"
  - name: work-client-b
    match:
      name_contains: "client-b-"
```

If the file is missing, default every detection to `personal`. **No hardcoded client names anywhere in source.**

**M10 fix** — cache:

```python
from functools import lru_cache

@lru_cache(maxsize=32)
def _git_info(cwd: str) -> tuple[str | None, str | None, str | None]:
    """Shell out to git; cache per-cwd. Invalidate via ScopeDetector.invalidate(cwd)."""
```

**M11 fix** — strip credentials:

```python
def _strip_creds(url: str | None) -> str | None:
    if not url:
        return None
    # Strip https://user:token@host/...  or  https://user@host/...
    return re.sub(r"(https?://)[^@/]+@", r"\1", url)
```

Applied in `scope.to_metadata()` before the remote URL is persisted.

### 7. `src/memory/observe.py` — word-boundary low-signal (fix I3)

```python
# Before (substring match — false positives on "trying", "exploring", etc.)
LOW_SIGNAL_TOKENS = ["maybe", "possibly", "trying", "exploring", ...]
def _is_low_signal(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in LOW_SIGNAL_TOKENS)

# After (word-boundary + phrase-level)
import re

LOW_SIGNAL_WORD_RE = re.compile(r"\b(maybe|possibly|probably|might)\b", re.IGNORECASE)
LOW_SIGNAL_PHRASES = (
    "just exploring",
    "not sure",
    "maybe later",
    "i think",
    "kinda",
)

def _is_low_signal(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in LOW_SIGNAL_PHRASES):
        return True
    # Only reject if the ENTIRE text looks uncertain — not just "User is trying to migrate"
    tokens = re.findall(r"\b\w+\b", lowered)
    hedge_count = sum(1 for t in tokens if LOW_SIGNAL_WORD_RE.fullmatch(t))
    return hedge_count >= 2 and len(tokens) < 20
```

Logic: a memory is only low-signal if it contains a known hedging phrase, OR if it is short AND contains multiple hedge words. A single "maybe" in a 40-word decision does not trigger rejection.

### 8. `src/server.py` — new REST endpoints

All new endpoints return typed JSON (Pydantic response models), all accept optional `project` query param (falls back to scope detector), all log structured error contexts.

| Path | Method | Request | Response |
|---|---|---|---|
| `/api/memory/detail/{memory_id}` | GET | — | `MemoryDetailResponse { memory, neighbors[], scope }` |
| `/api/memory/kb` | GET | `?project=...` | `KbResponse { decisions[], requirements[], preferences[], learnings[] }` (each is a list of summarized memories: id, summary, tier, updated_at) |
| `/api/memory/pressure` | GET | `?project=...` | `PressureResponse { load_score, capacity, flagged: { stale_working_count, low_value_count, contradiction_count }, candidates[] }` |
| `/api/memory/prune/plan` | POST | `{project, limit?}` | `PrunePlanResponse { plan_id, candidates[], summary, expires_at }` |
| `/api/memory/prune/apply` | POST | `{plan_id, confirm}` | `PruneApplyResponse { deleted[], skipped[] }` or 400 on mismatch |
| `/api/memory/lifecycle/backfill` | POST | `{dry_run, project?}` | `BackfillResponse { updated_by_tier, skipped, errors }` |
| `/api/memory/resume` | GET | `?project=...` | `ResumeResponse { recent[], important[], unresolved[], pressure, next_steps[], truncated }` |

### 9. `src/tools/builtin/memory.py` — MCP tool mirroring

All new endpoints mirrored as MCP tools **except** `/api/memory/prune/apply`. The apply is REST-only. Rationale: MCP tools are callable by agents in a loop; REST endpoints are callable by a human in a UI (or a human shelling `curl`). This asymmetry is the C1 fix.

MCP tool additions: `memory_detail`, `memory_kb`, `memory_pressure`, `prune_plan`, `backfill_lifecycle`, `resume_packet`.

Also restore the `context` arg enrichment in the `save_memory` MCP tool — it was dropped during the branch's refactor (fix I6).

---

## Data model changes

Every memory payload in Qdrant gains three optional fields:

```python
{
    # ... existing fields (id, content, type, project, date, importance, ...)
    "tier": "working" | "episodic" | "semantic" | "identity",
    "durability": 0.0,          # float 0-1
    "reinforcement_count": 0,   # int, incremented on each dedupe hit
    "lifecycle_reason": "str",  # human-readable classifier explanation
    "scope": {                  # written once at save
        "project": "str",
        "agent": "str",
        "repo_name": "str | None",
        "repo_remote": "str | None (credentials stripped)",
        "trust_boundary": "str",  # from trust.yaml
        "branch": "str | None",
        "workspace_root": "str | None",
    }
}
```

All fields are **additive and optional** — older memories without them still work, and `backfill_lifecycle` populates them on-demand.

**YAML files** gain the same fields in the same positions. YAML writes happen after Qdrant writes; on YAML failure, we log and continue (Qdrant is source of truth for ranking; YAML is for human auditing).

---

## Tests (written before implementation)

### `tests/test_lifecycle_classifier.py` (new)

```python
def test_explicit_identity_is_sacred():
    signals = LifecycleSignals(
        memory_type="note", salience=0.0, age_days=0,
        reinforcement_count=0, contradicts_count=99,
        explicit_tier="identity",
    )
    assert classify(signals).tier == "identity"

def test_contradictions_demote():
    signals = LifecycleSignals(
        memory_type="decision", salience=0.9, age_days=30,
        reinforcement_count=3, contradicts_count=3,
        explicit_tier=None,
    )
    # decision+high-salience would normally be semantic; contradicts demote to episodic
    assert classify(signals).tier == "episodic"

def test_reinforcement_promotes_notes():
    signals = LifecycleSignals(
        memory_type="note", salience=0.3, age_days=10,
        reinforcement_count=6, contradicts_count=0,
        explicit_tier=None,
    )
    assert classify(signals).tier == "semantic"

def test_short_lived_note_stays_working():
    signals = LifecycleSignals(
        memory_type="note", salience=0.3, age_days=1,
        reinforcement_count=1, contradicts_count=0,
        explicit_tier=None,
    )
    assert classify(signals).tier == "working"

def test_durability_monotonic_with_reinforcement():
    base = LifecycleSignals("note", 0.3, 10, 0, 0, None)
    more = LifecycleSignals("note", 0.3, 10, 5, 0, None)
    assert classify(more).durability > classify(base).durability
```

### `tests/test_recall_tier_bias.py` (new — fix I1)

```python
def test_tier_actually_changes_ranking(real_qdrant):
    """Two memories with identical vector score and type, different tiers.
    The higher-tier memory must rank first."""
    mgr = MemoryManager(...)
    mgr.save(content="alpha config", type="fact", tier="working")
    mgr.save(content="alpha config", type="fact", tier="semantic")
    results = mgr.recall("alpha config", limit=2)
    assert results[0]["tier"] == "semantic"
    # Before fix: both are "fact" → identical importance → rounding decides → flaky
    # After fix: tier_norm gives semantic a 0.10 advantage → deterministic
```

### `tests/test_backfill_lifecycle.py` (new — fix I4)

```python
def test_backfill_populates_tier_on_legacy_memories(real_qdrant, legacy_memory_fixture):
    """Seed 5 memories with no tier field (legacy format). After backfill, all have tier + durability."""
    mgr = MemoryManager(...)
    seed_legacy_memories(mgr, count=5)  # writes raw Qdrant points with no tier
    report = mgr.backfill_lifecycle(dry_run=False)
    assert report.updated_by_tier["working"] + report.updated_by_tier["semantic"] == 5
    all_points = mgr.store.scroll(limit=10)
    assert all("tier" in p for p in all_points)
    assert all("durability" in p for p in all_points)

def test_backfill_dry_run_no_writes(real_qdrant):
    mgr = MemoryManager(...)
    seed_legacy_memories(mgr, count=3)
    report = mgr.backfill_lifecycle(dry_run=True)
    assert report.updated_by_tier  # counts populated
    all_points = mgr.store.scroll(limit=10)
    assert all("tier" not in p for p in all_points)  # no writes happened
```

### `tests/test_prune_safety.py` (new — fix C1)

```python
def test_identity_tier_never_in_plan(real_qdrant):
    mgr = MemoryManager(...)
    mgr.save(content="JR prefers Go for backends", type="preference", tier="identity")
    mgr.save(content="random note", type="note", salience=0.1)  # prunable
    plan = build_plan(mgr, project="test")
    ids = {c.memory_id for c in plan.candidates}
    assert mgr.find(content="JR prefers Go")[0]["id"] not in ids

def test_unknown_salience_never_in_plan(real_qdrant):
    """This is THE bug that would wipe JR's notes. Memories without an explicit
    salience field must not be selected for deletion."""
    mgr = MemoryManager(...)
    mgr.save(content="some note", type="note")  # no salience kwarg
    plan = build_plan(mgr, project="test")
    assert len(plan.candidates) == 0

def test_apply_without_plan_id_rejects():
    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id="abc", confirm_plan_id="wrong")

def test_apply_with_expired_plan_rejects(monkeypatch):
    plan = build_plan(mgr, project="test")
    monkeypatch.setattr("src.memory.prune.datetime", FakeDatetime(now=plan.expires_at + timedelta(seconds=1)))
    with pytest.raises(PlanExpired):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)

def test_apply_respects_hard_cap():
    """Even if the plan has 500 candidates, apply deletes at most 200."""
    plan = make_plan_with_candidates(500)
    result = apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id=plan.plan_id)
    assert len(result.deleted) == 200
    assert len(result.skipped) == 300

def test_neighborhood_protection():
    """A low-salience memory adjacent to an identity memory is NOT prunable."""
    id_mem = mgr.save(content="JR prefers vim", type="preference", tier="identity")
    note = mgr.save(content="keybindings note", type="note", salience=0.1)
    mgr.graph.add_edge(id_mem, note, relation="related_to")
    plan = build_plan(mgr, project="test")
    assert note not in {c.memory_id for c in plan.candidates}
```

### `tests/test_resume_at_scale.py` (new — fix C2)

```python
def test_resume_sorts_by_date_not_point_id(real_qdrant):
    """Seed 100 memories in shuffled date order. Resume packet must return
    the 20 most RECENT by date, not by Qdrant internal ordering."""
    mgr = MemoryManager(...)
    import random
    dates = [f"2026-0{i%4+1}-{(i%28)+1:02d}" for i in range(100)]
    random.shuffle(dates)
    for i, date in enumerate(dates):
        mgr.save(content=f"memory {i}", type="note", date=date)
    packet = build_resume_packet(mgr, project="test", now=datetime(2026, 4, 10))
    # Top recent must be sorted descending by date
    assert packet.recent[0]["date"] >= packet.recent[-1]["date"]
    # Must cover the actual latest dates, not arbitrary point-ids
    latest_date = max(dates)
    assert any(r["date"] == latest_date for r in packet.recent)

def test_resume_truncated_flag_on_overflow(real_qdrant, monkeypatch):
    monkeypatch.setattr("src.memory.resume.MAX_RESUME_SCROLL", 50)
    for i in range(100):
        mgr.save(content=f"m{i}", type="note")
    packet = build_resume_packet(mgr, project="test", now=datetime.now())
    assert packet.truncated is True
```

### `tests/test_scope_trust_yaml.py` (new — fix I2)

```python
def test_no_hardcoded_client_names_in_source():
    """Regression test: grep the source for the hardcoded names to ensure they
    never come back."""
    import pathlib
    src = pathlib.Path("src/memory/scope.py").read_text()
    assert "yum" not in src.lower()
    assert "audacy" not in src.lower()

def test_trust_yaml_missing_defaults_to_personal(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    detector = ScopeDetector()
    scope = detector.detect(cwd="/tmp/anywhere")
    assert scope.trust_boundary == "personal"

def test_trust_yaml_matches_by_remote(tmp_path, monkeypatch):
    (tmp_path / "trust.yaml").write_text("""
boundaries:
  - name: acme
    match:
      remote_contains: "gitlab.acme.internal"
""")
    monkeypatch.setenv("MEMENTO_MEMORY_DIR", str(tmp_path))
    detector = ScopeDetector()
    scope = detector.detect(cwd="/tmp/acme-repo", override_remote="https://gitlab.acme.internal/foo.git")
    assert scope.trust_boundary == "acme"
```

### `tests/test_observe_low_signal.py` (expand existing — fix I3)

```python
def test_trying_to_is_not_low_signal():
    """'User is trying to migrate from Postgres to Yugabyte' must not be rejected."""
    assert _is_low_signal("User is trying to migrate from Postgres to Yugabyte") is False

def test_exploring_rust_is_not_low_signal():
    assert _is_low_signal("Exploring Rust for the unikernel rewrite") is False

def test_just_exploring_phrase_is_low_signal():
    assert _is_low_signal("Just exploring, nothing concrete yet") is True

def test_multiple_hedges_short_text_is_low_signal():
    assert _is_low_signal("maybe probably") is True
```

### `tests/test_scope_cred_strip.py` (new — fix M11)

```python
def test_strip_creds_from_https_remote():
    assert _strip_creds("https://user:token@github.com/foo/bar.git") == "https://github.com/foo/bar.git"

def test_strip_creds_leaves_plain_urls_alone():
    assert _strip_creds("https://github.com/foo/bar.git") == "https://github.com/foo/bar.git"

def test_strip_creds_handles_ssh():
    assert _strip_creds("git@github.com:foo/bar.git") == "git@github.com:foo/bar.git"  # no change

def test_persisted_scope_has_no_creds(real_qdrant, monkeypatch):
    """End-to-end: save a memory in a repo with credentials in the remote URL,
    assert the persisted payload contains no credentials."""
    monkeypatch.setattr("src.memory.scope._git_remote",
                        lambda _: "https://u:t@git.example.com/x.git")
    mgr = MemoryManager(...)
    mid = mgr.save(content="test", type="note")
    stored = mgr.get(mid)
    assert "t@" not in str(stored.get("scope", {}).get("repo_remote", ""))
```

### `tests/test_integration_memory_os.py` (new — the one real end-to-end test)

```python
def test_full_lifecycle_observe_to_resume_to_prune(real_qdrant, tmp_memory_dir):
    """
    The only test that exercises the whole system in sequence.
    Uses a real tmp Qdrant + real tmp YAML dir. No mocks.
    """
    mgr = MemoryManager(qdrant_url="http://localhost:6334", memory_dir=tmp_memory_dir)

    # 1. observe a note, should land as "working"
    obs = mgr.observe("User prefers Go over Rust for backends", source="test")
    assert obs.saved
    mem = mgr.get(obs.memory_id)
    assert mem["tier"] == "working"

    # 2. reinforce it 6 times with age > 7 days (simulate via monkeypatch of created_at)
    for _ in range(6):
        obs2 = mgr.observe("User prefers Go over Rust for backends", source="test")
        assert obs2.memory_id == obs.memory_id  # dedupe hit
    # Simulate age by rewriting the payload's created_at
    mgr.store.update_payload(obs.memory_id, {"created_at": (datetime.now() - timedelta(days=8)).isoformat()})
    # Trigger a no-op observe to re-run reinforce_and_reclassify
    mgr.observe("User prefers Go over Rust for backends", source="test")
    mem = mgr.get(obs.memory_id)
    assert mem["tier"] == "semantic"  # auto-promoted
    assert mem["reinforcement_count"] >= 6

    # 3. recall must return this memory before a lower-tier twin
    mgr.observe("User prefers Go over Rust for backends (twin)", source="test")
    results = mgr.recall("Go Rust backends", limit=5)
    assert results[0]["id"] == obs.memory_id

    # 4. resume packet must include it in `important`
    packet = build_resume_packet(mgr, project="test", now=datetime.now())
    important_ids = [m["id"] for m in packet.important]
    assert obs.memory_id in important_ids

    # 5. prune plan must NOT include it (semantic tier, salience populated, reinforced)
    plan = build_plan(mgr, project="test")
    plan_ids = {c.memory_id for c in plan.candidates}
    assert obs.memory_id not in plan_ids

    # 6. prune apply with wrong plan_id rejects
    with pytest.raises(PlanIdMismatch):
        apply_plan(mgr, plan_id=plan.plan_id, confirm_plan_id="wrong")
```

### Tests to delete or rewrite

- `tests/test_agent_startup_doc_smoke.py` — delete, replace with `tests/test_startup_hints_match_doc.py` that renders the live hints and diffs them against the parsed doc.
- `tests/test_manager_observe_dedupe.py` — rewrite to not mock `_find_duplicate_memory_id`. Use real Qdrant, assert the dedupe path actually returns the existing id and increments `reinforcement_count`.

### Coverage target

All new modules: **≥85% line coverage** with the integration test contributing the cross-module flow. Existing modules: no regression from current baseline.

---

## Before / after concrete examples

### Prune plan on JR's memory directory (the bug)

**Before this spec**: `prune_plan(project="memento-mcp")` returns every hand-saved note as a candidate, because none of them have a `salience` field.

```json
{
  "candidates": [
    {"memory_id": "m_0001", "reason": "tier=working, salience=0.0"},
    {"memory_id": "m_0002", "reason": "tier=working, salience=0.0"},
    ... 147 more
  ]
}
```

If `prune_apply(..., apply=True)` is called by any agent in a loop, **147 hand-saved notes are deleted**.

**After this spec**: same call returns zero candidates because unknown-salience is excluded.

```json
{
  "plan_id": "b3a9...",
  "candidates": [],
  "summary": "0 candidates: no memories with explicit salience <= 0.25 and age >= 7 days",
  "expires_at": "2026-04-10T14:23:11Z"
}
```

And even if candidates existed, there is no `prune_apply` MCP tool for the agent to call. The REST endpoint exists, but only the UI (or a human with `curl`) can reach it.

### Resume packet on a 500-memory project (the bug)

**Before**: `build_resume_packet` calls `store.scroll(limit=24)` → returns 24 memories in Qdrant internal point-id order, which is effectively random. Top "recent" is a random memory from 2025.

**After**: `store.scroll(limit=2000)` → Python-side sort by `(date desc, importance desc)` → top 20 are genuinely the 20 most-recent memories. If the project has > 2000 memories, `truncated: true` is set in the response and the UI can show a warning.

### Recall ranking with tier bias (the bug)

**Before** (identical vector scores for "alpha config"):
```
m_a  type=fact  tier=working   final=0.8210
m_b  type=fact  tier=semantic  final=0.8225  (delta = 0.0015)
```
Tier contributes 0.0015 — less than float rounding noise on a warm cache. Effectively random ordering.

**After**:
```
m_a  type=fact  tier=working   final=0.8210
m_b  type=fact  tier=semantic  final=0.9200  (delta = 0.099)
```
Tier bias is deterministic and visible.

---

## File tree

```
docs/
  superpowers/
    specs/
      2026-04-10-memory-os-backend-hardening-design.md   ← THIS FILE, NEW

src/
  memory/
    lifecycle.py             ← REWRITE (behavioral classifier)
    intelligence.py          ← REWRITE (reinforce_and_reclassify)
    manager.py               ← MODIFY (save path, recall weights, backfill_lifecycle)
    resume.py                ← MODIFY (bounded scroll, Python sort)
    prune.py                 ← REWRITE (plan/apply, plan id, safety rules)
    scope.py                 ← MODIFY (trust.yaml loader, lru_cache, _strip_creds)
    observe.py               ← MODIFY (word-boundary + phrase low-signal)
    trust.py                 ← NEW (trust.yaml loader + schema)
  server.py                  ← MODIFY (7 new endpoints, pydantic response models)
  tools/
    builtin/
      memory.py              ← MODIFY (6 new MCP tools; prune_apply deliberately NOT added; restore context enrichment)

tests/
  test_lifecycle_classifier.py         ← NEW
  test_recall_tier_bias.py             ← NEW (fix I1)
  test_backfill_lifecycle.py           ← NEW (fix I4)
  test_prune_safety.py                 ← NEW (fix C1)
  test_resume_at_scale.py              ← NEW (fix C2)
  test_scope_trust_yaml.py             ← NEW (fix I2)
  test_scope_cred_strip.py             ← NEW (fix M11)
  test_observe_low_signal.py           ← EXPAND (fix I3)
  test_startup_hints_match_doc.py      ← NEW (replaces test_agent_startup_doc_smoke.py)
  test_manager_observe_dedupe.py       ← REWRITE (no mocks)
  test_integration_memory_os.py        ← NEW (end-to-end, real qdrant)
  test_agent_startup_doc_smoke.py      ← DELETE

~/.claude/memory/
  trust.yaml                           ← NEW (optional, user-editable)
```

---

## Implementation checklist (ordered, gated by green tests)

### P0 — Hardening

- [ ] **0.1** Write all new unit tests first (RED). Run them — confirm they fail with current code.
- [ ] **0.2** Rewrite `src/memory/lifecycle.py` with `LifecycleSignals` / `LifecycleResult` dataclasses and the classifier. Green for `test_lifecycle_classifier.py`.
- [ ] **0.3** Rewrite `src/memory/intelligence.py` with `reinforce_and_reclassify` as a pure function.
- [ ] **0.4** Modify `src/memory/manager.py` save path to compute `LifecycleSignals` on new saves, call `reinforce_and_reclassify` on dedupe hits, and persist tier/durability/reinforcement_count to Qdrant payload + YAML.
- [ ] **0.5** Fix recall weights in `manager.py`. Green for `test_recall_tier_bias.py`.
- [ ] **0.6** Add `manager.backfill_lifecycle(dry_run, project)`. Green for `test_backfill_lifecycle.py`.
- [ ] **0.7** Rewrite `src/memory/prune.py` with plan/apply, `_PLAN_STORE`, TTL, hard cap, identity exemption, unknown-salience exemption, neighborhood protection. Green for `test_prune_safety.py`.
- [ ] **0.8** Fix `src/memory/resume.py` — bounded scroll, Python sort, `truncated` flag. Green for `test_resume_at_scale.py`.
- [ ] **0.9** Add `src/memory/trust.py` (yaml loader, schema validation, default=personal). Modify `scope.py` to use it; delete all hardcoded client names. Add `_git_info` `lru_cache`. Add `_strip_creds`. Green for `test_scope_trust_yaml.py` and `test_scope_cred_strip.py`.
- [ ] **0.10** Fix `observe._is_low_signal`. Green for `test_observe_low_signal.py`.
- [ ] **0.11** Restore `context` enrichment in `save_memory` MCP tool.
- [ ] **0.12** Delete `test_agent_startup_doc_smoke.py`, replace with `test_startup_hints_match_doc.py`.
- [ ] **0.13** Rewrite `test_manager_observe_dedupe.py` to drop the mock.
- [ ] **0.14** Write `test_integration_memory_os.py` — full end-to-end. This is the keystone test.
- [ ] **P0 gate**: full suite green. Commit.

### P1 — API expansion

- [ ] **1.1** Add pydantic response models in a new module (or at top of `server.py`).
- [ ] **1.2** Add `GET /api/memory/detail/{memory_id}` + `memory_detail` MCP tool.
- [ ] **1.3** Add `GET /api/memory/kb` + `memory_kb` MCP tool. Implementation: filter by `type` into four slices, return summaries only (no raw content body unless `?full=true`).
- [ ] **1.4** Add `GET /api/memory/pressure` + `memory_pressure` MCP tool. Return structured JSON, not the pre-formatted string currently embedded in the startup response.
- [ ] **1.5** Add `POST /api/memory/prune/plan` + `prune_plan` MCP tool.
- [ ] **1.6** Add `POST /api/memory/prune/apply` — **REST only, no MCP tool**. Verify `prune_apply` is not in `tools/builtin/memory.py`.
- [ ] **1.7** Add `POST /api/memory/lifecycle/backfill` + `backfill_lifecycle` MCP tool.
- [ ] **1.8** Add `GET /api/memory/resume` + `resume_packet` MCP tool. This is the clean structured endpoint; the existing `/api/memory/context/startup` continues to work unchanged.
- [ ] **1.9** Add server integration tests in `tests/test_server_endpoints.py` exercising each new endpoint with a real tmp Qdrant.
- [ ] **1.10** Update `docs/ARCHITECTURE.md` with the new endpoint table and the tier-behavioral semantics.
- [ ] **P1 gate**: full suite green. Commit.

### Migration

- [ ] **M.1** First time the hardened branch runs against an existing `~/.claude/memory` directory, the user calls `POST /api/memory/lifecycle/backfill {"dry_run": true}` via `curl` or via MCP tool, reviews the report, then calls it with `dry_run: false`. No automatic migration on server start.
- [ ] **M.2** Document the migration step in `docs/AGENT_STARTUP.md` and in the spec file referenced from the PR description (when JR asks for a PR).

---

## Run commands

```bash
# Full test suite (local, fast)
uv run --extra dev pytest -v

# Just the new + affected tests
uv run --extra dev pytest tests/test_lifecycle_classifier.py \
  tests/test_recall_tier_bias.py \
  tests/test_backfill_lifecycle.py \
  tests/test_prune_safety.py \
  tests/test_resume_at_scale.py \
  tests/test_scope_trust_yaml.py \
  tests/test_scope_cred_strip.py \
  tests/test_observe_low_signal.py \
  tests/test_integration_memory_os.py \
  -v

# Server integration tests (requires Qdrant on :6334)
docker compose --profile test run --rm test pytest tests/test_server_endpoints.py -v

# Start the hardened backend locally (for manual testing against the UI later)
docker compose up -d  # production Qdrant on 6333
MCP_TRANSPORT=streamable-http HOST=0.0.0.0 PORT=8000 QDRANT_URL=http://localhost:6333 \
  uv run python -m src.server

# One-shot migration for existing memory directory
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H "content-type: application/json" \
  -d '{"dry_run": true}'  # review report first
curl -X POST http://localhost:8000/api/memory/lifecycle/backfill \
  -H "content-type: application/json" \
  -d '{"dry_run": false}'  # then apply
```

---

## Risks and open questions

| Risk | Mitigation |
|---|---|
| `reinforce_and_reclassify` runs on every dedupe hit and adds a classifier recompute to the save hot path. | Classifier is pure Python arithmetic on a 6-field dataclass, ~microseconds. Benchmark in the integration test if needed. Acceptable. |
| Backfill on a very large memory directory could be slow. | 500-point batches, progress logging every batch, dry-run first. Cancel-safe: incomplete backfills just leave some memories unclassified, which is the pre-spec default. |
| `_PLAN_STORE` is in-memory — lost on server restart. | Intentional. Plans are ephemeral by design; 15-min TTL. A new plan is cheap to regenerate. |
| Killing `prune_apply` at the MCP layer means agents literally cannot self-prune. | Intentional per JR's directive and the review's C1 fix. If an automation case ever needs it, add a separate `agent_prune_apply` tool with its own stricter guardrails as a future spec — not this one. |
| `trust.yaml` schema could drift. | Validate with pydantic at load time; bad file = log warning + default to `personal`. Never crash the server on a bad trust file. |
| The integration test adds latency to the suite (real Qdrant connection). | Gate it behind `-m integration` marker and run in the Docker `test` profile. Fast unit tests stay on the local `pytest` path. |

## Open questions for JR to answer at review

1. Is the **4-tier vocabulary** (working/episodic/semantic/identity) permanent, or do you want any of them renamed before this ships? (I recommend keeping them.)
2. Is the **hard cap of 200 deletions per apply** reasonable, or do you want stricter (e.g., 50)?
3. For **`/api/memory/kb`**, the four slices I propose are `decisions`, `requirements`, `preferences`, `learnings`. Any slices you'd add or cut? (I considered `constraints` and `incidents` but YAGNI'd them.)
4. **Plan TTL 15 minutes** — too long, too short, or fine?

None of these block writing the implementation plan. They are tuning knobs that can be adjusted in the implementation PR.

---

## Out of scope (lands in the sibling UI spec)

- Next.js cockpit structure, routing, shared design tokens, visual language, polling → React Query
- Force-directed graph engine choice (Cytoscape vs d3-force vs react-force-graph)
- Node details drawer, KB curated display, continuity console, hygiene dashboard
- Prune-apply UX (the actual UI flow that calls `POST /api/memory/prune/apply` with the plan id)
- Motion, animation, premium visual polish

All of those require this spec's backend to be green first.
