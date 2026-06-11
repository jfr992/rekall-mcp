# Memento Config Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push the current `feature/agent-memory-os` work cleanly to origin, then selectively port only the worth-taking pieces from the other laptop's branches (`chore/sync-claude-bundle`, `feat/hybrid-search-bm25`, `feat/knowledge-base-ui`) — preserving JR's running cockpit + scope fix + zero-injection restore as the spine.

**Architecture:** Backup-first, smallest-blast-radius-first sequencing. Each phase is independently revertable. The high-risk BM25 merge is deliberately deferred to a follow-up plan.

**Tech Stack:** bash hooks · jq · git cherry-pick + merge · Python (server) · Next.js 15 (UI, untouched in this plan) · Qdrant (Docker) · Claude Code Hooks (PreToolUse / Stop / SessionStart / UserPromptSubmit) · Haiku 4.5 LLM judge

---

## File Structure

### Files created in this plan

| Path | Responsibility |
|------|----------------|
| `~/backups/memento-pre-merge-<TS>/` | Tarballs + sha256 manifest of all non-git state |
| `~/.claude/hooks/git-safety.sh` | PreToolUse — block `--no-verify` on git state-changing commands |
| `~/.claude/hooks/iac-safety.sh` | PreToolUse — block destructive terraform/terragrunt/tofu commands |
| `~/.claude/hooks/session-context.sh` | SessionStart — emit ~200 bytes of project/branch/account detection |
| `/tmp/memento-observe-last-fire` | Persistent timestamp marker for the rewritten Stop hook gate |

### Files modified in this plan

| Path | Change |
|------|--------|
| `.gitignore` (repo root) | Add screenshot + playwright + tsbuildinfo entries |
| `~/.claude/settings.json` | Register 3 new hooks (`git-safety`, `iac-safety`, `session-context`) |
| `~/.claude/hooks/memento-observe.sh` | Replace per-turn Haiku judge with gated version (10× cost reduction) |
| `~/.claude/CLAUDE.md` | Insert 4 sections from other laptop's version (Collaboration Style, Workflow Engine, Memory two-lane, MR/PR + Code comments) |
| `src/core/vector_store.py` | RRF prefetch filter-leak fix (cherry-pick from `ce6016e`) |
| `src/memory/manager.py` | Adds `days_back` arg on `get_topic_clusters` (cherry-pick from `ce6016e`) |
| `src/server.py` | Adds `?days=N` on `/api/memory/context/hierarchy` (cherry-pick from `ce6016e`) |

### Files deleted in this plan

| Path | Reason |
|------|--------|
| `CLAUDE_CONTINUE_PROMPT.md` (repo root) | Stale handoff document |

### Files NOT touched (deferred to follow-up plan)

- `src/core/sparse_encoder.py` — BM25 work (Phase 6 of original plan, follow-up doc)
- `src/memory/{compact,smart_context,migrate_hybrid}.py` — same
- `src/tools/builtin/{chat_orchestrator,agent_config}.py` — same
- All UI files — current cockpit work is the spine, no UI changes in this plan

---

## Skip Pile (do not merge from other laptop)

| Source file | Why skip |
|-------------|----------|
| `claude/hooks/user-prompt-observe.sh` | 153 tokens × every prompt = ~7,650/session nag. Regression of yesterday's nuclear-mode decision. |
| `claude/hooks/session-start-memory.sh` | Double-charges (2K injection + forced MCP recall). Wrong `mcp__memory__*` namespace. |
| `claude/hooks/memory-cleanup.sh` | Endpoint `/api/memory/cleanup` does not exist on this laptop yet. |
| `claude/hooks/stop-verify.sh` | Useful but JR doesn't push to main anyway. Low marginal value. |
| Branch's full `claude/CLAUDE.md` | Has Bedrock/GitLab/Port.io content from JR's job laptop. Cherry-pick 4 sections only. |
| Branch's `claude/SETUP.md` | Setup doc references Repos/-prefixed paths that don't match this layout. |
| `feat/knowledge-base-ui` (other than `ce6016e`) | Branch is strictly an ancestor of `feature/agent-memory-os`. |

---

## Task 1: Backup all non-git state

**Files:**
- Create: `~/backups/memento-pre-merge-<TS>/repo-working-tree.tar.gz`
- Create: `~/backups/memento-pre-merge-<TS>/dotclaude-config.tar.gz`
- Create: `~/backups/memento-pre-merge-<TS>/clawd-memory.tar.gz`
- Create: `~/backups/memento-pre-merge-<TS>/qdrant-data.tar.gz`
- Create: `~/backups/memento-pre-merge-<TS>/auto-memory.tar.gz`
- Create: `~/backups/memento-pre-merge-<TS>/memento-observe.log`
- Create: `~/backups/memento-pre-merge-<TS>/MANIFEST.sha256`

- [ ] **Step 1.1: Capture timestamp + create backup directory**

```bash
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=~/backups/memento-pre-merge-$TS
mkdir -p "$BACKUP_DIR"
echo "$BACKUP_DIR" > /tmp/_memento_backup_dir
echo "Backup target: $BACKUP_DIR"
```

Expected: prints the backup path; `/tmp/_memento_backup_dir` holds it for later steps.

- [ ] **Step 1.2: Snapshot repo working tree (untracked + modified)**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
cd /Users/demo-user/clawd/memento-mcp
tar czf "$BACKUP_DIR/repo-working-tree.tar.gz" \
    --exclude='ui/node_modules' \
    --exclude='ui/.next' \
    --exclude='.playwright-mcp' \
    --exclude='.git' \
    .
