"""The menu Ralph asked for is already in the composer.

He sent a screenshot of Claude Code's approval menu and said "put that in
ehre", pointing at the message box. Before writing any of it I read Open
WebUI's own source off the build's source maps on the box, because the
warning in tests/browser/test_the_panel_lands_inside_the_reply.py says
placement has been wrong three times when markup was reasoned about
rather than read. What is there, in 0.12.0, is this:

    src/lib/components/chat/MessageInput/InputMenu.svelte
      Full access         Run tools without asking for approval.
      Ask for approval    Stop before each tool call until you allow or
                          deny it.
    $: toolPermissionsEnabled = $config?.features?.enable_tool_permissions

It is hidden because `chat.tool_permissions.enable` is false, and that is
a row in the `config` table (models/config.py: "key TEXT PK, value JSON",
read with no cache), so turning it on needs no rebuild and no restart.

So there is nothing to build in the composer. What is left is reading the
person's pick, and WHERE we read it from is the whole of this file.

NOT from the turn's metadata. main.py:1300 writes

    tool_approval_mode = ('full' if automation_id or
        chat_id.startswith('channel:') else (... if await Config.get(
        'chat.tool_permissions.enable', False) else 'full') or 'full')

so `full` is what the platform says when it has nothing to say: the
feature off, an automation, a channel, a chat nobody has touched. Reading
that as "this person chose to skip approvals" would have stopped the main
chat asking for all nine people the moment it deployed, with no menu on
screen to put it back.

FROM THE CHAT ROW. Chat.svelte's handleToolApprovalModeChange is the only
thing that writes `params.tool_approval_mode` onto the chat
(updateChatById), and it only runs on a click. So the key being there at
all is the record of intent, which is exactly what the metadata lost.
"""
import pytest

import agent_access as A
import routes_agent_turn as R


# --- the two postures Open WebUI offers, in our own words ---------------

def test_ask_for_approval_means_rules_answer_and_the_rest_asks():
    assert A.choice_from_approval_mode("ask") == A.CHAT_AUTO


def test_full_access_means_never_ask():
    assert A.choice_from_approval_mode("full") == A.CHAT_SKIP


def test_the_two_postures_are_not_the_same_choice():
    assert (A.choice_from_approval_mode("ask")
            != A.choice_from_approval_mode("full"))


def test_both_postures_map_onto_choices_the_rest_of_the_module_knows():
    for mode in ("ask", "full"):
        assert A.choice_from_approval_mode(mode) in A.CHAT_CHOICES


def test_their_menu_cannot_reach_manual():
    """It has two items. `manual` stays ours, through our own route."""
    assert A.CHAT_MANUAL not in {A.choice_from_approval_mode("ask"),
                                 A.choice_from_approval_mode("full")}


# --- nothing chosen is not a choice ------------------------------------

def test_nothing_on_the_chat_row_is_not_a_choice():
    assert A.choice_from_approval_mode(None) is None


def test_an_empty_string_is_not_a_choice():
    assert A.choice_from_approval_mode("") is None


def test_a_word_their_menu_never_writes_is_not_a_choice():
    assert A.choice_from_approval_mode("read_only") is None
    assert A.choice_from_approval_mode("yes") is None


def test_something_that_is_not_text_is_not_a_choice():
    """It comes out of a JSON column, so anything can turn up."""
    for junk in (True, 1, 0, [], {}, ["ask"]):
        assert A.choice_from_approval_mode(junk) is None


def test_the_value_is_read_the_way_it_is_stored():
    assert A.choice_from_approval_mode(" Ask ") == A.CHAT_AUTO
    assert A.choice_from_approval_mode("FULL") == A.CHAT_SKIP


# --- the turn reads the composer's pick --------------------------------

class _Body:
    def __init__(self, chat_id="c1", user_email="someone@example.com"):
        self.chat_id = chat_id
        self.user_email = user_email
        self.messages = [{"role": "user", "content": "hi"}]
        self.route_only = False
        self.first_only = False
        self.agent_id = None


@pytest.fixture
def seams(monkeypatch):
    """The turn replaced by one that reports the choice it was handed."""
    seen = {}

    async def _inner(body, secret):
        seen["choice"] = R._choice_for_turn.get()
        return {"turns": []}

    monkeypatch.setattr(R, "_chat_inner", _inner)
    monkeypatch.setattr(R, "_require_internal", lambda secret: None)
    return seen


async def test_the_composers_pick_reaches_the_turn(monkeypatch, seams):
    async def _composer(chat_id):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_SKIP


async def test_the_composer_wins_over_what_we_stored_ourselves(
        monkeypatch, seams):
    """The composer is the control the person can SEE. A visible control
    that an invisible one overrules is a bug, not a preference."""
    async def _composer(chat_id):
        return A.CHAT_SKIP

    async def _stored(key):
        return A.CHAT_MANUAL

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_SKIP


