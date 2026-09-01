"""The web chat asking who should answer.

The pipe holds no routing logic; it sends the conversation here and this
decides. That keeps one implementation serving Discord, Telegram and the web
chat, and it means the web chat runs OUR tool loop, so the per-agent access
levels apply there.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routes_agent_turn as rt

ADA = {"id": "agent-a", "name": "Ada", "meta": {"toolIds": ["gmail"]}}
MIA = {"id": "agent-m", "name": "Mia", "meta": {"toolIds": []}}


def _body(text, chat_id="chat-1", email="owner@example.com"):
    class B:
        user_email = email
        messages = [{"role": "user", "content": text}]
    b = B()
    b.chat_id = chat_id
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA], False)))
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "hi", "notes": []}))
    pins = {}
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(side_effect=lambda k: pins.get(k)))
    monkeypatch.setattr(rt, "_write_pin",
                        AsyncMock(side_effect=lambda k, v: pins.__setitem__(k, v)))
    monkeypatch.setattr(rt, "_clear_pin", AsyncMock(side_effect=lambda k: pins.pop(k, None)))
    return pins


async def test_naming_an_agent_wakes_it(_wire):
    out = await rt.chat(_body("hi mia how are you"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia"
    assert out["answer"] == "hi"
    rt._run_turn.assert_awaited_once()
    assert rt._run_turn.await_args.args[1] == "agent-m"


async def test_naming_nobody_is_answered_by_io_itself(_wire, monkeypatch):
    """No agent named means IO answers, on the base model, from here. The pipe
    holds no Open WebUI credentials, so this side owns that call."""
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(return_value="I can help with that."))
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert out["agent"] is None
    assert out["answer"] == "I can help with that."
    rt._run_turn.assert_not_awaited()
    rt._answer_as_io.assert_awaited_once()


async def test_ios_own_answer_survives_the_base_model_failing(_wire, monkeypatch):
    """Somebody is watching this chat. A base model outage must still produce
    a sentence, not an exception the pipe has to guess at."""
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(side_effect=RuntimeError("model down")))
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert out["agent"] is None
    assert isinstance(out["answer"], str) and out["answer"].strip()


async def test_a_woken_agent_stays_awake_for_the_next_message(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("and what about tomorrow"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia", "the pin did not hold"
    assert rt._run_turn.await_count == 2


async def test_naming_a_different_agent_switches_rather_than_stacking(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("actually ada, you take this"), x_internal_secret="s")
    assert out["agent"]["name"] == "Ada"
    again = await rt.chat(_body("carry on"), x_internal_secret="s")
    assert again["agent"]["name"] == "Ada", "the switch did not stick"


async def test_a_release_phrase_sends_the_agent_back_to_sleep(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("stop"), x_internal_secret="s")
    assert out["agent"] is None
    after = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert after["agent"] is None, "the agent woke back up on its own"


async def test_the_pin_is_per_chat(_wire):
    """Two conversations must not share an agent."""
    await rt.chat(_body("hi mia", chat_id="chat-1"), x_internal_secret="s")
    out = await rt.chat(_body("carry on", chat_id="chat-2"), x_internal_secret="s")
    assert out["agent"] is None


async def test_a_pinned_agent_that_was_deleted_does_not_wedge_the_chat(_wire,
                                                                      monkeypatch):
    """The agent can be deleted between messages. Failing closed to "no agent"
    keeps the person chatting instead of erroring on every message."""
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA], False)))
    out = await rt.chat(_body("carry on"), x_internal_secret="s")
    assert out["agent"] is None
    assert out["answer"] is None


async def test_a_truncated_listing_does_not_wake_the_wrong_agent(_wire,
                                                                 monkeypatch):
    """"Not in what we fetched" is not "does not exist". Matching against a
    partial list could pick a different agent with a similar name."""
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], True)))
    out = await rt.chat(_body("hi mia"), x_internal_secret="s")
    assert out["agent"] is None


async def test_a_pending_approval_is_passed_through(_wire, monkeypatch):
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(
        return_value={"pending": {"calls": [{"id": "c1"}]}}))
    out = await rt.chat(_body("mia send that email"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia"
    assert out["pending"]["calls"][0]["id"] == "c1"


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")

    monkeypatch.setattr(rt, "_require_internal", deny)
    with pytest.raises(HTTPException) as caught:
        await rt.chat(_body("hi mia"), x_internal_secret="wrong")
    assert caught.value.status_code == 403
