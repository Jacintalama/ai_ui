"""How much this chat asks before it acts.

Ralph, 2026-11-09, with a screenshot of the menu he wants in the chat
composer, next to the model name:

    Manually approve
    Automatically approve     <- ticked
    Skip all approvals

The three levels already exist (read, ask, all) and are already enforced
in one place. What is new is that the choice is made in the conversation
rather than on the Agents page, and that it means something precise:

    manual   ask about every write, and do NOT let a standing rule
             answer for me
    auto     standing rules answer what they cover, the rest asks
             (today's behaviour)
    skip     never ask, run everything

Without that middle definition `manual` and `auto` are the same thing,
because the main chat already asks.

THE RULE THIS MUST NOT BREAK, from agent_access's own docstring: "An
agent's level is a CEILING. A schedule may narrow it and may never widen
it. Two controls that can each widen the other is how permission systems
get holes."

So the preference narrows a named agent and never widens it. In the main
chat there is no agent row and no owner-set ceiling: `_resolve_agent_row`
returns MODE_ASK for the assistant, so all three choices are reachable
there, which is where the control lives. A named agent keeps its own
ceiling, which is the whole point of having one.
"""
import pytest

import agent_access as A


# --- the three choices mean three different things ----------------------

def test_manual_asks_even_where_a_rule_would_have_answered():
    assert A.rules_apply(A.CHAT_MANUAL) is False


def test_automatic_lets_a_rule_answer():
    assert A.rules_apply(A.CHAT_AUTO) is True


def test_no_choice_behaves_exactly_as_before():
    """Every chat that has never touched the menu, which is all of them."""
    assert A.rules_apply(None) is True


def test_manual_and_automatic_are_not_the_same_setting():
    """If they were, the menu would have two items doing one thing."""
    assert A.rules_apply(A.CHAT_MANUAL) != A.rules_apply(A.CHAT_AUTO)


# --- what the loop is allowed to do -------------------------------------

def test_skipping_approvals_in_the_main_chat_acts_without_asking():
    """No agent row, so no ceiling: the assistant is MODE_ASK and the
    person is choosing for their own chat."""
    assert A.with_chat_choice(A.MODE_ASK, A.CHAT_SKIP, ceiling=None) \
        == A.MODE_FULL


def test_manual_in_the_main_chat_still_asks():
    assert A.with_chat_choice(A.MODE_ASK, A.CHAT_MANUAL, ceiling=None) \
        == A.MODE_ASK


def test_no_choice_changes_nothing():
    for mode in (A.MODE_READ_ONLY, A.MODE_ASK, A.MODE_FULL):
        assert A.with_chat_choice(mode, None, ceiling=None) == mode


# --- the ceiling holds ---------------------------------------------------

def test_skipping_approvals_cannot_widen_an_agent_set_to_ask():
    """The rule this module exists to protect. Ada is on `ask` because
    her owner put her there; a menu in a chat window does not overrule
    that."""
    assert A.with_chat_choice(A.MODE_ASK, A.CHAT_SKIP,
                              ceiling=A.LEVEL_ASK) == A.MODE_ASK


def test_skipping_approvals_cannot_widen_a_read_only_agent():
    assert A.with_chat_choice(A.MODE_READ_ONLY, A.CHAT_SKIP,
                              ceiling=A.LEVEL_READ) == A.MODE_READ_ONLY


def test_an_agent_on_all_can_still_be_asked_to_ask():
    """Narrowing is always allowed: that is the direction that is safe."""
    assert A.with_chat_choice(A.MODE_FULL, A.CHAT_MANUAL,
                              ceiling=A.LEVEL_ALL) == A.MODE_ASK


def test_an_agent_on_all_may_be_left_alone():
    assert A.with_chat_choice(A.MODE_FULL, A.CHAT_SKIP,
                              ceiling=A.LEVEL_ALL) == A.MODE_FULL


# --- nothing here may raise ---------------------------------------------

@pytest.mark.parametrize("junk", ["", "nonsense", 7, None, [], {}])
def test_a_choice_nobody_recognises_is_no_choice(junk):
    """It arrives from a browser. An unrecognised value must read as
    "they have not chosen", never as the widest option."""
    assert A.with_chat_choice(A.MODE_ASK, junk, ceiling=A.LEVEL_ASK) \
        == A.MODE_ASK
    assert A.rules_apply(junk) is True


