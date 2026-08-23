#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BUNDLE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE_ADAPTER="$BUNDLE_ROOT/hooks/rekall_hook.py"
SOURCE_SKILL="$BUNDLE_ROOT/skills/rekall-memory/SKILL.md"
MERGER="$SCRIPT_DIR/merge_hooks.py"

CODEX_HOME_INPUT="${CODEX_HOME:-$HOME/.codex}"
MCP_URL="${REKALL_API_URL:-http://localhost:8000}"
API_URL=""
API_URL_EXPLICIT=0
ALLOW_REMOTE=0

usage() {
  cat <<'EOF'
Usage: install.sh [--mcp-url URL] [--api-url URL] [--allow-remote-mcp]

Installs Rekall's Codex hooks and MCP-first skill without changing native
Codex memory. Use --api-url when the MCP transport has a path. Remote URLs
require --allow-remote-mcp.
EOF
}

fail() {
  printf 'Rekall Codex install failed: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mcp-url)
      [ "$#" -ge 2 ] || fail "--mcp-url requires a value"
      MCP_URL="$2"
      shift 2
      ;;
    --api-url)
      [ "$#" -ge 2 ] || fail "--api-url requires a value"
      API_URL="$2"
      API_URL_EXPLICIT=1
      shift 2
      ;;
    --allow-remote-mcp)
      ALLOW_REMOTE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument"
      ;;
  esac
done

for dependency in python3 curl codex; do
  command -v "$dependency" >/dev/null 2>&1 || fail "required command is unavailable: $dependency"
done
for source_file in "$SOURCE_ADAPTER" "$SOURCE_SKILL" "$MERGER"; do
  [ -f "$source_file" ] || fail "installation bundle is incomplete"
done

CODEX_HOME="$({
  CODEX_HOME_INPUT="$CODEX_HOME_INPUT" python3 - <<'PY'
import os
import sys
from pathlib import Path

path = Path(os.environ["CODEX_HOME_INPUT"]).expanduser().resolve()
if any(part.lower() == "memories" for part in path.parts):
    raise SystemExit(2)
print(path)
PY
} 2>/dev/null)" || fail "CODEX_HOME cannot be a native memory path"

validate_url() {
  URL_INPUT="$1" URL_KIND="$2" ALLOW_REMOTE="$ALLOW_REMOTE" python3 - <<'PY'
import ipaddress
import os
from urllib.parse import urlsplit, urlunsplit

raw = os.environ["URL_INPUT"]
kind = os.environ["URL_KIND"]
allow_remote = os.environ["ALLOW_REMOTE"] == "1"
try:
    if raw != raw.strip() or any(char.isspace() for char in raw):
        raise ValueError
    parsed = urlsplit(raw)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError
    hostname = host.rstrip(".").lower()
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname == "localhost"
    if not allow_remote and (parsed.scheme != "http" or not loopback):
        raise ValueError
    # urlsplit validates the port lazily.
    parsed.port
except (TypeError, ValueError):
    raise SystemExit(2)
path = parsed.path
if kind == "api":
    path = path.rstrip("/")
print(urlunsplit((parsed.scheme, parsed.netloc, path, "", "")))
PY
}

MCP_URL="$(validate_url "$MCP_URL" mcp 2>/dev/null)" || \
  fail "MCP URL is invalid or requires --allow-remote-mcp"

if [ "$API_URL_EXPLICIT" -eq 0 ]; then
  API_URL="$({
    MCP_URL_INPUT="$MCP_URL" python3 - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit

parsed = urlsplit(os.environ["MCP_URL_INPUT"])
if parsed.path not in {"", "/"}:
    raise SystemExit(2)
print(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
PY
  } 2>/dev/null)" || fail "MCP URLs with a path require a separate --api-url"
fi
API_URL="$(validate_url "$API_URL" api 2>/dev/null)" || \
  fail "API URL is invalid or requires --allow-remote-mcp"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rekall-codex-install.XXXXXX")"
