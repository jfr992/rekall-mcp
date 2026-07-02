# Transferring memories between machines (or memento versions)

Use this guide when you have an existing memento install on one machine (or an older version) and want to move its memories to another setup. The destination must already be running memento (see [`docs/SETUP.md`](SETUP.md) and [`README.md`](../README.md)).

For per-version upgrades on the *same* machine (e.g. v1.4 → v1.5 in place), see [`docs/MIGRATION.md`](MIGRATION.md).

---

## Before you start

On both machines, confirm:

```bash
# Rekall version
grep '^version' pyproject.toml                                  # e.g. 1.5.0

# Memory count + graph (your "expected delta" for verification later)
curl -s http://localhost:8000/api/memory/stats \
    | python3 -c "import json,sys; d=json.load(sys.stdin); \
        print(f\"{d['total_memories']} memories · {d['knowledge_graph']['nodes']} nodes · {d['knowledge_graph']['edges']} edges\")"
```

Write down the source machine's count. After migration on the destination, the destination's count should grow by approximately that amount (minus any cosine-≥0.97 dedup hits).

---

## Three paths

| Path | When to use | Speed | Re-embeds? |
|------|-------------|-------|------------|
| **A — Qdrant snapshot transfer** | Same embedding model both sides (default `all-MiniLM-L6-v2`, 384-dim — true since v1.0) | Fast (minutes) | No — preserves embeddings |
| **B — YAML re-ingestion via REST** | Embedding model differs, snapshot transfer fails, or you want every memory re-classified under v1.5 schema at write time | Slow (re-embeds everything) | Yes |
| **C — Direct YAML copy** | Edge case — you only need YAMLs as a reference and will rebuild Qdrant from scratch later | Trivial | Yes (next time something triggers re-index) |

**Recommended: Path A first, fall back to Path B if it fails.**

---

## Path A — Qdrant snapshot transfer

### On the SOURCE machine

```bash
# 1. Trigger a Qdrant snapshot of the agent_memory collection
curl -sX POST http://localhost:6333/collections/agent_memory/snapshots | jq .

# 2. Find the snapshot file
SNAP=$(docker exec rekall-qdrant ls -t /qdrant/storage/snapshots/agent_memory/ | head -1)
echo "Snapshot: $SNAP"

# 3. Copy it out of the container
docker cp "rekall-qdrant:/qdrant/storage/snapshots/agent_memory/$SNAP" "$HOME/Desktop/$SNAP"

# 4. Tarball the YAML directory (human-editable source of truth)
#    MEMORY_DIR resolves to whatever MEMORY_STORAGE_PATH points to (default ~/.claude/memory).
MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
tar czf "$HOME/Desktop/old-memento-yaml.tar.gz" -C "$(dirname "$MEMORY_DIR")" "$(basename "$MEMORY_DIR")"
```

You now have two files on the source's `~/Desktop/`. Transfer both to the destination machine (AirDrop / scp / iCloud).

### On the DESTINATION machine

#### 1. Backup destination state first

```bash
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=~/backups/pre-transfer-$TS
mkdir -p "$BACKUP_DIR"

docker compose stop qdrant
tar czf "$BACKUP_DIR/qdrant-current.tar.gz" -C ~/.claude qdrant
docker compose start qdrant
sleep 4

MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
tar czf "$BACKUP_DIR/memory-current.tar.gz" \
    -C "$(dirname "$MEMORY_DIR")" "$(basename "$MEMORY_DIR")"

# Save the BEFORE count for verification
curl -s http://localhost:8000/api/memory/stats > "$BACKUP_DIR/stats-before.json"
echo "Backup at: $BACKUP_DIR"
```

#### 2. Drop the YAMLs into a tagged subdir

```bash
mkdir -p /tmp/old-memento-extract
tar xzf ~/Desktop/old-memento-yaml.tar.gz -C /tmp/old-memento-extract

MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
mkdir -p "$MEMORY_DIR/imported-old"
# The tarball contains whatever directory the source had — rsync from any layout:
rsync -a --prune-empty-dirs \
    --include='*/' --include='*.yaml' --exclude='*' \
    /tmp/old-memento-extract/ "$MEMORY_DIR/imported-old/"

find "$MEMORY_DIR/imported-old" -name '*.yaml' | wc -l
```

#### 3. Restore the Qdrant snapshot

```bash
SNAP="<snapshot-filename>.snapshot"      # the file you copied over
docker cp ~/Desktop/$SNAP rekall-qdrant:/qdrant/storage/snapshots/agent_memory/

curl -sX PUT "http://localhost:6333/collections/agent_memory/snapshots/recover" \
  -H "Content-Type: application/json" \
  -d "{\"location\": \"file:///qdrant/storage/snapshots/agent_memory/$SNAP\"}"
```

The restore call merges the snapshot's points into the existing collection. Existing memories on the destination are preserved.

#### 4. Backfill v1.5 schema (only if source was a pre-1.5 version)

```bash
# Dry-run first — review what will change
curl -sX POST http://localhost:8000/api/memory/lifecycle/backfill \
    -H "Content-Type: application/json" -d '{"dry_run": true}' | python3 -m json.tool

# Apply
curl -sX POST http://localhost:8000/api/memory/lifecycle/backfill \
    -H "Content-Type: application/json" -d '{"dry_run": false}' | python3 -m json.tool
```

