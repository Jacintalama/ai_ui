"""The main chat says what it is doing, and its runs can be counted.

Three complaints, one change, 2026-10-29.

THE WAIT WAS SILENT. Measured on the live box right after the pool fix:
2.4s for a question the free model answers, 9.5s for "check my inbox",
12.3s for a message with an attachment that an agent took, against a 120s
timeout, with recorded turns averaging 5.6s and reaching 41.7s. The person
saw a spinner for all of it. The one line there used to be was removed on
2026-10-28 and rightly so: it said "Choosing who answers..." on every
message, including the ones where nothing was being chosen.

So the rule these tests hold to is not "say something", it is **say only
what is true of this message**: who is answering, because an agent was
named or Jev picked one, and what is being read, because Jev picked a tool.
A question the free model takes says nothing at all.

A GROUNDED ANSWER LOOKED LIKE A GUESS. When the assistant answered using
the person's own mailbox, nothing on screen said so, so it was
indistinguishable from the model inventing an inbox.

THE MAIN CHAT COULD NOT BE MEASURED. Its turns recorded `source` as
"channel", the same value Discord uses, because channel is the fallback.
The 136 channel rows could not be split, so there was no latency, failure
rate or cost for the main chat anywhere in the database.
"""
import asyncio
import json

import pytest

import agent_access
import agent_activity
import agent_progress
import routes_agent_turn as rt


# --- what the lines say -------------------------------------------------------

def test_a_tool_is_named_as_a_place_not_as_an_id():
    assert agent_progress.reading_line(["gmail"]) == "Reading your email..."
    assert agent_progress.used_line(["gmail"]) == "Used your email"


def test_two_tools_are_joined_readably():
    assert agent_progress.used_line(["gmail", "calendar"]) == (
        "Used your email and your calendar")


def test_three_tools_get_their_commas():
    assert agent_progress.used_line(["gmail", "calendar", "gdrive"]) == (
        "Used your email, your calendar and your Drive")


def test_two_tools_that_mean_one_place_are_not_said_twice():
    """Jev can pick both `agents` and `colleague` for one message, and both
    are "your agents" to the person. "your agents and your agents" is not a
    sentence."""
    assert agent_progress.used_line(["agents", "colleague"]) == "Used your agents"


def test_no_tool_means_no_line_at_all():
    """The ordinary question. Nothing is happening to it, so nothing is said:
    this is the whole reason the old blanket status line was removed."""
    assert agent_progress.reading_line([]) == ""
    assert agent_progress.used_line([]) == ""
    assert agent_progress.reading_line(None) == ""


def test_an_unknown_tool_is_still_named():
    """Ugly but true. Dropping it would defeat the point of the line, which
    is that the person can see what was touched."""
    assert "wingdings" in agent_progress.used_line(["wingdings"])


def test_an_agent_is_announced_by_name():
    assert agent_progress.answering_line(["Mia"]) == "Mia is answering..."
    assert agent_progress.answered_by(["Mia"]) == "Answered by Mia"


def test_several_agents_are_announced_together():
    assert agent_progress.answered_by(["Mia", "Ada"]) == "Answered by Mia and Ada"


def test_nobody_is_never_announced_as_somebody():
    """The reported bug of 2026-10-28, as a test: the assistant is not an
    agent, so with no names there must be no line to borrow its credit."""
    assert agent_progress.answering_line([]) == ""
    assert agent_progress.answered_by([]) == ""
    assert agent_progress.answered_by([None, ""]) == ""


# --- saying it ---------------------------------------------------------------

def test_nothing_is_said_when_nobody_is_listening():
    """Discord, the panel and every test that does not opt in. `say` must be
    free to call from anywhere in the ladder."""
    assert agent_progress.listening() is False
    agent_progress.say("this goes nowhere")          # must not raise


def test_what_is_said_reaches_the_listener_in_order():
    heard = []
    with agent_progress.reporting_to(heard.append):
        assert agent_progress.listening() is True
        agent_progress.say("first")
        agent_progress.say("second")
    assert heard == ["first", "second"]


def test_an_empty_line_is_never_delivered():
    heard = []
    with agent_progress.reporting_to(heard.append):
        agent_progress.say("")
        agent_progress.say(None)
    assert heard == []


def test_the_listener_is_put_back_afterwards():
    heard = []
    with agent_progress.reporting_to(heard.append):
        pass
    agent_progress.say("after")
    assert heard == []


def test_a_listener_that_throws_cannot_break_a_turn():
    """The answer is the point and this is decoration on top of it."""
    def explode(_line):
        raise RuntimeError("the socket went away")

    with agent_progress.reporting_to(explode):
        agent_progress.say("still fine")             # must not raise


