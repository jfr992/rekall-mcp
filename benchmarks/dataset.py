"""LongMemEval dataset loader and corpus builder."""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_FIELDS = {
    "question_id",
    "question_type",
    "question",
    "haystack_sessions",
    "haystack_session_ids",
    "haystack_dates",
    "answer_session_ids",
}


def load_dataset(
    path: str,
    limit: int = 0,
    skip: int = 0,
) -> list[dict]:
    """Load LongMemEval JSON dataset.

    Args:
        path: Path to JSON dataset file
        limit: Max entries to return (0 = no limit)
        skip: Number of entries to skip from start

    Returns:
        List of validated dataset entries

    Raises:
        FileNotFoundError: If dataset file doesn't exist
        ValueError: If any entry is missing required fields
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    with open(p) as f:
        data = json.load(f)

    for i, entry in enumerate(data):
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise ValueError(
                f"Entry {i} ({entry.get('question_id', '?')}) "
                f"missing required fields: {missing}"
            )

    if skip > 0:
        data = data[skip:]
    if limit > 0:
        data = data[:limit]

    return data


def build_session_corpus(
    entry: dict,
    include_assistant: bool = False,
) -> list[dict]:
    """Build documents from haystack sessions. Each doc = one session.

    Args:
        entry: A dataset entry
        include_assistant: If True, include assistant turns; else user-only

    Returns:
        List of documents with keys: session_id, text, date
    """
    corpus = []
    sessions = entry["haystack_sessions"]
    session_ids = entry["haystack_session_ids"]
    dates = entry["haystack_dates"]

    for session, sess_id, date in zip(sessions, session_ids, dates):
        if include_assistant:
            turns = [t["content"] for t in session]
        else:
            turns = [t["content"] for t in session if t["role"] == "user"]

        if turns:
            corpus.append({
                "session_id": sess_id,
                "text": "\n".join(turns),
                "date": date,
            })

    return corpus


def get_ground_truth(entry: dict) -> set[str]:
    """Extract ground-truth session IDs for a question.

    Args:
        entry: A dataset entry

    Returns:
        Set of session IDs that contain the answer
    """
    return set(entry["answer_session_ids"])


def dataset_stats(data: list[dict]) -> dict:
    """Summary statistics for a loaded dataset.

    Args:
        data: List of dataset entries

    Returns:
        Dict with keys: total_questions, question_types,
        avg_sessions_per_question, min_sessions, max_sessions
    """
    from collections import Counter
    types = Counter(e["question_type"] for e in data)
    sessions_per_q = [len(e["haystack_sessions"]) for e in data]
    return {
        "total_questions": len(data),
        "question_types": dict(types),
        "avg_sessions_per_question": sum(sessions_per_q) / len(sessions_per_q) if sessions_per_q else 0,
        "min_sessions": min(sessions_per_q) if sessions_per_q else 0,
        "max_sessions": max(sessions_per_q) if sessions_per_q else 0,
    }
