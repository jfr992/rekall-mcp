# Task 8 Report: Verify-gates, live smoke, README

## Status
COMPLETE

## Root Cause Found (was blocking previous sessions)

`test_one_probe_end_to_end` was failing because the ephemeral backend always started with only
2 of 28 rekall MCP tools registered. Root cause: `EphemeralBackend._child_env()` inherited
`PYTEST_VERSION` from the parent pytest process via `dict(os.environ)`.

`server.py` line 178: `_is_testing = "pytest" in sys.modules or "PYTEST_VERSION" in os.environ`

With `PYTEST_VERSION` in the server's env, `_is_testing=True` → `setup_tools()` never called →
`recall_memories` and 25 other tools never registered → Claude Code's init event showed 2 tools
→ model said "recall function not available in deferred tools" or tried to shell-execute the tool name.

The `ENABLE_TOOL_SEARCH=auto:0` investigation from the previous session was a red herring —
the filter was applied correctly, but the tools were never registered in the first place.

## Changes Made

### `benchmarks/eval/env.py`
- `_child_env()`: strip `PYTEST_VERSION`, `PYTEST_CURRENT_TEST`, `PYTEST_XDIST_WORKER`
  before the subprocess inherits them.
- `make_workspace()`: create minimal `.git/{HEAD,config}` so Claude Code recognizes the
  workspace as a project root and reads `cwd/.claude/settings.json` (secondary fix).

### `benchmarks/eval/driver.py`
- Create `cwd/.claude/settings.json` with `ENABLE_TOOL_SEARCH=1` before subprocess.
- Explicit `env` dict with `ENABLE_TOOL_SEARCH=1` to prevent `auto:0` from settings.json.
- Debug dump under `REKALL_EVAL_DEBUG` env var.

### `tests/test_eval_env.py`
- `test_child_env_strips_pytest_markers`: asserts PYTEST_VERSION/PYTEST_CURRENT_TEST absent
  from `_child_env()` output.
- `test_make_workspace_creates_git_root`: asserts `.git/` dir created.

### `tests/test_eval_driver.py`
- `test_run_creates_project_settings_to_override_tool_search`: asserts `cwd/.claude/settings.json`
  written with `ENABLE_TOOL_SEARCH=1`.
- `test_run_does_not_overwrite_existing_project_settings`: idempotency guard.
- Updated `test_run_sets_enable_tool_search_env`: now asserts `"1"` (was `"auto:0"`).

### `tests/test_eval_live.py`
- Uses clearly fictional scenario (`FluxSync notification daemon UDP port 17341`) to prevent
  hallucination from training context.
- Direct prompt: `"Call mcp__rekall__recall_memories with query '...' ..."` — works because
  all 28 tools are now non-deferred in the init event.
- Asserts `rekall_tool_calls >= 1`, `rekall_payload_tokens > 0`, `"17341" in rekall_payload_text`.
- 3-attempt retry for extended-thinking edge cases.

## Test Summary
- `tests/test_eval_env.py`: 6 passed
- `tests/test_eval_driver.py`: 11 passed
- `tests/test_eval_live.py::test_one_probe_end_to_end`: PASSED (45s, ~1 claude -p call used)
- Full non-integration suite: 701 passed, 3 skipped, 52 deselected

## Verify-Gates Evidence

**Gate: Ephemeral backend isolation**
`assert_not_prod()` blocks `:6333` and `~/.claude/memory` — unchanged, 2 passing tests.

**Gate: Project filter on seeding**
`b.recall_ids("FluxSync notification daemon port", project=ws.name)` returns non-empty before
the Claude arm runs — direct REST retrieval confirms the memory is reachable.

**Gate: End-to-end retrieval**
`out.rekall_tool_calls >= 1` + `out.rekall_payload_tokens > 0` + `"17341" in out.rekall_payload_text`
— confirmed in passing live test run (2026-07-06).

## Deviations from Brief

