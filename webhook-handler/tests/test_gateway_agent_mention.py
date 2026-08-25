"""Calling an agent by name in an ordinary sentence.

Not an @mention. You write "hi jack, are you there" and Jack answers, which is
why an agent's name has to be one word: a name with a space in it is not
something anybody says mid sentence, and it cannot be found in free text
reliably.

The other half is that an agent has to arrive with its tools. Measured against
production: Open WebUI attaches a model's own tools only for requests from its
own UI, and its middleware says API callers must ask via tool_ids. Without that
field an agent has its instructions and nothing it can do, and it answers that
it cannot reach your mail.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from gateway import agent_router, pipeline
from gateway.events import MessageEvent, MessageType, SessionSource


def _row(aid, name, tools):
    return {"id": aid, "name": name, "base_model_id": "gpt-4o-mini",
            "params": {"system": "do the thing"},
            "meta": {"description": "does the thing", "toolIds": tools},
            "access_grants": [], "is_active": True, "write_access": True,
            "created_at": 1, "updated_at": 1}


JACK = _row("agent-jack-0001", "Jack", ["gmail", "calendar"])
ANA = _row("agent-ana-0002", "Ana", [])
CANDS = agent_router.candidates([JACK, ANA])


# --- the matcher on its own ------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("hi jack are you there", "Jack"),
    ("JACK, any news?", "Jack"),
    ("  jack: what is up", "Jack"),
    ("could you ask Ana about the invoice", "Ana"),
    ("jack and ana are both here", "Jack"),      # the one said first wins
])
def test_a_name_spoken_in_a_sentence_picks_that_agent(text, expected):
    assert agent_router.match_mention(text, CANDS)["name"] == expected


@pytest.mark.parametrize("text", [
    "can you analyse this for me",   # contains "ana"
    "the jackpot is enormous",       # contains "jack"
    "hijack this process",           # contains "jack"
    "hi mary, any news",             # nobody by that name
    "",
])
def test_a_name_inside_another_word_is_not_a_mention(text):
    """An agent called Ana must not answer every time somebody says analyse."""
    assert agent_router.match_mention(text, CANDS) is None


def test_no_candidates_means_no_mention():
    assert agent_router.match_mention("hi jack", []) is None


def test_a_candidate_carries_its_tools():
    """The pipeline hands these to the model. They used to be dropped here,
    which is why an agent arrived with nothing it could do."""
    assert agent_router.candidates([JACK])[0]["tools"] == ["gmail", "calendar"]


def test_a_malformed_tool_list_does_not_become_junk_tools():
    bad = _row("agent-bad-0003", "Bad", "not-a-list")
    assert agent_router.candidates([bad])[0]["tools"] == []
    mixed = _row("agent-mix-0004", "Mix", ["gmail", 7, None, "calendar"])
    assert agent_router.candidates([mixed])[0]["tools"] == ["gmail", "calendar"]


# --- the whole flow --------------------------------------------------------

@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    return a


@pytest.fixture
def owui():
    c = AsyncMock()
    c.get_chat.return_value = {"title": "t", "messages": [],
                               "history": {"messages": {}, "currentId": None}}
    c.create_chat.return_value = "chat-1"
    c.list_models.return_value = [JACK, ANA]
    c.chat_completion.return_value = "the answer"
    return c


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok"}
    tasks.gateway_get_session.return_value = None
    tasks.get_state.return_value = None
    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _event(text):
    return MessageEvent(
        text=text, message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type="dm", user_id="111", user_name="Ralph"))


async def test_saying_the_name_answers_as_that_agent(adapter, owui):
    out = await pipeline.handle_event(_event("hi jack, are you there"), adapter)

    assert owui.chat_completion.await_args.args[1] == "agent-jack-0001"
    assert out.startswith("Jack:"), out


async def test_the_agent_is_handed_its_tools(adapter, owui):
    """The whole point. Without tool_ids the model gets no tools at all on
    this path, whatever the agent says it has."""
    await pipeline.handle_event(_event("jack, check my mail"), adapter)

    assert owui.chat_completion.await_args.kwargs["tool_ids"] == [
        "gmail", "calendar"]


async def test_an_agent_with_no_tools_sends_none(adapter, owui):
    """Sending an empty list would read as "explicitly no tools" rather than
    "nothing to ask for", so it has to be omitted."""
    await pipeline.handle_event(_event("ana, what do you think"), adapter)

    assert owui.chat_completion.await_args.kwargs["tool_ids"] is None


async def test_an_ordinary_message_is_not_answered_by_an_agent(adapter, owui):
    """No name spoken, no pin, and the router declines: the default model
    answers and nothing is prefixed."""
    owui.chat_completion.side_effect = ["NONE", "the answer"]

    out = await pipeline.handle_event(_event("what is the capital of France"),
                                      adapter)

    assert owui.chat_completion.await_args_list[-1].args[1] == settings.gateway_model
    assert ":" not in out.split("\n")[0] or out.startswith("the answer")


async def test_a_spoken_name_beats_the_pin_for_that_message(adapter, owui, wired):
    """Pinned to Ana, but you addressed Jack, so Jack answers and the pin is
    left alone for the message after."""
    wired.tasks.get_state.return_value = {"id": ANA["id"], "name": "Ana"}

    out = await pipeline.handle_event(_event("jack, any news"), adapter)

    assert out.startswith("Jack:"), out
    wired.tasks.delete_state.assert_not_called()
    wired.tasks.set_state.assert_not_called()
