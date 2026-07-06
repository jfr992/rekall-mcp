"""Replicated LongMemEval judge (5 verbatim templates) + probe oracle.

Templates copied verbatim from upstream evaluate_qa.py
(github.com/xiaowu0162/longmemeval src/evaluation/evaluate_qa.py).
Positional {} placeholders are adapted to named {question}/{gold}/{answer}
so Python's .format() can be called with keyword arguments — content unchanged.
A generic prompt is a correctness bug — the per-type rubrics differ.
"""

from __future__ import annotations

import re
from typing import Protocol


class JudgeClient(Protocol):
    def complete(self, prompt: str) -> str: ...


# VERBATIM from github.com/xiaowu0162/longmemeval src/evaluation/evaluate_qa.py.
# {} placeholders adapted to named {question}/{gold}/{answer} — text unchanged.
_TEMPLATES: dict[str, str] = {
    "default": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. \n\n"
        "Question: {question}\n\nCorrect Answer: {gold}\n\nModel Response: {answer}\n\n"
        "Is the model response correct? Answer yes or no only."
    ),
    "temporal": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "In addition, do not penalize off-by-one errors for the number of days. "
        "If the question asks for the number of days/weeks/months, etc., and the model makes "
        "off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's "
        "response is still correct. \n\n"
        "Question: {question}\n\nCorrect Answer: {gold}\n\nModel Response: {answer}\n\n"
        "Is the model response correct? Answer yes or no only."
    ),
    "knowledge_update": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response contains some previous information along with an updated answer, "
        "the response should be considered as correct as long as the updated answer is the "
        "required answer.\n\n"
        "Question: {question}\n\nCorrect Answer: {gold}\n\nModel Response: {answer}\n\n"
        "Is the model response correct? Answer yes or no only."
    ),
    "preference": (
        "I will give you a question, a rubric for desired personalized response, and a "
        "response from a model. Please answer yes if the response satisfies the desired "
        "response. Otherwise, answer no. The model does not need to reflect all the points "
        "in the rubric. The response is correct as long as it recalls and utilizes the "
        "user's personal information correctly.\n\n"
        "Question: {question}\n\nRubric: {gold}\n\nModel Response: {answer}\n\n"
        "Is the model response correct? Answer yes or no only."
    ),
    "abstention": (
        "I will give you an unanswerable question, an explanation, and a response from a "
        "model. Please answer yes if the model correctly identifies the question as "
        "unanswerable. The model could say that the information is incomplete, or some "
        "other information is given but the asked information is not.\n\n"
        "Question: {question}\n\nExplanation: {gold}\n\nModel Response: {answer}\n\n"
        "Does the model correctly identify the question as unanswerable? "
        "Answer yes or no only."
    ),
}


def route_template(question_type: str) -> str:
    """Map a LongMemEval question_type (+_abs suffix) to a template key."""
    if question_type.endswith("_abs"):
        return "abstention"
    return {
        "temporal-reasoning": "temporal",
        "knowledge-update": "knowledge_update",
        "single-session-preference": "preference",
    }.get(question_type, "default")


def build_judge_prompt(question_type: str, question: str, gold: str, answer: str) -> str:
    return _TEMPLATES[route_template(question_type)].format(
        question=question, gold=gold, answer=answer
    )


def judge_answer(
    client: JudgeClient, question_type: str, question: str, gold: str, answer: str
) -> bool:
    """Binary correctness per the published protocol: 'yes' in lowered response."""
    response = client.complete(build_judge_prompt(question_type, question, gold, answer))
    return "yes" in response.lower()


def oracle(answer: str, pattern: str) -> bool:
    """Deterministic probe scorer — no judge, no variance."""
    return re.search(pattern, answer, re.IGNORECASE) is not None
