from __future__ import annotations

from datetime import datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def capsule_manager():
    """Factory fixture: call with a list of memory dicts → returns a manager stub."""

    def _make(memories):
        class _Store:
            def scroll(self, filters=None, limit=300):
                return list(memories)

        class _Graph:
            def get_importance(self, memory_id):
                return 0.5

        return type("Manager", (), {"store": _Store(), "knowledge_graph": _Graph()})()

    return _make


@pytest.fixture
def capsule_manager_empty(capsule_manager):
    return capsule_manager([])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _mem(memory_id, type_, content, date_delta_days=0, **extra):
    date = (datetime.now() - timedelta(days=date_delta_days)).strftime("%Y-%m-%d")
    return {
        "memory_id": memory_id,
        "type": type_,
        "date": date,
        "content": content,
        "entities": [],
        **extra,
    }


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------


def test_capsule_groups_project_familiarity():
    from memory.capsules import build_project_capsule

    class Store:
        def scroll(self, filters=None, limit=300):
            assert filters == {"project": "byte-edge"}
            assert limit == 2000
            return [
                {
                    "memory_id": "m1",
                    "type": "decision",
                    "tier": "semantic",
                    "date": "2026-07-01",
                    "content": "Use Longhorn tuned settings for two-node k3s.",
                    "entities": ["Longhorn", "k3s"],
                },
                {
                    "memory_id": "m2",
                    "type": "learning",
                    "tier": "episodic",
                    "date": "2026-07-02",
                    "content": "Helm rollout failed until BSO namespace policy was fixed.",
                    "entities": ["Helm", "BSO"],
                },
                {
                    "memory_id": "m3",
                    "type": "requirement",
                    "tier": "semantic",
                    "date": "2026-07-02",
                    "content": "Back up live Claude files before editing hooks.",
                    "entities": ["Claude"],
                },
            ]

    manager = type(
        "Manager",
        (),
        {
            "store": Store(),
            "knowledge_graph": type(
                "Graph",
                (),
                {
                    "get_importance": lambda self, memory_id: {
                        "m1": 0.9,
                        "m2": 0.5,
                        "m3": 0.8,
                    }.get(memory_id, 0.5)
                },
            )(),
        },
    )()

    capsule = build_project_capsule(manager, "byte-edge")

    assert capsule["project"] == "byte-edge"
    assert "Longhorn" in capsule["entities"]
    assert any("two-node k3s" in item["content"] for item in capsule["standing_context"])
    # m3 (requirement, no danger) → standing_context under new routing (operating_rules merged)
    assert any(
        "Back up live Claude files" in item["content"] for item in capsule["standing_context"]
    )


def test_capsule_scans_beyond_small_limit_for_recent_high_priority_items():
    from memory.capsules import build_project_capsule

    points = [
        {
            "memory_id": f"m{i}",
            "type": "decision",
            "tier": "semantic",
            "date": f"2026-06-{(i % 28) + 1:02d}",
            "content": f"Filler decision {i}.",
            "entities": ["Filler"],
        }
        for i in range(320)
    ]
    points[319] = {
        "memory_id": "m319",
        "type": "decision",
        "tier": "semantic",
        "date": "2026-07-02",
        "content": "Ship the high priority startup capsule fix.",
        "entities": ["Startup"],
    }

    class Store:
        def scroll(self, filters=None, limit=300):
            assert filters == {"project": "byte-edge"}
            assert limit == 2000
            return points[:limit]

    class Graph:
        def get_importance(self, memory_id):
            return 0.99 if memory_id == "m319" else 0.1

    manager = type("Manager", (), {"store": Store(), "knowledge_graph": Graph()})()

    capsule = build_project_capsule(manager, "byte-edge", limit=300)

    assert any(item["memory_id"] == "m319" for item in capsule["standing_context"])
    assert len(capsule["standing_context"]) <= 8


