"""Software-work retrieval evals: six integration scenarios over a seeded historical corpus.

Each test asserts a specific retrieval property against real Qdrant (:6334), a real embedder,
and real save/recall/capsule/resume paths.

Corpus: 17 memories across svc-api (primary), infra-live (cross-repo), ui-console (foil).
Every corpus entry is annotated with the scenario(s) it serves; unannotated entries are
forbidden by convention.

Save-order note: s4_old_decision is saved before s4_new_decision so auto_link can find the
older polling decision when the newer webhooks decision is saved, enabling the supersedes edge.
SUPERSEDES condition (linker.py:181): similarity > 0.9 AND new_type == cand_type.
"""

from __future__ import annotations

from datetime import datetime as _real_datetime
from datetime import timedelta

import pytest

from memory import MemoryManager
from memory.knowledge_graph import TYPE_WEIGHTS

TEST_QDRANT_URL = "http://localhost:6334"

# ---------------------------------------------------------------------------
# Base epoch: seed dates are resolved relative to this at fixture setup time.
# Using noon to avoid off-by-one on days calculations (recall uses day arithmetic).
# ---------------------------------------------------------------------------
_NOW = _real_datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Datetime shim: patches memory.manager.datetime so save() writes historical dates.
#
# Satisfies the exact call sequence in manager.save():
#   date      = datetime.now().strftime("%Y-%m-%d")   -- classmethod call on the patched name
#   timestamp = datetime.now().isoformat()            -- same call, same classmethod
#
# _fixed is updated before each save(), reset to _NOW after all saves so recall's
# own datetime.now() calls see a sensible "present" time.
# ---------------------------------------------------------------------------
class _ShimMeta(type):
    """Metaclass that delegates unknown class-level attribute lookups to real datetime.

    Needed because ``datetime.utcnow()`` style calls are class-level lookups;
    plain ``__getattr__`` on the class body only covers *instance* lookups.
    """

    def __getattr__(cls, name: str):  # noqa: ANN001, ANN204
        return getattr(_real_datetime, name)


class _ShimDatetime(metaclass=_ShimMeta):
    """Drop-in for memory.manager.datetime; freezes now() to a configured historical time.

    Any attribute not explicitly defined (utcnow, today, fromisoformat, …) is
    transparently delegated to the real datetime class via _ShimMeta.__getattr__,
    so future callers through the patched name don't break.
    """

    _fixed: _real_datetime = _NOW

    @classmethod
    def now(cls, tz=None):  # noqa: ANN102
        return cls._fixed

    @staticmethod
    def strptime(date_string: str, fmt: str) -> _real_datetime:
        return _real_datetime.strptime(date_string, fmt)


