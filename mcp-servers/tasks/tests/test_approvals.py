"""Approvals from anywhere (2026-10-28).

A held question is a row with an id: answered from the Agents page, from
the main chat with a bare yes or no, or over a route; settled before the
call runs so two answers cannot both run it; delivered back where it came
from. Standing rules answer the usual questions inside the tool loop, and
an automation's agent on Ask now asks instead of only reading.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_access
import agent_approvals as ap
import agent_runner
import automation_runner
import routes_agent_turn as rt
import routes_approvals as ra
from auth import CurrentUser, current_user

OWNER = "owner@example.com"
CALL = {"id": "c1", "type": "function",
        "function": {"name": "send_email", "arguments": '{"to": "bo@acme.com", "body": "hi"}'}}
PENDING = {"agent_id": "agent-ada-1", "user_email": OWNER, "calls": [CALL],
           "conversation": [{"role": "user", "content": "send it"}]}


# --- standing rules -----------------------------------------------------------

def test_a_rule_matches_by_tool_pattern_and_argument_text():
    rules = [{"tool": "send_*", "decision": "allow", "when_contains": "@acme.com", "label": "our domain"},
             {"tool": "create_todo", "decision": "allow"}]
    assert ap.rule_decision(rules, "send_email", {"to": "Bo@Acme.com"})["label"] == "our domain"
    assert ap.rule_decision(rules, "send_email", {"to": "bo@other.com"}) is None
    assert ap.rule_decision(rules, "create_todo", {})["decision"] == "allow"
    assert ap.rule_decision(rules, "delete_todo", {}) is None
    assert ap.rule_decision([], "send_email", {}) is None
    assert ap.rule_decision(rules, "", {}) is None


def test_deny_wins_over_allow():
    rules = [{"tool": "*", "decision": "allow"}, {"tool": "delete_*", "decision": "deny", "label": "never delete"}]
    assert ap.rule_decision(rules, "delete_file", {})["decision"] == "deny"
    assert ap.rule_decision(rules, "send_email", {})["decision"] == "allow"


def test_rule_problems_are_sentences():
    assert "Name the tool" in ap.rule_problem("", "allow")
    assert "allows or denies" in ap.rule_problem("send_email", "maybe")
    assert ap.rule_problem("send_email", "allow", "x") == ""


async def test_an_allowing_rule_runs_the_call_without_asking(monkeypatch):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [CALL]},
                                 "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"content": "Sent.", "tool_calls": None},
                             "finish_reason": "stop"}]}
    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_standing_rules", AsyncMock(return_value=[
        {"tool": "send_email", "decision": "allow", "when_contains": "@acme.com"}]))
    ran = AsyncMock(return_value="ok, sent")
    monkeypatch.setattr(agent_runner, "execute_tool_call", ran)
    answer, notes = await agent_runner._chat(
        token="t", model="agent-ada-1", messages=[{"role": "user", "content": "send it"}],
        tool_ids=["gmail"], user_email=OWNER, tool_mode=agent_access.MODE_ASK)
    assert answer == "Sent." and notes == []
    ran.assert_awaited_once()


async def test_a_denying_rule_refuses_and_says_so(monkeypatch):
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [CALL]},
                                 "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"content": "I did not send it.", "tool_calls": None},
                             "finish_reason": "stop"}]}
    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_standing_rules", AsyncMock(return_value=[
        {"tool": "send_*", "decision": "deny", "label": "no sending"}]))
    monkeypatch.setattr(agent_runner, "execute_tool_call", AsyncMock(side_effect=AssertionError("ran")))
    answer, notes = await agent_runner._chat(
        token="t", model="agent-ada-1", messages=[{"role": "user", "content": "send it"}],
        tool_ids=["gmail"], user_email=OWNER, tool_mode=agent_access.MODE_ASK)
    assert answer == "I did not send it."
    assert notes == ["Declined to run send_email, because your rule 'no sending' denies it."]


async def test_with_no_rule_the_question_is_still_held(monkeypatch):
    async def fake_post(payload, token, timeout=None):
        return {"choices": [{"message": {"content": "", "tool_calls": [CALL]},
                             "finish_reason": "tool_calls"}]}
    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_standing_rules", AsyncMock(return_value=[]))
    with pytest.raises(agent_access.ApprovalRequired) as err:
        await agent_runner._chat(
            token="t", model="agent-ada-1", messages=[{"role": "user", "content": "send it"}],
            tool_ids=["gmail"], user_email=OWNER, tool_mode=agent_access.MODE_ASK)
    assert err.value.calls == [CALL]


async def test_rules_are_not_read_for_a_turn_that_cannot_ask(monkeypatch):
    async def fake_post(payload, token, timeout=None):
        return {"choices": [{"message": {"content": "", "tool_calls": [CALL]},
                             "finish_reason": "tool_calls"}]} if not payload["messages"][-1].get("role") == "tool" \
            else {"choices": [{"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}]}
    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_standing_rules", AsyncMock(side_effect=AssertionError("read")))
    answer, notes = await agent_runner._chat(
        token="t", model="agent-ada-1", messages=[{"role": "user", "content": "send it"}],
        tool_ids=["gmail"], user_email=OWNER, tool_mode=agent_access.MODE_READ_ONLY)
    assert notes and "Declined" in notes[0]


# --- the surface ---------------------------------------------------------------------

@pytest.mark.parametrize("level,expected", [
    (None, agent_access.MODE_READ_ONLY), ("read", agent_access.MODE_READ_ONLY),
    ("ask", agent_access.MODE_ASK), ("all", agent_access.MODE_FULL)])
def test_an_automations_agent_on_ask_now_asks(level, expected):
    assert agent_access.effective_mode(level, "full", agent_access.SURFACE_AUTOMATION) == expected


# --- holding and deciding --------------------------------------------------------------

@pytest.fixture
def rows(monkeypatch):
    store = {}
    seen = {"settled": [], "resumed": [], "delivered": [], "cleared": []}

    async def create(email, fields):
        rid = "ap%d" % (len(store) + 1)
        store[rid] = dict(fields, id=rid, user_email=email, status="pending",
                          created_at=None, expires_at=None, decided_at=None, decided_via=None, result="")
        return {k: v for k, v in store[rid].items() if k not in ("calls", "conversation", "user_email")}

    async def get(email, aid, with_held=False):
        r = store.get(aid)
        if not r or r["user_email"] != email:
            return None
        out = {k: v for k, v in r.items() if k not in ("user_email",)}
        if not with_held:
            out.pop("calls"); out.pop("conversation")
        return out

    async def pending(email):
        return [{k: v for k, v in r.items() if k not in ("calls", "conversation", "user_email")}
                for r in store.values() if r["user_email"] == email and r["status"] == "pending"]

    async def settle(email, aid, status, via, result):
        r = store.get(aid)
        if not r or r["user_email"] != email or r["status"] != "pending":
            return False
        r.update(status=status, decided_via=via, result=result)
        seen["settled"].append((aid, status, via))
        return True

    async def resume(email, agent_id, conversation, calls, approved):
        seen["resumed"].append((email, agent_id, calls, approved))
        return {"answer": "Sent to Bo." if approved else "Not sent.", "notes": []}

    async def deliver_automation(email, automation_id, agent_name, status, text):
        seen["delivered"].append(("automation", automation_id, status, text))
        return "chat"

    async def deliver_chat(email, agent_id, agent_name, text):
        seen["delivered"].append(("chat", agent_id, text))
        return "chat"

    async def clear(key):
        seen["cleared"].append(key)

    monkeypatch.setattr(ap, "_create", create)
    monkeypatch.setattr(ap, "_get", get)
    monkeypatch.setattr(ap, "_pending", pending)
    monkeypatch.setattr(ap, "_settle", settle)
    monkeypatch.setattr(ra, "_resume_seam", resume)
    monkeypatch.setattr(ra, "_deliver_automation_seam", deliver_automation)
    monkeypatch.setattr(ra, "_deliver_chat_seam", deliver_chat)
    monkeypatch.setattr(ra, "_clear_chat_hold_seam", clear)
    seen["store"] = store
    return seen


async def test_a_held_question_is_written_with_what_it_needs_to_resume(rows):
    row = await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    assert row["id"] == "ap1" and row["agent_name"] == "Ada" and row["origin_ref"] == "auto-1"
    assert row["question"].startswith("Ada wants to run:") and "send_email" in row["question"]
    assert "calls" not in row, "the held calls were handed to the page"
    assert rows["store"]["ap1"]["calls"] == [CALL]


async def test_yes_resumes_the_turn_and_delivers_where_the_question_came_from(rows):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    out = await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert out["status"] == "done" and out["answer"] == "Sent to Bo."
    assert rows["settled"] == [("ap1", "approved", "page")]
    assert rows["resumed"] == [(OWNER, "agent-ada-1", [CALL], True)]
    assert rows["delivered"] == [("automation", "auto-1", "done", "Sent to Bo.")]


async def test_no_refuses_and_a_second_answer_does_nothing(rows):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    out = await ra.decide(OWNER, "ap1", False, ap.VIA_CHAT)
    assert out["answer"] == "Not sent." and rows["resumed"][0][3] is False
    again = await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert again["status"] == "already" and len(rows["resumed"]) == 1


async def test_a_chat_born_question_answered_elsewhere_clears_the_chats_hold_and_posts_to_the_office(rows):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_CHAT, "agentpending:chat-1:o")
    out = await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert out["status"] == "done"
    assert rows["cleared"] == ["agentpending:chat-1:o"]
    assert rows["delivered"] == [("chat", "agent-ada-1", "Sent to Bo.")]


async def test_a_chat_born_question_answered_in_the_chat_is_not_posted_twice(rows):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_CHAT, "k")
    out = await ra.decide(OWNER, "ap1", True, ap.VIA_CHAT)
    assert out["status"] == "done" and rows["delivered"] == []


async def test_an_agent_that_asks_again_is_held_again(rows, monkeypatch):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    monkeypatch.setattr(ra, "_resume_seam", AsyncMock(return_value={
        "pending": {"agent_id": "agent-ada-1", "user_email": OWNER, "calls": [CALL], "conversation": []}}))
    out = await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert out["status"] == "waiting" and "Ada wants to run:" in out["answer"]
    assert "ap2" in rows["store"] and rows["store"]["ap2"]["origin_ref"] == "auto-1"
    assert rows["delivered"][0][2] == "waiting"


async def test_a_resume_that_blows_up_is_a_failed_status_not_a_raise(rows, monkeypatch):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    monkeypatch.setattr(ra, "_resume_seam", AsyncMock(side_effect=RuntimeError("boom")))
    out = await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    assert out["status"] == "failed" and "could not finish" in out["notes"][0]


async def test_somebody_elses_question_cannot_be_answered(rows):
    await ra.hold_and_tell("other@example.com", "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    assert (await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE))["status"] == "already"


# --- an automation that asks --------------------------------------------------------------

async def test_an_automation_whose_agent_asks_delivers_the_question_and_waits(rows, monkeypatch):
    monkeypatch.setattr(automation_runner, "_run_turn_seam", AsyncMock(return_value={"pending": PENDING}))
    delivered = []

    async def to_chat(email, agent_id, agent_name, rule_name, answer):
        delivered.append(answer)
        return "chat"
    monkeypatch.setattr(automation_runner, "_to_chat_seam", to_chat)
    runs = []

    async def record(email, aid, status, trigger_text, result, delivered_to):
        runs.append((status, result, delivered_to))
    import automations
    monkeypatch.setattr(automations, "_record_run", record)
    out = await automation_runner.fire(
        {"id": "auto-1", "user_email": OWNER, "agent_id": "agent-ada-1", "name": "Lead",
         "instructions": "Reply.", "deliver_to": "chat"}, {"name": "Bo"}, "Ada")
    assert out["status"] == "waiting"
    assert "Ada wants to run:" in out["answer"] and "Agents page" in out["answer"]
    assert delivered and "send_email" in delivered[0]
    assert runs[0][0] == "waiting"
    assert rows["store"]["ap1"]["origin_ref"] == "auto-1"


# --- the main chat --------------------------------------------------------------------------

def _body(text, chat_id="chat-1"):
    class B:
        user_email = OWNER
        route_only = True
        first_only = False
        agent_id = None
        messages = [{"role": "user", "content": text}]
    b = B()
    b.chat_id = chat_id
    return b


@pytest.fixture
def chat(monkeypatch, rows):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    held = {}
    monkeypatch.setattr(rt, "_read_pending", AsyncMock(side_effect=lambda k: held.get(k)))
    monkeypatch.setattr(rt, "_write_pending", AsyncMock(side_effect=lambda k, v: held.__setitem__(k, v)))
    monkeypatch.setattr(rt, "_clear_pending", AsyncMock(side_effect=lambda k: held.pop(k, None)))
    rows["held"] = held
    return rows


async def test_a_bare_yes_with_nothing_held_here_answers_the_one_waiting_question(chat, monkeypatch):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    monkeypatch.setattr(rt, "_route_chat", AsyncMock(side_effect=AssertionError("routed")))
    out = await rt.chat(_body("yes"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Ada" and out["turns"][0]["answer"] == "Sent to Bo."
    assert chat["settled"] == [("ap1", "approved", "chat")]


async def test_two_waiting_questions_are_listed_not_guessed(chat, monkeypatch):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    await ra.hold_and_tell(OWNER, "agent-mia-1", "Mia", PENDING, ap.ORIGIN_AUTOMATION, "auto-2")
    monkeypatch.setattr(rt, "_route_chat", AsyncMock(side_effect=AssertionError("routed")))
    out = await rt.chat(_body("yes"), x_internal_secret="s")
    assert "More than one question is waiting" in out["turns"][0]["answer"]
    assert "Ada" in out["turns"][0]["answer"] and "Mia" in out["turns"][0]["answer"]
    assert chat["resumed"] == []


async def test_a_bare_yes_with_nothing_waiting_anywhere_is_routed_as_usual(chat, monkeypatch):
    monkeypatch.setattr(rt, "_route_chat", AsyncMock(return_value={"turns": [{"agent": None, "answer": "ok", "notes": []}]}))
    out = await rt.chat(_body("yes"), x_internal_secret="s")
    assert out["turns"][0]["answer"] == "ok"


async def test_a_question_born_in_the_chat_gets_a_row_and_a_later_page_answer_wins(chat, monkeypatch):
    turn = {"agent": {"id": "agent-ada-1", "name": "Ada"}, "answer": "", "notes": [],
            "pending": PENDING}
    monkeypatch.setattr(rt, "_route_chat", AsyncMock(return_value={"turns": [turn]}))
    await rt.chat(_body("send it"), x_internal_secret="s")
    key = rt._pending_key(rt._pin_key("chat-1", OWNER))
    assert chat["held"][key]["approval_id"] == "ap1"
    assert chat["store"]["ap1"]["origin"] == "chat" and chat["store"]["ap1"]["origin_ref"] == key
    # Answered on the page meanwhile; the chat's yes finds it settled.
    await ra.decide(OWNER, "ap1", True, ap.VIA_PAGE)
    monkeypatch.setattr(rt, "_resume_held", AsyncMock(side_effect=AssertionError("ran twice")))
    out = await rt.chat(_body("yes"), x_internal_secret="s")
    assert out["turns"][0]["answer"] == rt.ALREADY_ANSWERED


async def test_a_question_born_in_the_chat_answered_in_the_chat_settles_its_row(chat, monkeypatch):
    turn = {"agent": {"id": "agent-ada-1", "name": "Ada"}, "answer": "", "notes": [], "pending": PENDING}
    monkeypatch.setattr(rt, "_route_chat", AsyncMock(return_value={"turns": [turn]}))
    await rt.chat(_body("send it"), x_internal_secret="s")
    monkeypatch.setattr(rt, "_resume_held", AsyncMock(return_value={"turns": [
        {"agent": {"id": "agent-ada-1", "name": "Ada"}, "answer": "Sent.", "notes": []}]}))
    out = await rt.chat(_body("yes"), x_internal_secret="s")
    assert out["turns"][0]["answer"] == "Sent."
    assert chat["settled"] == [("ap1", "approved", "chat")]


# --- the routes -------------------------------------------------------------------------------

@pytest.fixture
def client(rows, monkeypatch):
    rules = []

    async def list_rules(email):
        return list(rules)

    async def add_rule(email, fields):
        if len(rules) >= ap.MAX_RULES:
            raise ap.TooMany()
        rules.append(dict(fields, id="r%d" % (len(rules) + 1), created_at=None))
        return rules[-1]

    async def delete_rule(email, rid):
        before = len(rules)
        rules[:] = [r for r in rules if r["id"] != rid]
        return len(rules) < before
    monkeypatch.setattr(ap, "_rules", list_rules)
    monkeypatch.setattr(ap, "_add_rule", add_rule)
    monkeypatch.setattr(ap, "_delete_rule", delete_rule)
    app = FastAPI()
    app.include_router(ra.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    return TestClient(app)


async def test_the_page_lists_decides_and_refuses_a_second_answer(client, rows):
    await ra.hold_and_tell(OWNER, "agent-ada-1", "Ada", PENDING, ap.ORIGIN_AUTOMATION, "auto-1")
    r = client.get("/api/tasks/approvals")
    assert [a["id"] for a in r.json()["approvals"]] == ["ap1"]
    assert "calls" not in r.json()["approvals"][0]
    r = client.post("/api/tasks/approvals/ap1/decide", json={"approved": True})
    assert r.status_code == 200 and r.json()["answer"] == "Sent to Bo."
    r = client.post("/api/tasks/approvals/ap1/decide", json={"approved": True})
    assert r.status_code == 409


def test_rules_are_added_listed_and_deleted_with_sentences_for_mistakes(client):
    r = client.post("/api/tasks/approvals/rules", json={"tool": " Send_Email ", "decision": "allow",
                                                        "when_contains": "@acme.com", "label": "our domain"})
    assert r.status_code == 200 and r.json()["tool"] == "send_email"
    assert client.get("/api/tasks/approvals/rules").json()["rules"][0]["label"] == "our domain"
    r = client.post("/api/tasks/approvals/rules", json={"tool": "x", "decision": "maybe"})
    assert r.status_code == 422 and "allows or denies" in r.json()["detail"]
    assert client.delete("/api/tasks/approvals/rules/r1").json() == {"deleted": True}
    assert client.delete("/api/tasks/approvals/rules/r1").json() == {"deleted": False}


def test_the_routes_need_a_signed_in_person():
    app = FastAPI()
    app.include_router(ra.router, prefix="/api/tasks")
    c = TestClient(app)
    assert c.get("/api/tasks/approvals").status_code == 401
    assert c.post("/api/tasks/approvals/x/decide", json={"approved": True}).status_code == 401
