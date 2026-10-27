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

# user_id, because _agents_for filters on it: for an admin the listing
# carries every user's agents, and reaching one by name is now something
# text an agent read somewhere can do. "u1" is what _owui_user_id_for is
# stubbed to return below.
ADA = {"id": "agent-a", "name": "Ada", "user_id": "u1",
       "meta": {"toolIds": ["gmail"]}}
MIA = {"id": "agent-m", "name": "Mia", "user_id": "u1",
       "meta": {"toolIds": []}}


def _body(text, chat_id="chat-1", email="owner@example.com"):
    class B:
        user_email = email
        route_only = False
        first_only = False
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


async def test_the_pin_lasts_five_minutes_of_quiet():
    """Ralph's ask, 2026-09-04: an agent nobody has talked to for five
    minutes goes back to sleep, so a new topic is not handed to an agent
    nobody named. A week was the previous value."""
    assert rt.PIN_TTL_SECONDS == 300


async def test_a_follow_up_keeps_the_agent_awake(_wire):
    """The five minutes run from the agent's last REPLY, not from the last
    time it was named. A pin only rewritten on naming would run out mid
    conversation while a person was still typing to their agent."""
    await rt.chat(_body("hi mia", chat_id="c"), x_internal_secret="s")
    rt._write_pin.reset_mock()
    out = await rt.chat(_body("and what about tomorrow", chat_id="c"),
                        x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Mia"
    rt._write_pin.assert_awaited_once()
    assert rt._write_pin.await_args.args[1] == "agent-m"


async def test_an_agent_sees_history_without_the_speaker_labels(_wire):
    """The rendered reply says "**Ada**" so a person can see who spoke. The
    agent must not see that, or it learns the format and starts inventing
    exchanges between the agents. Seen live 2026-09-04."""
    class B:
        user_email = "ralph@example.com"
        chat_id = "c"
        first_only = False
        messages = [
            {"role": "user", "content": "hi team"},
            {"role": "assistant", "content": "**Ada**\n\nhello\n\n**Mia**\n\nhi there"},
            {"role": "user", "content": "mia, how are you"},
        ]
    await rt.chat(B(), x_internal_secret="s")
    sent = rt._run_turn.await_args.args[2]
    # A system line telling the agent its own name rides in front now,
    # because stripping the labels also left it with no way to know what
    # it is called.
    assert sent[0]["role"] == "system" and "You are " in sent[0]["content"]
    said = [m for m in sent if m["role"] != "system"]
    assert said[0]["content"] == "hi team"
    assert said[1]["content"] == "hello\n\nhi there"
    # The point of the test: no name survives anywhere in the transcript
    # it reads, however the turns are numbered.
    transcript = "\n".join(m["content"] for m in said)
    assert "Ada" not in transcript and "Mia" not in transcript


async def test_an_echoed_label_is_stripped_before_the_real_one_is_added(_wire, monkeypatch):
    """Even with clean history a model can echo a name. Two labels stacked
    is what the person saw, so the answer loses any it opens with."""
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "**Mia**\n\n**Mia**\n\nall good", "notes": []}))
    out = await rt.chat(_body("hi mia"), x_internal_secret="s")
    assert out["turns"][0]["answer"] == "all good"