# ---------------------------------------------------------------------------
# Inline corpus (17 memories).
# Every entry has:
#   id_key   — stable key used by tests to look up the resolved memory_id
#   content  — natural prose (no quoted pattern-list words)
#   type     — memory type
#   project  — owning project
#   days_ago — historical age resolved to (today - N days) at seed time
#
# Corpus spans: svc-api (12), infra-live (3), ui-console (2).
# ---------------------------------------------------------------------------
CORPUS: list[dict] = [
    # ---- svc-api --------------------------------------------------------
    # scenario:1,5 — open loop via TODO/waiting-on pattern → capsule["open_loops"]
    {
        "id_key": "s1_open_loop",
        "content": (
            "TODO: wire up the retry logic for failed payment-processing webhooks "
            "in the checkout service; waiting on merchant API rate-limit review from "
            "the platform team before we can proceed"
        ),
        "type": "note",
        "project": "svc-api",
        "days_ago": 3,
    },
    # scenario:1,5 — most-recent thread decision; in resume recent AND important.
    # Phrased with explicit "working on" so the recall query 'what were we working on
    # in svc-api' retrieves it (verified: final_score 0.671 > preference 0.651 when
    # polling importance is halved by scenario-4 supersedes; decision importance=0.85
    # carries the weight the note type in s1_thread_context cannot).
    {
        "id_key": "s1_thread_decision",
        "content": (
            "Currently working on the svc-api checkout service: decided to rewrite "
            "order-confirmation from synchronous fulfillment HTTP calls to an "
            "asynchronous event queue"
        ),
        "type": "decision",
        "project": "svc-api",
        "days_ago": 2,
    },
    # scenario:2,5 — production incident learning; triggers danger gate naturally via
    # 'incident', 'failed', 'corrupted', 'never' (no pattern list quoted) → danger_zones
    {
        "id_key": "s2_incident",
        "content": (
            "During the Black Friday peak we had a production incident: the inventory "
            "sync process failed when two concurrent workers updated the same stock "
            "record simultaneously, causing corrupted inventory counts across hundreds "
            "of SKUs. We must never run concurrent bulk inventory writes without "
            "distributed locking in place."
        ),
        "type": "learning",
        "project": "svc-api",
        "days_ago": 30,
    },
    # scenario:4 — OLD polling decision (MUST be saved before s4_new_decision below)
    # Similarity requirement: embed-embed(old, new) > 0.9 AND < 0.97 (dedup floor).
    # auto_link now uses encode(embedding_text) for search (symmetric with stored vectors);
    # current pair yields embed-embed ≈ 0.949 — verified before adjusting content.
    {
        "id_key": "s4_old_decision",
        "content": (
            "Using polling to synchronise product catalog updates from catalog-svc: "
            "svc-api fetches changed products from the catalog REST endpoint every "
            "30 seconds and refreshes the local product cache on each poll interval"
        ),
        "type": "decision",
        "project": "svc-api",
        "days_ago": 60,
    },
    # scenario:4 — NEW webhooks decision; supersedes s4_old_decision via auto_link
    # (same type=decision; auto_link searches with encode(embedding_text) so similarity
    # is symmetric with stored vectors → this pair scores 0.949, above the 0.9 threshold)
    {
        "id_key": "s4_new_decision",
        "content": (
            "Using webhooks to synchronise product catalog updates from catalog-svc: "
            "svc-api subscribes to catalog push events instead of polling the catalog "
            "REST endpoint every 30 seconds, eliminating the per-poll cache miss"
        ),
        "type": "decision",
        "project": "svc-api",
        "days_ago": 10,
    },
    # scenario:5 — identity/rule (requirement type, no danger pattern) → standing_context
    # and resume important (importance = TYPE_WEIGHTS["requirement"] = 1.0)
    {
        "id_key": "s5_identity_rule",
        "content": (
            "Always include an idempotency key header on every payment API request; "
            "the payment provider silently double-charges without it — confirmed in "
            "a production incident last quarter"
        ),
        "type": "requirement",
        "project": "svc-api",
        "days_ago": 45,
    },
    # scenario:5 — preference → capsule standing_context
    {
        "id_key": "s5_preference",
        "content": (
            "Team prefers structured JSON logging with correlation IDs over free-form "
            "log strings in svc-api services; makes distributed tracing significantly "
            "easier across the stack"
        ),
        "type": "preference",
        "project": "svc-api",
        "days_ago": 20,
    },
    # scenario:5 — recent (days_ago=1, newest memory) → resume recent
    {
        "id_key": "s5_recent",
        "content": (
            "Currently working on the svc-api v2 authentication refactor; migrated "
            "3 of 7 endpoints to the new token-validation middleware; pausing to "
            "address the integration test coverage gap before continuing"
        ),
        "type": "note",
        "project": "svc-api",
        "days_ago": 1,
    },
    # scenario:1 — thread context for 'what were we working on' recall
    # Phrased explicitly as work-in-progress so the query 'what were we working on
    # in svc-api' retrieves this over the product-sync decisions (verified: score 0.662
    # vs webhooks 0.642 at embed-text level).
    {
        "id_key": "s1_thread_context",
        "content": (
            "What we were working on in svc-api: the order management refactor targeting "
            "the state machine migration; currently focused on implementing the state "
            "transition logic between order states"
        ),
        "type": "note",
        "project": "svc-api",
        "days_ago": 5,
    },
    # scenario:2 — inventory-module context for code-context recall
    {
        "id_key": "s2_code_context",
        "content": (
            "The svc-api inventory module uses an optimistic-locking pattern on stock "
            "updates; callers must handle version-mismatch conflicts and retry with "
            "exponential backoff to avoid lost updates"
        ),
        "type": "learning",
        "project": "svc-api",
        "days_ago": 25,
    },
    # scenario:3 — svc-api declares infra-live dependency
    {
        "id_key": "s3_svcapi_infra_link",
        "content": (
            "svc-api staging environment is provisioned by the infra-live Terraform "
            "modules; any infra-live changes can affect svc-api deployments and should "
            "be coordinated"
        ),
        "type": "note",
        "project": "svc-api",
        "days_ago": 8,
    },
    # scenario:3 — svc-api deployment learning (complements infra-live cross-project recall)
    {
        "id_key": "s3_deployment_learning",
        "content": (
            "svc-api pipeline failures after a partial infra-live apply can be resolved "
            "by re-running the Terraform plan; stale Terraform state is the usual cause"
        ),
        "type": "learning",
        "project": "svc-api",
        "days_ago": 22,
    },
    # ---- infra-live ------------------------------------------------------
    # scenario:3 — Terraform fix → must surface in related_projects for svc-api recall
    {
        "id_key": "s3_infra_fix",
        "content": (
            "Fixed the intermittent svc-api deployment failure caused by stale Terraform "
            "state after a partial apply; the fix is terraform state rm on the affected "
            "resource followed by a clean re-apply from scratch"
        ),
        "type": "learning",
        "project": "infra-live",
        "days_ago": 20,
    },
    # scenario:3 — infra-live workspace isolation decision
    {
        "id_key": "s3_infra_decision",
        "content": (
            "Decided to use Terraform workspaces to isolate staging and production "
            "environments in infra-live, preventing accidental state cross-contamination "
            "between service deployments"
        ),
        "type": "decision",
        "project": "infra-live",
        "days_ago": 35,
    },
    # scenario:3 — infra-live backend fact
    {
        "id_key": "s3_infra_fact",
        "content": (
            "The infra-live Terraform backend uses S3 with DynamoDB locking; concurrent "
            "terraform applies will block until the state lock is released, so serialise "
            "applies in CI"
        ),
        "type": "fact",
        "project": "infra-live",
        "days_ago": 12,
    },
    # ---- ui-console (isolation foil for scenario 6 only) ----------------
    # scenario:6 — distinctive ui-console memory; must NOT appear in svc-api recall
    {
        "id_key": "s6_ui_decision",
        "content": (
            "ui-console migrated from Create React App to Vite for faster local "
            "development; the Vite build reduced hot-reload latency from 8 seconds "
            "to under 400 milliseconds"
        ),
        "type": "decision",
        "project": "ui-console",
        "days_ago": 7,
    },
    # scenario:6 — second ui-console memory for isolation depth
    {
        "id_key": "s6_ui_preference",
        "content": (
            "ui-console team prefers Tailwind CSS over styled-components for new "
            "components; reduces CSS bundle size and eliminates the runtime styling "
            "overhead"
        ),
        "type": "preference",
        "project": "ui-console",
        "days_ago": 14,
    },
]

