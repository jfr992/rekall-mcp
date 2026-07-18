#!/usr/bin/env bash
# claude/setup/test.sh
# Verifies install.sh against seven scenarios in isolated $HOME directories.
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
[[ -f "$H/.claude/hooks/rekall-reflex.sh" ]] && pass "rekall-reflex.sh installed" || fail "rekall-reflex.sh missing"
[[ -x "$H/.claude/hooks/rekall-restore.sh" ]] && pass "rekall-restore.sh executable" || fail "rekall-restore.sh not executable"
[[ -x "$H/.claude/hooks/rekall-reflex.sh" ]] && pass "rekall-reflex.sh executable" || fail "rekall-reflex.sh not executable"

UPS=$(jq -r '.hooks.UserPromptSubmit | length' "$H/.claude/settings.json" 2>/dev/null)
[[ "$UPS" == "1" ]] && pass "UserPromptSubmit has 1 entry" || fail "UserPromptSubmit entry count = $UPS (expected 1)"

STOP=$(jq -r '.hooks.Stop | length' "$H/.claude/settings.json" 2>/dev/null)
[[ "$STOP" == "1" ]] && pass "Stop has 1 entry" || fail "Stop entry count = $STOP (expected 1)"

# 4 hook events wired total: UserPromptSubmit, Stop, SessionStart (memory-prune), PreToolUse (reflex)
HOOK_EVENTS=$(jq -r '.hooks | keys | length' "$H/.claude/settings.json" 2>/dev/null)
[[ "$HOOK_EVENTS" == "4" ]] && pass "fresh install wires 4 hook events" || fail "hook event count = $HOOK_EVENTS (expected 4)"

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

PRETOOL_AFTER=$(jq -r '.hooks.PreToolUse | length' "$H/.claude/settings.json")
[[ "$PRETOOL_AFTER" == "1" ]] && pass "PreToolUse still 1 entry (no duplicate)" || fail "PreToolUse grew to $PRETOOL_AFTER"

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

REFLEX_APPENDED=$(jq -r '.hooks.PreToolUse[1].hooks[0].command' "$H2/.claude/settings.json")
[[ "$REFLEX_APPENDED" == *"rekall-reflex.sh" ]] && pass "reflex entry appended after foreign PreToolUse[0]" || fail "reflex not appended: $REFLEX_APPENDED"

REFLEX_APPENDED_MATCHER=$(jq -r '.hooks.PreToolUse[1].matcher' "$H2/.claude/settings.json")
[[ "$REFLEX_APPENDED_MATCHER" == "Bash" ]] && pass "appended reflex entry has Bash matcher" || fail "appended reflex matcher = $REFLEX_APPENDED_MATCHER"

PRE_REST=$(jq -r '[.hooks.UserPromptSubmit[].hooks[].command] | length' "$H2/.claude/settings.json")
[[ "$PRE_REST" == "2" ]] && pass "UserPromptSubmit now has 2 entries (preexisting + rekall)" || fail "UserPromptSubmit count = $PRE_REST"

PLUGIN=$(jq -r '.enabledPlugins."test-plugin"' "$H2/.claude/settings.json")
[[ "$PLUGIN" == "true" ]] && pass "non-hooks fields preserved (enabledPlugins intact)" || fail "enabledPlugins lost"

jq empty "$H2/.claude/settings.json" 2>/dev/null && pass "settings.json still valid JSON" || fail "settings.json corrupted"

# ---- test 4: repair a rekall-reflex entry with a missing matcher -----------
printf "\n[test 4] existing reflex entry with missing matcher gets repaired\n"
H5=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H5"
cat > "$H5/.claude/settings.json" <<JSON
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          { "type": "command", "command": "$H5/.claude/hooks/rekall-reflex.sh" }
        ]
      }
    ]
  }
}
JSON

if HOME="$H5" bash "$INSTALL_SH" --hooks-only >"$H5/install.log" 2>&1; then
    pass "installer exited 0 against missing-matcher reflex entry"
else
    fail "installer failed against missing-matcher reflex entry"
fi

REPAIRED_MATCHER=$(jq -r '.hooks.PreToolUse[0].matcher' "$H5/.claude/settings.json")
[[ "$REPAIRED_MATCHER" == "Bash" ]] && pass "missing matcher repaired to Bash" || fail "matcher = $REPAIRED_MATCHER (expected Bash)"

# ---- test 5: repair a rekall-reflex entry with a wrong (non-Bash) matcher --
printf "\n[test 5] existing reflex entry with wrong matcher gets repaired\n"
H6=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H6"
cat > "$H6/.claude/settings.json" <<JSON
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          { "type": "command", "command": "$H6/.claude/hooks/rekall-reflex.sh" }
        ]
      }
    ]
  }
}
JSON

if HOME="$H6" bash "$INSTALL_SH" --hooks-only >"$H6/install.log" 2>&1; then
    pass "installer exited 0 against wrong-matcher reflex entry"
else
    fail "installer failed against wrong-matcher reflex entry"
fi

WRONG_REPAIRED=$(jq -r '.hooks.PreToolUse[0].matcher' "$H6/.claude/settings.json")
[[ "$WRONG_REPAIRED" == "Bash" ]] && pass "wrong matcher (Write) repaired to Bash" || fail "matcher = $WRONG_REPAIRED (expected Bash)"

WRONG_COUNT=$(jq -r '.hooks.PreToolUse | length' "$H6/.claude/settings.json")
[[ "$WRONG_COUNT" == "1" ]] && pass "repair corrects in place, no duplicate entry" || fail "PreToolUse count = $WRONG_COUNT (expected 1)"

# ---- test 6: skills install -------------------------------------------------
printf "\n[test 6] --skills-only installs all 9 slash commands\n"
H3=$(with_isolated_home); TMP_HOMES="$TMP_HOMES $H3"

if HOME="$H3" bash "$INSTALL_SH" --skills-only >"$H3/install.log" 2>&1; then
    pass "installer exited 0"
else
    fail "installer failed"
fi

EXPECTED=(rekall-setup rekall-publish memory-observe memory-recall memory-restore memory-stats memory-skills memory-rebuild memory-consolidate)
for s in "${EXPECTED[@]}"; do
    [[ -f "$H3/.claude/skills/$s/SKILL.md" ]] && pass "$s/SKILL.md installed" || fail "$s/SKILL.md missing"
done

# ---- test 7: backend health (skipped if backend down) ----------------------
printf "\n[test 7] backend health (--skip-backend skips, default verifies)\n"
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
