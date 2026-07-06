# Rekall Effectiveness Eval

Measures whether Rekall is an effective memory system: `precision@5`,
LongMemEval `accuracy` (replicated judge), `retrieved_context_tokens/query`
(cl100k, memory payload only), and causal deltas (Δproduct on probes,
parity gap vs full-context on LongMemEval). Design:
`docs/superpowers/specs/2026-07-05-effectiveness-eval-design.md` (local).

## Never touches prod

Backend `:8010` → test Qdrant `:6334` + temp storage. `env.py` refuses
`:6333` / `~/.claude/memory`. All arms run `claude -p --strict-mcp-config`.

## Run tiers

| Tier | Command | Claims allowed | Cost |
|------|---------|----------------|------|
| smoke | `--dataset probes --corpus benchmarks/eval/probes/core.frozen.json` | deterministic metrics only | ~$0.3 |
| probes Δ | same + `--repeats 3` | Δproduct (16 items — directional, CI wide) | ~$3-5 |
| Δ-capable | `--dataset longmemeval --items 200` | parity gap + Δproduct | ~$30-40 |
| headline | `--dataset longmemeval --items 500 --judge-provider openai` | mem0-comparable accuracy | ~$60-90 |

```bash
docker compose up qdrant-test -d
uv run python -m benchmarks.eval.runner \
  --dataset probes --corpus benchmarks/eval/probes/core.frozen.json --repeats 3
```

## Frozen dev subset

`probes/lme_dev_subset.frozen.json` — 199 question_ids, stratified by type, seed=42.
Regenerate from the downloaded dataset:

```bash
uv run python scripts/gen_lme_dev_subset.py
```

Use for reproducible Δ-capable runs:

```bash
uv run python -m benchmarks.eval.runner \
  --dataset longmemeval \
  --corpus benchmarks/data/longmemeval_s_cleaned.json \
  --subset benchmarks/eval/probes/lme_dev_subset.frozen.json
```

## Honesty labels

- Retrieval mode on `main` = **dense** (no BM25 vocab on fresh storage;
  `sparse_encoder=None` → dense path). The published number says so.
- `--judge-provider anthropic` (default) = Rekall-internal, NOT mem0-comparable.
  The comparable headline requires `openai` (gpt-4o-2024-08-06, the published
  LongMemEval judge, 5 verbatim type templates).
- `n_items < 200` → report carries `delta_claim_allowed: false`. Respect it.
- Reliability: before quoting a Δ, re-run the same config and check
  `stats.run_to_run_unreliable(acc1, acc2, target_delta)` — True means the
  run-to-run noise swamps the effect; don't quote it.
- Live tests: `pytest -m eval_live` (real `claude -p`, costs money, off CI).
- `driver.run()` forces `ENABLE_TOOL_SEARCH=1` in the child env — with the operator's `auto:0` user setting, 26 of 28 rekall tools would be deferred and `recall_memories` unreachable; the eval requires the full tool surface. This is a machine-config-sensitive knob.
- Hooks are NOT suppressed (`--bare` breaks Keychain OAuth; not used). User hooks fire SYMMETRICALLY in all arms; the rekall hooks specifically are disabled via `REKALL_AUTOSAVE=0` in the child env. Symmetric residue does not bias the arm deltas.
