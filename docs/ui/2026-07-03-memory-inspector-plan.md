# Memory Inspector UI Implementation Plan

> **For agentic workers:** Execute task-by-task on a feature branch. Use tests as gates. Do not implement a visual-only drawer refresh without the detail contract changes in Task 1.

**Goal:** Replace the current memory popup with a developer-grade Memory Inspector that answers whether an agent memory is relevant, trustworthy, current, and connected to the current software task.

**Audience:** A developer using an AI companion for software work. The drawer should feel like inspecting the agent's working memory: concise enough for browsing, explicit enough for trust/debugging.

**Architecture:** Enrich `/api/memory/detail/{memory_id}` with a v2-compatible contract while preserving existing `memory` and `neighbors` fields for one release. Replace the shared `NodeDrawer` surface with a structured inspector reused by Brain and Continuity. Fix the responsive shell enough that the inspector is usable on narrow screens.

**Design Direction:** Dense dark cockpit, forensic rather than decorative. Use one signature structure: an evidence rail that separates Source, Lifecycle, Storage, and Graph evidence from the readable memory content. Keep motion subtle and functional.

## Evidence From Audit

Adversary agents and Playwright found the same core issues:

- The drawer repeats memory content as a giant title and body.
- Missing `durability` is rendered as `0.00`, making legacy/unknown values look like known low value.
- Only outgoing graph edges are shown, so incoming `supersedes`, `depends_on`, and `contradicts` are invisible.
- Provenance exists in payloads but is not surfaced: agent, source tool, cwd, repo, branch, trust boundary, session.
- Neighbor cards are static, ungrouped, and not direction-aware.
- The drawer is visually modal but not accessibly modal: no accessible name, focus trap, initial focus, background inerting, or focus restoration.
- Brain graph selection is pointer-only because the canvas has no keyboard-accessible memory list.
- Mobile layout is broken: the fixed sidebar leaves about 155px for Continuity content at a 390px viewport.
- Graph tooltips interpolate raw memory content into HTML strings and need escaping.

Playwright observations captured during planning:

- Desktop Continuity with an open drawer showed duplicated content, unexplained lifecycle metrics, and neighbor evidence below the fold.
- Mobile Continuity at `390x844` showed the fixed sidebar consuming most of the viewport, leaving about 155px for content.

## Current Confusing Metrics

The current block:

```text
DATE         DURABILITY
2026-02-03   0.00

REINFORCED   SALIENCE
0x           -
```

means:

- `date`: stored memory date.
- `durability`: lifecycle retention score from tier, salience, contradictions, and reinforcement.
- `reinforced`: dedupe/repetition count.
- `salience`: observe/judge confidence that the memory was worth saving.

The UI must not show missing durability as `0.00`. Unknown salience is not low salience; it is legacy/manual/unknown and is protected from pruning.

## Global Constraints

- Keep `/api/memory/detail/{memory_id}` backward compatible for existing UI consumers during this PR.
- Do not expose credential-bearing remotes or secrets. Use existing credential stripping from `ScopeDetector`.
- Do not introduce a new UI library. Use existing Next.js, React, TanStack Query, Tailwind, Framer Motion, Lucide, Vitest, and Playwright patterns.
- Keep the cockpit dense and operational. No marketing hero sections, decorative cards, or explanatory feature copy.
- Use semantic labels: source, lifecycle, storage, graph evidence. Avoid internal-only labels unless paired with explanation.
- Touch targets in the inspector must be at least 44px high.
- Long paths, hashes, URLs, and code-shaped text must wrap without horizontal overflow.
- Preserve reduced-motion behavior.

## Task 1: Detail Contract V2

**Files:**
- Modify: `src/server.py`
- Modify: `src/memory/manager.py`
- Test: `tests/test_server_memory_os_endpoints.py`
- Test: `tests/test_memory_detail.py` if a new focused file reads cleaner

**Interfaces:**
- Produces: `MemoryManager.get_memory_detail(memory_id: str, current_project: str | None = None) -> dict`
- Produces: REST payload with existing `memory`, `neighbors`, `scope` plus new `relationships`, `provenance`, `lifecycle`, `storage`, `warnings`

**Steps:**

- [ ] Add a failing backend test for a memory with incoming and outgoing edges.
  - Setup a selected memory with:
    - incoming `supersedes`
    - outgoing `depends_on`
    - incoming `contradicts`
  - Assert the response includes both directions under `relationships`.
  - Assert `neighbors` still exists as a compatibility alias.

- [ ] Add a failing backend test for provenance and lifecycle.
  - Use a payload with `agent`, `source_tool`, `source_event`, `timestamp`, `session_id`, `repo_name`, `repo_remote`, `branch`, `trust_boundary`, `retention_days`, `lifecycle_reason`.
  - Assert `provenance` and `lifecycle` expose these fields with `null` for missing values.

