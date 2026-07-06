"""claude -p driver: stream-json parsing + token accounting (cl100k, spec-pinned)."""

from pathlib import Path

FIXTURE = Path("tests/fixtures/eval_stream.jsonl")


def test_parse_stream_extracts_answer_usage_and_rekall_payload():
    from benchmarks.eval.driver import count_tokens, parse_stream

    r = parse_stream(FIXTURE.read_text().splitlines())
    assert r.answer == "The metrics proxy listens on port 9741."
    assert r.input_tokens == 2300 and r.output_tokens == 45
    assert r.rekall_tool_calls == 1
    expected = count_tokens(
        "[decision] Metrics proxy listens on port 9741 (memory_id: 2026-07-05_decision_ab12cd34)"
    )
    assert r.rekall_payload_tokens == expected > 0


def test_build_cmd_no_bare_mcp_difference(tmp_path):
    """Deviation from original spec: no --bare on any arm.

    --bare disables macOS Keychain OAuth auth. Arms now differ only in which
    --mcp-config file they point at; absent arm caller passes an empty config.

    DISALLOWED_TOOLS blocks all non-MCP tools on both arms (contamination channels):
    - Bash/Read/Grep/Glob: absent arm could read seeded YAML from disk, destroying causal delta.
    - Write/Edit/NotebookEdit: pointless side effects in a read-only eval.
    - WebFetch/WebSearch: any arm could look up the answer externally.
    - Agent/Skill: spawn child processes whose mcp__rekall__* traffic is invisible to parse_stream.
    ToolSearch remains allowed: it only loads deferred MCP schemas, no disk/web access.
    """
    from benchmarks.eval.driver import DISALLOWED_TOOLS, build_cmd

    cfg = tmp_path / "arm.json"
    empty = tmp_path / "empty.json"
    seeded = build_cmd("q", cfg, "claude-haiku-4-5-20251001")
    absent = build_cmd("q", empty, "claude-haiku-4-5-20251001")
    # No --bare on any arm
    assert "--bare" not in seeded and "--bare" not in absent
    assert str(cfg) in seeded and str(empty) in absent
    assert seeded.index("-p") + 1 == seeded.index("q")
    # All contamination tools must be blocked on both arms
    assert "--disallowedTools" in seeded and "--disallowedTools" in absent
    for tool in DISALLOWED_TOOLS:
        assert tool in seeded, f"missing disallowed tool {tool!r} in seeded arm"
        assert tool in absent, f"missing disallowed tool {tool!r} in absent arm"
    # ToolSearch must NOT be blocked
    assert "ToolSearch" not in seeded and "ToolSearch" not in absent
    # Arms differ only in the mcp-config path
    diffs = [(a, b) for a, b in zip(seeded, absent, strict=False) if a != b]
    assert len(diffs) == 1
    assert diffs[0] == (str(cfg), str(empty))


def test_parse_stream_fallback_to_last_assistant_text_when_result_empty():
    """Extended-thinking + heavy context can produce result.result=''. In that case
    parse_stream falls back to the last assistant text block."""
    from benchmarks.eval.driver import parse_stream

    lines = [
        '{"type":"system","subtype":"init","tools":["mcp__rekall__recall_memories"]}',
        '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"thinking..."}]}}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_1","name":"mcp__rekall__recall_memories","input":{"query":"test"}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_1","content":[{"type":"text","text":"port is 17341"}]}]}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"17341"}]}}',
        '{"type":"result","subtype":"success","result":"","usage":{"input_tokens":10,"output_tokens":500}}',
    ]
    r = parse_stream(lines)
    assert r.answer == "17341", f"expected fallback to assistant text, got: {r.answer!r}"
    assert r.rekall_tool_calls == 1
    assert r.rekall_payload_tokens > 0
    assert r.input_tokens == 10


def test_parse_stream_exposes_rekall_payload_text():
    """parse_stream captures raw tool-result text in rekall_payload_text so callers
    can assert retrieval worked independently of the model's output."""
    from benchmarks.eval.driver import parse_stream

    lines = [
        '{"type":"system","subtype":"init","tools":["mcp__rekall__recall_memories"]}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_pt","name":"mcp__rekall__recall_memories","input":{"query":"port"}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_pt","content":[{"type":"text","text":"FluxSync binds to UDP port 17341"}]}]}}',
        '{"type":"result","subtype":"success","result":"","usage":{"input_tokens":5,"output_tokens":10}}',
    ]
    r = parse_stream(lines)
    assert "17341" in r.rekall_payload_text
    assert r.rekall_tool_calls == 1


