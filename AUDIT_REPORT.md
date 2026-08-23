# Principal Engineer Audit — MODE: AUDIT

## 1. Executive Summary

[FACT] Rekall is a public-beta, local-first memory service that exposes Python, CLI, MCP, REST, and Next.js interfaces over YAML, Qdrant, NetworkX, and JSONL storage (`pyproject.toml:1-16`, `docs/ARCHITECTURE.md:283-325`).

[JUDGMENT] **Health grade: D for network-exposed deployments; C for the supported loopback-only defaults.** The unpatched cockpit RCE caps any network-reachable deployment at D. Loopback materially reduces remote reachability, but verified consistency and failure-reporting defects still prevent a production-ready rating.

[FACT] A live production-dependency audit on 2026-08-23 reported **1 Critical and 3 High** vulnerable packages, including the committed Next.js 15.5.6 App Router installation (`ui/package-lock.json:5251-5262`, `ui/app/layout.tsx:1-43`).

[JUDGMENT] The first major risk is compromise of a network-reachable cockpit, which can then reach the unauthenticated memory backend on the Compose network. The default Compose host mapping is loopback-only; this critical path applies when an operator exposes the cockpit beyond that boundary or an attacker already has local access.

[JUDGMENT] The second major risk is disclosure of the optional Gemini API key through the unauthenticated health response and raw exception handling.

[JUDGMENT] The third major risk is partial mutation across YAML, Qdrant, and the graph: deletion can report success while leaving searchable data behind, while failed save/update calls can leave durable split state that is unsafe to retry.

[JUDGMENT] The highest-leverage opportunities are to make mutations explicitly recoverable, make HTTP/readiness boundaries truthful and secret-safe, and turn CI into an authoritative release signal.

[FACT] This audit modified no tracked source files; `AUDIT_REPORT.md` is the requested deliverable, and pre-existing worktree changes were left untouched.

---

# Phase 1 — Discovery & Mapping

## 2. Repo Map

### Purpose and maturity

- [FACT] Rekall gives AI assistants durable, cross-session memory with typed relationships and semantic recall (`README.md:1-15`).
- [FACT] The package is version `1.13.0`, targets Python 3.11+, and declares beta maturity for developer users (`pyproject.toml:1-16`).
- [JUDGMENT] The release automation, container paths, cockpit, security policy, and 1,299 collected Python tests make this a serious public beta rather than a prototype.
- [FACT] The repository contains 538 tracked files, approximately 18.8k Python source lines, 30.2k Python test lines, and 11.2k UI TypeScript/TSX lines.
- [FACT] The supplied `AGENTS.md` imports `RTK.md`, but no `RTK.md` exists at the repository root or its parent; its additional instructions could not be verified.

### Stack

- [FACT] The backend uses Python, FastMCP, Starlette/Uvicorn, Qdrant Client, FastEmbed, HTTPX, NetworkX, Click, PyYAML, Pydantic, pytest, Ruff, and mypy (`pyproject.toml:18-43`).
- [FACT] The cockpit uses Next.js 15, React 19, React Query, Zod, Zustand, Tailwind, Vitest, and TypeScript (`ui/package.json:5-38`).
- [FACT] Distribution paths include PyPI/`uvx`, an HTTP daemon, an all-in-one container, and three-container Compose (`pyproject.toml:45-58`, `docs/ARCHITECTURE.md:314-325`).

### Architecture sketch

```text
[FACT]

Claude hooks / CLI / MCP clients / Browser cockpit
                │
                ▼
     server.py / FastMCP / Starlette / CLI
                │
                ▼
       process-wide MemoryManager
                │
       ┌────────┼──────────┬──────────────┐
       ▼        ▼          ▼              ▼
 YAML archive  Qdrant   NetworkX graph  JSONL events
 source truth  recall      relations     operations
       └────────┴──────────┴──────────────┘
                │
                ▼
       recall / capsules / publish / doctor
```

- [FACT] The intended flow is event capture → YAML archive → Qdrant and graph indexes → recall and agent-facing capsules (`docs/ARCHITECTURE.md:43-58`).
- [FACT] `MemoryManager` currently owns domain decisions and direct filesystem, embedding, Qdrant, graph, and event-log I/O (`src/memory/manager.py:164-222`, `src/memory/manager.py:410-510`).
- [JUDGMENT] The dominant architectural risk is therefore not file size by itself; it is coordinating several durable side effects without an explicit mutation state.

### Key areas

| Area | Description |
|---|---|
| `src/server.py` | [FACT] FastMCP initialization, HTTP middleware, health, and approximately 40 REST routes (`src/server.py:35-165`, `src/server.py:311-331`). |
| `src/memory/` | [FACT] Memory lifecycle, recall, persistence, graph, events, publishing, repair, cleanup, and CLI behavior. |
| `src/core/` | [FACT] Embeddings, Qdrant adapter, ownership, browser protection, utilities, and telemetry. |
| `src/tools/` | [FACT] Tool discovery/configuration and MCP memory handlers (`src/tools/builtin/memory.py:484-587`). |
| `ui/` | [FACT] Next.js App Router cockpit, response schemas, API client, and Vitest tests (`ui/app/layout.tsx:1-43`, `ui/lib/schemas.ts:1-55`). |
| `claude/` | [FACT] Claude Code hooks, setup scripts, and assistant-facing skills (`README.md:65-83`). |
| `tests/` | [FACT] Unit, integration, wheel, embedded-store, security, and nervous-system behavior tests (`pyproject.toml:60-69`, `.github/workflows/ci.yml:34-136`). |
| `benchmarks/` | [FACT] LongMemEval and related effectiveness evidence (`README.md:280-284`). |
| `scripts/` | [FACT] Operational and developer startup utilities, including the full-stack launcher (`scripts/start-rekall.sh:1-70`). |

### Existing conventions worth retaining

- [FACT] YAML is documented as source of truth while Qdrant and the graph are rebuildable indexes (`docs/ARCHITECTURE.md:283-293`).
- [FACT] Per-file YAML and graph writes use temporary files followed by atomic `os.replace` (`src/memory/manager.py:934-946`, `src/memory/knowledge_graph.py:111-139`).
- [FACT] Tests actively prevent production Qdrant and memory paths from being touched (`tests/conftest.py:27-78`).
- [FACT] The UI generally parses responses through Zod schemas (`ui/lib/schemas.ts:1-55`).
- [FACT] Pre-commit hooks cover formatting, linting, secret detection, mypy, and pytest (`.pre-commit-config.yaml:1-38`).

