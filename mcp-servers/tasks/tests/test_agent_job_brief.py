"""What a job step's agent is told, and what the lead is told at the end.

Pure functions: the request, the plan and earlier results in, one user
message out. Never the chat transcript (see test_agents_do_not_see_each_other).
"""
import agent_job_brief as brief

NAMES = {"agent-mia": "Mia", "agent-ada": "Ada", "agent-dev": "Dev"}


def _steps(results=None):
    results = results or {}
    rows = [("agent-mia", "find the three latest reports."),
            ("agent-ada", "compare them."),
            ("agent-dev", "draft a summary page.")]
    out = []
    for pos, (agent, task) in enumerate(rows, start=1):
        done = pos in results
        out.append({"position": pos, "agent_id": agent, "task": task,
                    "status": "done" if done else "waiting",
                    "result": results.get(pos)})
    return out


def _content(messages):
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    return messages[0]["content"]


def test_a_step_is_one_user_message_with_the_request_and_the_plan():
    text = _content(brief.step_messages("prepare the weekly summary",
                                        _steps(), 1, NAMES))
    assert text.startswith("The person asked the team: prepare the weekly summary")
    assert "1. Mia: find the three latest reports." in text
    assert "2. Ada: compare them." in text
    assert "3. Dev: draft a summary page." in text
    assert text.rstrip().endswith(
        "Do your step now and answer with its result only.")


def test_the_agents_own_step_is_marked_and_no_other():
    text = _content(brief.step_messages("r", _steps({1: "three reports"}),
                                        2, NAMES))
    assert "2. Ada: compare them. <- this is your step" in text
    assert text.count("this is your step") == 1
    assert "1. Mia: find the three latest reports. (done)" in text


def test_earlier_results_are_given_and_later_steps_have_none():
    steps = _steps({1: "three reports: A, B, C"})
    text = _content(brief.step_messages("r", steps, 2, NAMES))
    assert "Results so far:\nStep 1, Mia: three reports: A, B, C" in text
    assert "Step 2," not in text
    assert "Step 3," not in text


def test_a_result_of_a_later_step_is_never_shown():
    """A retried job could carry a result past this step; it is not this
    agent's to see, because it was written after the plan said this step
    comes first."""
    steps = _steps({1: "first", 3: "from the future"})
    text = _content(brief.step_messages("r", steps, 2, NAMES))
    assert "from the future" not in text


def test_the_first_step_has_no_results_section():
    text = _content(brief.step_messages("r", _steps(), 1, NAMES))
    assert "Results so far" not in text


def test_a_long_result_is_cut_visibly():
    long = "x" * (brief.RESULT_CAP_CHARS + 500)
    text = _content(brief.step_messages("r", _steps({1: long}), 2, NAMES))
    assert "x" * brief.RESULT_CAP_CHARS + " (cut)" in text
    assert "x" * (brief.RESULT_CAP_CHARS + 1) not in text


def test_a_result_at_the_cap_is_not_marked_cut():
    exact = "y" * brief.RESULT_CAP_CHARS
    text = _content(brief.step_messages("r", _steps({1: exact}), 2, NAMES))
    assert "(cut)" not in text


def test_an_unknown_agent_is_named_by_its_id():
    text = _content(brief.step_messages("r", _steps(), 1, {}))
    assert "1. agent-mia: find the three latest reports." in text


def test_steps_are_listed_in_position_order_whatever_order_they_came_in():
    text = _content(brief.step_messages("r", list(reversed(_steps())), 1,
                                        NAMES))
    assert text.index("1. Mia") < text.index("2. Ada") < text.index("3. Dev")


def test_the_final_brief_lists_every_result_and_asks_for_an_answer():
    steps = _steps({1: "three reports", 2: "B is up", 3: "page drafted"})
    text = _content(brief.final_messages("prepare the weekly summary",
                                         steps, NAMES))
    assert text.startswith("The person asked the team: prepare the weekly summary")
    assert "Step 1, Mia: three reports" in text
    assert "Step 2, Ada: B is up" in text
    assert "Step 3, Dev: page drafted" in text
    assert text.rstrip().endswith(
        "Write the person a short final answer from these results.")


def test_the_final_brief_cuts_results_too():
    long = "z" * (brief.RESULT_CAP_CHARS + 1)
    text = _content(brief.final_messages("r", _steps({1: long, 2: "b",
                                                      3: "c"}), NAMES))
    assert "z" * brief.RESULT_CAP_CHARS + " (cut)" in text
