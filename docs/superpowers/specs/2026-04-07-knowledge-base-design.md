# Knowledge Base UI — Design Spec

**Date**: 2026-04-07
**Status**: Approved
**Route**: `/kb`

## Overview

A browsable, searchable knowledge base UI for Memento MCP memories. Serves three use cases in priority order: personal review (finding past decisions, recalling learnings), knowledge sharing (onboarding new sessions/people to a project), and memory hygiene (resolving duplicates, contradictions, stale entries).

## Architecture

**Approach**: Hybrid — reuse existing REST endpoints, add one new structured endpoint for topic detail, add `?format=json` to the hierarchy endpoint.

**Pattern**: Single embedded HTML page (same as `/dashboard`), client-side SPA with hash-based routing, fetching data from existing + new API endpoints. No new dependencies.

## Navigation & Views

### Modes

| Mode | Purpose |
|------|---------|
| **KB** | Browse topics, search memories, view details |
| **Fix** | Review superseded pairs and conflicts, take hygiene actions |

### Views (KB Mode)

| View | URL Hash | Description |
|------|----------|-------------|
| Home | `#` or `#home` | Topic cards grid + stats bar + skills row |
| Topic detail | `#topic=<label>` | List + Detail split for one topic's memories |
| Search results | `#search=<query>` | Split view with search results on left |

### Navigation Flow

```
/kb#home
  → Click topic card → /kb#topic=Architecture
    → Click memory in list → detail pane updates (right side)
    → Click connected memory link → navigates to that memory's topic + selects it
  → Type in search bar → /kb#search=postgresql
    → Click result → detail pane shows full content + connections
  → Toggle Fix mode → /kb#fix
    → Review pairs → Confirm/Dismiss actions
  → "Brain →" link → /dashboard (separate page)
```

## UI Components

### Top Bar (persistent across all views)

- **Brand**: "MEMENTO KB" with gradient text (matches dashboard)
- **Search input**: Debounced (300ms), POST to `/api/memory/recall`
- **Project filter pills**: "All projects" (default active), plus one pill per project. Project list derived from unique `project` values in the hierarchy JSON response (no separate endpoint needed)
- **Type filter pills**: Filter topic cards / search results by memory type
- **Mode toggle**: KB | Fix segmented control
- **Brain link**: "Brain →" links to `/dashboard`

### Stats Bar (home view)

Single row: total memories, count per type (colored), connection count, skill count. Data from `GET /api/memory/stats`.

### Skills Row (home view)

Horizontal pill badges: extracted skills from `GET /api/memory/context/skills`. Clicking a skill triggers a search for that term.

### Topic Cards Grid (home view)

- CSS grid, 3 columns (responsive: 2 on tablet, 1 on mobile)
- Each card: topic label, memory count, content preview (first ~80 chars of top memories), type breakdown badges
- Hover: border highlight
- Click: navigate to `#topic=<label>`
- Data from `GET /api/memory/context/hierarchy?format=json`

### Topic Detail — Split View

**Left panel** (280px fixed width):
- Compact memory list sorted by date (newest first)
- Each row: content preview (1-2 lines), type badge, date, connection count
- Selected memory highlighted with accent border
- Click to update detail pane

**Right panel** (flex):
- Type badge + date + project tag
- Full memory content
- "Connections" section: list of 1-hop graph neighbors, each showing relation type badge, content preview, target type, target topic. Clickable — navigates to that memory.
- Memory ID in monospace at bottom

**Breadcrumb**: `Topics / <label>` — click "Topics" to return to home grid.

Data from `GET /api/kb/topic/<label>` (new endpoint).

### Fix Mode

**Superseded Pairs section**:
- Side-by-side memory cards showing the newer (keeper) and older (candidate for deletion)
- Similarity score badge
- Actions: "Confirm & Delete Old" (calls DELETE), "Dismiss" (hides pair)

**Conflicts section**:
- Side-by-side memory cards showing contradicting memories
- Actions: "Keep A" / "Keep B" (deletes the other), "Dismiss"

**Empty state**: "All clean" message with checkmark when no issues found.

Data from `GET /api/memory/consolidate`.

### Search Results View

Same split layout as topic detail. Left panel shows ranked search results (with similarity score). Right panel shows selected memory detail + connections. Breadcrumb: `Search / "<query>"`.

## API Changes

### New Endpoint: `GET /api/kb/topic/<label>`