# --- the stream --------------------------------------------------------------

class _Body:
    """Enough of ChatIn for _chat_events, which only passes it through."""
    user_email = "owner@example.com"
    chat_id = "chat-1"
    messages = [{"role": "user", "content": "check my inbox"}]
    route_only = True


def _events(monkeypatch, inner):
    """Drain _chat_events into a list of (event, data) pairs."""
    monkeypatch.setattr(rt, "_chat_inner", inner)

    async def drain():
        out = []
        async for ev in rt._chat_events(_Body(), "secret"):
            out.append((ev["event"], json.loads(ev["data"])))
        return out

    return asyncio.run(drain())


def test_a_line_said_during_the_turn_arrives_before_the_reply(monkeypatch):
    """The point of the whole route. If the status arrived with the reply it
    would be worth nothing: the wait is what it is for."""
    async def inner(body, secret):
        agent_progress.say("Reading your email...")
        return {"turns": [{"agent": None, "answer": "two unread", "notes": []}],
                "status": "Used your email"}

    events = _events(monkeypatch, inner)
    assert [e for e, _ in events] == ["status", "reply"]
    assert events[0][1] == {"line": "Reading your email..."}
    assert events[1][1]["status"] == "Used your email"


def test_every_line_arrives_in_the_order_it_was_said(monkeypatch):
    async def inner(body, secret):
        agent_progress.say("Mia is answering...")
        agent_progress.say("Reading your email...")
        return {"turns": [{"agent": None, "answer": "ok", "notes": []}]}

    events = _events(monkeypatch, inner)
    assert [d["line"] for e, d in events if e == "status"] == [
        "Mia is answering...", "Reading your email..."]


def test_a_turn_that_says_nothing_sends_only_the_reply(monkeypatch):
    """The ordinary question again, through the real route this time."""
    async def inner(body, secret):
        return {"turns": [], "status": ""}

    assert [e for e, _ in _events(monkeypatch, inner)] == ["reply"]


def test_a_turn_that_blows_up_ends_the_stream_with_an_error(monkeypatch):
    """The caller then answers with its own free model, which is what it did
    before any of this existed."""
    async def inner(body, secret):
        raise RuntimeError("the database went away")

    assert [e for e, _ in _events(monkeypatch, inner)] == ["error"]


def test_a_line_said_before_a_failure_is_not_mistaken_for_success(monkeypatch):
    async def inner(body, secret):
        agent_progress.say("Reading your email...")
        raise RuntimeError("and then it broke")

    events = _events(monkeypatch, inner)
    assert [e for e, _ in events] == ["status", "error"]


def test_the_stream_marks_its_runs_as_the_main_chat(monkeypatch):
    """The mark has to be inside the streaming route too, not only on the
    plain one, or half the main chat's runs would still read as Discord's."""
    seen = {}

    async def inner(body, secret):
        seen["in_main_chat"] = agent_activity.in_main_chat()
        return {"turns": []}

    _events(monkeypatch, inner)
    assert seen["in_main_chat"] is True


def test_the_listener_does_not_outlive_the_stream(monkeypatch):
    async def inner(body, secret):
        return {"turns": []}

    _events(monkeypatch, inner)
    assert agent_progress.listening() is False


# --- the main chat is countable now -------------------------------------------

def test_a_main_chat_turn_is_recorded_as_the_main_chat():
    with agent_activity.main_chat():
        assert rt._source_for(agent_access.SURFACE_CHANNEL) == (
            agent_activity.SOURCE_CHAT)


def test_a_turn_from_anywhere_else_is_still_recorded_as_before():
    """Discord must not start reading as the main chat."""
    assert rt._source_for(agent_access.SURFACE_CHANNEL) == (
        agent_activity.SOURCE_CHANNEL)


def test_the_main_chat_and_discord_are_no_longer_the_same_value():
    """The defect itself, named: these two were both "channel", so the rows
    could not be told apart."""
    assert agent_activity.SOURCE_CHAT != agent_activity.SOURCE_CHANNEL


@pytest.mark.parametrize("surface,expected", [
    (agent_access.SURFACE_COLLEAGUE, agent_activity.SOURCE_COLLEAGUE),
    (agent_access.SURFACE_AUTOMATION, agent_activity.SOURCE_AUTOMATION),
])
def test_a_handoff_or_an_automation_keeps_its_own_source_inside_the_chat(
        surface, expected):
    """Most specific wins: who asked this agent, or what started it, says
    more about why the run exists than which window it was typed in."""
    with agent_activity.main_chat():
        assert rt._source_for(surface) == expected


