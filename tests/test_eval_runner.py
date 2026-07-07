"""Runner: arm selection, tier guardrails, aggregation with fake deps."""

import argparse
import json

import pytest
from benchmarks.eval.runner import arms_for, delta_claim_allowed


def test_arms_for_dataset():
    assert arms_for("longmemeval") == ["seeded", "fullcontext", "absent"]
    assert arms_for("probes") == ["seeded", "absent"]


def test_delta_claim_gate():
    assert delta_claim_allowed(200) is True
    assert delta_claim_allowed(199) is False


def test_aggregate_computes_primaries_and_suppresses_small_strata():
    from benchmarks.eval.runner import aggregate

    records = []
    for i in range(250):
        item = f"q{i}"
        qtype = "multi-session" if i < 241 else "rare-type"
        seeded_ok = i % 10 < 8  # 80%
        absent_ok = i % 10 < 3  # 30%
        records.append(
            {
                "item_id": item,
                "arm": "seeded",
                "correct": seeded_ok,
                "rekall_payload_tokens": 1500,
                "question_type": qtype,
                "precision_at_5": 0.4,
            }
        )
        records.append(
            {
                "item_id": item,
                "arm": "absent",
                "correct": absent_ok,
                "rekall_payload_tokens": 0,
                "question_type": qtype,
            }
        )
    rep = aggregate(records, n_items=250)
    assert rep["delta_claim_allowed"] is True
    dp = rep["primary_endpoints"]["delta_product"]
    assert dp["estimate"] == pytest.approx(0.5, abs=1e-9)
    lo, hi = dp["ci95"]
    assert lo > 0.4 and hi < 0.6
    assert dp["mcnemar_p"] < 0.001
    assert rep["precision_at_5"] == pytest.approx(0.4)
    assert rep["retrieved_context_tokens_per_query"] == pytest.approx(1500.0)
    assert "rare-type" in rep["exploratory"]["suppressed_strata"]


def test_evaluate_loop_with_fakes(tmp_path):
    from benchmarks.eval.runner import evaluate

    class FakeBackend:
        def wipe(self): ...

        def seed(self, memories, cwd):
            return {f"mem{i}": m.get("session_id", f"probe:{i}") for i, m in enumerate(memories)}

        def recall_ids(self, query, project, limit=5):
            return ["mem0"]

    class FakeOut:
        answer = "port 9741"
        rekall_payload_tokens = 42
        input_tokens = 900
        prompt_tokens = 0

    items = [
        {
            "item_id": "er-01",
            "question": "port?",
            "question_type": "exact-recall",
            "seed_memories": [{"summary": "proxy on 9741", "type": "decision"}],
            "gold_session_ids": ["probe:0"],
            "oracle_regex": "9741",
            "entry": None,
        }
    ]
    records = evaluate(
        items,
        ["seeded", "absent"],
        {
            "backend": FakeBackend(),
            "run_arm": lambda arm, item, ws: FakeOut(),
            "scorer": lambda item, ans: "9741" in ans,
            "workspace_root": tmp_path,
        },
    )
    assert len(records) == 2
    seeded = next(r for r in records if r["arm"] == "seeded")
    assert seeded["correct"] is True and seeded["precision_at_5"] == 1 / 5


def test_aggregate_smoke_tier_blocks_delta_claim():
    from benchmarks.eval.runner import aggregate

    records = [
        {
            "item_id": "q0",
            "arm": "seeded",
            "correct": True,
            "rekall_payload_tokens": 100,
            "question_type": "multi-session",
            "precision_at_5": 1.0,
        },
        {
            "item_id": "q0",
            "arm": "absent",
            "correct": False,
            "rekall_payload_tokens": 0,
            "question_type": "multi-session",
        },
    ]
    rep = aggregate(records, n_items=1)
    assert rep["delta_claim_allowed"] is False
    assert "warning" in rep["primary_endpoints"]["delta_product"]
    assert "ci95" not in rep["primary_endpoints"]["delta_product"]


