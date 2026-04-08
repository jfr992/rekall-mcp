#!/bin/bash
# Stop hook — session debrief safety net.
# Primary observation happens during the session (Claude calls observe()).
# This hook catches anything that was missed by reviewing today's memories
# and asking Haiku if there are gaps.
set -euo pipefail
trap 'echo "[session-debrief] hook failed at line $LINENO (exit $?)" >&2' ERR

MEMENTO_API="http://127.0.0.1:8000"
CURL="/usr/bin/curl"
PROJECT=$(basename "${CLAUDE_PROJECT_DIR:-$(pwd)}")

# Guard: required tools
command -v jq >/dev/null 2>&1 || exit 0
[ -x "$CURL" ] || exit 0

# Gate: memento must be up
$CURL -sf --max-time 2 "${MEMENTO_API}/health" >/dev/null 2>&1 || exit 0

# Gate: claude CLI must be available
command -v claude >/dev/null 2>&1 || exit 0

# --- Gather session signals ---
TODAY=$(date +%Y-%m-%d)
MEMORY_DIR="${HOME}/.claude/memory"
YAML_FILE="${MEMORY_DIR}/${TODAY}.yaml"

if [ -f "$YAML_FILE" ]; then
  MEM_COUNT=$(grep -c '^\- id:' "$YAML_FILE" 2>/dev/null || echo "0")
  MEMORIES=$(grep -m 10 'content:' "$YAML_FILE" 2>/dev/null | sed 's/.*content: //' || true)
else
  MEM_COUNT=0
  MEMORIES=""
fi

# Use git log as a signal of what actually happened
GIT_LOG=$(git log --oneline --since="24 hours ago" --no-merges -10 2>/dev/null || true)

# If no commits AND 3+ memories already saved, session is well-covered
[ -z "$GIT_LOG" ] && [ "$MEM_COUNT" -ge 3 ] && exit 0

# Need at least one signal to evaluate
[ -z "$GIT_LOG" ] && [ "$MEM_COUNT" -eq 0 ] && exit 0

PROMPT="A coding session just ended. Review what happened and identify observations worth saving for future sessions.

Git commits this session:
${GIT_LOG:-NONE}

Existing memories saved today (${MEM_COUNT} total):
${MEMORIES:-NONE}

Save-worthy criteria (if not already covered by existing memories):
- User correction, preference, or constraint stated
- Bug root cause or non-obvious gotcha discovered
- Architecture/tool/design decision made
- Approach tried and abandoned (with reason why)
- Environment or tooling quirk discovered
- Significant feature completed or config changed

DO NOT output: routine edits, obvious facts, temporary context, anything already in code/docs/git history.
Format: TYPE: one-sentence description (TYPE = DECISION, LEARNING, or FACT)
If everything is well-covered, respond with exactly: NONE
Maximum 3 items."

DEBRIEF=$(echo "$PROMPT" | claude --model "claude-haiku-4-5-20251001" --print 2>&1) || { echo "[session-debrief] claude call failed: $DEBRIEF" >&2; exit 0; }

[ -z "$DEBRIEF" ] && exit 0
echo "$DEBRIEF" | grep -qiE '^[[:space:]]*none[[:space:]]*\.?[[:space:]]*$' && exit 0

# --- Save each gap item ---
while IFS= read -r line; do
  [ -z "$line" ] && continue
  echo "$line" | grep -qEi '^(note:|here|these|the following|i found|based on|it seems|looking at|i notice|no meaningful)' && continue

  TYPE=$(echo "$line" | grep -oEi '^(DECISION|LEARNING|FACT|PREFERENCE|CORRECTION)' | tr '[:upper:]' '[:lower:]' || true)
  [ -z "$TYPE" ] && continue
  CONTENT=$(echo "$line" | sed -E 's/^(DECISION|LEARNING|FACT|PREFERENCE|CORRECTION)[: ]+//I')
  [ -z "$CONTENT" ] && continue

  $CURL -s --max-time 3 \
    -X POST "${MEMENTO_API}/api/memory/save" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg content "[session-debrief] $CONTENT" --arg type "$TYPE" \
      '{content: $content, type: $type}')" \
    >/dev/null 2>&1 || true
done <<< "$DEBRIEF"

exit 0
