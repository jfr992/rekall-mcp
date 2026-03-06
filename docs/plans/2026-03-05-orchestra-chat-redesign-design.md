# Orchestra Chat Redesign - Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create the implementation plan from this design.

**Goal:** Transform the Agent Orchestra dashboard panel from a simple dispatch form into a master chat interface where the user talks to Claude (orchestrator), which decomposes goals and dispatches to role-specific AI agents (Codex Spark for implementation, Gemini for research, Claude for architecture/review). All agents share memory via memento MCP.

**Architecture:** Chat-centric center panel replaces the brain graph. Claude API serves as the orchestrator backend, interpreting user messages and dispatching to sub-agents via CLI. Each agent gets a role-specific context template (minimal for Codex, research-focused for Gemini, full for Claude). Memento MCP is the shared knowledge layer across all agents.

**Tech Stack:** Python/FastAPI (server), vanilla JS (dashboard), Claude API (orchestrator), CLI subprocesses (agent execution), memento MCP (shared memory)

---

## 1. Layout Redesign

### Current Layout
```
[ Tracker (320px) | Brain Graph (1fr) | Briefing + Memory + Orchestra (340px) ]
```

### New Layout
```
[ Tracker (320px) | Orchestra Chat (1fr) | Briefing + Memory + Config (340px) ]
```

### Topbar Changes
- Add **workspace selector** dropdown next to logo: `MEMENTO // Command | [~/Repos/holodeck v]`
- Add **[BRAIN]** toggle button — opens brain graph as a modal overlay on center column
- Active workspace persisted in `~/.memento/dashboard.json` and localStorage

### Center Column: Orchestra Chat
- Full-height chat interface with message history scrolling up
- Input bar fixed at bottom with send button
- Messages from user, orchestrator (Claude), and agent run results
- Agent runs appear inline as expandable status cards
- Approve/reject actions inline on review-ready runs

### Right Column Changes
- Briefing section stays
- Memory detail stays
- New **Config section** at bottom:
  - Shows active MCPs per agent
  - Shows plugin count
  - "Edit Config" button opens config editor

---

## 2. Agent Roles

| Agent | Role | Trigger | Context Injected | Context NOT Injected |
|-------|------|---------|------------------|---------------------|
| **Claude** | Architect + Reviewer | Decomposition, review, complex reasoning | Full superpowers, CLAUDE.md, skills, all memory | N/A (gets everything) |
| **Codex Spark** | Programmer | "Implement", "build", "code", TDD steps | Plan output (write-plan format), relevant files, memento MCP, TDD instructions | Skills, hooks, heavy context |
| **Gemini** | Deep Research | "Research", "explore", "investigate", "docs" | Research question, memory context, memento MCP, broad scope | Implementation details, plans |

### Role-Specific Prompt Templates

**Codex Spark preamble:**
```
You are implementing a specific task from a detailed plan.
Working directory: {workspace}
MCP servers: memento (for reading/writing project memory)

## Task
{task_description}

## Plan Context
{plan_steps}

## Rules
- Follow TDD: write failing test, implement, verify, commit
- One step at a time
- Commit after each passing test
- Store implementation decisions in memento memory
- Do NOT deviate from the plan
```

**Gemini preamble:**
```
You are researching a topic to inform an implementation decision.
Working directory: {workspace}
MCP servers: memento (for storing research findings)

## Research Question
{task_description}

## Context
{memory_context}

## Rules
- Be thorough and cite sources
- Store key findings as memento memories (type: "fact" or "learning")
- Summarize with actionable recommendations
- Note any risks or trade-offs discovered
```

**Claude (orchestrator) system prompt:**
```
You are the orchestrator of a multi-agent development team.

Available agents:
- codex: Fast programmer. Give detailed, step-by-step implementation instructions.
- gemini: Deep researcher. Use for docs, patterns, exploration.
- claude: You. Handle architecture, decomposition, review.

Active workspace: {workspace}

When the user describes a goal:
1. Decompose into subtasks
2. Assign each to the best agent
3. For codex tasks, write detailed plans (TDD, file paths, exact specs)
4. For gemini tasks, frame clear research questions
5. Review all outputs before presenting to user

Available memories: {recent_memories}

Respond conversationally. Show your dispatch plan before executing.
```

---

## 3. Shared MCP Layer

All agents get memento MCP configured so they share the same knowledge base.

### Agent MCP Configs (`~/.memento/agent-configs/`)

**`codex.json`:**
```json
{
  "mcpServers": {
    "memento": {
      "url": "http://localhost:8001/mcp",
      "transport": "streamable-http"
    }
  }
}
```

**`gemini.json`:**
```json
{
  "mcpServers": {
    "memento": {
      "url": "http://localhost:8001/mcp",
      "transport": "streamable-http"
    }
  }
}
```

**`claude.json`:** Uses existing `~/.claude/settings.json` (already has memento + all plugins).

### Memory Flow
```
User goal → Claude decomposes
  ├─ Codex implements → stores decisions/patterns in memento
  ├─ Gemini researches → stores findings in memento
  └─ Claude reviews → reads all memories, synthesizes
```

---

## 4. API Endpoints

### New Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/workspaces` | Scan configured roots for git repos |
| GET | `/api/config` | Return current MCP/plugin/agent configs |
| PUT | `/api/config` | Update configs from dashboard |
| POST | `/api/orchestra/chat` | Send message to orchestrator, get response + dispatches |
| GET | `/api/orchestra/chat/history` | Retrieve chat message history |
| GET | `/api/orchestra/runs/{run_id}/output` | Stream/poll run output |

