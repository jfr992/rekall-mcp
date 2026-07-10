# How I Work

_Auto-generated from preferences + requirements_

## Preferences (23)

- Harness scripts use 'success is silent, failures are verbose' — zero output on pass, verbose error output on failure. Applied to all script pseudocode and validation logic.
- Juan prefers fresh cluster installs for each test run — affects BSO operator testing strategy and rollback validation approach
- Canonical pack.yaml variable shape across byte-edge charts (byte-edge-sync, byte-edge-api, byte-edge-common all follow it): name, displayName, description (optional), format (always "string"), defaultValue ({{ cluster:* }} or {{ env:* }} or literal), required, hidden, immutable, isSensitive. ALL fields populated explicitly; format: string is universal — no chart omits it. byte-edge-cli pack lint accepts a variable without format, but Spectro rejects the profile at deploy time. When adding a new pack variable, copy the full 9-field shape from an existing one in the same file.

Context: Established pattern verified 2026-05-19 across byte-edge-sync/byte-edge-api (byte-edge-core) and byte-edge-common (helm/) after the cloudMqttOtp omission caused MR-137 follow-up. Treat as a hard rule.
- Juan strongly prefers terse MR descriptions and NO narrative YAML comments in chart values / fixtures — comments belong in commit messages and MR descriptions. Code comments must explain WHY, single-line preferred. Also prefers patch-style chart version bumps (0.10.7 → 0.10.8 → 0.10.9) over jumping to minor with appVersion (i.e. chart 0.10.x stays patch even when appVersion is 0.11.0). Pipeline-affecting MRs (chart values that publish a pack) should NOT have [skip ci]; test-only fixture MRs SHOULD have [skip ci] — but title also needs the [skip ci] marker if commit has it (helm CI parses MR title).

Context: Multiple corrections during BSO MR !28 + helm MR !132 prep on 2026-05-14: removed YAML comments from policy fixtures and chart values, reverted accidental 0.11.0 chart bump back to 0.10.8 then 0.10.9, added/removed [skip ci] based on whether CI needed to run.
- Always run `make test` + relevant `make e2e-*` suites locally before pushing to an MR branch. Do not iterate by pushing speculative fixes and watching CI — each cycle burns 10-15min and clutters the MR history. Exception: changes that ONLY affect CI infrastructure (.gitlab-ci.yml, ci-shim scripts) can't be validated locally — say so explicitly when pushing them and push one at a time so each retry isolates the cause.

Context: Triggered 2026-05-12 during BSO MR !23 e2e prod-parity work: pushed 6+ speculative CI fixes without running anything locally. User called it out: "did you run every test locally? we might need to run this locally and instruct you to always run it before creating MR's."
- Workflow preference: when scope of in-progress work overlaps with an existing open MR, fold the new work into that MR's existing branch instead of spawning a new branch + MR. Don't create parallel MRs for the same chart/version line.
- Don't commit/push docs/superpowers/ planning artifacts (spec + plan files from the brainstorming/writing-plans workflow) to shared production repos like helm/. Reasoning: those are Claude-side scratch work that adds noise for reviewers, has no shared context, and pollutes the chart repo. Keep them in ~/.claude/ or local-only. Override the brainstorming skill's default 'commit the design document to git' step in this kind of repo.
- Two MR description failure modes to avoid: (1) skipping the Claude Code AI signal at the bottom — attribution is enabled and PRs/MRs require the '🤖 Generated with Claude Code' footer, not just the Co-Authored-By trailer in commits. (2) Overlong descriptions — keep MR bodies under ~15 lines, no Follow-ups/marketing/design-link sections, no prose between bullets. The diff is the source of truth; the description is a wayfinder.
- NEVER create spectro_deployment entities or trigger any deployment (Port, Spectro, kubectl, helm) without explicit user authorization. Always describe what you're about to deploy and ask first.
- Always use superpowers brainstorming → writing-plans → executing-plans flow before making code/chart changes, even for "simple" fixes. Juan corrected me for jumping straight to edits on the byte-edge-api ORG_ID fix. Why: simple-looking changes hide design decisions (e.g., hardcoded value vs Spectro variable, which branch to base off, chart version strategy). How to apply: at the start of any non-trivial change, invoke brainstorming skill first; only skip planning for genuinely trivial well-defined tasks (typo fixes, single-line bumps the user explicitly described).
- HARD PREFERENCE — every commit and MR/PR description MUST include AI signals. No exceptions, no skipping on "small" changes.

