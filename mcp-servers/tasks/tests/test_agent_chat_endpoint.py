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
    assert len(out["turns"]) == 1
    turn = out["turns"][0]
    assert turn["agent"]["name"] == "Mia"
    assert turn["answer"] == "hi"
    rt._run_turn.assert_awaited_once()
    assert rt._run_turn.await_args.args[1] == "agent-m"


async def test_naming_nobody_is_answered_by_io_itself(_wire, monkeypatch):
    """No agent named means IO answers, on the base model, from here. The pipe
    holds no Open WebUI credentials, so this side owns that call."""
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(return_value="I can help with that."))
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert len(out["turns"]) == 1
    turn = out["turns"][0]
    assert turn["agent"] is None
    assert turn["answer"] == "I can help with that."
    rt._run_turn.assert_not_awaited()
    rt._answer_as_io.assert_awaited_once()


async def test_ios_own_answer_survives_the_base_model_failing(_wire, monkeypatch):
    """Somebody is watching this chat. A base model outage must still produce
    a sentence, not an exception the pipe has to guess at."""
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(side_effect=RuntimeError("model down")))
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    turn = out["turns"][0]
    assert turn["agent"] is None
    assert isinstance(turn["answer"], str) and turn["answer"].strip()


async def test_a_woken_agent_stays_awake_for_the_next_message(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("and what about tomorrow"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Mia", "the pin did not hold"
    assert rt._run_turn.await_count == 2


async def test_naming_a_different_agent_switches_rather_than_stacking(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("actually ada, you take this"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Ada"
    again = await rt.chat(_body("carry on"), x_internal_secret="s")
    assert again["turns"][0]["agent"]["name"] == "Ada", "the switch did not stick"


async def test_a_release_phrase_sends_the_agent_back_to_sleep(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("stop"), x_internal_secret="s")
    assert len(out["turns"]) == 1
    assert out["turns"][0]["agent"] is None
    after = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert after["turns"][0]["agent"] is None, "the agent woke back up on its own"


async def test_the_release_wording_costs_no_completion(_wire, monkeypatch):
    """Releasing gets a fixed acknowledgement, not a model call: the person
    asked for something specific and cheap, and spending a completion to say
    "ok" is waste."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="unused"))
    out = await rt.chat(_body("stop"), x_internal_secret="s")
    turn = out["turns"][0]
    assert turn["agent"] is None
    assert isinstance(turn["answer"], str) and turn["answer"].strip()
    rt._answer_as_io.assert_not_awaited()


async def test_the_pin_is_per_chat(_wire):
    """Two conversations must not share an agent."""
    await rt.chat(_body("hi mia", chat_id="chat-1"), x_internal_secret="s")
    out = await rt.chat(_body("carry on", chat_id="chat-2"), x_internal_secret="s")
    assert out["turns"][0]["agent"] is None


async def test_a_pinned_agent_that_was_deleted_does_not_wedge_the_chat(_wire,
                                                                      monkeypatch):
    """The agent can be deleted between messages. The person did not cause
    that and should not have to notice it: the pin is dropped and IO answers
    what they actually typed."""
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(return_value="I can help with that."))
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA], False)))

    out = await rt.chat(_body("carry on"), x_internal_secret="s")

    turn = out["turns"][0]
    assert turn["agent"] is None
    assert turn["answer"] == "I can help with that.", "the chat was wedged"


async def test_a_truncated_listing_does_not_wake_the_wrong_agent(_wire,
                                                                 monkeypatch):
    """"Not in what we fetched" is not "does not exist". Matching against a
    partial list could pick a different agent with a similar name."""
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], True)))
    out = await rt.chat(_body("hi mia"), x_internal_secret="s")
    assert out["turns"][0]["agent"] is None


async def test_agents_for_filters_out_non_agent_rows(_wire, monkeypatch):
    """_list_agents returns every workspace model this person owns, agents
    and plain derived models alike. Only rows prefixed agent- are this
    person's actual agents, the same test every other consumer of this
    listing applies (webhook-handler/gateway/agent_router.py, cron.html)."""
    fusion = {"id": "fusion", "name": "Fusion", "meta": {}}
    io_model = {"id": "io", "name": "io", "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA, fusion, io_model], False)))

    out = await rt._agents_for("owner@example.com")

    ids = {a["id"] for a in out}
    assert ids == {"agent-a", "agent-m"}
    assert "io" not in ids, "the pipe's own model id must never be an agent"
    assert "fusion" not in ids


async def test_a_workspace_model_that_is_not_an_agent_is_never_woken(_wire,
                                                                     monkeypatch):
    """A workspace model called Fusion getting matched and run through
    _run_turn as though it were an agent, on a message like "let's do a
    fusion of these", is exactly the false positive this filter exists to
    prevent."""
    fusion = {"id": "fusion", "name": "Fusion", "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA, fusion], False)))
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="unused"))

    out = await rt.chat(_body("let's do a fusion of these"), x_internal_secret="s")

    assert out["turns"][0]["agent"] is None
    rt._run_turn.assert_not_awaited()


async def test_a_model_called_io_can_never_wake_itself(_wire, monkeypatch):
    """This branch's own pipe registers a model whose id is "io". Unfiltered,
    "check socket.io" matches it because the dot is a word boundary, and
    running it through _run_turn would call _chat(model="io"), which is the
    pipe re-entering itself and recursing until timeout on a 3.8GB box."""
    io_model = {"id": "io", "name": "io", "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA, io_model], False)))
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="unused"))

    out = await rt.chat(_body("check socket.io"), x_internal_secret="s")

    assert out["turns"][0]["agent"] is None
    rt._run_turn.assert_not_awaited()


async def test_the_pin_is_per_user_not_just_per_chat(_wire, monkeypatch):
    """chat_id alone collapses across real people: the pipe's own "web"
    default for a caller with no chat metadata, and "local", which
    open-webui-functions/langfuse_filter.py already special-cases for
    temporary chats. Without the user's email in the key, alice naming an
    agent in her temporary chat would answer bob's next message in his own
    temporary chat with alice's agent."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="unused"))

    await rt.chat(_body("hi mia", chat_id="local", email="alice@example.com"),
                 x_internal_secret="s")
    out = await rt.chat(_body("carry on", chat_id="local", email="bob@example.com"),
                        x_internal_secret="s")

    assert out["turns"][0]["agent"] is None, "bob's message was answered by alice's agent"


async def test_a_pending_approval_is_passed_through(_wire, monkeypatch):
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(
        return_value={"pending": {"calls": [{"id": "c1"}]}}))
    out = await rt.chat(_body("mia send that email"), x_internal_secret="s")
    turn = out["turns"][0]
    assert turn["agent"]["name"] == "Mia"
    assert turn["pending"]["calls"][0]["id"] == "c1"


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")

    monkeypatch.setattr(rt, "_require_internal", deny)
    with pytest.raises(HTTPException) as caught:
        await rt.chat(_body("hi mia"), x_internal_secret="wrong")
    assert caught.value.status_code == 403


async def test_answer_or_agent_is_always_present(_wire, monkeypatch):
    """Every turn through chat() must either name an agent or say something.

    Silence with no agent named is the wedged-chat bug this whole file exists
    to prevent, and it slipped through twice (the release phrase and the
    stale pin) because every other test here only checks one path at a time.
    """
    monkeypatch.setattr(rt, "_answer_as_io",
                        AsyncMock(return_value="I can help with that."))

    named = await rt.chat(_body("hi mia", chat_id="c-named"),
                          x_internal_secret="s")
    pinned = await rt.chat(_body("and what about tomorrow", chat_id="c-named"),
                           x_internal_secret="s")
    released = await rt.chat(_body("stop", chat_id="c-released"),
                             x_internal_secret="s")
    nobody = await rt.chat(_body("what is the weather", chat_id="c-nobody"),
                           x_internal_secret="s")

    for label, out in (("named", named), ("pinned", pinned),
                       ("released", released), ("nobody", nobody)):
        turn = out["turns"][0]
        assert turn.get("agent") or (turn.get("answer") or "").strip(), label


# --- naming more than one agent --------------------------------------------

async def test_two_names_produce_two_turns_in_spoken_order(_wire):
    """"hi mia and ada" speaks Mia first, so her turn must come first even
    though AGENTS/the fixture lists Ada first."""
    rt._run_turn.side_effect = None
    rt._run_turn.reset_mock()
    async def _answer(user_email, agent_id, messages):
        return {"answer": "answer from %s" % agent_id, "notes": []}
    rt._run_turn.side_effect = _answer

    out = await rt.chat(_body("hi mia and ada, are you there?"), x_internal_secret="s")

    turns = out["turns"]
    assert len(turns) == 2
    assert turns[0]["agent"]["name"] == "Mia"
    assert turns[1]["agent"]["name"] == "Ada"
    assert rt._run_turn.await_count == 2
    first_call, second_call = rt._run_turn.await_args_list
    assert first_call.args[1] == "agent-m"
    assert second_call.args[1] == "agent-a"


async def test_naming_two_agents_pins_the_last_one_named(_wire):
    """A follow up with no name must go to Ada, the one named last, not
    Mia, who was named first."""
    async def _answer(user_email, agent_id, messages):
        return {"answer": "answer from %s" % agent_id, "notes": []}
    rt._run_turn.side_effect = _answer

    out = await rt.chat(_body("hi mia and ada"), x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Mia", "Ada"]

    follow_up = await rt.chat(_body("carry on then"), x_internal_secret="s")
    assert len(follow_up["turns"]) == 1
    assert follow_up["turns"][0]["agent"]["name"] == "Ada", \
        "the pin did not land on the last named agent"


async def test_one_agent_raising_still_returns_both_turns(_wire):
    """Nobody should lose Ada's answer because Mia's tool timed out."""
    async def _flaky(user_email, agent_id, messages):
        if agent_id == "agent-m":
            raise RuntimeError("tool timed out")
        return {"answer": "Ada is here.", "notes": []}
    rt._run_turn.side_effect = _flaky

    out = await rt.chat(_body("hi mia and ada"), x_internal_secret="s")

    turns = out["turns"]
    assert len(turns) == 2
    mia_turn, ada_turn = turns
    assert mia_turn["agent"]["name"] == "Mia"
    assert isinstance(mia_turn["answer"], str) and mia_turn["answer"].strip()
    assert "RuntimeError" not in mia_turn["answer"] and "Traceback" not in mia_turn["answer"], \
        "the failure sentence should be readable, not a stack trace"
    assert ada_turn["agent"]["name"] == "Ada"
    assert ada_turn["answer"] == "Ada is here."


async def test_the_failing_agents_name_appears_in_the_failure_message(_wire):
    """When two agents answer and one fails, the person must know which one
    broke: if the failure does not name its agent, they cannot tell which of
    the two is down."""
    async def _flaky(user_email, agent_id, messages):
        if agent_id == "agent-m":
            raise RuntimeError("tool timed out")
        return {"answer": "Ada is here.", "notes": []}
    rt._run_turn.side_effect = _flaky

    out = await rt.chat(_body("hi mia and ada"), x_internal_secret="s")

    turns = out["turns"]
    mia_turn = turns[0]
    assert mia_turn["agent"]["name"] == "Mia"
    assert "Mia" in mia_turn["answer"], "the failure message must name which agent failed"