# Corpus size sentinel: keep 15-18 per spec.
assert len(CORPUS) == 17, f"Corpus size out of range: {len(CORPUS)}"

# Every entry must have an id_key annotation.
assert all("id_key" in m for m in CORPUS), "Every corpus entry must have an id_key"


# ---------------------------------------------------------------------------
# Session-scoped fixture: MemoryManager + datetime shim applied once.
# Manual MonkeyPatch is required because the monkeypatch fixture is function-scoped.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def eval_manager(tmp_path_factory):
    """Session-scoped manager with the datetime shim live for the whole session."""
    import memory.manager as _mm_module

    mp = pytest.MonkeyPatch()
    tmpdir = tmp_path_factory.mktemp("eval_memory")
    mp.setattr(_mm_module, "datetime", _ShimDatetime)

    manager = MemoryManager(memory_dir=tmpdir, qdrant_url=TEST_QDRANT_URL)
    yield manager
    mp.undo()


# ---------------------------------------------------------------------------
# Function-scoped autouse fixture: re-seeds corpus for every test.
#
# Explicit dependency on _clean_integration_collection guarantees seeding runs
# AFTER the autouse fixture has recreated (wiped) the Qdrant collection.
#
# Graph reset before each seed prevents stale supersedes/contradicts edges from
# polluting subsequent tests.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def seeded_corpus(_clean_integration_collection, eval_manager):
    """Re-seed the full corpus into a fresh collection for every integration test."""
    # 1. Reset knowledge graph (delete file + clear lazy cache).
    graph_path = eval_manager.memory_dir / "_graph.json"
    if graph_path.exists():
        graph_path.unlink()
    eval_manager._knowledge_graph = None  # force lazy re-init

    # 2. Reset store so the recreated collection gets fresh indexes.
    eval_manager._store = None

    # 3. Seed each corpus entry with its historical datetime.
    saved_ids: dict[str, str] = {}
    for mem in CORPUS:
        _ShimDatetime._fixed = _NOW - timedelta(days=mem["days_ago"])
        mid = eval_manager.save(
            mem["content"],
            type=mem["type"],
            project=mem["project"],
        )
        saved_ids[mem["id_key"]] = mid

    # 4. Reset shim to "present" so recall's recency scoring uses correct days_old.
    _ShimDatetime._fixed = _NOW

    # ---- Fixture preconditions (scenario 4) --------------------------------
    # These assert corpus well-formedness. Failure = ERROR (setup), not FAIL.
    graph = eval_manager.knowledge_graph
    old_id = saved_ids["s4_old_decision"]
    new_id = saved_ids["s4_new_decision"]

    # (a) auto_link must have created a supersedes edge: new_id → old_id
    out_edges = graph.get_edges(new_id, direction="out")
    supersedes_targets = [e.target for e in out_edges if e.relation == "supersedes"]
    assert old_id in supersedes_targets, (
        f"Precondition FAIL: auto_link did not create supersedes edge "
        f"{new_id!r} → {old_id!r}. "
        f"Out-edges: {[(e.relation, e.target, round(e.weight, 3)) for e in out_edges]}. "
        "Tune corpus content similarity (requires cosine > 0.9, same type)."
    )

    # (b) old decision importance must be halved below TYPE_WEIGHTS["decision"]
    old_importance = graph.get_importance(old_id)
    assert old_importance < TYPE_WEIGHTS["decision"], (
        f"Precondition FAIL: old decision importance {old_importance} "
        f"not < TYPE_WEIGHTS['decision']={TYPE_WEIGHTS['decision']}. "
        "The linker halving did not fire."
    )

    yield saved_ids


