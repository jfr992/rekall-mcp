#!/usr/bin/env bash
# claude/setup/install.sh
# One-shot installer for Rekall's Claude Code wiring (hooks + skills + settings).
# Idempotent: re-run anytime. Backs up ~/.claude/settings.json before patching.
#
# Usage: bash claude/setup/install.sh
#        bash claude/setup/install.sh --skip-backend     (skip docker + python startup)
#        bash claude/setup/install.sh --skills-only       (only install slash commands)
#        bash claude/setup/install.sh --hooks-only        (only install hooks + settings)
#        bash claude/setup/install.sh --install-startup-capsule

set -euo pipefail

# ---------------------------------------------------------------- args
SKIP_BACKEND=0
SKILLS_ONLY=0
HOOKS_ONLY=0
INSTALL_STARTUP_CAPSULE=0
BACKUP=""  # set by the settings.json patch path; referenced unconditionally in the final report
LIVE_BACKUP_DIR=""
for arg in "$@"; do
    case "$arg" in
        --skip-backend) SKIP_BACKEND=1 ;;
        --skills-only)  SKILLS_ONLY=1; SKIP_BACKEND=1 ;;
        --hooks-only)   HOOKS_ONLY=1; SKIP_BACKEND=1 ;;
        --install-startup-capsule) INSTALL_STARTUP_CAPSULE=1 ;;
        --help|-h)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown arg: $arg (see --help)" >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------- locate repo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLAUDE_BUNDLE="$REPO_DIR/claude"

if [[ ! -d "$CLAUDE_BUNDLE/hooks" ]]; then
    echo "ERROR: $CLAUDE_BUNDLE/hooks not found. Run from a rekall-mcp checkout." >&2
    exit 1
fi