REQUIRED on every commit message body:
  Co-Authored-By: Claude <noreply@anthropic.com>

REQUIRED at end of every MR/PR description:
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

Apply this BEFORE running `git commit`, BEFORE `git commit --amend`, and BEFORE `glab mr create`. Treat it as a pre-flight check, not a thing to add after Juan reminds. Juan has had to flag this multiple times in one session — it's a habit failure, not a knowledge gap.
- Juan workflow preference: do NOT commit plan/spec/design markdown files to repos — those are working notes that stay local; commits should contain only shipped code (and necessary docs alongside that code).
- When mirroring container images to the GitLab registry, always pull and push the linux/amd64 variant explicitly (using platform-specific digest or --platform linux/amd64). Mac M-series hardware defaults to arm64 pulls — always verify arch before pushing. User preference: amd64 unless explicitly told otherwise.
- User prefers SHORT MR/PR descriptions — bullet-list summary of what changed and why, not multi-section essays. Cut the "Tests" / "Local validation" / "Rollout" subsections unless explicitly asked. Keep Claude Code attribution footer.
- Always include "Generated with Claude Code" / Claude attribution footer on GitLab MR descriptions and PR descriptions. User wants the AI co-authorship visible — corrected me when I stripped it out. Don't omit it just because a previous instruction said "no AI signals" — that referred to in-code comments and commit message attribution clutter, not MR/PR body footers.
- Always confirm before deleting Port entities — even when deletion is part of an approved plan. Show the list of what will be deleted and wait for explicit approval before executing. Why: user was surprised when I deleted 9 pack_[REDACTED] without asking, even though it was in the plan.
- User has `claude-switch` tool at ~/scripts/claude-switcher/bin/claude-switch for toggling between Anthropic Max (personal) and Amazon Bedrock (work/yum) — Bedrock sessions are billed to employer and appear on the GRE AI leaderboard, Max sessions are flat-rate. Switcher validates SSO [REDACTED] from ~/.aws/sso/cache/ (not via AWS CLI which lies with cached IAM creds). Sister scripts: claude-cost, claude-usage. Pricing table in claude-cost is stale (uses Opus 3/4 rates, not 4.6).
- Preference: when Juan says "memory", use Memento MCP (`mcp__memory__save_memory` / `mcp__memory__observe` / `mcp__memory__recall_memories`) — NOT the auto-memory file system at ~/.claude/projects/-Users-.../memory/. Auto-memory files are secondary; Memento is the primary knowledge graph across sessions.
- User preference: when they say "store in memory" or "save memory", use the Memento MCP (mcp__memory__save_memory), NOT the auto-memory local file system. Writing to auto-memory files is a fallback only; default to Memento when the user explicitly asks.
- Keep code comments short and direct — no multi-line explanatory blocks, no "why" essays in comments. If the code is clear, don't comment it.
- MR descriptions should be short and not chatty — brief bullet summary, no prose paragraphs, no lengthy test plans.
- Core MCP servers in daily use: superpowers skills, context7 (library docs), memory MCP, port MCP, gre-graph. These are the keepers in any MCP audit — everything else (excalidraw, playwright unless in mfe work, etc.) is a candidate to drop or scope per-project to cut context overhead.
- User timezone is EST (America/New_York). When creating Port spectro_deployment entities, convert deployment_time from EST to UTC by adding 5 hours. Example: 2:00 PM EST = 19:00:00.000Z UTC.

