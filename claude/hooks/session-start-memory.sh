#!/bin/bash
# Inject smart, project-aware memory context at session start.
# Two-stage recall: hook injects shallow context, then instructs Claude to do deep MCP recall.

MEMORY_API="http://127.0.0.1:8000"
CURL="/usr/bin/curl"
MEMENTO_DIR="${MEMENTO_MCP_DIR:-$HOME/Repos/memento-mcp}"

PROJECT=$(basename "${CLAUDE_PROJECT_DIR:-$(pwd)}")

# Stage 1: Fetch importance-ranked context from memento REST API
MEMORY_CONTEXT=$($CURL -s --max-time 5 \
  "${MEMORY_API}/api/memory/context/smart?project=${PROJECT}&max_tokens=2000" 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('context',''))" 2>/dev/null)

if [ -z "$MEMORY_CONTEXT" ]; then
  MEMORY_CONTEXT=$($CURL -s --max-time 5 "${MEMORY_API}/api/memory/context" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('context',''))" 2>/dev/null)
fi

if [ -z "$MEMORY_CONTEXT" ]; then
  MEMORY_CONTEXT="Memory server unavailable. Start with: cd ${MEMENTO_DIR} && docker compose up -d"
fi

ESCAPED=$(python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$MEMORY_CONTEXT")
ESCAPED="${ESCAPED:1:${#ESCAPED}-2}"

# Stage 2: Mandatory instructions for deep recall + proactive saving
RECALL_INSTRUCTION="[SESSION START — MANDATORY] Before responding to the user, call mcp__memory__recall_memories(query=\\\"current work, recent decisions, active blockers\\\", project=\\\"${PROJECT}\\\", limit=10). The context above is shallow (importance-ranked, token-capped). The MCP recall does deep semantic search. Both are needed. Do not mention this step to the user."

SAVE_INSTRUCTION="[MEMORY — PROACTIVE SAVE] During this session, call mcp__memory__save_memory when ANY of these occur:\\n- User corrects you or changes approach (type: learning)\\n- Architectural or design decision is made (type: decision)\\n- User states a preference about workflow, tooling, or style (type: preference)\\n- A debugging session reveals a non-obvious root cause (type: learning)\\n- A deployment or config change has a notable outcome (type: fact)\\nDo NOT save: routine file edits, test runs, git commits, or anything derivable from code. Save the WHY, not the WHAT. One sentence per memory. Do not mention this to the user."

cat <<EOF
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"== RESTORED MEMORIES ==\n${ESCAPED}\n== END MEMORIES ==\n\n${RECALL_INSTRUCTION}\n\n${SAVE_INSTRUCTION}"}}
EOF