The brief's Step 4 template used `/mcp` suffix in the MCP URL:
```python
{"mcpServers": {"rekall": {"type": "http", "url": f"{b.base_url}/mcp"}}}
```
The actual server mounts MCP at root `/`, not `/mcp`. The live test uses `b.base_url` directly.
This deviation was discovered in an earlier task session and is documented in the test docstring.

The brief used `"Internal metrics proxy listens on port 9741."` as the seed. The live test uses
`"FluxSync notification daemon binds to UDP port 17341."` — a more distinct fictional scenario
to prevent training data contamination (the port 9741/metrics proxy scenario is common in
real-world configs).

---

## Review Findings Fix Report (code-review pass)

### Finding 1 — driver.py CLAUDECODE comment (false claim)

**File:** `benchmarks/eval/driver.py:217`

Old comment: `# Suppress caveman/ponytail/superpowers SessionStart hooks; MCP still loads.`

No installed hook checks `CLAUDECODE=1` to suppress itself. The real gate for rekall hooks is
`REKALL_AUTOSAVE=0`. Replaced with:

```
# Claude Code child-session signal (does NOT suppress hooks; REKALL_AUTOSAVE=0 is what gates the rekall hooks).
```

### Finding 2 — runner.py _ClaudeJudge inherits full parent env

**File:** `benchmarks/eval/runner.py:319` (`_ClaudeJudge.complete`)

