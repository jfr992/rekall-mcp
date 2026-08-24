# Claude Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task by task. Use `superpowers:test-driven-development` for every behavioral change and `superpowers:verification-before-completion` before claiming success.

**Goal:** Make Rekall's Claude integration lifecycle-correct, bounded, deterministic to reinstall, and materially cheaper without weakening memory utility.

**Architecture:** Preserve the existing restore/reflex/observe hooks, isolate the nested observation judge, extract utility accounting to a dedicated SessionEnd hook, and make the installer authoritative only for exact Rekall-owned entries. Normalize the live profile only after repository verification.

**Tech Stack:** Bash, Python 3 standard library, Claude Code hooks/settings JSON, pytest, uv, curl.

**Spec:** [`docs/superpowers/specs/2026-08-23-claude-runtime-hardening-design.md`](../specs/2026-08-23-claude-runtime-hardening-design.md)

## Global constraints

- Work only on `codex/support`; never push directly to main.
- Tests precede implementation and each new test must be observed failing for the expected reason.
- Hooks fail open, emit no unsolicited stdout, and never gate tool permission.
- Preserve foreign Claude settings and native Claude memory.
- Never print the exposed Context7 credential; the user must rotate it.
- Ask the user before pushing the final commit.

## Task 1: Isolate the Stop-hook judge

**Files:**
- Modify: `tests/test_hooks_session.py`
- Modify: `claude/hooks/rekall-observe.sh`

- [ ] Extend the fake Claude executable to append its argv to `FAKE_CLAUDE_ARGS`.
- [ ] Add a signal-triggered test asserting `--safe-mode`, `--effort low`, `--tools ""`, and `--no-session-persistence`.
- [ ] Run the single test and observe RED because the current command has none of those flags.
- [ ] Add the flags to the one nested Claude invocation while retaining the model, inflight guard, and timeout.
- [ ] Run the focused hook-session tests and observe GREEN.

Expected command shape:

```bash
claude --safe-mode -p --model "$MODEL" --effort low \
  --tools "" --no-session-persistence
```

## Task 2: Make reflex URL selection and debounce deterministic

**Files:**
- Modify: `tests/test_reflex_hook.py`
- Modify: `claude/hooks/rekall-reflex.sh`

- [ ] Add a test that runs two same-session IAC cues against an empty response and expects one curl call.
- [ ] Add a test that sets conflicting URL variables and expects `REKALL_API_URL` to win.
- [ ] Run both tests and observe RED.
- [ ] Implement `REKALL_API_URL > REKALL_URL > default` once at the top of the hook.
- [ ] When the server returns no cue groups, fall back to locally matched groups and reserve their markers before empty-context exit.
- [ ] Run all reflex tests and observe GREEN.

## Task 3: Move utility accounting to SessionEnd

**Files:**
- Modify: `tests/test_observe_hook_summary.py`
- Modify: `claude/hooks/rekall-observe.sh`
- Create: `claude/hooks/rekall-session-end.sh`

- [ ] Retarget the summary test harness to the not-yet-existing SessionEnd hook.
- [ ] Add assertions that Stop contains no `session_summary`, the new hook contains a bounded-tail control, empty/invalid input exits zero, and no transcript content appears in the POST body.
- [ ] Run the summary tests and observe RED because the hook is missing.
- [ ] Extract the existing utility parsing into the new hook.
- [ ] Parse the SessionEnd JSON contract, require the restore marker, and read only the last `REKALL_TRANSCRIPT_TAIL_BYTES` bytes (default 1 MiB), dropping an initial partial JSONL line.
- [ ] Emit at most one event with memory IDs and integer counts, curl timeouts `0.1/1`, no stdout, and fail-open exit zero.
- [ ] Delete the utility block from `rekall-observe.sh`.
- [ ] Run summary and Stop-hook tests and observe GREEN.
- [ ] Run `bash -n` for every Claude hook.

## Task 4: Give the installer explicit ownership and migration behavior

