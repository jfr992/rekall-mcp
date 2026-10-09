# Measurable Memory (sub-project A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Rekall write and recall carries caller provenance, every delivered memory is traceable by id, subagents stop receiving the startup capsule, and the session summary records delivered vs referenced ids without inflating reinforcement credit.

**Architecture:** Server-side changes in the MCP tool layer, renderers, the events route, the sessions fold and the utility report. Client-side changes in three shell hooks (startup capsule, session end, a new provenance hook) and the Codex adapter. No UI, no mod, no schema bump: all new record fields already exist on `MemoryScope`/`manager.save`, and new event payload fields are optional.

**Tech Stack:** Python 3.11 (FastMCP, Starlette, pytest), bash 3.2-compatible shell hooks with `jq` and `python3`, `uv run --extra dev pytest`.

**Spec:** `docs/superpowers/specs/2026-10-09-measurable-memory-design.md`

## Global Constraints

- Branch `feat/measurable-memory-a`, off `main`. Never push to main. Never `--no-verify`.
- Run tests with `uv run --extra dev pytest <path> -v`. If uv's cache is sandbox-blocked, prefix `UV_CACHE_DIR=$TMPDIR/uv-cache`.
- Do not edit `tests/test_software_evals.py`.
- Hooks: bash 3.2 compatible (no associative arrays, no `mapfile`), every failure path exits 0, bounded network (`--connect-timeout 0.1 --max-time 1`), kill switch `REKALL_AUTOSAVE=0` honored, never set `permissionDecision`.
- Hook tests use fake `curl` on `PATH` (pattern in `tests/test_hooks_session.py`), never the real backend.
- Memory id regex everywhere: `\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+`.
- The MCP server is registered as `memory` on this machine; hook matchers must cover `mcp__memory__.*` and `mcp__rekall__.*`.
- No `asyncio.run()` inside sync code called from async routes.
- Comments: one line, why not what. No essay comments.
- Commit after every task with a conventional-commit message and the `Co-Authored-By: Claude <noreply@anthropic.com>` trailer.

## Review Focus

1. Hook payload carries `agent_id` with an empty string value: treat empty as "not a subagent". Test in Task 1.
2. Model already passed `cwd` or `session_id` to a Rekall tool: the provenance hook must not overwrite it. Test in Task 4.
3. A Rekall tool outside the allowlist (`close_loop`, `memory_doctor`): the provenance hook must emit nothing, not an empty `updatedInput`. Test in Task 4.
4. A memory id appearing only inside a `tool_result` block after delivery is exposure, not a reference. Test in Task 5.
5. Transcript tail truncated at `REKALL_TRANSCRIPT_TAIL_BYTES`: summary must report `coverage.truncated: true`. Test in Task 5.
6. Capsule render truncation at 3500 chars must not cut an id in half: truncate content before appending the id. Test in Task 3.

---

### Task 0: Spike, `updatedInput` reaches an MCP tool

**Files:**
- Create: `$TMPDIR/spike-settings.json` (throwaway, not committed)
- Create: `$TMPDIR/spike-hook.sh` (throwaway)
- Record result in: `docs/superpowers/plans/2026-10-09-measurable-memory.md` (this file, the "Spike result" line under this task)

**Interfaces:**
- Produces: a yes/no on whether Claude Code delivers `hookSpecificOutput.updatedInput` to an MCP tool call. Task 4 depends on yes. If no, Task 4 is replaced by a Claude Code mod `tool.call` rewrite with the same allowlist (out of this plan; stop and report).

- [ ] **Step 1: Write the throwaway hook**

```bash
cat > "$TMPDIR/spike-hook.sh" <<'EOF'
#!/usr/bin/env bash
payload="$(cat)"
tool_input="$(jq -c '.tool_input' <<<"$payload")"
jq -cn --argjson ti "$tool_input" '{hookSpecificOutput:{hookEventName:"PreToolUse",updatedInput:($ti + {session_id:"spike-updatedinput-1", cwd:"/tmp/spike-cwd"})}}'
EOF
chmod +x "$TMPDIR/spike-hook.sh"
cat > "$TMPDIR/spike-settings.json" <<EOF
{"hooks":{"PreToolUse":[{"matcher":"mcp__memory__recall_memories","hooks":[{"type":"command","command":"$TMPDIR/spike-hook.sh"}]}]}}
EOF
```

- [ ] **Step 2: Run one headless call that invokes the tool**

Run (outside the sandbox, the backend is on localhost):
```bash
claude -p --settings "$TMPDIR/spike-settings.json" --max-turns 3 \
  "Call the recall_memories tool once with query 'spike updatedInput' and limit 1, then reply DONE."
```
Expected: the model calls the tool and replies.

- [ ] **Step 3: Check the backend saw the injected session id**

Run:
```bash
curl -s "localhost:8000/api/memory/events?limit=50" \
  | python3 -c 'import json,sys; ev=json.load(sys.stdin); ev=ev.get("events") or ev; print([e["payload"].get("session_id") for e in ev if e.get("event_type")=="memory_recalled"][-5:])'
```
Expected: `spike-updatedinput-1` present. If present: spike passes. If absent after two tries: spike fails; stop and report before Task 4.

- [ ] **Step 4: Record the result**

Add one line under this task: `Spike result (YYYY-MM-DD): PASS|FAIL, <one line of evidence>`. Commit:
```bash
git add docs/superpowers/plans/2026-10-09-measurable-memory.md
git commit -m "docs: record updatedInput spike result"
```

Spike result (2026-10-09): PASS, `memory_recalled` event carried `session_id: spike-updatedinput-1` after a `claude -p --settings` run with a PreToolUse hook on `mcp__memory__recall_memories`.

---

### Task 1: Subagent guard in the startup capsule hook

**Files:**
- Modify: `claude/hooks/session-start-memory.sh:10-13`
- Test: `tests/test_claude_startup_hook.py`

**Interfaces:**
- Consumes: hook stdin JSON; documented field `agent_id` is present only inside subagent hook calls.
- Produces: nothing new. Behavior: exit 0 with no output when `agent_id` is a non-empty string.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_startup_hook.py`:

```python
def test_session_start_hook_skips_subagents(tmp_path):
    result, calls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp", "session_id": "s1", "agent_id": "a1b2c3"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert calls == []