ls -lh "$BACKUP_DIR/repo-working-tree.tar.gz"
```

Expected: tarball ~5-30 MB.

- [ ] **Step 1.3: Snapshot ~/.claude/ config (excluding heavy subdirs)**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
tar czf "$BACKUP_DIR/dotclaude-config.tar.gz" \
    --exclude='.claude/qdrant' \
    --exclude='.claude/projects' \
    --exclude='.claude/plugins/cache' \
    -C ~ .claude
ls -lh "$BACKUP_DIR/dotclaude-config.tar.gz"
```

Expected: tarball ~1-10 MB (CLAUDE.md, hooks, settings, skills).

- [ ] **Step 1.4: Snapshot the YAML memory data**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
tar czf "$BACKUP_DIR/clawd-memory.tar.gz" -C ~ clawd/memory
COUNT=$(find ~/clawd/memory -name '*.yaml' -type f | wc -l | tr -d ' ')
echo "yaml files backed up: $COUNT"
ls -lh "$BACKUP_DIR/clawd-memory.tar.gz"
```

Expected: count matches what `~/clawd/memory/*/*.yaml` contains today (≥6 files across projects).

- [ ] **Step 1.5: Snapshot Qdrant volume (stop → tar → start)**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
cd /Users/demo-user/clawd/memento-mcp
docker-compose stop qdrant
tar czf "$BACKUP_DIR/qdrant-data.tar.gz" -C ~/.claude qdrant
docker-compose start qdrant
sleep 4
curl -sf http://localhost:6333/healthz && echo " qdrant healthy"
ls -lh "$BACKUP_DIR/qdrant-data.tar.gz"
```

Expected: Qdrant goes down, gets snapshotted, comes back up; final curl prints `healthz` + `qdrant healthy`.

- [ ] **Step 1.6: Snapshot Claude Code auto-memory + hook log**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
tar czf "$BACKUP_DIR/auto-memory.tar.gz" \
    -C ~/.claude/projects/-Users-demo-user-clawd-memento-mcp memory 2>/dev/null || \
    echo "auto-memory dir absent — skipping"
cp /tmp/memento-observe.log "$BACKUP_DIR/memento-observe.log" 2>/dev/null || \
    echo "no observe log yet — skipping"
ls -lh "$BACKUP_DIR/"
```

Expected: 5 tarballs visible (or 4 if auto-memory dir absent), plus the log if present.

- [ ] **Step 1.7: Generate sha256 manifest**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
cd "$BACKUP_DIR"
shasum -a 256 *.tar.gz *.log > MANIFEST.sha256 2>/dev/null
cat MANIFEST.sha256
du -sh "$BACKUP_DIR"
```

Expected: 4-5 sha256 lines printed; total directory size ~200-400 MB.

- [ ] **Step 1.8: Verify restore-ability (smoke test, do not actually restore)**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
echo "--- repo tarball contents (first 5) ---"
tar tzf "$BACKUP_DIR/repo-working-tree.tar.gz" | head -5
echo "--- dotclaude config (CLAUDE.md + hooks + settings) ---"
tar tzf "$BACKUP_DIR/dotclaude-config.tar.gz" | grep -E 'CLAUDE\.md|hooks/|settings\.json' | head -10
echo "--- memory yaml count ---"
tar tzf "$BACKUP_DIR/clawd-memory.tar.gz" | grep '\.yaml$' | wc -l | tr -d ' '
echo "--- qdrant collection dir present ---"
tar tzf "$BACKUP_DIR/qdrant-data.tar.gz" | grep -c collection
```

Expected: file paths visible, `CLAUDE.md`/`settings.json`/`hooks/` lines present, yaml count matches Step 1.4, qdrant `collection` dirs present (≥1).

- [ ] **Step 1.9: Print rollback recipe to a README in the backup dir**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
cat > "$BACKUP_DIR/README.md" <<'EOF'
# Rollback Recipe

If anything in the merge plan goes wrong, restore in this order:

1. Stop services:
   cd /Users/demo-user/clawd/memento-mcp && docker-compose stop && pkill -f "uv run python -m server"

2. Restore Qdrant:
   tar xzf qdrant-data.tar.gz -C ~/.claude/

3. Restore YAML memories:
   tar xzf clawd-memory.tar.gz -C ~/

4. Restore ~/.claude/ config (CLAUDE.md, hooks, settings.json):
   tar xzf dotclaude-config.tar.gz -C ~/

5. Restore repo working tree (only if needed):
   cd /Users/demo-user/clawd/memento-mcp
   git stash    # save anything new
   tar xzf repo-working-tree.tar.gz

6. Restart services:
   docker-compose up -d
   MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/memento-backend.log 2>&1 &

7. Verify integrity:
   shasum -a 256 -c MANIFEST.sha256
EOF
ls "$BACKUP_DIR/README.md"
```

Expected: README written to backup dir.

- [ ] **Step 1.10: Commit nothing (this phase has no git changes), but echo confirmation**

```bash
BACKUP_DIR=$(cat /tmp/_memento_backup_dir)
echo "✓ Phase -1 complete. Backup location: $BACKUP_DIR"
```

---

## Task 2: Repo housekeeping (gitignore + stale doc removal)

**Files:**
- Modify: `/Users/demo-user/clawd/memento-mcp/.gitignore`
- Delete: `/Users/demo-user/clawd/memento-mcp/CLAUDE_CONTINUE_PROMPT.md`

- [ ] **Step 2.1: Inspect current .gitignore**

```bash
cat /Users/demo-user/clawd/memento-mcp/.gitignore | grep -E "^\.next|node_modules|playwright|brain.*png|tsbuildinfo" || echo "(no matches — entries needed)"
```

Expected: lists which entries already exist; `.playwright-mcp/`, `brain-*.png`, and `*.tsbuildinfo` are likely missing.

- [ ] **Step 2.2: Append missing entries to .gitignore**

```bash
cat >> /Users/demo-user/clawd/memento-mcp/.gitignore <<'EOF'

# Audit/debug screenshots — never commit
brain-*.png

# Playwright MCP session artifacts
.playwright-mcp/

# TypeScript incremental build cache
*.tsbuildinfo
EOF

cat /Users/demo-user/clawd/memento-mcp/.gitignore | tail -10
```

Expected: tail shows the 3 new entries.

- [ ] **Step 2.3: Verify ignored files now show as ignored**

```bash
cd /Users/demo-user/clawd/memento-mcp
git status --porcelain | grep -E "brain-.*\.png|playwright-mcp|tsbuildinfo" || echo "✓ all ignored"
```

Expected: prints `✓ all ignored` (the previously-untracked `??` lines for these patterns are gone).

- [ ] **Step 2.4: Delete stale handoff prompt**

```bash
rm /Users/demo-user/clawd/memento-mcp/CLAUDE_CONTINUE_PROMPT.md
git status --porcelain | grep CLAUDE_CONTINUE || echo "✓ deleted (no longer in untracked)"
```

Expected: file gone, no longer in `?? ` listing.

- [ ] **Step 2.5: Commit housekeeping**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add .gitignore
git commit -m "chore: gitignore audit screenshots + playwright artifacts + tsbuildinfo"
```

Expected: single commit on `feature/agent-memory-os`.

---

## Task 3: Commit current scope/storage backend changes

**Files:**
- Modify: `src/server.py` (already in working tree)
- Modify: `src/memory/manager.py` (already in working tree)

- [ ] **Step 3.1: Re-read the diffs to confirm scope is what we expect**

```bash
cd /Users/demo-user/clawd/memento-mcp
git diff src/server.py | head -80
git diff src/memory/manager.py | head -80
```

Expected: server.py shows `caller_cwd`/`caller_project` in `/api/memory/observe`; manager.py shows nested `memory_dir/{project}/{date}.yaml` write path + `_reinforce_existing_memory`.

- [ ] **Step 3.2: Smoke-test that backend still serves correctly with these changes loaded**

```bash
curl -s http://localhost:8000/api/memory/projects -o /tmp/_proj.json
/usr/bin/python3 -c "import json; d=json.load(open('/tmp/_proj.json')); print(f\"projects={len(d['projects'])} total={d['total']}\")"
```

Expected: prints `projects=≥1 total=≥292` (or however many memories exist now).

- [ ] **Step 3.3: Stage backend changes**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add src/server.py src/memory/manager.py
git status --short
```

Expected: only `M  src/server.py` and `M  src/memory/manager.py` staged.

- [ ] **Step 3.4: Commit with descriptive message**

```bash
git commit -m "fix(memory): scope from caller cwd + nested project YAML storage

/api/memory/observe now accepts cwd and project in request body and
threads them through ScopeDetector.detect(). Without this, every
observation from every Claude Code session landed under
project=memento-mcp because the backend resolved scope from its own
cwd. Endpoint also returns scope.project in response so callers can
verify attribution.

YAML write path refactored to ~/clawd/memory/<project>/<date>.yaml
(nested) so per-project rollups are cheap and the legacy flat layout
reindex-noise stops accumulating in a single file."
```

Expected: commit lands; `git log -1 --stat` shows 2 files changed.

---

## Task 4: Commit project-switcher UI work

**Files:**
- New: `ui/lib/api/projects.ts`
- New: `ui/lib/queries/use-projects.ts`
- Modify: `ui/components/shell/project-switcher.tsx`
- Modify: `ui/lib/project-store.ts`
- Modify: `ui/lib/schemas.ts`

- [ ] **Step 4.1: Stage the project-switcher files**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/lib/api/projects.ts \
        ui/lib/queries/use-projects.ts \
        ui/components/shell/project-switcher.tsx \
        ui/lib/project-store.ts \
        ui/lib/schemas.ts
git status --short
```

Expected: 5 files staged (2 new, 3 modified).

- [ ] **Step 4.2: Commit**

```bash
git commit -m "feat(ui): scope dropdown — empty=all-memories default

ProjectSwitcher reads /api/memory/projects, defaults to empty string
(all memories) instead of forcing a project filter. Adds
ProjectInfoSchema + ProjectsResponseSchema to ui/lib/schemas.ts and a
useProjects() React Query hook. Project store no longer hardcodes a
default project — empty means cross-project view."
```

Expected: commit lands; `git log -1 --stat` shows 5 files.

---

## Task 5: Commit Brain canvas improvements

**Files:**
- Modify: `ui/components/brain/brain-canvas.tsx`
- Modify: `ui/app/brain/page.tsx`
- Modify: `ui/lib/api/graph.ts`
- Modify: `ui/app/globals.css`

- [ ] **Step 5.1: Stage Brain files**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/brain/brain-canvas.tsx \
        ui/app/brain/page.tsx \
        ui/lib/api/graph.ts \
        ui/app/globals.css
git status --short
```

Expected: 4 files staged.

- [ ] **Step 5.2: Commit**

```bash
git commit -m "feat(ui): brain link sparsifier + tier-based coloring + NaN guards

At 1488 edges the force graph rendered as a hairball; new sparsifier
keeps top-2 strongest links per node and drops the rest. When 99% of
memories are 'learning' type, categorical color is useless, so color
falls back to tier when type would be uniform. Adds Number.isFinite
guards before createRadialGradient calls to prevent NaN crashes
during force simulation init."
```

Expected: commit lands; 4 files in stat.

---

## Task 6: Commit KB column + remaining UI lib

**Files:**
- Modify: `ui/components/kb/kb-columns.tsx`
- Modify: `ui/components/kb/kb-slice.tsx`
- Modify: `ui/app/kb/page.tsx`
- Modify: `ui/lib/api/kb.ts`
- Modify: `ui/lib/api/pressure.ts`
- Modify: `ui/lib/api/resume.ts`

- [ ] **Step 6.1: Stage KB + remaining lib files**

```bash
cd /Users/demo-user/clawd/memento-mcp
git add ui/components/kb/ \
        ui/app/kb/page.tsx \
        ui/lib/api/kb.ts \
        ui/lib/api/pressure.ts \
        ui/lib/api/resume.ts
git status --short
```

Expected: 6 files staged.

- [ ] **Step 6.2: Commit**

```bash
git commit -m "feat(ui): KB column bounds + pressure/resume API clients

Bounded KB columns with h-[calc(100vh-3.5rem)] + overflow-hidden +
min-h-0 so each typed slice scrolls independently instead of growing
the page. Adds API clients + Zod schemas for pressure and resume
endpoints used by the Hygiene + Continuity surfaces."
```

Expected: commit lands; 6 files in stat.

---

## Task 7: Commit infrastructure (docker-compose + scripts)

**Files:**
- New: `docker-compose.yml`
- New: `scripts/start-memento.sh`
- New: `scripts/stop-memento.sh`
- New: `scripts/` (any other scripts present)

- [ ] **Step 7.1: List untracked infrastructure files**

```bash
cd /Users/demo-user/clawd/memento-mcp
ls scripts/
git status --porcelain | grep -E "scripts|docker-compose"
```

Expected: shows `start-memento.sh`, `stop-memento.sh`, and any others; matching `??` lines in status.

- [ ] **Step 7.2: Stage infrastructure**

```bash
git add docker-compose.yml scripts/
git status --short
```

Expected: docker-compose.yml + all script files staged.

- [ ] **Step 7.3: Commit**

```bash
git commit -m "chore: docker-compose qdrant + idempotent start/stop scripts

Qdrant container with restart: unless-stopped, volume at
~/.claude/qdrant. start-memento.sh brings up qdrant → backend → UI
sequentially with health checks. stop-memento.sh cleanly stops in
reverse order. Both use 'docker-compose' (hyphen) since Docker v29
dropped the 'docker compose' subcommand on macOS."
```

Expected: commit lands.

---

## Task 8: Push current branch to origin

**Files:** none (push only)

- [ ] **Step 8.1: Verify github account is jfr992 (this repo is at jfr992/memento-mcp)**

```bash
gh auth status 2>&1 | grep -E "Active|Logged in to" | head -4
```

Expected: `Active account: true` line under `jfr992`.

- [ ] **Step 8.2: Confirm remote URL**

```bash
git remote -v
```

Expected: `origin  https://github.com/jfr992/memento-mcp.git`.

- [ ] **Step 8.3: Push the branch**

```bash
cd /Users/demo-user/clawd/memento-mcp
git push origin feature/agent-memory-os
```

Expected: pushes ~7 new commits; no errors.

- [ ] **Step 8.4: Verify on remote**

```bash
gh api repos/jfr992/memento-mcp/branches/feature/agent-memory-os \
    -q '.commit.sha + " — " + .commit.commit.message' | head -2
```

Expected: shows the latest commit SHA + first commit message line matching the most recent local commit.

---

## Task 9: Cherry-pick `ce6016e` (RRF filter fix + date filter on hierarchy)

**Files:**
- Modify: `src/core/vector_store.py:341` (filter-leak fix)
- Modify: `src/memory/manager.py` (`get_topic_clusters` gains `days_back`)
- Modify: `src/server.py` (`?days=N` on `/api/memory/context/hierarchy`)

- [ ] **Step 9.1: Inspect what ce6016e changes**

```bash
cd /Users/demo-user/clawd/memento-mcp
git show --stat ce6016e
```

Expected: 3 files changed; +/- counts visible.

- [ ] **Step 9.2: Cherry-pick onto feature/agent-memory-os**

```bash
git cherry-pick ce6016e
```

Expected: clean cherry-pick (no conflicts predicted by review agent). If conflicts arise, abort and stop: `git cherry-pick --abort` then escalate.

- [ ] **Step 9.3: Smoke-test the hierarchy date filter**

```bash
# Restart backend so changes load
pkill -f "uv run python -m server" 2>/dev/null; sleep 2
cd /Users/demo-user/clawd/memento-mcp
MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/memento-backend.log 2>&1 &
disown
sleep 6

# Hit the new ?days= param
curl -s "http://localhost:8000/api/memory/context/hierarchy?days=7&max_topics=3" \
    -o /tmp/_hier.json
/usr/bin/python3 -c "import json; d=json.load(open('/tmp/_hier.json')); print('chars:', len(d.get('context','')))"
```

Expected: chars > 0 (non-empty context restricted to last 7 days).

- [ ] **Step 9.4: Push cherry-pick**

```bash
git push origin feature/agent-memory-os
```

Expected: 1 new commit on origin.

---

## Task 10: Adopt `git-safety.sh` hook

**Files:**
- New: `~/.claude/hooks/git-safety.sh`
- Modify: `~/.claude/settings.json`

- [ ] **Step 10.1: Extract the hook from the branch into the global hooks dir**

```bash
cd /Users/demo-user/clawd/memento-mcp
git show origin/chore/sync-claude-bundle:claude/hooks/git-safety.sh > ~/.claude/hooks/git-safety.sh
chmod +x ~/.claude/hooks/git-safety.sh
ls -la ~/.claude/hooks/git-safety.sh
```

Expected: file exists, executable, ~700 bytes.

- [ ] **Step 10.2: Smoke-test the hook (no-verify should block)**

```bash
INPUT='{"tool_input":{"command":"git commit --no-verify -m test"}}'
echo "$INPUT" | bash ~/.claude/hooks/git-safety.sh
echo "exit=$?"
```

Expected: stderr says `BLOCKED: --no-verify flag is not allowed.`; exit code = 2.

- [ ] **Step 10.3: Smoke-test pass-through (normal git command)**

```bash
INPUT='{"tool_input":{"command":"git status"}}'
echo "$INPUT" | bash ~/.claude/hooks/git-safety.sh
echo "exit=$?"
```

Expected: no output; exit code = 0.

- [ ] **Step 10.4: Register in `~/.claude/settings.json` under PreToolUse → Bash**

Use the Edit tool (no shell heredoc needed) to add the hook entry alongside `rtk-rewrite.sh`.

```json
"PreToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/rtk-rewrite.sh" },
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/git-safety.sh" }
    ]
  }
]
```

Expected: jq verification: `jq '.hooks.PreToolUse[0].hooks | length' ~/.claude/settings.json` returns `2`.

---

## Task 11: Adopt `iac-safety.sh` hook

**Files:**
- New: `~/.claude/hooks/iac-safety.sh`
- Modify: `~/.claude/settings.json`

- [ ] **Step 11.1: Extract the hook**

```bash
cd /Users/demo-user/clawd/memento-mcp
git show origin/chore/sync-claude-bundle:claude/hooks/iac-safety.sh > ~/.claude/hooks/iac-safety.sh
chmod +x ~/.claude/hooks/iac-safety.sh
ls -la ~/.claude/hooks/iac-safety.sh
```

Expected: file exists, executable.

- [ ] **Step 11.2: Smoke-test block (terraform apply)**

```bash
INPUT='{"tool_input":{"command":"terraform apply -auto-approve"}}'
echo "$INPUT" | bash ~/.claude/hooks/iac-safety.sh
echo "exit=$?"
```

Expected: stderr says `BLOCKED: Destructive IaC command requires explicit user approval.`; exit code = 2.

- [ ] **Step 11.3: Smoke-test pass-through (terraform plan)**

```bash
INPUT='{"tool_input":{"command":"terraform plan"}}'
echo "$INPUT" | bash ~/.claude/hooks/iac-safety.sh
echo "exit=$?"
```

Expected: no output; exit code = 0.

- [ ] **Step 11.4: Smoke-test run-all variant block**

```bash
INPUT='{"tool_input":{"command":"terragrunt run-all destroy"}}'
echo "$INPUT" | bash ~/.claude/hooks/iac-safety.sh
echo "exit=$?"
```

Expected: stderr says `BLOCKED: Destructive IaC batch command requires explicit user approval.`; exit code = 2.

- [ ] **Step 11.5: Register in `~/.claude/settings.json` (append to existing PreToolUse Bash hooks array)**

```json
"PreToolUse": [
  {
    "matcher": "Bash",
    "hooks": [
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/rtk-rewrite.sh" },
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/git-safety.sh" },
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/iac-safety.sh" }
    ]
  }
]
```

Expected: `jq '.hooks.PreToolUse[0].hooks | length' ~/.claude/settings.json` → `3`.

---

## Task 12: Adopt `session-context.sh` hook

**Files:**
- New: `~/.claude/hooks/session-context.sh`
- Modify: `~/.claude/settings.json`

- [ ] **Step 12.1: Extract the hook**

```bash
cd /Users/demo-user/clawd/memento-mcp
git show origin/chore/sync-claude-bundle:claude/hooks/session-context.sh > ~/.claude/hooks/session-context.sh
chmod +x ~/.claude/hooks/session-context.sh
ls -la ~/.claude/hooks/session-context.sh
```

Expected: file exists, executable.

- [ ] **Step 12.2: Smoke-test in this repo (Node.js + git context expected)**

```bash
CLAUDE_PROJECT_DIR=/Users/demo-user/clawd/memento-mcp \
    bash ~/.claude/hooks/session-context.sh
```

Expected output contains:
```
--- Session Context ---
Project: Node.js
  TypeScript: yes
Branch: feature/agent-memory-os
Remote: jfr992/memento-mcp
Context: Personal project (gh auth: jfr992)
Local CLAUDE.md: found (repo-local rules active)
--- End Context ---
```

- [ ] **Step 12.3: Register under SessionStart**

Use the Edit tool to add a `SessionStart` array to `~/.claude/settings.json`:

```json
"SessionStart": [
  {
    "hooks": [
      { "type": "command", "command": "/Users/demo-user/.claude/hooks/session-context.sh" }
    ]
  }
]
```

Expected: `jq '.hooks.SessionStart[0].hooks[0].command' ~/.claude/settings.json` returns the script path.

- [ ] **Step 12.4: Validate JSON shape**

```bash
jq '.hooks | keys' ~/.claude/settings.json
```

Expected: `["PostToolUse", "PreToolUse", "SessionStart", "Stop", "UserPromptSubmit"]` — five keys.

---

## Task 13: Replace `memento-observe.sh` with gated Stop hook

**Files:**
- Modify: `~/.claude/hooks/memento-observe.sh`

**Why:** Per-turn Haiku judge fires ~50 times/session ≈ $0.05/session. Add cheap signal-detection gate in front so Haiku only fires when there's real evidence something durable happened. Target ~3 fires/session instead of 50 → 10× cost reduction.

- [ ] **Step 13.1: Confirm current hook runs Haiku unconditionally**

```bash
grep -n "claude -p" ~/.claude/hooks/memento-observe.sh | head -3
```

Expected: shows the line that pipes the exchange to `claude -p --model claude-haiku-4-5` (the per-turn Haiku call).

- [ ] **Step 13.2: Write a test harness that fires the hook with a benign exchange and measures whether Haiku was called**

Create `/tmp/_test_memento_observe.sh`:

```bash
cat > /tmp/_test_memento_observe.sh <<'BASH'
#!/usr/bin/env bash
# Wraps memento-observe.sh and counts whether it actually called `claude -p`.
# Substitutes a fake `claude` binary that just touches a marker file.
set -euo pipefail

MARKER=/tmp/_test_memento_haiku_called
rm -f "$MARKER"

# Build a fake claude that records that it was called
FAKEDIR=$(mktemp -d)
cat > "$FAKEDIR/claude" <<EOF
#!/usr/bin/env bash
echo "called" > $MARKER
echo '{"observe": false}'
EOF
chmod +x "$FAKEDIR/claude"

# Build a benign transcript (one user "thanks", one assistant "you're welcome")
TMP=$(mktemp).jsonl
cat > "$TMP" <<EOF
{"type":"user","message":{"role":"user","content":"thanks"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"you're welcome"}]}}
EOF

# Fire the hook with PATH overridden so fake claude is found first
PATH="$FAKEDIR:$PATH" \
    bash ~/.claude/hooks/memento-observe.sh <<HOOK
{"transcript_path":"$TMP","stop_hook_active":false,"cwd":"/tmp"}
HOOK

rm -f "$TMP"

if [ -f "$MARKER" ]; then
    echo "RESULT: haiku was called (current behavior — expensive)"
    exit 1
else
    echo "RESULT: haiku was NOT called (gated — cheap)"
    exit 0
fi
BASH
chmod +x /tmp/_test_memento_observe.sh
```

- [ ] **Step 13.3: Run the test against current hook — expect FAIL (haiku is called even on benign exchanges)**

```bash
/tmp/_test_memento_observe.sh
echo "exit=$?"
```

Expected: prints `RESULT: haiku was called (current behavior — expensive)` and exit 1. This confirms the test detects the unwanted behavior.

- [ ] **Step 13.4: Edit `~/.claude/hooks/memento-observe.sh` to add gate before the Haiku call**

Insert the gate block immediately before the existing `judge_out=` line. Use the Edit tool. The new gate:

```bash
# ============================================================
# Cheap signal gate — bypass Haiku unless there's real evidence
# something durable happened in this turn.
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
LAST_USER=$(printf '%s' "$exchange" | sed -n 's/^USER:.*//; /^USER:/,/^ASSISTANT:/p' | head -50)
if printf '%s' "$LAST_USER" | grep -qiE 'remember|let.?s go|decided|prefer|gotcha|fix.{0,8}root|hard rule|always|never'; then
    fire_haiku=true
