# Audit Hardening (Milestone 0 + Quick Wins + Critical Fixes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Critical/High findings from `docs/audits/2026-06-10-repo-audit.md`: test isolation from production Qdrant, CI, loopback-by-default, input validation (path traversal + type enum), the `cleanup()`/`clear_project()` silent-failure bugs, per-request embedder waste, the hybrid `score_threshold` drop, and doc drift.

**Architecture:** No structural changes. Each task is a surgical fix to an existing module plus a regression test that fails first. Tests that genuinely need a live Qdrant get the existing `integration` marker; pre-commit runs the non-integration suite, CI runs both.

**Tech Stack:** Python 3.11, pytest (+ starlette TestClient), uv, pre-commit, GitHub Actions, Docker (Qdrant).

**Spec:** `docs/superpowers/specs/2026-06-10-audit-hardening-spec.md` (FR1–FR13, NFR1–NFR4), derived from `docs/audits/2026-06-10-repo-audit.md` (findings C1, H1–H5, H6 partial, M2, plus QW1–QW5 / Tasks 0.1–0.3, 1.1–1.5).

---

## Preflight (before Task 1)

- [ ] **Confirm you are on a feature branch, NOT main.** If on main: stop and ask the user (repo rule: no branch creation without explicit permission).
- [ ] **Back up production data** (we touch test infra around a live memory store):

```bash
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p ~/backups
tar czf ~/backups/pre-$TS-memory.tar.gz -C ~ .claude/memory
docker compose stop qdrant
tar czf ~/backups/pre-$TS-qdrant.tar.gz -C ~/.claude qdrant
docker compose start qdrant
```

- [ ] **Start the test Qdrant** (tmpfs, port 6334):

```bash
cd /Users/juanreyes/clawd/memento-mcp
docker compose --profile test up -d qdrant-test
curl -sf http://localhost:6334/healthz && echo OK
```

Expected: `OK`. If the service name differs, check `docker-compose.yaml` (the test Qdrant service is defined around line 106 with `QDRANT_URL=http://qdrant-test:6333` used by the `test` profile).

- [ ] **Baseline:** run the suite once and record the result:

```bash
QDRANT_URL=http://localhost:6334 PYTHONPATH=src uv run --extra dev pytest --tb=short -q
```

All tasks below assume this baseline passes (or its failures are noted before starting).

---

### Task 1: Test isolation — tests can never touch production Qdrant (:6333)

Audit findings C1 / 0.1 / QW1.

**Files:**
- Modify: `tests/conftest.py` (fixture `memory_manager` at line 20–23; add autouse fixture)
- Create: `tests/test_qdrant_isolation.py`
- Modify: `tests/test_server_memory_os_endpoints.py` (add `pytestmark` — its module docstring at lines 1–5 admits it reads production Qdrant)
- Modify: `tests/test_memory.py:879` (`@pytest.mark.skip` → integration marker)
- Modify: `.pre-commit-config.yaml:35` (pytest hook entry)

- [ ] **Step 1: Write the failing meta-tests**

Create `tests/test_qdrant_isolation.py`:

```python
"""Guard tests: the suite must be physically unable to reach production Qdrant."""

import pytest

from core.vector_store import VectorStore
from memory.manager import MemoryManager


def test_manager_default_url_is_test_qdrant(tmp_path):
    """With no explicit qdrant_url, a manager built inside a test must point at :6334."""
    manager = MemoryManager(memory_dir=tmp_path)
    assert "6334" in manager._qdrant_url, (
        f"MemoryManager defaulted to {manager._qdrant_url} — test isolation is broken"
    )


def test_connecting_to_production_qdrant_raises():
    """Explicitly pointing a store at :6333 inside a test must hard-fail."""
    store = VectorStore(collection="isolation-check", url="http://localhost:6333")
    with pytest.raises(RuntimeError, match="production Qdrant"):
        _ = store.client
```

- [ ] **Step 2: Run them to verify they fail**

```bash
QDRANT_URL='' PYTHONPATH=src uv run --extra dev pytest tests/test_qdrant_isolation.py -v
```

Expected: both FAIL (`6334 not in http://localhost:6333`, and no `RuntimeError` raised — the second test will instead try a real connection).

- [ ] **Step 3: Add the autouse isolation fixture to `tests/conftest.py`**

Add below the existing imports (`import tempfile`, etc.) and above `temp_memory_dir`:

```python
TEST_QDRANT_URL = "http://localhost:6334"


@pytest.fixture(autouse=True)
def _qdrant_isolation(monkeypatch):
    """Force every test toward the disposable test Qdrant and refuse :6333.

    Production Qdrant lives on :6333 (CLAUDE.md: tests must never touch it).
    """
    monkeypatch.setenv("QDRANT_URL", TEST_QDRANT_URL)

    from core.vector_store import VectorStore

    original_connect = VectorStore._connect

    def guarded_connect(self):
        if ":6333" in self.url:
            raise RuntimeError(
                f"Test attempted to reach production Qdrant ({self.url}). "
                "Tests must use :6334 — start it with: docker compose --profile test up -d qdrant-test"
            )
        return original_connect(self)

    monkeypatch.setattr(VectorStore, "_connect", guarded_connect)
```

