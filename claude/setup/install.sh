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

    HOOKS=(rekall-restore.sh rekall-observe.sh memory-prune.sh)
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

    # Merge: add UserPromptSubmit (rekall-restore) + Stop (rekall-observe) hooks.
    # SessionStart is intentionally opt-in because it injects additionalContext.
    # Idempotent — checks if the command path already exists in the array.
    REST_CMD="$HOME/.claude/hooks/rekall-restore.sh"
    OBS_CMD="$HOME/.claude/hooks/rekall-observe.sh"
    PRUNE_CMD="$HOME/.claude/hooks/memory-prune.sh"
    START_CMD=""
    if [[ "$INSTALL_STARTUP_CAPSULE" == "1" ]]; then
        START_CMD="$HOME/.claude/hooks/session-start-memory.sh"
    fi

    /usr/bin/python3 - "$SETTINGS" "$REST_CMD" "$OBS_CMD" "$PRUNE_CMD" "$START_CMD" <<'PY'
import json, sys
path, rest_cmd, obs_cmd, prune_cmd, start_cmd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
with open(path) as f: d = json.load(f)
d.setdefault("hooks", {})

def ensure_event_hook(event, command, matcher=""):
    arr = d["hooks"].setdefault(event, [])
    # Already wired?
    for entry in arr:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return False
    # Append (don't clobber existing matchers)
    new_entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        new_entry["matcher"] = matcher
    arr.append(new_entry)
    return True

added = []
if ensure_event_hook("UserPromptSubmit", rest_cmd):
    added.append("UserPromptSubmit → rekall-restore.sh")
if ensure_event_hook("Stop", obs_cmd):
    added.append("Stop → rekall-observe.sh")
if ensure_event_hook("SessionStart", prune_cmd):
    added.append("SessionStart → memory-prune.sh")
if start_cmd and ensure_event_hook("SessionStart", start_cmd):
    added.append("SessionStart → session-start-memory.sh")

with open(path, "w") as f:
    json.dump(d, f, indent=2)

if added:
    print("  ✓ added:", ", ".join(added))
else:
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
    [[ -f "$HOME/.claude/hooks/memory-prune.sh" ]]   && ok "memory-prune.sh in place"   || warn "memory-prune.sh missing"
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
echo "  REKALL_AUTOSAVE=0   disables restore status, SessionStart capsule, and Stop-hook auto-save"
