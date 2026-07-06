"""Live 1-probe end-to-end: seeded recall hits + nonzero retrieved tokens.

Costs ~2 claude -p calls. Run: uv run --extra dev pytest -m eval_live -v
Requires: docker compose up qdrant-test -d; claude CLI authed.

Deviation from brief template: MCP URL uses b.base_url (server mounts MCP at root /,
not /mcp). --bare is not used on any arm: it disables macOS Keychain OAuth auth.
driver.run() sets ENABLE_TOOL_SEARCH=1 (overriding settings.json auto:0) so all 28
rekall tools appear non-deferred in the init event. auto:0 excludes 26 of 28 tools
from both context and deferred pool — recall_memories becomes completely unreachable.
"""

import json
import os
import subprocess

import pytest


@pytest.mark.eval_live
def test_no_bash_under_bypass(tmp_path):
    """Regression guard for the allowlist-inert-under-bypass bug: prove Bash is
    actually blocked. An allowlist here let the seeded agent explore the workspace
    via Bash instead of recalling (er+xp 18/21 -> 7/21). The denylist must hard-block
    it even under --permission-mode bypassPermissions.
    """
    from benchmarks.eval.driver import build_cmd
    from benchmarks.eval.env import make_workspace

    ws = make_workspace(tmp_path, "nobash")  # has .git/.claude — the decoy that tempts Bash
    cfg = tmp_path / "empty.json"
    cfg.write_text(json.dumps({"mcpServers": {}}))
    env = {k: os.environ.get(k, "") for k in ("HOME", "PATH", "USER", "TMPDIR", "LANG", "TERM")}
    env.update(CLAUDECODE="1", REKALL_AUTOSAVE="0", ENABLE_TOOL_SEARCH="1")
    prompt = "Use the Bash tool to run `ls -la` and report what you see."
    proc = subprocess.run(
        build_cmd(prompt, cfg, "claude-haiku-4-5-20251001"),
        capture_output=True,
        text=True,
        cwd=str(ws),
        timeout=180,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    bash_calls = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []) or []:
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    bash_calls.append(block.get("input"))
    assert not bash_calls, f"Bash was invocable under bypass — denylist not enforced: {bash_calls}"


@pytest.mark.eval_live
def test_one_probe_end_to_end(tmp_path):
    from benchmarks.eval import driver
    from benchmarks.eval.env import EphemeralBackend, make_workspace

    ws = make_workspace(tmp_path, "live01")
    with EphemeralBackend(storage_path=tmp_path / "store") as b:
        b.wipe()
        # Clearly fictional scenario to prevent hallucination from training context.
        b.seed(
            [
                {
                    "summary": "FluxSync notification daemon binds to UDP port 17341.",
                    "type": "decision",
                }
            ],
            cwd=str(ws),
        )
        # agent-free retrieval sanity (the seeding CRITICAL guard)
        assert b.recall_ids("FluxSync notification daemon port", project=ws.name)

        cfg = tmp_path / "arm.json"
        # Server mounts MCP at root /, not /mcp — use base_url directly.
        cfg.write_text(json.dumps({"mcpServers": {"rekall": {"type": "http", "url": b.base_url}}}))
        # All 28 rekall tools are non-deferred (driver.run() sets ENABLE_TOOL_SEARCH=1
        # overriding settings.json auto:0). Direct call works without ToolSearch scaffolding.
        # Retry up to 3 times: extended thinking can produce a thinking-only final
        # response with result.result=''. The parse_stream fallback handles that.
        prompt = (
            "Call mcp__rekall__recall_memories with query "
            "'FluxSync notification daemon UDP port'. "
            "Report the port number from the result."
        )
        out = None
        for _attempt in range(3):
            out = driver.run(prompt, cfg, "claude-haiku-4-5-20251001", cwd=ws)
            if (
                out.rekall_tool_calls >= 1
                and out.rekall_payload_tokens > 0
                and "17341" in out.rekall_payload_text
            ):
                break
        assert out is not None
        # Primary: recall tool was called and returned the correct memory.
        # rekall_payload_text is the raw tool-result text — model's output interpretation
        # is unreliable in heavy-context (extended thinking), but data flow is testable.
        assert out.rekall_tool_calls >= 1
        assert out.rekall_payload_tokens > 0
        assert "17341" in out.rekall_payload_text