- [ ] **Step 4: Make the `memory_manager` fixture explicit**

In `tests/conftest.py`, change:

```python
@pytest.fixture
def memory_manager(temp_memory_dir: Path) -> MemoryManager:
    """Create a MemoryManager instance for testing."""
    return MemoryManager(memory_dir=temp_memory_dir)
```

to:

```python
@pytest.fixture
def memory_manager(temp_memory_dir: Path) -> MemoryManager:
    """Create a MemoryManager instance for testing (test Qdrant only)."""
    return MemoryManager(memory_dir=temp_memory_dir, qdrant_url=TEST_QDRANT_URL)
```

- [ ] **Step 5: Run the meta-tests to verify they pass**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_qdrant_isolation.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Mark the deliberately-prod-reading tests as integration**

In `tests/test_server_memory_os_endpoints.py`, after the imports (line ~9), add:

```python
pytestmark = pytest.mark.integration  # exercises live endpoints against a real Qdrant (:6334)
```

Also update its module docstring (lines 1–6): replace the sentence claiming "the production Qdrant at :6333 is used for read paths" with "Requires a real Qdrant on :6334 (integration marker)."

In `tests/test_memory.py:879`, replace:

```python
@pytest.mark.skip(reason="Requires running Qdrant server")
```

with:

```python
@pytest.mark.integration
```

- [ ] **Step 7: Find any remaining prod-touchers**

Run the full suite with the guard active:

```bash
PYTHONPATH=src uv run --extra dev pytest --tb=short -q
```

Any test failing with `Test attempted to reach production Qdrant` or with a connection error to 6334 (while qdrant-test is up, a 6334 connection error means the test needs Qdrant and should be marked) gets `pytest.mark.integration` added the same way as Step 6. Repeat until the full suite is green.

- [ ] **Step 8: Update the pre-commit pytest hook**

In `.pre-commit-config.yaml`, change line 35 from:

```yaml
        entry: bash -c 'source .venv/bin/activate && PYTHONPATH=src pytest --tb=short -q'
```

to:

```yaml
        entry: bash -c 'source .venv/bin/activate && QDRANT_URL=http://localhost:6334 PYTHONPATH=src pytest -m "not integration" --tb=short -q'
```

- [ ] **Step 9: Verify both suite slices**

```bash
PYTHONPATH=src uv run --extra dev pytest -m "not integration" --tb=short -q
PYTHONPATH=src uv run --extra dev pytest -m integration --tb=short -q
bash tests/verify_test_isolation.sh
```

Expected: all green (integration slice requires qdrant-test up, which Preflight started).

- [ ] **Step 10: Commit**

```bash
git add tests/conftest.py tests/test_qdrant_isolation.py tests/test_server_memory_os_endpoints.py tests/test_memory.py .pre-commit-config.yaml
git commit -m "test: enforce Qdrant isolation — tests refuse :6333, integration marker for real-Qdrant tests"
```

---

### Task 2: GitHub Actions CI

Audit finding H6 / 0.2.

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `src/memory/observe.py:81` (delete one dead assignment so ruff is clean in CI)

- [ ] **Step 1: Verify lint is clean locally first**

```bash
uv run --extra dev ruff check src tests
```

If it flags `src/memory/observe.py:81` (`lowered` assigned but never used — F841), delete that line (`lowered = normalized.lower()` inside `evaluate()`; note the *other* `lowered` at line ~103 inside `_infer_type` is used — leave it). Fix any other trivial findings it reports. Re-run until clean.

- [ ] **Step 2: Create the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Pre-commit (lint, types, unit tests)
        run: uv run pre-commit run --all-files

  integration:
    runs-on: ubuntu-latest
    services:
      qdrant:
        image: qdrant/qdrant:v1.13.4
        ports:
          - 6334:6333
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Wait for Qdrant
        run: |
          for i in $(seq 1 30); do
            curl -sf http://localhost:6334/healthz && exit 0
            sleep 1
          done
          echo "Qdrant did not become healthy" >&2
          exit 1
      - name: Integration tests
        env:
          QDRANT_URL: http://localhost:6334
        run: PYTHONPATH=src uv run pytest -m integration --tb=short -q

  ui:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ui
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: ui/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm test
```

Notes for the implementer:
- The `backend` job reuses pre-commit as the single source of truth (same gates as local commits). The pytest hook excludes integration tests (Task 1 Step 8), so this job needs no Qdrant.
- The pre-commit pytest hook does `source .venv/bin/activate`; `uv sync` creates `.venv` at the repo root, so this works.
- `npm test` must be non-interactive. Check `ui/package.json` — if the `test` script is `vitest` (watch mode) rather than `vitest run`, change the CI step to `npx vitest run` instead of editing package.json.

- [ ] **Step 3: Validate the workflow file**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid')"
```

Expected: `valid`. (Full validation happens when the PR opens — check the Actions tab then.)

- [ ] **Step 4: Run the exact CI commands locally as a smoke test**