**Files:**
- Modify: `tests/test_claude_startup_hook.py`
- Modify: `claude/setup/install.sh`
- Modify: `claude/settings.example.json`

- [ ] Add an installer test whose settings contain all three obsolete Rekall hooks, a foreign hook, and unrelated top-level configuration.
- [ ] Assert reinstall removes only the obsolete exact basenames, adds SessionEnd exactly once with timeout 3, and preserves foreign/unrelated data.
- [ ] Run the test and observe RED.
- [ ] Add `rekall-session-end.sh` to the default hook copy list.
- [ ] Extend the settings merger with a reusable exact-basename predicate and prune empty entries/events.
- [ ] Add SessionEnd to the example settings.
- [ ] Run installer, startup, hook-session, reflex, and summary tests and observe GREEN.

## Task 5: Repair documentation and audit parity

**Files:**
- Modify: `tests/test_docs_parity.py`
- Modify: `claude/INSTALL.md`
- Modify: `CLAUDE.md`
- Modify: `docs/AGENT_STARTUP.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `README.md` if its hook inventory is stale
- Modify: `AUDIT_REPORT.md`

- [ ] Add parity assertions for the five-hook Claude bundle, SessionEnd utility accounting, safe/low judge, and obsolete-hook migration.
- [ ] Run the new parity tests and observe RED.
- [ ] Replace the stale “no native end-of-session hook” claim.
- [ ] Document the lifecycle split, safe judge, URL precedence, migration ownership, and five default hooks.
- [ ] Add an audit finding with measured runtime bloat, shipped fixes, live cleanup, residual credential-rotation action, and verification evidence.
- [ ] Run documentation parity and grep for contradictory lifecycle claims; observe GREEN.

## Task 6: Verify repository behavior and review the diff

- [ ] Run focused Claude tests:

```bash
uv run --extra dev pytest -q \
  tests/test_observe_hook_summary.py \
  tests/test_hooks_session.py \
  tests/test_reflex_hook.py \
  tests/test_claude_startup_hook.py \
  tests/test_docs_parity.py
```

- [ ] Run shell syntax and static checks:

```bash
for hook in claude/hooks/*.sh; do bash -n "$hook"; done
git diff --check
```

- [ ] Run all required lanes:

```bash
uv run --extra dev pytest -q
REKALL_TEST_LANE=embedded uv run --extra dev pytest -q
uv run --extra dev pytest -m wheel
```

- [ ] Review the complete diff for secrets, PII, duplicate logic, unbounded I/O, fragile basename matching, and accidental profile changes.
- [ ] If any test fails, use `superpowers:systematic-debugging`; do not patch speculatively.

## Task 7: Normalize and re-evaluate the live Claude profile

- [ ] Inventory counts and checksums without printing MCP command arguments or secrets.
- [ ] Back up `~/.claude/settings.json` and `~/.claude.json` with mode `0600`.
- [ ] Record checksums for `~/.claude/projects/*/memory/MEMORY.md`.
- [ ] Remove the duplicate manual user Context7 MCP registration while retaining the official plugin integration.
- [ ] Disable Ponytail; keep Superpowers and Caveman.
- [ ] Install the verified hooks-only bundle through the repository installer.
- [ ] Verify exactly one Context7 integration, Rekall connectivity, SessionEnd wiring, absence of obsolete managed entries, and unchanged native-memory checksums.
- [ ] Run a safe judge control and one focused Rekall recall evaluation; report tokens/cost only as directional measurements.
- [ ] Report residual user actions: rotate/revoke the exposed Context7 key and complete any interactive OAuth re-login.

Rollback uses the timestamped profile backups. Do not delete the stale secondary Claude binary during this task.

## Task 8: Commit and request push approval

- [ ] Inspect `git status`, diff summary, and final verification evidence.
- [ ] Create one focused commit on `codex/support`; do not bypass hooks.
- [ ] Ask the user before pushing the commit to PR #96.
- [ ] After approval, push the feature branch and confirm PR checks.
