# BM25 Vocab Lifecycle — Implementation Plan (rev-2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. One RED per behavior; tdd-guard active.

> rev-2 after two adversarial reviews (independent: APPROVE-WITH-FIXES, 10 findings; Codex: BLOCK, 8 findings + structural). All HIGHs folded in. Biggest changes vs rev-1: encoder math fix is now in scope (asymmetric BM25), a two-phase score contract resolves the ranking-freeze tension, resparse is a fail-closed transaction, and the auto-trigger is DEFERRED (ship safe manual + doctor first).

**Goal:** Make hybrid BM25+dense search correct and maintainable over time. Machinery shipped long ago (encoder, sparse schema, RRF, reindex) but: (a) the IDF vocab freezes at fit time with no refit path short of full reindex, and drift is silent; (b) the encoder applies document-style weighting to queries, so sparse scores are ~IDF² — a live correctness bug; (c) RRF replaces cosine scores with rank-based scores that feed the downstream 0.40-weighted blend, so hybrid-vs-dense changes score semantics, not just coverage.

**Prod evidence (2026-07-17):** vocab frozen Jul 5 (7,222 tokens, headerless); `EdgeHostDeviceAlreadyInUse` and `i-03470c789e7b72080` (Jul 16-17 memories) recall-miss entirely — OOV on both query and point side. Collection HAS the sparse field (rebuilt Jul 5, verified by point sampling); embedded-mode `update_vectors` with named sparse verified working (qdrant-client 1.17.0 local mode).

**Hard constraint shaping everything:** `BM25Encoder.fit()` assigns token IDs by insertion order — refit reassigns IDs, so every point's sparse vector must be rewritten in the same transaction. Incremental vocab append is impossible without a stable-ID redesign (deferred, see bottom).

## Global constraints

- Branch `feat/bm25-vocab-lifecycle` off main. Tests never touch prod (:6334/tmp_path). `tests/test_software_evals.py` stays **byte-identical** — identifier evals live in a new module with their own seeded fixture (adversarial finding: corpus additions perturb frozen scenario rankings).
- Ranking-freeze: resolved by design, not argued around — T2's two-phase score contract keeps downstream `vector_score` cosine-valued in all paths, so hybrid changes candidate **coverage** only. Frozen probes must pass unchanged.
- docker-compose pins Qdrant server 1.13.4 vs client 1.17.0 — never assume server-side transactional behavior for `update_vectors`; design for partial failure.

## Tasks

### T1 — Encoder correctness: asymmetric BM25 + safe persistence
**Files:** `src/core/sparse_encoder.py`, `src/core/vector_store.py`, tests.
Current `encode()` is used for both docs and queries and applies IDF + doc-TF saturation + length normalization on both sides → dot product yields ~IDF² × doc_tf × query_tf (Codex H4, formula-verified against qdrant local sparse dot product).
- Split: `encode_document(text)` (IDF × BM25 TF/length normalization — current behavior) and `encode_query(text)` (term presence with query-TF count, **no IDF, no length normalization** — IDF applied exactly once, on the document side). `encode()` stays as deprecated alias for `encode_document` until call sites migrate.
- `fit()` requires a fresh encoder instance per generation (refitting a reused encoder retains stale terms — Codex M7): raise if vocab non-empty.
- `save()` becomes atomic: same-dir temp file, flush+fsync, `os.replace`.
- RED cycles (formula-level): repeated query terms weight linearly not saturated; doc length affects doc side only; IDF appears once (assert score of known pair against hand-computed BM25); fit-on-nonempty raises; interrupted save leaves old vocab intact.