def test_parse_stream_handles_tool_result_content_as_string_list():
    """tool_result content can be a list of plain strings (not dicts). parse_stream
    must not crash and must still count payload tokens."""
    from benchmarks.eval.driver import count_tokens, parse_stream

    lines = [
        '{"type":"system","subtype":"init","tools":["mcp__rekall__recall_memories"]}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_s","name":"mcp__rekall__recall_memories","input":{"query":"port"}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_s","content":["port is 17341"]}]}}',
        '{"type":"assistant","message":{"content":[{"type":"text","text":"17341"}]}}',
        '{"type":"result","subtype":"success","result":"17341","usage":{"input_tokens":5,"output_tokens":10}}',
    ]
    r = parse_stream(lines)
    assert r.answer == "17341"
    assert r.rekall_tool_calls == 1
    assert r.rekall_payload_tokens == count_tokens("port is 17341")


def test_parse_stream_fallback_to_post_rekall_thinking_when_text_is_pre_tool():
    """Thinking-only final turn after rekall result, with pre-tool text in _last_text.
    parse_stream must use the thinking that follows the tool result, not the pre-tool text."""
    from benchmarks.eval.driver import parse_stream

    lines = [
        '{"type":"system","subtype":"init","tools":["mcp__rekall__recall_memories"]}',
        # pre-tool text (unhelpful as answer)
        '{"type":"assistant","message":{"content":[{"type":"text","text":"I need to look this up."}]}}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_2","name":"mcp__rekall__recall_memories","input":{"query":"port"}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_2","content":[{"type":"text","text":"port is 17341"}]}]}}',
        # final response: thinking only (no text block) — extended-thinking mode
        '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"The recall returned port 17341."}]}}',
        '{"type":"result","subtype":"success","result":"","usage":{"input_tokens":10,"output_tokens":200}}',
    ]
    r = parse_stream(lines)
    assert "17341" in r.answer, f"expected post-rekall thinking fallback, got: {r.answer!r}"
    assert r.rekall_tool_calls == 1
    assert r.rekall_payload_tokens > 0


def test_parse_stream_tool_result_content_as_plain_string():
    """tool_result content can be a plain string (not a list) for error cases.
    Claude Code serializes tool_use_error as content="<tool_use_error>..." (string).
    Iterating over a string yields individual characters → joined with spaces.
    parse_stream must wrap a string content in a list before iterating."""
    from benchmarks.eval.driver import parse_stream

    lines = [
        '{"type":"system","subtype":"init","tools":["mcp__rekall__recall_memories"]}',
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_err","name":"mcp__rekall__recall_memories","input":{"query":"port"}}]}}',
        # content is a plain string, not a list — this is the error serialization format
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_err","content":"<tool_use_error>Error: No such tool available: mcp__rekall__recall_memories</tool_use_error>"}]}}',
        '{"type":"result","subtype":"success","result":"","usage":{"input_tokens":10,"output_tokens":50}}',
    ]
    r = parse_stream(lines)
    # Must NOT produce char-by-char spaced output
    assert "< t o o l" not in r.rekall_payload_text, "string content iterated char-by-char"
    assert "No such tool available" in r.rekall_payload_text
    assert r.rekall_tool_calls == 1


