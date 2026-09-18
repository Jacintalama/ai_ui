"""Yes and No on an agent that stopped to ask.

The security property under test is that the held conversation never leaves the
server: the browser is handed tool names and arguments, and hands back an id
and an answer.
"""
import importlib
import re

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


def _ask(app, room=("agent-a", "agent-m"), message="email the boss"):
    c = TestClient(app)
    import routes_agent_chat as mod
    c.post("/tasks/agents/chat/send", data={"message": message},
           headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    return c, body


def _questions(mod):
    """The ids of the questions waiting for an answer, oldest first.

    One per question, not one per agent: the same agent can be waiting on two.
    """
    return list(mod.store.get_session(EMAIL).pending)


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
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr())
    assert r.status_code == 200
    assert len(resumed) == 1
    assert resumed[0]["agent_id"] == "agent-a"
    assert resumed[0]["approved"] is True
    assert resumed[0]["conversation"] == HELD
    assert "Sent it." in r.text


# Typing the answer is pressing the button. Ralph, with a screenshot,
# 2026-09-18: Rex asked to apply a change, he typed "Yes", and because "yes"
# names nobody it went to all seven agents. Every one of them passed, the
# panel said nobody had anything to add, and the change he had just approved
# was never applied.

def test_typing_yes_answers_the_question_that_is_waiting(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/send", data={"message": "yes"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert [r["approved"] for r in resumed] == [True], (
        "the typed answer never reached the agent that asked")
    assert resumed[0]["agent_id"] == "agent-a"
    assert "Sent it." in body
    assert not _questions(mod), "the question is spent and must not linger"


def test_typing_no_refuses_it(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/send", data={"message": "no"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert [r["approved"] for r in resumed] == [False]
    assert "I did not run that." in body


def test_a_typed_yes_never_becomes_a_message_for_the_room(monkeypatch):
    """The other agents must not be asked. Seven turns for one word is what
    the room cost, and one of them could answer as though it had been asked
    to do the thing the person was approving."""
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    body = c.post("/tasks/agents/chat/send", data={"message": "yes"},
                  headers=_hdr()).text
    body += c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert "Mia here" not in body, "the room answered an approval"


def test_yes_with_a_subject_of_its_own_is_not_an_approval(monkeypatch):
    """"yes, but send it tomorrow" is an instruction. Reading it as a bare
    approval would run the tool the person was in the middle of changing."""
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/send",
           data={"message": "yes but send it tomorrow instead please"},
           headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert resumed == [], "a sentence was treated as a bare yes"
    assert _questions(mod), "the question must still be waiting"


def test_with_two_questions_waiting_a_typed_yes_asks_which(monkeypatch):
    """Which tool runs is not a coin toss. Two agents waiting and one word
    means the buttons decide it."""
    async def both_ask(email, agent, messages, names=()):
        return {"answer": "May I send this?", "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]},
                "pending": {"agent_id": agent["id"], "user_email": EMAIL,
                            "calls": CALLS, "conversation": HELD}}

    app, mod, resumed = _app(monkeypatch, both_ask)
    c, _ = _ask(app)
    assert len(_questions(mod)) == 2
    c.post("/tasks/agents/chat/send", data={"message": "yes"}, headers=_hdr())
    body = c.get("/tasks/agents/chat/stream", headers=_hdr()).text
    assert resumed == [], "it guessed which question to answer"
    assert "Yes or No" in body
    assert len(_questions(mod)) == 2, "both questions stay waiting"


def test_no_refuses_and_says_so(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "no"},
               headers=_hdr())
    assert resumed[0]["approved"] is False
    assert "did not run that" in r.text