- [ ] Implement `MemoryManager.get_memory_detail`.
  - Fetch from Qdrant first with `store.get_by_id`.
  - Record `storage.qdrant = true/false`.
  - Add YAML fallback only if Qdrant is missing. Keep fallback read-only.
  - Record `storage.yaml = true/false`.
  - Fetch graph edges with `knowledge_graph.get_edges(memory_id, direction="both")`.
  - For each edge, compute:
    - `source_id`
    - `target_id`
    - `neighbor_id`
    - `direction`
    - `relation`
    - `weight`
    - `auto`
    - `created`
    - `memory`
  - Include `missing_neighbor_ids` when graph edges point to unavailable memories.

- [ ] Update `/api/memory/detail/{memory_id}` to call `manager.get_memory_detail`.
  - Accept optional `?current_project=` for scope warnings.
  - Keep the missing-memory contract: `memory: null`, `neighbors: []`, `scope: null`.

- [ ] Add `warnings`.
  - `scope_mismatch` when selected memory project differs from `current_project`.
  - `missing_provenance` when source/tool/agent fields are absent.
  - `missing_index` when YAML fallback exists but Qdrant does not.
  - `missing_lifecycle` when durability/lifecycle fields are absent.

## Task 2: Graph Payload Truth

**Files:**
- Modify: `src/memory/graph.py`
- Test: `tests/test_memory_graph.py` or existing graph builder test
- Modify: `ui/lib/schemas.ts`

**Interfaces:**
- Graph node must include `tier`, `durability`, `salience`, `trust_boundary`, and `timestamp` when present.

**Steps:**

- [ ] Add a failing graph builder test proving graph node payload preserves tier/durability/salience/trust/timestamp from Qdrant point payloads.
- [ ] Update `build_memory_graph` node serialization.
- [ ] Update `GraphNodeSchema` to make these fields explicit.
- [ ] Ensure Brain canvas radius/color logic no longer depends on fields that are missing in live backend responses.

## Task 3: Detail Schema And API Client

**Files:**
- Modify: `ui/lib/schemas.ts`
- Modify: `ui/lib/api/detail.ts`
- Modify: `ui/lib/queries/use-memory-detail.ts`
- Test: `ui/tests/schemas.test.ts`
- Fixture: `ui/tests/fixtures/detail-v2.json`

**Interfaces:**
- Produces: explicit `DetailResponseV2Schema`
- Consumes: `getMemoryDetail(memoryId, currentProject?)`
- Consumes: `useMemoryDetail(memoryId, currentProject?)`

**Steps:**

- [ ] Add a v2 detail fixture with provenance, lifecycle, relationships, storage, warnings, and legacy `neighbors`.
- [ ] Add schema tests for v1 fixture and v2 fixture.
- [ ] Update detail client to pass `current_project` when supplied.
- [ ] Update query key to include current project, preventing stale all-project detail when scope changes.

## Task 4: Accessible Drawer Foundation

**Files:**
- Modify: `ui/components/ui/drawer.tsx`
- Test: `ui/tests/drawer.test.tsx`

**Interfaces:**
- `Drawer` accepts `ariaLabel`, `ariaLabelledBy`, `initialFocusRef`, and optional `size`.

**Steps:**

- [ ] Add failing tests:
  - `getByRole("dialog", { name: /memory details/i })`
  - focus moves into drawer on open
  - Escape closes
  - focus returns to triggering element on close
  - Tab stays inside drawer
- [ ] Implement focus trap and focus restore without adding a new dependency.
- [ ] Lock background scroll while drawer is open.
- [ ] Increase close button hit area to at least 44px.
- [ ] Use `100dvh` and safe-area padding for mobile.

## Task 5: Memory Inspector Component

**Files:**
- Create: `ui/components/memory-inspector/memory-inspector.tsx`
- Create: `ui/components/memory-inspector/evidence-rail.tsx`
- Create: `ui/components/memory-inspector/relationship-list.tsx`
- Create: `ui/components/memory-inspector/memory-content.tsx`
- Modify: `ui/components/brain/node-drawer.tsx` or replace it with a compatibility wrapper
- Test: `ui/tests/memory-inspector.test.tsx`

**Interfaces:**
- `MemoryInspector({ open, detail, isLoading, currentProject, onClose, onSelectMemory })`
- `onSelectMemory(memoryId)` lets neighbor cards traverse the graph.

**Steps:**

- [ ] Add failing tests for:
  - no duplicated memory content
  - unknown durability renders `unknown`, not `0.00`
  - actual `durability: 0` renders `0.00`
  - missing salience renders `legacy/unknown`, not low value
  - provenance fields render
  - incoming/outgoing relations render with direction-aware labels
  - neighbor rows are buttons and call `onSelectMemory`
  - contradiction warning checks both incoming and outgoing relationships
