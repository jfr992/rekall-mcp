"""T6: the judge prompt must exclude session-parking/scratch notes (capture quality —
prod showed 'SESSION PARK'/'TOMORROW track 2' notes stored as facts)."""

from pathlib import Path

HOOK = Path(__file__).parent.parent / "claude" / "hooks" / "rekall-observe.sh"


def test_judge_prompt_excludes_session_parking_notes():
    text = HOOK.read_text()
    assert "session-parking" in text.lower()