async def test_route_only_returns_nothing_when_nobody_is_up(_wire, monkeypatch):
    """The Auto (Free) pipe answers for itself when no agent is involved,
    and IO answers for itself THROUGH that pipe. Without this flag Auto
    asking here would get IO's answer, which asks Auto, which asks here."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="IO spoke"))
    b = _body("what is the weather")
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["turns"] == []
    assert out["rendered"] == ""
    rt._answer_as_io.assert_not_awaited()


async def test_first_only_runs_one_agent_and_names_the_rest(_wire):
    """The web page takes turns: the pipe shows the first agent, the page
    fetches the rest one at a time. So the service runs one and says who
    is left, in speaking order."""
    b = _body("hi team")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Ada"]
    assert out["queue"] == ["agent-m"]
    rt._run_turn.assert_awaited_once()


async def test_first_only_still_pins_the_last_agent_in_the_full_list(_wire):
    """A follow up with no name goes to whoever spoke last, and that is
    still Mia even though only Ada has spoken so far."""
    b = _body("hi team")
    b.first_only = True
    await rt.chat(b, x_internal_secret="s")
    assert rt._write_pin.await_args.args[1] == "agent-m"


async def test_the_marker_names_every_speaker_with_the_author_first(_wire):
    b = _body("hi team")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["marker"] == "<!-- aiui:turns agent-a,agent-m -->"


async def test_one_agent_named_means_no_queue_and_no_marker(_wire):
    b = _body("hi mia")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["queue"] == []
    assert out["marker"] == ""


async def test_without_first_only_every_agent_still_runs(_wire):
    """Discord and Telegram never set the flag and must not change."""
    out = await rt.chat(_body("hi team"), x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Ada", "Mia"]
    assert out["queue"] == []
    assert out["marker"] == ""


async def test_every_reply_shape_carries_queue_and_marker(_wire, monkeypatch):
    """The pipes read both fields off every reply, so every branch must
    return them, not only the one that fills them."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="io"))
    for text in ("what is the weather", "stop"):
        out = await rt.chat(_body(text), x_internal_secret="s")
        assert out["queue"] == [] and out["marker"] == "", text
    b = _body("plain")
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["queue"] == [] and out["marker"] == ""


def test_turns_marker_is_one_line_with_ids_only():
    assert rt.turns_marker(["agent-a", "agent-m"]) == "<!-- aiui:turns agent-a,agent-m -->"
    assert rt.turns_marker([]) == ""
    assert rt.turns_marker(["agent-a"]) == ""


@pytest.mark.parametrize("bad", [
    "agent-x-->" + "<script>alert(1)</script>",
    "agent-a,agent-m",
    "agent-with space",
    "not-an-agent",
    "",
])
def test_the_marker_refuses_an_id_that_could_break_out_of_the_comment(bad):
    """The id lands inside an HTML comment on the page. A "-->" would end
    the comment early; a comma would mis-split. Refuse, do not escape."""
    assert rt.turns_marker(["agent-a", bad]) == ""
    assert rt.turns_marker([bad, "agent-a", "agent-m"]) == "<!-- aiui:turns agent-a,agent-m -->"