### Review depth and verification limits

- [FACT] Deep review concentrated on `MemoryManager`, HTTP/MCP boundaries, embedding and vector adapters, health, configuration, primary cockpit API paths, CI, deployment, and the Claude/Codex lifecycle integration surfaces.
- [FACT] Crawler parsing, visual UI components, benchmark semantic validity, and release publishing received lighter review.
- [FACT] Fresh verification produced: Ruff lint passing, Ruff format failing on one tracked test file, 17/17 targeted boundary tests passing, and mypy reporting 166 errors across 33 of 71 source files.
- [FACT] The broader non-integration Python run produced 1,155 passes, 8 skips, and 34 failures; most failures involved prohibited sockets or offline tokenizer/model access, but the Qdrant test-selection defect described below is structurally reproducible from CI configuration.
- [FACT] UI tests could not start in the existing local `node_modules` because `tdd-guard-vitest` was absent, although it is present in both manifests and would be installed by `npm ci` (`ui/package.json:25-38`, `ui/package-lock.json:6198-6208`).
- [FACT] A local production build reached compilation but could not download three Google fonts in the restricted network because the layout imports `next/font/google` (`ui/app/layout.tsx:1-24`).
- [FACT] Python CVEs were not independently verified because `pip-audit` is neither installed nor configured in the repository.

### Surprises

- [JUDGMENT] The test-to-source ratio and explicit test-isolation safeguards are substantially better than the runtime mutation guarantees.
- [JUDGMENT] The 2,399-line manager and 2,269-line server are symptoms of concentrated operational responsibility, but splitting them purely for size would be unjustified.
- [FACT] The architecture document’s testing section is duplicated and still claims “245 passed” and that all tests use mocks (`docs/ARCHITECTURE.md:343-365`).

---

# F16 — Codex support is documented but not shipped

**[JUDGMENT] Severity: Medium product correctness / integration safety · Fix tier: Tier 2**

**[FACT] Remediation status:** Addressed on the `codex/support` branch; the finding remains here as the evidence and acceptance record for the change.

- **Evidence [FACT]:** Before this work, the repository had no `codex/` adapter bundle, no Codex lifecycle contract tests, generic FastMCP metadata, and user guidance centered on Claude hooks. The installed local environment likewise had no reproducible Codex installer path. These are repository and inspected-environment observations, not claims about every Codex installation.
- **Impact [JUDGMENT]:** A user could believe memory support was client-neutral while silently depending on Claude-specific wiring; setup was not reproducible and native Codex memory ownership was unclear.
- **Smallest safe fix [JUDGMENT]:** Ship a typed Codex lifecycle adapter, deterministic hook merger, idempotent installer, MCP-first skill, client-neutral server instructions, and parity-tested documentation. Keep native `~/.codex/memories/` untouched.
- **Target architecture [JUDGMENT]:** Claude and Codex adapters feed the same MCP/REST server; each harness retains its own native memory. The adapter plane owns bounded transformation and transport only.
- **Definition of done [JUDGMENT]:** Isolated install and rollback are documented and tested; foreign configuration is preserved; conflicting MCP definitions fail before mutation; MCP transport paths require an explicit REST hook base; add and post-add verification failures roll back; native-memory non-interference is asserted; all six hook contracts and bounded/untrusted context behavior have tests; Codex and Claude quickstarts are balanced.
- **Milestone [JUDGMENT]:** Add the Codex bundle and dependencies in the first-class harness-adapter milestone, then run focused lifecycle, installer, server-instruction, and documentation parity gates before broader integration verification.

**Review-depth update [FACT/JUDGMENT]:** The Claude install, restore, observe, reflex, prune, and capsule hook paths were reviewed specifically for Codex migration and parity. That focused review found marker-token sanitization, raw-content logging, API URL inconsistency, and startup untrusted framing risks; they remain follow-up evidence rather than silent Claude refactors. Existing strengths include `agent_startup(agent="codex")` and the client-neutral backend.

# Phase 2 — Audit Report

## Security and dependencies

### F1 — Known remotely exploitable cockpit dependency
**[JUDGMENT] Severity: Critical · Fix tier: Tier 2**