def test_run_strips_claude_code_session_vars(tmp_path, monkeypatch):
    """run() must use a minimal env to make eval sessions reliable.

    Starting from os.environ leaks CLAUDE_CODE_EFFORT_LEVEL=max (suppresses tool calls)
    and other session vars. Minimal env (HOME, PATH, USER, TMPDIR, LANG, TERM + explicit
    keys) blocks those leaks.
    REKALL_AUTOSAVE must be "0" to prevent session-start-memory.sh from hanging (~219s).
    CLAUDECODE must be "1" to suppress SessionStart hooks while --strict-mcp-config loads
    the eval server's MCP tools.
    ENABLE_TOOL_SEARCH must be "1" (NOT "auto:0") — auto:0 causes Claude Code to exclude
    26 of 28 rekall tools from BOTH context AND deferred pool, so recall_memories is
    completely unreachable. Value "1" keeps all 28 tools non-deferred in the init event.
    """
    import subprocess as _sp

    from benchmarks.eval import driver

    # Inject offending vars into the current process env (monkeypatch restores on teardown)
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "max")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("ENABLE_TOOL_SEARCH", "auto:0")

    captured_env: dict = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        # Return a minimal valid stream-json result so run() doesn't crash.
        fake = _sp.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"type":"result","subtype":"success","result":"ok","usage":{"input_tokens":1,"output_tokens":1}}\n',
            stderr="",
        )
        return fake

    monkeypatch.setattr(_sp, "run", fake_run)

    cfg = tmp_path / "arm.json"
    cfg.write_text('{"mcpServers":{}}')
    driver.run("ping", cfg, "claude-haiku-4-5-20251001", cwd=tmp_path)

    # Parent process vars must NOT bleed through — run() builds a minimal env from scratch.
    assert "CLAUDE_CODE_EFFORT_LEVEL" not in captured_env, (
        "CLAUDE_CODE_EFFORT_LEVEL leaked — max thinking suppresses tool calls"
    )
    assert "ANTHROPIC_MODEL" not in captured_env, (
        "ANTHROPIC_MODEL leaked — overrides the eval model"
    )
    assert "CLAUDE_CODE_CHILD_SESSION" not in captured_env, "CLAUDE_CODE_CHILD_SESSION leaked"
    # Mandatory vars must be set.
    assert captured_env.get("CLAUDECODE") == "1", (
        "CLAUDECODE must be '1' to suppress hooks while keeping MCP via --strict-mcp-config"
    )
    assert captured_env.get("ENABLE_TOOL_SEARCH") == "1", (
        "ENABLE_TOOL_SEARCH must be '1' — auto:0 from settings.json excludes 26 of 28 "
        "rekall tools from both context and deferred pool, making recall_memories unreachable"
    )
    assert captured_env.get("REKALL_AUTOSAVE") == "0", (
        "REKALL_AUTOSAVE must be '0' — session-start-memory.sh hangs otherwise (~219s)"
    )


def test_run_creates_project_settings_to_override_tool_search(tmp_path, monkeypatch):
    """run() creates cwd/.claude/settings.json with ENABLE_TOOL_SEARCH=1.

    settings.json env block has higher precedence than process env. The only reliable
    way to override user-level auto:0 is a project-level settings file in the cwd.
    The file is created only if it doesn't already exist (respects existing project config).
    """
    import json as _json
    import subprocess as _sp

    from benchmarks.eval import driver

    def fake_run(cmd, **kwargs):
        return _sp.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"type":"result","subtype":"success","result":"ok","usage":{"input_tokens":1,"output_tokens":1}}\n',
            stderr="",
        )

    monkeypatch.setattr(_sp, "run", fake_run)

    cfg = tmp_path / "arm.json"
    cfg.write_text('{"mcpServers":{}}')
    driver.run("ping", cfg, "claude-haiku-4-5-20251001", cwd=tmp_path)

    settings_file = tmp_path / ".claude" / "settings.json"
    assert settings_file.exists(), "driver.run() must create cwd/.claude/settings.json"
    data = _json.loads(settings_file.read_text())
    assert data.get("env", {}).get("ENABLE_TOOL_SEARCH") == "1", (
        "cwd/.claude/settings.json must set ENABLE_TOOL_SEARCH=1 to override user-level auto:0"
    )


def test_run_does_not_overwrite_existing_project_settings(tmp_path, monkeypatch):
    """run() skips writing .claude/settings.json if it already exists."""
    import json as _json
    import subprocess as _sp

    from benchmarks.eval import driver

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = claude_dir / "settings.json"
    existing.write_text(_json.dumps({"env": {"ENABLE_TOOL_SEARCH": "existing"}}))

    def fake_run(cmd, **kwargs):
        return _sp.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"type":"result","subtype":"success","result":"ok","usage":{"input_tokens":1,"output_tokens":1}}\n',
            stderr="",
        )

    monkeypatch.setattr(_sp, "run", fake_run)

    cfg = tmp_path / "arm.json"
    cfg.write_text('{"mcpServers":{}}')
    driver.run("ping", cfg, "claude-haiku-4-5-20251001", cwd=tmp_path)

    data = _json.loads(existing.read_text())
    assert data.get("env", {}).get("ENABLE_TOOL_SEARCH") == "existing", (
        "driver.run() must not overwrite existing .claude/settings.json"
    )


def test_fullcontext_prompt_carries_sessions_and_date():
    from benchmarks.eval.driver import build_fullcontext_prompt

    entry = {
        "question": "What did I adopt?",
        "question_date": "2023/05/20",
        "haystack_sessions": [[{"role": "user", "content": "I adopted a cat named Miso."}]],
        "haystack_session_ids": ["s_1"],
        "haystack_dates": ["2023/05/01"],
        "answer_session_ids": ["s_1"],
    }
    p = build_fullcontext_prompt(entry)
    assert "Miso" in p and "s_1" in p and "Today is 2023/05/20" in p
