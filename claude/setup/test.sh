#!/usr/bin/env bash
# claude/setup/test.sh
# Verifies install.sh against four scenarios in isolated $HOME directories.
# No effect on real ~/.claude/. Backend on localhost:8000 must be running for
# the health-check assertions; tests skip those if backend is down.
#
# Usage: bash claude/setup/test.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_SH="$SCRIPT_DIR/install.sh"

PASS=0
FAIL=0
SKIP=0

# ---- helpers ----------------------------------------------------------------
pass() { printf "  ✓ %s\n" "$*"; PASS=$((PASS + 1)); }
fail() { printf "  ✗ %s\n" "$*"; FAIL=$((FAIL + 1)); }
skip() { printf "  ⊘ %s (skipped)\n" "$*"; SKIP=$((SKIP + 1)); }

with_isolated_home() {
    local h
    h=$(mktemp -d)
    mkdir -p "$h/.claude"
    echo "$h"
}

cleanup() {
    [[ -n "${TMP_HOMES:-}" ]] && rm -rf $TMP_HOMES
}
trap cleanup EXIT
TMP_HOMES=""

# ---- test 1: fresh install --------------------------------------------------
printf "\n[test 1] fresh install with --hooks-only on empty settings.json\n"
H=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H"
echo '{}' > "$H/.claude/settings.json"

if HOME="$H" bash "$INSTALL_SH" --hooks-only >"$H/install.log" 2>&1; then
    pass "installer exited 0"
else
    fail "installer exited non-zero (see $H/install.log)"
fi

[[ -f "$H/.claude/hooks/rekall-restore.sh" ]] && pass "rekall-restore.sh installed" || fail "rekall-restore.sh missing"
[[ -f "$H/.claude/hooks/rekall-observe.sh" ]] && pass "rekall-observe.sh installed" || fail "rekall-observe.sh missing"
[[ -x "$H/.claude/hooks/rekall-restore.sh" ]] && pass "rekall-restore.sh executable" || fail "rekall-restore.sh not executable"

UPS=$(jq -r '.hooks.UserPromptSubmit | length' "$H/.claude/settings.json" 2>/dev/null)
[[ "$UPS" == "1" ]] && pass "UserPromptSubmit has 1 entry" || fail "UserPromptSubmit entry count = $UPS (expected 1)"

STOP=$(jq -r '.hooks.Stop | length' "$H/.claude/settings.json" 2>/dev/null)
[[ "$STOP" == "1" ]] && pass "Stop has 1 entry" || fail "Stop entry count = $STOP (expected 1)"

ls "$H/.claude/settings.json.bak-"* >/dev/null 2>&1 && pass "settings.json backup created" || fail "no backup file"

# ---- test 2: idempotency ----------------------------------------------------
printf "\n[test 2] re-run on already-wired install (idempotency)\n"

if HOME="$H" bash "$INSTALL_SH" --hooks-only >"$H/install2.log" 2>&1; then
    pass "second run exited 0"
else
    fail "second run failed (see $H/install2.log)"
fi

UPS_AFTER=$(jq -r '.hooks.UserPromptSubmit | length' "$H/.claude/settings.json")
[[ "$UPS_AFTER" == "1" ]] && pass "UserPromptSubmit still 1 entry (no duplicate)" || fail "UserPromptSubmit grew to $UPS_AFTER"

STOP_AFTER=$(jq -r '.hooks.Stop | length' "$H/.claude/settings.json")
[[ "$STOP_AFTER" == "1" ]] && pass "Stop still 1 entry (no duplicate)" || fail "Stop grew to $STOP_AFTER"

grep -q "already" "$H/install2.log" && pass "log reports 'already' on re-run" || fail "log doesn't show idempotent path"

# ---- test 3: merge with pre-existing user hooks -----------------------------
printf "\n[test 3] merge alongside pre-existing user hooks (no clobber)\n"
H2=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H2"
cat > "$H2/.claude/settings.json" <<'JSON'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "/Users/test/.claude/hooks/preexisting-rtk.sh" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "/Users/test/.claude/hooks/preexisting-restore.sh" }
        ]
      }
    ]
  },
  "enabledPlugins": { "test-plugin": true }
}
JSON

if HOME="$H2" bash "$INSTALL_SH" --hooks-only >"$H2/install.log" 2>&1; then
    pass "installer exited 0 with pre-existing hooks"
else
    fail "installer failed against pre-existing config"
fi

PRE_RTK=$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$H2/.claude/settings.json")
[[ "$PRE_RTK" == "/Users/test/.claude/hooks/preexisting-rtk.sh" ]] && pass "pre-existing PreToolUse hook preserved" || fail "PreToolUse clobbered: $PRE_RTK"

PRE_REST=$(jq -r '[.hooks.UserPromptSubmit[].hooks[].command] | length' "$H2/.claude/settings.json")
[[ "$PRE_REST" == "2" ]] && pass "UserPromptSubmit now has 2 entries (preexisting + rekall)" || fail "UserPromptSubmit count = $PRE_REST"

PLUGIN=$(jq -r '.enabledPlugins."test-plugin"' "$H2/.claude/settings.json")
[[ "$PLUGIN" == "true" ]] && pass "non-hooks fields preserved (enabledPlugins intact)" || fail "enabledPlugins lost"

jq empty "$H2/.claude/settings.json" 2>/dev/null && pass "settings.json still valid JSON" || fail "settings.json corrupted"

# ---- test 4: skills install -------------------------------------------------
printf "\n[test 4] --skills-only installs all 8 slash commands\n"
H3=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H3"

if HOME="$H3" bash "$INSTALL_SH" --skills-only >"$H3/install.log" 2>&1; then
    pass "installer exited 0"
else
    fail "installer failed"
fi

EXPECTED=(rekall-setup memory-observe memory-recall memory-restore memory-stats memory-skills memory-rebuild memory-consolidate)
for s in "${EXPECTED[@]}"; do
    [[ -f "$H3/.claude/skills/$s/SKILL.md" ]] && pass "$s/SKILL.md installed" || fail "$s/SKILL.md missing"
done

# ---- test 5: backend health (skipped if backend down) ----------------------
printf "\n[test 5] backend health (--skip-backend skips, default verifies)\n"
H4=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H4"

if curl -sf -o /dev/null --max-time 2 http://localhost:8000/health 2>/dev/null; then
    HOME="$H4" bash "$INSTALL_SH" --skip-backend >"$H4/install.log" 2>&1
    grep -q "backend:" "$H4/install.log" && pass "backend stats reported" || fail "no backend stats line"
else
    skip "backend not running (start rekall and re-run)"
fi

# ---- summary ----------------------------------------------------------------
printf "\n──────────────────────────────────────\n"
printf "PASS: %d   FAIL: %d   SKIP: %d\n" "$PASS" "$FAIL" "$SKIP"
printf "──────────────────────────────────────\n"

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
