# Codex installation

This is the authoritative guide for the first-class Codex adapter. It registers the Rekall HTTP MCP server and installs six bounded lifecycle hooks; it never replaces Codex's native memory.

## Prerequisites

Run from a checkout with Python 3.11+, `python3`, and the Codex CLI available. The default server is loopback-only:

```bash
bash codex/setup/install.sh
```

The installer validates the MCP definition before changing hooks. The equivalent manual registration is:

```bash
codex mcp add rekall --url http://localhost:8000
```

A missing server is added; a matching loopback HTTP server is accepted. A conflicting URL or stdio definition fails without mutating configuration. Remote URLs require the explicit `--allow-remote-mcp` flag and must not contain credentials.

MCP transport and REST hook endpoints can differ. With a root MCP URL, the installer safely derives the REST base. If the MCP transport has a path such as `/mcp`, provide the REST base explicitly:

```bash
bash codex/setup/install.sh \
  --mcp-url https://memory.example.test/mcp \
  --api-url https://memory.example.test \
  --allow-remote-mcp
```

The validated REST base is pinned into each hook as `REKALL_API_URL`; the hook then appends `/health` or `/api/...`. The installer rejects an MCP URL with a non-root path when `--api-url` is absent rather than guessing. For backward compatibility, an ambient `REKALL_API_URL` seeds the shared default only; an explicit `--mcp-url` replaces that default, and a split REST endpoint must use `--api-url`. Re-run the installer to change either endpoint.

## Backup and migration

Before replacing settings, the installer creates one timestamped backup containing every file it replaces, including existing hooks. It merges six canonical events while preserving foreign entries and is idempotent. It removes only known legacy Rekall commands; it does not touch `$CODEX_HOME/memories/` (normally `~/.codex/memories/`). Native Codex memory is separate, remains owned by Codex, and must never be edited by Rekall.

Paths with spaces are supported. The installer uses temporary sibling files and atomic replacement. It fails before mutation when dependencies or input validation fail. It verifies the MCP registration after adding it; any later failure restores replaced files, removes new files, and removes the MCP registration only when this run added it. Backups are retained for operator recovery.

## Kill switches

- `REKALL_AUTOSAVE=0` disables all adapter activity.
- `REKALL_REFLEX=0` disables pre-tool reflex context.
- Unset or remove individual hook entries to disable one lifecycle event.
- Stop the local MCP server to disable tool calls; hooks fail open and do not block Codex.

## Uninstall and rollback

To uninstall, remove the six Rekall entries from the Codex hooks configuration, remove the installed `rekall-memory` skill, and run `codex mcp remove rekall` if that MCP registration was created by this install. Do not remove native files under `~/.codex/memories/`.

For manual rollback, stop Codex, restore the timestamped backup files with `cp`/`mv`, then restart Codex. Keep the backup until the restored configuration has been verified. Restart Codex after installation or rollback so it reloads MCP and hook configuration.

## Verification

```bash
bash codex/setup/test.sh
codex mcp get rekall --json
```

Expected: `rekall` points to `http://localhost:8000`, hook commands pin `REKALL_API_URL=http://localhost:8000`, six lifecycle entries exist, foreign hooks remain, and native memory is unchanged.