DEST_ADAPTER="$CODEX_HOME/hooks/rekall_hook.py"
DEST_SKILL="$CODEX_HOME/skills/rekall-memory/SKILL.md"
HOOKS_FILE="$CODEX_HOME/hooks.json"
BACKUP_DIR=""
cleanup_work_dir() {
  python3 - "$WORK_DIR" <<'PY' >/dev/null 2>&1 || true
import shutil
import sys

shutil.rmtree(sys.argv[1], ignore_errors=True)
PY
}

INSTALL_SUCCEEDED=0
MCP_ADDED=0
ADAPTER_CHANGED=0
ADAPTER_EXISTED=0
SKILL_CHANGED=0
SKILL_EXISTED=0
HOOKS_CHANGED=0
HOOKS_EXISTED=0

file_mode() {
  stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"
}

rollback_file() {
  changed_flag="$1"
  existed_flag="$2"
  backup_path="$3"
  destination="$4"
  [ "$changed_flag" -eq 1 ] || return 0
  if [ "$existed_flag" -eq 1 ]; then
    [ -f "$backup_path" ] || return 0
    atomic_copy "$backup_path" "$destination" "$(file_mode "$backup_path")"
  else
    rm -f -- "$destination" 2>/dev/null || true
  fi
}

rollback_install() {
  rollback_file "$HOOKS_CHANGED" "$HOOKS_EXISTED" "$BACKUP_DIR/hooks.json" "$HOOKS_FILE"
  rollback_file \
    "$SKILL_CHANGED" "$SKILL_EXISTED" \
    "$BACKUP_DIR/skills/rekall-memory/SKILL.md" "$DEST_SKILL"
  rollback_file \
    "$ADAPTER_CHANGED" "$ADAPTER_EXISTED" \
    "$BACKUP_DIR/hooks/rekall_hook.py" "$DEST_ADAPTER"
  if [ "$MCP_ADDED" -eq 1 ]; then
    codex mcp remove rekall >/dev/null 2>&1 || true
  fi
}

on_exit() {
  exit_code=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$INSTALL_SUCCEEDED" -ne 1 ]; then
    rollback_install
  fi
  cleanup_work_dir
  exit "$exit_code"
}
trap on_exit EXIT
trap 'exit 130' HUP INT TERM

mcp_config_matches() {
  MCP_EXPECTED_URL="$MCP_URL" python3 - "$1" <<'PY'
import json
import os
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        data = json.load(stream)
    transport = data["transport"]
    matches = (
        isinstance(transport, dict)
        and transport.get("type") == "streamable_http"
        and transport.get("url") == os.environ["MCP_EXPECTED_URL"]
    )
except (KeyError, OSError, TypeError, ValueError):
    matches = False
raise SystemExit(0 if matches else 3)
PY
}

MCP_JSON="$WORK_DIR/mcp.json"
MCP_ERROR="$WORK_DIR/mcp.err"
MCP_MISSING=0
if codex mcp get rekall --json >"$MCP_JSON" 2>"$MCP_ERROR"; then
  if ! mcp_config_matches "$MCP_JSON"; then
    fail "MCP server 'rekall' already exists with a conflicting transport"
  fi
else
  if grep -q "No MCP server named ['\"]\{0,1\}rekall" "$MCP_ERROR"; then
    MCP_MISSING=1
  else
    fail "could not inspect the existing MCP configuration"
  fi
fi

CANDIDATE_HOOKS="$WORK_DIR/hooks.json"
if [ -f "$HOOKS_FILE" ]; then
  cp -p "$HOOKS_FILE" "$CANDIDATE_HOOKS"
else
  printf '{}\n' >"$CANDIDATE_HOOKS"
  chmod 600 "$CANDIDATE_HOOKS"
fi
python3 "$MERGER" --hooks-file "$CANDIDATE_HOOKS" --adapter "$DEST_ADAPTER" \
  --api-url "$API_URL" || \
  fail "hooks.json is invalid"

changed() {
  [ ! -f "$2" ] || ! cmp -s "$1" "$2"
}