def test_render_project_capsule_is_thin():
    from memory.capsules import render_project_capsule

    text = render_project_capsule(
        {
            "project": "byte-edge",
            "entities": ["Longhorn", "Helm"],
            "standing_context": [{"content": "Use Longhorn tuned settings.", "date": "2026-07-01"}],
            "danger_zones": [
                {"content": "Migration failed and corrupted the index.", "date": "2026-07-02"}
            ],
            "open_loops": [],
        }
    )

    assert text.startswith("# Project Capsule: byte-edge")
    assert "Entities: Longhorn, Helm" in text
    assert len(text) < 2000


# ---------------------------------------------------------------------------
# New tests — routing contract
# ---------------------------------------------------------------------------


def test_capsule_has_no_removed_keys(capsule_manager):
    """Capsule dict must not contain active_workstreams or operating_rules keys."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("x1", "decision", "Chose PostgreSQL for relational data."),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    assert "active_workstreams" not in capsule
    assert "operating_rules" not in capsule


def test_danger_requirement_routes_only_to_danger(capsule_manager):
    """type=requirement + danger pattern → danger_zones only, not standing_context."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("req1", "requirement", "NEVER push to main. Feature branch + PR."),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    danger_ids = [item["memory_id"] for item in capsule["danger_zones"]]
    standing_ids = [item["memory_id"] for item in capsule["standing_context"]]

    assert "req1" in danger_ids, "requirement+never must land in danger_zones"
    assert "req1" not in standing_ids, "requirement+never must NOT land in standing_context"


def test_pure_decision_routes_only_to_standing(capsule_manager):
    """type=decision with no danger/open patterns → standing_context only."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("d1", "decision", "Chose FastAPI over Flask for async support."),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    danger_ids = [item["memory_id"] for item in capsule["danger_zones"]]
    open_ids = [item["memory_id"] for item in capsule["open_loops"]]
    standing_ids = [item["memory_id"] for item in capsule["standing_context"]]

    assert "d1" in standing_ids
    assert "d1" not in danger_ids
    assert "d1" not in open_ids
    assert "active_workstreams" not in capsule
    assert "operating_rules" not in capsule


def test_migration_doc_reference_not_danger(capsule_manager):
    """learning without danger/open terms → excluded from all buckets."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("l1", "learning", "Updated MIGRATION.md with v1.9 notes."),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    all_ids = set(
        [i["memory_id"] for i in capsule["danger_zones"]]
        + [i["memory_id"] for i in capsule["open_loops"]]
        + [i["memory_id"] for i in capsule["standing_context"]]
    )
    assert "l1" not in all_ids, "learning without danger/open terms must be excluded"


def test_failed_migration_is_danger(capsule_manager):
    """learning + 'failed' and 'corrupted' → danger_zones."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("l2", "learning", "The data migration failed and corrupted the index."),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    danger_ids = [item["memory_id"] for item in capsule["danger_zones"]]
    assert "l2" in danger_ids


def test_old_todo_not_open_loop(capsule_manager):
    """TODO content older than 90 days must NOT appear in open_loops."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem("old1", "note", "TODO: migrate helm chart to new registry.", date_delta_days=150),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    open_ids = [item["memory_id"] for item in capsule["open_loops"]]
    assert "old1" not in open_ids
    assert "active_workstreams" not in capsule


def test_recent_blocked_is_open_loop(capsule_manager):
    """Recent 'blocked' note (within 90 days) → open_loops."""
    from memory.capsules import build_project_capsule

    manager = capsule_manager(
        [
            _mem(
                "n1",
                "note",
                "blocked: waiting on infra team to provision nodes.",
                date_delta_days=5,
            ),
        ]
    )
    capsule = build_project_capsule(manager, "test")

    open_ids = [item["memory_id"] for item in capsule["open_loops"]]
    assert "n1" in open_ids