def test_aggregate_no_per_type_mcnemar_when_repeats_gt_1():
    """Records with 2 repeats per item produce fractional per-item means.
    McNemar is only valid for binary outcomes, so per_type_delta_bh_significant
    must be absent from the report when reps > 1."""
    from benchmarks.eval.runner import aggregate

    records = []
    for i in range(200):
        item = f"q{i}"
        for _ in range(2):
            records.append(
                {
                    "item_id": item,
                    "arm": "seeded",
                    "correct": bool(i % 2),
                    "rekall_payload_tokens": 100,
                    "question_type": "multi-session",
                }
            )
            records.append(
                {
                    "item_id": item,
                    "arm": "absent",
                    "correct": False,
                    "rekall_payload_tokens": 0,
                    "question_type": "multi-session",
                }
            )
    rep = aggregate(records, n_items=200)
    assert "per_type_delta_bh_significant" not in rep["exploratory"], (
        "per_type McNemar must be suppressed when repeats > 1 (fractional means)"
    )


def test_aggregate_uses_prompt_tokens_for_fullcontext_ratio():
    """aggregate() must use prompt_tokens (pasted haystack) for the fullcontext
    token ratio, not input_tokens (haystack + system prompt).
    Falls back to input_tokens when prompt_tokens is absent or zero."""
    from benchmarks.eval.runner import aggregate

    records = []
    for i in range(200):
        item = f"q{i}"
        records.append(
            {
                "item_id": item,
                "arm": "seeded",
                "correct": True,
                "rekall_payload_tokens": 50,
                "question_type": "multi-session",
                "precision_at_5": 1.0,
            }
        )
        records.append(
            {
                "item_id": item,
                "arm": "absent",
                "correct": False,
                "rekall_payload_tokens": 0,
                "question_type": "multi-session",
            }
        )
        records.append(
            {
                "item_id": item,
                "arm": "fullcontext",
                "correct": True,
                "rekall_payload_tokens": 0,
                "question_type": "multi-session",
                "input_tokens": 9000,  # haystack + system prompt — must NOT be used
                "prompt_tokens": 8000,  # pasted haystack only — must be used
            }
        )
    rep = aggregate(records, n_items=200)
    pg = rep["primary_endpoints"]["parity_gap"]
    assert pg["token_ratio_fullcontext_over_seeded"] == pytest.approx(8000.0 / 50.0, rel=1e-6)

    # Fallback: when prompt_tokens is absent, use input_tokens
    records_no_pt = [{k: v for k, v in r.items() if k != "prompt_tokens"} for r in records]
    rep2 = aggregate(records_no_pt, n_items=200)
    pg2 = rep2["primary_endpoints"]["parity_gap"]
    assert pg2["token_ratio_fullcontext_over_seeded"] == pytest.approx(9000.0 / 50.0, rel=1e-6)


def test_lme_assistant_turns_in_seeded_and_fullcontext(tmp_path):
    """F1 regression: build_session_corpus(e) defaulted include_assistant=False,
    making single-session-assistant questions structurally unanswerable in the
    seeded arm and the fullcontext arm."""
    from benchmarks.eval.driver import build_fullcontext_prompt
    from benchmarks.eval.runner import _load_items

    GOLD = "unicorn_token_42"  # only in an assistant turn

    entry = {
        "question_id": "q-assist-01",
        "question_type": "single-session-assistant",
        "question": "What is the special token?",
        "haystack_sessions": [
            [
                {"role": "user", "content": "Tell me a special token."},
                {"role": "assistant", "content": f"The token is {GOLD}."},
            ]
        ],
        "haystack_session_ids": ["sess-01"],
        "haystack_dates": ["2024-01-01"],
        "answer_session_ids": ["sess-01"],
        "answer": GOLD,
    }
    corpus = tmp_path / "data.json"
    corpus.write_text(json.dumps([entry]))

    args = argparse.Namespace(dataset="longmemeval", corpus=str(corpus), subset=None, items=0)
    items = _load_items(args)
    assert len(items) == 1

    seed_texts = " ".join(m["summary"] for m in items[0]["seed_memories"])
    assert GOLD in seed_texts, (
        f"Assistant turn absent from seeded corpus; '{GOLD}' not in {seed_texts!r}"
    )

    fc = build_fullcontext_prompt(items[0]["entry"], include_assistant=True)
    assert GOLD in fc, f"Assistant turn absent from fullcontext prompt; '{GOLD}' not in prompt"


