# Dense Representation Fix — Spec (rev 2, post-adversarial)

**Date:** 2026-07-09
**Status:** rev 2 — adversarial pass done (1 full independent report; Codex wedged after 3h, one finding salvaged from its log: the `tests/test_performance.py` ≥0.4 default-threshold pin). Control experiments run.
**Trigger:** pre-registered escalation clause fired — probes show target unreachable under current representation.

## Rev-2 adjudication (what the red-team + control data changed)

| Finding | Ruling |
|---|---|
| [CRIT] Spec never traced which score 0.45 gates. Actual mechanism: hybrid mode applies the threshold ONLY to the dense Prefetch cosine, pre-RRF (`vector_store.py:326`); BM25 leg unthresholded; fused `score` is RRF rank-based; composite has NO threshold. Fresh installs (no `_bm25_vocab.json`) take a dense-only path where the threshold gates final cosine — two score semantics. | Accepted. Mechanism section corrected. The offline cosine tables validate the prefetch gate only. pr probes passed exactly when the BM25 leg rescued them — supports the dilution diagnosis. |
| [CRIT] Skipped the cheapest experiment: threshold-only control, no migration. | **Run. Decisive**: 0.35 default, current representation → seeded 93.8% vs 70.8% at 0.45 (er 12/12, ku 9/9, tm 8/9, pr 7/9, xp 9/9). The gate was suppressing every family. Phase restructured to two steps: threshold first, representation as hardening. |
| [Codex, salvaged] `tests/test_performance.py::test_default_threshold_is_reasonable` pins default ≥ 0.4 ("too low" guard). | 0.40 arm measured before choosing (see decision record below). Changing a quality pin in the same PR it guards requires the control data as justification if 0.35 wins materially. |
| [HIGH] Missed consumer: `freshness.py` conflict detection (theta=0.9) is calibrated to stored-vs-stored embedding_text cosines — variant A silently regresses conflict groups / outdated stubs / superseded-prune (last week's shipped feature). | Step 2 scope: measure stored-vs-stored distribution under A on the conflict-pair corpus, recalibrate theta, keep the freshness pytest suite green + ku/tm probes as the behavioral gate. |
| [HIGH] `linker.py` bands (0.5 similar / 0.6 contradiction / 0.6–0.9 supersedes) calibrated under old distribution; `knowledge_graph.py:408` rebuild passes embedding_text into auto_link. | Step 2 scope: recalibrate bands with measured pair distributions; flip the rebuild call-site to content. |
| [HIGH] Migration plan as drafted (recreate + rebuild-from-YAML) violates two contracts: Qdrant-only fields (reinforcement_count, promoted tiers — identity demotion) and compacted-memory resurrection. Health check would pass anyway. | Migration inverted: scroll Qdrant WITH payloads (source of truth), re-encode `payload["content"]`, upsert in place (`content=embedding_text` for sparse), stamp `repr_version: 2` for idempotent resume. Tarball before; `/health` + count + spot recalls after; plus assert zero identity-tier demotions and zero compacted resurrections. |
| [MED] `sync.py:237,264` already encodes raw content (pre-existing instance of this bug class) and saves without `content=` → wipes sparse vectors. | Fixed in Step 2 (becomes consistent under A; add `content=`). |
| [MED] Dedupe `_find_duplicate_memory_id` (0.97 band, dense prefetch only): under A, must query with content not embedding_text or the dense leg goes blind. Cross-project collision risk checked by test. | Step 2: flip search text to content; add cross-project dedupe regression test (same content, different project must NOT reinforce). |
| [LOW] Graph-expanded results enter at score 0.0 and skip the threshold; lower gate widens the expansion frontier. | Accepted as monitored risk — probes gate covers end-to-end; no code change. |
| B (query symmetrization) | Refuted by measurement (margin 0.225 < current 0.278). Dead. |
| C (trimmed) | Dominated by A on every aggregate. Dead. |

## Decision record

- **Step 1 (ship first): recall default `score_threshold` 0.45 → 0.35.** Both arms measured, 3 repeats each, current representation: 0.35 → **93.8%** seeded (er 12/12, ku 9/9, tm 8/9, pr 7/9, xp 9/9); 0.40 → 75.0% (pr collapses to 2/9). The live correct-cosine band sits between 0.35 and 0.40 — the `test_performance.py` ≥0.4 pin guards a value the data refutes; pin moves to ≥0.35 citing this record. Residual risk (negative-query false positives at a zero-margin gate) is accepted short-term and retired by Step 2's measured gap.
- **Step 2 (hardening, separate PR): variant A** — dense = `encode(content)`, embedding_text stays for BM25 + payload. Owns: margin (measured gap 0.434/0.357 vs zero-margin threshold-only), pr-01 residual retrieval miss (precision 0.0 even at 0.35), and the bug-class fix. Carries the full consumer/calibration scope above.

## Evidence (measured 2026-07-09)

Dense vectors embed `embedding_text` = `"Project {p}. Type {t}. Tier {tier}. Repository {r}. Entities: {e}. Claim: {content}"`. Measured cosine (all-MiniLM, prod embedder) question-vs-stored:

| probe | q vs raw content | q vs embedding_text | dilution |
|---|---|---|---|
| er-01 | 0.681 | 0.448 | −0.233 |
| ku-01 | 0.644 | 0.445 | −0.199 |
| tm-01 | 0.634 | 0.467 | −0.167 |
| pr-01 | 0.472 | 0.354 | −0.118 |
| pr-02 | 0.452 | 0.339 | −0.113 |

- `score_threshold=0.45` sits mid-band: every family operates within ~0.05 of the cutoff → gate-run wobble (tm 7/9→4/9 across runs) and pr hard-misses (precision@5 = 0.0 with a corpus of ONE memory).
- Third occurrence of this bug class: PR #38 (auto_link encoded content vs stored embedding_text — dead SUPERSEDES path), zero-vector search floor, now recall dilution.

## Decision fork 1 — what does the dense vector encode?

- **A. Raw content only.** `vector = encode(content)`. embedding_text retained solely as BM25 sparse input + payload field. Max dilution removal; loses entity/project semantic anchoring in dense space (BM25 keeps lexical). Requires full re-embed migration.
- **B. Query-side symmetrization.** Store side unchanged; wrap queries in the same boilerplate shape. No migration, cheap, reversible. Risk: boilerplate still dominates both sides — similarity between boilerplates inflates scores uniformly (may compress discrimination rather than improve it).
- **C. Trimmed representation.** `"Entities: {e}. Claim: {content}"` — drop project/type/tier/repository (pure noise for semantic match; they're payload filters anyway), keep entities (identifier anchoring). Partial dilution removal; still a migration.

### Offline decision data (measured, all 16 probes, 15-distractor separation)

| variant | mean cosine (correct) | min (correct) | mean margin vs best distractor | rank-1 |
|---|---|---|---|---|
| current (full boilerplate) | 0.513 | 0.352 | 0.278 | 16/16 |
| **A raw content** | **0.653** | **0.434** | **0.404** | 16/16 |
| C trimmed (Entities+Claim) | 0.610 | 0.397 | 0.356 | 16/16 |
| B query-symmetrized | 0.852 (inflated) | 0.735 | **0.225 — worse than current** | 16/16 |

B is refuted by measurement: wrapping both sides in identical boilerplate inflates ALL scores (correct and distractor alike) and compresses discrimination below the status quo. A dominates C on every aggregate.

Threshold-placement data under A: correct min 0.434, distractor max 0.357, p95 0.256. A threshold of **0.40** sits in the measured gap with margin on both sides (current 0.45 would still guillotine pr-03 at 0.434).

**Provisional recommendation (pre-adversarial):** fork 1 = A, fork 2 = lower threshold to 0.40 (empirically placed in the measured correct/distractor gap; re-verify placement post-migration on the live corpus distribution).

## Decision fork 2 — score_threshold

Keep 0.45, lower, or recalibrate empirically after re-embed (measure the new score distribution over the probes corpus, place threshold at measured separation point). Recalibration must be data-derived, not vibes.

## Consumers that must stay consistent (audit list)

1. `manager.recall` — `encode(query)` vs stored vector.
2. `_find_duplicate_memory_id` (save-time dedupe) — queries with embedding_text today; must query with whatever the doc side stores or dedupe silently degrades (cosine ≥0.97 reinforcement band).
3. `auto_link` — same-representation search (the #38 fix); must follow.
4. `update_memory_content` — rebuilds embedding_text + re-encodes (shipped today; follows the builder).
5. BM25 sparse (`content=` param to `store.save`) — decision: keep embedding_text (lexical entity/project matching) regardless of dense choice.
6. `migrate_hybrid.py` — re-embed path for the migration; rglob (nested layout).

## Migration safety (fork 1 = A or C)

- Tarball memory + qdrant BEFORE (CLAUDE.md discipline).
- Re-embed all ~770 via migrate path; verify: count unchanged, `/health` zero_vectors 0/256, spot-check recall.
- Two prior zero-vector incidents were migration/write-path related — the health check is non-negotiable.

## Constraints

- Frozen probes corpus (16) — not edited, must not regress er/ku/tm/xp while lifting pr.
- Ranking WEIGHTS stay frozen (0.40/0.20/0.10/0.15/0.15) — representation is upstream of scoring, threshold is a retrieval gate not a weight. Adversaries: attack this boundary claim.
- Gate: probes 3-repeat run — pr ≥ 6/9 target, no other family below its noise band (er+xp ≥15/21, ku+tm ≥12/18).

## Out of scope

Embedding model swap, weight changes, BM25 fusion changes, new metrics.
