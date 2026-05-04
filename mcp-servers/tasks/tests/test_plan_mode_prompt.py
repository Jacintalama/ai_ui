"""Regression: the Plan-mode /chat system prompt must instruct the AI to
ask 1-2 clarifying questions before emitting BUILD_SUGGESTION on the
first turn.

Background: a user typed a detailed Plan-mode prompt ("Redesign portfolio
with light theme, add projects showcase, skills section, improved hero,
and modern component architecture") and the AI auto-fired a build
without any back-and-forth. The previous prompt told the AI to skip
clarifications on "any specific feature description"; this regression
test pins the new clause that forbids that behavior on the first turn.

Source-level test: the system prompt is built inline in an async route
handler, so we read the file and assert the marker clause is present.
A future refactor that hoists the prompt into a constant should keep
this test passing by name.
"""
from pathlib import Path

ROUTES_TASKS = Path(__file__).parent.parent / "routes_tasks.py"


def test_plan_mode_prompt_requires_clarification_first():
    """Without this clause, Plan mode auto-fires builds on detailed first
    prompts and skips the planning conversation users expect."""
    src = ROUTES_TASKS.read_text(encoding="utf-8")
    assert "PLAN-FIRST DISCIPLINE" in src, (
        "Plan-mode /chat system prompt is missing the clarification-first "
        "clause. See routes_tasks.py around the 'BUILD KICK-OFF' block."
    )


def test_plan_mode_prompt_documents_the_skip_phrase_exception():
    """Users must still be able to bypass the interview with phrases like
    'just do it' / 'build it' — the exception is what keeps Plan from
    feeling stuck. If this assertion fails, the exception was deleted and
    the user has no way to fast-track."""
    src = ROUTES_TASKS.read_text(encoding="utf-8")
    # At least one of the canonical bypass phrases must remain in the prompt.
    bypass_phrases = ["just do it", "yes do it", "build it", "go ahead", "ship it"]
    found = [p for p in bypass_phrases if p in src]
    assert found, (
        "No bypass phrases left in the Plan-mode prompt. Users must be "
        "able to skip the interview when they're sure. Add one of: "
        f"{bypass_phrases!r}."
    )