```bash
uv run pre-commit run --all-files
QDRANT_URL=http://localhost:6334 PYTHONPATH=src uv run pytest -m integration --tb=short -q
cd ui && npm run lint && npm test && cd ..
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml src/memory/observe.py
git commit -m "ci: add GitHub Actions — pre-commit gates, integration tests vs Qdrant service, UI lint+test"
```

---

### Task 3: `make backup` target

Audit task 0.3 — codify the documented tarball ritual from `CLAUDE.md`.

**Files:**
- Modify: `Makefile` (`.PHONY` line 1; help text ~line 20; new target at end of the Memory Commands section)

- [ ] **Step 1: Add the target**

In `Makefile`: add `backup` to the `.PHONY` list on line 1. In the `help` target's "Memory Commands" block, add:

```make
	@echo "  backup         Tarball ~/.claude/memory + Qdrant volume to ~/backups"
```

Add the target (near `memory-clean`/`qdrant` targets):

```make
backup:
	@mkdir -p ~/backups
	@TS=$$(date +%Y%m%d-%H%M%S); \
	tar czf ~/backups/pre-$$TS-memory.tar.gz -C ~ .claude/memory; \
	docker compose stop qdrant; \
	tar czf ~/backups/pre-$$TS-qdrant.tar.gz -C ~/.claude qdrant; \
	docker compose start qdrant; \
	echo "✓ Backups written: ~/backups/pre-$$TS-{memory,qdrant}.tar.gz"
```

(Indentation must be tabs, not spaces — Makefile requirement.)

- [ ] **Step 2: Verify**

```bash
make backup
ls -lh ~/backups | tail -2
```

Expected: two fresh tarballs; Qdrant container running again (`docker compose ps`).

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build: add make backup target for memory + qdrant tarballs"
```

---

### Task 4: Loopback by default (server + start script)

Audit findings H1 / QW2 / 1.1. The Docker path is unaffected: `docker-compose.yaml:48` already sets `HOST=0.0.0.0` *inside* the container, where it's correct (port mapping controls exposure).

**Files:**
- Modify: `src/server.py:100–110` (FastMCP constructor) and `src/server.py:1009–1013` (`main()`)
- Modify: `scripts/start-memento.sh:28`
- Create: `tests/test_server_host_default.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_host_default.py`:

```python
"""The server must default to loopback; non-loopback binds must warn loudly."""

import logging


def test_resolve_host_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    from server import _resolve_host

    assert _resolve_host() == "127.0.0.1"