# ---------------------------------------------------------------- ui helpers
step() { printf "\n→ %s\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
warn() { printf "  ⚠ %s\n" "$*"; }
fail() { printf "  ✗ %s\n" "$*" >&2; exit 1; }

ensure_live_backup_dir() {
    if [[ -z "$LIVE_BACKUP_DIR" ]]; then
        LIVE_BACKUP_DIR="$HOME/.claude/backups/rekall-live-config-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$LIVE_BACKUP_DIR"
    fi
}

backup_live_file() {
    local path="$1"
    [[ -e "$path" ]] || return 0

    local root="$HOME/.claude"
    local rel
    rel="${path#$root/}"
    ensure_live_backup_dir
    local backup_root
    backup_root="$LIVE_BACKUP_DIR"
    local backup_parent
    backup_parent="$backup_root/$(dirname "$rel")"
    mkdir -p "$backup_parent"
    cp -p "$path" "$backup_parent/"
    ok "backed up $rel to ${backup_root#$root/}/$rel"
}

# ---------------------------------------------------------------- preflight
step "Preflight checks"
command -v docker     >/dev/null 2>&1 && ok "docker"   || warn "docker not found (backend won't start)"
command -v jq         >/dev/null 2>&1 && ok "jq"       || fail "jq is required (brew install jq)"
command -v curl       >/dev/null 2>&1 && ok "curl"     || fail "curl is required"
command -v python3    >/dev/null 2>&1 && ok "python3"  || fail "python3 is required"
[[ -d "$HOME/.claude" ]] && ok "~/.claude/ exists"     || mkdir -p "$HOME/.claude"

# ---------------------------------------------------------------- backend
if [[ "$SKIP_BACKEND" == "0" ]]; then
    step "Starting Qdrant + backend"

    if ! command -v docker >/dev/null 2>&1; then
        fail "docker missing. Install Docker Desktop or use --skip-backend."
    fi

    cd "$REPO_DIR"
    if docker compose ps qdrant 2>/dev/null | grep -q "Up"; then
        ok "qdrant already running"
    else
        if docker compose version >/dev/null 2>&1; then
            docker compose up -d qdrant >/dev/null 2>&1 || fail "docker compose up qdrant failed"
        else
            docker-compose up -d qdrant >/dev/null 2>&1 || fail "docker-compose up qdrant failed"
        fi
        ok "qdrant started"
    fi

    # Wait for qdrant health (max 15s)
    for _ in $(seq 1 15); do
        curl -sf -o /dev/null --max-time 2 http://localhost:6333/healthz 2>/dev/null && break
        sleep 1
    done
    curl -sf -o /dev/null --max-time 2 http://localhost:6333/healthz 2>/dev/null \
        && ok "qdrant healthy at :6333" \
        || warn "qdrant not healthy after 15s — backend may not start cleanly"

    # Backend python server
    if curl -sf -o /dev/null --max-time 2 http://localhost:8000/health 2>/dev/null; then
        ok "backend already running at :8000"
    else
        if command -v uv >/dev/null 2>&1; then
            cd "$REPO_DIR"
            MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/rekall-backend.log 2>&1 &
            disown
            for _ in $(seq 1 20); do
                curl -sf -o /dev/null --max-time 2 http://localhost:8000/health 2>/dev/null && break
                sleep 1
            done
            curl -sf -o /dev/null --max-time 2 http://localhost:8000/health 2>/dev/null \
                && ok "backend started (logs: /tmp/rekall-backend.log)" \
                || warn "backend didn't come up in 20s — check /tmp/rekall-backend.log"
        else
            warn "uv not found — start backend manually: MCP_TRANSPORT=streamable-http uv run python -m server"
        fi
    fi
fi

# ---------------------------------------------------------------- hooks
if [[ "$SKILLS_ONLY" == "0" ]]; then
    step "Installing hooks → ~/.claude/hooks/"
    mkdir -p "$HOME/.claude/hooks"

    HOOKS=(rekall-restore.sh rekall-observe.sh rekall-session-end.sh memory-prune.sh rekall-reflex.sh)
    if [[ "$INSTALL_STARTUP_CAPSULE" == "1" ]]; then
        HOOKS+=(session-start-memory.sh)
    fi

    for hook in "${HOOKS[@]}"; do
        src="$CLAUDE_BUNDLE/hooks/$hook"
        dst="$HOME/.claude/hooks/$hook"
        if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
            ok "$hook already up-to-date"
        else
            backup_live_file "$dst"
            cp "$src" "$dst"
            chmod +x "$dst"
            ok "$hook installed"
        fi
    done

    # ----- settings.json patch -----
    step "Wiring ~/.claude/settings.json"

    SETTINGS="$HOME/.claude/settings.json"
    if [[ ! -f "$SETTINGS" ]]; then
        echo '{}' > "$SETTINGS"
        ok "created empty settings.json"
    fi

    # Validate it's parseable JSON before touching
    jq empty "$SETTINGS" 2>/dev/null || fail "$SETTINGS is not valid JSON. Fix it manually."

    # Backup
    backup_live_file "$SETTINGS"
    BACKUP="$SETTINGS.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$SETTINGS" "$BACKUP"
    ok "backed up to $(basename "$BACKUP")"

    # Merge Rekall's supported lifecycle hooks and retire exact basenames from
    # superseded experimental hooks. Foreign hooks and top-level settings are
    # preserved; session-start-memory.sh (context injector) remains opt-in.
    REST_CMD="$HOME/.claude/hooks/rekall-restore.sh"
    OBS_CMD="$HOME/.claude/hooks/rekall-observe.sh"
    SESSION_END_CMD="$HOME/.claude/hooks/rekall-session-end.sh"
    PRUNE_CMD="$HOME/.claude/hooks/memory-prune.sh"
    REFLEX_CMD="$HOME/.claude/hooks/rekall-reflex.sh"
    START_CMD=""
    if [[ "$INSTALL_STARTUP_CAPSULE" == "1" ]]; then
        START_CMD="$HOME/.claude/hooks/session-start-memory.sh"
    fi

    /usr/bin/python3 - "$SETTINGS" "$REST_CMD" "$OBS_CMD" "$SESSION_END_CMD" "$PRUNE_CMD" "$REFLEX_CMD" "$START_CMD" <<'PY'
import json
import os
import shlex
import sys

(
    path,
    rest_cmd,
    obs_cmd,
    session_end_cmd,
    prune_cmd,
    reflex_cmd,
    start_cmd,
) = sys.argv[1:]
with open(path) as f:
    d = json.load(f)
if not isinstance(d.setdefault("hooks", {}), dict):
    raise SystemExit("settings hooks must be a JSON object")


OBSOLETE_REKALL_HOOKS = {
    "rekall-precompact.sh",
    "rekall-postcompact.sh",
    "rekall-commit-nudge.sh",
}


def command_basename(command):
    if not isinstance(command, str):
        return ""
    try:
        parts = shlex.split(command)
    except ValueError:
        return ""
    return os.path.basename(parts[0]) if len(parts) == 1 else ""


def prune_obsolete_rekall_hooks():
    removed = 0
    for event, entries in list(d["hooks"].items()):
        if not isinstance(entries, list):
            continue
        kept_entries = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                kept_entries.append(entry)
                continue
            kept_hooks = []
            for hook in entry["hooks"]:
                basename = command_basename(hook.get("command")) if isinstance(hook, dict) else ""
                if basename in OBSOLETE_REKALL_HOOKS:
                    removed += 1
                else:
                    kept_hooks.append(hook)
            if kept_hooks:
                entry["hooks"] = kept_hooks
                kept_entries.append(entry)
        if kept_entries:
            d["hooks"][event] = kept_entries
        else:
            del d["hooks"][event]
    return removed


def ensure_event_hook(event, command, matcher="", timeout=None):
    """Wire `command` under `event`, keyed on matcher correctness.

    Returns "added" (new entry appended), "repaired" (existing entry's
    matcher was wrong/missing and got corrected in place), or None
    (already wired with the correct matcher — true no-op).
    """
    arr = d["hooks"].setdefault(event, [])
    # Already wired?
    for entry in arr:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                changed = False
                existing_matcher = entry.get("matcher", "")
                if matcher and existing_matcher != matcher:
                    entry["matcher"] = matcher
                    changed = True
                if timeout is not None and h.get("timeout") != timeout:
                    h["timeout"] = timeout
                    changed = True
                return "repaired" if changed else None
    # Append (don't clobber existing matchers on OTHER entries)
    hook = {"type": "command", "command": command}
    if timeout is not None:
        hook["timeout"] = timeout
    new_entry = {"hooks": [hook]}
    if matcher:
        new_entry["matcher"] = matcher
    arr.append(new_entry)
    return "added"

removed = prune_obsolete_rekall_hooks()
added = []
repaired = []

def record(result, label):
    if result == "added":
        added.append(label)
    elif result == "repaired":
        repaired.append(label)

record(ensure_event_hook("UserPromptSubmit", rest_cmd), "UserPromptSubmit → rekall-restore.sh")
record(ensure_event_hook("Stop", obs_cmd), "Stop → rekall-observe.sh")
record(
    ensure_event_hook("SessionEnd", session_end_cmd, timeout=3),
    "SessionEnd → rekall-session-end.sh",
)
record(ensure_event_hook("SessionStart", prune_cmd), "SessionStart → memory-prune.sh")
record(ensure_event_hook("PreToolUse", reflex_cmd, matcher="Bash"), "PreToolUse → rekall-reflex.sh")
if start_cmd:
    record(ensure_event_hook("SessionStart", start_cmd), "SessionStart → session-start-memory.sh")

with open(path, "w") as f:
    json.dump(d, f, indent=2)

if removed:
    print(f"  ✓ removed {removed} obsolete Rekall hook entr{'y' if removed == 1 else 'ies'}")
if added:
    print("  ✓ added:", ", ".join(added))
if repaired:
    print("  ✓ repaired matcher:", ", ".join(repaired))
if not removed and not added and not repaired:
    print("  ✓ already wired (no changes)")
PY
fi

# ---------------------------------------------------------------- skills
if [[ "$HOOKS_ONLY" == "0" ]]; then
    step "Installing slash commands → ~/.claude/skills/"
    mkdir -p "$HOME/.claude/skills"

    installed=0
    for skill_dir in "$CLAUDE_BUNDLE/skills/"*/; do
        name=$(basename "$skill_dir")
        target="$HOME/.claude/skills/$name"
        if [[ -d "$target" ]] && diff -rq "$skill_dir" "$target" >/dev/null 2>&1; then
            : # up-to-date, skip
        else
            mkdir -p "$target"
            cp -r "$skill_dir"* "$target/"
            installed=$((installed + 1))
        fi
    done
    if [[ "$installed" -gt 0 ]]; then
        ok "installed/updated $installed slash command(s)"
    else
        ok "all slash commands up-to-date"
    fi
fi

# ---------------------------------------------------------------- final verify
step "Verifying"

if curl -sf -o /dev/null --max-time 2 http://localhost:8000/health 2>/dev/null; then
    STATS=$(curl -s --max-time 3 http://localhost:8000/api/memory/stats 2>/dev/null \
        | /usr/bin/python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"{d['total_memories']} memories · {d['knowledge_graph']['nodes']} nodes · {d['knowledge_graph']['edges']} edges\")" 2>/dev/null \
        || echo "alive")
    ok "backend: $STATS"
else
    warn "backend not reachable at http://localhost:8000 — start it before next session"
fi

if [[ "$SKILLS_ONLY" == "0" ]]; then
    [[ -f "$HOME/.claude/hooks/rekall-restore.sh" ]] && ok "rekall-restore.sh in place" || warn "rekall-restore.sh missing"
    [[ -f "$HOME/.claude/hooks/rekall-observe.sh" ]] && ok "rekall-observe.sh in place" || warn "rekall-observe.sh missing"
    [[ -f "$HOME/.claude/hooks/rekall-session-end.sh" ]] && ok "rekall-session-end.sh in place" || warn "rekall-session-end.sh missing"
    [[ -f "$HOME/.claude/hooks/memory-prune.sh" ]]   && ok "memory-prune.sh in place"   || warn "memory-prune.sh missing"
    [[ -f "$HOME/.claude/hooks/rekall-reflex.sh" ]]  && ok "rekall-reflex.sh in place"  || warn "rekall-reflex.sh missing"
    if [[ "$INSTALL_STARTUP_CAPSULE" == "1" ]]; then
        [[ -f "$HOME/.claude/hooks/session-start-memory.sh" ]] && ok "session-start-memory.sh in place" || warn "session-start-memory.sh missing"
    fi
fi

echo
echo "✓ Rekall setup complete."
echo
echo "Next steps:"
echo "  • Restart your Claude Code session for the new hooks/skills to load."
echo "  • Type /memory-stats in a new session to verify slash commands work."
[[ -n "$BACKUP" ]] && echo "  • If something's off, restore your settings: cp '$BACKUP' '$HOME/.claude/settings.json'"
[[ -n "$LIVE_BACKUP_DIR" ]] && echo "  • Live file backups: $LIVE_BACKUP_DIR"
echo
echo "Kill switches (env vars):"
echo "  REKALL_AUTOSAVE=0   disables restore, SessionStart capsule, Stop auto-save, and SessionEnd utility"
echo "  REKALL_REFLEX=0     disables the PreToolUse reflex recall hook (also gated by REKALL_AUTOSAVE=0)"
