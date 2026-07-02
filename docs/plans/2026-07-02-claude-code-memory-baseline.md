# Claude Code Memory Baseline

Captured: 2026-07-02 19:20:59 EDT

## Purpose

This is a content-safe baseline for the live Rekall memory system already used
by Claude Code.

The goal is to preserve current behavior while hardening the system into a more
trustworthy agent nervous system. This baseline intentionally records counts,
configuration, and safety posture, not memory contents.

## Git State

Branch:

```text
codex/claude-code-memory-reliability-plan
```

Unrelated local files present before this baseline:

```text
 M uv.lock
?? .DS_Store
?? AGENTS.md
?? continuity-current.png
?? continuity-drawer.png
?? continuity-new.png
?? digest/
?? scripts/digest.py
```

## Live Containers

Non-test memory containers:

```text
rekall-qdrant
rekall-mcp
rekall-ui
```

Test memory container present and excluded from this baseline:

```text
rekall-qdrant-test
```

### rekall-qdrant

```text
Image: qdrant/qdrant:v1.13.4
Status: running
Health: healthy
Published ports: 0.0.0.0:6333->6333/tcp, [::]:6333->6333/tcp
Storage mount: /Users/jfr9044/.claude/qdrant -> /qdrant/storage
```

### rekall-mcp

```text
Image: rekall-mcp-mcp
Status: running
Health: healthy
Published ports: 0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp
Memory mount: /Users/jfr9044/.claude/memory -> /data/memory
MEMORY_STORAGE_PATH: /data/memory
QDRANT_URL: http://qdrant:6333
MCP_TRANSPORT: streamable-http
HOST: 0.0.0.0
PORT: 8000
REKALL_API_TOKEN: not present in inspected container environment
```

### rekall-ui

```text
Status: running
Published ports: 0.0.0.0:3333->3333/tcp, [::]:3333->3333/tcp
```

## Qdrant Baseline

Collection:

```text
agent_memory
```

Collection status:

```text
status: green
optimizer_status: ok
points_count: 810
indexed_vectors_count: 0
segments_count: 8
vector_size: 384
distance: Cosine
on_disk_payload: true
payload_indexes: type, memory_id, date, project
```

Exact count:

```text
810
```

Project counts from Qdrant payload metadata:

```text
byte-edge: 361
app: 186
general: 65
claude-dotfiles: 32
self-service-temporal-workflow-service: 26
web-app: 20
test-project: 20
memento-mcp: 16
claude-switcher: 13
byte-secrets-operator: 12
saas-dashboard: 10
claude-harness-kit: 9
gre-plugins: 7
helm: 6
byte-edge-core: 6
rekall-mcp: 5
infrastructure-ecommerce: 3
terragrunt-skill: 3
iss-monorepo: 2
byte-edge-cli: 2
diagnostic: 1
infrastructure-catalog: 1
byte-edge-api-ip-access: 1
test: 1
install: 1
byte-edge-forge: 1
```

Type counts from Qdrant payload metadata:

```text
learning: 342
fact: 199
decision: 171
preference: 54
requirement: 30
note: 13
reference: 1
```

Tier metadata from Qdrant payload metadata:

```text
unknown: 804
semantic: 3
episodic: 3
```

Provenance metadata from Qdrant payload metadata:

```text
agent unknown: 810
source_tool unknown: 810
```

This confirms provenance is effectively absent from existing live memories and
must be introduced as backwards-compatible metadata.

## Backend Baseline

Health:

```text
status: healthy
transport: streamable-http
tools_enabled: memory
```

Stats:

```text
total_memories: 810
memory_files: 124
memory_dir: /data/memory
```

Backend type counts:

```text
fact: 199
learning: 342
decision: 171
preference: 54
note: 13
requirement: 30
reference: 1
```

Knowledge graph stats:

```text
nodes: 650
edges: 2782
relations:
  related_to: 2431
  contradicts: 224
  led_to: 87
  depends_on: 28
  supersedes: 12
```

Graph endpoint note:

```text
GET /api/memory/graph?limit=1 returned node content in the response payload.
No memory content is copied into this baseline.
```

## YAML Baseline

Host YAML root:

```text
/Users/jfr9044/.claude/memory
```

YAML scan:

```text
yaml_files: 124
yaml_records: 810
yaml_parse_errors: 0
```

Project counts from YAML:

```text
byte-edge: 361
app: 186
general: 65
claude-dotfiles: 32
self-service-temporal-workflow-service: 26
test-project: 20
web-app: 20
memento-mcp: 16
claude-switcher: 13
byte-secrets-operator: 12
saas-dashboard: 10
claude-harness-kit: 9
gre-plugins: 7
byte-edge-core: 6
helm: 6
rekall-mcp: 5
terragrunt-skill: 3
infrastructure-ecommerce: 3
byte-edge-cli: 2
iss-monorepo: 2
test: 1
byte-edge-forge: 1
install: 1
infrastructure-catalog: 1
diagnostic: 1
byte-edge-api-ip-access: 1
```

YAML and Qdrant counts match at 810 records.

## Safety Observations

- The live non-test backend is exposed on all interfaces at port 8000.
- The live non-test Qdrant service is exposed on all interfaces at port 6333.
- The live UI is exposed on all interfaces at port 3333.
- `REKALL_API_TOKEN` was not present in the inspected `rekall-mcp` environment.
- Qdrant did not require a token for the inspected localhost collection reads.
- The live graph is substantial enough to be useful already, but recall evidence
  and provenance are not yet exposed in a way an agent can fully trust.

## Restore Notes

No backup was created during this read-only baseline capture.

Before applying destructive changes, create host backups:

```bash
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p ~/backups
tar czf ~/backups/pre-$TS-claude-memory.tar.gz -C ~ .claude/memory
docker compose stop qdrant
tar czf ~/backups/pre-$TS-claude-qdrant.tar.gz -C ~/.claude qdrant
docker compose start qdrant
```

Do not use the test Qdrant container or port 6334 as evidence for live memory
state.