def test_session_start_hook_treats_empty_agent_id_as_main_session(tmp_path):
    result, calls = _run_hook(
        tmp_path,
        {"cwd": "/workspaces/rekall-mcp", "session_id": "s1", "agent_id": ""},
    )
    assert result.returncode == 0
    assert "REKALL STARTUP" in result.stdout
    assert any("/api/memory/capsule" in c for c in calls)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --extra dev pytest tests/test_claude_startup_hook.py -k "skips_subagents or empty_agent_id" -v`
Expected: `test_session_start_hook_skips_subagents` FAILS (stdout contains `REKALL STARTUP`, calls non-empty). The second passes already.

- [ ] **Step 3: Add the guard**

In `claude/hooks/session-start-memory.sh`, right after `INPUT="$(cat || true)"` (line 13), insert:

```bash
# Subagent hooks carry agent_id; the capsule is for the main session only.
AGENT_ID="$(
  printf '%s' "$INPUT" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("agent_id") or "")' \
      2>/dev/null \
    || true
)"
[[ -n "$AGENT_ID" ]] && exit 0
```

- [ ] **Step 4: Run the whole hook test file**

Run: `uv run --extra dev pytest tests/test_claude_startup_hook.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add claude/hooks/session-start-memory.sh tests/test_claude_startup_hook.py
git commit -m "fix(hooks): skip startup capsule inside subagents"
```

---

### Task 2: Provenance parameters on `observe` and `save_memory`

**Files:**
- Modify: `src/tools/builtin/memory.py:480-482` (`_get_current_scope`), `:489-537` (`observe`), `:662-690` (`save_memory`), `:541-592` (`recall_memories`, add `agent`)
- Test: `tests/test_tools_provenance.py` (new)

**Interfaces:**
- Consumes: `ScopeDetector.detect(*, project, cwd, agent, trust_boundary, session_id)` (`src/memory/scope.py:105`); `manager.save(..., session_id=, cwd=, **metadata)` (`src/memory/manager.py:436`); `manager.observe(summary, type, project, scope, context, **metadata)` which forwards `**metadata` into `save`.
- Produces: tool signatures
  - `observe(summary, type="auto", context=None, project=None, cwd=None, session_id=None, agent=None)`
  - `save_memory(content, memory_type="note", project=None, context=None, cwd=None, session_id=None, agent=None)`
  - `recall_memories(..., cwd=None, session_id=None, agent=None)`
  - `OptimizedMemoryTools._get_current_scope(project=None, **scope_kwargs)` passing only non-None kwargs to `ScopeDetector.detect`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_provenance.py`:

```python
"""MCP write tools carry caller provenance (spec 2026-10-09, section 2)."""

import subprocess
from unittest.mock import MagicMock

import pytest


def _bind(provider, tool_registry):
    capture_tool, registered_tools = tool_registry

    class FakeMCP:
        def tool(self, **kwargs):
            return capture_tool()

    provider.register(FakeMCP())
    return registered_tools


def _provider(manager):
    from tools.builtin.memory import OptimizedMemoryTools

    provider = OptimizedMemoryTools()
    provider._manager = manager
    return provider


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "caller-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    from memory.scope import ScopeDetector

    ScopeDetector.clear_cache()
    yield repo
    ScopeDetector.clear_cache()


@pytest.mark.asyncio
async def test_save_memory_resolves_project_from_caller_cwd(tool_registry, git_repo):
    manager = MagicMock()
    manager.save.return_value = "2026-10-09_note_abcd1234"
    tools = _bind(_provider(manager), tool_registry)

    await tools["save_memory"](
        content="x", cwd=str(git_repo), session_id="sess-1", agent="codex"
    )

    kw = manager.save.call_args.kwargs
    assert kw["project"] == "caller-repo"
    assert kw["scope"].project == "caller-repo"
    assert kw["scope"].agent == "codex"
    assert kw["cwd"] == str(git_repo)
    assert kw["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_observe_resolves_project_from_caller_cwd(tool_registry, git_repo, monkeypatch):
    monkeypatch.setattr("tools.builtin.memory._classify_smart", lambda *a, **k: "fact")
    manager = MagicMock()
    manager.observe.return_value = "2026-10-09_fact_abcd1234"
    tools = _bind(_provider(manager), tool_registry)

    await tools["observe"](summary="x", cwd=str(git_repo), session_id="sess-2", agent="codex")

    kw = manager.observe.call_args.kwargs
    assert kw["project"] == "caller-repo"
    assert kw["scope"].agent == "codex"
    assert kw["cwd"] == str(git_repo)
    assert kw["session_id"] == "sess-2"


@pytest.mark.asyncio
async def test_observe_accepts_explicit_project(tool_registry, git_repo, monkeypatch):
    monkeypatch.setattr("tools.builtin.memory._classify_smart", lambda *a, **k: "fact")
    manager = MagicMock()
    tools = _bind(_provider(manager), tool_registry)

    await tools["observe"](summary="x", project="explicit-proj", cwd=str(git_repo))

    assert manager.observe.call_args.kwargs["project"] == "explicit-proj"


@pytest.mark.asyncio
async def test_save_memory_without_provenance_passes_no_scope_kwargs(tool_registry):
    """Old tests mock the helper with a one-arg lambda; omitted fields must not reach it."""
    manager = MagicMock()
    provider = _provider(manager)
    scope = MagicMock()
    scope.project = "fallback"
    calls = []

    def fake_scope(project=None, **kw):
        calls.append(kw)
        return scope

    provider._get_current_scope = fake_scope
    tools = _bind(provider, tool_registry)

    await tools["save_memory"](content="x")

    assert calls == [{}]
    kw = manager.save.call_args.kwargs
    assert kw["project"] == "fallback"
    assert kw["cwd"] is None
    assert kw["session_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_tools_provenance.py -v`
Expected: FAIL with `TypeError: ... got an unexpected keyword argument 'cwd'` on the first three; the last fails on `kw["cwd"]` missing.

- [ ] **Step 3: Implement**

In `src/tools/builtin/memory.py` replace `_get_current_scope`:

```python
    def _get_current_scope(self, project: str | None = None, **scope_kwargs):
        """Caller-supplied cwd/agent/session win; never fall back to the backend cwd silently."""
        provided = {k: v for k, v in scope_kwargs.items() if v is not None}
        return ScopeDetector.detect(project=project, **provided)
```

Change `observe`'s signature and body:

```python
        async def observe(
            summary: str,
            type: str = "auto",
            context: str | None = None,
            project: str | None = None,
            cwd: str | None = None,
            session_id: str | None = None,
            agent: str | None = None,
        ) -> str:
```
Add to its docstring `Args`:
```
                project: Your project name; pass it when cwd is unavailable
                cwd: Your working directory, so the memory lands in the right project
                session_id: Your session id, for attribution
                agent: Your agent name (claude-code, codex)
```
Replace `scope = self._get_current_scope()` with:
```python
            scope = self._get_current_scope(
                project=project, cwd=cwd, agent=agent, session_id=session_id
            )
```
and add `cwd=cwd, session_id=session_id,` to the `self.manager.observe(...)` call.

Change `save_memory`'s signature to add `cwd: str | None = None, session_id: str | None = None, agent: str | None = None`, the same three docstring lines, and:
```python
            scope = self._get_current_scope(
                project=project, cwd=cwd, agent=agent, session_id=session_id
            )
```
then add `cwd=cwd, session_id=session_id,` to `self.manager.save(...)`.

Change `recall_memories`: add `agent: str | None = None` after `session_id`, docstring line `agent: Your agent name (claude-code, codex)`, and pass `agent=agent` into `self.manager.recall_formatted(...)`. In `src/memory/manager.py` add `agent: str | None = None` to `recall_formatted` and forward it to `self.recall(...)` only if `recall` already accepts `agent`; if it does not, accept and ignore it in `recall_formatted` with the comment `# agent is attribution-only today; recall events carry it via session_id join`.

- [ ] **Step 4: Verify `manager.observe` forwards the new kwargs**

Run: `grep -n "self.save(" src/memory/manager.py | head -3` and read the `observe` body. Confirm `**metadata` reaches `self.save(...)`. If `observe` builds the save call with explicit kwargs instead, add `session_id=metadata.pop("session_id", None), cwd=metadata.pop("cwd", None)` to that call.

- [ ] **Step 5: Run tests**

