"""The main chat's own assistant (main_assistant).

Lukas, standup 2026-10-27: control everything from the main chat, and never
pick a tool by hand. When no agent takes a message on Auto, this assistant
answers through the same loop the agents use, with the tools Jev picked, and
asks before it changes anything. It is not a row in Open WebUI, so the one
lookup every agent turn makes has to know it.
"""
from unittest.mock import AsyncMock

import pytest

import agent_access
import agent_llm
import agent_runner
import main_assistant as ma
import routes_agent_turn as rt


def test_the_assistant_runs_on_the_free_pool_through_meta_llm(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS",
                        ["z-ai/glm-5.3-flash", "z-ai/glm-4.7-flash"])
    a = ma.agent()
    assert a["id"] == ma.ASSISTANT_ID == "io-assistant"
    assert a["name"] == "IO"
    # On the pipe with a real model in meta.llm: the runner posts the model,
    # never the pipe and never this id, which Open WebUI does not know.
    assert agent_llm.is_callback(a["base_model_id"])
    assert agent_llm.llm_of(a) == "z-ai/glm-5.3-flash"
    assert agent_llm.on_pipe(a)
    assert agent_access.level_of(a["meta"]) == agent_access.MODE_ASK
    assert "ask" in a["params"]["system"].lower()


def test_an_empty_pool_is_an_assistant_that_cannot_run(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", [])
    assert not agent_llm.can_run(ma.agent())


def test_it_is_the_assistant_only_by_its_id():
    assert ma.is_assistant("io-assistant")
    assert not ma.is_assistant("agent-mia-2201")
    assert not ma.is_assistant(None)


@pytest.fixture
def owui(monkeypatch):
    listed = [{"id": "agent-mia", "name": "Mia", "meta": {}}]
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "session_stamp_for", AsyncMock(return_value="s"))
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=(listed, False)))
    monkeypatch.setattr(rt, "_every_tool_for",
                        AsyncMock(return_value=["gmail", "calendar"]))
    monkeypatch.setattr(agent_runner, "FREE_MODELS", ["z-ai/glm-5.3-flash"])
    return listed


async def test_the_lookup_knows_the_assistant_without_a_row(owui):
    token, tools, level, agent, roster = await rt._resolve_agent_row(
        "p@example.com", ma.ASSISTANT_ID)
    assert token == "tok"
    assert tools == ["gmail", "calendar"]
    assert level == agent_access.MODE_ASK
    assert agent["id"] == ma.ASSISTANT_ID
    # The person's agents are still the roster, so "ask Mia" works.
    assert roster == owui


async def test_an_unknown_id_is_still_a_404(owui):
    with pytest.raises(rt.HTTPException) as err:
        await rt._resolve_agent_row("p@example.com", "agent-nobody")
    assert err.value.status_code == 404


# --- the turn takes the tools Jev picked ------------------------------------

@pytest.fixture
def turn_seams(monkeypatch, owui):
    seen = {}

    async def fake_chat(**kw):
        seen.update(kw)
        return "done", []

    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-1"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection",
                        lambda *a, **k: None)
    return seen


async def test_a_turn_uses_the_tools_it_was_given(turn_seams):
    await rt._run_turn("p@example.com", ma.ASSISTANT_ID,
                       [{"role": "user", "content": "my calendar"}],
                       tool_ids=["calendar"])
    assert turn_seams["tool_ids"] == ["calendar"]
    assert turn_seams["tool_mode"] == agent_access.MODE_ASK


async def test_no_pick_keeps_every_tool_the_person_has(turn_seams):
    await rt._run_turn("p@example.com", ma.ASSISTANT_ID,
                       [{"role": "user", "content": "hello"}])
    assert turn_seams["tool_ids"] == ["gmail", "calendar"]


async def test_an_empty_pick_means_no_tools_at_all(turn_seams):
    await rt._run_turn("p@example.com", ma.ASSISTANT_ID,
                       [{"role": "user", "content": "tell me a joke"}],
                       tool_ids=[])
    assert turn_seams["tool_ids"] is None


async def test_the_chat_wrapper_passes_the_pick_on(monkeypatch):
    seen = {}

    async def fake_run(user_email, agent_id, history, **kw):
        seen.update(kw, agent_id=agent_id)
        return {"answer": "ok", "notes": []}

    monkeypatch.setattr(rt, "_run_turn", fake_run)
    monkeypatch.setattr(rt.agent_memory, "recall_block",
                        AsyncMock(return_value=""))
    out = await rt._turn_for("p@example.com", ma.agent(),
                             [{"role": "user", "content": "my calendar"}],
                             tool_ids=["calendar"], now=__import__(
                                 "datetime").datetime(2026, 10, 27))
    assert seen == {"agent_id": ma.ASSISTANT_ID, "tool_ids": ["calendar"]}
    assert out["agent"] == {"id": ma.ASSISTANT_ID, "name": "IO"}
