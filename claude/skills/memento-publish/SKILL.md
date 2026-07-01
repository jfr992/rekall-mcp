---
name: memento-publish
description: Use when the user wants to export or publish memory to an OKF (Open Knowledge Format) bundle — shareable markdown knowledge docs.
---

# Publish memory to an OKF bundle

When the user asks to export, publish, or share their memory as a knowledge bundle:

1. Call the `publish_memory` MCP tool (project-scoped if the user named a project, else all memory).
2. Show the returned file tree.
3. Tell the user how to get the files:
   - Downloadable `.tar.gz`: cockpit Knowledge → Export OKF tab, or `GET /api/memory/publish?mode=tar`.
   - Write to disk: `GET /api/memory/publish?mode=dir&dest=<name>` — writes under `MEMENTO_PUBLISH_DIR` (default `~/.claude/publish`).

Namespace note: the tool is `mcp__<server>__publish_memory` where `<server>` is the
MCP server name in the user's Claude Code config (`memento` if installed per the repo
config; `memory` if added via the README's `claude mcp add ... memory`).