Returns structured JSON for a single topic cluster with graph connections inlined.

**Response shape**:
```json
{
  "topic": "Architecture",
  "memory_count": 5,
  "memories": [
    {
      "memory_id": "2026-02-01_decision_a1b2c3d4",
      "content": "Chose PostgreSQL over MySQL...",
      "type": "decision",
      "date": "2026-02-01",
      "project": "memento-mcp",
      "connections": [
        {
          "memory_id": "2026-02-01_learning_e5f6g7h8",
          "content": "JWT tokens stored in JSONB...",
          "relation": "led_to",
          "weight": 0.87,
          "type": "learning",
          "topic": "Authentication"
        }
      ]
    }
  ]
}
```

**Implementation**: Fetch topic cluster from hierarchy logic (reuse `TopicCluster`), for each memory query knowledge graph for 1-hop edges via `KnowledgeGraph.get_neighbors()`, attach connections inline. Lookup target memory content from Qdrant/YAML for the connection previews.

### Modified Endpoint: `GET /api/memory/context/hierarchy`

Add `?format=json` query parameter. When set, return structured JSON instead of markdown:

```json
{
  "project": "all",
  "topics": [
    {
      "label": "Architecture",
      "memory_count": 5,
      "memories": [
        {
          "memory_id": "2026-02-01_decision_a1b2c3d4",
          "content": "Chose PostgreSQL over MySQL...",
          "type": "decision",
          "date": "2026-02-01",
          "project": "memento-mcp"
        }
      ]
    }
  ],
  "params": {
    "limit": 200,
    "max_topics": 12,
    "similarity_threshold": 0.72
  }
}
```

**Implementation**: The clustering logic in `topics.py` already produces `TopicCluster` objects with structured data. The markdown rendering is a separate step. Add a branch that serializes `TopicCluster` objects directly to JSON when `format=json`.

### Modified Endpoint: `GET /api/memory/consolidate`

Add `?format=json` query parameter. When set, return structured pairs instead of markdown:

```json
{
  "superseded": [
    {
      "newer": {"memory_id": "...", "content": "...", "type": "...", "date": "..."},
      "older": {"memory_id": "...", "content": "...", "type": "...", "date": "..."},
      "score": 0.923
    }
  ],
  "conflicts": [
    {
      "a": {"memory_id": "...", "content": "...", "type": "...", "date": "..."},
      "b": {"memory_id": "...", "content": "...", "type": "...", "date": "..."},
      "score": 0.781
    }
  ]
}
```

**Implementation**: The consolidation logic in `manager.py` already identifies pairs programmatically before rendering to markdown. Add a branch that returns the raw pair data as JSON.

### Existing Endpoints Used (unchanged)

| Endpoint | Used For |
|----------|----------|
| `GET /api/memory/stats` | Stats bar |
| `GET /api/memory/context/skills` | Skills row |
| `POST /api/memory/recall` | Search |
| `DELETE /api/memory/:id` | Hygiene delete actions |

## Visual Design

Same dark neural theme as `/dashboard`:
- Background: `#050510`
- Surface: `rgba(15, 20, 50, 0.6)` with `rgba(100, 120, 255, 0.1)` borders
- Glass panels: `backdrop-filter: blur(20px)` on `rgba(10, 14, 36, 0.85)`
- Brand: gradient `#818cf8 → #38bdf8`
- Type colors: fact `#38bdf8`, decision `#fbbf24`, learning `#34d399`, preference `#f472b6`, requirement `#22d3ee`, session `#a78bfa`, note `#94a3b8`
- Relation badges: same color as source type with 20% opacity background
- Typography: Inter / system sans-serif, monospace for memory IDs
- No emojis — colored dots and badges only

## Responsive Behavior

| Breakpoint | Layout |
|------------|--------|
| > 1024px | 3-column topic grid, split view with 280px list |
| 768-1024px | 2-column topic grid, split view with narrower list |
| < 768px | 1-column grid, split view stacks vertically (list above detail) |

## Scope Boundaries

**In scope (v1)**:
- Topic cards home view with stats, skills, filters
- Topic detail split view with connections
- Search with debounced recall
- Fix mode with consolidation review + delete actions
- Hash-based client-side routing
- Link to brain dashboard

**Out of scope (future)**:
- Full memory CRUD (create, edit content)
- LLM-generated topic summaries
- Memory version history
- Export/import
- Brain visualization embedded in KB
- Authentication / multi-user access control