Run: `uv run --extra dev pytest tests/test_tools_provenance.py tests/test_close_loop.py tests/test_cross_project_recall.py -v`
Expected: all PASS (close_loop's one-arg lambda still works because no extra kwargs are passed when all are None).

- [ ] **Step 6: Commit**

```bash
git add src/tools/builtin/memory.py src/memory/manager.py tests/test_tools_provenance.py
git commit -m "feat(mcp): observe and save_memory accept caller cwd, session_id, agent"
```

---

### Task 3: Printed memory ids in recall and capsule output

**Files:**
- Modify: `src/memory/manager.py:1999-2002` (`_line` inside `_format_with_guidance`)
- Modify: `src/memory/capsules.py:146-162` (`render_project_capsule`)
- Modify: `claude/hooks/session-start-memory.sh:55-61` (`_item_text`) and the `text = _render_capsule(payload)[:3500]` line
- Test: `tests/test_memory.py`, `tests/test_capsules.py`, `tests/test_claude_startup_hook.py`

**Interfaces:**
- Produces: bullet formats
  - recall: `- {content} ({date}) [{memory_id}]`
  - capsule (server and hook): `- [{date}] {content} [{memory_id}]`
  - Task 5 relies on these ids being present in `tool_result` text and in the capsule `additionalContext`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory.py` (find the existing `_format_with_guidance` test for the import pattern, reuse its manager fixture; if none, construct `MemoryManager.__new__(MemoryManager)` and call the method unbound):

```python
def test_format_with_guidance_prints_memory_id():
    from memory.manager import MemoryManager

    mgr = MemoryManager.__new__(MemoryManager)
    out = mgr._format_with_guidance(
        [{"memory_id": "2026-10-09_fact_ab12cd34", "content": "port is 8000", "type": "fact", "date": "2026-10-09"}]
    )
    assert "- port is 8000 (2026-10-09) [2026-10-09_fact_ab12cd34]" in out


def test_format_with_guidance_outdated_line_keeps_id():
    from memory.manager import MemoryManager

    mgr = MemoryManager.__new__(MemoryManager)
    out = mgr._format_with_guidance(
        [{"memory_id": "2026-10-09_fact_ab12cd34", "content": "old", "type": "fact", "date": "2026-10-09", "_outdated": True}]
    )
    assert "[2026-10-09_fact_ab12cd34]" in out
```

Append to `tests/test_capsules.py`:

```python
def test_render_project_capsule_prints_memory_id():
    from memory.capsules import render_project_capsule

    text = render_project_capsule(
        {
            "project": "p",
            "standing_context": [
                {"memory_id": "2026-10-09_decision_ab12cd34", "date": "2026-10-09", "content": "use uv"}
            ],
            "danger_zones": [],
            "open_loops": [],
        }
    )
    assert "- [2026-10-09] use uv [2026-10-09_decision_ab12cd34]" in text


def test_render_project_capsule_truncation_keeps_last_id_whole():
    from memory.capsules import _MAX_RENDER_CHARS, render_project_capsule

    long = "x" * _MAX_RENDER_CHARS
    text = render_project_capsule(
        {
            "project": "p",
            "standing_context": [
                {"memory_id": "2026-10-09_decision_ab12cd34", "date": "2026-10-09", "content": long}
            ],
            "danger_zones": [],
            "open_loops": [],
        }
    )
    assert len(text) <= _MAX_RENDER_CHARS
    assert text.rstrip().endswith("[2026-10-09_decision_ab12cd34]")
```

In `tests/test_claude_startup_hook.py`, change the fake curl capsule JSON (inside `_fake_curl`) to include an id:
```
printf '{"project":"rekall-mcp","danger_zones":[{"memory_id":"2026-07-03_learning_ab12cd34","date":"2026-07-03","content":"Back up live files before touching Claude hooks."}]}'
```
and append:
```python
def test_session_start_hook_prints_memory_ids(tmp_path):
    result, _ = _run_hook(tmp_path, {"cwd": "/workspaces/rekall-mcp", "session_id": "s1"})
    assert "[2026-07-03_learning_ab12cd34]" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_memory.py tests/test_capsules.py tests/test_claude_startup_hook.py -k "memory_id or last_id or prints_memory" -v`
Expected: all five FAIL on missing `[...]` suffix.

- [ ] **Step 3: Implement the recall line**

`src/memory/manager.py`, replace `_line`:

```python
        def _line(m: dict) -> str:
            mid = m.get("memory_id") or m.get("id") or ""
            tag = f" [{mid}]" if mid else ""
            if m.get("_outdated"):
                return f"- [outdated — replaced by the newer entry above]{tag}"
            return f"- {m['content']} ({m.get('date', 'unknown date')}){tag}"
```

- [ ] **Step 4: Implement the server capsule renderer**

`src/memory/capsules.py`, replace the body of `render_project_capsule`:

```python
def render_project_capsule(capsule: dict[str, Any]) -> str:
    lines = [f"# Project Capsule: {capsule['project']}", ""]
    budget = _MAX_RENDER_CHARS - 40  # headroom so the final id is never cut
    used = sum(len(line) + 1 for line in lines)

    sections = [
        ("Standing Context", "standing_context"),
        ("Danger Zones", "danger_zones"),
        ("Open Loops", "open_loops"),
    ]
    for title, key in sections:
        items = capsule.get(key) or []
        if not items:
            continue
        lines.append(f"## {title}")
        used += len(title) + 4
        for item in items:
            tag = f" [{item['memory_id']}]" if item.get("memory_id") else ""
            head = f"- [{item.get('date', 'unknown')}] "
            room = budget - used - len(head) - len(tag)
            if room <= 0:
                break
            content = str(item.get("content", ""))
            if len(content) > room:
                content = content[: max(room - 3, 0)].rstrip() + "..."
            line = f"{head}{content}{tag}"
            lines.append(line)
            used += len(line) + 1
        lines.append("")

    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 5: Implement the hook renderer**

`claude/hooks/session-start-memory.sh`, replace `_item_text`:

```python
def _item_text(item):
    if isinstance(item, dict):
        date = item.get("date") or "unknown"
        content = " ".join(str(item.get("content") or "").split())
        mid = item.get("memory_id") or ""
        tag = f" [{mid}]" if mid else ""
        return f"- [{date}] {content}{tag}" if content else ""
    return f"- {str(item)}"
```
and replace `text = _render_capsule(payload)[:3500]` with a per-line cap so ids survive:
```python
def _cap(text, limit=3500):
    out, used = [], 0
    for line in text.splitlines():
        if used + len(line) + 1 > limit:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


text = _cap(_render_capsule(payload))
```

- [ ] **Step 6: Run the tests**

Run: `uv run --extra dev pytest tests/test_memory.py tests/test_capsules.py tests/test_claude_startup_hook.py -v`
Expected: all PASS, including the pre-existing capsule and startup-hook tests (the cap test `test_session_start_hook_caps_startup_summary` still holds: the cap is line-based but never exceeds 3500).

- [ ] **Step 7: Commit**

```bash
git add src/memory/manager.py src/memory/capsules.py claude/hooks/session-start-memory.sh tests/test_memory.py tests/test_capsules.py tests/test_claude_startup_hook.py
git commit -m "feat: print memory ids in recall and capsule output for traceability"
```

---

### Task 4: Provenance hook `rekall-provenance.sh` and installer wiring

**Files:**
- Create: `claude/hooks/rekall-provenance.sh`
- Modify: `claude/setup/install.sh:138` (HOOKS array), `:177-185` (command vars), the `python3 - ...` argv line, and `:300` (record calls)
- Test: `tests/test_provenance_hook.py` (new), `tests/test_claude_startup_hook.py` (installer test)

**Interfaces:**
- Consumes: Task 0 PASS. Task 2's tool parameters: `cwd`, `session_id`, `agent` on `recall_memories`, `observe`, `save_memory`.
- Produces: PreToolUse hook on matcher `mcp__memory__.*|mcp__rekall__.*` that prints `{"hookSpecificOutput":{"hookEventName":"PreToolUse","updatedInput":{...}}}` or nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_provenance_hook.py`:

```python
"""rekall-provenance.sh: fills cwd/session_id/agent on Rekall MCP calls (spec section 4)."""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude" / "hooks" / "rekall-provenance.sh"


def _run(payload: dict, env_extra: dict | None = None):
    env = os.environ.copy()
    env["REKALL_AUTOSAVE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )


def _payload(tool, tool_input):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-42",
        "cwd": "/Users/me/Repos/proj",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def test_adds_provenance_to_recall():
    r = _run(_payload("mcp__memory__recall_memories", {"query": "ports", "limit": 3}))
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["updatedInput"] == {
        "query": "ports",
        "limit": 3,
        "cwd": "/Users/me/Repos/proj",
        "session_id": "sess-42",
        "agent": "claude-code",
    }
    assert "permissionDecision" not in out


def test_rekall_namespace_also_matches():
    r = _run(_payload("mcp__rekall__save_memory", {"content": "x"}))
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]["session_id"] == "sess-42"


def test_does_not_overwrite_model_supplied_fields():
    r = _run(_payload("mcp__memory__observe", {"summary": "x", "cwd": "/elsewhere", "session_id": "mine"}))
    out = json.loads(r.stdout)["hookSpecificOutput"]["updatedInput"]
    assert out["cwd"] == "/elsewhere"
    assert out["session_id"] == "mine"
    assert out["agent"] == "claude-code"


def test_tool_outside_allowlist_emits_nothing():
    r = _run(_payload("mcp__memory__close_loop", {"memory_id": "m1"}))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_non_rekall_tool_emits_nothing():
    r = _run(_payload("Bash", {"command": "ls"}))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_kill_switch():
    r = _run(_payload("mcp__memory__recall_memories", {"query": "x"}), {"REKALL_AUTOSAVE": "0"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_malformed_stdin_exits_zero_silently():
    env = os.environ.copy()
    r = subprocess.run(["bash", str(HOOK)], input="not json", text=True, capture_output=True, env=env, timeout=10)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_provenance_hook.py -v`
Expected: all FAIL (hook file missing).

- [ ] **Step 3: Write the hook**

Create `claude/hooks/rekall-provenance.sh`:

```bash
#!/usr/bin/env bash
# ~/.claude/hooks/rekall-provenance.sh
# PreToolUse on Rekall MCP tools. Fills cwd, session_id, agent when the model
# omitted them, so saves land in the caller's project and recalls attribute.
# Never gates: no permissionDecision, every failure path exits 0.
#
# Kill switch: REKALL_AUTOSAVE=0
set -uo pipefail

[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

payload="$(cat 2>/dev/null || true)"
[[ -z "$payload" ]] && exit 0

tool="$(jq -r '.tool_name // empty' <<<"$payload" 2>/dev/null || true)"
[[ -z "$tool" ]] && exit 0

case "$tool" in
  mcp__memory__recall_memories|mcp__rekall__recall_memories) ;;
  mcp__memory__observe|mcp__rekall__observe) ;;
  mcp__memory__save_memory|mcp__rekall__save_memory) ;;
  *) exit 0 ;;
