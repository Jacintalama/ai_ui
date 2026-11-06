"""A question nobody can usefully answer does not sit in the queue.

2026-11-06. Ralph said yes to creating a ClickUp space. The chat replied:

    More than one question is waiting, so I did not guess which you meant:
      Main chat: This will run:
      Mia: Mia wants to run:
      Mia: Mia wants to run:
      Main chat: This will run:

Four rows were stuck pending, and two of them were `refresh_cache`, a
method that does not exist and 404s. His yes had nowhere to land, so
every later yes was ambiguous too.

`never_ask_about` stops NEW ones being created. These are the ones
already in the table, and the same reasoning applies: a question about a
call that cannot run is not a question. It should not be counted among
what is waiting, and it should not be offered to somebody to answer.

The TTL is not the answer. It is 24 hours, deliberately, because an
automation fires when nobody is watching. These were hours old and
correctly unexpired. The problem is not that they were old; it is that
they were never answerable.
"""
import pytest

import agent_approvals as A
import agent_tools as T


def _row(name, status="pending", with_held=False):
    """A row shaped the way PRODUCTION produces it.

    `row_of` is what every route and the page see, and it deliberately
    leaves the held conversation out because it can carry the person's own
    mail. The first version of this file built rows WITH held calls, which
    production never produces: the check passed every test here and was a
    no-op on the server, and the four stuck questions were still there
    after it deployed.

    The question text comes from the real builder rather than a copy, so a
    change to its shape fails here instead of silently on the box.
    """
    import routes_agent_turn

    question = routes_agent_turn.approval_question(
        None, [{"function": {"name": name, "arguments": "{}"}}])
    row = {"id": "r-" + name, "status": status, "agent_name": "Main chat",
           "question": question}
    if with_held:
        row["held"] = {"calls": [{"function": {"name": name,
                                               "arguments": "{}"}}]}
    return row


def test_the_row_this_file_builds_is_the_shape_routes_return():
    """Guards every test below. A fixture carrying fields production does
    not produce is testing something else."""
    fields = set(_row("create_app"))
    assert "question" in fields
    assert "held" not in fields
    assert A._tools_named_in(_row("create_app")["question"]) == ["create_app"]


def test_the_held_calls_are_used_when_a_caller_has_them():
    """Some callers do read the held conversation. When they do, that is
    better evidence than the sentence."""
    assert A.is_answerable(_row("refresh_cache", with_held=True)) is False
    assert A.is_answerable(_row("create_app", with_held=True)) is True


# --- the rule -----------------------------------------------------------

def test_the_rule_exists():
    assert hasattr(A, "is_answerable"), (
        "nothing can tell a real question from one about a call that "
        "cannot run")


@pytest.mark.parametrize("name", sorted(T.PROXY_META_ABSENT))
def test_a_question_about_a_call_that_cannot_run_is_not_answerable(name):
    assert A.is_answerable(_row(name)) is False


@pytest.mark.parametrize("name", ["my-clickup_create_space", "send_email",
                                  "create_app", "call_tool"])
def test_a_real_question_is_answerable(name):
    assert A.is_answerable(_row(name)) is True


def test_a_row_with_no_held_call_is_still_answerable():
    """Older rows, and rows from other surfaces, carry no held calls. They
    are somebody's real question and must not be thrown away by a check
    that cannot see inside them."""
    assert A.is_answerable({"id": "x", "status": "pending",
                            "question": "Mia wants to run: something"}) is True


def test_an_odd_row_does_not_crash_the_queue():
    for row in (None, {}, [], "nonsense", {"held": "not a dict"}):
        assert A.is_answerable(row) in (True, False)


# --- it is used where the person is asked -------------------------------

def test_the_waiting_list_leaves_them_out():
    import inspect
    src = inspect.getsource(A.pending_for)
    assert "is_answerable" in src, (
        "pending_for still counts questions nobody can answer")


def test_refresh_cache_is_the_one_he_saw():
    assert A.is_answerable(_row("refresh_cache")) is False