## Requirements & Hard Rules (4)

- kind-platform harness (helm/test/e2e/kind-platform/run.sh) has 6 phases replicating Spectro install-priority order: Phase 1 (-13 to -11 BSO CRDs + operator), Phase 2 (-10 MinIO/NATS), Phase 3 (-9 MongoDB), Phase 4 (-8 to -6 OTel Operator + HyperDX + OTel Collectors), Phase 5 (50/55 Core), Phase 6 (Assertions). HARD RULE: run harness locally to green (~35-45 min) before opening or merging ANY harness MR. MR !156 was merged untested with Phase 4 observability unvalidated — never again. Phase 4 requires: docker login registry.gitlab.com, OTel Operator from open-telemetry helm chart with admissionWebhooks.certManager.enabled: false + autoGenerateCert.enabled: true, HyperDX clickstack subchart service named byte-hyperdx-clickstack-clickhouse (not parent fullnameOverride), otel-collectors with backends.clickhouse.enabled: true and backends.datadog.enabled: false.
- byte-edge k3s control-plane args for fast node failure detection (Spectro K8s pack values, requires server restart):

Set via Spectro Cluster Profile K8s/k3s pack:
- --kube-controller-manager-arg=node-monitor-period=2s (default 5s — how often the controller polls for missing heartbeats)
- --kube-controller-manager-arg=node-monitor-grace-period=20s (default 40s upstream, MEASURED 280s on current Spectro k3s — how long to wait before flipping Ready→Unknown and applying node.kubernetes.io/unreachable taint)

DEAD FLAGS (do not use — deprecated/ignored since K8s 1.27):
- --pod-eviction-timeout — REMOVED, replaced by per-pod tolerationSeconds via DefaultTolerationSeconds admission plugin

Pod-level tolerationSeconds is the correct knob for eviction speed (already 60s on g5011-v2 workload pods).

Full failover timeline AFTER all tuning (Longhorn + k3s + tolerations):
- t=0: heartbeat stops
- t=20s: Ready→Unknown, NoExecute taint applied
- t=80s: pod eviction (tolerationSeconds=60)
- t=~90s: Longhorn force-deletes via node-down-pod-deletion-policy
- t=~150s: pods rescheduled and mounted on surviving node
Total RTO: ~2.5 min vs current 5m37s + indefinite stuck.

MEASURED CURRENT BEHAVIOR (2026-05-27 on g5011-v2):
- Heartbeat lost at 15:38:35
- Node flipped to NotReady at 15:43:12 (277s = ~4m37s)
- Eviction fired within 30s of NoExecute taint (workload tolerationSeconds=60 already correct, some pods 30s)
- Pods then stuck Terminating indefinitely until Longhorn settings changed

Context: Measured node-failure-detection timing on Spectro k3s edge cluster. Default k3s on Spectro uses ~280s grace period (likely tuned for flaky edge networks but causes 10-min failover). Documents the dead pod-eviction-timeout flag so we don't waste time on it again.
- byte-edge 2-node cluster chart settings (g5011-v2 review 2026-05-27):

byte-minio: ALREADY CORRECT. affinity.podAntiAffinity uses preferredDuringSchedulingIgnoredDuringExecution (soft), replicas: 4, drivesPerNode: 1, mode: distributed (EC:2 = survives 2 drive losses). No change needed.

byte-nats-jetstream: BROKEN on 2-node. Currently topologySpreadConstraints.kubernetes.io/hostname.whenUnsatisfiable: DoNotSchedule with maxSkew: 1. With 3 replicas on 2 nodes, 3rd pod stays Pending forever after node loss. FIX in both values.yaml and values.spectro.yaml: whenUnsatisfiable: ScheduleAnyway, maxSkew: 2. Acceptable tradeoff: all 3 pods may temporarily land on one node during recovery; JetStream R3 quorum (2/3) still satisfied.

