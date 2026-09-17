"""Every surface that runs an agent says who is asking, and records what the
turn cost. The loop itself is tested in test_agent_escalation_loop.py; this
file only checks what each caller hands it and what it writes back."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_escalation
import agent_memory
import agent_runner
import routes_agent_turn as rt

EMAIL = "owner@example.com"


def _agent():
    return {"id": "agent-1", "name": "Ada",
            "base_model_id": "nvidia/nemotron-3-super-120b-a12b:free",
            "meta": {"toolIds": ["gmail"], "access": "ask"}}


def _wire_turn(monkeypatch, seen):
    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=["gmail"]))
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-7"))
    finish = AsyncMock()
    monkeypatch.setattr(rt.agent_activity, "finish_run", finish)
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(agent_memory, "schedule_reflection", lambda *a, **k: None)
    return finish


async def test_a_chat_turn_says_what_the_person_typed_and_records_the_cost(monkeypatch):
    seen = {}
    finish = _wire_turn(monkeypatch, seen)

    await rt._run_turn(EMAIL, "agent-1",
                       [{"role": "system", "content": "identity"},
                        {"role": "user", "content": "build me a todo app"}])

    assert seen["intent"] == agent_escalation.Intent(person_text="build me a todo app")
    assert seen["usage"].run_id == "run-7"
    finish.assert_awaited_once()
    assert finish.await_args.kwargs["usage"] is seen["usage"]


async def test_a_turn_inside_the_room_uses_the_rooms_intent(monkeypatch):
    seen = {}
    _wire_turn(monkeypatch, seen)
    room = agent_escalation.Intent(person_text="build me a todo app", may_pass=True)

    with agent_escalation.asking(room):
        await rt._run_turn(EMAIL, "agent-1",
                           [{"role": "user", "content": "build me a todo app"},
                            {"role": "user", "content": "reply with exactly PASS"}])

    assert seen["intent"] is room


async def test_a_resumed_turn_is_a_follow_up(monkeypatch):
    seen = {}
    finish = _wire_turn(monkeypatch, seen)
    monkeypatch.setattr(rt, "execute_tool_call", AsyncMock(return_value="sent"))

    await rt._resume_turn(EMAIL, "agent-1",
                          [{"role": "user", "content": "send it"},
                           {"role": "assistant", "content": "",
                            "tool_calls": [{"id": "c1", "function": {
                                "name": "send_email", "arguments": "{}"}}]}],
                          [{"id": "c1", "type": "function",
                            "function": {"name": "send_email", "arguments": "{}"}}],
                          True)

    assert seen["intent"] == agent_escalation.Intent(follow_up=True)
    assert finish.await_args.kwargs["usage"] is seen["usage"]


async def test_a_schedule_says_its_own_prompt(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "report", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)
    monkeypatch.setattr(agent_memory, "recall_block", AsyncMock(return_value=""))
    monkeypatch.setattr(agent_runner.agent_activity, "start_run",
                        AsyncMock(return_value="run-9"))
    finish = AsyncMock()
    monkeypatch.setattr(agent_runner.agent_activity, "finish_run", finish)
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=[]))

    sched = SimpleNamespace(id="s1", user_email=EMAIL, agent_id="agent-1",
                            prompt="Refactor the pricing page code.",
                            last_result="last week", last_run_status="completed",
                            tool_mode=None)
    await agent_runner.run_agent(sched)

    assert seen["intent"] == agent_escalation.Intent(
        person_text="Refactor the pricing page code.")
    assert seen["usage"].run_id == "run-9"
    assert finish.await_args.kwargs["usage"] is seen["usage"]


def _room(monkeypatch, answers):
    import agent_chat_store
    import routes_agent_chat
    importlib.reload(agent_chat_store)
    importlib.reload(routes_agent_chat)
    seen = []

    async def turn(email, agent, messages, names=()):
        seen.append(agent_escalation.current_intent())
        return {"answer": answers.pop(0), "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}

    async def agents_for(email):
        return [{"id": "agent-a", "name": "Ada"}, {"id": "agent-m", "name": "Mia"}]

    async def noop_create(email, title, s):
        return "chat-1"

    async def noop_save(email, s):
        return None

    monkeypatch.setattr(routes_agent_chat, "_agents_for", agents_for)
    monkeypatch.setattr(routes_agent_chat, "_turn_for", turn)
    monkeypatch.setattr(routes_agent_chat.store, "create_chat", noop_create)
    monkeypatch.setattr(routes_agent_chat.store, "save_chat", noop_save)
    app = FastAPI()
    app.include_router(routes_agent_chat.router)
    return TestClient(app), seen


def test_the_room_hands_every_agent_the_persons_words_not_the_pass_instruction(monkeypatch):
    client, seen = _room(monkeypatch, ["PASS", "PASS", "Mia here"])
    hdr = {"X-User-Email": "panel@example.com"}
    client.post("/tasks/agents/chat/send", data={"message": "build me a todo app"},
                headers=hdr)
    client.get("/tasks/agents/chat/stream", headers=hdr)

    assert [i.person_text for i in seen] == ["build me a todo app"] * 3
    # Both heard it unnamed; the everybody-passed fallback may not pass.
    assert [i.may_pass for i in seen] == [True, True, False]
    assert agent_escalation.current_intent() is None


def test_a_named_agent_in_the_room_may_not_pass(monkeypatch):
    client, seen = _room(monkeypatch, ["on it"])
    hdr = {"X-User-Email": "panel@example.com"}
    client.post("/tasks/agents/chat/send",
                data={"message": "ada, build me a todo app"}, headers=hdr)
    client.get("/tasks/agents/chat/stream", headers=hdr)

    assert [(i.person_text, i.may_pass) for i in seen] == [
        ("ada, build me a todo app", False)]


async def test_the_room_summariser_never_leaves_the_free_models(monkeypatch):
    import routes_agent_chat as mod
    seen = {}

    async def fake_resolve(email, agent_id):
        return "tok", [], "all"

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "notes", []

    monkeypatch.setattr(mod, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(mod, "_chat", fake_chat)
    await mod._summarise("a@example.com", {"id": "agent-a"},
                         [{"role": "user", "content": "build me an app"}])
    assert "intent" in seen and seen["intent"] is None


async def test_the_reflection_never_posts_the_paid_model(monkeypatch):
    posted = []

    async def fake_post(payload, token, timeout=None):
        posted.append(payload["model"])
        return {"choices": [{"message": {"content": "[]"}}]}

    async def no_pool(agent):
        return []

    monkeypatch.setattr(agent_runner, "_post_chat", fake_post)
    monkeypatch.setattr(agent_runner, "_fallback_pool", no_pool)
    await agent_memory._complete(
        {"model": agent_memory.reflect_model() or "nvidia/nemotron-3-super-120b-a12b:free",
         "messages": [{"role": "user", "content": "build me an app"}]},
        "tok", 5)
    assert posted and agent_escalation.PAID_MODEL not in posted