- [ ] Implement header:
  - title: `Memory details`
  - badges: type, tier, project, status
  - actions: copy ID, copy content, close
- [ ] Implement content:
  - render memory text once
  - preserve line breaks
  - wrap paths/hashes/URLs
  - collapse very long content with explicit “Show full”
- [ ] Implement evidence rail:
  - Source: agent, tool/event, repo, branch, trust
  - Lifecycle: tier, durability, salience, reinforcement, reason, retention
  - Storage: YAML/Qdrant/graph state
  - Warnings: missing provenance, scope mismatch, missing lifecycle, missing index
- [ ] Implement relationship list:
  - group contradictions first, then supersedes, depends_on, led_to, related_to
  - show direction labels
  - show neighbor type/tier/date/project
  - clamp neighbor content with expand affordance

## Task 6: Integrate Brain And Continuity

**Files:**
- Modify: `ui/app/brain/page.tsx`
- Modify: `ui/app/continuity/page.tsx`
- Modify: `ui/components/continuity/memory-row.tsx`
- Test: `ui/tests/node-drawer.test.tsx` or migrate to `memory-inspector.test.tsx`
- Test: `ui/tests/continuity.test.tsx`

**Steps:**

- [ ] Pass active project into `useMemoryDetail`.
- [ ] Replace `NodeDrawer` usage with `MemoryInspector`.
- [ ] Add `aria-haspopup="dialog"` and focus-visible states to `MemoryRow`.
- [ ] Add a keyboard-accessible Brain fallback list or side list for opening selected graph memories without canvas pointer interaction.
- [ ] Fix the Continuity heading so `all memories` and project-specific scopes render correctly instead of `Continuity ·`.

## Task 7: Responsive Cockpit Shell

**Files:**
- Modify: `ui/components/shell/cockpit-shell.tsx`
- Modify: `ui/components/shell/sidebar-nav.tsx`
- Modify: `ui/app/globals.css`
- Test: Playwright

**Steps:**

- [ ] Add a Playwright test or scripted check at `390x844` proving no horizontal overflow.
- [ ] Convert the fixed sidebar to a responsive shell:
  - desktop: persistent sidebar
  - mobile: compact top/bottom nav or collapsible nav
- [ ] Ensure main content gets full viewport width on mobile.
- [ ] Ensure inspector opens as a full-screen sheet on mobile with sticky header.

## Task 8: Tooltip Safety

**Files:**
- Modify: `ui/components/brain/brain-canvas.tsx`
- Test: `ui/tests/brain-canvas.test.tsx` or focused utility test

**Steps:**

- [ ] Add a regression test for memory content containing `<script>` or inline HTML.
- [ ] Escape tooltip HTML before interpolation, or render tooltip via a safe React surface instead of an HTML string if the graph library allows it.

## Task 9: Visual Verification

**Files:**
- Add or update Playwright tests under the existing UI test setup
- Store screenshots only as test output, not committed artifacts

**Checks:**

- [ ] Desktop Continuity: open a long requirement memory; inspector is readable.
- [ ] Desktop Brain: open a graph memory; inspector does not obscure the whole graph without context.
- [ ] Mobile Continuity at `390x844`: no horizontal overflow; inspector usable full-screen.
- [ ] Drawer close button is at least 44x44.
- [ ] Background does not scroll while inspector is open.
- [ ] Reduced motion does not depend on animation timing.

## Task 10: Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/CLAUDE_MEMORY_SETTINGS.md` if memory detail semantics need agent-facing guidance

**Steps:**

- [ ] Document the detail contract at a high level.
- [ ] Document lifecycle metric wording:
  - durability = retention strength
  - salience = save confidence
  - missing salience = unknown/protected, not low
  - reinforcement = repeated/merged observations
- [ ] Document relationship direction semantics.

## Recommended Execution Order

1. Task 1: detail contract v2.
2. Task 3: schema/client.
3. Task 5: inspector component with tests.
4. Task 6: integration.
5. Task 4 and Task 7: accessibility/mobile foundations. These can happen before Task 5 if a separate worker owns only shell/drawer foundation.
6. Task 2 and Task 8: graph truth and tooltip safety.
7. Task 9 and Task 10: verification/docs.

## Definition Of Done

- A developer can open any memory and answer:
  - What is it?
  - Where did it come from?
  - Does it apply to this project/repo?
  - Is it current, superseded, contradicted, or legacy?
  - Why did the agent keep it?
  - What other memories are evidence for/against it?
- Unknown metrics are visibly unknown, never silently converted to zero.
- Relationship direction is explicit.
- Neighbor memories are traversable.
- The inspector is keyboard-accessible.
- Mobile cockpit is usable at 390px width.
- Backend, UI, and schema tests cover the contract.
