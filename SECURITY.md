# Security

## Trust model

Rekall's REST and MCP API is **unauthenticated by design**. The trust model is
localhost: anyone who can reach the port can read, write, and delete memories.

- **Bare metal:** the server binds `127.0.0.1` by default. Nothing off-machine
  can reach it.
- **Docker:** the container binds `0.0.0.0` internally (`HOST=0.0.0.0` in
  `docker-compose.yaml` — required for port-mapping), but compose maps all
  host ports to localhost only (`127.0.0.1:8000:8000`, `127.0.0.1:6333:6333`,
  `127.0.0.1:3333:3333`).

## Exposing the server on a network

Setting `HOST=0.0.0.0` (or removing the `127.0.0.1:` prefix from the compose
port mappings) exposes an unauthenticated read/write memory API to your
network. Only do this behind a firewall or a reverse proxy that adds
authentication. `REKALL_API_TOKEN` enables bearer auth on every route except
`/health` — see the README's "Securing a non-localhost deployment" section.

Note that Qdrant (`:6333`) is also unauthenticated; exposing it has the same
consequences as exposing the API itself.

## Browser-originated requests

Localhost is not a browser auth boundary: any web page can POST to
`127.0.0.1` (CSRF), and DNS rebinding defeats same-origin assumptions. The
server rejects state-changing requests (POST/PUT/DELETE/PATCH) carrying
browser markers (`Origin` or `Sec-Fetch-Site`) unless they come from an
allowlisted exact origin (`http://localhost:3333`, `http://127.0.0.1:3333`,
extendable via the `REKALL_UI_ORIGINS` csv) with the `X-Rekall-UI` header and
`application/json` (403 otherwise), and answers 421 to any request whose
`Host` is outside the allowlist (loopback names, extendable via the
`REKALL_ALLOWED_HOSTS` csv). Requests without browser markers — hooks' curl,
the CLI, MCP clients — pass untouched, and a valid `REKALL_API_TOKEN` bearer
takes precedence over origin rejection for non-loopback deployments. The
cockpit sends the header from `ui/lib/api/client.ts`; an older cockpit
against a newer server will 403 on mutations — upgrade both together.

## Reporting a vulnerability

Report vulnerabilities privately via
[GitHub security advisories](../../security/advisories/new). Please do not
open public issues for security problems.