async def test_first_only_is_inert_when_nobody_is_named(_wire, monkeypatch):
    """The flag is read only on the named branch. Every other return must
    still carry an empty queue and marker, or a pipe reading them raises."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="io"))
    b = _body("what is the weather")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["turns"][0]["agent"] is None
    assert out["queue"] == [] and out["marker"] == ""

    b = _body("what is the weather")
    b.first_only = True
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["turns"] == [] and out["queue"] == [] and out["marker"] == ""


async def test_route_only_still_wakes_a_named_agent(_wire):
    b = _body("hi mia")
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Mia"
    assert out["rendered"] == "**Mia**\n\nhi"


async def test_every_reply_carries_the_rendered_text(_wire):
    """Two pipes show these turns. One renderer here, so they cannot
    drift from each other or from the page that splits replies apart."""
    out = await rt.chat(_body("hi team"), x_internal_secret="s")
    assert out["rendered"] == "**Ada**\n\nhi\n\n**Mia**\n\nhi"


async def test_a_pending_approval_pauses_the_asker_but_still_names_the_rest(
        _wire, monkeypatch):
    """Ada is waiting on a yes or no, so the pin goes to HER rather than to
    the last agent named, and only her turn runs here.

    Mia is not dropped. Withholding the marker as well as the queue used to
    lose every other addressed agent for good: "hi team, delete the stale
    rows" with Ada on Ask had Ada ask her question and Mia never speak and
    never be mentioned, with nothing anywhere recording that she had been
    addressed. Pausing Ada is the point; silently losing Mia was not.
    """
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(return_value={
        "answer": "", "notes": [],
        "pending": {"calls": [{"function": {"name": "send_email"}}],
                    "conversation": []}}))
    b = _body("hi team")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["queue"] == ["agent-m"], "the rest of the round was dropped"
    assert out["marker"] == "<!-- aiui:turns agent-a,agent-m -->", out["marker"]
    # The pin is the asker's, not the last named, so a "yes" reaches Ada.
    assert rt._write_pin.await_args.args[1] == "agent-a"
    rt._run_turn.assert_awaited_once()


async def test_agents_for_returns_only_your_own_agents(_wire, monkeypatch):
    """An admin's /api/v1/models/list carries EVERY user's agents, whatever
    their grants. Before agents could ask each other, reaching one of those by
    name took an admin typing it; now the name can arrive inside text an agent
    read somewhere, which is the case agent_access exists to protect against.
    The colleague still runs as the caller's own email, so what would leak is
    somebody else's persona and its answer rather than their account, and it
    is worth closing before untrusted text can reach it.

    static/agents.html has filtered `m.user_id === state.me` for the same
    reason; /api/v1/models/list is the only listing that still carries
    user_id, which is why this reads that endpoint.
    """
    theirs = {"id": "agent-someone-else", "name": "Vera", "user_id": "u2",
              "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA, theirs], False)))

    out = await rt._agents_for("owner@example.com")

    assert {a["id"] for a in out} == {"agent-a", "agent-m"}


async def test_a_row_with_no_owner_is_not_treated_as_yours(_wire, monkeypatch):
    """Unknown ownership is not ownership. Treating a missing user_id as
    "yours" is how this hole was dug the first time."""
    orphan = {"id": "agent-orphan", "name": "Orphan", "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, orphan], False)))

    out = await rt._agents_for("owner@example.com")

    assert {a["id"] for a in out} == {"agent-a"}


async def test_another_users_agent_is_never_woken_by_name(_wire, monkeypatch):
    """The routing half of the same rule: an admin saying a name that belongs
    to somebody else's agent gets IO, not that agent."""
    theirs = {"id": "agent-vera", "name": "Vera", "user_id": "u2", "meta": {}}
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, theirs], False)))
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="unused"))

    out = await rt.chat(_body("hi vera"), x_internal_secret="s")

    assert out["turns"][0]["agent"] is None
    rt._run_turn.assert_not_awaited()


async def test_own_agents_needs_both_the_prefix_and_the_owner():
    rows = [{"id": "agent-a", "user_id": "u1"},
            {"id": "fusion", "user_id": "u1"},
            {"id": "agent-b", "user_id": "u2"},
            "not a row"]
    assert rt.own_agents(rows, "u1") == [{"id": "agent-a", "user_id": "u1"}]


# --- release in plain words (agent_jev.wants_release) -----------------------
# The exact phrases above stay. Jev is asked only about a short message in a
# chat that has an agent awake, and only when it has a key.

@pytest.fixture
def jev_release(monkeypatch):
    import agent_jev
    asked = []
    state = {"verdict": True}

    async def wants_release(email, text):
        asked.append((email, text))
        return state["verdict"]

    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.setattr(agent_jev, "wants_release", wants_release)
    return asked, state


async def test_plain_words_release_an_awake_agent(_wire, jev_release):
    asked, _ = jev_release
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    rt._run_turn.reset_mock()
    out = await rt.chat(_body("ok thanks, I'm done for now"),
                        x_internal_secret="s")
    assert asked == [("owner@example.com", "ok thanks, I'm done for now")]
    assert out["turns"][0]["agent"] is None
    assert out["turns"][0]["answer"] == rt.RELEASED
    rt._run_turn.assert_not_awaited()
    assert _wire == {}


@pytest.mark.parametrize("verdict", [False, None])
async def test_jev_not_sure_keeps_the_agent_awake(_wire, jev_release,
                                                  verdict):
    _, state = jev_release
    state["verdict"] = verdict
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("yes do it"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Mia"


async def test_jev_is_not_asked_with_nobody_awake(_wire, jev_release,
                                                 monkeypatch):
    asked, _ = jev_release
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="io"))
    await rt.chat(_body("ok I'm done for now"), x_internal_secret="s")
    assert asked == []