### T2 — Score contract: RRF for candidates, cosine for scores
**Files:** `src/core/vector_store.py`, tests (incl. existing `test_hybrid_threshold.py` expectations).
Today: sparse leg empty-encode → direct dense (cosine scores); sparse non-empty → RRF (rank-based scores). Downstream blend (`manager.py:1199-1265`) multiplies `vector_score` by 0.40 — two different score spaces feed the same formula (Codex H6).
- Two-phase design: hybrid `query_points` (RRF) selects the fused candidate set with `with_vectors=["" ]` (dense vector returned per hit); store computes cosine(query_vector, point_dense) locally per candidate and returns THAT as `score`. Dense-only path unchanged. One score contract everywhere: cosine.
- Threshold semantics unified: cosine threshold applied post-scoring identically in both paths (fixes the `0.0` vs `None` divergence pinned in `test_hybrid_threshold.py:27-35` — update that test's pins deliberately, with a comment, as part of this task).
- Sparse leg zero-hits (encodable query, no matches): RRF degenerates to dense ranking; with cosine re-scoring the output is then identical to dense-only — RED pins this equivalence.
- RED cycles: hybrid hit scores are cosine-valued (bounded [-1,1], match direct dense for same point); fully-OOV query → byte-identical results to dense path; sparse-zero-hits → same; identifier query pulls a dense-invisible point into candidates (coverage) while its score stays cosine.

### T3 — Transactional `resparse` (fail-closed, manual-only for now)
**Files:** new `src/memory/resparse.py`, `src/memory/manager.py`, `src/server.py`, tests.
Order of operations (both reviews converged on this):
1. **Preflight:** collection schema has `bm25` sparse field (collections created dense-only route to full reindex — Codex missing-item); doctor-style YAML/Qdrant ID parity check — orphan Qdrant points or unreadable YAML → abort before any mutation with remediation message (full reindex).
2. **Exclusive maintenance barrier:** in-process async lock shared by save/update/delete/resparse routes (single-process daemon and embedded tiers make this sufficient; multi-writer URL deployments: resparse refuses unless it can acquire the ownership record exclusively). Snapshot the corpus only AFTER acquiring the barrier; hold until encoder commit.
3. **Sentinel:** write a resparse-generation sentinel (separate from the reindex sentinel — that one demands full reindex to clear). While present: sparse leg disabled (dense-only), doctor reports it. Cleared only after verification.
4. Fit fresh encoder on full corpus — **paginate to exhaustion, no caps** (rev-1's scan-cap language deleted; both reviews flagged it as a correctness contradiction). Corpus text = the exact `embedding_text` the save path sparse-encodes (`representation.py`).
5. `update_vectors` in batches of ~64-100, `wait=True`, idempotent per-batch retry, per-batch accounting; missing-point mid-run → abort (sentinel stays, rerun is the recovery — resparse is derivable, cheap, safe to repeat).
6. **Verify:** points_updated == store.count() (reindex.py:106-110 pattern).
7. Atomic vocab publish (T1 save) WITH `_binding`; swap `manager._sparse_encoder` AND `manager.store.sparse_encoder` inside the barrier; reset `_sparse_vocab_rejected` latch; clear sentinel.
- REST: `POST /api/memory/resparse` (browser guard; no MCP tool — maintenance op like prune_apply).
- Recovery doc: sentinel present → rerun resparse; never hand-delete the marker.
- RED cycles: abort-before-mutation on parity failure; interrupted run (kill between batches) → sentinel holds, sparse disabled, doctor loud, rerun completes and clears; in-process save during resparse blocks on barrier and lands with the NEW vocab; both encoder refs swapped; `update_memory_content` mid-resparse cannot resurrect old-generation sparse (barrier covers it); dense vectors byte-identical after resparse; embedded-lane run of the full transaction.

### T4 — Drift detection + doctor block
**Files:** `src/memory/manager.py`, `src/memory/doctor.py`, tests.
- Signals (OOV alone is insufficient — Codex H5: corpus growth shifts IDF with zero OOV): (a) OOV rate of `embedding_text` tokens over last-50-saves window (persisted beside the vocab, atomic write), (b) corpus count at last fit vs now (>25% growth), (c) vocab age (>7d), (d) fast-flag: any single OOV identifier-shaped token (matches the tokenizer's hyphen/underscore identifier pattern).
- Doctor `bm25` block: vocab age/size/binding, drift signals, sentinel state, schema presence, verdict — **own verdict field surfaced via `notes`, never global `findings`** (global health stays governed by store integrity; contract test pins global status unaffected — independent L9).
- Corrupt vocab file: `enc.load()` failure currently propagates and bricks every save/recall (`manager.py:239` catches only the binding peek — independent M8). Fix: catch, log loud, latch dense-only, doctor reports. RED: corrupt vocab → saves and recalls still work dense-only + doctor finding.
- Drift state resets only after a verified resparse.

### T5 — Identifier evals (new module)
**Files:** NEW `tests/test_identifier_evals.py`; `tests/test_software_evals.py` untouched (byte-identical).
- Fixture seeds ≥ the bootstrap threshold (50 — `manager.py:506-524`; a 17-doc corpus silently never exercises hybrid, Codex M8) or installs a fitted encoder explicitly; test **asserts the sparse leg executed** (not just a hit).
- The lifecycle transition test (the behavior this PR ships): fit vocab → save identifier memory (token OOV, drift window records it) → recall misses → resparse → recall hits. Plus dense-only fallback separately.
- Frozen probes suite: no-regression gate.

### T6 — Docs
- README: resparse endpoint row. TUNING: vocab lifecycle (why refit = full sparse rewrite; drift signals; recovery). CLAUDE.md: fix the stale "BM25 lives on feat/hybrid-search-bm25" pitfall row (hybrid is on main; rglob already fixed); add pitfall rows: "vocab refit reassigns token IDs — resparse is transactional, never partial" and "encode_query vs encode_document — IDF once, doc side only".
- PR body: state the deliberate T1 score change (sparse scores were ~IDF²; identifier eval deltas expected on the sparse leg).

### T7 — Gates (controller)
- Both py lanes + ui lane + wheel + ruff **format** + docs-parity (last PR failed CI on format — check it locally this time).
- Live: tarball backup; `POST /api/memory/resparse` against prod; verify: binding stamped, both prod identifier misses flip to HIT in top-3, frozen-probe spot checks unchanged, doctor bm25 block healthy, drift window reset; kill-and-rerun once mid-resparse on a COPY of prod data (scratch collection) to prove the sentinel path before touching prod.
- PR with before/after identifier-recall table + both adversarial verdicts linked.

## Deferred (with reason)
- **Auto-resparse trigger** — both reviews called it premature (races + the compact.py asyncio pitfall class); manual endpoint + loud doctor covers current save cadence. Revisit with operating data: if drift recurs unattended for two weeks, add a trigger using T4's signals via a thread (`run_in_executor`), never a bare asyncio task in the sync save path.
- **Stable token IDs (hash-based, bm42-style)** — would make refit incremental and kill the transaction entirely; touches every stored sparse vector once. Revisit at >50k memories or if resparse duration ever exceeds the barrier-hold tolerance.
- **fastembed SparseTextEmbedding swap** — loses the identifier-preserving tokenizer that is the whole point.
