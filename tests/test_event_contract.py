"""Event contract v2: manager-layer emission with enriched payloads (U1 Task 1)."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from memory.manager import MemoryManager

HITS = [
    {
        "memory_id": f"m{i}",
        "content": f"note {i}",
        "score": 0.9 - i * 0.05,
        "date": "2026-07-01",
        "type": "fact",
        "project": "p",
        "timestamp": f"2026-07-01T0{i}:00:00",
    }
    for i in range(8)
]


def _mgr(hits):
    mgr = object.__new__(MemoryManager)
    mgr._store = MagicMock()
    mgr._store.search.return_value = [dict(h) for h in hits]
    mgr._store.get_many.return_value = []
    mgr._knowledge_graph = MagicMock()
    mgr._knowledge_graph.stats.return_value = {"nodes": 0, "edges": 0}
    mgr._embedder = MagicMock()
    mgr._embedder.encode.return_value = [0.0] * 384
    mgr.record_event = MagicMock()

    @contextmanager
    def _noop_track(_name):
        yield

    telemetry = MagicMock()
    telemetry.track.side_effect = _noop_track
    mgr._telemetry = telemetry
    return mgr


def test_record_event_merges_session_id_into_payload(tmp_path):
    mgr = object.__new__(MemoryManager)
    mgr._event_log = None
    mgr.memory_dir = tmp_path

    mgr.record_event(
        event_type="memory_recalled",
        project="p",
        session_id="sess-42",
        payload={"query": "q"},
    )
    mgr.record_event(event_type="memory_recalled", project="p", payload={"query": "q"})

    events = mgr.event_log.tail(limit=2)
    assert events[0].payload["session_id"] == "sess-42"
    # absent param -> key present and null (old callers stay contract-shaped)
    assert events[1].payload["session_id"] is None


def test_recall_emits_one_memory_recalled_with_query_scores_tokens():
    mgr = _mgr(HITS)
    out = MemoryManager.recall(mgr, "auth rotation", limit=5, task_hint="auth middleware")

    assert mgr.record_event.call_count == 1
    kwargs = mgr.record_event.call_args.kwargs
    assert kwargs["event_type"] == "memory_recalled"
    assert kwargs["memory_ids"] == [m["memory_id"] for m in out]

    payload = kwargs["payload"]
    assert payload["query"] == "auth rotation"
    assert payload["task_hint"] == "auth middleware"
    assert payload["memories"] == [{"memory_id": m["memory_id"], "score": m["score"]} for m in out]
    assert payload["token_estimate"] == sum(len(m["content"]) // 4 for m in out)
    assert payload["session_id"] is None
    assert payload["capture_origin"] is None


def test_recall_survives_event_emission_failure():
    mgr = _mgr(HITS)
    mgr.record_event.side_effect = RuntimeError("event log broken")

    out = MemoryManager.recall(mgr, "auth rotation", limit=5)

    assert [m["memory_id"] for m in out] == [f"m{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_mcp_recall_tool_rides_on_manager_emission(tool_registry):
    """recall_memories has no emission of its own — manager.recall carries it."""
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider = OptimizedMemoryTools()
    provider._manager = _mgr(HITS)
    provider.register(FakeMCP())

    await registered_tools["recall_memories"](query="auth rotation", limit=3)

    assert provider._manager.record_event.call_count == 1
    assert provider._manager.record_event.call_args.kwargs["event_type"] == "memory_recalled"


@pytest.fixture
def rest_client():
    from starlette.testclient import TestClient

    from server import mcp

    return TestClient(mcp.streamable_http_app())


@pytest.fixture
def fake_rest_manager(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("memory.singleton._instance", fake)
    return fake


def test_cross_project_handler_does_not_emit(rest_client, fake_rest_manager):
    """Both inner manager.recall calls emit; the handler must add nothing."""
    fake_rest_manager.recall_cross_project.return_value = {
        "query": "q",
        "current_project": "p",
        "same_project": [{"memory_id": "m1", "content": "x"}],
        "related_projects": [],
        "global": [],
    }
    r = rest_client.post(
        "/api/memory/recall/cross-project", json={"query": "q", "current_project": "p"}
    )
    assert r.status_code == 200
    fake_rest_manager.record_event.assert_not_called()


def test_reflex_handler_does_not_emit(rest_client, fake_rest_manager):
    """manager.recall emits once per cue; the handler must add nothing."""
    fake_rest_manager.reflex.return_value = {
        "cues": ["iac"],
        "memories": [{"memory_id": "m1", "content": "x", "reason": "iac"}],
    }
    r = rest_client.post("/api/memory/reflex", json={"text": "terraform apply"})
    assert r.status_code == 200
    fake_rest_manager.record_event.assert_not_called()


def _real_save_manager(tmp_path, monkeypatch):
    """Real manager against tmp storage, vector/graph legs stubbed (pattern:
    tests/test_memory_events.py::test_manager_records_memory_saved_event)."""
    manager = MemoryManager(memory_dir=tmp_path, qdrant_url="http://localhost:6334")
    manager._store = type(
        "Store",
        (),
        {"search": lambda *a, **k: [], "save": lambda *a, **k: None},
    )()
    manager._embedder = type("Embedder", (), {"encode": lambda self, text: [0.1] * 384})()
    manager._knowledge_graph = type(
        "Graph",
        (),
        {"add_node": lambda *a, **k: None, "save": lambda *a, **k: None},
    )()
    monkeypatch.setattr(
        "memory.manager.auto_link",
        lambda **kwargs: type("R", (), {"edges_created": 0, "relations": {}})(),
    )
    return manager


def test_save_stamps_capture_origin_into_memory_saved_event(tmp_path, monkeypatch):
    manager = _real_save_manager(tmp_path, monkeypatch)

    manager.save("Use capsules", type="decision", project="p", capture_origin="cli")
    manager.save("Another memory entirely", type="decision", project="p")

    events = manager.event_log.tail(limit=2)
    assert events[0].payload["capture_origin"] == "cli"
    assert events[1].payload["capture_origin"] == "rest"  # documented default


def test_save_threads_session_id_into_memory_saved_event(tmp_path, monkeypatch):
    manager = _real_save_manager(tmp_path, monkeypatch)

    manager.save("Session-stamped memory", type="decision", project="p", session_id="sess-9")
    manager.save("Another memory entirely two", type="decision", project="p")

    events = manager.event_log.tail(limit=2)
    assert events[0].payload["session_id"] == "sess-9"
    # old callers (no session_id) stay contract-shaped: key present, null
    assert events[1].payload["session_id"] is None


def test_save_threads_evidence_class_into_memory_saved_event(tmp_path, monkeypatch):
    manager = _real_save_manager(tmp_path, monkeypatch)

    manager.save(
        "Evidence-stamped memory",
        type="decision",
        project="p",
        evidence_class="confirmed_artifact",
    )
    manager.save("Another memory entirely three", type="decision", project="p")

    events = manager.event_log.tail(limit=2)
    assert events[0].payload["evidence_class"] == "confirmed_artifact"
    # missing -> null, NEVER coerced to "inferred" (old hooks must not
    # pollute U3's queue)
    assert events[1].payload["evidence_class"] is None


def test_observe_threads_capture_origin_to_save():
    mgr = object.__new__(MemoryManager)
    candidate = MagicMock()
    candidate.should_save = True
    candidate.content = "judged content"
    candidate.memory_type = "learning"
    candidate.salience = 0.8
    mgr._observer = MagicMock()
    mgr._observer.evaluate.return_value = candidate
    mgr.save = MagicMock(return_value="mid")

    MemoryManager.observe(mgr, "judged content", capture_origin="observe_judge")

    assert mgr.save.call_args.kwargs["capture_origin"] == "observe_judge"


def test_rest_save_stamps_capture_origin_rest(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post("/api/memory/save", json={"content": "remember this"})
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["capture_origin"] == "rest"


def test_rest_observe_stamps_capture_origin_hook(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "fixed the bug", "type": "learning", "cwd": "/tmp/x"},
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["capture_origin"] == "hook"


def test_rest_observe_threads_session_id(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "fixed the bug", "type": "learning", "cwd": "/tmp/x", "session_id": "s-1"},
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["session_id"] == "s-1"


def test_rest_observe_threads_evidence_class(rest_client, fake_rest_manager):
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={
            "summary": "fixed the bug",
            "type": "learning",
            "cwd": "/tmp/x",
            "evidence_class": "confirmed_artifact",
        },
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["evidence_class"] == "confirmed_artifact"


def test_rest_observe_without_session_id_nulls_it(rest_client, fake_rest_manager):
    """Version-skew pin: an old installed hook sends no session_id -> null, never fabricated."""
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "fixed the bug", "type": "learning", "cwd": "/tmp/x"},
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["session_id"] is None


def test_rest_observe_without_evidence_class_nulls_it(rest_client, fake_rest_manager):
    """Skew pin: old hooks send no evidence_class -> null, never 'inferred'."""
    fake_rest_manager.save.return_value = "mid"
    r = rest_client.post(
        "/api/memory/observe",
        json={"summary": "fixed the bug", "type": "learning", "cwd": "/tmp/x"},
    )
    assert r.status_code == 200
    assert fake_rest_manager.save.call_args.kwargs["evidence_class"] is None


@pytest.mark.asyncio
async def test_mcp_tools_stamp_capture_origin(tool_registry):
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    manager = MagicMock()
    manager.observe.return_value = "mid"
    manager.save.return_value = "mid"
    provider = OptimizedMemoryTools()
    provider._manager = manager
    provider.register(FakeMCP())

    await registered_tools["observe"](summary="fixed the bug", type="learning")
    assert manager.observe.call_args.kwargs["capture_origin"] == "observe_judge"

    await registered_tools["save_memory"](content="remember this", memory_type="note")
    assert manager.save.call_args.kwargs["capture_origin"] == "save_memory_tool"


def test_recall_with_cwd_attributes_event_to_detected_project(tmp_path):
    """No explicit project + caller cwd → the event carries the detected project."""
    caller = tmp_path / "caller-proj"
    caller.mkdir()
    mgr = _mgr(HITS)

    MemoryManager.recall(mgr, "auth rotation", limit=5, cwd=str(caller))

    assert mgr.record_event.call_args.kwargs["project"] == "caller-proj"


def test_recall_explicit_project_beats_cwd(tmp_path):
    caller = tmp_path / "caller-proj"
    caller.mkdir()
    mgr = _mgr(HITS)

    MemoryManager.recall(mgr, "auth rotation", limit=5, project="explicit-proj", cwd=str(caller))

    assert mgr.record_event.call_args.kwargs["project"] == "explicit-proj"


def test_recall_without_project_or_cwd_stays_general():
    mgr = _mgr(HITS)

    MemoryManager.recall(mgr, "auth rotation", limit=5)

    assert mgr.record_event.call_args.kwargs["project"] == "general"


@pytest.mark.asyncio
async def test_mcp_recall_tool_forwards_cwd_for_attribution(tool_registry, tmp_path):
    """cwd through the tool → manager emission attributed to the detected project."""
    from tools.builtin.memory import OptimizedMemoryTools

    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    caller = tmp_path / "tool-proj"
    caller.mkdir()
    provider = OptimizedMemoryTools()
    provider._manager = _mgr(HITS)
    provider.register(FakeMCP())

    await registered_tools["recall_memories"](query="auth rotation", cwd=str(caller))

    assert provider._manager.record_event.call_args.kwargs["project"] == "tool-proj"


def test_rest_recall_passes_cwd_to_manager(rest_client, fake_rest_manager):
    fake_rest_manager.recall.return_value = []
    r = rest_client.post("/api/memory/recall", json={"query": "q", "cwd": "/Users/x/repo"})
    assert r.status_code == 200
    assert fake_rest_manager.recall.call_args.kwargs["cwd"] == "/Users/x/repo"


def test_rest_recall_without_cwd_passes_none(rest_client, fake_rest_manager):
    """Old clients send no cwd → None, never fabricated from the backend's own cwd."""
    fake_rest_manager.recall.return_value = []
    r = rest_client.post("/api/memory/recall", json={"query": "q"})
    assert r.status_code == 200
    assert fake_rest_manager.recall.call_args.kwargs["cwd"] is None


