"""One message, one bubble per agent, in order.

The assertion that matters most is test_agents_do_not_see_each_other: feeding
agents each other's replies is what taught the model to invent whole exchanges
between agents, and nothing but this test stops that coming back.
"""
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

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

    async def default_turn(email, agent, messages, names=()):
        seen.append({"agent": agent["id"], "messages": [dict(m) for m in messages]})
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return list(agents)

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn or default_turn)
    # The store's SQL half needs a real Postgres. Swap it out so these tests
    # measure the round rather than the "database is down" path.
    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)

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
    assert s.messages[-1] == {"role": "user", "content": "hi team"}


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
    async def turn(email, agent, messages, names=()):
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

    async def turn(email, agent, messages, names=()):
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
