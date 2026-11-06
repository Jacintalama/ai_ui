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


def _row(name, status="pending"):
    return {"id": "r-" + name, "status": status, "agent_name": "Main chat",
            "question": "This will run:\n  " + name + "\n\nReply yes to let "
                        "it, or no to skip.",
            "held": {"calls": [{"function": {"name": name, "arguments": "{}"}}]}}


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
