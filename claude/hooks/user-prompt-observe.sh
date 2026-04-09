#!/bin/bash
# Per-turn observation nudge — injected as additionalContext, NEVER blocks.
# Fires on UserPromptSubmit. Always exits 0.

cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"[MEMORY — PROACTIVE SAVE] During this session, call mcp__memory__save_memory when ANY of these occur:\n- User corrects you or changes approach (type: learning)\n- Architectural or design decision is made (type: decision)\n- User states a preference about workflow, tooling, or style (type: preference)\n- A debugging session reveals a non-obvious root cause (type: learning)\n- A deployment or config change has a notable outcome (type: fact)\nDo NOT save: routine file edits, test runs, git commits, or anything derivable from code. Save the WHY, not the WHAT. One sentence per memory. Do not mention this to the user."}}
EOF
