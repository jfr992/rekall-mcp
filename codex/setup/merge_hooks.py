#!/usr/bin/env python3
"""Safely migrate Codex hooks without disturbing unrelated configuration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

EVENTS = ("SessionStart", "PreToolUse", "PreCompact", "PostCompact", "PostToolUse", "SessionEnd")
LEGACY = (
    "rekall-restore.sh",
    "rekall-observe.sh",
    "rekall-reflex.sh",
    "rekall-precompact.sh",
    "rekall-postcompact.sh",
    "rekall-commit-nudge.sh",
    "memory-prune.sh",
    "session-context.sh",
)
SPEC: dict[str, tuple[str, int, int | None]] = {
    "SessionStart": ("", 5, 1200),
    "PreToolUse": ("Bash", 2, 800),
    "PreCompact": ("", 2, None),
    "PostCompact": ("", 2, None),
    "PostToolUse": ("Bash", 2, 300),
    "SessionEnd": ("", 3, None),
}


def _known_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return any(Path(token).name in LEGACY for token in tokens)


def _canonical_command(command: object, adapter: Path | str, event: str) -> bool:
    """Recognize only the exact invocation emitted by this merger.

    In particular, a vendor command that happens to mention ``rekall_hook.py``
    or passes extra flags is foreign and must survive migration.
    """
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) == 3 and tokens[0] == "python3" and tokens[2] == event:
        adapter_token = tokens[1]
    elif (
        len(tokens) in {5, 6}
        and tokens[0] == "env"
        and tokens[1].startswith("REKALL_API_URL=")
        and (len(tokens) == 5 or tokens[2].startswith("REKALL_API_TOKEN_ENV_VAR="))
        and tokens[-3] == "python3"
        and tokens[-1] == event
    ):
        adapter_token = tokens[-2]
    else:
        return False
    try:
        return Path(adapter_token).expanduser().resolve() == Path(adapter).expanduser().resolve()
    except OSError:
        return False


def _validated_api_url(api_url: str) -> str:
    try:
        parsed = urlsplit(api_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("api URL must be credential-free HTTP(S)") from exc
    return api_url


def canonical_entries(
    adapter: Path | str,
    api_url: str = "http://localhost:8000",
    bearer_token_env_var: str = "",
) -> dict[str, list[dict[str, Any]]]:
    """Return the sole canonical representation (also used by the example)."""
    auth_env = ""
    if bearer_token_env_var:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", bearer_token_env_var):
            raise ValueError("bearer token environment variable name is invalid")
        auth_env = f" REKALL_API_TOKEN_ENV_VAR={bearer_token_env_var}"
    command_base = (
        f"env REKALL_API_URL={shlex.quote(_validated_api_url(api_url))}{auth_env} "
        f"python3 {shlex.quote(str(adapter))}"
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for event in EVENTS:
        matcher, timeout, limit = SPEC[event]
        handler: dict[str, Any] = {
            "type": "command",
            "command": f"{command_base} {event}",
            "timeout": timeout,
        }
        if limit is not None:
            handler["additionalContextLimit"] = limit
        result[event] = [{"matcher": matcher, "hooks": [handler]}]
    return result


def merge(
    existing: dict[str, Any],
    adapter: Path | str,
    api_url: str = "http://localhost:8000",
    bearer_token_env_var: str = "",
) -> dict[str, Any]:
    hooks = existing.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise ValueError(f"hooks.{event} must be a list")
    output = dict(existing)
    cleaned: dict[str, list[Any]] = {}
    for event, entries in hooks.items():
        kept_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            children = entry.get("hooks")
            if not isinstance(children, list):
                kept_entries.append(entry)
                continue
            kept = [
                child
                for child in children
                if not (
                    isinstance(child, dict)
                    and (
                        _known_command(child.get("command"))
                        or _canonical_command(child.get("command"), adapter, event)
                    )
                )
            ]
            if kept:
                item = dict(entry)
                item["hooks"] = kept
                kept_entries.append(item)
        if kept_entries:
            cleaned[event] = kept_entries
    for event, canonical in canonical_entries(adapter, api_url, bearer_token_env_var).items():
        # Keep foreign entries in place and append exactly one canonical entry.
        cleaned[event] = cleaned.get(event, []) + canonical
    output["hooks"] = cleaned
    return output


def write_atomic(path: Path, data: dict[str, Any]) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), mode)
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hooks-file", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--bearer-token-env-var", default="")
    args = parser.parse_args(argv)
    if any(part.lower() == "memories" for part in args.hooks_file.parts + args.adapter.parts):
        parser.error("native memory paths are not permitted")
    try:
        raw = args.hooks_file.read_text(encoding="utf-8") if args.hooks_file.exists() else "{}"
        existing = json.loads(raw)
        if not isinstance(existing, dict):
            raise ValueError("root must be an object")
        output = merge(existing, args.adapter, args.api_url, args.bearer_token_env_var)
        write_atomic(args.hooks_file, output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"merge_hooks: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
