# Benchmarks

End-to-end effectiveness numbers for Rekall's memory pipeline. Every number below
comes from a result file committed in [`benchmarks/eval/results/`](benchmarks/eval/results/)
— nothing is quoted that you can't recompute from the JSONLs. That includes the
workload we lose on ([see below](#where-rekall-loses-longmemeval-raw-conversations)).

The harness ([`benchmarks/eval/`](benchmarks/eval/)) runs three arms per item:
**seeded** (memories saved, agent recalls via MCP), **fullcontext** (entire corpus
pasted into the prompt — the ceiling), and **absent** (no memory at all — the
no-leak control). The agent is `claude -p` (Haiku); answers are scored by an LLM
judge. Metrics: end-to-end answer accuracy, precision@5, and retrieved context
tokens per query (cl100k, memory payload only).

## Headline results

Dev-probes: 16 frozen probes ([`core.frozen.json`](benchmarks/eval/probes/core.frozen.json)),
5 families (exact-recall, preference, temporal, knowledge-update, cross-project),
3 repeats = 48 trials per run.

| Metric | v1.9 (threshold 0.45) | v1.10 (three runs) | Evidence |
|---|---|---|---|
| Seeded accuracy | 70.8% (34/48) | **87.5% / 91.7% / 95.8%** | [v1.9](benchmarks/eval/results/ctx-noregress/), [release](benchmarks/eval/results/v1.10.0-release/), [combo-gate-clean](benchmarks/eval/results/combo-gate-clean/), [final-gate](benchmarks/eval/results/final-gate/) |
| Probes with precision@5 = 0 (retrieval misses) | 3 (pr-01, pr-02, tm-02) | **0 across all three runs** | same records |
| Absent-arm accuracy (no-leak control) | 0/48 | 0/48, 0/48, 1/48* | same records |
| Retrieved context tokens/query | ~39 | ~48–53 | same summaries |

*One absent-arm trial in [`final-gate`](benchmarks/eval/results/final-gate/) (tm-01)
was judged correct with zero memory context — an LLM-judge false positive, not a
leak (the probe corpus is wiped per item). That's the judge's noise floor; we
report it rather than round it away.

**Why a band and not one number:** retrieval in v1.10 is deterministic — zero
precision@5 = 0 misses in all three runs — so the 87.5–95.8% spread is entirely
`claude -p` agent behavior plus LLM-judge stochasticity at n=48 trials/run. Wilson
95% CI at n=48 is roughly ±9pp; treat the band, not any single run, as the result.

Token economics (measured on the LongMemEval-200 workload, same records as the
loss below): **~1,011 tokens/query seeded vs 104,352 full-context — 103× cheaper.**

## The threshold experiment

The single dominant fix in v1.10. Three arms, same code, same frozen probes,
3 repeats each — only `score_threshold` changes:

| `score_threshold` | Seeded accuracy | Evidence |
|---|---|---|
| 0.45 (v1.9 default) | 70.8% | [`ctx-noregress/`](benchmarks/eval/results/ctx-noregress/) |
| 0.40 | 75.0% | [`threshold-040-arm/`](benchmarks/eval/results/threshold-040-arm/) |
| **0.35 (v1.10 default)** | **93.8%** | [`threshold-035-control/`](benchmarks/eval/results/threshold-035-control/) |

The 0.45 gate sat mid-band on the live cosine distribution — every probe family
operated within ~0.05 of the cutoff, so runs wobbled and preference probes
hard-missed (precision@5 = 0.0 against a corpus of one memory). At 0.40 the
preference family still collapses (2/9). Full decision record, including the
adversarial review that forced the control experiment:
[`docs/specs/2026-07-09-dense-representation-fix.md`](docs/specs/2026-07-09-dense-representation-fix.md).

## Representation v2

The threshold fix worked because the old dense representation had no margin to
give. v1 encoded a boilerplate-wrapped string (`"Project X. Type Y. Tier Z. ...
Claim: {content}"`); the boilerplate diluted question-vs-memory cosine by up to
0.233. v2 encodes raw content.

Measured offline on all 16 probes × 15 distractors (spec above, "Offline decision
data"):

| Representation | Min cosine (correct) | Max cosine (best distractor) | Margin |
|---|---|---|---|
| v1 (boilerplate) | 0.352 | — | 0.278 mean vs best distractor |
| **v2 (raw content)** | **0.434** | **0.357** | positive worst-case gap |

Under v2 the worst correct memory (0.434) scores above the best distractor
(0.357) — the threshold sits in a measured gap instead of guillotining live
traffic. Two alternatives (query-side symmetrization, trimmed boilerplate) were
measured and refuted; the spec has the tables.

## Where rekall loses: LongMemEval raw conversations

**Rekall loses badly on raw-conversation needle recall.** LongMemEval-200
(stratified 200-question dev subset, [`lme_dev_subset.frozen.json`](benchmarks/eval/probes/lme_dev_subset.frozen.json),
four 50-item runs pooled):

| Arm | Accuracy | Tokens/query |
|---|---|---|
| Seeded (rekall) | **8.5%** | 1,011 |
| Full-context | **38.0%** | 104,352 |
| Absent | 1.0% (2/200)* | — |

Deficit: **−29.5pp**, paired bootstrap ci95 [−36.5, −22.0], exact McNemar
p = 4×10⁻¹³, precision@5 = 0.119. Raw records:
[`benchmarks/eval/results/lme-200/`](benchmarks/eval/results/lme-200/).
(*Same judge false-positive floor as the probes absent arm.)

Why: rekall distills at save time — an LLM judge extracts durable claims from
sessions. It is **not a verbatim conversation archive**. LongMemEval asks for
incidental details ("what color shirt did I mention in session 12?") that the
distiller correctly discards, so no retrieval threshold can recover them.
These runs predate v1.10 (2026-07-07/08); the threshold fix doesn't change the
structural cause. Verbatim-first systems (MemPalace's thesis) win this domain.

The positioning, stated plainly: rekall is **distilled SWE-agent memory at ~1% of
full-context token cost** — decisions, preferences, incident learnings across
sessions and projects. If you need raw-transcript needle recall, use a verbatim
archive; today that is out of rekall's design scope.

(Retrieval-only R@5 on LongMemEval-500 — a different, retrieval-not-QA metric
where rekall scores 96.6–97.6% — is documented separately in
[`benchmarks/README.md`](benchmarks/README.md). Don't conflate the two.)

## Hybrid identifier recall (2026-07-17)

Hybrid BM25+dense became the default product recall path with the vocab-lifecycle
work (PRs #69–#71): asymmetric encoder (the shipped symmetric one scored ~IDF²),
cosine score contract, transactional `resparse`, drift surfaced in the doctor.

Live prod evidence, before/after the vocab refit + fixes — exact-token queries
whose memories existed but were invisible to dense-only recall:

| Query (exact token) | Before | After |
|---|---|---|
| `EdgeHostDeviceAlreadyInUse` (error class) | MISS | HIT rank 5 |
| `i-03470c789e7b72080` (instance ID) | MISS (0 results) | HIT rank 2 |
| Dense spot-checks (metallb, task_hint, packValuesFrom) | HIT | HIT (unchanged) |

Honesty note: it took **three** live-gate rounds after a fully green suite
(1118 tests, two adversarial plan reviews) to reach HIT — a prod-leaked orphan
point caught by resparse's parity preflight, a cosine floor that killed
sparse-rescued hits (the eval had searched with non-production parameters),
and the frozen blend weights cutting the low-cosine exact match (fixed with a
reserved final-cut slot, weights untouched). Frozen probes and the
`test_software_evals.py` corpus were byte-identical throughout. The
identifier-class regression suite is `tests/test_identifier_evals.py`.

## Methodology & honesty rules

- **Frozen corpus.** The 16 probes are frozen and may not be edited in the same
  PR as ranking/routing changes (except to add scenarios) — enforced as a repo
  rule in [`CLAUDE.md`](CLAUDE.md). You can't tune the test to the fix.
- **Per-item isolation.** Every item gets a wiped Qdrant collection and empty
  temp storage ([`env.py`](benchmarks/eval/env.py)); the harness refuses to run
  against production ports/paths.
- **Absent arm on every run.** No-memory control; anything above ~0 is judge
  noise or a leak, and we publish it either way.
- **Judge label.** All numbers here use the Anthropic judge and carry the label
  `Rekall-internal (uncalibrated) — not mem0-comparable`. A mem0-comparable
  headline requires the published LongMemEval judge (gpt-4o) — we have not run
  it, so we don't quote one.
- **Smoke-tier discipline.** n < 200 items ⇒ the report is stamped
  `delta_claim_allowed: false` and we make no Δ claims from it — the probes
  numbers above are per-arm accuracies, not causal deltas. The LME-200 deficit
  is the only stat-tested Δ in this document.
- **Run-to-run reliability.** Before quoting any Δ, the same config is re-run and
  checked with `stats.run_to_run_unreliable()`; the probes band exists because we
  did this and the noise is real.

## Reproducing

Everything runs against the isolated test Qdrant on `:6334` — production data
untouched. The harness spends real API money (`claude -p` + judge).

```bash
docker compose up qdrant-test -d
```

**Dev-probes, 3 repeats (any row of the probes tables above; ~$3–5):**

```bash
uv run python -m benchmarks.eval.runner \
  --dataset probes --corpus benchmarks/eval/probes/core.frozen.json --repeats 3
```

To reproduce a specific threshold arm, set `score_threshold` in
`src/memory/manager.py` to the arm's value first (0.35 is the shipped default).

**LongMemEval-200 (the loss table; ~$30–40, needs the dataset):**

```bash
bash benchmarks/download_data.sh
uv run python -m benchmarks.eval.runner \
  --dataset longmemeval \
  --corpus benchmarks/data/longmemeval_s_cleaned.json \
  --subset benchmarks/eval/probes/lme_dev_subset.frozen.json
```

**Retrieval-only R@5 (no LLM, free):** see [`benchmarks/README.md`](benchmarks/README.md).

Outputs land in `benchmarks/eval/results/` as `eval_*.json` (summary) +
`records_*.jsonl` (per-trial). The committed evidence dirs referenced above are
exactly these files, unedited.
