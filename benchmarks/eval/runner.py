"""Effectiveness-eval orchestrator.

Tiers (spec §Statistics): smoke(50)=deterministic metrics only; Δ-capable(200+);
headline(500). Primary endpoints (α=.025): Δproduct on probes, parity gap on LME.
Everything else exploratory + Benjamini-Hochberg. Never touches prod (env.py refuses).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from benchmarks.dataset import get_ground_truth, load_dataset
from benchmarks.eval import stats
from benchmarks.metrics import precision_at_k

MIN_DELTA_ITEMS = 200
MIN_STRATUM = 10


def arms_for(dataset: str) -> list[str]:
    return ["seeded", "fullcontext", "absent"] if dataset == "longmemeval" else ["seeded", "absent"]


def delta_claim_allowed(n_items: int) -> bool:
    return n_items >= MIN_DELTA_ITEMS


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(records: list[dict], n_items: int) -> dict:
    """records: one per (item, arm, repeat) with keys
    item_id, arm, correct(bool), rekall_payload_tokens(int), question_type(str),
    plus per-item 'precision_at_5' carried on seeded records (repeat 0)."""
    by_arm: dict[str, dict[str, list[float]]] = {}
    for r in records:
        item_accs = by_arm.setdefault(r["arm"], {})
        item_accs.setdefault(r["item_id"], []).append(1.0 if r["correct"] else 0.0)

    def arm_item_means(arm: str) -> dict[str, float]:
        return {i: _mean(v) for i, v in by_arm.get(arm, {}).items()}

    seeded = arm_item_means("seeded")
    accuracy = {arm: _mean(list(arm_item_means(arm).values())) for arm in by_arm}
    seeded_tokens = [r["rekall_payload_tokens"] for r in records if r["arm"] == "seeded"]
    fullctx_tokens = [
        float(r.get("prompt_tokens") or r.get("input_tokens", 0))
        for r in records
        if r["arm"] == "fullcontext"
    ]
    p5 = [r["precision_at_5"] for r in records if r["arm"] == "seeded" and "precision_at_5" in r]

    report: dict = {
        "n_items": n_items,
        "delta_claim_allowed": delta_claim_allowed(n_items),
        "accuracy": accuracy,
        "precision_at_5": _mean(p5),
        "retrieved_context_tokens_per_query": _mean([float(t) for t in seeded_tokens]),
        "primary_endpoints": {},
        "exploratory": {},
    }

    reps = max((len(v) for v in by_arm.get("seeded", {}).values()), default=1)

    for name, baseline_arm in (("delta_product", "absent"), ("parity_gap", "fullcontext")):
        base = arm_item_means(baseline_arm)
        common = sorted(set(seeded) & set(base))
        if not common:
            continue
        diffs = [seeded[i] - base[i] for i in common]
        entry: dict = {"estimate": _mean(diffs), "n": len(common)}
        if name == "parity_gap" and fullctx_tokens and seeded_tokens:
            # the smarter-reads claim: parity gap is only meaningful WITH the token ratio
            entry["token_ratio_fullcontext_over_seeded"] = _mean(fullctx_tokens) / max(
                1.0, _mean([float(t) for t in seeded_tokens])
            )
        if delta_claim_allowed(n_items):
            entry["ci95"] = stats.paired_bootstrap_ci(diffs)
            if reps == 1:
                b = sum(1 for i in common if seeded[i] > base[i])
                c = sum(1 for i in common if base[i] > seeded[i])
                entry["mcnemar_p"] = stats.mcnemar_exact(b, c)
                entry["alpha"] = 0.025
        else:
            entry["warning"] = f"n_items < {MIN_DELTA_ITEMS}: no delta claim (smoke tier)"
        report["primary_endpoints"][name] = entry

    # exploratory: per-type accuracy on the seeded arm, suppressed under MIN_STRATUM
    types: dict[str, list[float]] = {}
    for r in records:
        if r["arm"] == "seeded":
            types.setdefault(r["question_type"], []).append(1.0 if r["correct"] else 0.0)
    report["exploratory"]["per_type_seeded_accuracy"] = {
        t: _mean(v) for t, v in sorted(types.items()) if len(v) >= MIN_STRATUM
    }
    report["exploratory"]["suppressed_strata"] = sorted(
        t for t, v in types.items() if len(v) < MIN_STRATUM
    )

    # exploratory per-type Δproduct p-values, BH-corrected (spec: exploratory = FDR-controlled)
    # Only valid when reps == 1 — with fractional per-item means McNemar is invalid.
    if reps == 1:
        absent = arm_item_means("absent")
        type_of = {r["item_id"]: r["question_type"] for r in records if r["arm"] == "seeded"}
        per_type_p: dict[str, float] = {}
        for t in sorted(set(type_of.values())):
            t_items = [i for i in seeded if i in absent and type_of.get(i) == t]
            if len(t_items) < MIN_STRATUM:
                continue
            b = sum(1 for i in t_items if seeded[i] > absent[i])
            c = sum(1 for i in t_items if absent[i] > seeded[i])
            per_type_p[t] = stats.mcnemar_exact(b, c)
        if per_type_p:
            flags = stats.benjamini_hochberg(list(per_type_p.values()), q=0.10)
            report["exploratory"]["per_type_delta_bh_significant"] = dict(
                zip(per_type_p, flags, strict=False)
            )
    return report


def evaluate(items: list[dict], arms: list[str], deps: dict, repeats: int = 1) -> list[dict]:
    """One pass. deps: backend(EphemeralBackend), run_arm(callable), scorer(callable),
    workspace_root(Path). run_arm(arm, item, cwd) -> RunResult; scorer(item, answer) -> bool."""
    from benchmarks.eval.env import make_workspace

    records: list[dict] = []
    backend = deps["backend"]
    for item in items:
        backend.wipe()
        ws = make_workspace(deps["workspace_root"], item["item_id"])
        idmap = backend.seed(item["seed_memories"], cwd=str(ws))
        retrieved = backend.recall_ids(item["question"], project=ws.name)
        gold_sessions = set(item["gold_session_ids"])
        p5 = precision_at_k([idmap.get(m, m) for m in retrieved], gold_sessions, 5)
        for arm in arms:
            for rep in range(repeats):
                try:
                    out = deps["run_arm"](arm, item, ws)
                except subprocess.TimeoutExpired:
                    # One hung claude -p must not kill a whole (billable) run:
                    # record the cell as a timeout failure and keep going.
                    records.append(
                        {
                            "item_id": item["item_id"],
                            "arm": arm,
                            "repeat": rep,
                            "correct": False,
                            "rekall_payload_tokens": 0,
                            "input_tokens": 0,
                            "prompt_tokens": 0,
                            "question_type": item["question_type"],
                            "timed_out": True,
                        }
                    )
                    continue
                rec = {
                    "item_id": item["item_id"],
                    "arm": arm,
                    "repeat": rep,
                    "correct": deps["scorer"](item, out.answer),
                    "rekall_payload_tokens": out.rekall_payload_tokens,
                    "input_tokens": out.input_tokens,
                    "prompt_tokens": out.prompt_tokens,
                    "question_type": item["question_type"],
                }
                if arm == "seeded" and rep == 0:
                    rec["precision_at_5"] = p5
                records.append(rec)
    return records


def _load_items(args: argparse.Namespace) -> list[dict]:
    if args.dataset == "probes":
        probes = json.loads(Path(args.corpus).read_text())
        return [
            {
                "item_id": p["id"],
                "question": p["question"],
                "question_type": p["question_type"],
                "seed_memories": p["seed_memories"],
                "gold_session_ids": [f"probe:{i}" for i in range(len(p["seed_memories"]))],
                "oracle_regex": p["oracle_regex"],
                "entry": None,
            }
            for p in probes[: args.items or None]
        ]
    data = load_dataset(args.corpus)
    if args.subset:
        keep = set(json.loads(Path(args.subset).read_text()))
        data = [e for e in data if e["question_id"] in keep]
    if args.items:
        data = data[: args.items]
    items = []
    for e in data:
        from benchmarks.dataset import build_session_corpus

        docs = build_session_corpus(e, include_assistant=True)
        items.append(
            {
                "item_id": e["question_id"],
                "question": e["question"],
                "question_type": e["question_type"],
                "seed_memories": [
                    {"summary": d["text"], "type": "fact", "session_id": d["session_id"]}
                    for d in docs
                ],
                "gold_session_ids": sorted(get_ground_truth(e)),
                "oracle_regex": None,
                "entry": e,
            }
        )
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rekall-effectiveness-eval")
    ap.add_argument("--dataset", choices=["longmemeval", "probes"], required=True)
    ap.add_argument("--corpus", required=True, help="dataset json / probes json path")
    ap.add_argument("--items", type=int, default=0)
    ap.add_argument(
        "--subset",
        default=None,
        help="json list of question_ids — the frozen stratified dev subset",
    )
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--agent-model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--judge-provider", choices=["openai", "anthropic"], default="anthropic")
    ap.add_argument("--out-dir", default="benchmarks/eval/results")
    ap.add_argument("--workdir", default="/tmp/claude/rekall-eval")
    args = ap.parse_args(argv)

    from benchmarks.eval import driver, scorers
    from benchmarks.eval.env import EphemeralBackend

    items = _load_items(args)
    if not delta_claim_allowed(len(items)):
        print(f"WARNING: {len(items)} items < {MIN_DELTA_ITEMS} — smoke tier, no Δ/parity claim.")

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    mcp_config = workdir / "seeded.mcp.json"

    with EphemeralBackend(storage_path=workdir / "store") as backend:
        mcp_config.write_text(
            json.dumps(
                # Server mounts MCP at root /, not /mcp — use base_url directly.
                {"mcpServers": {"rekall": {"type": "http", "url": backend.base_url}}}
            )
        )

        def run_arm(arm: str, item: dict, ws: Path):
            if arm == "seeded":
                n = len(item["seed_memories"])
                return driver.run(
                    driver.build_seeded_prompt(
                        item.get("entry") or item,
                        n_memories=n,
                        nodes=n,
                    ),
                    mcp_config,
                    args.agent_model,
                    cwd=ws,
                )
            if arm == "fullcontext":
                return driver.run(
                    driver.build_fullcontext_prompt(item["entry"], include_assistant=True),
                    None,
                    args.agent_model,
                    cwd=ws,
                )
            return driver.run(
                driver.build_question_prompt(item.get("entry") or item),
                None,
                args.agent_model,
                cwd=ws,
            )

        def scorer(item: dict, answer: str) -> bool:
            if item["oracle_regex"]:
                return scorers.oracle(answer, item["oracle_regex"])
            client = _judge_client(args.judge_provider)
            return scorers.judge_answer(
                client,
                item["question_type"],
                item["question"],
                item["entry"]["answer"],
                answer,
            )

        records = evaluate(
            items,
            arms_for(args.dataset),
            {
                "backend": backend,
                "run_arm": run_arm,
                "scorer": scorer,
                "workspace_root": workdir,
            },
            repeats=args.repeats,
        )

    report = aggregate(records, n_items=len(items))
    report["judge_provider"] = args.judge_provider
    if args.judge_provider == "anthropic":
        report["label"] = "Rekall-internal (anthropic judge, uncalibrated) — not mem0-comparable"
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (out / f"eval_{args.dataset}_{stamp}.json").write_text(json.dumps(report, indent=2))
    (out / f"records_{args.dataset}_{stamp}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records)
    )
    print(json.dumps(report, indent=2))
    return 0


def _judge_client(provider: str):
    """Thin adapters. openai = gpt-4o-2024-08-06 (comparable headline); anthropic = dev."""
    if provider == "openai":
        from openai import OpenAI  # optional dep; headline runs only

        client = OpenAI()

        class _OpenAIJudge:
            def complete(self, prompt: str) -> str:
                r = client.chat.completions.create(
                    model="gpt-4o-2024-08-06",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=10,
                )
                return r.choices[0].message.content or ""

        return _OpenAIJudge()

    import subprocess as sp

    class _ClaudeJudge:
        def complete(self, prompt: str) -> str:
            import tempfile
            from pathlib import Path as _Path

            # No --bare (breaks OAuth auth); use empty config + --strict-mcp-config.
            # /dev/null is rejected as "not valid JSON" by the CLI.
            _d = tempfile.mkdtemp(prefix="claude-judge-nomcp-")
            _cfg = _Path(_d) / "empty.json"
            _cfg.write_text('{"mcpServers":{}}')
            import os as _os

            env = {
                "HOME": _os.environ.get("HOME", ""),
                "PATH": _os.environ.get("PATH", ""),
                "USER": _os.environ.get("USER", ""),
                "TMPDIR": _os.environ.get("TMPDIR", ""),
                "LANG": _os.environ.get("LANG", "en_US.UTF-8"),
                "TERM": _os.environ.get("TERM", "xterm-256color"),
                "CLAUDECODE": "1",
                "REKALL_AUTOSAVE": "0",
            }
            try:
                p = sp.run(
                    [
                        "claude",
                        "-p",
                        prompt,
                        "--output-format",
                        "text",
                        "--strict-mcp-config",
                        "--mcp-config",
                        str(_cfg),
                        "--model",
                        "claude-haiku-4-5-20251001",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                    stdin=sp.DEVNULL,
                )
            finally:
                import shutil

                shutil.rmtree(_d, ignore_errors=True)
            if p.returncode != 0:
                raise RuntimeError(
                    f"judge process failed (rc={p.returncode}): {(p.stderr or '')[-300:]}"
                )
            if not p.stdout.strip():
                raise RuntimeError("judge returned empty response")
            return p.stdout

    return _ClaudeJudge()


if __name__ == "__main__":
    raise SystemExit(main())