def test_no_memory_in_two_buckets(capsule_manager):
    """Property: union of all bucket id-lists has zero duplicates (exclusive routing)."""
    from memory.capsules import build_project_capsule

    corpus = [
        # danger_zones: type in DANGER_TYPES + pattern
        _mem("p0", "requirement", "NEVER push to main. Feature branch always."),
        _mem("p1", "learning", "The migration failed unexpectedly."),
        _mem("p2", "fact", "Database corruption detected during upgrade."),
        _mem("p3", "decision", "Do not disable auth even in dev."),
        _mem("p4", "requirement", "All incidents must be escalated immediately."),
        # open_loops: recent + open pattern (not danger)
        _mem("p5", "note", "TODO: update Helm chart.", date_delta_days=5),
        _mem("p6", "note", "Blocked: waiting on infra team.", date_delta_days=10),
        _mem("p7", "session", "Follow up on certificate renewal.", date_delta_days=30),
        _mem("p8", "note", "Pending migration review.", date_delta_days=15),
        _mem("p9", "note", "Next step: run load benchmarks.", date_delta_days=20),
        # standing_context: type in STANDING_TYPES, no danger/open
        _mem(
            "p10", "decision", "Use Qdrant as vector store."
        ),  # "qdrant" NOT in new danger patterns
        _mem("p11", "requirement", "Code reviews required on all PRs."),
        _mem("p12", "preference", "Prefer FastAPI over Flask."),
        _mem("p13", "decision", "Chose k3s for local cluster management."),
        _mem("p14", "preference", "Use ruff for Python formatting."),
        # excluded: no matching bucket
        _mem("p15", "note", "Reviewed the architecture document."),
        _mem("p16", "learning", "Read about Qdrant hybrid search capabilities."),
        _mem("p17", "fact", "Version 1.8.0 released on 2026-06-01."),
        _mem("p18", "session", "Started working on capsule refactor today."),
        _mem("p19", "summary", "Summary of yesterday's session."),
        # stale open-loop terms (>90 days) → excluded
        _mem("p20", "note", "TODO: migrate old Helm charts.", date_delta_days=150),
        _mem("p21", "note", "Blocked: waiting on approval.", date_delta_days=120),
        # more standing
        _mem("p22", "decision", "Avoid singleton patterns in async handlers."),
        _mem("p23", "requirement", "Tests must pass before any merge."),
        _mem("p24", "preference", "Logging should use structured JSON."),
        # more danger
        _mem("p25", "learning", "Race condition found in compaction code."),
        _mem("p26", "fact", "Data loss risk if qdrant tmpfs volume fills up."),
        _mem("p27", "decision", "Don't cache auth tokens in localStorage."),
        # more open loops (recent)
        _mem("p28", "note", "Not yet: enable BM25 hybrid search.", date_delta_days=25),
        _mem("p29", "fact", "Restart needed after config change.", date_delta_days=40),
    ]

    manager = capsule_manager(corpus)
    capsule = build_project_capsule(manager, "test")

    all_ids = (
        [item["memory_id"] for item in capsule["danger_zones"]]
        + [item["memory_id"] for item in capsule["open_loops"]]
        + [item["memory_id"] for item in capsule["standing_context"]]
    )
    assert len(all_ids) == len(set(all_ids)), (
        f"Duplicate memory_ids across buckets: {[mid for mid in all_ids if all_ids.count(mid) > 1]}"
    )


def test_empty_corpus_renders(capsule_manager_empty):
    """Zero memories: build + render must not crash and must emit no section headers."""
    from memory.capsules import build_project_capsule, render_project_capsule

    capsule = build_project_capsule(capsule_manager_empty, "test")

    assert "active_workstreams" not in capsule
    assert "operating_rules" not in capsule
    assert capsule["danger_zones"] == []
    assert capsule["open_loops"] == []
    assert capsule["standing_context"] == []

    rendered = render_project_capsule(capsule)
    assert isinstance(rendered, str)
    assert "## " not in rendered, "Empty corpus must produce no section headers"
