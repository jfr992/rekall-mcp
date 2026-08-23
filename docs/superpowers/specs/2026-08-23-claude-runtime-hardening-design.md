# Claude Runtime Hardening Design

**Status:** Approved by the user on 2026-08-23 ("fix em").

## Problem narrative

Rekall's Claude integration works, but the live Claude profile revealed four ownership and cost defects:

1. The Stop hook's supposedly cheap memory judge launches a normal nested Claude session. It therefore inherits the user's plugins, MCP servers, and `xhigh` effort. A controlled no-tool safe-mode session used roughly 4.2k input-context tokens, while an ordinary full-profile session used roughly 51k.
2. The Stop hook also scans the transcript and emits recall-utility telemetry on every stop. Claude Code now exposes `SessionEnd`, so this work belongs at the actual lifecycle boundary.
3. The shipped reflex hook does not debounce successful HTTP responses that contain no memories, and it recognizes only the legacy `REKALL_URL` variable.
4. The installer adds managed hooks but never removes three obsolete Rekall-owned lifecycle entries. Reinstalling can leave a mixed, surprising runtime.

The live profile also contains a duplicate manual Context7 MCP server whose command line carries a secret, plus both Caveman and Ponytail as overlapping always-on behavior plugins. Repository fixes must make reinstall deterministic before any live-profile cleanup.

## Decision

Use a surgical lifecycle split rather than rewriting the hook system:

- Keep cheap signal gating and memory observation in `rekall-observe.sh`.
- Run its nested judge in Claude safe mode with low effort, no tools, and no session persistence.
- Move utility telemetry to a new bounded, fail-open `rekall-session-end.sh` hook.
- Port the installed reflex hook's reserve-before-exit debounce behavior into the shipped hook and standardize URL precedence.
- Make the installer authoritative only for exact Rekall-owned hook basenames. Preserve every foreign setting and hook.
- After repository verification, back up and minimally normalize the live profile: remove the duplicate manual Context7 registration, disable Ponytail, and reinstall the verified hook bundle. Native Claude project memory remains untouched.

Rejected alternatives:

- **Unified hook rewrite:** unnecessary blast radius and weak migration safety.
- **Profile-only cleanup:** the next installer run would recreate drift.
- **Disable all plugins/MCP globally:** solves symptoms by discarding useful capabilities.
- **Use `--bare` for the judge:** it can bypass normal OAuth/keychain behavior; `--safe-mode` is the supported isolated path.

## Architecture

```text
UserPromptSubmit                 PreToolUse(Bash)
       |                               |
       v                               v
rekall-restore.sh                rekall-reflex.sh
fetch-don't-inject               local cue gate -> reserve marker
                                        -> bounded /api/memory/reflex

Stop
 |
 v
rekall-observe.sh
cheap local gate -> isolated Claude judge -> /api/memory/observe
                  (safe mode, low effort, no tools, no persistence)

SessionEnd
 |
 v
rekall-session-end.sh
bounded transcript tail -> extract IDs/outcomes -> one /api/memory/events POST

claude/setup/install.sh
copy five managed hooks -> merge settings -> remove only obsolete Rekall entries
```

## Typed boundaries

Shell hooks receive and emit JSON, but their contracts are equivalent to these typed interfaces:

```python
from typing import Literal, NotRequired, TypedDict


class ClaudeHookInput(TypedDict):
    session_id: str
    transcript_path: str
    cwd: str
    hook_event_name: str
    reason: NotRequired[str]


class SessionSummaryEvent(TypedDict):
    event: Literal["session_summary"]
    session_id: str
    project: str
    recalled_memory_ids: list[str]
    recall_count: int
    edit_count_after_recall: int
    passing_test_count_after_recall: int


class ReflexRequest(TypedDict):
    cue_groups: list[str]
    project: str
```

### Configuration precedence

The canonical base URL is:

```text
REKALL_API_URL > REKALL_URL > http://localhost:8000
```

`REKALL_URL` remains a compatibility alias.

### Judge contract

The nested judge command must include all of:

```text
--safe-mode --model <configured-cheap-model> --effort low
--tools "" --no-session-persistence
```

It remains protected by `REKALL_JUDGE_INFLIGHT=1` and the existing timeout.

### SessionEnd contract

- Requires the restore marker so unrelated Claude sessions do not emit Rekall telemetry.
- Reads no more than `REKALL_TRANSCRIPT_TAIL_BYTES` bytes; default `1_048_576`.
- Discards the first partial JSONL record if the transcript was truncated.
- Extracts memory IDs from recall/reflex results and hook attachments.
- Counts Edit/Write operations and passing test commands occurring after recall.
- Emits at most one IDs-and-counts-only `session_summary` event.
- Uses a one-second network timeout, writes nothing to stdout, and always exits zero.

## Security and failure behavior

- Transcript text, prompts, tool inputs, and tool outputs are never sent in telemetry; only identifiers and integer counts leave the hook.
- All hooks fail open and never make a permission decision.
- The installer removes only exact obsolete basenames: `rekall-precompact.sh`, `rekall-postcompact.sh`, and `rekall-commit-nudge.sh`.
- Settings backups are mode `0600`; the live profile is backed up before modification.
- Native Claude `projects/*/memory/MEMORY.md` files are out of scope and must remain byte-for-byte unchanged.
- The exposed Context7 credential cannot be repaired locally. The duplicate command-line registration will be removed, but the user must rotate or revoke the provider key.

## TDD blocks

### Safe judge

```text
RED: trigger the Stop hook and assert the fake Claude argv lacks safe flags.
GREEN: add the isolated flags and observe the assertion pass.
REFACTOR: keep judge construction in one invocation.
```

### Reflex behavior

```text
RED: two zero-result commands in one session cause two HTTP calls.
GREEN: reserve matched cue groups before empty-context exit; the second call is skipped.
RED: conflicting REKALL_API_URL and REKALL_URL select the legacy URL.
GREEN: canonical URL precedence selects REKALL_API_URL.
```

### SessionEnd telemetry

```text
RED: tests target the missing SessionEnd hook.
GREEN: extract the old utility logic into the bounded lifecycle hook.
REFACTOR: delete duplicate utility work from Stop.
```

### Installer ownership

```text
RED: seed settings with legacy Rekall entries and a foreign hook; reinstall leaves legacy entries.
GREEN: prune exact managed basenames while preserving the foreign hook and unrelated settings.
```

### Documentation parity

```text
RED: assert the Claude lifecycle docs name SessionEnd and the safe judge.
GREEN: update bundle docs and AUDIT_REPORT.md.
```

## Concrete expected outputs

After implementation:

1. A gated Stop hook invokes the fake Claude binary with every required isolation flag.
2. Two same-session zero-hit reflex commands for the same cue group issue exactly one curl request.
3. A SessionEnd transcript containing recall, Edit, and passing pytest records emits one sanitized summary event.
4. Reinstalling settings removes the three obsolete Rekall entries, adds SessionEnd once, and preserves a seeded foreign hook.
5. Focused Claude tests, the default and embedded pytest lanes, wheel tests, shell syntax checks, and `git diff --check` pass.
6. The normalized live profile has one Context7 integration, keeps Rekall connected, wires SessionEnd, and retains native Claude memory unchanged.

## Non-goals

- Changing the user's global model or effort defaults.
- Deleting native Claude memory.
- Rotating third-party credentials on the user's behalf.
- Broadly redesigning Rekall ranking, storage, or observation semantics.
