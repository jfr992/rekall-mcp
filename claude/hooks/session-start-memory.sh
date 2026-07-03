#!/usr/bin/env bash
# ~/.claude/hooks/session-start-memory.sh
# Fires on SessionStart. Injects a thin Rekall startup capsule, preferring the
# project capsule endpoint and falling back to the unified startup endpoint.
#
# Kill switch: REKALL_AUTOSAVE=0
# Backend URL: REKALL_API_URL (default http://127.0.0.1:8000)
set -euo pipefail

[[ "${REKALL_AUTOSAVE:-1}" == "0" ]] && exit 0

MEMORY_API="${REKALL_API_URL:-http://127.0.0.1:8000}"
INPUT="$(cat || true)"
PROJECT_DIR="$(
  printf '%s' "$INPUT" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("cwd") or d.get("project_dir") or "")' \
      2>/dev/null \
    || true
)"
PROJECT="${CLAUDE_PROJECT_NAME:-$(basename "${PROJECT_DIR:-$(pwd)}")}"
PROJECT_ENCODED="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$PROJECT")"

CAPSULE="$(curl -fsS --max-time 2 "$MEMORY_API/api/memory/capsule?project=$PROJECT_ENCODED" 2>/dev/null || true)"
if [[ -z "$CAPSULE" ]]; then
  CAPSULE="$(curl -fsS --max-time 2 "$MEMORY_API/api/memory/context/startup?project=$PROJECT_ENCODED&agent=claude-code&limit=8" 2>/dev/null || true)"
fi
[[ -z "$CAPSULE" ]] && exit 0

python3 - "$PROJECT" "$CAPSULE" <<'PY'
import json
import sys

project = sys.argv[1]
raw = sys.argv[2]

try:
    payload = json.loads(raw) if raw else {}
except json.JSONDecodeError:
    payload = {}


def _item_text(item):
    if isinstance(item, dict):
        date = item.get("date") or "unknown"
        content = " ".join(str(item.get("content") or "").split())
        return f"- [{date}] {content}" if content else ""
    return f"- {str(item)}"


def _render_capsule(data):
    if data.get("startup_summary"):
        return str(data["startup_summary"])

    lines = []
    warnings = data.get("health_warnings") or data.get("warnings") or []
    if warnings:
        lines.append("Health Warnings")
        lines.extend(f"- {warning}" for warning in warnings[:6])
        lines.append("")

    if data.get("project"):
        lines.append(f"Project Capsule: {data['project']}")
    if lines:
        lines.append("")

    sections = [
        ("Standing Context", "standing_context"),
        ("Active Workstreams", "active_workstreams"),
        ("Operating Rules", "operating_rules"),
        ("Danger Zones", "danger_zones"),
        ("Open Loops", "open_loops"),
    ]
    for title, key in sections:
        items = data.get(key) or []
        if not items:
            continue
        lines.append(title)
        rendered = [_item_text(item) for item in items[:4]]
        lines.extend(line for line in rendered if line)
        lines.append("")

    if not lines:
        return json.dumps(data, indent=2)
    return "\n".join(lines).strip()


text = _render_capsule(payload)[:3500]
instruction = (
    "Use Rekall for targeted recall. Save durable decisions, requirements, "
    "root causes, and user preferences."
)

print(
    json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    f"== REKALL STARTUP ({project}) ==\n"
                    f"{text}\n\n"
                    f"{instruction}\n"
                    "== END REKALL STARTUP =="
                ),
            }
        }
    )
)
PY