### Modified Endpoints
- `POST /api/orchestra/dispatch` — now called internally by the chat orchestrator, not directly by the UI
- `GET /api/orchestra/status` — still used for polling run status updates

### Workspace Scanner Config
```json
// ~/.memento/dashboard.json
{
  "workspace_roots": [
    "~/Repos",
    "~/scripts",
    "~/.config/superpowers/worktrees"
  ],
  "active_workspace": "~/Repos/holodeck",
  "chat_history_limit": 100
}
```

---

## 5. Chat UI Components

### Message Types
1. **User message** — right-aligned, cyan border
2. **Orchestrator message** — left-aligned, shows Claude's decomposition/review
3. **Agent run card** — inline expandable card showing:
   - Agent icon + name + run ID
   - Status badge (pending/running/review/completed/failed)
   - Progress indicator
   - Expandable output section
   - Approve/reject buttons (when status = review)
4. **System message** — centered, dim, for status updates ("Workspace changed to...")

### Input Bar
- Text input (auto-expanding textarea)
- Send button (or Enter to send, Shift+Enter for newline)
- No agent/working_dir selectors — workspace is in topbar, agent selection is automatic via orchestrator

### Chat Persistence
- Chat history stored in localStorage for session persistence
- Optionally synced to `~/.memento/chat-history/` for cross-session persistence
- Limited to configurable message count (default: 100)

---

## 6. Brain Graph Improvements

### Current Problems
- Random scatter, no organization
- Always visible, takes prime real estate

### New Behavior
- **Toggle via [BRAIN] button** in topbar
- Opens as a **modal overlay** on the center column (semi-transparent backdrop)
- Close with Escape or clicking backdrop

### Layout Improvements
- **Cluster by project** — nodes in the same project group spatially together
- **Color by type** — same as current (requirement=red, fact=blue, etc.)
- **Force-directed with group gravity** — nodes attract to their project centroid
- **Project labels** — each cluster gets a dim label
- **Reduce jitter** — higher damping factor, nodes settle faster

---

## 7. Config Panel (Right Sidebar)

### Display
```
--- CONFIG ---
MCPs
  memento ........... [active]
  context7 .......... [active]

Agent Configs
  claude  [12 plugins] [Edit]
  codex   [1 MCP]      [Edit]
  gemini  [1 MCP]      [Edit]

[Edit Global Config]
```

### Edit Flow
- "Edit" opens a code editor modal (textarea with JSON syntax)
- Changes POST to `/api/config` and write to `~/.memento/agent-configs/`
- Global config edits write to relevant files (`~/.claude/settings.json`, etc.)

---

## 8. Orchestrator Backend

### Chat Handler (`POST /api/orchestra/chat`)

```python
async def handle_chat(request):
    body = await request.json()
    message = body["message"]
    workspace = body["workspace"]
    history = body.get("history", [])

    # 1. Build orchestrator prompt with system context
    system = build_orchestrator_prompt(workspace)

    # 2. Call Claude API with conversation history
    response = await call_claude_api(system, history + [{"role": "user", "content": message}])

    # 3. Parse response for dispatch intents
    dispatches = parse_dispatch_intents(response)

    # 4. Execute dispatches
    run_ids = []
    for d in dispatches:
        result = await orchestra.dispatch_task(
            task=d["task"],
            agent=d["agent"],
            working_dir=workspace,
            context=d.get("context", ""),
        )
        run_ids.append(result)

    # 5. Return orchestrator message + dispatch results
    return {"message": response.text, "dispatches": run_ids}
```

### Claude API Integration
- Uses `anthropic` Python SDK
- Requires `ANTHROPIC_API_KEY` env var (already available in user's env)
- Model: `claude-sonnet-4-20250514` for orchestrator (fast, good enough for decomposition)
- Conversation history maintained client-side, sent with each request

---

## 9. Execution Flow

### Full Cycle
```
1. User types: "Build JWT auth middleware for the holodeck project"

2. Orchestrator (Claude API) responds:
   "I'll break this down:
    1. Research: JWT + Redis patterns in Go → Gemini
    2. Plan: Write implementation plan with TDD steps → Me
    3. Implement: Execute plan → Codex Spark

    Starting with research..."

3. Dispatches:
   [RUN-001] gemini → "Research JWT+Redis auth middleware patterns in Go.
                        Focus on: token rotation, Redis session store,
                        middleware chain integration. Store findings in memento."

4. Gemini completes → memories stored → status: REVIEW
   Orchestrator auto-reviews research, synthesizes into plan

5. Orchestrator writes plan (write-plan format):
   "Based on Gemini's research, here's the implementation plan:
    Step 1: Write failing test for JWT validation middleware
    Step 2: Implement minimal JWT parser
    ..."

6. Dispatches implementation:
   [RUN-002] codex → Step 1 with full plan context
   [RUN-003] codex → Step 2 (after RUN-002 completes)

7. Each Codex completion → orchestrator reviews → approve/reject
   Results and decisions stored in memento throughout
```

---

## 10. Non-Goals (YAGNI)

- No real-time streaming (SSE/WebSocket) in v1 — polling is fine
- No multi-user support
- No agent-to-agent direct communication (all goes through orchestrator)
- No custom agent registration (claude/codex/gemini are hardcoded for now)
- No voice input
- No file upload in chat