async def test_with_nothing_in_the_composer_our_own_choice_still_counts(
        monkeypatch, seams):
    """Their menu has no `manual`, and surfaces that send no mode at all
    still have one. Neither can be reached if a blank composer wiped it."""
    async def _composer(chat_id):
        return None

    async def _stored(key):
        return A.CHAT_MANUAL

    async def _none(_):
        return None

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _none)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_MANUAL


async def test_nobody_has_chosen_anything_is_todays_behaviour(
        monkeypatch, seams):
    async def _none(_):
        return None

    monkeypatch.setattr(R, "_composer_seam", _none)
    monkeypatch.setattr(R, "_choice_seam", _none)
    monkeypatch.setattr(R, "_account_seam", _none)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] is None


async def test_the_pick_is_read_for_the_chat_the_message_is_in(
        monkeypatch, seams):
    asked = {}

    async def _composer(chat_id):
        asked["chat_id"] = chat_id
        return None

    async def _none(_):
        return None

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_account_seam", _none)
    await R.chat(_Body(chat_id="chat-42"), x_internal_secret="s")
    assert asked["chat_id"] == "chat-42"


# --- it cannot widen a named agent -------------------------------------

def test_full_access_in_the_composer_does_not_widen_a_read_only_agent():
    """The ceiling is the point of having one. Same rule as the Agents
    page, reached from a different control."""
    assert A.with_chat_choice(
        A.MODE_READ_ONLY, A.choice_from_approval_mode("full"),
        A.LEVEL_READ) == A.MODE_READ_ONLY


def test_full_access_in_the_composer_is_honoured_in_the_main_chat():
    """No agent row behind the main chat, so there is no ceiling to hold."""
    assert A.with_chat_choice(
        A.MODE_ASK, A.choice_from_approval_mode("full"),
        None) == A.MODE_FULL


def test_ask_for_approval_narrows_an_agent_that_could_have_acted():
    assert A.with_chat_choice(
        A.MODE_FULL, A.choice_from_approval_mode("ask"),
        A.LEVEL_ALL) == A.MODE_ASK


# --- a database that will not answer must not widen anything -----------

async def test_a_chat_row_that_cannot_be_read_is_no_choice(monkeypatch):
    """Fails toward None, which is today's behaviour, never toward the
    widest option: an outage must not quietly stop a chat asking."""
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("no database")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(R, "session", lambda: _Boom())
    assert await R._read_composer_choice("c1") is None


# --- the streamed path is the one the main chat actually uses ----------

async def test_a_streamed_turn_is_handed_the_same_choice(monkeypatch, seams):
    """Found while wiring this up: /agents/chat/stream runs _chat_inner
    itself and never set the contextvar, so the control worked on the
    one-shot route and did nothing on the route the chat really calls.
    A preference that only applies on the path nobody takes is not a
    preference.
    """
    async def _composer(chat_id):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    async for _ in R._chat_events(_Body(), "s"):
        pass
    assert seams["choice"] == A.CHAT_SKIP


async def test_a_streamed_turn_falls_back_to_our_own_choice(
        monkeypatch, seams):
    async def _composer(chat_id):
        return None

    async def _stored(key):
        return A.CHAT_MANUAL

    async def _none(_):
        return None

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _none)
    async for _ in R._chat_events(_Body(), "s"):
        pass
    assert seams["choice"] == A.CHAT_MANUAL


async def test_both_routes_read_the_choice_the_same_way(monkeypatch):
    """One function behind both, so they cannot drift. The alternative is
    what this codebase has done twice before: the same decision written
    in two places, where fixing one leaves the other open."""
    asked = []

    async def _composer(chat_id):
        asked.append(chat_id)
        return None

    async def _inner(body, secret):
        return {"turns": []}

    async def _none(_):
        return None

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_account_seam", _none)
    monkeypatch.setattr(R, "_chat_inner", _inner)
    monkeypatch.setattr(R, "_require_internal", lambda secret: None)
    await R.chat(_Body(chat_id="one"), x_internal_secret="s")
    async for _ in R._chat_events(_Body(chat_id="two"), "s"):
        pass
    assert asked == ["one", "two"]