- **Found / where:** [FACT] The lockfile installs deprecated Next.js `15.5.6`; the application uses the affected App Router, and the current production audit reports one Critical and three High packages (`ui/package-lock.json:5251-5262`, `ui/app/layout.tsx:1-43`, `ui/package-lock.json:5223-5239`, `ui/package-lock.json:5453-5472`, `ui/package-lock.json:5896-5919`).
- **Why it matters:** [FACT] Next.js identifies CVE-2025-66478 as a CVSS 10.0 remote-code-execution vulnerability affecting unpatched Next 15 App Router applications and lists 15.5.7 as the initial fixed 15.5 release ([official advisory](https://nextjs.org/blog/CVE-2025-66478)).
- **Current release timing:** [FACT] Next.js has also announced a scheduled August 26, 2026 security release for the 15.5 maintenance line addressing another Critical vulnerability ([official notice](https://nextjs.org/blog/upcoming-nextjs-security-release-august-2026)).
- **Blast radius:** [JUDGMENT] Cockpit compromise can expose the UI process and provides network reachability to `http://mcp:8000`, where memory read/write/delete operations are available (`docker-compose.yaml:75-85`). Default Compose host mappings are loopback-only, so remote exploitability depends on explicit network exposure; local compromise remains in scope.
- **Smallest safe fix:** [JUDGMENT] Upgrade immediately to the current patched 15.5 release and its safe production transitives, regenerate the lockfile, and require audit, tests, typecheck, and production build to pass. Repeat the audit and patch again when the announced August 26 release lands; do not wait for unrelated backend CI cleanup.
- **Tier rationale:** [JUDGMENT] Dependency behavior and framework output may change, so this needs approval despite being urgent.

### F2 — Gemini credentials can escape through public errors
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] Gemini places its API key in the request query string and calls `raise_for_status`; embedder health converts the complete exception to text, `/health` returns it, and authentication deliberately exempts `/health` (`src/core/embeddings.py:262-295`, `src/server.py:106-136`, `src/server.py:263-299`, `src/server.py:311-331`).
- **Found / where:** [FACT] A sentinel HTTPX test confirmed that the query-string value appears in `HTTPStatusError.__str__`; ordinary routes likewise log and return raw exception text (`src/server.py:453-456`, `src/server.py:489-518`, `src/server.py:1168-1182`).
- **Why it matters:** [JUDGMENT] An invalid, revoked, or rate-limited Gemini request can disclose the credential to unauthenticated health callers and operational logs.
- **Blast radius:** [JUDGMENT] Anyone able to reach `/health`, plus anyone with log access, could gain the authority attached to the Gemini key.
- **Smallest safe fix:** [JUDGMENT] Add one boundary-level exception mapper/redactor, return stable public error codes rather than `str(e)`, and ensure provider URLs, headers, and bodies are scrubbed before logging.
- **Tier rationale:** [JUDGMENT] Public error bodies change, so the patch requires approval and contract tests.

### F3 — The convenience launcher silently abandons the localhost trust model
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] The main server defaults to `127.0.0.1`, but `scripts/start-rekall.sh` defaults the bare-metal backend to `0.0.0.0` without requiring `REKALL_API_TOKEN` (`src/server.py:139-153`, `scripts/start-rekall.sh:21-39`).
- **Why it matters:** [FACT] The documented trust model states that anyone who can reach the port can read, write, and delete memories (`SECURITY.md:3-21`).
- **Blast radius:** [JUDGMENT] Running the advertised developer stack on a shared or hostile LAN exposes the complete memory API to neighboring hosts.
- **Smallest safe fix:** [JUDGMENT] Default the script to loopback and require an explicit network-exposure flag plus a token before accepting a non-loopback bind.
- **Tier rationale:** [JUDGMENT] This intentionally changes launcher behavior and therefore belongs in Tier 2.

### F4 — Cockpit authentication exposes its bearer token and breaks downloads
**[JUDGMENT] Severity: Medium · Fix tier: Tier 2**

- **Found / where:** [FACT] The README instructs operators to set `NEXT_PUBLIC_REKALL_API_TOKEN`; client-side code reads it and sends it as a bearer token (`README.md:257-276`, `ui/lib/api/client.ts:8-29`).
- **Found / where:** [FACT] Next.js documents that `NEXT_PUBLIC_` values are embedded in browser-delivered JavaScript ([official environment-variable guide](https://nextjs.org/docs/app/guides/environment-variables)).
- **Found / where:** [FACT] Bundle download uses a plain anchor rather than `fetchJson`, so no authorization header is attached even though backend auth protects every non-health path (`ui/components/publish/okf-export.tsx:178-195`, `ui/lib/api/publish.ts:11-13`, `src/server.py:110-136`).
- **Why it matters:** [JUDGMENT] The single administrative token becomes browser-visible while one cockpit operation still receives a 401 when authentication is enabled.
- **Blast radius:** [JUDGMENT] Authenticated cockpit deployments and every user or extension able to inspect their client bundle are affected.
- **Smallest safe fix:** [JUDGMENT] Move the token to a server-only environment variable and proxy API/download requests through a Next route handler that attaches it.
- **Tier rationale:** [JUDGMENT] This changes deployment configuration and request flow.

### F5 — Primary content boundaries are untyped and unbounded
**[JUDGMENT] Severity: Medium · Fix tier: Tier 2**

- **Found / where:** [FACT] Save and recall validate only truthiness for `content` and `query`, while observe does the same for `summary`; no shared request-body or content-length limit is configured (`src/server.py:489-518`, `src/server.py:521-563`, `src/server.py:2093-2117`).
- **Found / where:** [FACT] Sanitization assumes a string and immediately passes content to regular expressions, embedding, and persistence (`src/memory/manager.py:64-100`, `src/memory/manager.py:416-444`).
- **Why it matters:** [JUDGMENT] Non-string input becomes a 500, while very large input can consume model, network, memory, and disk resources before rejection.
- **Blast radius:** [JUDGMENT] Every REST save, recall, and observe caller is affected; network exposure turns this into a simple resource-exhaustion path.
- **Smallest safe fix:** [JUDGMENT] Introduce shared typed request parsers with explicit byte/character limits and use the same limits for REST and MCP tools.
- **Tier rationale:** [JUDGMENT] Previously accepted oversized requests will be rejected.

## Architecture and correctness

### F6 — Deletion reports success after partial failure and cannot repair itself
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] `delete` removes YAML first, then treats Qdrant and graph deletion as best-effort and returns `True` after swallowing either failure (`src/memory/manager.py:1035-1126`).
- **Found / where:** [FACT] A retry returns `False` once YAML is absent and therefore never retries removal from Qdrant or the graph (`src/memory/manager.py:1049-1067`).
- **Why it matters:** [JUDGMENT] A caller can receive `{"deleted": true}` while the supposedly deleted content remains searchable, and the same API cannot finish the operation (`src/server.py:1185-1208`).
- **Blast radius:** [JUDGMENT] Privacy deletion, pruning, cleanup, and UI deletion all inherit the false acknowledgement.
- **Smallest safe fix:** [JUDGMENT] Make store deletion idempotent, delete rebuildable indexes before the YAML source, preserve YAML on any index failure, and return a typed per-store outcome.
- **Tier rationale:** [JUDGMENT] Failure semantics change and need injected-failure tests.

### F7 — Failed save and update calls can leave durable split state
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] Save durably appends YAML before Qdrant, event, and graph operations (`src/memory/manager.py:466-510`).
- **Found / where:** [FACT] Update rewrites YAML before encoding and the Qdrant upsert (`src/memory/manager.py:948-985`).
- **Why it matters:** [JUDGMENT] A Qdrant or embedding failure leaves durable content that the caller was told failed, while recall retains absent or stale vectors; retrying save can append a second YAML record because deduplication searches Qdrant first.
- **Blast radius:** [JUDGMENT] Every save/update caller, rebuild process, backup, and recall consumer can observe inconsistent identity or content.
- **Smallest safe fix:** [JUDGMENT] Make the YAML write idempotent by stable memory ID, preserve or return that ID on partial failure so a caller can retry safely, and make doctor/reindex converge the indexes. Add a durable pending-repair record only if failure-injection tests prove those simpler guarantees cannot represent or repair every failure point.
- **Tier rationale:** [JUDGMENT] Retry and failure contracts change; the smallest convergent design must be selected from failure-injection evidence rather than assumed up front.

### F8 — Human lifecycle state bypasses the declared source of truth
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] Architecture declares YAML the source of truth, but pinning and dispute resolution update only the Qdrant payload (`docs/ARCHITECTURE.md:283-293`, `src/memory/manager.py:1128-1191`).
- **Found / where:** [FACT] Lifecycle backfill likewise writes only Qdrant payloads (`src/memory/manager.py:850-890`).
- **Why it matters:** [JUDGMENT] Reindexing from YAML can silently discard human pin/dispute decisions and lifecycle metadata.
- **Blast radius:** [JUDGMENT] Identity-tier memories, disputed facts, cleanup selection, and post-rebuild ranking are affected.
- **Smallest safe fix:** [JUDGMENT] Add one atomic YAML metadata-patch operation and use it alongside Qdrant updates, with a YAML → reindex → Qdrant round-trip test.
- **Tier rationale:** [JUDGMENT] Existing persisted records and rebuild behavior change.

### F9 — Qdrant authentication is ignored and configuration ownership is ambiguous
**[JUDGMENT] Severity: Medium · Fix tier: Tier 2**

- **Found / where:** [FACT] `src/config.py` calls itself the recommended unified configuration and defines Qdrant, server, embedding, collection, and retention settings (`src/config.py:1-84`).
- **Found / where:** [FACT] The HTTP server instead loads a separate tool-only `MCP_CONFIG`, while `MemoryManager` reads environment variables directly and hardcodes the collection (`src/server.py:45-70`, `src/memory/manager.py:164-205`, `src/memory/singleton.py:14-20`).
- **Found / where:** [FACT] `QDRANT_API_KEY` is advertised and parsed, and `VectorStore` supports it, but the main manager never passes it to the adapter (`.env.example:19-22`, `src/config.py:199-206`, `src/core/vector_store.py:81-109`, `src/memory/manager.py:279-289`).
- **Found / where:** [FACT] Repository search finds no runtime consumer of `Config.load()` outside `src/config.py` itself, so the supposedly unified configuration is currently dead infrastructure rather than an established application contract.
- **Why it matters:** [JUDGMENT] Operators can believe a setting applies while the service ignores it, and the documented Qdrant Cloud path cannot authenticate.
- **Blast radius:** [JUDGMENT] Service, migration, cleanup, and sync commands can resolve different stores or policies.
- **Smallest safe fix:** [JUDGMENT] First pass `QDRANT_API_KEY` through the main manager into `VectorStore` and add a focused Qdrant Cloud construction test. Separately decide whether to adopt `src/config.py` as canonical or delete it; do not make a repository-wide settings migration a prerequisite for restoring advertised authentication.
- **Tier rationale:** [JUDGMENT] The authentication repair is small but affects a security boundary; configuration consolidation is a separate product/architecture decision.

### F10 — The unpackaged auxiliary indexer is presently broken
**[JUDGMENT] Severity: Low · Fix tier: Tier 1 after support decision**

- **Found / where:** [FACT] The indexer constructs `Embedder(model_name=...)` and reads `embedder.dimension`, but the real interface accepts `model` and exposes `dimensions` (`src/indexer/cli.py:100-121`, `src/core/embeddings.py:340-347`, `src/core/embeddings.py:430-433`).
- **Found / where:** [FACT] Mypy reports 166 errors but remains advisory, and no indexer CLI contract test catches this mismatch (`.github/workflows/ci.yml:27-32`).
- **Found / where:** [FACT] `src/indexer` and `src/crawler` are not included in the wheel package list or exposed through `[project.scripts]`; README mentions them only in the repository map (`pyproject.toml:45-58`, `README.md:541-542`).
- **Why it matters:** [JUDGMENT] The command fails at component initialization before indexing any document.
- **Blast radius:** [JUDGMENT] Only source-checkout users who manually invoke this undocumented auxiliary workflow are affected; it is not currently part of the shipped Rekall package contract.
- **Smallest safe fix:** [JUDGMENT] Decide whether the crawler/indexer is supported. If yes, add a failing CLI initialization test, repair the two interface names, and document/package the entry path. If no, deprecate or remove the dead workflow instead of adding maintenance surface.
- **Tier rationale:** [JUDGMENT] This is not a release blocker until support is affirmed; the eventual code repair is small.

## Performance, concurrency, and operability

### F11 — Health fails open when Qdrant is unavailable
**[JUDGMENT] Severity: Medium · Fix tier: Tier 2**

- **Found / where:** [FACT] Both manager and server convert vector-store exceptions into `{"sampled": 0, "zero_vectors": 0}` (`src/memory/manager.py:2300-2318`, `src/server.py:237-249`).
- **Found / where:** [FACT] Health calls that state healthy unless zero vectors or the embedder reports an error, and it always returns HTTP 200 (`src/server.py:311-331`).
- **Found / where:** [FACT] Docker and Compose use `curl -f`, so even a body marked `degraded` remains container-healthy (`Dockerfile:60-61`, `docker-compose.yaml:65-70`).
- **Why it matters:** [JUDGMENT] Health consumers cannot distinguish a functioning service from one whose required recall store is unavailable. This repository ships Docker Compose rather than a traffic-routing orchestrator; Compose records health but does not itself provide the load-balancer behavior implied by a generic orchestration claim.
- **Blast radius:** [JUDGMENT] Operator diagnostics, dependency startup checks, launcher output, and external systems that choose to consume `/health` as readiness receive false assurance. Container auto-restart or traffic-routing impact is deployment-specific and is not demonstrated by this repository.
- **Smallest safe fix:** [JUDGMENT] Separate liveness from readiness, preserve dependency error state, and return 503 from readiness when Qdrant or the configured embedder cannot serve requests.
- **Tier rationale:** [JUDGMENT] Health status codes and orchestration behavior change.

### F12 — Async interfaces execute blocking work and can race first singleton initialization
**[JUDGMENT] Severity: High · Fix tier: Tier 2**

- **Found / where:** [FACT] REST save and recall are `async` but directly invoke synchronous embedding, Qdrant, filesystem, and graph methods; only resparse explicitly uses `asyncio.to_thread` (`src/server.py:474-518`, `src/server.py:521-563`).
- **Found / where:** [FACT] MCP async handlers follow the same direct synchronous pattern (`src/tools/builtin/memory.py:488-587`).
- **Found / where:** [FACT] External embedding calls carry 30–60 second timeouts, while the process singleton uses an unlocked check-and-create and health initializes it from a worker thread (`src/core/embeddings.py:205-222`, `src/core/embeddings.py:262-295`, `src/memory/singleton.py:14-20`, `src/server.py:280-295`).
- **Why it matters:** [JUDGMENT] One slow save or recall can block the event loop and health traffic; simultaneous first health/request access can construct two managers despite the documented split-brain warning.
- **Blast radius:** [JUDGMENT] Every concurrent HTTP/MCP user shares the same latency and initialization risk.
- **Smallest safe fix:** [JUDGMENT] Eagerly construct the singleton in lifespan, route blocking application calls through one bounded execution adapter, and serialize mutations explicitly before introducing read concurrency.
- **Tier rationale:** [JUDGMENT] Scheduling and concurrency behavior change and require load/failure tests.

### F13 — Initial event-log reads copy the full file; retention is undefined
**[JUDGMENT] Severity: Medium for unbounded reads · Retention risk: unscored pending policy**

- **Found / where:** [FACT] Events append indefinitely to one JSONL file; both `tail` and no-cursor `_fresh_tail` read the whole file before slicing to the requested limit (`src/memory/events.py:55-75`, `src/memory/events.py:77-144`).
- **Why it matters:** [JUDGMENT] Memory use and initial event latency grow linearly with system lifetime rather than requested page size. Separate from that verified implementation issue, indefinite append can consume disk, but no event-volume target or retention requirement was supplied.
- **Blast radius:** [JUDGMENT] Long-lived installations and cockpit initial event feeds are directly affected by full-file reads. Backup size and disk exhaustion depend on actual event volume and retention expectations and should not be scored without measurements.
- **Smallest safe fix:** [JUDGMENT] Implement a reverse chunked tail so initial reads are bounded. Treat rotation/retention as a separate product decision: measure event growth, define required history, then design rotation that preserves explicit cursor invalidation semantics.
- **Tier rationale:** [JUDGMENT] Bounded tailing is a behavior-preserving implementation fix; deletion of retained history requires human policy approval.

## Testing and developer experience

### F14 — CI is neither currently green nor fully authoritative
**[JUDGMENT] Severity: Medium · Fix tier: Tier 2**

- **Remediation status [FACT]:** The Ruff format drift in `tests/test_publish_synthesis.py` is fixed on `codex/support`; the Qdrant lane, UI authority, and typed-gate findings remain open.
- **Found / where:** [FACT] The blocking backend unit job has no Qdrant service, while unmarked pin/dispute tests use `memory_manager`, whose default lane targets Qdrant on port 6334 (`.github/workflows/ci.yml:9-32`, `tests/conftest.py:117-126`, `tests/test_manager_pin.py:13-53`, `tests/test_manager_dispute.py:13-26`).
- **Found / where:** [FACT] Before this branch, the Ruff format gate failed on `tests/test_publish_synthesis.py`, despite CI describing blocking gates as green (`.github/workflows/ci.yml:18-26`, `tests/test_publish_synthesis.py:1-91`).
- **Found / where:** [FACT] UI CI runs tests but no production build or explicit TypeScript check, and ESLint is advisory without a committed replacement for deprecated `next lint` (`.github/workflows/ci.yml:182-200`, `ui/package.json:5-11`).
- **Found / where:** [FACT] Mypy remains advisory with a stale “~110 errors” comment while fresh verification reports 166 (`.github/workflows/ci.yml:27-32`).
- **Why it matters:** [JUDGMENT] Contributors can receive false-red backend results while release-only UI and type failures remain false-green.
- **Blast radius:** [JUDGMENT] Every pull request and release inherits a low-trust safety signal.
- **Smallest safe fix:** [JUDGMENT] Make unit tests hermetic, restore formatting, add UI build/typecheck/lint gates, and make a small typed core/entry-point slice blocking before expanding mypy scope.
- **Tier rationale:** [JUDGMENT] The complete repair exceeds S effort and may reveal additional build failures.

## Documentation

### F15 — The privacy promise contradicts optional cloud behavior
**[JUDGMENT] Severity: Medium · Fix tier: Tier 1**

- **Found / where:** [FACT] README states “Nothing is sent anywhere,” while Gemini sends memory text to Google and synthesis sends clustered note content to an Anthropic-compatible endpoint (`README.md:237-250`, `src/core/embeddings.py:262-295`, `src/memory/publish.py:319-360`).
- **Why it matters:** [JUDGMENT] Users can enable documented cloud providers without understanding that memory content leaves the machine.
- **Blast radius:** [JUDGMENT] Privacy expectations, data-residency decisions, and regulated or proprietary memory content are affected.
- **Smallest safe fix:** [JUDGMENT] Change the promise to “local by default” and document exactly which opt-in providers receive content.
- **Tier rationale:** [JUDGMENT] This is a behavior-preserving documentation correction under two hours.

## Strengths to preserve

- [FACT] Bare-metal and Compose defaults bind host ports to loopback (`src/server.py:139-153`, `docker-compose.yaml:20-24`, `docker-compose.yaml:54-58`, `docker-compose.yaml:82-85`).
- [FACT] Browser-origin and Host validation explicitly address CSRF and DNS rebinding rather than assuming localhost is sufficient (`SECURITY.md:26-40`, `src/core/browser_guard.py:27-93`).
- [FACT] Bearer comparison uses constant-time primitives (`src/server.py:124-135`, `src/core/browser_guard.py:43-48`).
- [FACT] The doctor already detects YAML/Qdrant drift and zero vectors, providing a natural repair surface (`src/memory/doctor.py:105-150`).
- [FACT] Per-file persistence is atomic and cleans temporary files on failure (`src/memory/manager.py:934-946`, `src/memory/knowledge_graph.py:128-139`).
- [FACT] Test isolation actively refuses production storage and resets process state between tests (`tests/conftest.py:27-78`).
- [FACT] CI includes separate real-Qdrant, embedded-store, and clean-wheel smoke lanes (`.github/workflows/ci.yml:34-136`).
- [FACT] Pre-commit and secret-scanning configurations already exist (`.pre-commit-config.yaml:1-38`, `.gitleaks.toml:1`).
- [FACT] Direct package licensing is clearly declared as Apache-2.0, and no direct-license conflict was identified during the review (`pyproject.toml:1-16`).

---

# Phase 3 — Improvement Strategy

## 3. Strategic themes

| Theme | Target state | Design Lens | Consequences |
|---|---|---|---|
| **Recoverable multi-store mutations** | [JUDGMENT] Every mutation has a stable ID, idempotent retry, and repair path across YAML, Qdrant, graph, and events; explicit pending state is added only where failure tests require it. | [JUDGMENT] Failure design; State & types; Boundaries. | [JUDGMENT] Retries, pruning, and rebuilds become predictable without assuming a repair journal is necessary before testing simpler convergence. |
| **Truthful, secret-safe boundaries** | [JUDGMENT] REST/MCP requests are typed and bounded; public errors are stable; readiness reflects dependencies; logs never echo credentials. | [JUDGMENT] Boundaries; Failure design; Operability. | [JUDGMENT] Operations and clients can act on reliable signals; raw debugging detail moves to protected structured logs. |
| **Truthful runtime settings and secret ownership** | [JUDGMENT] Every documented setting is applied, Qdrant credentials reach the adapter, browser secrets remain server-side, and unused configuration paths are either adopted explicitly or removed. | [JUDGMENT] Explicitness; Security; Dependency direction. | [JUDGMENT] Immediate authentication defects are repaired without prematurely committing the repository to a broad configuration migration. |
| **Authoritative safety gates** | [JUDGMENT] Unit tests are hermetic, release artifacts build in CI, critical dependencies are audited, and a core type-safe slice blocks merges. | [JUDGMENT] Failure design; Simplicity; Operability. | [JUDGMENT] Pull-request results regain meaning; some existing debt becomes visible instead of remaining advisory. |
| **First-class harness adapters** | [JUDGMENT] Claude and Codex have separate, tested lifecycle adapters over one client-neutral memory service; neither adapter edits harness-native memory. | [JUDGMENT] Boundaries; Security; Simplicity. | [JUDGMENT] Agent integration becomes reproducible without coupling Rekall to one client or duplicating domain policy. |

### Target architecture

```text
[JUDGMENT]

Claude adapter ─┐
Codex adapter ──┼─> HTTP / MCP / CLI
Direct clients ─┘          │
                           ▼
typed command + bounded input
      │
      ▼
application mutation service
      │
      ├── stable identity + idempotency
      ├── optional pending-repair state where tests require it
      │
      ├── YAML source adapter
      ├── Qdrant index adapter
      ├── graph adapter
      └── event adapter
      │
      ▼
typed committed / pending-repair / failed result
```

- [JUDGMENT] This does not require microservices, a database replacement, or a wholesale manager rewrite.
- [JUDGMENT] The application service should coordinate side effects while pure lifecycle, ranking, validation, and transformation functions remain independently testable.

## Explicit non-recommendations

- [JUDGMENT] Do **not** split `MemoryManager` or `server.py` solely because they are large; first extract only mutation coordination and boundary parsing that directly address verified failures.
- [JUDGMENT] Do **not** introduce Kafka, distributed transactions, or an external job system for a local-first daemon; first prove whether idempotent writes plus existing doctor/reindex repair are sufficient, and add only the smallest durable repair marker that failure tests still require.
- [JUDGMENT] Do **not** pursue 100% mypy compliance across all 166 errors before fixing runtime risks; make critical boundaries and entry points clean first.
- [JUDGMENT] Do **not** replace NetworkX or optimize the current 2,000-record entity scan without measured workload targets (`src/memory/manager.py:1528-1556`).
- [JUDGMENT] Do **not** add RBAC, tenants, or enterprise observability unless networked multi-user operation is a supported product goal.
- [JUDGMENT] Do **not** remove cloud embedding or synthesis merely because they are non-local; make data transfer explicit and opt-in.

## Definition of done

- [JUDGMENT] `npm audit --omit=dev` reports zero Critical and zero High production vulnerabilities, or every exception has a time-bounded human-approved waiver; the check is repeated after the announced August 26, 2026 Next.js security release.
- [JUDGMENT] Failure-injection tests prove deletion never removes YAML or reports success while an index deletion is incomplete.
- [JUDGMENT] Save/update retries cannot create duplicate YAML identities or leave stale vectors without a visible repair state.
- [JUDGMENT] Pin and dispute metadata survive YAML → rebuild → Qdrant round trips.
- [JUDGMENT] Public responses and logs contain no sentinel secrets under provider errors.
- [JUDGMENT] The main service passes the configured `QDRANT_API_KEY` to the Qdrant client in a focused construction test.
- [JUDGMENT] Readiness returns 503 when required Qdrant or embedding dependencies are unavailable.
- [JUDGMENT] Backend unit CI runs without Qdrant; integration tests alone require the service.
- [JUDGMENT] UI lint, tests, typecheck, production build, and production dependency audit are blocking.
- [JUDGMENT] The selected core/entry-point mypy slice has zero errors.
- [JUDGMENT] Documentation says local-by-default, names every opt-in cloud content transfer, and does not imply cloud-enabled memory stays local.
- [JUDGMENT] First-class harness adapters install and roll back in isolation, preserve foreign configuration, pass lifecycle contract tests, and never touch harness-native memory.
- [JUDGMENT] Zero Critical and zero unaccepted High audit findings remain.

---

# Phase 4 — Detailed Task Plan

## 4. Milestones and tasks

| ID / Task | Tier | Description and proposed patch sketch | Files / areas | Acceptance criteria | Effort | Change risk | Dependencies |
|---|---:|---|---|---|---:|---:|---|
| **M0.1 — Mutation failure safety net** | 2 | [JUDGMENT] Add failure-injection tests for YAML, Qdrant, graph, embedding, and event steps before changing mutation order. | [FACT] `tests/test_memory.py`, new focused mutation test module. | [JUDGMENT] Tests reproduce F6/F7 and fail against current behavior for the intended reason. | M | Low | None |
| **M0.2 — Restore authoritative CI** | 2 | [JUDGMENT] Format the tracked test, make pin/dispute unit tests embedded or mocked, move genuine service tests under `integration`, add UI build/typecheck/lint, and define a blocking mypy slice. | [FACT] `.github/workflows/ci.yml`, `tests/conftest.py`, pin/dispute tests, `ui/package.json`, ESLint config. | [JUDGMENT] All blocking lanes are hermetic and green from a clean checkout. | M | Medium | None |
| **M0.3 — Correct the cloud privacy promise** | 1 | [JUDGMENT] Immediately replace “Nothing is sent anywhere” with local-by-default language and name the content sent to each opt-in cloud provider. | [FACT] `README.md`, `SECURITY.md`, `.env.example`. | [JUDGMENT] A reader can identify every opt-in path that transfers memory content off-machine. | S | Low | None |
| **M0.4 — Ship the first-class Codex harness adapter** | 2 | [JUDGMENT] Add a typed, bounded lifecycle adapter; safe hook merger; conflict-aware installer; MCP-first skill; client-neutral server instructions; and parity documentation. | [FACT] `codex/`, `src/server.py`, Codex-focused tests and docs. | [JUDGMENT] Isolated install is idempotent, foreign hooks survive, conflicts fail before mutation, six hook contracts pass, and `~/.codex/memories/` remains untouched. | M | Medium | MCP HTTP daemon; official Codex hook contract |
| **M1.1 — Patch the cockpit supply chain** | 2 | [JUDGMENT] Upgrade Next and vulnerable transitives immediately, regenerate only the UI lockfile, and schedule a repeat patch/audit when the announced August 26 release lands. | [FACT] `ui/package.json`, `ui/package-lock.json`. | [JUDGMENT] Audit has zero Critical/High production issues; focused UI tests, typecheck, and build pass. | M | Medium | None—must not wait for unrelated CI cleanup |
| **M1.2 — Seal the public error boundary** | 2 | [JUDGMENT] Replace route-level `str(e)` responses with a shared typed mapper, scrub exceptions before logs, and keep provider detail internal. | [FACT] `src/server.py`, `src/core/embeddings.py`, error/health tests. | [JUDGMENT] Sentinel keys never appear in health, API bodies, or captured logs. | M | Medium | None |
| **M1.3 — Make deletion idempotent** | 2 | [JUDGMENT] Delete Qdrant and graph indexes before YAML, retain YAML on any failure, retry all stores, and return a typed outcome. | [FACT] `src/memory/manager.py`, delete route/tests, prune callers. | [JUDGMENT] Every injected-failure case is retryable and no incomplete delete returns success. | M | Medium | M0.1 |
| **M1.4 — Separate liveness and readiness** | 2 | [JUDGMENT] Preserve Qdrant failures, add readiness status codes, keep liveness process-only, and point container checks at readiness. | [FACT] `src/server.py`, `src/memory/manager.py`, `Dockerfile`, `docker-compose.yaml`. | [JUDGMENT] Qdrant/embedder outage returns 503 readiness while liveness remains process-based. | M | Medium | M1.2 |
| **M1.5 — Restore safe launcher defaults** | 2 | [JUDGMENT] Default the launcher to loopback, add bounded wait helpers, fail nonzero on startup timeout, and require auth for explicit network exposure. | [FACT] `scripts/start-rekall.sh`, script tests/docs. | [JUDGMENT] Default launch is loopback-only and failed services cannot hang or be reported “UP.” | S | Low | M1.4 |
| **M1.6 — Bound REST and MCP inputs** | 2 | [JUDGMENT] Add shared typed validators and explicit content/query/body ceilings before embedding or persistence. | [FACT] `src/server.py`, `src/tools/builtin/memory.py`, validation tests. | [JUDGMENT] Non-string and oversized requests return deterministic 400/413 responses. | M | Medium | M1.2 |
| **M1.7 — Restore Qdrant API-key authentication** | 2 | [JUDGMENT] Add a failing client-construction test, then pass `QDRANT_API_KEY` from the main manager path into `VectorStore`. | [FACT] `src/memory/manager.py`, `src/core/vector_store.py`, focused configuration test. | [JUDGMENT] Qdrant Cloud client construction receives the configured key without a repository-wide settings migration. | S | Low | None |
| **M2.1 — Make save/update retries converge** | 2 | [JUDGMENT] Introduce stable operation/memory identity, make YAML persistence idempotent by ID, and add only the minimal visible pending-repair state demonstrated necessary by failure tests. | [FACT] `src/memory/manager.py`, doctor/reindex, REST/MCP result adapters. | [JUDGMENT] Each failure point converges to one YAML memory and one current vector after retry/repair. | L | High | M0.1, M1.3 |
| **M2.2 — Persist human lifecycle metadata in YAML** | 2 | [JUDGMENT] Implement one atomic YAML metadata-patch primitive and use it for pin, dispute, and lifecycle backfill. | [FACT] `src/memory/manager.py`, rebuild/backfill tests. | [JUDGMENT] Pin/dispute/tier state survives a complete index rebuild. | M | Medium | M2.1 |
| **M2.3 — Establish one blocking-I/O execution boundary** | 2 | [JUDGMENT] Eagerly create the manager during lifespan and offload synchronous application calls through a bounded adapter with explicit mutation serialization. | [FACT] `src/server.py`, `src/tools/builtin/memory.py`, `src/memory/singleton.py`. | [JUDGMENT] A deliberately slow embed does not block health/event-loop heartbeat, and only one manager is constructed. | L | High | M1.4, M2.1 |
| **M2.4 — Resolve configuration ownership** | 2 | [JUDGMENT] After the canonical-source decision, either inject one typed settings object at entry points or delete the unused `src/config.py` path and document environment ownership. | [FACT] `src/config.py`, `src/tools/config.py`, `src/server.py`, singleton/manager, entry points. | [JUDGMENT] One documented precedence model remains and every accepted setting has a runtime consumer. | L | Medium | M1.7, human configuration decision |
| **M3.1 — Bound initial event-log reads** | 1 | [JUDGMENT] Read tails backward in chunks without changing retention. | [FACT] `src/memory/events.py`, event/session tests. | [JUDGMENT] Initial tail memory stays bounded as the fixture log grows, and cursor behavior remains unchanged. | S | Low | None |
| **M3.2 — Refresh post-change architecture documentation** | 1 | [JUDGMENT] After runtime changes, refresh stale test claims and document mutation/readiness semantics. | [FACT] `docs/ARCHITECTURE.md`, `SECURITY.md`. | [JUDGMENT] Documentation matches verified CI and runtime behavior. | S | Low | M1.4, M2.1 |
| **M3.3 — Make authenticated cockpit proxying server-side** | 2 | [JUDGMENT] Replace the public token with a server-only variable and proxy downloads and API requests through authenticated Next route handlers. | [FACT] `ui/lib/api/client.ts`, `ui/lib/api/publish.ts`, `ui/components/publish/okf-export.tsx`, Next routes/docs. | [JUDGMENT] No token exists in client bundles, and download works with backend auth enabled. | M | Medium | M1.1 |
| **M3.4 — Decide crawler/indexer support** | 1 | [JUDGMENT] Either remove/deprecate the unpackaged workflow or make it a tested, documented package surface and repair `model=` / `dimensions`. | [FACT] `src/crawler/`, `src/indexer/`, `pyproject.toml`, README. | [JUDGMENT] No broken ambiguous auxiliary path remains: it is either absent or supported end-to-end. | S | Low | Human support decision |
| **M3.5 — Define event retention from evidence** | 2 | [JUDGMENT] Measure event growth and choose a retention requirement before adding rotation. | [FACT] `src/memory/events.py`, event/session tests, operations docs. | [JUDGMENT] A human-approved size/age policy preserves required history and explicit stale-cursor behavior. | M | Medium | Human retention decision, measured event volume |

## Quick wins

- [JUDGMENT] **Tier 1 / S:** Format `tests/test_publish_synthesis.py` so the declared Ruff gate is not immediately red.
- [JUDGMENT] **Tier 1 / S:** Make pin/dispute unit tests use an embedded or fake store rather than silently requiring Qdrant.
- [JUDGMENT] **Tier 1 / S:** Correct the “Nothing is sent anywhere” documentation claim.
- [JUDGMENT] **Tier 2 / S:** Pass `QDRANT_API_KEY` through the main manager path after adding a focused construction test.
- [JUDGMENT] **Tier 2 / S:** Change `start-rekall.sh` to loopback-by-default and bound its wait loops.
- [JUDGMENT] **Decision / S:** Confirm whether crawler/indexer is supported before either repairing or deleting it.

## Top-three implementation sketches

### T1 — Patch the cockpit supply chain

- **Approach:** [JUDGMENT] Upgrade the smallest supported dependency set that removes all current Critical/High production findings, rather than using an unconstrained bulk update. Execute this independently of backend CI cleanup, then repeat the check when the announced August 26 Next.js security release becomes available.
- **TDD/verification block:**

  ```text
  [JUDGMENT]
  npm audit --package-lock-only --omit=dev
  npm test
  npx tsc --noEmit
  npm run build
  ```

- **Key steps:** [JUDGMENT] Record the pre-upgrade audit, update Next/React-compatible dependencies, regenerate `package-lock.json`, rerun the four focused UI gates, inspect rewrite/container output, and create a dated follow-up for the August 26 patch rather than treating today’s upgrade as final.
- **Gotchas:** [JUDGMENT] A Next-only bump may leave vulnerable `sharp`, `postcss`, or `nanoid`; acceptance is audit output, not merely a newer Next version.
- **Concrete expected output:** [JUDGMENT] Production audit metadata reports `critical: 0` and `high: 0`, with unchanged cockpit API behavior.

### T2 — Make deletion idempotent

- **Proposed interface:**

  ```python
  # [JUDGMENT — sketch only]
  class DeleteOutcome(TypedDict):
      memory_id: str
      status: Literal["deleted", "already_absent", "failed"]
      completed: list[Literal["qdrant", "graph", "yaml"]]
      retryable: bool
  ```

- **TDD block:**

  ```python
  # [JUDGMENT — sketch only]
  test_qdrant_failure_keeps_yaml_and_returns_failure()
  test_graph_failure_keeps_yaml_and_retry_finishes()
  test_yaml_failure_after_index_delete_is_retryable()
  test_second_successful_delete_is_idempotent()
  test_route_never_reports_deleted_for_partial_outcome()
  ```

- **Key steps:** [JUDGMENT] Extract per-store deletion operations, make each idempotent, execute Qdrant → graph → YAML, and map the typed result once at REST/MCP/prune boundaries.
- **Gotchas:** [JUDGMENT] “Already absent” must not be confused with an earlier incomplete deletion, and Qdrant completion semantics must be verified against its client documentation before implementation.
- **Concrete expected output:** [JUDGMENT] A failed index delete leaves YAML intact and returns a retryable failure; retry converges without manual repair.

### T3 — Seal errors and health

- **Proposed interface:**

  ```python
  # [JUDGMENT — sketch only]
  class PublicError(TypedDict):
      code: Literal[
          "invalid_request",
          "dependency_unavailable",
          "internal_error",
      ]
      request_id: str
  ```

- **TDD block:**

  ```python
  # [JUDGMENT — sketch only]
  test_gemini_query_key_absent_from_health_body()
  test_gemini_query_key_absent_from_logs()
  test_internal_exception_returns_stable_public_error()
  test_qdrant_outage_returns_readiness_503()
  test_liveness_does_not_probe_external_dependencies()
  ```

- **Key steps:** [JUDGMENT] Add one exception-to-public-error mapper, one recursive redactor, structured request IDs, and separate liveness/readiness handlers.
- **Gotchas:** [JUDGMENT] Redaction must cover URL query strings, headers, nested exception causes, and response bodies without hiding the exception class or request ID from protected logs.
- **Concrete expected output:** [JUDGMENT] Provider failure returns a stable non-secret body, logs retain a request ID, and the readiness probe returns HTTP 503.

---

## 5. Open Questions

1. [JUDGMENT] Is networked deployment a supported product mode, or merely an escape hatch for advanced users?
2. [JUDGMENT] On a YAML-success/Qdrant-failure save, should the public contract return success-with-pending-repair, or fail while retaining an idempotent operation ID?
3. [JUDGMENT] Is the crawler/indexer workflow supported, or should it be deprecated and removed rather than repaired?
4. [JUDGMENT] What are the expected maximum memory count, JSONL event volume, concurrent callers, and acceptable recall/save latency?
5. [JUDGMENT] How long may operational events be retained, and must rotation preserve a complete audit history?
6. [JUDGMENT] Are Gemini embeddings and Anthropic-compatible synthesis acceptable for all memory classes, or is per-project consent/data classification required?
7. [JUDGMENT] Should `config.yaml` remain the canonical configuration, or should environment-only runtime configuration replace it?
8. [FACT] What additional rules were intended by the missing `RTK.md` imported by the supplied `AGENTS.md`?
