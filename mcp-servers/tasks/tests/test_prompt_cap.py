"""The prompt cap must not cut a build prompt's own closing instructions.

MAX_PROMPT_CHARS was 8000 when it was added (2026-04-13, "to limit injection
of huge payloads"). The templates grew past it: on 2026-10-02 a fresh-build
prompt rendered to 9530 characters, so both executors cut off its commit,
NEEDS_INPUT, tool-use and COMPLETED instructions on every build.
"""
import claude_executor as ce

SHORT = "Build a landing page for a bakery called Crumb and Co in Basel."
FORM_MAX = "x" * 2000          # routes_tasks caps the enhance form at 2000
COMMON = dict(action_type="BUILD", priority="NICE_TO_HAVE",
              meeting_title="m", meeting_date="", slug="crumb-and-co")
SUPABASE = dict(supabase_url="https://abc.supabase.co", has_db_uri=True)
ENDING = ("When done successfully", "COMPLETED: <summary")


def _cut(prompt: str) -> str:
    """What both executors pass on (local_executor, remote_executor)."""
    return prompt[:ce.MAX_PROMPT_CHARS]


def _keeps_its_ending(prompt: str) -> bool:
    kept = _cut(prompt)
    return all(marker in kept for marker in ENDING)


def test_a_fresh_build_keeps_its_ending():
    assert _keeps_its_ending(ce.build_prompt(description=SHORT, **COMMON))


def test_a_fresh_build_with_a_long_request_keeps_its_ending():
    assert _keeps_its_ending(ce.build_prompt(description=FORM_MAX, **COMMON))


def test_a_supabase_build_keeps_its_ending():
    assert _keeps_its_ending(
        ce.build_prompt(description=SHORT, **COMMON, **SUPABASE))


def test_a_resume_keeps_its_ending():
    assert _keeps_its_ending(ce.build_resume_prompt(
        description=SHORT, slug="crumb-and-co",
        conversation_history=[{"role": "ai", "content": "Which city?"}],
        latest_answer="Basel"))


def test_an_enhance_keeps_its_completed_block():
    prompt = ce.build_enhance_prompt(slug="crumb-and-co",
                                     user_request=FORM_MAX, **SUPABASE)
    assert "end your response with a `COMPLETED:` block" in _cut(prompt)


def test_the_cap_still_fits_one_command_line_argument():
    # The prompt is one argv entry locally and inside the ssh command
    # remotely, and Linux caps one argument at 131072 bytes. Four bytes is
    # the most one character takes in UTF-8.
    assert ce.MAX_PROMPT_CHARS * 4 <= 131072