# ===========================================================================
# Scenario 1: resume_after_restart
# ===========================================================================
@pytest.mark.integration
def test_resume_after_restart(seeded_corpus, eval_manager):
    """Unfinished-thread ids appear in capsule open_loops; thread decision in
    resume important + recent; top-3 recall for 'what were we working on in
    svc-api' includes a thread memory."""
    from memory.scope import ScopeDetector

    scope = ScopeDetector.detect(project="svc-api")
    packet = eval_manager.get_resume_packet(project="svc-api", scope=scope)
    capsule = eval_manager.get_project_capsule("svc-api")

    open_loop_id = seeded_corpus["s1_open_loop"]
    thread_decision_id = seeded_corpus["s1_thread_decision"]
    thread_context_id = seeded_corpus["s1_thread_context"]

    # (a) TODO open-loop memory is in capsule["open_loops"]
    open_loop_ids = {item["memory_id"] for item in capsule["open_loops"]}
    assert open_loop_id in open_loop_ids, (
        f"Expected {open_loop_id!r} in capsule open_loops. "
        f"Found: {[(i['memory_id'], i['content'][:70]) for i in capsule['open_loops']]}"
    )

    # (b) Thread decision is in resume recent (sorted by date desc)
    recent_ids = {item["memory_id"] for item in packet["recent"]}
    assert thread_decision_id in recent_ids, (
        f"Expected {thread_decision_id!r} in resume recent. "
        f"Got: {[(i['memory_id'], i['date']) for i in packet['recent']]}"
    )

    # (c) Thread decision is in resume important (decision type → importance=0.85)
    important_ids = {item["memory_id"] for item in packet["important"]}
    assert thread_decision_id in important_ids, (
        f"Expected {thread_decision_id!r} in resume important. "
        f"Got: {[(i['memory_id'], i['importance']) for i in packet['important']]}"
    )

    # (d) Top-3 recall for 'what were we working on' contains a thread memory
    results = eval_manager.recall("what were we working on in svc-api", limit=3, project="svc-api")
    result_ids = {r["memory_id"] for r in results}
    thread_ids = {thread_decision_id, thread_context_id}
    assert result_ids & thread_ids, (
        f"Top-3 recall 'what were we working on' contains no thread memory. "
        f"Got: {[(r['memory_id'], r['content'][:70]) for r in results]}"
    )


