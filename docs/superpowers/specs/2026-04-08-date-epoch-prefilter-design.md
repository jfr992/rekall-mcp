# Date Epoch Pre-Filter for Recall

**Date**: 2026-04-08
**Status**: Approved
**Problem**: `days` filter in `recall_memories()` is applied post-retrieval, causing incomplete results for temporal queries like "what did we do this week"

## Problem

The `days` parameter filters results *after* vector search + ranking. If a memory doesn't semantically match the query well enough to land in the top K×2 candidates, it's excluded before the date filter ever runs. This makes `days` unreliable for completeness queries.

**Root cause**: Qdrant `Range` requires numeric values, but `date` is stored as a `YYYY-MM-DD` string. The workaround was post-retrieval string comparison, which defeats the purpose of a date filter.

## Solution

Add a `date_epoch` integer field to every Qdrant point payload. Use Qdrant `Range(gte=cutoff_epoch)` as a pre-filter in the vector search query.

## Changes

### 1. VectorStore init (`src/core/vector_store.py`)

Add integer payload index on `date_epoch` alongside existing keyword indexes:

```python
client.create_payload_index("memories", "date_epoch", PayloadSchemaType.INTEGER)
```

### 2. Save path (`src/memory/manager.py` — `save()`)

Add `date_epoch` to payload:

```python
date_epoch = int(datetime.strptime(date, "%Y-%m-%d").timestamp())
payload = {
    ...
    "date_epoch": date_epoch,
    ...
}
```

No fields removed. Purely additive.

### 3. Recall path (`src/memory/manager.py` — `recall()`)

When `days_back` is specified, add `Range` filter to Qdrant query:

```python
cutoff_epoch = int((datetime.now() - timedelta(days=days_back)).timestamp())
filters["date_epoch"] = Range(gte=cutoff_epoch)
```

Remove the post-retrieval string comparison filter:

```python
# REMOVE: scored = [r for r in scored if (r.get("date") or "") >= cutoff_date]
```

### 4. Server graph endpoint (`src/server.py`)

Replace `_cutoff_date` string filter in `_parse_graph_filters()` with `date_epoch` Range filter. Remove post-retrieval date filtering in `/api/memory/graph` endpoint.

### 5. Backfill migration

One-time migration to add `date_epoch` to all existing Qdrant points:

1. Scroll all points in the `memories` collection
2. For each point, read `date` from payload, compute `date_epoch = int(datetime.strptime(date, "%Y-%m-%d").timestamp())`
3. Use `set_payload` to update (no re-indexing of vectors)
4. Create the integer index if it doesn't exist

Can be triggered via existing `rebuild_knowledge_graph` endpoint or a standalone migration function.

## Testing

- Unit test: save a memory, recall with `days=1`, verify it's returned
- Unit test: save a memory with old date, recall with `days=1`, verify it's excluded
- Integration test: save 10 memories across 5 days, recall with `days=3`, verify completeness (all memories from last 3 days returned, none older)
- Regression test: recall without `days` parameter still works (no filter applied)

## Risks

- **Backfill**: If Qdrant is unavailable during migration, existing memories won't have `date_epoch`. Recall should handle missing field gracefully (fall back to no date filter for that point, or skip it).
- **Timezone**: `datetime.strptime(date, "%Y-%m-%d").timestamp()` uses local timezone. Consistent because both save and recall use the same machine. If multi-machine deployment is needed later, switch to UTC explicitly.