def test_answering_twice_does_not_run_it_twice(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    spent = _questions(mod)[0]
    c.post("/tasks/agents/chat/approve",
           data={"ask_id": spent, "approved": "yes"}, headers=_hdr())
    again = c.post("/tasks/agents/chat/approve",
                   data={"ask_id": spent, "approved": "yes"},
                   headers=_hdr())
    assert len(resumed) == 1
    assert "no longer waiting" in again.text


def test_answering_a_question_nobody_asked_does_nothing(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c = TestClient(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": "a-question-nobody-asked", "approved": "yes"},
               headers=_hdr())
    assert resumed == []
    assert "no longer waiting" in r.text


def test_someone_elses_session_cannot_answer_your_question(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr("stranger@example.com"))
    assert resumed == []
    assert "no longer waiting" in r.text


def test_an_answered_question_leaves_the_thread(monkeypatch):
    app, mod, _ = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    c.post("/tasks/agents/chat/approve",
           data={"ask_id": _questions(mod)[0], "approved": "yes"},
           headers=_hdr())
    replayed = mod.render.thread(mod.store.get_session(EMAIL).messages)
    assert ">Yes<" not in replayed
    assert "Sent it." in replayed


def test_asking_again_holds_the_raw_payload_but_shows_only_the_page_shape(
        monkeypatch):
    async def resume_turn(user_email, agent_id, conversation, calls, approved):
        return {"answer": "One more check first.", "notes": [],
                "pending": {"agent_id": agent_id, "user_email": EMAIL,
                            "calls": CALLS, "conversation": HELD}}

    app, mod, _ = _app(monkeypatch, _asking_turn())
    monkeypatch.setattr(mod, "_resume_turn", resume_turn)
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr())
    # The raw payload, id and all, is held server side for the next resume.
    held = mod.store.get_session(EMAIL).pending[_questions(mod)[0]]
    assert held["calls"][0]["id"] == "call-1"
    # The id never reaches the page. Only the page-shaped calls do.
    assert "call-1" not in r.text
    assert "send_email" in r.text


def test_a_failed_resume_clears_the_question_and_does_not_restore_it(
        monkeypatch):
    async def resume_turn(user_email, agent_id, conversation, calls, approved):
        raise RuntimeError("boom")

    app, mod, _ = _app(monkeypatch, _asking_turn())
    monkeypatch.setattr(mod, "_resume_turn", resume_turn)
    c, _ = _ask(app)
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr())
    assert r.status_code == 200
    assert "no longer waiting" in r.text
    s = mod.store.get_session(EMAIL)
    assert s.pending == {}
    assert not any(m.get("agent_id") == "agent-a" and m.get("awaiting")
                   for m in s.messages)


def test_a_click_mid_round_does_not_run_two_turns_at_once(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    c, _ = _ask(app)
    mod.store.get_session(EMAIL).streaming = True
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr())
    assert resumed == []
    assert ">Yes<" in r.text and ">No<" in r.text


# --- one agent, two questions --------------------------------------------
# Nothing stops a second message going out while the first question is still
# unanswered, so the same agent can be waiting on two answers. Keyed by the
# agent, the second question overwrote the first: a held conversation thrown
# away without anybody being told, and two bubbles on the page carrying the
# same id, so htmx sent the second one's Yes at the first one's element.

def test_two_questions_from_one_agent_get_their_own_ids(monkeypatch):
    app, mod, _ = _app(monkeypatch, _asking_turn())
    _ask(app, room=("agent-a",), message="email the boss")
    _ask(app, room=("agent-a",), message="and the other one too")
    ids = _questions(mod)
    assert len(ids) == 2, "the second question replaced the first"
    assert ids[0] != ids[1]


def test_the_page_can_tell_two_questions_from_one_agent_apart(monkeypatch):
    app, mod, _ = _app(monkeypatch, _asking_turn())
    _ask(app, room=("agent-a",), message="email the boss")
    _ask(app, room=("agent-a",), message="and the other one too")
    html = mod.render.thread(mod.store.get_session(EMAIL).messages)
    ids = re.findall(r'id="(await-[^"]+)"', html)
    assert len(ids) == 2, ids
    assert len(set(ids)) == 2, "both Yes buttons point at the same element"


