"""claude -p driver: stream-json parsing, cl100k token accounting.

retrieved_context_tokens = tokens of Rekall tool_result payloads ONLY (the
mem0/NEMORI-comparable definition) — never the aggregate input_tokens.

Deviation from original spec: --bare is not used on any arm.
--bare disables macOS Keychain OAuth lookup (auth stored keyed to CLAUDE_CONFIG_DIR
path hash). Instead, both arms run without --bare; --strict-mcp-config limits which
MCP servers are active. Absent arm uses an empty {"mcpServers":{}} config file (not
/dev/null — the CLI rejects empty/non-JSON files as "not valid JSON"). Hooks fire
but parse_stream ignores all type=system events, so eval results are unaffected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import tiktoken

from benchmarks.dataset import build_session_corpus

# Arms are pure Q&A: the agent may use ONLY ToolSearch (deferred MCP schema loading)
# and mcp__rekall__* (memory retrieval — under measurement). Everything else is a
# contamination channel and is DENIED via --disallowedTools.
#
# Why a denylist, not an allowlist: --allowedTools is INERT under --permission-mode
# bypassPermissions (which headless eval runs require) — bypass permits every tool
# regardless of the allowlist, so the agent wanders into Bash/Read and never recalls.
# --disallowedTools is a HARD block that IS enforced under bypass. A leaky-but-enforced
# denylist beats an airtight-but-inert allowlist. (Regression: an allowlist here dropped
# er+xp 18/21 -> 7/21 because the seeded agent explored the workspace via Bash instead
# of calling recall_memories.) Guarded by test_no_bash_under_bypass (eval_live).
DISALLOWED_TOOLS: tuple[str, ...] = (
    # disk read — absent arm could read the seeded YAML on disk, destroying the delta
    "Bash",
    "Read",
    "Grep",
    "Glob",
    # side effects in a read-only eval
    "Write",
    "Edit",
    "NotebookEdit",
    # external lookup — answer from the web, not from memory
    "WebFetch",
    "WebSearch",
    # delegation / child processes — their mcp__rekall__* traffic is invisible to parse_stream
    "Agent",
    "Skill",
    "Task",
    "Workflow",
    "SendMessage",
    # background / scheduling / worktree — spawn or defer work outside the measured turn
    "Monitor",
    "EnterWorktree",
    "ExitWorktree",
    "RemoteTrigger",
    "ScheduleWakeup",
    "CronCreate",
    "CronDelete",
    "CronList",
    "PushNotification",
    "DesignSync",
    # task management
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    # arbitrary MCP resource reads + misc
    "ListMcpResourcesTool",
    "ReadMcpResourceTool",
    "ReadMcpResourceDirTool",
    "LSP",
    "ReportFindings",
)

_ENC = tiktoken.get_encoding("cl100k_base")
_REKALL_PREFIX = "mcp__rekall__"


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


@dataclass
class RunResult:
    answer: str
    input_tokens: int
    output_tokens: int
    rekall_payload_tokens: int
    rekall_tool_calls: int
    rekall_payload_text: str = ""
    prompt_tokens: int = 0


def build_cmd(prompt: str, mcp_config: Path, model: str) -> list[str]:
    """Build the claude -p command. Both arms use --strict-mcp-config to isolate MCPs.

    The seeded arm passes a real config pointing at the ephemeral backend (root URL, not /mcp).
    The absent arm passes an empty {"mcpServers":{}} file — handled by run().
    No --bare: it disables macOS Keychain OAuth auth in this environment.

    Arms use --disallowedTools (a hard block enforced under bypassPermissions, unlike
    --allowedTools which bypass ignores). Only ToolSearch and mcp__rekall__* survive.
    See DISALLOWED_TOOLS for the rationale.
    """
    return [
        "claude",
        "-p",
        prompt,
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config),
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]


def _tool_use_ids(event: dict) -> set[str]:
    ids = set()
    for block in event.get("message", {}).get("content", []) or []:
        if block.get("type") == "tool_use" and str(block.get("name", "")).startswith(
            _REKALL_PREFIX
        ):
            ids.add(block.get("id", ""))
    return ids


def _last_assistant_text(event: dict) -> str:
    """Extract the last text block from an assistant event."""
    last = ""
    for block in event.get("message", {}).get("content", []) or []:
        if block.get("type") == "text":
            last = block.get("text", "")
    return last


def _last_assistant_thinking(event: dict) -> str:
    """Extract the last thinking block from an assistant event."""
    last = ""
    for block in event.get("message", {}).get("content", []) or []:
        if block.get("type") == "thinking":
            last = block.get("thinking", "")
    return last


def parse_stream(lines: Iterable[str]) -> RunResult:
    answer, in_tok, out_tok, payload_tok, calls = "", 0, 0, 0, 0
    rekall_ids: set[str] = set()
    # Fallback chain: result.result → post-rekall text → post-rekall thinking → any text.
    # Extended thinking can produce result.result='' and a thinking-only final response.
    # Track what arrives AFTER a rekall tool_result to avoid confusing pre-tool narrative
    # with the answer.
    _last_text = ""
    _post_rekall_text = ""
    _post_rekall_thinking = ""
    _saw_rekall_result = False
    payload_parts: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "assistant":
            new = _tool_use_ids(event)
            calls += len(new)
            rekall_ids |= new
            t = _last_assistant_text(event)
            if t:
                _last_text = t
                if _saw_rekall_result:
                    _post_rekall_text = t
            th = _last_assistant_thinking(event)
            if th and _saw_rekall_result:
                _post_rekall_thinking = th
        elif etype == "user":
            for block in event.get("message", {}).get("content", []) or []:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in rekall_ids:
                    _saw_rekall_result = True
                    # content can be a plain string (tool_use_error), a list of strings,
                    # or a list of {"type":"text","text":"..."} dicts — normalise to list.
                    _content = block.get("content", []) or []
                    if isinstance(_content, str):
                        _content = [_content]
                    for part in _content:
                        if isinstance(part, str):
                            payload_tok += count_tokens(part)
                            payload_parts.append(part)
                        elif isinstance(part, dict) and part.get("type") == "text":
                            txt = part.get("text", "")
                            payload_tok += count_tokens(txt)
                            payload_parts.append(txt)
        elif etype == "result":
            answer = event.get("result", "") or ""
            usage = event.get("usage", {}) or {}
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
    if not answer:
        answer = _post_rekall_text or _post_rekall_thinking or _last_text
    return RunResult(answer, in_tok, out_tok, payload_tok, calls, " ".join(payload_parts))


def build_question_prompt(entry: dict) -> str:
    q = entry["question"]
    date = entry.get("question_date")
    return f"Today is {date}. {q}" if date else q


# The line rekall-restore.sh injects at session start in a real deployment.
# The seeded arm measures the product AS SHIPPED — without it, agents never
# reach for memory tools (measured: 2% accuracy, ~4 tokens/query).
# Format matches the hook's jq output: stats="N memories · M nodes · K edges"
# plus vectors=" · vectors OK", giving: "Rekall ready — N · M · K · vectors OK. ..."
REKALL_SESSION_PREAMBLE = (
    "Rekall ready — {n} memories · {nodes} nodes · {edges} edges"
    " · vectors OK. Use recall_memories() on demand."
)


def build_seeded_prompt(
    entry: dict,
    n_memories: int,
    nodes: int | None = None,
    edges: int | None = None,
) -> str:
    """Product-as-deployed prompt: restore-hook preamble + the question.

    nodes defaults to n_memories (an ephemeral per-item store has ~n nodes).
    edges defaults to 0 (no cross-session links in a freshly seeded store).
    """
    if nodes is None:
        nodes = n_memories
    if edges is None:
        edges = 0
    return (
        f"{REKALL_SESSION_PREAMBLE.format(n=n_memories, nodes=nodes, edges=edges)}"
        f"\n\n{build_question_prompt(entry)}"
    )


def build_fullcontext_prompt(entry: dict, include_assistant: bool = False) -> str:
    docs = build_session_corpus(entry, include_assistant=include_assistant)
    haystack = "\n\n".join(f"[session {d['session_id']} | {d['date']}]\n{d['text']}" for d in docs)
    return (
        "Here is the user's conversation history:\n\n"
        f"{haystack}\n\n"
        f"Based only on the history above, answer: {build_question_prompt(entry)}"
    )


def run(
    prompt: str,
    mcp_config: Path | None,
    model: str,
    cwd: Path,
    timeout_s: int = 300,
) -> RunResult:
    """Run one claude -p arm.

    When mcp_config is None (absent arm), creates a temp empty config so that
    --strict-mcp-config loads no MCP servers (/dev/null is rejected as invalid JSON).
    """
    # Create project-level settings to override user settings.json env block.
    # settings.json env block has higher precedence than process env, so setting
    # ENABLE_TOOL_SEARCH=1 in the env dict alone is insufficient — the user's
    # auto:0 wins. A cwd/.claude/settings.json with ENABLE_TOOL_SEARCH=1 overrides it.
    # ponytail: only create if absent; respect existing project configs.
    import json as _json

    _project_settings = cwd / ".claude" / "settings.json"
    if not _project_settings.exists():
        _project_settings.parent.mkdir(exist_ok=True)
        _project_settings.write_text(_json.dumps({"env": {"ENABLE_TOOL_SEARCH": "1"}}))

    _tmpdir: str | None = None
    _cfg = mcp_config
    if _cfg is None:
        _tmpdir = tempfile.mkdtemp(prefix="claude-eval-nomcp-")
        _empty = Path(_tmpdir) / "empty.json"
        _empty.write_text('{"mcpServers":{}}')
        _cfg = _empty
    # Use a minimal env for the inner subprocess to block session var leakage.
    # CLAUDE_CODE_EFFORT_LEVEL=max from the parent suppresses tool calls entirely.
    # ponytail: explicit set beats glob-strip so the intent is clear.
    import os

    env: dict[str, str] = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "USER": os.environ.get("USER", ""),
        "TMPDIR": os.environ.get("TMPDIR", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        # Claude Code child-session signal (does NOT suppress hooks; REKALL_AUTOSAVE=0 is what gates the rekall hooks).
        "CLAUDECODE": "1",
        # Disable rekall hooks: session-start-memory.sh hangs ~219s without this.
        "REKALL_AUTOSAVE": "0",
        # Override settings.json's "auto:0" — auto:0 excludes 26 of 28 rekall tools from
        # both context AND deferred pool, making recall_memories completely unreachable.
        # "1" keeps all 28 tools non-deferred in the init event.
        "ENABLE_TOOL_SEARCH": "1",
    }
    try:
        proc = subprocess.run(
            build_cmd(prompt, _cfg, model),
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout_s,
            env=env,
            # claude -p appends piped stdin to the prompt — an inherited stdin
            # (pytest, heredocs) silently contaminates the eval question.
            stdin=subprocess.DEVNULL,
        )
    finally:
        if _tmpdir:
            shutil.rmtree(_tmpdir, ignore_errors=True)
    if proc.returncode != 0:
        _diag = (proc.stderr or "")[-300:] or (proc.stdout or "")[-300:] or "(no output)"
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {_diag}")
    result = parse_stream(proc.stdout.splitlines())
    result.prompt_tokens = count_tokens(prompt)
    # ponytail: debug dump under REKALL_EVAL_DEBUG so the live test can read stderr
    import os as _os

    _debug = _os.getenv("REKALL_EVAL_DEBUG")
    if _debug:
        import pathlib

        pathlib.Path(_debug + ".stdout").write_text(proc.stdout or "")
        pathlib.Path(_debug + ".stderr").write_text(proc.stderr or "")
        pathlib.Path(_debug + ".env").write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(env.items()))
        )
        pathlib.Path(_debug + ".meta").write_text(
            f"cwd={cwd}\nproject_settings={_project_settings}\nexists={_project_settings.exists()}\n"
        )
    return result