This adds `tier`, `durability`, `lifecycle_reason`, `retention_days`, `reinforcement_count` to memories that don't have them.

#### 5. Rebuild graph edges

```bash
curl -sX POST http://localhost:8000/api/memory/graph/rebuild | python3 -m json.tool
```

The auto-linker re-runs against the merged collection and recreates typed edges (`supersedes`, `contradicts`, `led_to`, `depends_on`, `related_to`).

#### 6. Verify

```bash
curl -s http://localhost:8000/api/memory/stats | python3 -c "import json,sys; d=json.load(sys.stdin); \
    print(f\"AFTER: {d['total_memories']} memories · {d['knowledge_graph']['nodes']} nodes · {d['knowledge_graph']['edges']} edges\")"
```

Compare to the BEFORE count + the source's count. Difference should approximate the source's count, minus any near-duplicate dedup.

Sanity-check by recalling something you know was in the source:

```bash
curl -s -X POST http://localhost:8000/api/memory/recall \
    -H "Content-Type: application/json" \
    -d '{"query": "<something specific from the source>", "top_k": 5}' \
    | python3 -m json.tool | head -40
```

Or open the cockpit at `http://localhost:3333/brain` — your imported memories should be visible in the graph.

---

## Path B — YAML re-ingestion (fallback)

Run this on the destination if Path A's Qdrant restore fails (volume permissions, version skew, snapshot format mismatch).

You still need the YAML tarball from the source — Path B doesn't need the Qdrant snapshot.

```bash
# Extract tarball as in Path A step 2
mkdir -p /tmp/old-memento-extract
tar xzf ~/Desktop/old-memento-yaml.tar.gz -C /tmp/old-memento-extract

# Re-ingest via /api/memory/observe (re-embeds, dedup applied)
PYTHONPATH=src:. uv run python - <<'PY'
import yaml, requests, glob, os
ok = skip = 0
for path in sorted(glob.glob('/tmp/old-memento-extract/**/*.yaml', recursive=True)):
    with open(path) as f:
        d = yaml.safe_load(f) or {}
    for section in ['decisions','requirements','preferences','learnings','facts','notes']:
        for entry in (d.get(section) or []):
            content = (entry.get('content') or '').strip()
            if not content:
                skip += 1; continue
            project = entry.get('project') or 'imported-old'
            r = requests.post(
                'http://localhost:8000/api/memory/observe',
                json={
                    'summary': content,
                    'type': section.rstrip('s'),
                    'project': project,
                    'cwd': f'/Users/{os.environ["USER"]}/imports/{project}',
                },
                timeout=10,
            )
            if r.ok: ok += 1
            else: skip += 1
print(f'imported={ok} skipped={skip}')
PY

# Then run the same backfill + graph rebuild as Path A steps 4-5
curl -sX POST http://localhost:8000/api/memory/lifecycle/backfill -H "Content-Type: application/json" -d '{"dry_run": false}'
curl -sX POST http://localhost:8000/api/memory/graph/rebuild
```

`mcp__rekall__observe`'s cosine-≥0.97 dedup means re-running this script is idempotent — duplicates collapse via reinforcement instead of creating new entries.

---

## Path C — Direct YAML copy

Only useful if you want the YAML history but plan to start with empty embeddings. Skip unless you know why.

```bash
MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
mkdir -p "$MEMORY_DIR/imported-old"
cp /tmp/old-memento-extract/memory/*.yaml "$MEMORY_DIR/imported-old/"
# Memories are on disk but not searchable until something writes them to Qdrant.
# Use Path B's loop, or just re-save each memory via observe.
```

---

## Rollback

If migration messes up the destination's memory state:

```bash
# Stop services
docker compose stop qdrant
pkill -f "uv run python -m server" || true

# Restore from the pre-transfer backup
tar xzf ~/backups/pre-transfer-<TS>/qdrant-current.tar.gz -C ~/.claude/
MEMORY_DIR="${MEMORY_STORAGE_PATH:-$HOME/.claude/memory}"
rm -rf "$MEMORY_DIR"
tar xzf ~/backups/pre-transfer-<TS>/memory-current.tar.gz -C "$(dirname "$MEMORY_DIR")"

# Restart
docker compose start qdrant
sleep 4
MCP_TRANSPORT=streamable-http nohup uv run python -m server > /tmp/rekall-backend.log 2>&1 &
disown
sleep 6

# Verify count matches stats-before.json
curl -s http://localhost:8000/api/memory/stats | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_memories'])"
```

---

## Notes

- **Embedding model compatibility**: memento has used `all-MiniLM-L6-v2` (384-dim) since v1.0. If you've switched providers (Ollama, Gemini) on either machine, snapshot transfer (Path A) won't work — embeddings are incompatible. Use Path B.
- **Project scope**: imported memories all land under whatever `project` they had in the source YAML. To re-tag, edit the project field on disk before running graph rebuild, or use Path B with explicit `project` overrides.
- **Knowledge graph edges**: never transfer directly. Always rebuild on the destination — the auto-linker uses the *destination's* memory set, not the source's, to compute edges.
- **Identity-tier memories**: pre-1.5 memories don't have a tier. After backfill, they default to `episodic` unless content matches identity-classification rules. Promote manually via the cockpit's Hygiene surface if needed.
