"""Replicated LongMemEval judge (5 verbatim templates) + probe oracle."""

from benchmarks.eval.scorers import route_template


def test_route_template_maps_all_six_types():
    assert route_template("single-session-user") == "default"
    assert route_template("single-session-assistant") == "default"
    assert route_template("multi-session") == "default"
    assert route_template("temporal-reasoning") == "temporal"
    assert route_template("knowledge-update") == "knowledge_update"
    assert route_template("single-session-preference") == "preference"
    assert route_template("whatever_abs") == "abstention"


class FakeClient:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def test_judge_yes_in_response_means_correct():
    from benchmarks.eval.scorers import judge_answer

    assert judge_answer(FakeClient("Yes"), "multi-session", "q", "g", "a") is True
    assert judge_answer(FakeClient("no"), "multi-session", "q", "g", "a") is False


def test_judge_prompt_carries_type_rubric_and_fields():
    from benchmarks.eval.scorers import judge_answer

    c = FakeClient("yes")
    judge_answer(c, "temporal-reasoning", "How many days?", "18", "19 days")
    assert "off-by-one" in c.prompts[0]
    assert "How many days?" in c.prompts[0] and "18" in c.prompts[0] and "19 days" in c.prompts[0]


def test_oracle_regex_case_insensitive():
    from benchmarks.eval.scorers import oracle

    assert oracle("We chose PostgreSQL for JSONB.", r"postgres") is True
    assert oracle("We chose MySQL.", r"postgres") is False
