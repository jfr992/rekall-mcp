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
page_id = re.compile(r"[a-z0-9][a-z0-9._-]*/(?:process|policy|reference|entity)/[a-z0-9][a-z0-9-]*")


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
wiki_tool_ids = {
    tool_id
    for tool_id, name in tool_names.items()
    if "wiki_lookup" in name or "wiki_read" in name
}
delivered = {"explicit": [], "capsule": [], "reflex": [], "wiki": []}
first_recall_index = None
first_delivery_index = None


def _add(bucket, ids):
    for mid in ids:
        if mid not in delivered[bucket]:
            delivered[bucket].append(mid)


def _envelope_context(stdout):
    try:
        envelope = json.loads(stdout or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(envelope, dict):
        return ""
    output = envelope.get("hookSpecificOutput")
    if not isinstance(output, dict):
        return ""
    context = output.get("additionalContext") or ""
    return context if isinstance(context, str) else ""


def _attachment_text(entry):
    if entry.get("hookEvent") == "PreToolUse":
        # Older transcripts carry the reflex envelope on the entry itself.
        return _envelope_context(entry.get("stdout", ""))
    att = entry.get("attachment") or {}
    if att.get("type") == "hook_additional_context":
        content = att.get("content")
        return "\n".join(c for c in content if isinstance(c, str)) if isinstance(content, list) else str(content or "")
    if att.get("type") == "hook_success":
        return _envelope_context(att.get("stdout", ""))
    return ""


for index, entry in enumerate(entries):
    kind = entry.get("type")
    if kind == "user":
        for block in content_blocks(entry):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id", "") in recall_tool_ids:
                _add("explicit", memory_id.findall(result_text(block)))
                if first_recall_index is None:
                    first_recall_index = index
                if first_delivery_index is None:
                    first_delivery_index = index
        for block in content_blocks(entry):
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id", "") in wiki_tool_ids:
                _add("wiki", page_id.findall(result_text(block)))
                if first_delivery_index is None:
                    first_delivery_index = index
    elif kind == "attachment":
        text = _attachment_text(entry)
        if "REKALL REFLEX" in text:
            _add("reflex", memory_id.findall(text))
            if first_recall_index is None:
                first_recall_index = index
        elif "REKALL STARTUP" in text:
            _add("capsule", memory_id.findall(text))
        else:
            continue
        if first_delivery_index is None:
            first_delivery_index = index

memory_delivered = set(delivered["explicit"]) | set(delivered["capsule"]) | set(delivered["reflex"])
all_delivered = memory_delivered | set(delivered["wiki"])
if not all_delivered:
    raise SystemExit(0)

# A reference is the id in the agent text or tool arguments, never in a tool_result.
referenced = []
for index, entry in enumerate(entries):
    if entry.get("type") != "assistant" or (first_delivery_index is not None and index <= first_delivery_index):
        continue
    for block in content_blocks(entry):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            found = memory_id.findall(text) + page_id.findall(text)
        elif block.get("type") == "tool_use":
            if block.get("id") in wiki_tool_ids:
                continue  # wiki_read(page_id=X) after a lookup is navigation, not a citation
            args = json.dumps(block.get("input", {}))
            found = memory_id.findall(args) + page_id.findall(args)
        else:
            continue
        for mid in found:
            if mid in all_delivered and mid not in referenced:
                referenced.append(mid)

edits = 0
test_passes = 0
bash_test_ids = set()
for index, entry in enumerate(entries):
    if first_recall_index is None or index <= first_recall_index:
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
            "recalled_ids": sorted(memory_delivered),
            "delivered": delivered,
            "referenced": referenced,
            "coverage": {"transcript_tail_bytes": limit, "truncated": bool(start)},
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
