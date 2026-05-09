#!/usr/bin/env bash
# ~/.claude/hooks/memento-observe.sh
# Fires on Stop. Uses a cheap LLM judge (haiku) to decide whether the last
# exchange contains something worth remembering. If yes, POSTs to memento.
#
# Kill switch: MEMENTO_AUTOSAVE=0
# Backend URL: MEMENTO_API_URL (default http://localhost:8000)
# Model:       MEMENTO_JUDGE_MODEL (default claude-haiku-4-5)
set -euo pipefail

API="${MEMENTO_API_URL:-http://localhost:8000}"
MODEL="${MEMENTO_JUDGE_MODEL:-claude-haiku-4-5}"

[[ "${MEMENTO_AUTOSAVE:-1}" == "0" ]] && exit 0

# Re-entrancy guard: if this hook invokes claude CLI, that inner claude will
# fire its own Stop hook when it finishes. This env var is set below before
# calling claude; if we see it, we're nested — bail.
[[ "${MEMENTO_JUDGE_INFLIGHT:-0}" == "1" ]] && exit 0

LOG="/tmp/memento-observe.log"
trace() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >> "$LOG"; }
trace "fire: hook invoked"

# Read the Stop hook payload from stdin.
payload="$(cat)"
transcript_path="$(jq -r '.transcript_path // ""' <<<"$payload")"
stop_hook_active="$(jq -r '.stop_hook_active // false' <<<"$payload")"

# Caller's working directory — Claude Code provides this in the Stop payload.
# Falls back to $CLAUDE_PROJECT_DIR then $PWD so the scope attaches to the
# right repo, not to memento-mcp (the backend's own cwd).
caller_cwd="$(jq -r '.cwd // ""' <<<"$payload")"
[[ -z "$caller_cwd" ]] && caller_cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