async def test_jev_is_not_asked_about_a_long_message(_wire, jev_release):
    asked, _ = jev_release
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    await rt.chat(_body("can you check the calendar for next week and tell "
                        "me what is free"), x_internal_secret="s")
    assert asked == []


async def test_jev_is_not_asked_about_an_exact_phrase(_wire, jev_release):
    asked, _ = jev_release
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("stop"), x_internal_secret="s")
    assert out["turns"][0]["agent"] is None
    assert asked == []


async def test_jev_is_not_asked_without_a_key(_wire, jev_release,
                                              monkeypatch):
    asked, _ = jev_release
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    await rt.chat(_body("ok I'm done for now"), x_internal_secret="s")
    assert asked == []


# --- Jev in the main chat (2026-10-26) --------------------------------------
# Nobody named, pinned or obviously owning the subject: before the general
# model answers, Jev is asked whether one agent should take the message.
# Without a key nothing here runs, which is what every test above relies on.

def _jev(monkeypatch, path="one_agent", agent_id="agent-m", reply_ok=True,
         raises=False):
    import agent_decider
    calls = {"decide": [], "reply": []}

    async def decide(email, chat_id, message, history, agents):
        calls["decide"].append((email, chat_id, message, [a["id"] for a in agents]))
        if raises:
            raise RuntimeError("jev down")
        return agent_decider.Decision(path=path, kind="answer", agent_id=agent_id,
                                      agent_confidence=0.9)

    async def reply_answers(email, message, reply):
        calls["reply"].append((message, reply))
        return reply_ok

    async def no_graph(email, question=""):
        return ""

    monkeypatch.setattr(rt.agent_decider, "enabled", lambda: True)
    monkeypatch.setattr(rt.agent_decider, "decide", decide)
    monkeypatch.setattr(rt.agent_jev, "reply_answers", reply_answers)
    monkeypatch.setattr(rt.agent_graph, "graph_block", no_graph)
    return calls


ASK = "chase the overdue invoices for me please"


async def test_jev_sends_an_unnamed_message_to_the_agent_it_is_sure_of(_wire, monkeypatch):
    calls = _jev(monkeypatch)
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body(ASK), x_internal_secret="s")
    assert calls["decide"] == [("owner@example.com", "chat-1", ASK, ["agent-a", "agent-m"])]
    assert out["turns"][0]["agent"]["name"] == "Mia"
    assert out["rendered"].startswith("**Mia**")
    assert calls["reply"] == [(ASK, "hi")]
    rt._answer_as_io.assert_not_awaited()
    # And Mia stays awake for the follow up, as a named agent would.
    assert _wire[rt._pin_key("chat-1", "owner@example.com")] == "agent-m"


async def test_the_free_model_gets_the_message_when_jev_picks_for_the_auto_pipe(_wire, monkeypatch):
    _jev(monkeypatch)
    b = _body(ASK)
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["turns"] and out["turns"][0]["agent"]["id"] == "agent-m"


async def test_jev_is_not_asked_about_a_greeting(_wire, monkeypatch):
    calls = _jev(monkeypatch)
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="hello"))
    out = await rt.chat(_body("hi there"), x_internal_secret="s")
    assert calls["decide"] == []
    assert out["turns"][0]["agent"] is None


async def test_jev_is_not_asked_without_a_key(_wire, monkeypatch):
    calls = _jev(monkeypatch)
    monkeypatch.setattr(rt.agent_decider, "enabled", lambda: False)
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body(ASK), x_internal_secret="s")
    assert calls["decide"] == []
    assert out["turns"][0]["answer"] == "general"


async def test_a_name_still_wins_over_jev(_wire, monkeypatch):
    calls = _jev(monkeypatch, agent_id="agent-m")
    out = await rt.chat(_body("ada, chase the overdue invoices"), x_internal_secret="s")
    assert calls["decide"] == []
    assert out["turns"][0]["agent"]["name"] == "Ada"


async def test_a_pick_whose_reply_did_not_answer_is_not_shown(_wire, monkeypatch):
    _jev(monkeypatch, reply_ok=False)
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body(ASK), x_internal_secret="s")
    assert out["turns"][0]["agent"] is None and out["turns"][0]["answer"] == "general"
    assert rt._pin_key("chat-1", "owner@example.com") not in _wire
    # The Auto pipe, which answers for itself, is told nobody took it.
    b = _body(ASK)
    b.route_only = True
    assert (await rt.chat(b, x_internal_secret="s"))["turns"] == []


