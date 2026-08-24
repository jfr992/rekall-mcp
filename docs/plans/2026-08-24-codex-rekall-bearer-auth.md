# Codex ↔ Rekall Bearer Authentication Repair Plan

## Problem narrative

Rekall's loopback server is correctly protected when `REKALL_API_TOKEN` is set, but the shipped Codex integration registers only the URL and its hook adapter sends unauthenticated REST requests. Once authentication is enabled, Codex MCP calls and protected hook calls receive HTTP 401 while `/health` still succeeds. The repair must keep the token out of Codex configuration, hooks JSON, logs, and process arguments; Codex will resolve the token from an environment variable and the hook will read that same variable only at request time.

## Architecture

```text
launch environment
  REKALL_API_TOKEN=<secret>
          │
          ├── Codex MCP transport
          │     config stores only bearer_token_env_var="REKALL_API_TOKEN"
          │     └── Authorization: Bearer <secret> ──► Rekall /mcp
          │
          └── rekall_hook.py
                request_json() builds an in-memory header
                └── Authorization: Bearer <secret> ──► Rekall /api/*

Codex config / hooks.json / logs: variable name or URL only; never secret bytes.
```

## Typed interfaces

```python
def api_headers(env: Mapping[str, str] | None = None) -> dict[str, str]: ...

def request_json(
    method: str,
    url: str,
    body: Mapping[str, object] | None,
    timeout: float = 1.0,
) -> object | None: ...
```

```text
install.sh [--bearer-token-env-var ENV_NAME]

ENV_NAME := [A-Za-z_][A-Za-z0-9_]*
```

The installer persists only `ENV_NAME` through Codex's official `--bearer-token-env-var` option. Existing matching configuration must include the requested variable name; an incompatible existing registration fails before mutation rather than silently weakening authentication.

## TDD blocks

1. **Hook authorization header — RED**
   - With `REKALL_API_TOKEN=fake-token`, capture the actual `urllib.request.Request` and assert `Authorization: Bearer fake-token`.
   - Without a token, assert the header is absent.
   - With whitespace/control characters, assert the token is rejected and never reaches a header.

2. **Installer bearer registration — RED**
   - Install with `--bearer-token-env-var REKALL_API_TOKEN` and assert the fake Codex CLI receives that exact option.
   - Assert verification requires the same `bearer_token_env_var`.
   - Assert malformed environment-variable names fail before filesystem or MCP mutation.
   - Assert no test token value appears in generated config, hooks, stdout, or stderr.

3. **Implementation — GREEN**
   - Centralize hook header construction in one pure helper.
   - Validate the variable name once at the installer boundary.
   - Extend MCP registration and match verification without changing unauthenticated default behavior.

4. **Regression verification**
   - Run focused Codex hook/installer tests.
   - Run the disposable Codex integration smoke.
   - Run the repository pre-commit hooks and required test suite if focused checks pass.

## Concrete expected output

```text
$ codex mcp get rekall --json
... "url":"http://localhost:8000", "bearer_token_env_var":"REKALL_API_TOKEN" ...

GET /api/memory/stats without bearer  -> 401
GET /api/memory/stats with bearer     -> 200
Codex config and hooks.json contain   -> no token bytes
```

The already-running Codex process cannot acquire a new environment variable in place. After installing and configuring the local launch environment, Codex must be restarted before its MCP client can authenticate.