esac

jq -c '
  .tool_input as $ti
  | ($ti // {}) as $in
  | ($in
     + (if ($in.cwd // "") == "" and (.cwd // "") != "" then {cwd: .cwd} else {} end)
     + (if ($in.session_id // "") == "" and (.session_id // "") != "" then {session_id: .session_id} else {} end)
     + (if ($in.agent // "") == "" then {agent: "claude-code"} else {} end)) as $out
  | {hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: $out}}
' <<<"$payload" 2>/dev/null || exit 0

exit 0
```
Then `chmod +x claude/hooks/rekall-provenance.sh`.

- [ ] **Step 4: Run the hook tests**

Run: `uv run --extra dev pytest tests/test_provenance_hook.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing installer test**

Append to `tests/test_claude_startup_hook.py`:

```python
def test_installer_wires_provenance_hook(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}")
    result, _ = _run_install(home)
    assert result.returncode == 0, result.stderr
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    entries = settings["hooks"]["PreToolUse"]
    match = [e for e in entries if e.get("matcher") == "mcp__memory__.*|mcp__rekall__.*"]
    assert match, entries
    assert any("rekall-provenance.sh" in h["command"] for h in match[0]["hooks"])
    assert (home / ".claude" / "hooks" / "rekall-provenance.sh").exists()
```
(Check `_run_install`'s signature at line 111 and pass arguments the way `test_installer_default_does_not_install_startup_capsule` does.)

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run --extra dev pytest tests/test_claude_startup_hook.py -k wires_provenance -v`
Expected: FAIL (no matching PreToolUse entry).

- [ ] **Step 7: Wire the installer**

`claude/setup/install.sh`:
- line 138: `HOOKS=(rekall-restore.sh rekall-observe.sh rekall-session-end.sh memory-prune.sh rekall-reflex.sh rekall-provenance.sh)`
- after `REFLEX_CMD=...` add `PROV_CMD="$HOME/.claude/hooks/rekall-provenance.sh"`
- add `"$PROV_CMD"` to the `/usr/bin/python3 - "$SETTINGS" ...` argv list after `"$REFLEX_CMD"`, and in the embedded Python read it into `prov_cmd` where the others are unpacked from `sys.argv` (keep `start_cmd` last).
- after the reflex `record(...)` line add:
```python
record(
    ensure_event_hook("PreToolUse", prov_cmd, matcher="mcp__memory__.*|mcp__rekall__.*"),
    "PreToolUse → rekall-provenance.sh",
)
```
- in the verify section near line 359 add `[[ -f "$HOME/.claude/hooks/rekall-provenance.sh" ]] && ok "rekall-provenance.sh in place" || warn "rekall-provenance.sh missing"`.

- [ ] **Step 8: Run installer and hook tests**

Run: `uv run --extra dev pytest tests/test_claude_startup_hook.py tests/test_provenance_hook.py tests/test_codex_installer.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add claude/hooks/rekall-provenance.sh claude/setup/install.sh tests/test_provenance_hook.py tests/test_claude_startup_hook.py
git commit -m "feat(hooks): provenance hook fills cwd, session_id, agent on Rekall MCP calls"
```

---

### Task 5: Session-end summary records delivered vs referenced

**Files:**
- Modify: `claude/hooks/rekall-session-end.sh:36-180` (the embedded Python)
- Test: `tests/test_hooks_session.py`

**Interfaces:**
- Consumes: ids printed by Task 3 in `tool_result` text and in `hook_additional_context` attachments.
- Produces: `session_summary` POST body
```json
{"event_type":"session_summary","session_id":"...","project":"...","client":"claude-code",
 "recalled_ids":[...],                      // union of delivered, kept for old servers
 "delivered":{"explicit":[...],"capsule":[...],"reflex":[...]},
 "referenced":[...],
 "coverage":{"transcript_tail_bytes":1048576,"truncated":false},
 "edits_after_recall":0,"test_passes_after_recall":0}
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hooks_session.py` (reuse `_make_fake_curl`; add a transcript builder):

```python
SESSION_END_HOOK = REPO / "claude" / "hooks" / "rekall-session-end.sh"
MID_A = "2026-10-09_fact_aaaa1111"
MID_B = "2026-10-09_decision_bbbb2222"
MID_C = "2026-10-09_learning_cccc3333"


def _transcript_lines():
    recall_use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__memory__recall_memories", "input": {"query": "x"}}]},
    }
    recall_result = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": f"- port 8000 (2026-10-09) [{MID_A}]\n- other (2026-10-09) [{MID_B}]"}]}]},
    }
    capsule = {
        "type": "attachment",
        "attachment": {"type": "hook_additional_context", "content": [f"== REKALL STARTUP (p) ==\n- [2026-10-09] use uv [{MID_C}]\n== END REKALL STARTUP =="]},
    }
    assistant_cites_a = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": f"Per memory {MID_A}, port is 8000."}]},
    }
    bash_use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "echo hi"}}]},
    }
    # MID_B appears only inside a later tool_result: exposure, not a reference.
    bash_result = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": f"log mentions {MID_B}"}]}]},
    }
    return [capsule, recall_use, recall_result, assistant_cites_a, bash_use, bash_result]