def test_answering_the_second_question_leaves_the_first_alone(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    _ask(app, room=("agent-a",), message="email the boss")
    c, _ = _ask(app, room=("agent-a",), message="and the other one too")
    first, second = _questions(mod)

    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": second, "approved": "yes"}, headers=_hdr())
    assert r.status_code == 200
    assert len(resumed) == 1
    # The agent is still resolved, from the payload rather than the form.
    assert resumed[0]["agent_id"] == "agent-a"

    s = mod.store.get_session(EMAIL)
    assert list(s.pending) == [first], "the unanswered question was lost"
    still_asked = [m for m in s.messages
                   if isinstance(m.get("awaiting"), dict)]
    assert len(still_asked) == 1
    assert still_asked[0]["awaiting"]["ask_id"] == first


def test_the_first_question_can_still_be_answered_afterwards(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _asking_turn())
    _ask(app, room=("agent-a",), message="email the boss")
    c, _ = _ask(app, room=("agent-a",), message="and the other one too")
    first, second = _questions(mod)
    c.post("/tasks/agents/chat/approve",
           data={"ask_id": second, "approved": "yes"}, headers=_hdr())
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": first, "approved": "no"}, headers=_hdr())
    assert len(resumed) == 2
    assert resumed[1]["approved"] is False
    assert "did not run that" in r.text
    assert mod.store.get_session(EMAIL).pending == {}


# --- a question from the everybody-passed fallback ------------------------
# Every agent passes, so the round asks one of them again without the option
# to pass. That agent can decide the answer needs a tool and stop to ask, and
# a turn that stops to ask comes back with a pending payload and no answer at
# all (routes_agent_turn._pending_payload). The fallback only read the answer,
# found it empty, and said "Nobody had anything to add to that." while the
# question was thrown away. Production 2026-09-16 13:37:56 UTC: Rex's run sat
# at waiting and nobody was ever asked.

def _passes_then_asks(answer=""):
    """Passes whenever passing is on offer, and stops to ask when it is not,
    which is exactly the shape _turn_for hands back for a held turn."""
    async def turn(email, agent, messages, names=()):
        offered = any("reply with exactly PASS" in (m.get("content") or "")
                      for m in messages)
        who = {"id": agent["id"], "name": agent["name"]}
        if offered:
            return {"answer": "PASS", "notes": [], "agent": who}
        return {"answer": answer, "agent": who,
                "pending": {"agent_id": agent["id"], "user_email": EMAIL,
                            "calls": CALLS, "conversation": HELD}}
    return turn


def test_a_question_from_the_fallback_reaches_the_page(monkeypatch):
    app, mod, _ = _app(monkeypatch, _passes_then_asks())
    _, body = _ask(app, message="sort out the invoices")
    assert "send_email" in body, "the question never reached the page"
    assert ">Yes<" in body and ">No<" in body
    assert "Nobody had anything to add" not in body, (
        "an agent that stopped to ask was reported as having nothing to say")

    s = mod.store.get_session(EMAIL)
    ids = _questions(mod)
    assert len(ids) == 1, s.pending
    # The raw payload is what the resume needs, held server side as it is for
    # a question asked in the ordinary loop.
    assert s.pending[ids[0]]["conversation"] == HELD
    asked = [m for m in s.messages if isinstance(m.get("awaiting"), dict)]
    assert len(asked) == 1, s.messages
    assert asked[0]["awaiting"]["ask_id"] == ids[0]
    assert asked[0]["agent_id"] == "agent-a"
    assert not any(m.get("role") == "note" for m in s.messages), s.messages
    # A reload offers the same Yes and No.
    assert ">Yes<" in mod.render.thread(s.messages)


def test_a_question_from_the_fallback_can_be_answered(monkeypatch):
    app, mod, resumed = _app(monkeypatch, _passes_then_asks())
    c, _ = _ask(app, message="sort out the invoices")
    r = c.post("/tasks/agents/chat/approve",
               data={"ask_id": _questions(mod)[0], "approved": "yes"},
               headers=_hdr())
    assert len(resumed) == 1
    assert resumed[0]["agent_id"] == "agent-a"
    assert resumed[0]["conversation"] == HELD
    assert "Sent it." in r.text


def test_the_fallback_shows_what_was_said_before_the_question(monkeypatch):
    """Same as the ordinary loop: words before the question get a bubble of
    their own, then the buttons."""
    app, mod, _ = _app(monkeypatch, _passes_then_asks("May I send this?"))
    _, body = _ask(app, message="sort out the invoices")
    assert "May I send this?" in body
    assert body.index("May I send this?") < body.index(">Yes<")