fi

# Signal 3: 5+ assistant turns in transcript AND zero saves today
TURN_COUNT=$(tail -n 400 "$transcript_path" 2>/dev/null | grep -c '"role":"assistant"' || echo 0)
if [ "$TURN_COUNT" -ge 5 ]; then
    TODAY=$(date +%Y-%m-%d)
    YAML_PROJECT=$(basename "$caller_cwd")
    YAML_FILE="$HOME/clawd/memory/$YAML_PROJECT/$TODAY.yaml"
    if [ -f "$YAML_FILE" ]; then
        TODAY_SAVES=$(grep -c '^- id:' "$YAML_FILE" 2>/dev/null || echo 0)
    else
        TODAY_SAVES=0
    fi
    [ "$TODAY_SAVES" -eq 0 ] && fire_haiku=true
fi

if [ "$fire_haiku" = "false" ]; then
    trace "skipped: no durability signal"
    exit 0
fi

date +%s > "$LAST_FIRE_FILE"
trace "fire: signal detected, calling haiku"
# ============================================================
```

- [ ] **Step 13.5: Re-run the test — expect PASS (haiku NOT called on benign exchange)**

```bash
/tmp/_test_memento_observe.sh
echo "exit=$?"
```

Expected: prints `RESULT: haiku was NOT called (gated — cheap)` and exit 0.

- [ ] **Step 13.6: Run with a high-signal exchange (user says "remember") — Haiku SHOULD be called**

```bash
TMP=$(mktemp).jsonl
cat > "$TMP" <<'EOF'
{"type":"user","message":{"role":"user","content":"remember: we always use Drizzle for migrations on capillas"}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Got it — Drizzle for capillas migrations."}]}}
EOF

# Use real claude CLI for this one
echo "{\"transcript_path\":\"$TMP\",\"stop_hook_active\":false,\"cwd\":\"/Users/demo-user/clawd/memento-mcp\"}" \
    | bash ~/.claude/hooks/memento-observe.sh
echo "exit=$?"
tail -3 /tmp/memento-observe.log
rm -f "$TMP"
```

Expected: log shows `fire: signal detected, calling haiku` then `save: type=...` (haiku ran). Exit 0.

- [ ] **Step 13.7: Cost projection**

```bash
echo "Before gate: 50 turns × \$0.001/fire = \$0.05/session"
echo "After gate:  ~3 fires × \$0.001/fire = \$0.003/session"
echo "Reduction:   ~17×"
```

---

## Task 14: CLAUDE.md graft — pull 4 sections from other laptop

**Files:**
- Modify: `~/.claude/CLAUDE.md`

- [ ] **Step 14.1: Snapshot current CLAUDE.md before edit (extra paranoia — backup already covers this, but cheap)**

```bash
cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.before-graft
wc -l ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.before-graft
```

Expected: both files same line count.

- [ ] **Step 14.2: Extract the 4 source sections from the branch CLAUDE.md to a temp file**

```bash
cd /Users/demo-user/clawd/memento-mcp
git show origin/chore/sync-claude-bundle:claude/CLAUDE.md > /tmp/_branch_claude_md
grep -n "^## " /tmp/_branch_claude_md
```

Expected: prints all `## ` headers. Confirm `## Collaboration Style`, `## Workflow Engine`, `## Memory — two-lane system`, `## MR / PR descriptions`, `## Code comments` are present.

- [ ] **Step 14.3: Insert "Collaboration Style" section after "## The Vision" in `~/.claude/CLAUDE.md`**

Use the Edit tool. Source content (from branch):

```markdown
## Collaboration Style

You are working with a platform/DevOps engineer who drives technical decisions and understands the systems deeply. Treat every session as a peer technical discussion.

- **Surface options, don't just execute** — when multiple approaches exist, present them with trade-offs
- **Push back on flawed logic** — disagree directly when something is wrong or suboptimal
- **Assume technical competence** — no over-explaining common concepts
- **Acknowledge subjective calls** — when something is preferential say so, don't dress it up as objectively correct
- **Stop and discuss if something unexpected comes up during implementation** — don't silently work around it

---
```

Expected: section visible between `## The Vision` and `## The Discipline`.

- [ ] **Step 14.4: Insert "Workflow Engine" section after "Collaboration Style"**

Source content:

```markdown
## Workflow Engine

Superpowers is the default workflow engine. For non-trivial work, follow this flow:

1. **brainstorming** — explore intent, requirements, design before implementation
2. **writing-plans** — create bite-sized implementation plan with TDD steps
3. **executing-plans** or **subagent-driven-development** — implement task-by-task
4. **verification-before-completion** — evidence before claims, always
5. **finishing-a-development-branch** — merge, PR, or cleanup

Quality gates (invoke automatically when applicable):
- **test-driven-development** — no production code without a failing test first
- **systematic-debugging** — root cause before any fix
- **requesting-code-review** — dispatch code-reviewer agent after major work
- **dispatching-parallel-agents** — 2+ independent tasks = parallel execution

---
```

Expected: section sits between `## Collaboration Style` and `## The Discipline`.

- [ ] **Step 14.5: Replace existing "### 11. Memory Protocol" with cleaner "## Memory — two-lane system"**

Source content (with namespace patched from `mcp__memory__` to `mcp__memento__`):

```markdown
## Memory — two-lane system

**Memento MCP is the primary write target.** Auto-restored at session start via hook. Save via `mcp__memento__save_memory` (or `mcp__memento__observe`) when:

- Juan corrects approach → type: `learning`
- Architectural/design decision → type: `decision`
- Stated preference about tooling/workflow → type: `preference`
- Non-obvious bug root cause → type: `learning`
- Notable deployment/config outcome → type: `fact`

Save the WHY, not the WHAT. One sentence per memory. Skip routine edits/tests/commits.

**Native `~/.claude/projects/<p>/memory/` is the curated read-lane.** `MEMORY.md` loads automatically at session start as a deterministic index. Don't auto-write here — only promote stable Memento memories to native topic files when Juan explicitly asks.
```

Expected: section replaces the older `### 11. Memory Protocol` header + body. Verify with `grep -A2 "Memory — two-lane" ~/.claude/CLAUDE.md`.

- [ ] **Step 14.6: Append "MR / PR descriptions" + "Code comments" sections inside the Communications Protocol area**

Source content:

```markdown
### MR / PR descriptions

- Lead with **what changed** in 1-2 sentences. Skip the marketing.
- Show the diff in prose — readers should not have to open the changes tab to understand the contract change.
- Include a **Test plan** checklist when the change is non-trivial.
- Never use emoji. Never use "🤖 Generated with..." footers unless the user has asked for them in this repo.

### Code comments

Default to writing no comments. Only add one when the WHY is non-obvious — a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader. Never write multi-paragraph docstrings.

Don't explain WHAT the code does (well-named identifiers do that). Don't reference the current task or callers ("used by X", "added for Y") — that belongs in the PR description and rots fast.
```

Expected: both sections live under "Communications Protocol".

- [ ] **Step 14.7: Validate the graft (check sections present + line count grew sensibly)**

```bash
grep "^## " ~/.claude/CLAUDE.md | head -25
echo "---"
echo "before: $(wc -l < ~/.claude/CLAUDE.md.before-graft) lines"
echo "after:  $(wc -l < ~/.claude/CLAUDE.md) lines"
```

Expected: new headers visible (`Collaboration Style`, `Workflow Engine`, `Memory — two-lane system`, `MR / PR descriptions`, `Code comments`); after-count is greater than before-count.

- [ ] **Step 14.8: Remove the .before-graft backup once verified (real backup is in Phase -1 tarball)**

```bash
rm ~/.claude/CLAUDE.md.before-graft
```

Expected: file gone.

---

## Task 15: Final verification + push

**Files:** none (verification only)

- [ ] **Step 15.1: Verify backend still serves correctly**

```bash
curl -sf http://localhost:8000/health -o /dev/null -w "health=%{http_code}\n"
curl -s http://localhost:8000/api/memory/stats -o /tmp/_stats.json
/usr/bin/python3 -c "import json; d=json.load(open('/tmp/_stats.json')); print(f\"memories={d['total_memories']}\")"
```

Expected: `health=200`, `memories=≥292`.

- [ ] **Step 15.2: Verify UI cockpit serves**

```bash
curl -sf -o /dev/null -w "ui=%{http_code}\n" http://localhost:3333
curl -sf -o /dev/null -w "brain=%{http_code}\n" http://localhost:3333/brain
```

Expected: both 200 (or 307 redirect → still alive).

- [ ] **Step 15.3: Verify all hooks fire correctly in a sandbox prompt**

```bash
# Force a fresh session-start by clearing the marker
rm -f /tmp/memento-restored-* /tmp/memento-observe-last-fire

# UserPromptSubmit hook fires the restore script
bash ~/.claude/hooks/memento-restore.sh
echo "---"
# SessionStart context hook
CLAUDE_PROJECT_DIR=/Users/demo-user/clawd/memento-mcp \
    bash ~/.claude/hooks/session-context.sh
```

Expected: restore prints `Memento ready — N memories...` (~92 bytes); session-context prints the project/branch/remote summary.

- [ ] **Step 15.4: Confirm git state is clean**

```bash
cd /Users/demo-user/clawd/memento-mcp
git status --short
git log --oneline -10
```

Expected: status shows nothing committable except possibly `~?? brain-*.png` etc. ignored; log shows the 7 new commits + cherry-pick.

- [ ] **Step 15.5: Push final cherry-pick if not already pushed**

```bash
git push origin feature/agent-memory-os
gh api repos/jfr992/memento-mcp/branches/feature/agent-memory-os \
    -q '.commit.sha + " — " + (.commit.commit.message | split("\n")[0])'
```

Expected: latest commit on origin matches local HEAD, message is the cherry-picked `ce6016e`'s subject (`feat(kb): add date filter to hierarchy + dashboard`).

- [ ] **Step 15.6: Save observations from this work to memento**

```bash
curl -s -X POST http://localhost:8000/api/memory/observe \
    -H "Content-Type: application/json" \
    -d "$(jq -cn \
        --arg c "Completed memento config merge plan execution: pushed feature/agent-memory-os with scope-fix + UI cockpit + nested YAML storage; cherry-picked ce6016e (RRF filter-leak fix + ?days= on hierarchy); adopted git-safety + iac-safety + session-context hooks; rewrote memento-observe.sh per-turn Haiku judge with cheap signal gate (10x cost reduction, ~\$0.005/session); grafted 4 sections into ~/.claude/CLAUDE.md (Collaboration Style, Workflow Engine, Memory two-lane, MR/PR + Code comments). Skipped user-prompt-observe.sh and session-start-memory.sh as regressions of zero-injection decision. BM25 hybrid merge deferred to follow-up plan." \
        --arg t "decision" \
        --arg cwd "/Users/demo-user/clawd/memento-mcp" \
        '{summary:$c, type:$t, cwd:$cwd}')"
```

Expected: response contains `"status":"observed"` and `"project":"memento-mcp"`.

---

## Self-Review Notes

### Spec coverage
- Backup: Task 1, 10 steps ✓
- Housekeeping: Task 2 ✓
- Push current 7-commit chain: Tasks 3-8 ✓
- Cherry-pick `ce6016e`: Task 9 ✓
- Adopt 3 safety/context hooks: Tasks 10-12 ✓
- Smart Stop hook gate: Task 13 ✓
- CLAUDE.md graft: Task 14 ✓
- Final verification + observation save: Task 15 ✓
- Skip pile documented: top of plan ✓
- BM25 deferred: noted; no tasks here ✓

### Type/name consistency
- Hook file paths consistently absolute (`/Users/demo-user/.claude/hooks/...`)
- Tool namespace consistently `mcp__memento__*` (the namespace patch is applied at every reference, including in CLAUDE.md graft)
- Backup tarball filenames consistent across Phase -1 steps + rollback README

### Placeholder scan: clean
- No `TBD`, `TODO`, `add appropriate error handling`, `similar to Task N`, or step-without-code instances.
- Every step that touches a file shows the exact file + the exact content/command.

---

## Risk + Sequencing Summary

| Phase | Time | Risk | Reversible? |
|-------|------|------|-------------|
| Task 1 (Backup) | 10 min | none | yes |
| Task 2 (Housekeeping) | 10 min | none | yes |
| Tasks 3-8 (Commit + push current) | 30 min | none | yes (revert) |
| Task 9 (Cherry-pick `ce6016e`) | 10 min | low | yes |
| Tasks 10-12 (3 hooks adopted) | 30 min | none | yes (backup of `~/.claude/hooks/`) |
| Task 13 (Smart Stop hook rewrite + test harness) | 60 min | low | yes (`memento-observe.sh` is in backup) |
| Task 14 (CLAUDE.md graft) | 45 min | none | yes (CLAUDE.md is in backup) |
| Task 15 (Verification + final push) | 15 min | none | yes |

**Total: ~3.5 hours wall time. All revertable from the Phase -1 backup tarballs.**

**BM25 hybrid merge (Phase 6 of original plan) is deferred to a separate follow-up plan with its own backup, conflict resolution checklist, and benchmark validation step.**