# ===========================================================================
# Scenario 2: danger_before_repeat
# ===========================================================================
@pytest.mark.integration
def test_danger_before_repeat(seeded_corpus, eval_manager):
    """Incident learning surfaces in capsule danger_zones; same memory in top-3
    recall for the inventory-sync code-context query."""
    incident_id = seeded_corpus["s2_incident"]
    # code_ctx_id is a welcome fallback if corpus scoring shifts, but the incident
    # is the authoritative assertion for danger-before-repeat coverage.

    capsule = eval_manager.get_project_capsule("svc-api")

    # (a) incident learning is in danger_zones (learning ∈ DANGER_TYPES; content
    # contains 'incident', 'failed', 'corrupted', 'never' → DANGER_PATTERNS match)
    danger_ids = {item["memory_id"] for item in capsule["danger_zones"]}
    assert incident_id in danger_ids, (
        f"Expected incident {incident_id!r} in danger_zones. "
        f"Got: {[(i['memory_id'], i['content'][:70]) for i in capsule['danger_zones']]}"
    )

    # (b) incident learning is in top-3 recall for the inventory-sync concurrent-write query.
    # The incident content contains "inventory sync", "concurrent", "failed", "locking"
    # verbatim, so it should rank first; code_ctx_id is a secondary signal but not asserted.
    results = eval_manager.recall(
        "inventory sync concurrent writes locking svc-api",
        limit=3,
        project="svc-api",
    )
    result_ids = {r["memory_id"] for r in results}
    assert incident_id in result_ids, (
        f"Incident {incident_id!r} not in top-3 recall for inventory sync context. "
        f"Got: {[(r['memory_id'], r['content'][:70]) for r in results]}"
    )


# ===========================================================================
# Scenario 3: cross_repo_fix
# ===========================================================================
@pytest.mark.integration
def test_cross_repo_fix(seeded_corpus, eval_manager):
    """infra-live Terraform fix memory surfaces in related_projects of a
    cross-project recall from svc-api; result is labeled with source project."""
    infra_fix_id = seeded_corpus["s3_infra_fix"]

    result = eval_manager.recall_cross_project(
        "Terraform deployment failure svc-api stale state",
        current_project="svc-api",
    )

    related_ids = {item["memory_id"] for item in result["related_projects"]}
    global_ids = {item["memory_id"] for item in result["global"]}

    # (a) infra-live fix is in related_projects OR global (not in same_project)
    assert infra_fix_id in related_ids | global_ids, (
        f"Expected infra-live fix {infra_fix_id!r} in related_projects or global. "
        f"related: {[(i['memory_id'], i['content'][:60]) for i in result['related_projects']]} "
        f"global: {[(i['memory_id'], i['content'][:60]) for i in result['global']]}"
    )

    # (b) result is labeled with project=infra-live
    all_cross = result["related_projects"] + result["global"]
    infra_items = [i for i in all_cross if i.get("memory_id") == infra_fix_id]
    assert infra_items and infra_items[0].get("project") == "infra-live", (
        f"Expected project='infra-live' on {infra_fix_id!r}. "
        f"Got: {infra_items[0] if infra_items else 'not found'}"
    )


# ===========================================================================
# Scenario 4: stale_contradiction
# ===========================================================================
@pytest.mark.integration
def test_stale_contradiction(seeded_corpus, eval_manager):
    """Webhooks decision ranks above the importance-halved polling decision for a
    product-catalog-update query.  The rank ordering is valid because the fixture
    precondition verified that auto_link fired the supersedes edge and halved the
    polling decision's importance (polling.importance < TYPE_WEIGHTS['decision'])."""
    old_id = seeded_corpus["s4_old_decision"]  # polling — importance halved by supersedes
    new_id = seeded_corpus["s4_new_decision"]  # webhooks — full importance

    results = eval_manager.recall(
        "how do we get product catalog updates from catalog-svc",
        limit=5,
        project="svc-api",
    )
    result_ids = [r["memory_id"] for r in results]

    assert new_id in result_ids, (
        f"Webhooks decision {new_id!r} not in top-5. "
        f"Got: {[(r['memory_id'], r['content'][:70]) for r in results]}"
    )
    assert old_id in result_ids, (
        f"Polling decision {old_id!r} not in top-5. "
        f"Got: {[(r['memory_id'], r['content'][:70]) for r in results]}"
    )

    new_rank = result_ids.index(new_id)
    old_rank = result_ids.index(old_id)
    assert new_rank < old_rank, (
        f"Polling (rank {old_rank}) ranked above webhooks (rank {new_rank}); "
        f"importance halving did not shift the ordering. "
        f"Results: {[(r['memory_id'], r['content'][:50]) for r in results]}"
    )


