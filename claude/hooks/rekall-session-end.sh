#!/usr/bin/env bash
# ~/.claude/hooks/rekall-session-end.sh
# Fires once on SessionEnd. Emits a bounded, content-free utility summary for
# memories actually recalled during the session. Never blocks session exit.
#
# Kill switch: REKALL_AUTOSAVE=0
# Backend URL: REKALL_API_URL, then legacy REKALL_URL
set -uo pipefail

API="${REKALL_API_URL:-${REKALL_URL:-http://localhost:8000}}"
[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

payload="$(cat 2>/dev/null || true)"
transcript_path="$(jq -r '.transcript_path // ""' <<<"$payload" 2>/dev/null || true)"
session_id="$(jq -r '.session_id // ""' <<<"$payload" 2>/dev/null || true)"
caller_cwd="$(jq -r '.cwd // ""' <<<"$payload" 2>/dev/null || true)"
hook_event="$(jq -r '.hook_event_name // ""' <<<"$payload" 2>/dev/null || true)"

[[ -n "$hook_event" && "$hook_event" != "SessionEnd" ]] && exit 0
[[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0
[[ -z "$session_id" ]] && session_id="${CLAUDE_SESSION_ID:-$(basename "$transcript_path" .jsonl)}"
[[ -z "$session_id" ]] && exit 0
[[ -z "$caller_cwd" ]] && caller_cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

# The restore marker proves this Claude session was Rekall-enabled and avoids
# telemetry attempts when the backend was unavailable at startup.
marker="${REKALL_MARKER_DIR:-/tmp}/rekall-restored-${session_id}"
[[ -f "$marker" ]] || exit 0

tail_bytes="${REKALL_TRANSCRIPT_TAIL_BYTES:-1048576}"
[[ "$tail_bytes" =~ ^[1-9][0-9]*$ ]] || tail_bytes=1048576
(( tail_bytes > 16777216 )) && tail_bytes=16777216
project="$(basename "$caller_cwd")"

summary_json="$(python3 - "$transcript_path" "$project" "$session_id" "$tail_bytes" 2>/dev/null <<'PY' || true
import json
import re
import sys


transcript_path, project, session_id, raw_limit = sys.argv[1:]
limit = int(raw_limit)
memory_id = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z]+_[0-9a-f]+")


def content_blocks(entry):
    content = entry.get("message", {}).get("content", [])
    return content if isinstance(content, list) else []


def result_text(block):
    raw = block.get("content", "")
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, list):
        return ""
    return "".join(
        item.get("text", "")
        for item in raw
        if isinstance(item, dict) and item.get("type") == "text"
    )


try:
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, 2)
        size = transcript.tell()
        start = max(0, size - limit)
        transcript.seek(start)
        data = transcript.read(limit)
except OSError:
    raise SystemExit(0)

# A byte tail can begin inside a UTF-8 character or JSONL record. Discard the
# incomplete first record whenever truncation occurred.
if start:
    newline = data.find(b"\n")
    if newline < 0:
        raise SystemExit(0)
    data = data[newline + 1 :]

entries = []
tool_names = {}
for line in data.decode("utf-8", errors="replace").splitlines():
    try:
        entry = json.loads(line)
    except (TypeError, ValueError):
        continue
    if not isinstance(entry, dict):
        continue
    entries.append(entry)
    if entry.get("type") != "assistant":
        continue
    for block in content_blocks(entry):
        if not (isinstance(block, dict) and block.get("type") == "tool_use"):
            continue
        tool_id = block.get("id")
        if tool_id:
            tool_names[tool_id] = block.get("name", "")

recall_tool_ids = {
    tool_id
    for tool_id, name in tool_names.items()
    if "recall" in name.lower() or "reflex" in name.lower()
}
recalled = set()
first_recall_index = None

for index, entry in enumerate(entries):
    if entry.get("type") != "user":
        continue
    for block in content_blocks(entry):
        if not (isinstance(block, dict) and block.get("type") == "tool_result"):
            continue
        if block.get("tool_use_id", "") not in recall_tool_ids:
            continue
        recalled.update(memory_id.findall(result_text(block)))
        if first_recall_index is None:
            first_recall_index = index

# Reflex context is recorded as a PreToolUse attachment rather than a normal
# tool result. Only the explicitly framed Rekall packet is considered.
for index, entry in enumerate(entries):
    if entry.get("type") != "attachment" or entry.get("hookEvent") != "PreToolUse":
        continue
    try:
        envelope = json.loads(entry.get("stdout", ""))
    except (TypeError, ValueError):
        continue
    context = envelope.get("hookSpecificOutput", {}).get("additionalContext") or ""
    if not isinstance(context, str) or "REKALL REFLEX" not in context:
        continue
    recalled.update(memory_id.findall(context))
    if first_recall_index is None or index < first_recall_index:
        first_recall_index = index

if not recalled:
    raise SystemExit(0)

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
            "recalled_ids": sorted(recalled),
            "edits_after_recall": edits,
            "test_passes_after_recall": test_passes,
        },
        separators=(",", ":"),
    )
)
PY
)"

[[ -n "$summary_json" ]] || exit 0
curl -sfo /dev/null --connect-timeout 0.1 --max-time 1 \
  -X POST "$API/api/memory/events" \
  -H "Content-Type: application/json" \
  -d "$summary_json" 2>/dev/null || true

exit 0
