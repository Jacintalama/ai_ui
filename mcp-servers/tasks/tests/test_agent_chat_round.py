"""One message, one bubble per agent, in order.

The assertion that matters most is test_agents_do_not_see_each_other: feeding
agents each other's replies is what taught the model to invent whole exchanges
between agents, and nothing but this test stops that coming back.
"""
import importlib

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_runner

EMAIL = "panel-owner@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _app(monkeypatch, turn=None, agents=(ADA, MIA)):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    seen = []

    async def default_turn(email, agent, messages, names=(), **kw):
        seen.append({"agent": agent["id"], "messages": [dict(m) for m in messages]})
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return list(agents)

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn or default_turn)
    # The store's SQL half needs a real Postgres. Swap it out so these tests
    # measure the round rather than the "database is down" path.
    async def noop_create(email, title, s, agent_id=None):
        return "chat-1"

    async def noop_save(email, s):
        return None

    async def no_graph(email, question=""):
        return ""

    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)
    # Same reason as the store: a round reads the person's whole account from
    # the database before the first agent speaks, and these tests measure the
    # round rather than what happens when that read is unavailable.
    monkeypatch.setattr(routes_agent_chat.agent_graph, "graph_block", no_graph)
    # A message to the whole team is put to the lead first (agent_job_triage),
    # which is one more model call. These tests measure the round as it was
    # before jobs, which is exactly what a triage that finds no job leaves.
    # The job tests below replace this with one that does.
    import agent_job_triage

    async def no_job(email, lead, roster, history):
        return None

    monkeypatch.setattr(agent_job_triage, "triage", no_job)
    # Before the triage, Jev is asked who should take a team message
    # (agent_decider). No decision is what a server without a key gets, and
    # it leaves the round as it was. The Jev tests below replace this.
    import agent_decider

    async def no_decision(email, chat_id, message, history, agents):
        return None

    monkeypatch.setattr(agent_decider, "decide", no_decision)

    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, seen


def _seat(mod, room=()):
    """There is no room to seat any more: every agent hears every message.

    Kept as the tests' way of reaching the session, and it now only says
    which agents exist by leaving that to the _app fixture.
    """
    return mod.store.get_session(EMAIL)


def test_send_requires_identity(monkeypatch):
    app, _, _ = _app(monkeypatch)
    r = TestClient(app).post("/tasks/agents/chat/send", data={"message": "hi"})
    assert r.status_code == 401


def test_send_records_the_message_and_opens_a_stream(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/send", data={"message": "hi team"},
               headers=_hdr())
    assert "hi team" in r.text
    assert 'sse-connect="/tasks/agents/chat/stream"' in r.text
    assert r.headers.get("HX-Trigger") == "agent-chats-changed"
    s = mod.store.get_session(EMAIL)
    # Carries the turn id the send response already drew on the page, so
    # _run_round can address its answers at the same turn (see s.turn_id and
    # into_turn/turn_status in agent_chat_render.py).
    stored = s.messages[-1]
    assert stored["role"] == "user"
    assert stored["content"] == "hi team"
    assert stored["turn_id"] == s.turn_id
    assert stored["turn_id"]