@pytest.mark.parametrize("junk", ["", "nonsense", 7, [], {}])
def test_junk_never_widens_the_main_chat_either(junk):
    assert A.with_chat_choice(A.MODE_ASK, junk, ceiling=None) == A.MODE_ASK


def test_the_choices_are_a_closed_set():
    """So the page and the service cannot drift on what the values are."""
    assert A.CHAT_CHOICES == frozenset(
        {A.CHAT_MANUAL, A.CHAT_AUTO, A.CHAT_SKIP})
    assert len(A.CHAT_CHOICES) == 3


# --- the routes the composer calls --------------------------------------

from unittest.mock import AsyncMock, patch   # noqa: E402

import routes_agents as ra                   # noqa: E402
import routes_agent_turn as rt               # noqa: E402


class _Me:
    email = "owner@example.com"


async def test_the_page_is_told_the_choices_rather_than_inventing_them():
    """So adding or renaming one is a change in a single place, and the
    page cannot drift from what the service accepts."""
    with patch.object(rt, "_choice_seam", new=AsyncMock(return_value=None)):
        got = await ra.read_chat_mode("c1", _Me())
    values = [c["value"] for c in got["choices"]]
    assert values == [A.CHAT_MANUAL, A.CHAT_AUTO, A.CHAT_SKIP], values
    assert got["default"] == A.CHAT_AUTO
    assert got["choice"] == ""
    for c in got["choices"]:
        assert c["label"] and c["detail"], c


async def test_the_skip_option_says_an_agent_keeps_its_own_level():
    """Otherwise it reads as "nothing will ever ask again", which is not
    true for a named agent and is the one place this could mislead."""
    with patch.object(rt, "_choice_seam", new=AsyncMock(return_value=None)):
        got = await ra.read_chat_mode("c1", _Me())
    skip = next(c for c in got["choices"] if c["value"] == A.CHAT_SKIP)
    assert "access level" in skip["detail"].lower(), skip


async def test_a_stored_choice_is_read_back():
    with patch.object(rt, "_choice_seam",
                      new=AsyncMock(return_value=A.CHAT_SKIP)):
        got = await ra.read_chat_mode("c1", _Me())
    assert got["choice"] == A.CHAT_SKIP


async def test_choosing_stores_it_for_this_person_and_chat():
    wrote = AsyncMock()
    with patch.object(rt, "_write_choice", new=wrote):
        got = await ra.set_chat_mode(
            ra.ChatChoiceIn(chat_id="c1", choice=A.CHAT_MANUAL), _Me())
    assert got["choice"] == A.CHAT_MANUAL
    key = wrote.await_args.args[0]
    assert "owner@example.com" in key and "c1" in key, key


async def test_an_empty_choice_clears_rather_than_stores():
    """The page sends "" to go back to the default."""
    cleared, wrote = AsyncMock(), AsyncMock()
    with patch.object(rt, "_clear_choice", new=cleared), \
         patch.object(rt, "_write_choice", new=wrote):
        got = await ra.set_chat_mode(
            ra.ChatChoiceIn(chat_id="c1", choice=""), _Me())
    assert got["choice"] == ""
    cleared.assert_awaited()
    wrote.assert_not_awaited()


async def test_a_value_the_service_does_not_know_is_never_stored():
    """A stale page must not be able to put something unreadable in the
    store, where it would be read back as a choice nobody can undo."""
    cleared, wrote = AsyncMock(), AsyncMock()
    with patch.object(rt, "_clear_choice", new=cleared), \
         patch.object(rt, "_write_choice", new=wrote):
        got = await ra.set_chat_mode(
            ra.ChatChoiceIn(chat_id="c1", choice="everything-always"), _Me())
    assert got["choice"] == ""
    wrote.assert_not_awaited()


def test_the_key_is_scoped_to_the_person_as_well_as_the_chat():
    """Two real chat_id values collapse across everybody on this box, so
    without the email one person's choice would govern another's chat."""
    a = rt._choice_key("web", "one@example.com")
    b = rt._choice_key("web", "two@example.com")
    assert a != b