def _run_session_end(tmp_path: Path, lines: list[dict], tail_bytes: str | None = None):
    fakebin, calls, bodies = _make_fake_curl(tmp_path)
    transcript = tmp_path / "sess-9.jsonl"
    transcript.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    (tmp_path / "rekall-restored-sess-9").write_text("")
    env = os.environ.copy()
    env.update({
        "PATH": f"{fakebin}:{env['PATH']}",
        "REKALL_API_URL": "http://rekall.test",
        "REKALL_AUTOSAVE": "1",
        "REKALL_MARKER_DIR": str(tmp_path),
    })
    if tail_bytes:
        env["REKALL_TRANSCRIPT_TAIL_BYTES"] = tail_bytes
    payload = {"hook_event_name": "SessionEnd", "session_id": "sess-9", "cwd": str(tmp_path / "proj"), "transcript_path": str(transcript)}
    r = subprocess.run(["bash", str(SESSION_END_HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=env, cwd=tmp_path, timeout=10, check=False)
    body = json.loads(bodies.read_text().strip().splitlines()[-1]) if bodies.exists() else None
    return r, body


def test_session_end_reports_delivered_by_surface_and_referenced(tmp_path):
    r, body = _run_session_end(tmp_path, _transcript_lines())
    assert r.returncode == 0
    assert body["client"] == "claude-code"
    assert body["delivered"] == {"explicit": [MID_A, MID_B], "capsule": [MID_C], "reflex": []}
    assert body["referenced"] == [MID_A]
    assert body["recalled_ids"] == sorted([MID_A, MID_B, MID_C])
    assert body["coverage"] == {"transcript_tail_bytes": 1048576, "truncated": False}


def test_session_end_marks_truncated_tail(tmp_path):
    lines = _transcript_lines()
    pad = {"type": "progress", "pad": "x" * 2000}
    r, body = _run_session_end(tmp_path, [pad] + lines, tail_bytes="4096")
    assert r.returncode == 0
    assert body["coverage"]["truncated"] is True
    assert body["coverage"]["transcript_tail_bytes"] == 4096
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_hooks_session.py -k "delivered or truncated" -v`
Expected: FAIL (`KeyError: 'client'` / no `delivered`).

- [ ] **Step 3: Implement in the embedded Python of `rekall-session-end.sh`**

Replace everything from `recall_tool_ids = {` through the final `print(json.dumps({...}))` with:

```python
recall_tool_ids = {
    tool_id
    for tool_id, name in tool_names.items()
    if "recall" in name.lower() or "reflex" in name.lower()
}
delivered = {"explicit": [], "capsule": [], "reflex": []}
first_recall_index = None


def _add(bucket, ids):
    for mid in ids:
        if mid not in delivered[bucket]:
            delivered[bucket].append(mid)


def _attachment_text(entry):
    att = entry.get("attachment") or {}
    if att.get("type") == "hook_additional_context":
        content = att.get("content")
        return "\n".join(c for c in content if isinstance(c, str)) if isinstance(content, list) else str(content or "")
    if att.get("type") == "hook_success":
        try:
            envelope = json.loads(att.get("stdout", "") or "{}")
        except (TypeError, ValueError):
            return ""
        return str(envelope.get("hookSpecificOutput", {}).get("additionalContext") or "")
    return ""


for index, entry in enumerate(entries):
    kind = entry.get("type")
    if kind == "user":
        for block in content_blocks(entry):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id", "") in recall_tool_ids:
                _add("explicit", memory_id.findall(result_text(block)))
                if first_recall_index is None:
                    first_recall_index = index
    elif kind == "attachment":
        text = _attachment_text(entry)
        if "REKALL REFLEX" in text:
            _add("reflex", memory_id.findall(text))
        elif "REKALL STARTUP" in text:
            _add("capsule", memory_id.findall(text))
        else:
            continue
        if first_recall_index is None or index < first_recall_index:
            first_recall_index = index

all_delivered = set(delivered["explicit"]) | set(delivered["capsule"]) | set(delivered["reflex"])
if not all_delivered:
    raise SystemExit(0)

# A reference is the id in the agent's own words or tool arguments, never in a tool_result.
referenced = []
for index, entry in enumerate(entries):
    if entry.get("type") != "assistant" or (first_recall_index is not None and index <= first_recall_index):
        continue
    for block in content_blocks(entry):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            found = memory_id.findall(block.get("text", ""))
        elif block.get("type") == "tool_use":
            found = memory_id.findall(json.dumps(block.get("input", {})))
        else:
            continue
        for mid in found:
            if mid in all_delivered and mid not in referenced:
                referenced.append(mid)

edits = 0
test_passes = 0
bash_test_ids = set()
for index, entry in enumerate(entries):
    if first_recall_index is not None and index <= first_recall_index:
        continue
    if entry.get("type") == "assistant":
        for block in content_blocks(entry):
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            name = block.get("name", "")
            if name in ("Edit", "Write"):
                edits += 1
            elif name == "Bash":
                command = block.get("input", {}).get("command", "")
                if isinstance(command, str) and re.search(r"pytest|go test|npm test", command):
                    bash_test_ids.add(block.get("id", ""))
    elif entry.get("type") == "user":
        for block in content_blocks(entry):
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            if block.get("tool_use_id", "") not in bash_test_ids:
                continue
            if re.search(r"\bpassed\b|\bok\b", result_text(block), re.IGNORECASE):
                test_passes += 1

print(
    json.dumps(
        {
            "event_type": "session_summary",
            "session_id": session_id,
            "project": project,
            "client": "claude-code",
            "recalled_ids": sorted(all_delivered),
            "delivered": delivered,
            "referenced": referenced,
            "coverage": {"transcript_tail_bytes": limit, "truncated": bool(start)},
            "edits_after_recall": edits,
            "test_passes_after_recall": test_passes,
        },
        separators=(",", ":"),
    )
)
```
Keep the existing file-tail reading block above it unchanged; it already defines `start` and `limit`.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev pytest tests/test_hooks_session.py tests/test_observe_hook_summary.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add claude/hooks/rekall-session-end.sh tests/test_hooks_session.py
git commit -m "feat(hooks): session summary records delivered ids by surface and referenced ids"
```

---

### Task 6: Events route accepts the new summary fields

**Files:**
- Modify: `src/server.py:753-805` (`api_record_events`)
- Test: `tests/test_server_events.py`

**Interfaces:**
- Consumes: Task 5 body shape.
- Produces: `record_event(..., payload={session_id, client, delivered, referenced, coverage, edits_after_recall, test_passes_after_recall})`. Old clients that omit the fields get `client: None`, `delivered: {}`, `referenced: []`, `coverage: None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server_events.py`:

```python
def test_post_events_records_delivered_referenced_client(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={
            "event_type": "session_summary",
            "session_id": "sess-abc",
            "project": "my-proj",
            "client": "claude-code",
            "recalled_ids": ["id-1", "id-2", "id-3"],
            "delivered": {"explicit": ["id-1", "id-2"], "capsule": ["id-3"], "reflex": []},
            "referenced": ["id-1"],
            "coverage": {"transcript_tail_bytes": 1048576, "truncated": False},
        },
    )
    assert r.status_code == 200
    p = manager.record_event.call_args.kwargs["payload"]
    assert p["client"] == "claude-code"
    assert p["delivered"] == {"explicit": ["id-1", "id-2"], "capsule": ["id-3"], "reflex": []}
    assert p["referenced"] == ["id-1"]
    assert p["coverage"] == {"transcript_tail_bytes": 1048576, "truncated": False}


def test_post_events_old_client_shape_still_accepted(client):
    tc, manager = client
    r = tc.post(
        "/api/memory/events",
        json={"event_type": "session_summary", "session_id": "s", "project": "p", "recalled_ids": ["id-1"]},
    )
    assert r.status_code == 200
    p = manager.record_event.call_args.kwargs["payload"]
    assert p["client"] is None
    assert p["delivered"] == {}
    assert p["referenced"] == []


def test_post_events_rejects_bad_referenced(client):
    tc, _ = client
    r = tc.post(
        "/api/memory/events",
        json={"event_type": "session_summary", "session_id": "s", "project": "p", "recalled_ids": [], "referenced": "id-1"},
    )
    assert r.status_code == 400


def test_post_events_rejects_bad_delivered(client):
    tc, _ = client
    r = tc.post(
        "/api/memory/events",
        json={"event_type": "session_summary", "session_id": "s", "project": "p", "recalled_ids": [], "delivered": {"explicit": "id-1"}},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_server_events.py -v`
Expected: the three new ones FAIL (`KeyError: 'client'`, 200 instead of 400).

- [ ] **Step 3: Implement**

In `api_record_events`, after the `test_passes_after_recall` validation block, add:

```python
        def _ids(value, name):
            if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
                raise ValueError(f"{name} must be a list of strings")
            return value

        try:
            referenced = _ids(body.get("referenced", []), "referenced")
            delivered_raw = body.get("delivered", {})
            if not isinstance(delivered_raw, dict):
                raise ValueError("delivered must be an object")
            delivered = {k: _ids(v, f"delivered.{k}") for k, v in delivered_raw.items()}
        except ValueError as exc:
            return _bad_request(str(exc))
        client_name = body.get("client")
        if client_name is not None and not isinstance(client_name, str):
            return _bad_request("client must be a string")
        coverage = body.get("coverage")
        if coverage is not None and not isinstance(coverage, dict):
            return _bad_request("coverage must be an object")
```
and extend the `payload={...}` passed to `record_event`:
```python
            payload={
                "session_id": session_id,
                "client": client_name,
                "delivered": delivered,
                "referenced": referenced,
                "coverage": coverage,
                "edits_after_recall": edits_after_recall,
                "test_passes_after_recall": test_passes_after_recall,
            },
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest tests/test_server_events.py tests/test_event_contract.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_server_events.py
git commit -m "feat(api): session_summary carries client, delivered by surface, referenced, coverage"
```

---

### Task 7: Sessions fold creates sessions from tagged recalls and totals `referenced`

**Files:**
- Modify: `src/memory/sessions.py:19-29` (`_new_session`), `:85-130` (`fold_sessions`)
- Test: `tests/test_sessions_fold.py`

**Interfaces:**
- Consumes: `memory_recalled` events with `payload.session_id` (set by Task 2/4 provenance); `session_summary` payload `referenced` (Task 6).
- Produces: session dict gains `"referenced": [...]` and `totals["referenced"]`; a `memory_recalled` event with a `session_id` and no prior summary creates the session instead of landing in `unattributed:<project>`. Last summary per session wins for `referenced`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sessions_fold.py`:

```python
def _recall(session_id, project, memory_ids, observed_at):
    return _ev(
        "memory_recalled",
        project,
        {"memory_ids": memory_ids, "session_id": session_id, "query": "q", "memories": [], "token_estimate": 10},
        observed_at,
    )


def _summary_v2(session_id, project, delivered, referenced, observed_at):
    all_ids = sorted({m for ids in delivered.values() for m in ids})
    return _ev(
        "session_summary",
        project,
        {"memory_ids": all_ids, "session_id": session_id, "delivered": delivered, "referenced": referenced},
        observed_at,
    )


def test_tagged_recall_creates_session_without_summary():
    from memory.sessions import fold_sessions

    out = fold_sessions([_recall("s-new", "proj", ["m1"], "2026-10-09T10:00:00")])
    ids = [s["session_id"] for s in out]
    assert "s-new" in ids
    assert not any(i.startswith("unattributed:") for i in ids)
    assert out[0]["totals"]["recalls"] == 1


def test_untagged_recall_still_lands_unattributed():
    from memory.sessions import fold_sessions

    ev = _ev("memory_recalled", "proj", {"memory_ids": ["m1"], "query": "q"}, "2026-10-09T10:00:00")
    out = fold_sessions([ev])
    assert out[0]["session_id"] == "unattributed:proj"


def test_summary_referenced_totals_last_wins():
    from memory.sessions import fold_sessions

    events = [
        _summary_v2("s1", "proj", {"explicit": ["m1", "m2"]}, ["m1"], "2026-10-09T10:00:00"),
        _summary_v2("s1", "proj", {"explicit": ["m1", "m2"]}, ["m1", "m2"], "2026-10-09T11:00:00"),
    ]
    out = fold_sessions(events)
    s = next(x for x in out if x["session_id"] == "s1")
    assert s["referenced"] == ["m1", "m2"]
    assert s["totals"]["referenced"] == 2
    assert s["totals"]["delivered"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_sessions_fold.py -v`
Expected: three new FAIL.

- [ ] **Step 3: Implement**

`_new_session`: add `"referenced": [],` and `"delivered": [],` keys, and `"totals": {"recalls": 0, "injected": 0, "tokens": 0, "referenced": 0, "delivered": 0}`.

In `fold_sessions`, inside the first loop's `session_summary` branch, after updating `summary_ids`, add:
```python
            delivered = payload.get("delivered") or {}
            session["delivered"] = sorted({m for ids in delivered.values() if isinstance(ids, list) for m in ids} or set(payload.get("memory_ids") or []))
            if event.observed_at >= (window_end.get(session_id) or ""):
                session["referenced"] = list(payload.get("referenced") or [])
```
(place it before `window_end[session_id]` is updated so "last wins" compares against the previous end).

In the second loop (`memory_recalled`), replace the `target = (sessions.get(session_id) if session_id else _join_target(...))` expression with:
```python
        if session_id:
            target = sessions.setdefault(session_id, _new_session(session_id, event.project))
        else:
            target = _join_target(event, sessions, summary_ids, window_end)
```

In the totals loop add:
```python
        session["totals"]["referenced"] = len(session["referenced"])
        session["totals"]["delivered"] = len(session["delivered"])
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest tests/test_sessions_fold.py tests/test_server_memory_os_endpoints.py -k "session or fold" -v`
Expected: all PASS (existing fold tests unchanged: a null-session recall still joins or lands unattributed).

- [ ] **Step 5: Commit**

```bash
git add src/memory/sessions.py tests/test_sessions_fold.py
git commit -m "feat(sessions): fold tagged recalls into sessions, total delivered and referenced"
```

---

### Task 8: Utility report stops crediting unreferenced memories; prints citation coverage

**Files:**
- Modify: `scripts/utility_report.py:55-70` (summary parse), `:73-105` (`collapse_sessions`), `:108-128` (`compute_utility_map`), and wherever the per-memory utility is printed (grep `utility` in the render function)
- Test: `tests/test_utility_report.py`

**Interfaces:**
- Consumes: summaries with optional `referenced` and `delivered` payload keys.
- Produces: `compute_utility_map(summaries) -> dict[str, float | None]`: value is `sessions_with_outcome_and_reference / sessions_recalled`, or `None` ("unknown") for a memory never referenced in any session where it was recalled. New `compute_citation_coverage(summaries) -> dict` with `{"delivered": int, "referenced": int, "coverage": float}` over collapsed sessions. Report prints a "Citation coverage" line; it never prints the word "used".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_utility_report.py` (extend `_ss` with `referenced=None`, `delivered=None` kwargs that add those payload keys when given):

```python
def test_unreferenced_memory_is_unknown_not_credited(tmp_path):
    from scripts.utility_report import collapse_sessions, compute_utility_map, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(_ss("sess-1", "p", ["mem-x", "mem-y"], edits=2, referenced=["mem-x"]) + "\n")
    umap = compute_utility_map(collapse_sessions(parse_events(f)))
    assert umap["mem-x"] == 1.0
    assert umap["mem-y"] is None


def test_legacy_summary_without_referenced_is_unknown(tmp_path):
    from scripts.utility_report import collapse_sessions, compute_utility_map, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(_ss("sess-1", "p", ["mem-x"], edits=2) + "\n")
    umap = compute_utility_map(collapse_sessions(parse_events(f)))
    assert umap["mem-x"] is None


def test_citation_coverage_counts_over_collapsed_sessions(tmp_path):
    from scripts.utility_report import collapse_sessions, compute_citation_coverage, parse_events

    f = tmp_path / "_events.jsonl"
    f.write_text(
        _ss("s1", "p", ["a", "b"], referenced=["a"], delivered={"explicit": ["a", "b"]})
        + "\n"
        + _ss("s1", "p", ["a", "b"], referenced=["a", "b"], delivered={"explicit": ["a", "b"]}, eid="ev1")
        + "\n"
        + _ss("s2", "p", ["c"], referenced=[], delivered={"capsule": ["c"]}, eid="ev2")
        + "\n"
    )
    cov = compute_citation_coverage(collapse_sessions(parse_events(f)))
    assert cov == {"delivered": 3, "referenced": 2, "coverage": pytest.approx(2 / 3)}


def test_report_prints_citation_coverage_not_used(tmp_path, capsys):
    from scripts.utility_report import main

    f = tmp_path / "_events.jsonl"
    f.write_text(_ss("s1", "p", ["a"], referenced=["a"], delivered={"explicit": ["a"]}) + "\n")
    main([str(f)])
    out = capsys.readouterr().out
    assert "Citation coverage" in out
    assert " used" not in out.lower()
```
(If `main` takes no argv, call it the way the existing CLI test in this file does and pass the path via the same mechanism.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_utility_report.py -v`
Expected: the four new FAIL.

- [ ] **Step 3: Implement**

In the summary parse (around line 55), add to the dict: `"referenced": list(payload.get("referenced") or []) if "referenced" in payload else None,` and `"delivered": payload.get("delivered") or {},`.

In `collapse_sessions`, per group also compute:
```python
        last = group[-1]
        referenced = last["referenced"]  # last summary wins for v2 fields
        delivered_ids: set[str] = set()
        for s in group:
            for ids in (s.get("delivered") or {}).values():
                delivered_ids.update(ids)
```
and add `"referenced": referenced, "delivered_ids": sorted(delivered_ids) if delivered_ids else sorted(all_ids),` to the collapsed dict.

Replace `compute_utility_map`:
```python
def compute_utility_map(summaries: list[dict]) -> dict[str, float | None]:
    """Per-memory outcome credit requires the memory to be referenced; otherwise unknown (None)."""
    sessions_recalled: dict[str, set[str]] = defaultdict(set)
    sessions_credited: dict[str, set[str]] = defaultdict(set)
    ever_referenced: set[str] = set()

    for ss in summaries:
        sid = ss["session_id"] or ""
        has_outcome = ss["edits_after_recall"] > 0 or ss["test_passes_after_recall"] > 0
        referenced = set(ss.get("referenced") or [])
        for mid in ss["recalled_ids"]:
            sessions_recalled[mid].add(sid)
            if mid in referenced:
                ever_referenced.add(mid)
                if has_outcome:
                    sessions_credited[mid].add(sid)

    return {
        mid: (len(sessions_credited.get(mid, set())) / len(sess_set)) if mid in ever_referenced else None
        for mid, sess_set in sessions_recalled.items()
    }


def compute_citation_coverage(summaries: list[dict]) -> dict:
    """Delivered vs referenced over collapsed sessions. Telemetry, not utility."""
    delivered = sum(len(ss["delivered_ids"]) for ss in summaries)
    referenced = sum(len(set(ss.get("referenced") or []) & set(ss["delivered_ids"])) for ss in summaries)
    return {"delivered": delivered, "referenced": referenced, "coverage": (referenced / delivered) if delivered else 0.0}
```

In the report rendering: wherever the per-memory utility value is printed, print `unknown` for `None`; add a line `Citation coverage: {referenced}/{delivered} ({coverage:.0%})` from `compute_citation_coverage`; and replace any literal "used" wording with "referenced".

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest tests/test_utility_report.py -v`
Expected: all PASS, including the pre-existing ones (adjust any pre-existing assertion that expected a credited float for an unreferenced memory: it must now expect `None`, and say so in the commit body).

- [ ] **Step 5: Commit**

```bash
git add scripts/utility_report.py tests/test_utility_report.py
git commit -m "feat(utility): credit only referenced memories; report citation coverage"
```

---

### Task 9: Codex adapter parity for the summary contract

**Files:**
- Modify: `codex/hooks/rekall_hook.py:338-400` (`summarize_session`, summary dict)
- Test: `tests/test_codex_hooks.py`

**Interfaces:**
- Consumes: Codex transcript events (`function_call` / `function_call_output` / assistant message items; find the assistant text event type in `_event_body` usage within this file).
- Produces: summary dict adds `"client": "codex"`, `"delivered": {"explicit": recalled[:32]}`, `"referenced": [...]`, `"coverage": {"transcript_tail_bytes": <the bound used by _bounded_lines>, "truncated": <bool if available, else False>}`. Codex has no capsule or reflex surfaces unless `REKALL_STARTUP_CAPSULE=1`; `delivered.capsule` is filled only from the SessionStart injection if that code path records ids, otherwise omitted.

- [ ] **Step 1: Write the failing test**

Find the existing `summarize_session` test in `tests/test_codex_hooks.py` and its transcript-line helpers. Append:

```python
def test_summarize_session_reports_delivered_and_referenced():
    from codex.hooks.rekall_hook import summarize_session

    mid_a = "2026-10-09_fact_aaaa1111"
    mid_b = "2026-10-09_decision_bbbb2222"
    lines = [
        _call("c1", "recall_memories", {"query": "x"}),
        _output("c1", f"- a (2026-10-09) [{mid_a}]\n- b (2026-10-09) [{mid_b}]"),
        _assistant_text(f"Using {mid_a}: port is 8000."),
        _call("c2", "shell", {"command": "echo hi"}),
        _output("c2", f"unrelated {mid_b}"),
    ]
    summary = summarize_session({"session_id": "s1", "cwd": "/tmp/proj", "transcript_path": "/x"}, lines)
    assert summary["client"] == "codex"
    assert summary["delivered"] == {"explicit": [mid_a, mid_b]}
    assert summary["referenced"] == [mid_a]
    assert summary["recalled_ids"] == [mid_a, mid_b]
    assert "coverage" in summary
```
Use the file's existing helpers for `_call` / `_output`; if there is no assistant-text helper, write `_assistant_text(text)` returning a JSON line in the shape `_event_body` accepts for assistant messages (read `_event_body` first and mirror one real Codex `message` item with `role: "assistant"` and `content: [{"type": "output_text", "text": ...}]`).

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev pytest tests/test_codex_hooks.py -k delivered_and_referenced -v`
Expected: FAIL (`KeyError: 'client'`).

- [ ] **Step 3: Implement**

In `summarize_session`, track `referenced: list[str] = []`. In the event loop, before the `call_id` check, handle assistant message items: if the body is an assistant message (role `assistant`), extract its text and, when `recalled` is non-empty, append any id in `_extract_memory_ids(text)` that is in `recalled` and not yet in `referenced`. Also when a `function_call` input contains a recalled id (`_extract_memory_ids(json.dumps(value))`), append it. Never read ids from `function_call_output` for `referenced`.

Extend the returned dict:
```python
        "client": "codex",
        "delivered": {"explicit": recalled[:32]},
        "referenced": referenced[:32],
        "coverage": {"transcript_tail_bytes": _TAIL_BYTES, "truncated": False},
```
where `_TAIL_BYTES` is the constant `_bounded_lines` uses (name it if it is a literal today).

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest tests/test_codex_hooks.py tests/test_codex_installer.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add codex/hooks/rekall_hook.py tests/test_codex_hooks.py
git commit -m "feat(codex): session summary carries client, delivered, referenced"
```

---

### Task 10: Docs and the namespace note

**Files:**
- Modify: `claude/INSTALL.md:14-20` (hook tree), `:41` (default hook list), `:137` (add a `rekall-provenance.sh` section after `rekall-session-end.sh`)
- Modify: `docs/CLAUDE_MEMORY_SETTINGS.md:65` (session-end summary fields), `:193` (hook list)
- Modify: `README.md` REST API table row for `POST /api/memory/events` (add the new optional fields)
- Modify: `CLAUDE.md:115` (namespace note)

- [ ] **Step 1: INSTALL.md**

Add to the tree: `│   ├── rekall-provenance.sh    PreToolUse (mcp__memory__.*|mcp__rekall__.*) — fills cwd, session_id, agent`. Change "5 default hooks" to "6 default hooks" and add `rekall-provenance.sh` to the list. Add a section:

```markdown
### `rekall-provenance.sh` — PreToolUse (Rekall MCP tools)

Matcher `mcp__memory__.*|mcp__rekall__.*`. For `recall_memories`, `observe`
and `save_memory` it returns `updatedInput` with `cwd`, `session_id` and
`agent: "claude-code"` filled in when the model omitted them. Never sets a
permission decision. Other tools: no output. Kill switch `REKALL_AUTOSAVE=0`.
```

- [ ] **Step 2: CLAUDE_MEMORY_SETTINGS.md**

After the `REKALL_TRANSCRIPT_TAIL_BYTES` bullet add:
```markdown
- `session_summary` (posted by `rekall-session-end.sh` and the Codex adapter) carries `client`, `delivered` (ids by surface: explicit, capsule, reflex), `referenced` (ids the agent cited in its own text or tool arguments after delivery) and `coverage` (tail bytes, truncated). The utility report calls `referenced / delivered` **citation coverage**; it is telemetry, not evidence a memory helped.
```
Update the hook list at line 193 to include `rekall-provenance.sh`.

- [ ] **Step 3: README REST table**

In the row for `POST /api/memory/events`, append to its description: `optional: client, delivered{surface: ids}, referenced, coverage`.

- [ ] **Step 4: CLAUDE.md namespace note**

Replace the paragraph at line 115 with:
```markdown
**Tool namespace:** tool names are `mcp__<server>__<tool>` where `<server>` is whatever name the Claude Code MCP config registered (`memory` on the maintainer's machine, `rekall` in the shipped example). Hook matchers in this repo cover both: `mcp__memory__.*|mcp__rekall__.*`. If you copy a hook from another project, namespace-patch first.
```

- [ ] **Step 5: Commit**

```bash
git add claude/INSTALL.md docs/CLAUDE_MEMORY_SETTINGS.md README.md CLAUDE.md
git commit -m "docs: provenance hook, session summary contract, namespace note"
```

---

### Task 11: Full suite and branch wrap-up

**Files:** none new.

- [ ] **Step 1: Run the full suite with the test Qdrant up**

Run (outside the sandbox):
```bash
docker compose --profile test up -d qdrant-test
uv run --extra dev pytest -q -p no:cacheprovider
```
Expected: no new failures beyond the 4 known date-rot failures in `tests/test_afk_memory_contract.py` (3) and `tests/test_close_loop.py::test_unresolved_todo_stays_in_open_loops` (1), which fail identically on `main`.

- [ ] **Step 2: Lint**

Run: `uv run --extra dev ruff check src tests scripts codex && git diff --check`
Expected: clean.

- [ ] **Step 3: Record the final counts in the plan**

Append under this task: `Final suite (YYYY-MM-DD): N passed, 4 failed (known), K skipped.` Commit:
```bash
git add docs/superpowers/plans/2026-10-09-measurable-memory.md
git commit -m "docs: record final test counts for measurable memory plan"
```

Rollout after merge (not tasks, operator steps): `claude/setup/install.sh` to pick up the two changed hooks and the new one; remove the `session-start-memory.sh` SessionStart entry from `~/.claude/settings.json` on the maintainer's machine (capsule is opt-in at install; the labeled eval found 0 helpful in 40 capsule deliveries); run the utility report after a week and read "Citation coverage" alongside the labeled eval, never alone.
