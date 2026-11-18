"""A run that was refused its tools did not complete its job.

Measured on production 2026-11-18. Every one of the seven schedules on
this platform has recorded exactly one status in six months:
`completed`. Not one failure, which is not credible.

One of them, a teammate's "Daily email summary", says this in its own
result, every run:

    The summary is sent, but I have to flag the same problem as the
    previous run: sending was refused again. I am still set to
    read-only, so the email draft above is what I have for you here
    instead.

Status: completed. A schedule whose whole purpose is to send has never
sent, the agent has been saying so run after run, and nothing read it
because the only thing that reads a run is `last_run_status`.

`agent_runner` already knows. It appends the refusal to the answer and
then returns "completed" anyway:

    if notes:
        answer = answer + note_text
    outcome = "completed"

It also already treats two other "the turn ended but the job did not
happen" cases as failures, with comments explaining exactly this
reasoning: a run that spent every round with no answer, and an exhausted
model pool. A refused write is the same class and was the one left out.

WHY `refused` AND NOT `failed`. The agent did its work: a summary WAS
written. Calling that failed would be as wrong in the other direction,
and the existing docstring is right that a refusal is not an error. What
is wrong is calling it completed. `refused` is the third thing that
actually happened, and it is what the owner needs to see.

The two things that read the status both handle a new value safely, and
one of them wants it: `_messages_for` carries a result forward only from
a completed run, so a refused run no longer poisons the next with its
own apology, and the schedules page colours an unknown status as plain,
which this teaches.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_runner


def test_the_phrase_is_named_once():
    """The producer and the decision must agree. Two copies of a string
    is how one of them changes and the other quietly stops matching."""
    assert hasattr(agent_runner, "DECLINED_NOTE")
    assert agent_runner.DECLINED_NOTE, "it is empty"


def test_the_notes_the_runner_writes_start_with_it():
    """Assert the statement, not the name: the real append sites have to
    produce something this matches."""
    import inspect
    src = inspect.getsource(agent_runner)
    # The statement, not a spelling: no bare copy of the phrase survives
    # anywhere but the constant's own definition. The first version of
    # this counted "notes.append(DECLINED_NOTE" and missed a real append
    # that wraps onto the next line.
    bare = src.count('"' + agent_runner.DECLINED_NOTE + '"')
    assert bare == 1, (
        "%d bare copies of the phrase, expected only the constant's own "
        "definition. A second copy is how the producer changes and the "
        "status check quietly stops matching." % bare)
    assert src.count("DECLINED_NOTE +") >= 2, (
        "the append sites do not build their note from the constant")


def _say(notes):
    return agent_runner.status_for_notes(notes)


def test_a_refused_tool_is_not_completed():
    """The live case."""
    notes = [agent_runner.DECLINED_NOTE
             + "gmail_send_email, because this schedule is set to read "
               "only."]
    assert _say(notes) == "refused"


def test_a_run_with_nothing_to_report_is_completed():
    assert _say([]) == "completed"


def test_a_note_that_is_not_a_refusal_is_still_completed():
    """Not every note means the job failed. A note about the model being
    swapped, or anything else we add later, must not turn a good run
    into a refused one."""
    assert _say(["Used a different model because the first was busy."]) \
        == "completed"


def test_one_refusal_among_several_notes_still_counts():
    notes = ["Used a different model because the first was busy.",
             agent_runner.DECLINED_NOTE + "gmail_send_email, because this "
             "schedule is set to read only."]
    assert _say(notes) == "refused"


def test_a_rule_denying_it_counts_too():
    """The other append site: a standing rule of the owner's, rather than
    read-only. Both mean the job did not happen."""
    notes = [agent_runner.DECLINED_NOTE
             + "trello_create_card, because your rule 'no writes' denies "
               "it."]
    assert _say(notes) == "refused"


def test_it_is_not_fooled_by_the_word_appearing_mid_sentence():
    """The check is on how the note STARTS, because an agent's own prose
    is appended to the same answer and routinely contains the word."""
    assert _say(["The vendor declined to run the report."]) == "completed"


def test_nothing_else_is_reclassified():
    """`failed` keeps its meaning. This adds a third state, it does not
    rename the second."""
    assert _say([]) != "failed"


# --- the page has to be able to draw it -----------------------------------

def test_the_schedules_page_knows_the_new_status():
    page = os.path.join(os.path.dirname(__file__), "..", "static",
                        "cron.html")
    src = open(page, encoding="utf-8").read()
    assert "refused" in src, (
        "the page colours an unknown status as plain, so a refused run "
        "would look like no status at all")
    i = src.index("function runStatusClass")
    chunk = src[i:i + 700]
    assert "refused" in chunk, (
        "runStatusClass does not know it: " + chunk[:300])
    # And it must not be lumped in with the two it is deliberately not.
    line = [l for l in chunk.splitlines() if "refused" in l][0]
    assert "completed" not in line, line
    assert "failed" not in line, line