# --- the account's own setting, when this chat has no pick -------------
#
# Found 2026-11-10 from a screenshot. Ralph asked "where is the option
# auto approve" after being asked twice for one ClickUp task. Both sides
# measured on the box:
#
#   chat 7f92c5ef...  Landing Page AIUI   tool_approval_mode: (null)
#   user ralphbenitez32@gmail.com         tool_approval_mode: full
#
# InputMenu.svelte declares `export let toolApprovalMode = 'full'` and
# Chat.svelte resolves it to 'full' unless something says 'ask', so his
# menu was ALREADY reading "Full access" while the platform asked anyway,
# because only a click writes the chat row. That is the bug
# `with_chat_choice` names in its own docstring, inverted: a visible
# control saying one thing while an invisible one does another.
#
# The account setting is a real record of intent, written by that same
# click through updateUserSettings, and it is what the menu displays. So
# it answers when the chat itself has nothing to say. It stays the
# narrowest thing that could have been read: per account, never platform
# wide, and the turn's metadata is still consulted nowhere.


async def test_the_account_setting_answers_when_this_chat_has_no_pick(
        monkeypatch, seams):
    async def _composer(chat_id):
        return None

    async def _stored(key):
        return None

    async def _account(email):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _account)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_SKIP


async def test_a_pick_in_this_chat_beats_the_account_setting(
        monkeypatch, seams):
    """Choosing "Ask for approval" in one chat has to hold there even when
    the account says full access, or the per-chat menu is decoration."""
    async def _composer(chat_id):
        return A.CHAT_AUTO

    async def _account(email):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_account_seam", _account)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_AUTO


async def test_our_own_choice_for_this_chat_beats_the_account_setting(
        monkeypatch, seams):
    """`manual` is per chat and unreachable from their two-item menu, so a
    global default must not quietly undo it."""
    async def _composer(chat_id):
        return None

    async def _stored(key):
        return A.CHAT_MANUAL

    async def _account(email):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _account)
    await R.chat(_Body(), x_internal_secret="s")
    assert seams["choice"] == A.CHAT_MANUAL


async def test_the_setting_is_read_for_whoever_sent_the_message(
        monkeypatch, seams):
    """Nine people share this platform. Reading the wrong row would hand
    one person's posture to somebody else."""
    asked = {}

    async def _composer(chat_id):
        return None

    async def _stored(key):
        return None

    async def _account(email):
        asked["email"] = email
        return None

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _account)
    await R.chat(_Body(user_email="her@example.com"), x_internal_secret="s")
    assert asked["email"] == "her@example.com"


async def test_the_streamed_route_reads_the_account_too(monkeypatch, seams):
    """The streamed route is the one the main chat really calls, and it
    has already been the one left behind once."""
    async def _composer(chat_id):
        return None

    async def _stored(key):
        return None

    async def _account(email):
        return A.CHAT_SKIP

    monkeypatch.setattr(R, "_composer_seam", _composer)
    monkeypatch.setattr(R, "_choice_seam", _stored)
    monkeypatch.setattr(R, "_account_seam", _account)
    async for _ in R._chat_events(_Body(), "s"):
        pass
    assert seams["choice"] == A.CHAT_SKIP


# --- reading the account row -------------------------------------------

class _Rows:
    """A session that answers one scalar, the way the real one does."""

    def __init__(self, value):
        self.value = value
        self.params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, _sql, params=None):
        self.params = params
        return self

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.parametrize("saved,expected", [
    ("full", A.CHAT_SKIP),
    ("ask", A.CHAT_AUTO),
    (None, None),
    ("", None),
    ("read_only", None),
])
async def test_what_the_account_row_says_becomes_our_choice(
        monkeypatch, saved, expected):
    """Same mapping as the chat row, so the two cannot disagree about
    what a word means."""
    rows = _Rows(saved)
    monkeypatch.setattr(R, "session", lambda: rows)
    assert await R._read_account_choice("him@example.com") == expected


async def test_the_account_row_is_looked_up_by_the_address_given(monkeypatch):
    rows = _Rows("full")
    monkeypatch.setattr(R, "session", lambda: rows)
    await R._read_account_choice("Him@Example.com")
    assert rows.params == {"email": "Him@Example.com"}


async def test_an_account_row_that_cannot_be_read_is_no_choice(monkeypatch):
    """Same direction as the chat row: an outage must not stop a chat
    asking."""
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("no database")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(R, "session", lambda: _Boom())
    assert await R._read_account_choice("him@example.com") is None


async def test_no_address_is_not_looked_up_at_all(monkeypatch):
    """A surface with nobody behind it must not match a row."""
    def _never():
        raise AssertionError("asked the database with no address")

    monkeypatch.setattr(R, "session", _never)
    assert await R._read_account_choice("") is None
    assert await R._read_account_choice(None) is None


def test_the_account_setting_still_cannot_widen_a_named_agent():
    """It goes through the same ceiling as every other control, so a
    global default cannot hand an agent more than its owner allowed."""
    assert A.with_chat_choice(
        A.MODE_READ_ONLY, A.CHAT_SKIP, A.LEVEL_READ) == A.MODE_READ_ONLY