byte-mongodb-edge: NO HA POSSIBLE on 2 nodes. MongoDB ReplicaSet requires odd voting members (1, 3, 5). members: 2 is WORSE than members: 1 due to split-brain. KEEP members: 1 for both mongodb-edge and mongodb-hyperdx. Rely on Longhorn 2-replica + node-down-pod-deletion-policy for failover. PDB: minAvailable: 0 to allow node drain. Accept ~30-60s outage during failover, possible last-few-seconds data loss.

byte-edge-api / byte-edge-sync: replicas: 3 in current values.spectro.yaml is WASTEFUL on 2-node — 3rd pod always co-located with one of the other 2. Change replicas: 2 in values.spectro.yaml (keep values.yaml replicas: 1 default). topologySpreadConstraints already correct: whenUnsatisfiable: ScheduleAnyway, maxSkew: 1. PDB maxUnavailable: 1 keeps 1 pod serving during node loss.

Tolerations (already correct, do not change): node.kubernetes.io/not-ready and node.kubernetes.io/unreachable both have tolerationSeconds: 60 on workload pods (measured live, applied by DefaultTolerationSeconds admission plugin).

Context: Chart audit for MinIO, NATS JetStream, MongoDB, edge-api, edge-sync against 2-node topology. NATS topology constraint is the only chart-level bug. MongoDB single-member is honest config (2-node fundamentally can't do MongoDB HA). edge-api/sync over-replicated.
- byte-edge 2-node cluster Longhorn settings (validated on g5011-v2 KFC UK lab, 2026-05-27 after node-disconnect investigation):

REQUIRED Longhorn settings for any 2-node edge cluster (apply via Longhorn pack values.spectro.yaml defaultSettings OR kubectl edit setting.longhorn.io <name> -n longhorn-system):
- default-replica-count: {"v1":"2","v2":"2"} — 1 replica per node, only affects NEW volumes
- node-down-pod-deletion-policy: delete-both-statefulset-and-deployment-pod — auto force-delete pods stuck on down node (was do-nothing, this is THE setting that fixes 32+ pods stuck Terminating)
- node-drain-policy: allow-if-replica-is-stopped — allows failover when last replica is on the draining node
- volume-attachment-recovery-policy: never — auto force-detach volumes from unreachable node (SAFE only with >=2 replicas, DANGEROUS with 1 replica)
- replica-soft-anti-affinity: false — KEEP false, forces replicas onto different nodes
- replica-replenishment-wait-interval: 300 — rebuild after 5 min (default 600 too slow for edge)
- concurrent-replica-rebuild-per-node-limit: 2 — prevents I/O saturation during rebuild
- disable-revision-counter: true — KEEP true, enables auto-salvage
- auto-salvage: true — KEEP true
- allow-volume-creation-with-degraded-availability: true — KEEP true
- default-data-locality: best-effort — keep replica on pod's node when possible
- replica-zone-soft-anti-affinity: true — KEEP true (single-zone tolerance)

CRITICAL: default-replica-count change does NOT propagate to existing volumes. Must patch each volume: kubectl patch volume.longhorn.io <pv> -n longhorn-system --type=merge -p '{"spec":{"numberOfReplicas":2}}'. Do this BEFORE any production deployment.

Context: Discovered 2026-05-27 on kfcuk-byte-edge-g5011-v2 when one of two control-plane nodes was disconnected. 32 pods stuck Terminating, 6 volumes faulted, MinIO/MongoDB unrecoverable because default-replica-count was 1 and the single replica was on the dead node. These settings unblock auto-failover for the next failure. Measured detection time 277s (node-monitor-grace-period default ~280s on Spectro k3s), eviction at +60s (tolerationSeconds already tuned), but pods stayed Terminating forever due to node-down-pod-deletion-policy=do-nothing.