ensure_backup() {
  if [ -z "$BACKUP_DIR" ]; then
    BACKUP_DIR="$CODEX_HOME/backups/rekall-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mkdir -p "$BACKUP_DIR"
  fi
}

backup_file() {
  source_path="$1"
  relative_path="$2"
  [ -f "$source_path" ] || return 0
  ensure_backup
  mkdir -p "$BACKUP_DIR/$(dirname -- "$relative_path")"
  cp -p "$source_path" "$BACKUP_DIR/$relative_path"
}

atomic_copy() {
  source_path="$1"
  destination="$2"
  mode="$3"
  destination_dir="$(dirname -- "$destination")"
  mkdir -p "$destination_dir"
  temporary="$(mktemp "$destination.tmp.XXXXXX")"
  cat "$source_path" >"$temporary"
  chmod "$mode" "$temporary"
  mv -f "$temporary" "$destination"
}

if changed "$SOURCE_ADAPTER" "$DEST_ADAPTER"; then
  ADAPTER_CHANGED=1
  [ ! -f "$DEST_ADAPTER" ] || ADAPTER_EXISTED=1
  backup_file "$DEST_ADAPTER" "hooks/rekall_hook.py"
fi
if changed "$SOURCE_SKILL" "$DEST_SKILL"; then
  SKILL_CHANGED=1
  [ ! -f "$DEST_SKILL" ] || SKILL_EXISTED=1
  backup_file "$DEST_SKILL" "skills/rekall-memory/SKILL.md"
fi
if changed "$CANDIDATE_HOOKS" "$HOOKS_FILE"; then
  HOOKS_CHANGED=1
  [ ! -f "$HOOKS_FILE" ] || HOOKS_EXISTED=1
  backup_file "$HOOKS_FILE" "hooks.json"
  hooks_mode=600
  if [ -f "$HOOKS_FILE" ]; then
    hooks_mode="$(stat -f '%Lp' "$HOOKS_FILE" 2>/dev/null || stat -c '%a' "$HOOKS_FILE")"
  fi
fi

if [ "$MCP_MISSING" -eq 1 ]; then
  codex mcp add rekall --url "$MCP_URL" >/dev/null || fail "could not register the MCP server"
  MCP_ADDED=1
fi

if [ "$ADAPTER_CHANGED" -eq 1 ]; then
  atomic_copy "$SOURCE_ADAPTER" "$DEST_ADAPTER" 700
fi
if [ "$SKILL_CHANGED" -eq 1 ]; then
  atomic_copy "$SOURCE_SKILL" "$DEST_SKILL" 600
fi
if [ "$HOOKS_CHANGED" -eq 1 ]; then
  atomic_copy "$CANDIDATE_HOOKS" "$HOOKS_FILE" "$hooks_mode"
fi

MCP_VERIFY_JSON="$WORK_DIR/mcp-verify.json"
if ! codex mcp get rekall --json >"$MCP_VERIFY_JSON" 2>/dev/null || \
   ! mcp_config_matches "$MCP_VERIFY_JSON"; then
  fail "MCP registration verification failed"
fi

python3 - "$HOOKS_FILE" "$DEST_ADAPTER" "$DEST_SKILL" <<'PY' || fail "installation verification failed"
import json
import sys
from pathlib import Path

expected = {"SessionStart", "PreToolUse", "PreCompact", "PostCompact", "PostToolUse", "SessionEnd"}
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not expected.issubset(data.get("hooks", {})):
    raise SystemExit(2)
if not Path(sys.argv[2]).is_file() or not Path(sys.argv[3]).is_file():
    raise SystemExit(2)
PY

INSTALL_SUCCEEDED=1

cat <<EOF
Rekall Codex integration installed
MCP:           rekall -> $MCP_URL
Hook API:      $API_URL
Hooks:         6 canonical entries; existing hooks preserved
Skill:         rekall-memory installed
Legacy hooks:  removed or none found
Native memory: unchanged
Restart Codex to load the integration
EOF