# ===========================================================================
# Scenario 5: startup_coverage
# ===========================================================================
@pytest.mark.integration
def test_startup_coverage(seeded_corpus, eval_manager):
    """6-fact checklist: each corpus entry must appear in its designated resume/capsule
    field.  Threshold ≥5/6 tolerates one routing edge-case without blocking the suite."""
    from memory.scope import ScopeDetector

    scope = ScopeDetector.detect(project="svc-api")
    packet = eval_manager.get_resume_packet(project="svc-api", scope=scope)
    capsule = eval_manager.get_project_capsule("svc-api")

    recent_ids = {i["memory_id"] for i in packet["recent"]}
    important_ids = {i["memory_id"] for i in packet["important"]}
    danger_ids = {i["memory_id"] for i in capsule["danger_zones"]}
    open_loop_ids = {i["memory_id"] for i in capsule["open_loops"]}
    standing_ids = {i["memory_id"] for i in capsule["standing_context"]}

    checks: list[tuple[str, bool]] = [
        # 1. identity/rule: requirement-type memory → resume important OR standing_context
        (
            "s5_identity_rule in resume.important or capsule.standing_context",
            seeded_corpus["s5_identity_rule"] in important_ids | standing_ids,
        ),
        # 2. danger: learning with DANGER_PATTERNS → capsule danger_zones
        (
            "s2_incident in capsule.danger_zones",
            seeded_corpus["s2_incident"] in danger_ids,
        ),
        # 3. open loop: note with TODO/waiting-on → capsule open_loops
        (
            "s1_open_loop in capsule.open_loops",
            seeded_corpus["s1_open_loop"] in open_loop_ids,
        ),
        # 4. preference: preference-type memory → capsule standing_context
        (
            "s5_preference in capsule.standing_context",
            seeded_corpus["s5_preference"] in standing_ids,
        ),
        # 5. recent: newest note (days_ago=1) → resume recent
        (
            "s5_recent in resume.recent",
            seeded_corpus["s5_recent"] in recent_ids,
        ),
        # 6. important: high-importance decision (days_ago=2) → resume important
        (
            "s1_thread_decision in resume.important",
            seeded_corpus["s1_thread_decision"] in important_ids,
        ),
    ]

    passed = [(label, ok) for label, ok in checks if ok]
    failed = [(label, ok) for label, ok in checks if not ok]

    assert len(passed) >= 5, (
        f"Startup coverage: only {len(passed)}/6 facts in designated fields. "
        f"Failed: {[label for label, _ in failed]}"
    )


# ===========================================================================
# Scenario 6: project_isolation (negative)
# ===========================================================================
@pytest.mark.integration
def test_project_isolation(seeded_corpus, eval_manager):
    """Querying with project='svc-api' using the exact content of a ui-console
    memory returns no ui-console results in the top-5.  Catches silent loss of
    the project filter that would surface cross-project noise in every recall."""
    # Use the exact ui-console decision content as the query to maximise
    # the chance of retrieval — if filtering works, still nothing leaks through.
    ui_decision_content = next(m["content"] for m in CORPUS if m["id_key"] == "s6_ui_decision")

    results = eval_manager.recall(
        ui_decision_content,
        limit=5,
        project="svc-api",
    )

    ui_project_leaks = [r for r in results if r.get("project") == "ui-console"]
    assert not ui_project_leaks, (
        f"Project filter leak: {len(ui_project_leaks)} ui-console memories appeared "
        f"in svc-api recall top-5. "
        f"Leaked: {[(r['memory_id'], r['content'][:70]) for r in ui_project_leaks]}"
    )