def test_a_meeting_called_from_the_main_chat_is_still_a_meeting():
    with agent_activity.main_chat(), agent_activity.meeting_round():
        assert rt._source_for(agent_access.SURFACE_CHANNEL) == (
            agent_activity.SOURCE_MEETING)


def test_a_job_step_outranks_the_main_chat_too():
    with agent_activity.main_chat(), agent_activity.job_step():
        assert rt._source_for(agent_access.SURFACE_CHANNEL) == (
            agent_activity.SOURCE_JOB)


def test_the_mark_is_put_back_after_the_chat_route():
    with agent_activity.main_chat():
        pass
    assert agent_activity.in_main_chat() is False


# --- the route itself, over real HTTP ----------------------------------------
# The tests above drive the generator. These drive the mounted route, so the
# EventSourceResponse wiring, the media type and the secret check are covered
# too: a correct generator behind a route that 403s everybody is no use.

def _app(monkeypatch, inner):
    import os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "s3cret")
    monkeypatch.setattr(rt, "_chat_inner", inner)
    app = FastAPI()
    app.include_router(rt.router)
    return TestClient(app)


BODY = {"user_email": "owner@example.com", "chat_id": "c1",
        "messages": [{"role": "user", "content": "check my inbox"}],
        "route_only": True}


def test_the_route_serves_an_event_stream(monkeypatch):
    async def inner(body, secret):
        agent_progress.say("Reading your email...")
        return {"turns": [{"agent": None, "answer": "Two unread.", "notes": []}],
                "rendered": "Two unread.", "status": "Used your email"}

    client = _app(monkeypatch, inner)
    r = client.post("/agents/chat/stream", json=BODY,
                    headers={"X-Internal-Secret": "s3cret"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    # The buffering header matters: a buffered event stream arrives all at
    # once at the end, which is the silence this route exists to remove.
    assert r.headers.get("x-accel-buffering") == "no"
    assert "Reading your email..." in r.text
    assert "Used your email" in r.text
    assert r.text.index("Reading your email") < r.text.index("Used your email")


def test_the_route_refuses_a_caller_with_no_secret(monkeypatch):
    async def inner(body, secret):
        raise AssertionError("the turn ran for an unauthenticated caller")

    client = _app(monkeypatch, inner)
    assert client.post("/agents/chat/stream", json=BODY).status_code == 403


def test_the_route_refuses_a_wrong_secret(monkeypatch):
    async def inner(body, secret):
        raise AssertionError("the turn ran for the wrong secret")

    client = _app(monkeypatch, inner)
    r = client.post("/agents/chat/stream", json=BODY,
                    headers={"X-Internal-Secret": "guess"})
    assert r.status_code == 403


# --- the ladder really calls it ----------------------------------------------
# Everything above drives the mechanism. These drive the places that use it,
# because a perfect reporter nobody calls reports nothing. Each one stubs the
# turn itself, which is the slow part and needs a database and a model.


def _stub_turn(monkeypatch, answer="Two unread."):
    """Replace the turn with an instant one, and record nothing else."""
    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        return {"agent": agent, "answer": answer, "notes": []}

    async def graph_block(_email, _text):
        return ""

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)


class _ChatBody:
    user_email = "owner@example.com"
    chat_id = "chat-1"
    route_only = True
    first_only = False
    agent_id = None

    def __init__(self, text):
        self.messages = [{"role": "user", "content": text}]


def test_the_assistant_says_what_it_is_about_to_read(monkeypatch):
    """The slowest thing the main chat does, and the one that was silent."""
    _stub_turn(monkeypatch)
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda _a: True)
    heard = []
    with agent_progress.reporting_to(heard.append):
        out = asyncio.run(rt._assistant_reply(
            _ChatBody("check my inbox"), "check my inbox", [],
            picked=["gmail"]))
    assert heard == ["Reading your email..."], heard
    assert out["status"] == "Used your email"


def test_the_assistant_with_no_tool_says_nothing_and_does_not_answer(monkeypatch):
    """An ordinary question: no tool, so no assistant turn and no line. This
    is the 2026-10-28 rule, and it must stay true now that there is
    something to say."""
    _stub_turn(monkeypatch)
    heard = []
    with agent_progress.reporting_to(heard.append):
        out = asyncio.run(rt._assistant_reply(
            _ChatBody("what is a webhook"), "what is a webhook", [],
            picked=[]))
    assert out is None
    assert heard == []