def test_every_agent_in_the_room_gets_its_own_bubble_in_order(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert body.count('class="am agent"') == 2
    assert body.index("Ada here") < body.index("Mia here")


def test_agents_do_not_see_each_other(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert [t["agent"] for t in seen] == ["agent-a", "agent-m"]
    # Identical input, and Ada's answer is nowhere in Mia's.
    assert seen[0]["messages"] == seen[1]["messages"]
    assert "Ada here" not in str(seen[1]["messages"])


def test_a_reconnecting_stream_does_not_re_run_the_round(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    after_one_round = len(seen)
    again = c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert len(seen) == after_one_round, "the reconnect re-ran the round"
    assert "am agent" not in again.text


def test_a_stream_with_nothing_to_answer_just_closes(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    r = TestClient(app).get("/tasks/agents/chat/stream", headers=_hdr())
    assert seen == []
    assert "event: close" in r.text


def test_a_person_with_no_agents_is_told_so(monkeypatch):
    """_agents_for returns nothing on any doubt, an upstream listing cut
    short included, so this is also what a hiccup looks like."""
    app, mod, seen = _app(monkeypatch, agents=())
    _seat(mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert seen == []
    assert body.count("no agents yet") == 1, body


def test_that_note_survives_a_reload(monkeypatch):
    app, mod, _ = _app(monkeypatch, agents=())
    _seat(mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    replayed = mod.render.thread(mod.store.get_session(EMAIL).messages)
    assert "no agents yet" in replayed


def test_a_failed_agent_does_not_take_the_round_down(monkeypatch):
    async def turn(email, agent, messages, names=(), **kw):
        if agent["id"] == "agent-a":
            # _turn_for never raises; a blown-up turn comes back as a sentence.
            return {"answer": "Ada could not finish that just now.", "notes": [],
                    "agent": {"id": "agent-a", "name": "Ada"}}
        return {"answer": "Mia here", "notes": [],
                "agent": {"id": "agent-m", "name": "Mia"}}

    app, mod, _ = _app(monkeypatch, turn=turn)
    _seat(mod, ["agent-a", "agent-m"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert "could not finish" in body
    assert "Mia here" in body


def test_the_working_line_names_the_agent(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _seat(mod, ["agent-a"])
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert "event: working" in body
    assert "Ada is working" in body


def test_an_abandoned_round_does_not_unlock_a_newer_one(monkeypatch):
    """The real defect this guards: New chat bumps generation while a round
    is in flight, a fresh send re-claims the room (streaming = True again),
    and the OLD round's finally must leave that newer claim alone. Clearing
    streaming unconditionally would let a third send through onto a session a
    second round already owns: two rounds of tool-running agents at once.
    """
    app, mod, _ = _app(monkeypatch)
    s = _seat(mod, ["agent-a"])

    async def turn(email, agent, messages, names=(), **kw):
        # Mid-round: New chat bumps the generation and a fresh send re-claims
        # the session, exactly as the New chat route will.
        s.generation += 1
        s.streaming = True
        return {"answer": "Ada here", "notes": [],
                "agent": {"id": "agent-a", "name": "Ada"}}

    monkeypatch.setattr(mod, "_turn_for", turn)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert s.streaming is True, "the abandoned round cleared a newer claim"


def test_a_conversation_that_fits_is_sent_whole():
    """The room is permanent. Nothing is dropped while it still fits, or an
    agent forgets what was agreed this morning for no reason."""
    import routes_agent_chat as mod
    turns = []
    for i in range(60):
        turns.append({"role": "user", "content": "ask %d" % i})
        turns.append({"role": "assistant", "agent_name": "Ada",
                      "content": "answer %d" % i})
    got = mod._history_for_round(turns)
    assert len(got) == 120
    assert got[0]["content"] == "ask 0"


def test_a_conversation_that_does_not_fit_keeps_the_recent_end():
    import routes_agent_chat as mod
    big = "x" * 2000
    turns = [{"role": "user", "content": big} for _ in range(40)]
    turns.append({"role": "user", "content": "the newest question"})
    got = mod._history_for_round(turns)
    assert mod._weight(got) <= mod.HISTORY_BUDGET_CHARS + len(big)
    assert got[-1]["content"] == "the newest question"


def test_the_message_being_answered_is_never_the_one_dropped():
    import routes_agent_chat as mod
    turns = [{"role": "assistant", "content": "x" * 30000},
             {"role": "user", "content": "answer me"}]
    got = mod._history_for_round(turns)
    assert got[-1]["content"] == "answer me"


def test_the_summary_rides_in_front_of_the_recent_turns():
    import routes_agent_chat as mod
    got = mod._history_for_round(
        [{"role": "user", "content": "now"}], summary="we agreed on blue")
    assert len(got) == 2
    assert "we agreed on blue" in got[0]["content"]
    assert got[0]["role"] == "assistant"
    assert got[-1]["content"] == "now"


def test_every_agent_still_gets_the_identical_history(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _seat(mod)
    c = TestClient(app)
    for i in range(6):
        c.post("/tasks/agents/chat/send", data={"message": "m%d" % i},
               headers=_hdr())
        c.get("/tasks/agents/chat/stream", headers=_hdr())
    last_two = seen[-2:]
    assert last_two[0]["messages"] == last_two[1]["messages"]


def test_history_for_round_keeps_only_real_turns():
    import routes_agent_chat as mod
    got = mod._history_for_round([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "agent_id": "agent-a", "agent_name": "Ada",
         "content": "hello"},
        {"role": "assistant", "content": "   "},
        {"role": "round", "content": ""},
    ])
    assert got == [{"role": "user", "content": "hi"},
                   {"role": "assistant", "content": "hello"}]


# ---------------------------------------------------------------------------
# Seven agents, one greeting, seven replies of "I'm here, what do you need?".
# Reported with a screenshot 2026-09-14. The room is supposed to read like a
# room of people, and a person who has nothing to add does not announce that
# they have nothing to add.
# ---------------------------------------------------------------------------


def test_the_pass_instruction_forbids_announcing_availability():
    """The exact failure: every agent replying that it is here. Pinned by the
    words, because this is a prompt and the words ARE the mechanism."""
    import routes_agent_chat
    text = routes_agent_chat.PASS_INSTRUCTION.lower()
    assert "pass" in text
    assert "greeting" in text, "nothing tells them to pass on a hello"
    assert "available" in text and "you are here" in text, (
        "nothing forbids the exact reply that was sent seven times")
    assert "true of every assistant" in text, (
        "nothing gives them the test for whether a reply is worth making")


def test_passing_is_still_only_offered_when_nobody_was_named():
    """Naming an agent means you asked it, so it must answer. Strengthening
    the pass wording must not let a named agent duck the question."""
    agents = [{"id": "a", "name": "Ada"}, {"id": "m", "name": "Mia"}]
    import routes_agent_chat
    named, may_pass = routes_agent_chat._speakers_for("hey mia what is in my inbox", agents)
    assert [a["id"] for a in named] == ["m"]
    assert may_pass is False, "a named agent was allowed to pass"

    everyone, may_pass = routes_agent_chat._speakers_for("hey everyone", agents)
    assert len(everyone) == 2
    assert may_pass is True


# ---------------------------------------------------------------------------
# The summariser writes the one string every later round reads. It runs on the
# agent's own model now, which means it can come back with the free pool's
# busy sentence as ordinary content rather than raising, and the busy sentence
# stored here is permanent: the room prepends it to every round after it.
# ---------------------------------------------------------------------------


def _long_room(mod, summary="we agreed on blue"):
    """A session over the history budget, so _keep_within_budget summarises."""
    s = mod.store.RoomSession()
    s.summary = summary
    s.messages = [{"role": "user", "content": "x" * 9000},
                  {"role": "assistant", "content": "y" * 9000},
                  {"role": "user", "content": "z" * 9000},
                  {"role": "user", "content": "the newest question"}]
    return s


async def _busy_budget_round(monkeypatch, answer):
    """Run _keep_within_budget with _chat answering `answer`. Returns the
    session, so the caller can say what its summary should be."""
    import routes_agent_chat as mod

    async def fake_resolve(email, agent_id):
        return "tok", [], "all"

    async def fake_chat(**kwargs):
        return answer, []

    monkeypatch.setattr(mod, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(mod, "_chat", fake_chat)
    s = _long_room(mod)
    await mod._keep_within_budget(EMAIL, s, [ADA])
    return s


async def test_a_busy_free_pool_does_not_become_the_rooms_notes(monkeypatch):
    """_chat returns the busy sentence as content, so without a check it is
    stored as the summary and read back as "notes so far" for good."""
    s = await _busy_budget_round(monkeypatch, agent_runner.FREE_POOL_EXHAUSTED)
    assert s.summary == "we agreed on blue"


async def test_the_routers_busy_sentence_is_not_the_rooms_notes_either(
        monkeypatch):
    s = await _busy_budget_round(monkeypatch, agent_runner.ROUTER_EXHAUSTED)
    assert s.summary == "we agreed on blue"


async def test_a_real_summary_still_replaces_the_notes(monkeypatch):
    """The opposite mistake would be worse: a room whose notes never move on
    because something about the busy check was too broad."""
    s = await _busy_budget_round(monkeypatch, "They settled on green.")
    assert s.summary == "They settled on green."


async def test_a_summariser_that_raises_leaves_the_notes_alone(monkeypatch):
    """_summarise's docstring says it never raises. Its except arm reached
    for a logger this module does not define, so the one path that promise
    exists for was the one that took the round down with it."""
    import routes_agent_chat as mod

    async def fake_resolve(email, agent_id):
        return "tok", [], "all"

    async def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(mod, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(mod, "_chat", boom)
    s = _long_room(mod)
    await mod._keep_within_budget(EMAIL, s, [ADA])
    assert s.summary == "we agreed on blue"


# --- a bare PASS must never reach the person --------------------------------
# Seen live in the owner's own thread, 2026-09-24: a bubble reading "Ada /
# PASS". One message with the content "PASS" was stored in
# tasks.agent_chats.messages, so it redrew on every load.
#
# The cause is the `may_pass and` guard on the skip: an agent that says PASS
# on a round where it was NOT offered the choice falls past the skip and its
# answer is stored verbatim. Naming an agent, a short follow on, the owner
# rung and the everybody-passed fallback are all may_pass=False.
#
# PASS is a word in a protocol between this code and the model. It is never
# something a person should read.


async def _passes(email, agent, messages, names=(), **kw):
    return {"answer": "PASS", "notes": [],
            "agent": {"id": agent["id"], "name": agent["name"]}}


def test_a_named_agent_that_passes_anyway_does_not_show_the_word(monkeypatch):
    """Naming somebody is a question put to them, so they are not offered the
    pass. If the model says it regardless, the person must not be shown the
    token."""
    app, mod, _ = _app(monkeypatch, turn=_passes)
    _seat(mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "ada what do you think"},
           headers=_hdr())

    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text

    assert "PASS" not in body, body[:400]


def test_a_named_agent_that_passes_anyway_stores_nothing(monkeypatch):
    """The bubble redrew on every load because the word was saved as the
    agent's answer. Nothing may reach s.messages."""
    app, mod, _ = _app(monkeypatch, turn=_passes)
    _seat(mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "ada what do you think"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())

    s = mod.store.get_session(EMAIL)
    assert not [m for m in s.messages
                if (m.get("content") or "").strip().upper() == "PASS"], s.messages


def test_the_person_is_still_told_the_agent_had_nothing(monkeypatch):
    """Silence is worse than the token. A question asked directly and
    answered with nothing must say so, the same way the room does when
    everybody passes."""
    app, mod, _ = _app(monkeypatch, turn=_passes)
    _seat(mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "ada what do you think"},
           headers=_hdr())

    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text

    assert "nothing to add" in body.lower(), body[:400]
    assert "Ada" in body


# --- a private word with one agent ------------------------------------------
# "add that if he click that it will change the chat to name of the agent itl
# not be global." Naming an agent in the room already routed the answer, but
# the question and the reply stayed where every other agent read them.

def test_in_a_private_chat_only_that_agent_answers(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "hello", "agent": "agent-a"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=_hdr())
    assert [t["agent"] for t in seen] == ["agent-a"]


def test_the_private_agent_answers_without_being_named(monkeypatch):
    """In the room a bare "hello" is put to everyone and they may pass. A
    conversation with one agent is not one they can sit out."""
    app, mod, seen = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "hello", "agent": "agent-m"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream?agent=agent-m", headers=_hdr()).text
    assert [t["agent"] for t in seen] == ["agent-m"]
    assert "Mia here" in body


def test_the_room_still_hears_everybody(monkeypatch):
    """The default is unchanged: no agent named, everyone hears it."""
    app, mod, seen = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert [t["agent"] for t in seen] == ["agent-a", "agent-m"]


def test_a_private_chat_is_not_in_the_room(monkeypatch):
    """The point of private. What was said to one agent must not turn up as
    context for the others."""
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "just between us", "agent": "agent-a"}, headers=_hdr())
    room = mod.store.get_session(EMAIL)
    said = " ".join(str(m.get("content", "")) for m in room.messages)
    assert "just between us" not in said


def test_each_agent_keeps_its_own_private_thread(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "for Ada", "agent": "agent-a"}, headers=_hdr())
    mia = mod.store.get_session(EMAIL, "agent-m")
    said = " ".join(str(m.get("content", "")) for m in mia.messages)
    assert "for Ada" not in said


def test_the_private_thread_is_what_the_panel_asks_for(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "for Ada only", "agent": "agent-a"}, headers=_hdr())
    mine = c.get("/tasks/agents/chat/thread?agent=agent-a", headers=_hdr()).text
    room = c.get("/tasks/agents/chat/thread", headers=_hdr()).text
    assert "for Ada only" in mine
    assert "for Ada only" not in room


def test_clearing_a_private_chat_leaves_the_room_alone(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "in the room"}, headers=_hdr())
    c.post("/tasks/agents/chat/clear", data={"agent": "agent-a"}, headers=_hdr())
    room = mod.store.get_session(EMAIL)
    said = " ".join(str(m.get("content", "")) for m in room.messages)
    assert "in the room" in said


def _live_job(monkeypatch, mod, error=None):
    """The person's running job, as agent_job_store.cancel_live finds it,
    and what the worker and the feed are told when it is stopped."""
    got = {"cancel_live": [], "worker": [], "events": []}

    async def cancel_live(email):
        got["cancel_live"].append(email)
        if error is not None:
            raise error
        return [{"job_id": "job-1", "lead_agent_id": "agent-a"}]

    monkeypatch.setattr(mod.job_store, "cancel_live", cancel_live)
    monkeypatch.setattr(mod.agent_job_worker, "cancel",
                        lambda job_id: got["worker"].append(job_id))
    monkeypatch.setattr(mod.agent_events, "publish",
                        lambda event, **kw: got["events"].append((event, kw)))
    return got


def test_new_chat_in_the_room_stops_the_running_job(monkeypatch):
    """New chat takes the card, and its Stop button, away. A job left
    running would post into the fresh conversation and hold the person's
    one running slot with no way to stop it."""
    app, mod, _ = _app(monkeypatch)
    got = _live_job(monkeypatch, mod)
    r = TestClient(app).post("/tasks/agents/chat/clear", headers=_hdr())
    assert r.status_code == 200
    assert got["cancel_live"] == [EMAIL]
    assert got["worker"] == ["job-1"]
    assert got["events"] == [("job_finished", {
        "agent_id": "agent-a", "user_email": EMAIL, "job_id": "job-1",
        "status": "cancelled"})]


def test_clearing_a_private_chat_leaves_a_running_job_alone(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    got = _live_job(monkeypatch, mod)
    TestClient(app).post("/tasks/agents/chat/clear",
                         data={"agent": "agent-a"}, headers=_hdr())
    assert got["cancel_live"] == [] and got["worker"] == []


def test_new_chat_still_clears_when_the_job_cannot_be_stopped(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    got = _live_job(monkeypatch, mod, error=RuntimeError("db down"))
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "in the room"},
           headers=_hdr())
    r = c.post("/tasks/agents/chat/clear", headers=_hdr())
    assert r.status_code == 200
    assert mod.store.get_session(EMAIL).messages == []
    assert got["worker"] == []


def test_an_agent_that_is_not_yours_cannot_be_talked_to(monkeypatch):
    """The id comes off a link in a browser. Only agents this person owns are
    in the roster, so anything else has nobody to answer."""
    app, mod, seen = _app(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "hello", "agent": "agent-somebody-elses"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream?agent=agent-somebody-elses", headers=_hdr())
    assert seen == []


# --- the office hears when a bubble goes out and when a meeting opens ------
# The round is not streamed token by token, so the office cannot see a bubble
# arrive unless the round says so. These record turns and events into ONE
# list, so the assertions are about order, not only presence.

def _record(monkeypatch, mod, reply=None):
    log = []

    async def turn(email, agent, messages, names=(), **kw):
        log.append(("turn", agent["id"]))
        if reply is not None:
            return reply(agent)
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    def publish(event, **kw):
        log.append((event, kw.get("agent_id"), kw.get("participants"),
                    kw.get("chars")))

    monkeypatch.setattr(mod, "_turn_for", turn)
    monkeypatch.setattr(mod.agent_events, "publish", publish)
    return log


def _say(app, message):
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": message}, headers=_hdr())
    return c.get("/tasks/agents/chat/stream", headers=_hdr()).text


def _speaking(log):
    return [e[1] for e in log if e[0] == "speaking_started"]


def test_a_meeting_opens_each_bubble_is_announced_then_it_closes(monkeypatch):
    # "hi team" reaches both agents (agent_routing: ROUTE_COLLECTIVE), which
    # is a meeting however it was routed: more than one speaker.
    app, mod, _ = _app(monkeypatch)
    log = _record(monkeypatch, mod)
    _say(app, "hi team")
    assert log == [
        ("meeting_started", "agent-a", ["agent-a", "agent-m"], None),
        ("turn", "agent-a"),
        ("speaking_started", "agent-a", None, len("Ada here")),
        ("turn", "agent-m"),
        ("speaking_started", "agent-m", None, len("Mia here")),
        ("meeting_ended", "agent-m", None, None),
    ]


def test_one_named_agent_is_not_a_meeting(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    log = _record(monkeypatch, mod)
    _say(app, "Ada, hi")
    assert log == [("turn", "agent-a"),
                   ("speaking_started", "agent-a", None, len("Ada here"))]


def test_a_failed_turn_is_not_announced_as_speech(monkeypatch):
    app, mod, _ = _app(monkeypatch)

    def reply(agent):
        answer = (mod._turn_failed_sentence(agent["name"])
                  if agent["id"] == "agent-a" else "Mia here")
        return {"answer": answer, "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    # The real failure sentence, so this is a turn the round recognises as
    # failed rather than an ordinary answer that happens to sound like one.
    assert mod._failure_reason("Ada", mod._turn_failed_sentence("Ada"))
    log = _record(monkeypatch, mod, reply)
    _say(app, "hi team")
    assert ("turn", "agent-a") in log
    assert _speaking(log) == ["agent-m"]


def test_a_turn_that_raises_still_closes_the_meeting(monkeypatch):
    app, mod, _ = _app(monkeypatch)

    def reply(agent):
        if agent["id"] == "agent-m":
            raise RuntimeError("boom")
        return {"answer": "Ada here", "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    log = _record(monkeypatch, mod, reply)
    # Today the error escapes the stream (the test client re-raises it inside
    # an ExceptionGroup). This test is not about that; it is about the office
    # not being left with a meeting that never ends.
    try:
        _say(app, "hi team")
    except Exception:                                       # noqa: BLE001
        pass
    assert log[0][0] == "meeting_started"
    assert log[-1] == ("meeting_ended", "agent-m", None, None)


def test_a_pass_is_not_announced_as_speech(monkeypatch):
    app, mod, _ = _app(monkeypatch)

    def reply(agent):
        answer = "PASS" if agent["id"] == "agent-a" else "Mia here"
        return {"answer": answer, "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    log = _record(monkeypatch, mod, reply)
    _say(app, "hi team")
    assert _speaking(log) == ["agent-m"]


def test_the_fallback_bubble_is_announced_inside_the_meeting(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    calls = []

    def reply(agent):
        # Both pass when offered the choice; the fallback re-asks Ada.
        calls.append(agent["id"])
        answer = "PASS" if len(calls) <= 2 else "Ada here"
        return {"answer": answer, "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    log = _record(monkeypatch, mod, reply)
    _say(app, "hi team")
    assert [e[0] for e in log] == ["meeting_started", "turn", "turn", "turn",
                                   "speaking_started", "meeting_ended"]
    assert _speaking(log) == ["agent-a"]


def test_an_agent_asking_a_question_is_speaking(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    calls = [{"id": "call-1", "function": {"name": "send_email",
                                           "arguments": "{}"}}]

    def reply(agent):
        out = {"answer": f'{agent["name"]} here', "notes": [],
               "agent": {"id": agent["id"], "name": agent["name"]}}
        if agent["id"] == "agent-a":
            out["answer"] = "May I send this?"
            out["pending"] = {"agent_id": "agent-a", "user_email": EMAIL,
                              "calls": calls, "conversation": []}
        return out

    log = _record(monkeypatch, mod, reply)
    body = _say(app, "hi team")
    assert "May I send this?" in body
    assert ("speaking_started", "agent-a", None,
            len("May I send this?")) in log
    assert _speaking(log) == ["agent-a", "agent-m"]


# --- a team request becomes a plan card --------------------------------------
# The lead triages every message to the whole team (agent_job_triage). A plan
# comes back as a card with Start and Cancel, and nobody answers yet: the work
# runs only once the person presses Start. Anything short of a stored plan,
# however it fails, is today's round.

PLAN = [{"agent_id": "agent-m", "task": "Find the three latest reports."},
        {"agent_id": "agent-a", "task": "Compare them."}]


#: Four words or more: a message the round puts to the lead at all (see
#: routes_agent_chat.MIN_TRIAGE_WORDS). "hi team" is not one.
CHATTY = "hi team, how is everyone doing"


def _jobs(monkeypatch, steps=PLAN, triage_error=None, store_error=None,
          live=False):
    """Triage and the job store, faked on the modules the round uses.
    Returns what each was called with. `live` is whether the person has a
    job running already: True, False or an exception to raise."""
    import agent_job_store
    import agent_job_triage
    calls = {"triage": [], "create": [], "live": []}

    async def has_live_job(email):
        calls["live"].append(email)
        if isinstance(live, BaseException):
            raise live
        return live

    async def triage(email, lead, roster, history):
        calls["triage"].append({"lead": lead["id"],
                                "roster": [a["id"] for a in roster],
                                "history": history})
        if triage_error is not None:
            raise triage_error
        return steps

    async def create_proposed(user_email, chat_id, lead_agent_id, request,
                              steps):
        calls["create"].append({"email": user_email, "chat_id": chat_id,
                                "lead": lead_agent_id, "request": request,
                                "steps": steps})
        if store_error is not None:
            raise store_error
        return "job-1"

    monkeypatch.setattr(agent_job_triage, "triage", triage)
    monkeypatch.setattr(agent_job_store, "create_proposed", create_proposed)
    monkeypatch.setattr(agent_job_store, "has_live_job", has_live_job)
    return calls


def test_a_team_request_with_a_plan_becomes_a_card_and_nobody_answers(
        monkeypatch):
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    log = _record(monkeypatch, mod)
    body = _say(app, "prepare the weekly summary")

    assert ("turn", "agent-a") not in log and ("turn", "agent-m") not in log, (
        "a speaker ran")
    assert body.count('class="am agent ajob"') == 1
    assert 'id="job-job-1"' in body
    assert "Mia: Find the three latest reports." in body
    assert "Ada: Compare them." in body
    assert 'hx-post="/tasks/agents/jobs/job-1/start"' in body
    assert "Ada here" not in body and "Mia here" not in body
    # The wait for the lead is visible.
    assert "Ada is working" in body

    # The lead here is the first agent (no team lead, no manager role).
    assert calls["triage"][0]["lead"] == "agent-a"
    assert calls["triage"][0]["roster"] == ["agent-a", "agent-m"]
    assert calls["triage"][0]["history"][-1] == {
        "role": "user", "content": "prepare the weekly summary"}
    assert calls["create"] == [{"email": EMAIL, "chat_id": "chat-1",
                                "lead": "agent-a",
                                "request": "prepare the weekly summary",
                                "steps": PLAN}]

    s = mod.store.get_session(EMAIL)
    stored = [m for m in s.messages if m.get("role") == "job"]
    assert len(stored) == 1
    assert stored[0]["job_id"] == "job-1"
    assert stored[0]["agent_name"] == "Ada"
    assert [(st["name"], st["task"]) for st in stored[0]["steps"]] == [
        ("Mia", "Find the three latest reports."), ("Ada", "Compare them.")]
    assert not [m for m in s.messages if m.get("role") == "assistant"]
    # The reload draws the same card the stream did.
    assert "Mia: Find the three latest reports." in mod.render.thread(
        s.messages)


def test_the_card_is_the_lead_speaking_and_no_meeting_is_called(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    _jobs(monkeypatch)
    log = _record(monkeypatch, mod)
    _say(app, "prepare the weekly summary")
    assert len(log) == 1, log
    assert log[0][0] == "speaking_started"
    assert log[0][1] == "agent-a"
    assert log[0][3] and log[0][3] > 0


def test_a_triage_that_finds_no_job_leaves_the_round_as_it_was(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    calls = _jobs(monkeypatch, steps=None)
    log = _record(monkeypatch, mod)
    body = _say(app, CHATTY)
    assert len(calls["triage"]) == 1
    assert calls["create"] == []
    assert body.count('class="am agent"') == 2
    assert log == [
        ("meeting_started", "agent-a", ["agent-a", "agent-m"], None),
        ("turn", "agent-a"),
        ("speaking_started", "agent-a", None, len("Ada here")),
        ("turn", "agent-m"),
        ("speaking_started", "agent-m", None, len("Mia here")),
        ("meeting_ended", "agent-m", None, None),
    ]


def test_a_triage_that_raises_leaves_the_round_as_it_was(monkeypatch):
    """triage() promises never to raise. The round must not depend on it."""
    app, mod, _ = _app(monkeypatch)
    calls = _jobs(monkeypatch, triage_error=RuntimeError("model down"))
    body = _say(app, CHATTY)
    assert len(calls["triage"]) == 1
    assert "Ada here" in body and "Mia here" in body
    assert "ajob" not in body


def test_a_plan_that_cannot_be_stored_leaves_the_round_as_it_was(monkeypatch):
    """A card without its row would offer a Start that finds nothing."""
    app, mod, _ = _app(monkeypatch)
    calls = _jobs(monkeypatch, store_error=RuntimeError("db down"))
    body = _say(app, CHATTY)
    assert len(calls["create"]) == 1
    assert "Ada here" in body and "Mia here" in body
    assert "ajob" not in body
    s = mod.store.get_session(EMAIL)
    assert not [m for m in s.messages if m.get("role") == "job"]


def test_a_named_agent_is_never_triaged(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    _say(app, "Ada, hi")
    assert calls["triage"] == []
    assert [t["agent"] for t in seen] == ["agent-a"]


def test_a_private_conversation_is_never_triaged(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "prepare the weekly summary", "agent": "agent-a"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=_hdr())
    assert calls["triage"] == []
    assert [t["agent"] for t in seen] == ["agent-a"]


def test_a_yes_to_a_waiting_question_is_never_triaged(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    answered = []

    async def apply(email, s, ask_id, yes, agents):
        answered.append((ask_id, yes))
        return "applied"

    monkeypatch.setattr(mod, "_apply_pending_answer", apply)
    mod.store.get_session(EMAIL).pending = {"ask-1": {"agent_id": "agent-a"}}
    _say(app, "yes")
    assert calls["triage"] == []
    assert answered == [("ask-1", True)]


def test_a_short_message_is_never_triaged(monkeypatch):
    """A greeting or a thank you to the team is never a job, and the triage
    is a model call the person waits on before anybody answers."""
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    body = _say(app, "thanks everyone")
    assert calls["triage"] == []
    assert "Ada here" in body and "Mia here" in body
    assert len("prepare the weekly summary".split()) == mod.MIN_TRIAGE_WORDS


def test_a_person_with_a_job_running_is_not_triaged(monkeypatch):
    """A plan could not be started while one runs (one job at a time), so
    proposing it would cost a call and offer a Start that is refused."""
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch, live=True)
    body = _say(app, "prepare the weekly summary")
    assert calls["live"] == [EMAIL]
    assert calls["triage"] == []
    assert "Ada here" in body and "Mia here" in body


def test_a_running_job_that_cannot_be_checked_skips_the_triage(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch, live=RuntimeError("db down"))
    body = _say(app, "prepare the weekly summary")
    assert calls["triage"] == []
    assert "Ada here" in body and "Mia here" in body


def test_jobs_switched_off_never_triage(monkeypatch):
    monkeypatch.setenv("AGENT_JOBS_ENABLED", "false")
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    body = _say(app, "prepare the weekly summary")
    assert mod.JOBS_ENABLED is False
    assert calls["triage"] == []
    assert "Ada here" in body and "Mia here" in body


def test_jobs_are_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("AGENT_JOBS_ENABLED", raising=False)
    _unused, mod, _ = _app(monkeypatch)
    assert mod.JOBS_ENABLED is True


def test_one_agent_is_never_triaged(monkeypatch):
    app, mod, seen = _app(monkeypatch, agents=(ADA,))
    calls = _jobs(monkeypatch)
    body = _say(app, "prepare the weekly summary")
    assert calls["triage"] == []
    assert "Ada here" in body


# --- Jev decides first ------------------------------------------------------
# Inside the same gate as the triage, Jev is asked whether the message is one
# answer or a job, and who should take it (agent_decider). Sure it is one
# answer by one agent: only that agent replies, and nobody triages. Every
# other outcome, including Jev failing, is the round above, unchanged.

def _jev(monkeypatch, path=None, agent_id="agent-m", error=None):
    import agent_decider
    calls = []

    async def decide(email, chat_id, message, history, agents):
        calls.append({"email": email, "chat_id": chat_id, "message": message,
                      "roster": [a["id"] for a in agents],
                      "history": history})
        if error is not None:
            raise error
        if path is None:
            return None
        return agent_decider.Decision(path=path, kind="answer",
                                      kind_confidence=0.95,
                                      agent_id=agent_id,
                                      agent_confidence=0.9)

    monkeypatch.setattr(agent_decider, "decide", decide)
    return calls


def test_jev_sure_of_one_agent_means_only_that_agent_answers(monkeypatch):
    import agent_decider
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    jev = _jev(monkeypatch, path=agent_decider.PATH_ONE_AGENT)
    log = _record(monkeypatch, mod)
    body = _say(app, CHATTY)

    assert len(jev) == 1
    assert jev[0]["email"] == EMAIL and jev[0]["message"] == CHATTY
    assert jev[0]["roster"] == ["agent-a", "agent-m"]
    assert calls["triage"] == []
    # One speaker is not a meeting, and nobody is offered a pass.
    assert log == [("turn", "agent-m"),
                   ("speaking_started", "agent-m", None, len("Mia here"))]
    assert "Mia here" in body and "Ada here" not in body


def test_the_agent_jev_chose_may_not_pass(monkeypatch):
    import agent_decider
    app, mod, seen = _app(monkeypatch)
    _jobs(monkeypatch)
    _jev(monkeypatch, path=agent_decider.PATH_ONE_AGENT)
    _say(app, CHATTY)
    assert [t["agent"] for t in seen] == ["agent-m"]
    assert seen[0]["messages"][-1]["content"] != mod.PASS_INSTRUCTION


def test_jev_sure_of_a_job_leaves_the_plan_to_the_lead(monkeypatch):
    import agent_decider
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch)
    _jev(monkeypatch, path=agent_decider.PATH_PLAN)
    body = _say(app, "prepare the weekly summary")
    assert len(calls["triage"]) == 1
    assert 'id="job-job-1"' in body


def test_jev_unsure_leaves_the_round_as_it_was(monkeypatch):
    import agent_decider
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch, steps=None)
    _jev(monkeypatch, path=agent_decider.PATH_FALLBACK)
    body = _say(app, CHATTY)
    assert len(calls["triage"]) == 1
    assert "Ada here" in body and "Mia here" in body


def test_jev_raising_leaves_the_round_as_it_was(monkeypatch):
    """decide() promises never to raise. The round does not lean on it."""
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch, steps=None)
    _jev(monkeypatch, error=RuntimeError("jev down"))
    body = _say(app, CHATTY)
    assert len(calls["triage"]) == 1
    assert "Ada here" in body and "Mia here" in body


def test_jev_naming_someone_not_in_the_room_is_ignored(monkeypatch):
    import agent_decider
    app, mod, seen = _app(monkeypatch)
    calls = _jobs(monkeypatch, steps=None)
    _jev(monkeypatch, path=agent_decider.PATH_ONE_AGENT, agent_id="agent-x")
    body = _say(app, CHATTY)
    assert len(calls["triage"]) == 1
    assert "Ada here" in body and "Mia here" in body


@pytest.mark.parametrize("message", ["Ada, can you check the weekly numbers",
                                     "thanks everyone"])
def test_jev_is_only_asked_inside_the_team_gate(monkeypatch, message):
    app, mod, seen = _app(monkeypatch)
    _jobs(monkeypatch)
    jev = _jev(monkeypatch)
    _say(app, message)
    assert jev == []


def test_jev_is_not_asked_while_a_job_runs(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _jobs(monkeypatch, live=True)
    jev = _jev(monkeypatch)
    _say(app, "prepare the weekly summary")
    assert jev == []


def test_jev_is_not_asked_in_a_private_conversation(monkeypatch):
    app, mod, seen = _app(monkeypatch)
    _jobs(monkeypatch)
    jev = _jev(monkeypatch)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "prepare the weekly summary", "agent": "agent-a"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream?agent=agent-a", headers=_hdr())
    assert jev == []


# --- the thread draws the card with the job's live status -------------------

def _stored_card(mod):
    s = mod.store.get_session(EMAIL)
    s.chat_id = "chat-1"
    s.messages = [
        {"role": "user", "content": "prepare the weekly summary",
         "turn_id": "abc123def456"},
        {"role": "job", "job_id": "job-1", "agent_id": "agent-a",
         "agent_name": "Ada",
         "steps": [{"agent_id": "agent-m", "name": "Mia",
                    "task": "Find the three latest reports."},
                   {"agent_id": "agent-a", "name": "Ada",
                    "task": "Compare them."}]}]
    return s


def test_the_thread_shows_a_running_job_with_who_is_working(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    import agent_job_store
    asked = []

    async def jobs_for_chat(user_email, chat_id):
        asked.append((user_email, chat_id))
        return {"job-1": {"status": "running", "done": 1, "total": 2,
                          "current_agent_id": "agent-a"}}

    monkeypatch.setattr(agent_job_store, "jobs_for_chat", jobs_for_chat)
    _stored_card(mod)
    html = TestClient(app).get("/tasks/agents/chat/thread",
                               headers=_hdr()).text
    assert asked == [(EMAIL, "chat-1")]
    assert "Running: step 2 of 2, Ada is working" in html
    assert ">Stop</button>" in html


def test_the_thread_still_draws_when_the_jobs_cannot_be_read(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    import agent_job_store
    asked = []

    async def jobs_for_chat(user_email, chat_id):
        asked.append(chat_id)
        raise RuntimeError("db down")

    monkeypatch.setattr(agent_job_store, "jobs_for_chat", jobs_for_chat)
    _stored_card(mod)
    r = TestClient(app).get("/tasks/agents/chat/thread", headers=_hdr())
    assert r.status_code == 200
    assert asked == ["chat-1"]
    assert "Mia: Find the three latest reports." in r.text
    assert "<button" not in r.text


def test_a_thread_without_a_card_does_not_read_the_jobs(monkeypatch):
    """Every page load draws the thread. A conversation with no plan in it
    has nothing to ask the jobs table about."""
    app, mod, _ = _app(monkeypatch)
    import agent_job_store
    asked = []

    async def jobs_for_chat(user_email, chat_id):
        asked.append(chat_id)
        return {}

    monkeypatch.setattr(agent_job_store, "jobs_for_chat", jobs_for_chat)
    s = mod.store.get_session(EMAIL)
    s.chat_id = "chat-1"
    s.messages = [{"role": "user", "content": "hi"},
                  {"role": "assistant", "agent_name": "Ada", "content": "hello"}]
    html = TestClient(app).get("/tasks/agents/chat/thread",
                               headers=_hdr()).text
    assert "hello" in html
    assert asked == []
