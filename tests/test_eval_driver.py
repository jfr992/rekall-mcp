"""claude -p driver: stream-json parsing + token accounting (cl100k, spec-pinned)."""

from pathlib import Path

FIXTURE = Path("tests/fixtures/eval_stream.jsonl")


def test_parse_stream_extracts_answer_usage_and_rekall_payload():
    from benchmarks.eval.driver import count_tokens, parse_stream

    r = parse_stream(FIXTURE.read_text().splitlines())
    assert r.answer == "The metrics proxy listens on port 9741."
    assert r.input_tokens == 2300 and r.output_tokens == 45
    assert r.rekall_tool_calls == 1
    expected = count_tokens(
        "[decision] Metrics proxy listens on port 9741 (memory_id: 2026-07-05_decision_ab12cd34)"
    )
    assert r.rekall_payload_tokens == expected > 0


def test_build_cmd_bare_and_mcp_difference(tmp_path):
    from benchmarks.eval.driver import build_cmd

    cfg = tmp_path / "arm.json"
    seeded = build_cmd("q", cfg, "claude-haiku-4-5-20251001")
    absent = build_cmd("q", None, "claude-haiku-4-5-20251001")
    assert "--bare" in seeded and "--bare" in absent
    assert str(cfg) in seeded and "/dev/null" in absent
    assert seeded.index("-p") + 1 == seeded.index("q")
    diff = {a for a, b in zip(seeded, absent, strict=False) if a != b}
    assert diff == {str(cfg)}  # arms differ ONLY in the mcp-config path


def test_fullcontext_prompt_carries_sessions_and_date():
    from benchmarks.eval.driver import build_fullcontext_prompt

    entry = {
        "question": "What did I adopt?",
        "question_date": "2023/05/20",
        "haystack_sessions": [[{"role": "user", "content": "I adopted a cat named Miso."}]],
        "haystack_session_ids": ["s_1"],
        "haystack_dates": ["2023/05/01"],
        "answer_session_ids": ["s_1"],
    }
    p = build_fullcontext_prompt(entry)
    assert "Miso" in p and "s_1" in p and "Today is 2023/05/20" in p
