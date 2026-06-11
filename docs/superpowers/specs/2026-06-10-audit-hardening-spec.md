# Audit Hardening Spec — Milestone 0 + Quick Wins + Critical Fixes

> Source of truth for what "done" means. Derived from `docs/audits/2026-06-10-repo-audit.md`.
> Implementation plan: `docs/superpowers/plans/2026-06-10-audit-hardening.md`.

## Goal

Close every Critical and High finding from the 2026-06-10 audit so the repo stops violating its own documented rules: tests isolated from production data, CI-enforced gates, closed-by-default network surface, loud failures instead of silent no-ops.

## Scope

**In:** test isolation (C1), CI (H6), backup target (0.3), loopback default (H1), input validation + path traversal (H2/M4), `cleanup()` rglob (H3), `clear_project()` three-store delete (H4), per-request embedder (H5, observe half), hybrid `score_threshold` (M2), doc/compose sync (M7/QW5).

**Out (Milestone 2+, separate spec):** event-loop de-blocking (`asyncio.to_thread`), N+1 recall fix + `memory_id` index, read-only recall, config-system merge, endpoint consolidation, UI resume schema.

## Functional Requirements

| ID | Requirement | Acceptance criterion (testable) |
|----|-------------|--------------------------------|
| FR1 | No test may reach production Qdrant (:6333) | Autouse fixture forces `QDRANT_URL=:6334`; a `VectorStore` pointed at `:6333` inside pytest raises `RuntimeError`; `tests/test_qdrant_isolation.py` passes; `tests/verify_test_isolation.sh` passes |
| FR2 | Tests needing a real Qdrant are explicitly marked | `pytest -m "not integration"` passes with no Qdrant running; `pytest -m integration` passes with qdrant-test on :6334 |
| FR3 | CI gates every PR | `.github/workflows/ci.yml` runs pre-commit (lint/types/unit tests), integration tests vs a Qdrant service container, and UI lint+test; all jobs green on the PR |
| FR4 | One-command backup | `make backup` produces dated `~/backups/pre-<TS>-{memory,qdrant}.tar.gz` and leaves Qdrant running |
| FR5 | Server binds loopback by default | Fresh `start-memento.sh` serves on 127.0.0.1; `HOST`/`MEMENTO_HOST` override exists; non-loopback bind logs a warning containing "no authentication"; Docker path unchanged (compose sets `HOST=0.0.0.0` in-container) |
| FR6 | Caller-supplied `project` is validated everywhere | `project` matching `^[A-Za-z0-9._-]{1,64}$` accepted; traversal-shaped values → HTTP 400 on every REST route that accepts `project`; `manager.save()` independently rejects `/`, `\`, `..` with `ValueError` |
| FR7 | `type` is enum-validated at the API boundary | Allowed: `decision, learning, preference, requirement, fact, note, session, summary` (+ `auto` for observe only); anything else → 400 |
| FR8 | Numeric params are bounded and well-typed | Non-integer `limit`/`max_tokens`/etc. → 400 (not 500); absurd values clamped (e.g. recall limit ≤ 100) |
| FR9 | `cleanup()` works on the nested YAML layout | Age-based fact pruning deletes facts in `<project>/<date>.yaml`; regression test proves `facts_pruned ≥ 1` on a nested fixture |
| FR10 | `clear_project()` clears all three stores | After clearing: project YAML files gone, graph nodes gone, `store.delete(filters={"project": ...})` called; returns `{"deleted": int, "strays_removed": int}`; CLI echoes counts |
| FR11 | Observe reuses the manager's embedder | `api_observe` auto-classification calls `_classify_by_embedding(summary, manager.embedder)`; no `Embedder()` construction inside the handler |
| FR12 | Hybrid search honors `score_threshold` | Threshold is passed to the dense `Prefetch` (`score_threshold=value or None`); unit test asserts it via mocked client; docstring documents that BM25 candidates are exempt (RRF is rank-based) |
| FR13 | Docs match code | README ranking weights = 40/20/15/15/10 (matching `manager.py:827–833`); README REST table covers all live routes; README + SETUP.md agree on the verified MCP URL; `docker-compose.yml` stub deleted; qdrant image pinned to the same tag in compose and CI |

## Non-Functional Requirements

- **NFR1 — No behavior change beyond the listed fixes.** Existing green tests stay green (except those updated explicitly per the plan: conftest fixture, CLI clear mock, integration markers).
- **NFR2 — TDD.** Every code fix lands with a test that failed before the fix (doc-only and CI-config changes exempt).
- **NFR3 — Repo rules hold.** No pushes to main, no `--no-verify`, pre-commit passes on every commit, conventional commit messages, one logical change per commit.
- **NFR4 — Production safety.** No restart/upgrade of the production Qdrant container; backup taken before any work (`make backup` or the Preflight tarballs).

## Execution Model (agreed with JR, 2026-06-10)

- Implementation runs as a **task loop**: one Workflow per plan task, executed sequentially (tasks share `src/server.py`, `tests/test_cleanup.py` — no parallel writes).
- **Implementer agents are cheap models (haiku)** — they follow the plan's bite-sized steps verbatim; the plan contains complete code so no design judgment is needed.
- **Review is Fable-only**: after each task's workflow completes, Fable (main session) reviews the diff against this spec + the plan, runs the gates, and either accepts (next task) or dispatches a bounded fix-up (max 2 retries per task; after that Fable stops and reports).
- Gate between tasks: `pytest -m "not integration"` green + the task's own commands green + diff matches the plan's stated Files list (no scope creep).

## Done

All FR acceptance criteria pass; final verification block of the plan passes end-to-end; branch is PR-ready with one commit per task.