def test_claude_judge_raises_on_nonzero_exit(monkeypatch):
    """F3a: _ClaudeJudge.complete() must raise RuntimeError (with stderr) on rc!=0."""
    import subprocess

    from benchmarks.eval.runner import _judge_client

    class _FailResult:
        returncode = 1
        stdout = ""
        stderr = "auth failure: token expired" * 20  # >300 chars

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FailResult())

    judge = _judge_client("anthropic")
    with pytest.raises(RuntimeError) as exc_info:
        judge.complete("Is this answer correct? Yes or No.")
    assert "auth failure" in str(exc_info.value), (
        f"RuntimeError should include stderr text; got: {exc_info.value}"
    )


def test_claude_judge_raises_on_empty_stdout(monkeypatch):
    """F3b: _ClaudeJudge.complete() must raise RuntimeError on empty stdout."""
    import subprocess

    from benchmarks.eval.runner import _judge_client

    class _EmptyResult:
        returncode = 0
        stdout = "   \n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _EmptyResult())

    judge = _judge_client("anthropic")
    with pytest.raises(RuntimeError, match="empty"):
        judge.complete("Is this answer correct? Yes or No.")


def test_claude_judge_returns_stdout_on_success(monkeypatch):
    """F3c: _ClaudeJudge.complete() must return stdout when rc=0 and output is non-empty."""
    import subprocess

    from benchmarks.eval.runner import _judge_client

    class _OkResult:
        returncode = 0
        stdout = "Yes\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _OkResult())

    judge = _judge_client("anthropic")
    result = judge.complete("Is this answer correct? Yes or No.")
    assert result == "Yes\n"


def test_evaluate_survives_arm_timeout(tmp_path):
    """One hung claude -p must not kill the whole billable run: the cell is
    recorded as a timeout failure and the loop continues (gate run 2 died at
    probe 15/16 from a single 300s TimeoutExpired)."""
    import subprocess

    from benchmarks.eval.runner import evaluate

    class FakeBackend:
        def wipe(self): ...

        def seed(self, memories, cwd):
            return {f"mem{i}": m.get("session_id", f"probe:{i}") for i, m in enumerate(memories)}

        def recall_ids(self, query, project, limit=5):
            return ["mem0"]

    class FakeOut:
        answer = "port 9741"
        rekall_payload_tokens = 42
        input_tokens = 900
        prompt_tokens = 10

    def run_arm(arm, item, ws):
        if item["item_id"] == "er-01" and arm == "seeded":
            raise subprocess.TimeoutExpired(cmd="claude", timeout=300)
        return FakeOut()

    items = [
        {
            "item_id": "er-01",
            "question": "port?",
            "question_type": "exact-recall",
            "seed_memories": [{"summary": "proxy on 9741", "type": "decision"}],
            "gold_session_ids": ["probe:0"],
            "oracle_regex": "9741",
            "entry": None,
        },
        {
            "item_id": "er-02",
            "question": "bucket?",
            "question_type": "exact-recall",
            "seed_memories": [{"summary": "bucket is velvet-otter", "type": "fact"}],
            "gold_session_ids": ["probe:0"],
            "oracle_regex": "velvet-otter",
            "entry": None,
        },
    ]
    records = evaluate(
        items,
        ["seeded", "absent"],
        {
            "backend": FakeBackend(),
            "run_arm": run_arm,
            "scorer": lambda item, ans: "9741" in ans,
            "workspace_root": tmp_path,
        },
    )
    assert len(records) == 4  # timeout cell recorded, run continued to er-02
    t = next(r for r in records if r["item_id"] == "er-01" and r["arm"] == "seeded")
    assert t["correct"] is False and t.get("timed_out") is True
    assert any(r["item_id"] == "er-02" for r in records)