def test_resolve_host_warns_on_public_bind(monkeypatch, caplog):
    monkeypatch.setenv("HOST", "0.0.0.0")
    from server import _resolve_host

    with caplog.at_level(logging.WARNING, logger="server"):
        host = _resolve_host()

    assert host == "0.0.0.0"
    assert any("no authentication" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_host_default.py -v
```

Expected: FAIL — `ImportError: cannot import name '_resolve_host'`.

- [ ] **Step 3: Implement**

In `src/server.py`, immediately above the `mcp = FastMCP(...)` block (line ~100), add:

```python
def _resolve_host() -> str:
    """Default to loopback. Memento has no auth — non-loopback binds are opt-in and loud."""
    host = os.getenv("HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            f"Binding to {host}: Memento has no authentication — "
            "anyone who can reach this interface can read and delete memories."
        )
    return host
```

Change the constructor (currently `host="0.0.0.0", port=8000` at server.py:107–108) to:

```python
mcp = FastMCP(
    "AI Memory & Tools Server",
    lifespan=app_lifespan,
    host=_resolve_host(),
    port=int(os.getenv("PORT", "8000")),
    stateless_http=True,
)
```

Also update the now-wrong comment above it (`# Set host to 0.0.0.0 for Docker container access`) to:

```python
# Host defaults to loopback; Docker sets HOST=0.0.0.0 explicitly (compose line 48).
```

In `main()` (server.py:1012), change `host = os.getenv("HOST", "127.0.0.1")` to `host = _resolve_host()` so both code paths share one resolution + warning.

- [ ] **Step 4: Update the start script**

In `scripts/start-memento.sh`, change line 28 from:

```bash
    HOST=0.0.0.0 \
```

to:

```bash
    HOST="${MEMENTO_HOST:-127.0.0.1}" \
```

- [ ] **Step 5: Run the tests**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_host_default.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Manual smoke test**

```bash
bash scripts/stop-memento.sh
bash scripts/start-memento.sh
curl -sf http://127.0.0.1:8000/health && echo LOOPBACK-OK
```

Expected: `LOOPBACK-OK`, and the cockpit at `http://localhost:3333` still loads data (it calls the API from the browser on the same machine, so loopback is fine).

- [ ] **Step 7: Commit**

```bash
git add src/server.py scripts/start-memento.sh tests/test_server_host_default.py
git commit -m "fix: default server bind to 127.0.0.1; warn loudly on non-loopback (no-auth surface)"
```

---

### Task 5: Input validation — project regex, type enum, bounded numerics

Audit findings H2 / M4 / 1.2.

**Files:**
- Modify: `src/server.py` (helpers at lines 202–213; route bodies listed below)
- Modify: `src/memory/manager.py` (`save()`, line ~245)
- Create: `tests/test_server_validation.py`
- Modify: `tests/test_cleanup.py` or `tests/test_memory.py` (one manager-level test, shown below)

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_server_validation.py`:

```python
"""Request validation: traversal-shaped projects, unknown types, garbage numerics → 400."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def fake_manager(monkeypatch):
    import server

    fake = MagicMock()
    fake.save.return_value = "2026-06-10_note_abc12345"
    fake.recall.return_value = []
    monkeypatch.setattr(server, "_memory_manager_instance", fake)
    return fake


@pytest.fixture
def client():
    from server import mcp

    return TestClient(mcp.streamable_http_app())


def test_save_rejects_path_traversal_project(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "project": "../../etc"})
    assert r.status_code == 400
    fake_manager.save.assert_not_called()


def test_save_rejects_unknown_type(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "type": "banana"})
    assert r.status_code == 400
    fake_manager.save.assert_not_called()


def test_save_accepts_valid_payload(client, fake_manager):
    r = client.post("/api/memory/save", json={"content": "x", "type": "note", "project": "my-app"})
    assert r.status_code == 200


def test_observe_allows_auto_type(client, fake_manager, monkeypatch):
    import tools.builtin.memory as tbm

    monkeypatch.setattr(tbm, "_classify_by_embedding", lambda s, e: "learning")
    r = client.post("/api/memory/observe", json={"summary": "Decided to use X because Y"})
    assert r.status_code == 200


def test_smart_context_rejects_non_integer_limit(client, fake_manager):
    r = client.get("/api/memory/context/smart?limit=abc")
    assert r.status_code == 400


def test_recall_clamps_absurd_limit(client, fake_manager):
    r = client.post("/api/memory/recall", json={"query": "x", "limit": 999999})
    assert r.status_code == 200
    assert fake_manager.recall.call_args.kwargs["limit"] <= 100


def test_kb_rejects_traversal_project(client, fake_manager):
    r = client.get("/api/memory/kb?project=../../secrets")
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failures**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_validation.py -v
```

Expected: traversal/type/limit tests FAIL (today they return 200 or 500); the two happy-path tests may already pass.

- [ ] **Step 3: Replace the numeric helpers and add validation helpers in `src/server.py`**

Add `import re` to the imports at the top (line ~18). Replace `_read_int` and `_read_float` (server.py:202–213) with:

```python
class RequestValidationError(ValueError):
    """Invalid request parameter — mapped to HTTP 400."""


_PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

VALID_MEMORY_TYPES = frozenset(
    {"decision", "learning", "preference", "requirement", "fact", "note", "session", "summary"}
)


def _safe_project(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _PROJECT_RE.match(value):
        raise RequestValidationError(
            "project must be 1-64 characters of letters, digits, dot, dash, underscore"
        )
    return value


def _safe_type(value: str, *, allow_auto: bool = False) -> str:
    if allow_auto and value == "auto":
        return value
    if value not in VALID_MEMORY_TYPES:
        raise RequestValidationError(f"type must be one of {sorted(VALID_MEMORY_TYPES)}")
    return value


def _read_int(query_params, key: str, default: int, lo: int = 1, hi: int = 10000) -> int:
    raw = query_params.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise RequestValidationError(f"{key} must be an integer") from e
    return max(lo, min(value, hi))


def _read_float(query_params, key: str, default: float, lo: float = 0.0, hi: float = 1.0) -> float:
    raw = query_params.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise RequestValidationError(f"{key} must be a number") from e
    return max(lo, min(value, hi))


def _body_int(body: dict, key: str, default: int, lo: int = 0, hi: int = 10000) -> int:
    try:
        value = int(body.get(key, default))
    except (TypeError, ValueError) as e:
        raise RequestValidationError(f"{key} must be an integer") from e
    return max(lo, min(value, hi))
```

- [ ] **Step 4: Wire validation into the route handlers**

Every route below gets ONE new except-arm inserted **before** its generic `except Exception as e:` line:

```python
    except RequestValidationError as e:
        return _bad_request(str(e))
```

(For routes that use inline `JSONResponse` instead of `_bad_request`, the helper still works — it's defined at module level, server.py:245.)

Apply the except-arm plus these specific extraction changes:

| Handler (server.py) | Change |
|---|---|
| `api_save_memory` (:255) | `mem_type = _safe_type(body.get("type", "note"))`; `project = _safe_project(body.get("project"))` |
| `api_recall_memories` (:278) | `limit = _body_int(body, "limit", 5, lo=1, hi=100)`; `project = _safe_project(body.get("project"))`; `mem_type = body.get("type")` → add `if mem_type: mem_type = _safe_type(mem_type)` |
| `api_get_context` (:302) | `project = _safe_project(request.query_params.get("project")) or "general"` |
| `api_smart_context` (:319) | `project = _safe_project(query.get("project"))`; drop the now-redundant `if limit < 1`/`if max_tokens < 100` lines (the helpers clamp); `max_tokens = _read_int(query, "max_tokens", 2000, lo=100, hi=20000)` |
| `api_quick_recall` (:352) | nothing extra — `_read_int`/`_read_float` now validate; keep the `min(..., 3)` |
| `api_get_hierarchical_context` (:398) | `project = _safe_project(query.get("project"))`; drop redundant `< 1` guards |
| `api_memory_graph` (:498) | `project` inside `_parse_graph_filters`: change `filters["project"] = project` to `filters["project"] = _safe_project(project)`; the route's existing `except ValueError` arm already returns 400 (RequestValidationError subclasses ValueError) — no new arm needed |
| `api_cleanup_memories` (:479) | `max_age = body.get("max_age_days_facts")` → `max_age = None if body.get("max_age_days_facts") is None else _body_int(body, "max_age_days_facts", 0, lo=0, hi=36500)` and pass `max_age` through |
| `api_consolidate_memories` (:557) | `project = _safe_project(query.get("project"))`; drop redundant `< 1` guard |
| `api_skill_context` (:591) | `project = _safe_project(query.get("project"))` |
| `api_agent_startup` (:621) | `project = _safe_project(query.get("project"))` |
| `api_resume_packet` (:640) | `project = _safe_project(query.get("project"))` |
| `api_proactive_context_summary` (:658) | `project = _safe_project(query.get("project"))`; drop redundant guard |
| `api_compact_memories` (:685) | `older_than_days = _body_int(body, "older_than_days", 30, lo=1, hi=36500)`; `project = _safe_project(body.get("project"))`; add `if llm_provider not in {"anthropic", "openai"}: raise RequestValidationError("llm_provider must be anthropic or openai")` |
| `api_memory_resume` (:727) | `project = _safe_project(query.get("project"))` |
| `api_lifecycle_backfill` (:743) | `project = _safe_project(body.get("project"))` |
| `api_memory_prune_plan` (:790) | `project = _safe_project(body.get("project"))` (keep the required-check); `limit = _body_int(body, "limit", 200, lo=1, hi=1000)` |
| `api_memory_pressure` (:830) | `project = _safe_project(query.get("project"))` |
| `api_memory_kb` (:874) | `project = _safe_project(query.get("project"))` |
| `api_observe` (:956) | `mem_type = _safe_type(body.get("type", "auto"), allow_auto=True)`; `caller_project = _safe_project(body.get("project"))` |

- [ ] **Step 5: Add the defense-in-depth guard in `manager.save()`**

In `src/memory/manager.py`, inside `save()` right after `project_name = project or scope.project or "general"` (line ~245), add:

```python
            if "/" in project_name or "\\" in project_name or ".." in project_name:
                raise ValueError(f"Invalid project name: {project_name!r}")
```

- [ ] **Step 6: Write the failing manager-level test**

Add to `tests/test_cleanup.py` (it already has `MemoryManager` + `tmp_path` patterns):

```python
class TestProjectNameGuard:
    """save() must refuse path-separator project names regardless of caller."""

    def test_save_rejects_traversal_project(self, tmp_path):
        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid project name"):
            manager.save("content", project="../evil")
        assert not (tmp_path.parent / "evil").exists()
```

(Ensure `import pytest` exists at the top of the file; it does.)

- [ ] **Step 7: Run everything**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_validation.py tests/test_cleanup.py -v
PYTHONPATH=src uv run --extra dev pytest -m "not integration" --tb=short -q
```

Expected: new tests PASS; full non-integration suite green. If any existing test saved a memory with an off-enum type, that's a real finding — extend `VALID_MEMORY_TYPES` only if the type appears in the schema table in `CLAUDE.md`, otherwise fix the test.

- [ ] **Step 8: Commit**

```bash
git add src/server.py src/memory/manager.py tests/test_server_validation.py tests/test_cleanup.py
git commit -m "fix: validate project/type/numeric params on all REST routes; block path traversal in save()"
```

---

### Task 6: `cleanup()` — flat `glob` silently no-ops on nested layout

Audit finding H3 / QW3.

**Files:**
- Modify: `src/memory/manager.py:653`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cleanup.py` in `TestMemoryManagerCleanup`:

```python
    def test_cleanup_prunes_old_facts_in_nested_project_layout(self, tmp_path):
        """v1.5.0+ writes <project>/<date>.yaml — cleanup must find those too."""
        project_dir = tmp_path / "my-app"
        project_dir.mkdir()
        old = {
            "date": "2020-01-01",
            "facts": [
                {
                    "id": "2020-01-01_fact_aaa",
                    "content": "ancient fact",
                    "project": "my-app",
                    "timestamp": "2020-01-01T10:00:00",
                }
            ],
        }
        (project_dir / "2020-01-01.yaml").write_text(yaml.dump(old))

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        stats = manager.cleanup(max_age_days_facts=30)

        assert stats["facts_pruned"] == 1
        assert not (project_dir / "2020-01-01.yaml").exists()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_cleanup.py -k nested_project_layout -v
```

Expected: FAIL — `assert 0 == 1` (flat glob finds nothing).

- [ ] **Step 3: Fix**

In `src/memory/manager.py:653`, change:

```python
            for yaml_file in sorted(self.memory_dir.glob("*.yaml")):
```

to:

```python
            for yaml_file in sorted(self.memory_dir.rglob("*.yaml")):
```

(The existing `file_date.startswith("_")` guard on the next line still skips `_bm25_vocab` etc.)

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_cleanup.py -v
```

Expected: all PASS (including the pre-existing flat-layout tests — `rglob` matches top-level files too).

- [ ] **Step 5: Commit**

```bash
git add src/memory/manager.py tests/test_cleanup.py
git commit -m "fix: cleanup() uses rglob — age-based pruning was a silent no-op on nested project layout"
```

---

### Task 7: `clear_project()` — delete from all three stores

Audit finding H4 / 1.4.

**Files:**
- Modify: `src/memory/manager.py:1366–1370`
- Modify: `src/memory/cli.py:186–187`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cleanup.py`:

```python
class TestClearProject:
    """clear_project() must remove YAML, vectors, and graph nodes — not just vectors."""

    def test_clear_project_removes_yaml_vectors_and_graph(self, tmp_path):
        from unittest.mock import MagicMock

        from memory.manager import MemoryManager

        manager = MemoryManager(memory_dir=tmp_path)
        project_dir = tmp_path / "my-app"
        project_dir.mkdir()
        data = {
            "date": "2026-04-01",
            "facts": [
                {
                    "id": "2026-04-01_fact_aaa",
                    "content": "x",
                    "project": "my-app",
                    "timestamp": "2026-04-01T10:00:00",
                }
            ],
        }
        (project_dir / "2026-04-01.yaml").write_text(yaml.dump(data))
        manager.knowledge_graph.add_node("2026-04-01_fact_aaa", topic="my-app")

        mock_store = MagicMock()
        mock_store.scroll.return_value = [{"memory_id": "2026-04-01_fact_aaa"}]
        manager._store = mock_store

        result = manager.clear_project("my-app")

        assert result["deleted"] == 1
        assert not (project_dir / "2026-04-01.yaml").exists()
        assert "2026-04-01_fact_aaa" not in manager.knowledge_graph._graph
        mock_store.delete.assert_called_with(filters={"project": "my-app"})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_cleanup.py -k clear_project_removes -v
```

Expected: FAIL — current `clear_project` returns `None` (no `["deleted"]`), YAML survives.

- [ ] **Step 3: Implement**

Replace `clear_project` in `src/memory/manager.py:1366–1370` with:

```python
    def clear_project(self, project: str) -> dict[str, int]:
        """Delete all memories for a project from YAML, vector store, AND knowledge graph."""
        with self._telemetry.track("memory.clear_project"):
            points = self.store.scroll(filters={"project": project}, limit=10000)
            ids = [p["memory_id"] for p in points if p.get("memory_id")]
            deleted = sum(1 for memory_id in ids if self.delete(memory_id))

            # Vector points whose YAML was already gone aren't reachable via delete().
            self.store.delete(filters={"project": project})

            # YAML entries that never reached the vector store.
            strays = 0
            project_dir = self.memory_dir / project
            if project_dir.is_dir():
                for yaml_file in list(project_dir.rglob("*.yaml")):
                    data = yaml.safe_load(yaml_file.read_text()) or {}
                    for value in data.values():
                        if isinstance(value, list):
                            for entry in value:
                                if entry.get("id"):
                                    self.knowledge_graph.remove_node(entry["id"])
                                    strays += 1
                    yaml_file.unlink()
                self.knowledge_graph.save()

            logger.info(f"Cleared project {project}: {deleted} deleted, {strays} stray YAML entries")
            return {"deleted": deleted, "strays_removed": strays}
```

- [ ] **Step 4: Surface counts in the CLI**

In `src/memory/cli.py`, change the `clear` command body (lines 186–187) from:

```python
    mgr.clear_project(project)
    click.echo(f"✓ Cleared memories for: {project}")
```

to:

```python
    result = mgr.clear_project(project)
    click.echo(
        f"✓ Cleared {result['deleted']} memories for: {project}"
        f" ({result['strays_removed']} stray YAML entries removed)"
    )
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_cleanup.py tests/test_memory_cli.py -v
```

Expected: PASS. Note `tests/test_memory_cli.py:261–268` mocks `clear_project` with a `MagicMock` — its return value supports `['deleted']` subscripting only if the mock is unconfigured `MagicMock` (it is — `MagicMock()[...]` works via `__getitem__`? **No** — plain `MagicMock` does not support subscripting). If `test_clear_with_confirmation` fails with `TypeError: 'MagicMock' object is not subscriptable`, configure the mock in that test: `mock_memory_manager.clear_project.return_value = {"deleted": 0, "strays_removed": 0}`.

- [ ] **Step 6: Commit**

```bash
git add src/memory/manager.py src/memory/cli.py tests/test_cleanup.py tests/test_memory_cli.py
git commit -m "fix: clear_project() deletes from YAML + graph + vectors, returns counts (was vectors-only)"
```

---

### Task 8: `api_observe` — reuse the manager's embedder

Audit finding H5 (first half) / QW4.

**Files:**
- Modify: `src/server.py:974–982`
- Test: `tests/test_server_validation.py` (same fixtures)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server_validation.py`:

```python
def test_observe_uses_manager_embedder_for_auto_classification(client, fake_manager, monkeypatch):
    """api_observe must reuse manager.embedder, not construct a fresh model per request."""
    import tools.builtin.memory as tbm

    captured = {}

    def fake_classify(summary, embedder):
        captured["embedder"] = embedder
        return "learning"

    monkeypatch.setattr(tbm, "_classify_by_embedding", fake_classify)

    r = client.post("/api/memory/observe", json={"summary": "Fixed the bug because of X"})

    assert r.status_code == 200
    assert captured["embedder"] is fake_manager.embedder
```

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_validation.py -k manager_embedder -v
```

Expected: FAIL — `KeyError: 'embedder'`. (Today the handler constructs a real `Embedder()` at server.py:979; loading the actual model makes `_classify_by_embedding` get a *different* embedder, or the construction itself errors into the keyword fallback — either way `captured` stays empty.)

- [ ] **Step 3: Implement**

In `src/server.py` `api_observe`, replace the auto-classification block (lines 974–982):

```python
        if mem_type == "auto":
            from core import Embedder
            from tools.builtin.memory import _classify_by_embedding, _classify_by_keywords

            try:
                embedder = Embedder()
                mem_type = _classify_by_embedding(summary, embedder)
            except Exception:
                mem_type = _classify_by_keywords(summary)
```

with:

```python
        if mem_type == "auto":
            from tools.builtin.memory import _classify_by_embedding, _classify_by_keywords

            try:
                mem_type = _classify_by_embedding(summary, manager.embedder)
            except Exception:
                mem_type = _classify_by_keywords(summary)
```

(`manager = _get_memory_manager()` already executes above this block at server.py:972, and `MemoryManager.embedder` is a cached lazy property — `manager.py:199–204`.)

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_server_validation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_server_validation.py
git commit -m "perf: api_observe reuses manager.embedder instead of constructing a model per request"
```

---

### Task 9: Hybrid search must honor `score_threshold`

Audit finding M2 / 1.5. RRF-fused scores are rank-based and incomparable to cosine thresholds, so the honest fix is to apply the threshold to the **dense prefetch** (cosine space) and document that sparse/BM25 candidates are exempt by design.

**Files:**
- Modify: `src/core/vector_store.py:307–335`
- Create: `tests/test_hybrid_threshold.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_hybrid_threshold.py`:

```python
"""Hybrid (RRF) search must not silently drop the caller's score_threshold."""

from unittest.mock import MagicMock

from core.vector_store import VectorStore


class FakeSparseEncoder:
    def encode(self, text: str) -> dict[int, float]:
        return {1: 0.5, 7: 0.25}


def test_hybrid_search_passes_threshold_to_dense_prefetch():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.9, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    dense_prefetch = kwargs["prefetch"][0]
    assert dense_prefetch.score_threshold == 0.9


def test_hybrid_search_omits_threshold_when_zero():
    store = VectorStore(collection="t", sparse_encoder=FakeSparseEncoder())
    store._client = MagicMock()
    store._client.query_points.return_value.points = []

    store.search(vector=[0.1] * 384, limit=5, score_threshold=0.0, query_text="TOPE-123")

    kwargs = store._client.query_points.call_args.kwargs
    assert kwargs["prefetch"][0].score_threshold is None
```

(Setting `store._client` directly bypasses `_connect`, so no Qdrant is needed.)

- [ ] **Step 2: Run it to verify it fails**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_hybrid_threshold.py -v
```

Expected: FAIL — `Prefetch` currently has `score_threshold=None` (never passed).

- [ ] **Step 3: Implement**

In `src/core/vector_store.py`, in the hybrid branch (line ~313), change the dense `Prefetch`:

```python
                            Prefetch(
                                query=vector,
                                using="",
                                limit=prefetch_limit,
                                filter=query_filter,
                            ),
```

to:

```python
                            Prefetch(
                                query=vector,
                                using="",
                                limit=prefetch_limit,
                                filter=query_filter,
                                # RRF-fused scores are rank-based; cosine thresholds only
                                # make sense on the dense candidate set.
                                score_threshold=score_threshold or None,
                            ),
```

Also extend the `search()` docstring's `score_threshold` arg description (line ~290) to read: `score_threshold: Minimum similarity (0-1). In hybrid mode this gates the dense candidates; BM25 candidates are exempt (RRF scores are rank-based).`

If `qdrant_client.http.models.Prefetch` rejects `score_threshold` (older client), this is a dependency floor problem — bump `qdrant-client` in `pyproject.toml` to a version whose `Prefetch` supports it and re-run `uv sync`; do not work around it by post-filtering RRF scores.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=src uv run --extra dev pytest tests/test_hybrid_threshold.py tests/test_hybrid_search.py -v
```

Expected: PASS (test_hybrid_search needs the :6334 Qdrant from Preflight if it's integration-marked).

- [ ] **Step 5: Commit**

```bash
git add src/core/vector_store.py tests/test_hybrid_threshold.py
git commit -m "fix: hybrid search applies score_threshold to dense prefetch (was silently dropped)"
```

---

### Task 10: Documentation + compose sync

Audit findings M7 / QW5.

**Files:**
- Delete: `docker-compose.yml` (15-line stale stub; `docker-compose.yaml` is canonical)
- Modify: `docker-compose.yaml:20` and `:106` (pin image)
- Modify: `README.md:105` (ranking weights), README REST table (~line 307–327), README/SETUP MCP URL
- Modify: `docs/SETUP.md:39–44`

- [ ] **Step 1: Delete the stale compose stub and pin Qdrant**

```bash
git rm docker-compose.yml
```

In `docker-compose.yaml`, change **both** occurrences (lines 20 and 106) of:

```yaml
    image: qdrant/qdrant:latest
```

to:

```yaml
    image: qdrant/qdrant:v1.13.4
```

(Must match the CI service image from Task 2. If the running production container is older, note it to the user — do NOT restart/upgrade production Qdrant without asking.)

- [ ] **Step 2: Fix the ranking-weights doc drift**

In `README.md:105`, replace:

```
3. RANK    - Composite: vector(50%) + importance(20%) + recency(15%) + proximity(15%)
```

with the actual weights from `src/memory/manager.py:827–833`:

```
3. RANK    - Composite: vector(40%) + importance(20%) + proximity(15%) + tier(15%) + recency(10%)
```

- [ ] **Step 3: Determine the real MCP endpoint URL, then align both docs**

With the backend running (Task 4 Step 6 left it up):

```bash
curl -s -o /dev/null -w "/ -> %{http_code}\n"    -X POST http://localhost:8000/    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
curl -s -o /dev/null -w "/mcp -> %{http_code}\n" -X POST http://localhost:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
```

Whichever path returns 200 is canonical (`src/server.py:1040` mounts the MCP endpoint at `/`, so expect `/` to win; README:27 currently says `/mcp`). Update **both**:
- `README.md:27` → `claude mcp add --transport http --url http://localhost:8000<canonical-path> memory`
- `docs/SETUP.md:39` (currently `claude mcp add --transport http memory http://localhost:8000`) and the `claude mcp list` example at `docs/SETUP.md:44` → same canonical URL.

- [ ] **Step 4: Complete the README REST table**

In the table at `README.md:307–327`, add these missing rows (after the `/api/memory/context/hierarchy` row to keep grouping):

```markdown
| `/api/memory/context/smart` | GET | Token-capped smart context (`?limit=&max_tokens=`) |
| `/api/memory/recall/quick` | GET | Fast high-threshold recall for per-prompt injection |
| `/api/memory/context/skills` | GET | Inferred skill context from memory clusters |
| `/api/memory/context/startup` | GET | Unified agent startup payload |
| `/api/memory/compact` | POST | LLM-summarize old memories (dry-run by default) |
```

- [ ] **Step 5: Cross-check the table against reality**

```bash
grep -o 'custom_route("[^"]*"' src/server.py | sort -u
```

Every printed path (except the duplicate `/api/memory/context/resume`, which is slated for removal in audit task 2.5) must appear in the README table. Add any still missing.

- [ ] **Step 6: Run pre-commit (docs touch YAML/whitespace hooks) and commit**

```bash
uv run --extra dev pre-commit run --all-files
git add README.md docs/SETUP.md docker-compose.yaml
git commit -m "docs: sync REST table + ranking weights + MCP URL; pin qdrant image; drop stale docker-compose.yml"
```

---

### Final verification (after all tasks)

- [ ] Full gate, exactly as CI will run it:

```bash
uv run --extra dev pre-commit run --all-files
QDRANT_URL=http://localhost:6334 PYTHONPATH=src uv run pytest -m integration --tb=short -q
cd ui && npm run lint && npm test && cd ..
bash tests/verify_test_isolation.sh
```

- [ ] Manual smoke: `bash scripts/start-memento.sh`, confirm `curl http://127.0.0.1:8000/health` is healthy, cockpit loads, and `curl -X POST http://127.0.0.1:8000/api/memory/save -H 'Content-Type: application/json' -d '{"content":"x","project":"../etc"}'` returns **400**.

---

## Self-review notes

- **Spec coverage:** C1→Task 1; H6→Task 2; 0.3→Task 3; H1/QW2→Task 4; H2+M4→Task 5; H3/QW3→Task 6; H4→Task 7; H5(observe half)/QW4→Task 8; M2→Task 9; M7/QW5→Task 10. *Not covered (deliberately, Milestone 2 scope):* H5's event-loop blocking (audit 2.1), M1 N+1 (2.2), M3 graph writes on recall (2.3), config merge (2.4), endpoint consolidation (2.5).
- **Known risk points called out inline:** `Prefetch.score_threshold` client-version floor (Task 9 Step 3), CLI mock subscripting (Task 7 Step 5), off-enum types in legacy tests (Task 5 Step 7), `npm test` watch mode (Task 2 Step 2).
- **Type consistency:** `RequestValidationError` subclasses `ValueError` so the graph route's existing `except ValueError → 400` keeps working; `clear_project` return shape `{"deleted", "strays_removed"}` is used consistently in manager, CLI, and tests.