The judge subprocess had no `env=` argument, so it inherited the full parent environment. A
parent `ANTHROPIC_MODEL` (or `CLAUDE_CODE_EFFORT_LEVEL=max`) would silently override the pinned
judge model or suppress tool calls. Fixed by building the same minimal-allowlist env that
`driver.run()` uses, minus `ENABLE_TOOL_SEARCH` (the judge doesn't call rekall tools):

```python
env = {
    "HOME": _os.environ.get("HOME", ""),
    "PATH": _os.environ.get("PATH", ""),
    "USER": _os.environ.get("USER", ""),
    "TMPDIR": _os.environ.get("TMPDIR", ""),
    "LANG": _os.environ.get("LANG", "en_US.UTF-8"),
    "TERM": _os.environ.get("TERM", "xterm-256color"),
    "CLAUDECODE": "1",
    "REKALL_AUTOSAVE": "0",
}
```

`env=env` passed to `sp.run(...)`.

### Finding 3 — Gate-3: fixture shape verification

Ran `claude -p "Say exactly: hello" ... --output-format stream-json --verbose` against
`empty.json` (no MCP servers). `parse_stream` returned `answer="hello"`, `input_tokens=10`,
`output_tokens=68`.

Shape diff (fields parse_stream actually reads):

| Field path | Fixture | Real |
|---|---|---|
| `assistant.message.content[].type` | `tool_use`, `tool_result` | `thinking`, `text` |
| `assistant.message.content[].{id,name,text,thinking}` | present per type | present per type |
| `result.result` | string | string |
| `result.usage.input_tokens` | int | int |
| `result.usage.output_tokens` | int | int |

Real `assistant.message` has extra fields (`model`, `id`, `role`, `stop_reason`, `usage`, etc.)
— `parse_stream` never reads them. Real `result.usage` has extra fields (`cache_creation_input_tokens`,
`cache_read_input_tokens`, etc.) — `parse_stream` only reads `input_tokens` and `output_tokens`.

**Verdict: shapes IDENTICAL** — fixture not regenerated.

### Finding 4 — README.md Honesty labels

**File:** `benchmarks/eval/README.md`

Added two bullets under "Honesty labels":

- `driver.run()` forces `ENABLE_TOOL_SEARCH=1` in child env — machine-config-sensitive knob;
  without it, 26 of 28 rekall tools deferred, `recall_memories` unreachable.
- Hooks NOT suppressed; symmetric across arms; rekall hooks specifically disabled via
  `REKALL_AUTOSAVE=0`. Symmetric residue does not bias arm deltas.

### Test output

```
tests/test_eval_driver.py  11 passed
tests/test_eval_runner.py   5 passed
Full suite (not integration, not eval_live): 701 passed, 3 skipped
```

---

## Gate-3b: Agent-delegation hole found and closed (2026-07-06)

### Problem

On real eval runs the model delegates via the `Agent` tool (and via the `Skill` tool — forked
execution harness). Both spawn child processes whose `mcp__rekall__*` tool traffic is invisible
to `parse_stream` in the parent stream-json, causing `rekall_tool_calls=0` and
`rekall_payload_tokens=0` even when memory was actually used. Evidence transcript
(`/tmp/claude/rekall-eval/real_toolcall_stream.jsonl`): tool_use names `ToolSearch, Agent,
ToolSearch, Agent`.

### Fix

`build_cmd` now appends `--disallowedTools Agent Skill` (both as separate list elements; the CLI
flag is variadic). With both blocked the 59-tool init event contains 28 rekall tools but no
delegation tools, forcing the model to call `mcp__rekall__*` directly in the parent transcript.

`make_workspace` now writes `.claude/settings.json` (`ENABLE_TOOL_SEARCH=1`) alongside the
minimal `.git` init. Callers that bypass `driver.run()` (e.g. inline capture scripts using
`subprocess.run(build_cmd(...))` directly) previously had no guarantee the settings file
existed; they now receive the ENABLE_TOOL_SEARCH override unconditionally.

### Envelope shape verification (gate-3 carried forward)

`parse_stream` fields verified against a REAL tool-calling transcript:
`assistant.tool_use{id, name}` / `user.tool_result{tool_use_id, list-content}` /
`result{result, usage}` — fixture matches. Fixture not regenerated (shapes identical).

### Live test result

`pytest -m eval_live -v` — **PASSED** (28 s). Prompt names `mcp__rekall__recall_memories`
explicitly; model calls it directly after `--disallowedTools Agent Skill` blocks delegation.
`rekall_tool_calls=1`, `rekall_payload_tokens > 0`, `"17341" in rekall_payload_text`.

### Capture script result — BLOCKED

Capture prompt "Use your memory tools: what port does our internal metrics proxy listen on?"
is vague — no explicit tool name. With delegation blocked, the model falls through to Bash
(3 filesystem searches) and never calls `mcp__rekall__*`.
Transcript tool names: `Bash`.
`rekall_tool_calls=0`, `rekall_payload_tokens=0`.

Root cause: vague prompts don't reliably trigger direct tool calls; explicit-name prompts
(as in the live test) do. The measurement mechanism is correct and proven by the live test;
the capture script's prompt is the limiting factor.

---

## Control-arm disk contamination hole closed (2026-07-06)

The `--disallowedTools` list previously blocked only `Agent` and `Skill`. A structural hole
remained: `Bash`, `Read`, `Grep`, and `Glob` let the absent-arm agent find the seeded YAML
on disk — seeding happens before the arms loop, so the temp store exists for the duration
of the absent arm's run — which would silently destroy the causal delta between arms. In
addition, `WebFetch` and `WebSearch` let any arm look up answers externally, and `Write` /
`Edit` / `NotebookEdit` are pointless side effects in a read-only eval. The fix: define
`DISALLOWED_TOOLS: tuple[str, ...]` as a module-level constant in `driver.py` covering all
eleven tools (`Agent Skill Bash Read Grep Glob Write Edit NotebookEdit WebFetch WebSearch`),
splice it into `build_cmd` with `*DISALLOWED_TOOLS`, and update `test_build_cmd_no_bare_mcp_difference`
to import and iterate the constant — asserting each member is present in both arms, the
arms-differ-only-in-mcp-config invariant unchanged, and `ToolSearch` explicitly absent from
the disallow list (it is still needed to load deferred MCP schemas). Live test passed with
the wider list (`rekall_tool_calls=1`, `rekall_payload_tokens>0`, `"17341" in payload_text`);
full suite 702 passed, 3 skipped.