def test_cli_save_stamps_capture_origin_cli():
    from unittest.mock import patch

    from click.testing import CliRunner

    from memory.cli import memory as memory_cli

    with patch("memory.cli.MemoryManager") as manager_cls:
        manager_cls.return_value.save.return_value = "mid"
        result = CliRunner().invoke(memory_cli, ["save", "remember this", "--project", "p"])

    assert result.exit_code == 0, result.output
    assert manager_cls.return_value.save.call_args.kwargs["capture_origin"] == "cli"


def _capsule_manager():
    mgr = MagicMock()
    mgr.store.scroll.return_value = [
        {
            "memory_id": "m1",
            "content": "Decided to use capsules",
            "type": "decision",
            "date": "2026-07-10",
            "tier": "semantic",
            "entities": [],
        },
        {
            "memory_id": "m2",
            "content": "never point tests at production qdrant",
            "type": "learning",
            "date": "2026-07-09",
            "tier": "semantic",
            "entities": [],
        },
    ]
    mgr.knowledge_graph.get_importance.return_value = 0.5
    return mgr


def test_build_project_capsule_emits_one_memory_surfaced():
    from memory.capsules import build_project_capsule

    mgr = _capsule_manager()
    capsule = build_project_capsule(mgr, project="p", session_id="sess-7")

    surfaced = [
        {"memory_id": m["memory_id"], "content": m["content"]}
        for bucket in ("standing_context", "danger_zones", "open_loops")
        for m in capsule[bucket]
    ]
    assert surfaced  # fixture must actually surface something

    assert mgr.record_event.call_count == 1
    kwargs = mgr.record_event.call_args.kwargs
    assert kwargs["event_type"] == "memory_surfaced"
    assert kwargs["project"] == "p"
    payload = kwargs["payload"]
    assert payload["memory_ids"] == [m["memory_id"] for m in surfaced]
    assert payload["token_estimate"] == sum(len(m["content"]) // 4 for m in surfaced)
    assert kwargs["session_id"] == "sess-7"


def test_capsule_get_threads_session_id(rest_client, fake_rest_manager):
    """?session_id= reaches build_project_capsule; absent -> None (skew pin)."""
    fake_rest_manager.get_project_capsule.return_value = {"project": "p"}

    r = rest_client.get("/api/memory/capsule?project=p&session_id=s-2")
    assert r.status_code == 200
    assert fake_rest_manager.get_project_capsule.call_args.kwargs["session_id"] == "s-2"

    r = rest_client.get("/api/memory/capsule?project=p")
    assert r.status_code == 200
    assert fake_rest_manager.get_project_capsule.call_args.kwargs["session_id"] is None


def test_startup_get_threads_session_id(rest_client, fake_rest_manager):
    """?session_id= reaches get_agent_startup; absent -> None (skew pin)."""
    fake_rest_manager.get_agent_startup.return_value = {"project_capsule": {}}

    r = rest_client.get("/api/memory/context/startup?project=p&session_id=s-3")
    assert r.status_code == 200
    assert fake_rest_manager.get_agent_startup.call_args.kwargs["session_id"] == "s-3"

    r = rest_client.get("/api/memory/context/startup?project=p")
    assert r.status_code == 200
    assert fake_rest_manager.get_agent_startup.call_args.kwargs["session_id"] is None


def test_nothing_coerces_null_evidence_class_to_inferred():
    """HARD RULE: null evidence_class is NEVER mapped to "inferred" — old
    installed hooks (no evidence_class) must not pollute U3's review queue
    with fabricated judgments. Grep-level pin over src/ and the hooks."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    coercion_patterns = [
        'or "inferred"',
        "or 'inferred'",
        'default="inferred"',
        "default='inferred'",
        '// "inferred"',  # jq default
        ":-inferred",  # bash parameter default
    ]
    scan_roots = [repo / "src", repo / "claude" / "hooks"]
    offenders = []
    for root in scan_roots:
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".sh") or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in coercion_patterns:
                if pattern in text:
                    offenders.append(f"{path}: {pattern!r}")
    assert not offenders, "null evidence_class coerced to 'inferred':\n" + "\n".join(offenders)


def test_capsule_and_startup_handlers_do_not_emit(rest_client, fake_rest_manager):
    """Both consumers of build_project_capsule ride on its emission."""
    capsule = {
        "project": "p",
        "entities": [],
        "standing_context": [{"memory_id": "m1", "content": "x"}],
        "danger_zones": [],
        "open_loops": [],
    }
    fake_rest_manager.get_project_capsule.return_value = capsule
    fake_rest_manager.get_agent_startup.return_value = {"project_capsule": capsule}

    r = rest_client.get("/api/memory/capsule?project=p")
    assert r.status_code == 200
    r = rest_client.get("/api/memory/context/startup?project=p")
    assert r.status_code == 200
    fake_rest_manager.record_event.assert_not_called()
