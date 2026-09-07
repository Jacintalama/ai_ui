"""Yes and No on an agent that stopped to ask.

The security property under test is that the held conversation never leaves the
server: the browser is handed tool names and arguments, and hands back an id
and an answer.
"""
import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

EMAIL = "panel-owner@example.com"
ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
CALLS = [{"id": "call-1",
          "function": {"name": "send_email",
                       "arguments": '{"to": "boss@example.com"}'}}]
HELD = [{"role": "user", "content": "email the boss"},
        {"role": "assistant", "content": "", "tool_calls": CALLS}]


def _hdr(email=EMAIL):
    return {"X-User-Email": email}


def _app(monkeypatch, turn):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)

    resumed = []

    async def agents_for(email):
        return [ADA, MIA]

    async def resume_turn(user_email, agent_id, conversation, calls, approved):
        resumed.append({"agent_id": agent_id, "approved": approved,
                        "conversation": conversation, "calls": calls})
        return {"answer": "Sent it." if approved else "I did not run that.",
                "notes": []}

    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    monkeypatch.setattr(routes_agent_chat, "_resume_turn", resume_turn)
    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)

    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return app, routes_agent_chat, resumed


def _asking_turn(who="agent-a"):
    async def turn(email, agent, messages, names=()):
        if agent["id"] == who:
            return {"answer": "May I send this?", "notes": [],
                    "agent": {"id": agent["id"], "name": agent["name"]},
                    "pending": {"agent_id": agent["id"], "user_email": EMAIL,
                                "calls": CALLS, "conversation": HELD}}
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}
    return turn


def _ask(app, room=("agent-a", "agent-m")):
    c = TestClient(app)
    import routes_agent_chat as mod
    mod.store.get_session(EMAIL).room = list(room)
    c.post("/tasks/agents/chat/send", data={"message": "email the boss"},
           headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    return c, body


def test_the_question_reaches_the_page_with_both_answers(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    assert "send_email" in body
    assert ">Yes<" in body and ">No<" in body


def test_the_held_conversation_never_reaches_the_page(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    # The stream carries the call, so the person can see what they are
    # approving.
    assert "send_email" in body
    # It does not carry the held conversation the resume will replay, nor the
    # owner's email. Both sit next to the calls in _pending_payload.
    assert "email the boss" not in body
    assert "tool_calls" not in body
    assert EMAIL not in body


def test_the_round_carries_on_past_the_agent_that_asked(monkeypatch):
    app, _, _ = _app(monkeypatch, _asking_turn())
    _, body = _ask(app)
    assert "Mia here" in body, "pausing Ada must not silently lose Mia"


def test_yes_resumes_only_that_agent(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    assert r.status_code == 200
    assert len(resumed) == 1
    assert resumed[0]["agent_id"] == "agent-a"
    assert resumed[0]["approved"] is True
    assert resumed[0]["conversation"] == HELD
    assert "Sent it." in r.text


def test_no_refuses_and_says_so(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "no"}, headers=_hdr())
    assert resumed[0]["approved"] is False
    assert "did not run that" in r.text


def test_answering_twice_does_not_run_it_twice(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/approve",
           data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    again = c.post("/tasks/agents/chat/approve",
                   data={"agent_id": "agent-a", "approved": "yes"},
                   headers=_hdr())
    assert len(resumed) == 1
    assert "no longer waiting" in again.text


def test_answering_a_question_nobody_asked_does_nothing(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-m", "approved": "yes"}, headers=_hdr())
    assert resumed == []
    assert "no longer waiting" in r.text


def test_someone_elses_session_cannot_answer_your_question(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"agent_id": "agent-a", "approved": "yes"},
               headers=_hdr("stranger@example.com"))
    assert resumed == []
    assert "no longer waiting" in r.text


def test_an_answered_question_leaves_the_thread(monkeypatch):
    app, mod, _ = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/approve",
           data={"agent_id": "agent-a", "approved": "yes"}, headers=_hdr())
    replayed = mod.render.thread(mod.store.get_session(EMAIL).messages)
    assert ">Yes<" not in replayed
    assert "Sent it." in replayed
