# Memory Publish — OKF Bundle Exporter

**Status:** Approved design (2026-07-01)
**Scope:** Export Memento memory (per-project or all) to a conformant OKF v0.1
markdown+YAML bundle. Preview always; output as tarball download or write-to-dir.
Surfaced via REST endpoint, MCP tool, Claude Code skill, and a `/kb` cockpit tab.
Export-only — no change to how memory is stored.

---

## 1. Background

Memento stores memories as YAML (source of truth) + Qdrant vectors + a networkx
knowledge graph (`_graph.json`). That knowledge is trapped in the store — readable
only through recall or the cockpit. The [Open Knowledge Format
(OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
v0.1 is a vendor-neutral spec for portable, human- and agent-readable knowledge:
"just files, just markdown, just YAML frontmatter." Exporting to OKF turns a
memory scope into a shareable, git-friendly, GitHub-renderable bundle.

This is a differentiator: competing memory systems (mem0, Zep, basic-memory) store
memory but do not emit an open, portable knowledge format.

### OKF v0.1 conformance rules (from SPEC.md, verbatim intent)

- **Required frontmatter:** only `type` (non-empty string). All else optional.
- **Optional/recommended:** `title`, `description`, `resource`, `tags`, `timestamp`.
- **Concept ID** = file path within the bundle, minus `.md` (`tables/users.md` → `tables/users`).
- **Reserved filenames:** `index.md` (directory listing), `log.md` (update history).
  Both optional; MUST NOT be used for concept docs. All other `.md` are concepts.
- **Cross-links:** standard markdown links; bundle-relative (`/…`) recommended
  (stable under moves). Relationship type conveyed in prose, not the link.
- **Timestamp:** ISO 8601 (`2026-05-28T14:30:00Z`).
- **Conformance:** every non-reserved `.md` has parseable frontmatter with non-empty
  `type`. Consumers MUST tolerate unknown types, unknown keys, broken links, missing
  `index.md`. Producers may add arbitrary extra frontmatter keys.

---

## 2. Architecture

Read-only, one direction:

```
YAML + _graph.json
   │  (manager loads memories + KnowledgeGraph)
   ▼
publish.build_bundle(memories, graph, *, title_fn, renderer)   # src/memory/publish.py
   │  1. filter (drop test-project, sub-40-char notes)
   │  2. cluster memories via graph connected components
   │  3. title each cluster (title_fn: Haiku → cache → slug)
   │  4. hand clusters to renderer
   ▼
renderers/okf.py  →  Bundle{ tree: [paths], files: {path: content}, stats: {...} }
   │
   ├─► endpoint /api/memory/publish  →  JSON (preview) | tar.gz | write-to-dir
   ├─► MCP tool  publish_memory()     →  shared code path, returns tree + summary
   └─► skill memento-publish (thin)   →  invokes tool, prints tree + path
```

### Modules (new)

| File | Responsibility | ~LOC |
|---|---|---|
| `src/memory/publish.py` | Orchestration: filter → cluster → title → renderer. Format-agnostic. Pure; deps injected. | ~200 |
| `src/memory/renderers/okf.py` | OKF v0.1 emission: frontmatter, concept paths, cross-links, `index.md`. | ~150 |
| `src/memory/renderers/__init__.py` | `get_renderer(format)` — dict lookup, not a registry. | ~10 |

**Key seam:** `title_fn` and `renderer` are **injected** into `build_bundle`, not
imported internally. This makes the orchestration testable without an LLM (pass a
slug `title_fn`) and swappable for future formats (pass a different renderer). No
base classes or plugin registry until a second format actually exists — the
`renderers/` directory convention is the only concession to future formats.

### Touched (existing)

- `src/server.py` — one thin `@mcp.custom_route("/api/memory/publish")` handler.
- `src/tools/builtin/memory.py` — one `@mcp.tool()`.
- `ui/` — schema, api client, query hook, `/kb` tab (no new route).
- `scripts/digest.py` — **retired**; the endpoint + tool supersede it. (Removes the
  duplication introduced during exploration.)

---

## 3. Clustering & titling

### Clustering

1. Load `KnowledgeGraph`; take the subgraph for the scope (one project or all).
2. **Connected components** over *grouping* edges only: `related_to`, `led_to`,
   `depends_on`, `part_of`, `supersedes`. **Exclude `contradicts`** — a contradiction
   links two memories that should remain separate concepts, not merge.
   `nx.connected_components(G.to_undirected())`.
3. Each component = one cluster = one concept doc. Singletons (no grouping edges) =
   their own one-section doc.
4. **Cap cluster size at 15** (`# ponytail: split at 15, tune if docs read badly`).
   Oversized components split by memory type.

### Titling — injected `title_fn(cluster) -> (title, summary)`

```
title_fn(cluster):
    key = hash(sorted member ids)          # stable cache key
    if key in cache: return cache[key]      # preview == export; re-run stable
    if judge_available():                   # Haiku via existing MEMENTO_JUDGE_MODEL
        t = haiku("Name this cluster in 3-6 words + one-line summary")
        if not plausible(t): t = slug_from_hub(cluster)   # length/format guard
    else:
        t = slug_from_hub(cluster)          # highest-degree member, first ~5 words
    cache[key] = t
    return t
```

- **Cache** at `~/.claude/memory/_publish_cache.json`, keyed by member-id-set hash.
  Survives restarts; makes preview and later export identical; re-runs free unless
  cluster membership changes.
- **Slug fallback** is deterministic and always correct → keyless operation works,
  preserving the local-first / no-API-key promise. Haiku only prettifies titles.
- Filename = slugified title; collision → append short hash.
- `stats.titled_by` reports `"haiku"` or `"slug"` so the UI is honest.

### Concept doc shape

```markdown
---
type: runbook                 # dominant member type, mapped to OKF-friendly noun
title: KubeVirt namespace recovery
tags: [byte-edge, learning]
timestamp: 2026-05-28T14:30:00Z   # newest member's timestamp
---
<one-line summary from title_fn>

## <memory 1 content>
_2026-05-28 · reinforced ×3_

## <memory 2 content>
...

## Related
- [ghost-pod recovery](/byte-edge/runbooks/ghost-pods.md)
```

- Type mapping: `learning`→`runbook`, `decision`→`decision`, `preference`→`preference`,
  `requirement`→`requirement`, `fact`→`fact`, `note`→`note`. OKF only requires *a*
  type string, so this is free and forgiving.
- **`contradicts` and cross-cluster edges become links** in a `## Related` / `##
  Conflicts` section — the 224 contradiction edges stay visible without merging clusters.

---

## 4. Endpoint, MCP tool, skill

### Endpoint — `@mcp.custom_route("/api/memory/publish", methods=["GET","POST"])`

| Param | Values | Purpose |
|---|---|---|
| `project` | name / omitted = all | scope; honors the "all"/empty sentinel |
| `format` | `okf` (default) | renderer selection |
| `mode` | `preview` (default) / `tar` / `dir` | output kind |
| `dest` | path (only `mode=dir`) | write target |

Returns:
- `preview` → `_ok({tree: [...], files: {path: content}, stats: {concepts, clusters, titled_by}})`.
- `tar` → `StreamingResponse` of `.tar.gz`, `Content-Disposition: attachment`.
- `dir` → writes files, `_ok({written: N, path})`.

**Security — write path (`mode=dir`) is the only dangerous surface:**
- `dest` resolved against an allowlisted base: `MEMENTO_PUBLISH_DIR` (default
  `~/.claude/publish`).
- `Path(dest).resolve()` MUST stay inside that base, else `_bad_request`. Blocks `../`.
- Write to a temp dir then atomic move; on partial failure, fail the whole op and
  report what was not written. No half-bundle reported as success.
- `preview`/`tar` write nothing → safe by construction.

### MCP tool — `publish_memory(project=None, format="okf", mode="preview", dest=None)`

Thin. Calls the same shared function as the endpoint (not an HTTP self-call).
Docstring trigger-shaped: *"Use when exporting memory to a shareable knowledge
bundle (OKF markdown)."* Returns tree + summary as text.

### Skill — `memento-publish` (thin wrapper)

`claude/skills/memento-publish/SKILL.md`: frontmatter (`name`, `description: "Use
when the user wants to export/publish memory to an OKF bundle"`) + short body that
invokes `publish_memory` and prints the tree + output path. No logic. Inert until
installed, like the other shipped skills. Uses the correct `mcp__<server>__*`
namespace (noting the known `memory` vs `memento` naming inconsistency — resolved,
not papered over).

---

## 5. Cockpit UI — "Export OKF" tab in `/kb`

Follows the repo pattern: schema → api client → query hook → component.

1. `ui/lib/schemas.ts` — `PublishResponseSchema` (Zod): `{ tree: string[], files:
   Record<string,string>, stats: {...} }`.
2. `ui/lib/api/publish.ts` — `getPublishPreview(project)`; `downloadBundle(project)`
   hits `mode=tar` and triggers browser download.
3. `ui/lib/queries/use-publish.ts` — TanStack Query hook keyed by project; `enabled`
   only when the tab is active (preview runs clustering — don't fetch until opened).
4. `ui/app/kb/page.tsx` — tabs `[ Curated | Export OKF ]` (sectioned like hygiene).

Layout: left file-tree from `tree[]` (clickable), right rendered markdown of the
selected `files[path]` (reuse existing markdown render; `<pre>` monospace fallback
if none). Scope picker reuses `project-store`. Footer shows `stats` (count +
`titled_by`).

**`mode=dir` is NOT in the UI** — the browser can't safely choose a server path, and
it is a security surface. UI does preview + download tarball only. Write-to-dir stays
tool/skill only, where caller intent is explicit. Deliberate scope cut for v1.

`/kb` is already in `sidebar-nav.tsx` — no new route. Tab state is local.

---

## 6. Error handling

Failures are loud. Read/preview/tar paths degrade gracefully and report degradation
in `stats`; only the write path hard-fails (a partial write masquerading as success
is the dangerous case).

| Failure | Where | Handling |
|---|---|---|
| Empty scope / unknown project | publish | Valid empty bundle, `_ok`. UI: "No memories for this scope." |
| Graph missing/corrupt | publish | Degrade: every memory a singleton concept; log warning; still builds. |
| Haiku unavailable / errors | title_fn | Slug fallback; `stats.titled_by="slug"`. Never fails export. |
| Haiku returns garbage | title_fn | Length/format guard → slug fallback for that cluster. |
| `dest` escapes allowlist | endpoint `dir` | `_bad_request`; no partial write. |
| `dest` write fails midway | endpoint `dir` | Temp dir + atomic move; else fail whole op, report unwritten. |
| tar stream error | endpoint `tar` | 500 `_server_error`, logged. |
| slug collision | renderer | Append short id hash; deterministic. |
| broken cross-link | renderer | Drop links to filtered-out concepts (don't emit dangling). |

---

## 7. Testing

**Unit — `tests/test_publish.py`** (keyless, no backend): inject a deterministic slug
`title_fn`; assert tree paths + concept count. Clustering (components correct,
`contradicts` doesn't merge, singletons own docs, oversized splits at cap). Cache
(same member-set → same title; changed membership → recomputed). Slug collision →
hash suffix.

**Renderer — `tests/test_renderer_okf.py`** (conformance): every non-reserved `.md`
has parseable frontmatter with non-empty `type`; `index.md`/`log.md` not concepts;
concept ID == path minus `.md`; cross-links bundle-relative; dropped (not dangling)
links to filtered concepts; frontmatter round-trips.

**Endpoint — `tests/test_server_publish.py`** (contract): `preview` shape; unknown/empty
project → empty bundle 200; `mode=dir` outside allowlist → 400; `mode=tar` → gzip magic
+ attachment header.

**UI — `ui/tests/publish-tab.test.tsx`** (vitest): renders tree from fixture; clicking
a node shows file content; empty bundle → empty state; download button wired.

**Fixtures:** small hand-built memory+graph set (~6 memories, one cluster, one
contradiction, one singleton) in `tests/conftest.py` / `ui/tests/fixtures/`. Covers
every branch without the real 794.

**Not tested** (YAGNI): real Haiku (injected/mocked), real Qdrant (publish reads
YAML+graph, not vectors), tarball byte-exactness (valid gzip + expected paths only).

---

## 8. Out of scope (v1)

- Write-to-dir from the UI.
- A second export format (the `renderers/` seam is ready; the interface is not built).
- Storing cluster titles at save-time (kept as export-time concern with cache).
- Round-trip *import* of an OKF bundle back into memory.
- Incremental/`log.md` update history across exports.
