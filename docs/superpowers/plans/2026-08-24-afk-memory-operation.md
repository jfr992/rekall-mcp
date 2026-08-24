# AFK memory operation contract — implementation plan

**Base:** `1e0b492` (release v1.14.0)
**Branch:** `codex/afk-operation-contract`
**Scope:** `src/memory/manager.py`, `src/server.py`, focused tests, and the REST table.

## Problem narrative

AFK needs a durable evidence record for each independently retryable pipeline
operation. Existing Rekall `save()` intentionally semantic-deduplicates content,
which is correct for ordinary memory but loses the identity of two distinct AFK
operations that happen to produce identical text. Retrying the *same* AFK
operation must return the already durable record without a second vector write;
reusing an operation key with changed normalized input must fail closed. A process
may die after the YAML durability point and before vector/indexing or HTTP
response; retry must find the YAML record and recover its exact response.

All writers share a YAML file. A read/modify/replace sequence without a process
lock loses accepted writes under concurrent AFK or ordinary requests. The common
writer therefore holds a POSIX advisory `flock`, rereads the target YAML while
locked, rejects duplicate ids, atomically replaces a fully flushed temporary
file, and fsyncs the containing directory. The vector store remains after YAML:
YAML is the idempotency authority and accepted data never disappears.

## Architecture and data flow

```text
POST /api/memory/afk/save
        |
        v
strict request parse -> sanitize content -> canonical normalized envelope
        |                         |                    |
        |                         +---- sign -----------+ (SHA-256 envelope)
        v
MemoryManager.save_afk_operation
        |
        +-- flock(project/date .lock) -- reread YAML -- operation lookup
        |        |                         |              |
        |        |                         |              +-- same envelope -> prior response
        |        |                         |              +-- differing envelope -> ConflictError (409)
        |        |                         +-- absent -> append operation memory
        |        |                                      -> temp write, flush/fsync, replace, dir fsync
        |        +-- release
        |
        +-- encode + vector save (retryable after a crash)
        v
200 { memory_id, envelope, canonical_content, sanitized }

GET /api/memory/afk/operations/{id}?project=&operation_date=
        -> derive scoped memory id -> scan authoritative YAML -> exact operation record | 404

ordinary save -> same locked YAML writer -> retains ordinary semantic dedupe behavior
```

## Typed contract

```python
class AfkSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str             # non-empty, bounded opaque identifier
    operation_date: date          # YYYY-MM-DD; never server current date on retry
    content: str
    tag: str
    proposed: str
    type: Literal["decision", "learning", "preference", "requirement", "fact", "note", "session", "summary"]
    project: str                  # `_safe_project` validated

class AfkEnvelope(TypedDict):
    operation_id: str
    operation_date: str
    project: str
    type: str
    tag: str
    proposed: str
    canonical_content: str        # Sanitizer.sanitize(content), before signing
    digest: str                   # sha256 canonical JSON of all normalized fields above

class AfkSaveResponse(TypedDict):
    memory_id: str                # <date>_<type>_<sha256(project + NUL + operation_id)>
    envelope: AfkEnvelope
    canonical_content: str
    sanitized: bool
```

`operation_id` idempotency scope is `(project, operation_date, operation_id)`;
project/date isolate identical opaque IDs. The deterministic memory identity
contains `project NUL operation_id` and the operation date, preserving
project/date isolation. The stored YAML entry carries `afk_operation` with the
exact envelope and response fields. Lookup returns that entry exactly.

## RED test matrix

| Test | Expected RED / final assertion |
|---|---|
| sanitize then sign | raw secret absent from YAML/envelope/digest material; canonical content signed |
| same key retry | same response and one YAML entry/vector write |
| same key changed normalized input | `409` conflict, prior record untouched |
| distinct keys, same content | two distinct AFK IDs/records (AFK-only dedupe bypass) |
| project/date isolation | same ID can exist in separate projects and dates; original date retry remains original date |
| crash after YAML | retry finds YAML authority, returns exact record, repairs vector, creates no duplicate |
| stock delete | ordinary `delete(memory_id)` removes AFK YAML/vector record through existing semantics |
| AFK concurrency | N concurrent distinct operations leave N accepted entries |
| mixed concurrency | AFK + ordinary saves to same project/date lose none; ordinary duplicate still reinforces |

## TDD sequence

1. Add contract and concurrency tests only; run the three focused files and
   commit their intentional failure(s).
2. Add `AfkOperationConflict` plus narrowly scoped manager/server logic. Keep
   the application manager I/O-free except its existing storage/vector ports;
   introduce no dependency or framework.
3. Centralize file persistence behind the shared flocked atomic writer, then
   route `_save_to_file` through it without altering normal save decisions.
4. Run the focused command:
   `uv run pytest -q tests/test_afk_memory_contract.py tests/test_memory.py tests/test_server_recall_hint.py`
   followed by lint/build-relevant checks only. Do not run full pytest in this
   budgeted task.

## Concrete expected output

```json
{
  "memory_id": "2026-08-24_note_<64-lowercase-hex>",
  "envelope": {
    "operation_id": "attack:sha256:abc",
    "operation_date": "2026-08-24",
    "project": "afk",
    "type": "note",
    "tag": "attack",
    "proposed": "Keep evidence",
    "canonical_content": "token=[REDACTED]",
    "digest": "<64-lowercase-hex>"
  },
  "canonical_content": "token=[REDACTED]",
  "sanitized": true
}
```

A retry returns byte-equivalent JSON fields. A changed envelope at the same
scope returns `409 {"error": "...conflict..."}`; a missing lookup returns 404.