# Bail if we're re-entering from our own Stop (should never happen with --bare
# but belt-and-suspenders).
[[ "$stop_hook_active" == "true" ]] && exit 0
[[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0

# Backend alive?
curl -sfo /dev/null --max-time 1 "$API/health" 2>/dev/null || exit 0

# Grab the last user message and last assistant text message from the JSONL
# transcript. Each line is a message object with {type, message:{role,content}}.
# Content can be a string or array of blocks; we pull text blocks only.
exchange="$(
  tail -n 200 "$transcript_path" 2>/dev/null | jq -rs '
    def text_of(msg):
      if (msg.content | type) == "string" then msg.content
      else
        (msg.content // [])
        | map(select(.type == "text") | .text)
        | join("\n")
      end;
    [ .[] | select(.type == "user" or .type == "assistant") ] as $msgs
    | ($msgs | map(select(.type == "user")) | last) as $u
    | ($msgs | map(select(.type == "assistant")) | last) as $a
    | "USER:\n\(text_of($u.message // {}))\n\nASSISTANT:\n\(text_of($a.message // {}))"
  ' 2>/dev/null || true
)"

# Skip tiny or empty exchanges.
[[ -z "$exchange" || "${#exchange}" -lt 40 ]] && exit 0

# Cap size — judge doesn't need more than ~4k chars per side.
exchange="$(printf '%s' "$exchange" | head -c 16000)"

# Judge prompt. Strict JSON only; haiku is cheap so this is ~$0.001/turn.
read -r -d '' JUDGE_PROMPT <<'EOF' || true
You are a memory judge for an AI assistant's persistent memory system.

Decide if the following exchange contains ONE durable fact worth saving. Save ONLY when the exchange contains:
- A user preference or style rule ("I prefer X", "always use Y", "don't do Z")
- A correction of the assistant (user overrode a mistake)
- A confirmed architecture/tool decision
- A project constraint ("we can't use X because Y")
- A bug root cause or non-obvious gotcha
- A shipped feature (one-line summary)

DO NOT save:
- Questions without answers
- File contents, logs, narration, step-by-step work
- Temporary/session-only context
- Things trivially derivable from code or docs
- Vague or speculative observations

Output STRICT JSON only, no prose, no markdown fence:
{"observe": false}
OR
{"observe": true, "type": "preference|learning|decision|requirement|fact", "content": "ONE concise sentence"}

Exchange:
EOF

# ============================================================
# Cheap signal gate — bypass Haiku unless real durability signal.
# Three signals: (1) new git commits since last fire,
# (2) keyword in last user message, (3) 5+ turns AND 0 saves today.
# ============================================================
LAST_FIRE_FILE=/tmp/memento-observe-last-fire
LAST_FIRE_TS=$(cat "$LAST_FIRE_FILE" 2>/dev/null || echo 0)

fire_haiku=false

# Signal 1: new commits since last fire (objective signal)
if command -v git >/dev/null 2>&1 && [ -n "$caller_cwd" ] && [ -d "$caller_cwd/.git" ]; then
    NEW_COMMITS=$(git -C "$caller_cwd" log --since="@$LAST_FIRE_TS" --oneline 2>/dev/null | wc -l | tr -d ' ')
    [ "$NEW_COMMITS" -gt 0 ] && fire_haiku=true
fi

# Signal 2: keyword in the last user message (durability hint)
LAST_USER=$(printf '%s' "$exchange" | sed -n '/^USER:/,/^ASSISTANT:/p' | head -50)
if printf '%s' "$LAST_USER" | grep -qiE 'remember|let.?s? ?go|decided|prefer|gotcha|fix.{0,8}root|hard rule|always|never'; then
    fire_haiku=true
fi

# Signal 3: 5+ assistant turns this session AND zero saves today
if [ "$fire_haiku" = "false" ]; then
    TURN_COUNT=$(tail -n 400 "$transcript_path" 2>/dev/null | grep -c '"role":"assistant"' || echo 0)
    if [ "$TURN_COUNT" -ge 5 ]; then
        TODAY=$(date +%Y-%m-%d)
        YAML_PROJECT=$(basename "$caller_cwd")
        MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
        YAML_FILE="$MEMORY_DIR/$YAML_PROJECT/$TODAY.yaml"
        if [ -f "$YAML_FILE" ]; then
            TODAY_SAVES=$(grep -c '^- id:' "$YAML_FILE" 2>/dev/null || echo 0)
        else
            TODAY_SAVES=0
        fi
        [ "$TODAY_SAVES" -eq 0 ] && fire_haiku=true
    fi
fi

if [ "$fire_haiku" = "false" ]; then
    trace "skipped: no durability signal"
    exit 0
fi

date +%s > "$LAST_FIRE_FILE"
trace "fire: signal detected, calling haiku"
# ============================================================

# Call claude in --bare mode so it doesn't recursively fire hooks / load memory.
judge_out="$(
  printf '%s\n\n%s\n' "$JUDGE_PROMPT" "$exchange" \
    | MEMENTO_JUDGE_INFLIGHT=1 perl -e 'alarm 25; exec @ARGV' claude -p --model "$MODEL" 2>/dev/null \
    | tr -d '\000' \
    || true
)"

[[ -z "$judge_out" ]] && exit 0

# Strip markdown fences (haiku often wraps in ```json ... ```), then try to
# find the first balanced {...} block. jq -c normalizes to one line.
clean="$(printf '%s' "$judge_out" | sed -E 's/^```[a-zA-Z]*//; s/```$//' | tr -d '`')"
json="$(printf '%s' "$clean" | jq -c '.' 2>/dev/null || true)"
if [[ -z "$json" ]]; then
  # Fallback: perl non-greedy multi-line extract of the first {...} group.
  json="$(printf '%s' "$clean" | perl -0777 -ne 'print $1 if /(\{.*?\})/s' | jq -c '.' 2>/dev/null || true)"
fi
[[ -z "$json" ]] && exit 0

observe="$(jq -r '.observe // false' <<<"$json" 2>/dev/null || echo false)"
if [[ "$observe" != "true" ]]; then
  trace "judge: no-op"
  exit 0
fi

mtype="$(jq -r '.type // "learning"' <<<"$json" 2>/dev/null)"
content="$(jq -r '.content // ""' <<<"$json" 2>/dev/null)"
[[ -z "$content" ]] && exit 0

# POST to memento. Dedupe (cosine ≥ 0.97) is handled server-side.
curl -sfo /dev/null --max-time 5 -X POST "$API/api/memory/observe" \
  -H "Content-Type: application/json" \
  -d "$(jq -cn --arg c "$content" --arg t "$mtype" --arg d "$caller_cwd" '{summary:$c, type:$t, cwd:$d}')" \
  2>/dev/null || true

trace "save: type=$mtype project=$(basename "$caller_cwd") :: $content"
exit 0
