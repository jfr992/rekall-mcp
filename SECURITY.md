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

## Reporting a vulnerability

Report vulnerabilities privately via
[GitHub security advisories](../../security/advisories/new). Please do not
open public issues for security problems.
