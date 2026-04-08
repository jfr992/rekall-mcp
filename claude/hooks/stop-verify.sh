#!/bin/bash
# Stop hook — warns if on main/master with staged changes.
set -euo pipefail
trap 'echo "[stop-verify] hook failed at line $LINENO (exit $?)" >&2' ERR

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  STAGED=$(git diff --cached --name-only 2>/dev/null)
  if [ -n "$STAGED" ]; then
    echo "WARNING: Staged changes on $BRANCH. Create a feature branch before committing." >&2
    echo "Staged files:" >&2
    echo "$STAGED" | sed 's/^/  /' >&2
    exit 2
  fi
fi

exit 0