def test_the_agent_jev_picked_is_named_before_it_runs(monkeypatch):
    """Named before the turn, not after: the turn is the slow part."""
    _stub_turn(monkeypatch)

    async def holds_up(_email, _text, _answer):
        return True

    monkeypatch.setattr(rt.agent_jev, "reply_answers", holds_up)

    async def write_pin(_key, _agent_id):
        return None

    monkeypatch.setattr(rt, "_write_pin", write_pin)
    agent = {"id": "a1", "name": "Mia"}
    heard = []
    with agent_progress.reporting_to(heard.append):
        out = asyncio.run(rt._jev_answer(_ChatBody("chase the invoices"),
                                         "chase the invoices", [agent], agent))
    assert heard == ["Mia is answering..."], heard
    assert out["status"] == "Answered by Mia"


def test_a_discarded_reply_leaves_no_claim_behind(monkeypatch):
    """Jev picked Mia, Mia's reply did not answer, so the free model takes
    it. The pipe gets None and emits nothing, so the person is never told
    an agent answered when none did."""
    _stub_turn(monkeypatch)

    async def did_not_answer(_email, _text, _answer):
        return False

    monkeypatch.setattr(rt.agent_jev, "reply_answers", did_not_answer)
    agent = {"id": "a1", "name": "Mia"}
    out = asyncio.run(rt._jev_answer(_ChatBody("chase the invoices"),
                                     "chase the invoices", [agent], agent))
    assert out is None, "a reply that did not answer was shown anyway"


# --- nobody was named, so nobody is shown (2026-10-29, reported twice) --------
#
# Reported with a screenshot: "i havnet mention any agent why is this". Asking
# the main chat to send an email drew the office robot and a bold "IO" above
# the approval question, as though an agent had taken it.
#
# The line that prevents that was already there from the 2026-10-28 report
# ("instead of answered by your agent just make it answer directly ... since
# no mention of his agents"). It was applied only to the branch where the
# assistant ANSWERS, and a turn that stops to ask goes down the other one.


def test_the_assistant_asking_for_approval_shows_no_agent(monkeypatch):
    """The reported case. A held turn must carry no agent, or the chat draws
    a face and a name for something the person never mentioned."""
    held = {"agent_id": "io-assistant",
            "calls": [{"function": {"name": "send_email",
                                    "arguments": '{"to": "a@b.c"}'}}]}

    async def turn_for(user_email, agent, messages, names=(), roster=(),
                       graph="", now=None, tool_ids=None):
        return {"agent": agent, "answer": "", "notes": [], "pending": held}

    async def graph_block(_email, _text):
        return ""

    monkeypatch.setattr(rt, "_turn_for", turn_for)
    monkeypatch.setattr(rt.agent_graph, "graph_block", graph_block)
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda _a: True)

    out = asyncio.run(rt._assistant_reply(
        _ChatBody("send an email to a@b.c"), "send an email to a@b.c", [],
        picked=["gmail"]))
    assert out["turns"][0]["agent"] is None, (
        "the assistant kept an agent row on a held turn, so the chat shows "
        "a robot and a name for an agent nobody mentioned")


def test_a_held_assistant_turn_renders_with_no_robot_and_no_name():
    """What the person actually sees. The face is a data: image, so a leak
    shows up as that string in the rendered reply."""
    turns = [{"agent": None, "answer": "", "notes": [],
              "pending": {"agent_id": "io-assistant",
                          "calls": [{"function": {"name": "send_email",
                                                  "arguments": "{}"}}]}}]
    web = rt.render_turns(turns, faces=True)
    assert "data:image" not in web, "the office robot was drawn"
    assert "**IO**" not in web and "IO wants to run" not in web
    assert web.startswith("This will run:")


def test_an_unnamed_approval_does_not_invent_an_agent():
    """"This agent wants to run" was the old fallback. In the main chat there
    is no agent, so it named one that does not exist."""
    first = rt.approval_question(None, []).splitlines()[0]
    assert first == "This will run:"
    assert "agent" not in first.lower()


def test_a_named_agent_is_still_named():
    """The fix must not strip the name off a real agent the person DID ask
    for: that is the whole point of the approval."""
    assert rt.approval_question("Mia", []).splitlines()[0] == "Mia wants to run:"


def test_a_real_agents_held_turn_keeps_its_face(monkeypatch):
    """Naming Mia and having her stop to ask must still show Mia."""
    turns = [{"agent": {"id": "a1", "name": "Mia"}, "answer": "", "notes": [],
              "pending": {"agent_id": "a1",
                          "calls": [{"function": {"name": "send_email",
                                                  "arguments": "{}"}}]}}]
    assert "Mia wants to run:" in rt.render_turns(turns)