async def test_jev_unsure_or_down_leaves_the_chat_as_before(_wire, monkeypatch):
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    _jev(monkeypatch, path="fallback")
    assert (await rt.chat(_body(ASK), x_internal_secret="s"))["turns"][0]["agent"] is None
    _jev(monkeypatch, raises=True)
    assert (await rt.chat(_body(ASK), x_internal_secret="s"))["turns"][0]["agent"] is None
    rt._run_turn.assert_not_awaited()


async def test_an_agent_jev_picked_that_stops_to_ask_is_passed_through(_wire, monkeypatch):
    calls = _jev(monkeypatch, reply_ok=False)
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(return_value={
        "answer": "", "notes": [],
        "pending": {"ask_id": "q1", "calls": [{"name": "send_email"}]}}))
    out = await rt.chat(_body(ASK), x_internal_secret="s")
    assert out["turns"][0]["agent"]["id"] == "agent-m"
    assert out["turns"][0]["pending"]["ask_id"] == "q1"
    # A question is not a reply to judge.
    assert calls["reply"] == []


# --- a skill asked for by name goes to the agent that has it (2026-10-26) ---

def _skills(monkeypatch, *names):
    monkeypatch.setattr(rt.agent_skills, "load_all",
                        lambda refresh=False: {n: {"name": n, "description": n, "body": "Steps.",
                                                   "tools": [], "tags": [], "folder": n}
                                               for n in names})


async def test_the_agent_with_the_skill_takes_the_job_and_stays_awake(_wire, monkeypatch):
    _skills(monkeypatch, "weekly-review")
    kai = {"id": "agent-k", "name": "Kai", "user_id": "u1",
           "meta": {"toolIds": [], "skillIds": ["weekly-review"]}}
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA, MIA, kai], False)))
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body("run the weekly review for me"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Kai"
    assert rt._run_turn.await_args.args[1] == "agent-k"
    rt._answer_as_io.assert_not_awaited()
    assert _wire[rt._pin_key("chat-1", "owner@example.com")] == "agent-k"


async def test_a_skill_nobody_has_leaves_the_message_to_the_general_model(_wire, monkeypatch):
    _skills(monkeypatch, "weekly-review")
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body("run the weekly review for me"), x_internal_secret="s")
    assert out["turns"][0]["agent"] is None
    rt._run_turn.assert_not_awaited()


async def test_two_agents_with_the_skill_are_left_to_jev(_wire, monkeypatch):
    _skills(monkeypatch, "weekly-review")
    kai = {"id": "agent-k", "name": "Kai", "user_id": "u1", "meta": {"skillIds": ["weekly-review"]}}
    kaz = {"id": "agent-z", "name": "Kaz", "user_id": "u1", "meta": {"skillIds": ["weekly-review"]}}
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([kai, kaz], False)))
    calls = _jev(monkeypatch, agent_id="agent-z")
    out = await rt.chat(_body("run the weekly review for me"), x_internal_secret="s")
    assert len(calls["decide"]) == 1
    assert out["turns"][0]["agent"]["name"] == "Kaz"


# --- the agents' faces on a reply (2026-10-27) ------------------------------

async def test_a_reply_carries_the_faces_and_a_web_rendering(_wire):
    out = await rt.chat(_body("hi mia how are you"), x_internal_secret="s")
    assert out["rendered"] == "**Mia**\n\nhi"
    assert out["rendered_web"].startswith("![Mia](data:image/svg+xml;base64,")
    assert out["rendered_web"].endswith(") **Mia**\n\nhi")
    assert set(out["faces"]) == {"agent-m"}
    assert out["faces"]["agent-m"].startswith("data:image/svg+xml;base64,")


async def test_ios_own_answer_has_no_face(_wire, monkeypatch):
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="general"))
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert out["rendered_web"] == "general" and out["faces"] == {}
