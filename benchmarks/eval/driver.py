"""claude -p driver: --bare arms, stream-json parsing, cl100k token accounting.

retrieved_context_tokens = tokens of Rekall tool_result payloads ONLY (the
mem0/NEMORI-comparable definition) — never the aggregate input_tokens.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import tiktoken

from benchmarks.dataset import build_session_corpus

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


def build_cmd(prompt: str, mcp_config: Path | None, model: str) -> list[str]:
    """--bare on EVERY arm (hook symmetry); the only arm difference is --mcp-config."""
    cfg = str(mcp_config) if mcp_config else "/dev/null"
    return [
        "claude",
        "-p",
        prompt,
        "--bare",
        "--strict-mcp-config",
        "--mcp-config",
        cfg,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
    ]


def _tool_use_ids(event: dict) -> set[str]:
    ids = set()
    for block in event.get("message", {}).get("content", []) or []:
        if block.get("type") == "tool_use" and str(block.get("name", "")).startswith(
            _REKALL_PREFIX
        ):
            ids.add(block.get("id", ""))
    return ids


def parse_stream(lines: Iterable[str]) -> RunResult:
    answer, in_tok, out_tok, payload_tok, calls = "", 0, 0, 0, 0
    rekall_ids: set[str] = set()
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
        elif etype == "user":
            for block in event.get("message", {}).get("content", []) or []:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in rekall_ids:
                    for part in block.get("content", []) or []:
                        if part.get("type") == "text":
                            payload_tok += count_tokens(part.get("text", ""))
        elif etype == "result":
            answer = event.get("result", "") or ""
            usage = event.get("usage", {}) or {}
            in_tok = int(usage.get("input_tokens", 0))
            out_tok = int(usage.get("output_tokens", 0))
    return RunResult(answer, in_tok, out_tok, payload_tok, calls)


def build_question_prompt(entry: dict) -> str:
    q = entry["question"]
    date = entry.get("question_date")
    return f"Today is {date}. {q}" if date else q


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
    proc = subprocess.run(
        build_cmd(prompt, mcp_config, model),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr[-500:]}")
    return parse_stream(proc.stdout.splitlines())