def test_the_raw_assistant_id_is_never_shown_to_a_person():
    """io-assistant is an internal id. It used to reach both the stored
    approval and its question once the agent row was nulled."""
    assert "io-assistant" not in rt.approval_question(None, [])


# --- the tools must not vanish when somebody says go (2026-10-29) -------------
#
# Reported with a screenshot: asking for a daily quote agent, then "create it
# please", and the chat answered "I can't actually create agents or scheduled
# cron jobs inside your platform". It can: agent_builder and schedules are
# both granted. Jev was shown one orphan sentence, so the follow-up carried no
# subject. From tasks.jev_check on the live box, the same conversation:
#
#   13:56:42  agent_builder,schedules  0.89   describing it
#   13:57:38  agent_builder            0.84   still describing it
#   13:57:48  none                     0.34   "create it please"
#
# Agreement is always the shortest message, so this failed hardest exactly
# when somebody said go.

FOLLOW_UP = [
    {"role": "user", "content": "make an agent that sends a daily quote on a cron"},
    {"role": "assistant", "content": "Would you like me to create the agent now?"},
    {"role": "user", "content": "create it please"},
]


def test_the_conversation_is_given_to_the_tool_pick():
    said = rt.recent_exchange(FOLLOW_UP)
    assert "daily quote" in said, "the subject of the request was not carried"
    assert "cron" in said


def test_the_message_being_judged_is_not_repeated_as_context():
    """The caller passes it separately, so including it here would weigh the
    same sentence twice."""
    assert "create it please" not in rt.recent_exchange(FOLLOW_UP)


def test_an_opening_message_has_no_context_and_that_is_fine():
    assert rt.recent_exchange([{"role": "user", "content": "hello"}]) == ""
    assert rt.recent_exchange([]) == ""
    assert rt.recent_exchange(None) == ""


def test_only_the_recent_turns_are_carried():
    """An old topic must not outweigh the current one."""
    many = [{"role": "user", "content": "topic %d" % i} for i in range(40)]
    said = rt.recent_exchange(many)
    assert "topic 0" not in said and "topic 38" in said
    assert len(said.splitlines()) <= rt.CONTEXT_TURNS


def test_rubbish_in_the_history_does_not_crash_the_pick():
    msgs = [None, "a string", 7, {"role": "tool", "content": "ignored"},
            {"role": "user", "content": "the real one"},
            {"role": "user", "content": "now"}]
    assert rt.recent_exchange(msgs) == "person: the real one"


def test_an_attached_turn_still_contributes_its_words():
    """The same list-of-parts shape that used to read as empty everywhere."""
    msgs = [{"role": "user", "content": [
                {"type": "text", "text": "look at this invoice"},
                {"type": "image_url", "image_url": {"url": "data:x"}}]},
            {"role": "user", "content": "chase it"}]
    assert "invoice" in rt.recent_exchange(msgs)


def test_jev_is_asked_about_the_follow_up_with_its_subject(monkeypatch):
    """End to end through _tool_pick: what Jev actually receives."""
    seen = {}

    async def pick_tools(email, text, tools, context=""):
        seen["text"] = text
        seen["context"] = context
        return ["agent_builder"]

    async def every_tool(_email):
        return ["agent_builder", "schedules", "gmail"]

    monkeypatch.setattr(rt.agent_jev, "pick_tools", pick_tools)
    monkeypatch.setattr(rt, "_every_tool_for", every_tool)
    monkeypatch.setattr(rt, "_assistant_on", lambda: True)
    monkeypatch.setattr(rt.agent_llm, "can_run", lambda _a: True)

    body = _ChatBody("create it please")
    body.messages = FOLLOW_UP
    picked = asyncio.run(rt._tool_pick(body, "create it please"))
    assert picked == ["agent_builder"]
    assert seen["text"] == "create it please"
    assert "daily quote" in seen["context"], (
        "Jev was asked about the follow-up with no subject again")


def test_the_question_without_context_is_word_for_word_what_it_was():
    """The calibration cases are single messages. Changing their wording
    would silently invalidate the measured 0.75 cut."""
    import agent_jev
    state, _q = agent_jev.tools_request("check my inbox", ["gmail"])
    assert state == "The person wrote:\ncheck my inbox"


def test_with_context_the_latest_message_is_clearly_the_one_being_judged():
    import agent_jev
    state, _q = agent_jev.tools_request(
        "create it please", ["gmail"], context="person: make a quote agent")
    assert state.rstrip().endswith("create it please")
    assert "The person has now written:" in state
