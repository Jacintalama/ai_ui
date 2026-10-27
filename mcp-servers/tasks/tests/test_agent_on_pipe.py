"""An agent on the IO pipe (2026-10-27): @Ada in the main chat runs our loop.

The base model of every agent is the IO pipe and its language model is
meta.llm. What has to hold: the runner posts the language model and never
the agent's id (that is the loop that took Open WebUI down twice); the chat
route runs the agent the message was sent to, whatever the words; and the
pipe tells the service which agent that was, without saying its name twice.
"""
import importlib.util
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import agent_llm
import agent_runner
import routes_agent_turn as rt

PIPE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "open-webui-functions", "io_gateway_pipe.py")

ADA = {"id": "agent-a", "name": "Ada", "user_id": "u1", "base_model_id": "io.io",
       "meta": {"toolIds": ["gmail"], "llm": "z-ai/glm-5.3-flash"},
       "params": {"system": "Be Ada."}}
MIA = {"id": "agent-m", "name": "Mia", "user_id": "u1", "base_model_id": "gpt-5",
       "meta": {"toolIds": []}, "params": {"system": "Be Mia."}}


# --- which model ------------------------------------------------------------

def test_the_language_model_is_meta_llm_on_a_pipe_and_the_base_otherwise():
    assert agent_llm.llm_of(ADA) == "z-ai/glm-5.3-flash"
    assert agent_llm.llm_of(MIA) == "gpt-5"
    assert agent_llm.on_pipe(ADA) and not agent_llm.on_pipe(MIA)
    assert agent_llm.can_run(ADA) and agent_llm.can_run(MIA)


def test_an_agent_on_a_pipe_with_no_model_cannot_run():
    stuck = {"id": "agent-s", "base_model_id": "auto_router.auto", "meta": {}}
    assert agent_llm.llm_of(stuck) is None and not agent_llm.can_run(stuck)
    # A pipe named as the model is no model either: that is the loop again.
    looped = {"id": "agent-l", "base_model_id": "io.io", "meta": {"llm": "auto_router.auto"}}
    assert agent_llm.llm_of(looped) is None
    assert agent_llm.llm_of(None) is None and agent_llm.llm_of({}) is None
    assert agent_llm.llm_of({"base_model_id": "", "meta": {"llm": "gpt-5"}}) is None


def test_the_base_for_new_agents_is_the_io_pipe(monkeypatch):
    monkeypatch.delenv("AGENT_BASE_MODEL", raising=False)
    assert agent_llm.base_model() == "io.io"
    monkeypatch.setenv("AGENT_BASE_MODEL", "io_two.io")
    assert agent_llm.base_model() == "io_two.io"


# --- the runner ---------------------------------------------------------------

def _reply(content="ok"):
    return {"choices": [{"message": {"content": content, "tool_calls": None},
                         "finish_reason": "stop"}]}


async def test_the_runner_posts_the_language_model_with_the_instructions_in_front():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("Hello from Ada.")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _notes = await agent_runner._chat(
            token="t", model="agent-a", messages=[{"role": "user", "content": "hi"}],
            tool_ids=["gmail"], user_email="o@example.com", tool_mode="read_only",
            agent=ADA)
    assert answer == "Hello from Ada."
    assert len(posts) == 1
    assert posts[0]["model"] == "z-ai/glm-5.3-flash", "it posted the agent id: the loop"
    assert posts[0]["messages"][0] == {"role": "system", "content": "Be Ada."}
    assert posts[0]["messages"][1]["content"] == "hi"
    assert posts[0]["tool_ids"] == ["gmail"], "the tools were lost on the way"


async def test_an_agent_whose_base_is_its_model_is_posted_as_before():
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply("Hello from Mia.")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(
            token="t", model="agent-m", messages=[{"role": "user", "content": "hi"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=MIA)
    assert posts[0]["model"] == "agent-m"
    assert posts[0]["messages"][0]["role"] == "user"


async def test_a_free_model_in_meta_llm_still_falls_down_the_pool(monkeypatch):
    monkeypatch.setattr(agent_runner, "FREE_MODELS", ["free/one", "free/two"])
    monkeypatch.setattr(agent_runner, "_available_free_ids", AsyncMock(return_value=None))
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload["model"])
        if len(posts) == 1:
            return {"error": {"message": "Provider returned error"}}
        return _reply("ok")

    agent = dict(ADA, meta={"llm": "free/one"})
    with patch.object(agent_runner, "_post_chat", new=fake_post):
        answer, _ = await agent_runner._chat(
            token="t", model="agent-a", messages=[{"role": "user", "content": "hi"}],
            tool_ids=None, user_email="o@example.com", tool_mode="read_only",
            agent=agent)
    assert posts == ["free/one", "free/two"] and answer == "ok"


# --- the guard ----------------------------------------------------------------

@pytest.fixture
def _resolve(monkeypatch):
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "tools_for_agent", AsyncMock(return_value=["gmail"]))


async def test_an_agent_on_the_pipe_with_a_model_is_allowed_to_run(_resolve, monkeypatch):
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA], False)))
    token, tools, level, agent, roster = await rt._resolve_agent_row("o@example.com", "agent-a")
    assert agent is ADA and tools == ["gmail"]


async def test_an_agent_on_the_pipe_with_no_model_is_still_refused(_resolve, monkeypatch):
    stuck = dict(ADA, meta={"toolIds": []})
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([stuck], False)))
    with pytest.raises(HTTPException) as e:
        await rt._resolve_agent_row("o@example.com", "agent-a")
    assert e.value.status_code == 409 and e.value.detail == rt.AGENT_ON_CALLBACK_MODEL


# --- the chat route -----------------------------------------------------------

def _body(text, agent_id=None):
    class B:
        user_email = "o@example.com"
        chat_id = "chat-1"
        route_only = False
        first_only = False
        messages = [{"role": "user", "content": text}]
    b = B()
    b.agent_id = agent_id
    return b


@pytest.fixture
def _chat(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA, MIA], False)))
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(return_value={"answer": "hi", "notes": []}))
    pins = {}
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(side_effect=lambda k: pins.get(k)))
    monkeypatch.setattr(rt, "_write_pin", AsyncMock(side_effect=lambda k, v: pins.__setitem__(k, v)))
    monkeypatch.setattr(rt, "_clear_pin", AsyncMock(side_effect=lambda k: pins.pop(k, None)))
    return pins


async def test_the_agent_the_message_was_sent_to_answers_whatever_the_words(_chat):
    out = await rt.chat(_body("hi mia, what is due", agent_id="agent-a"), x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Ada"], out
    assert rt._run_turn.await_args.args[1] == "agent-a"
    assert _chat[rt._pin_key("chat-1", "o@example.com")] == "agent-a"


async def test_a_goodbye_sent_to_an_agent_is_still_for_that_agent(_chat):
    out = await rt.chat(_body("thanks, that's all for now", agent_id="agent-a"),
                        x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Ada"
    assert out["turns"][0]["answer"] == "hi"


async def test_a_message_for_an_agent_that_is_not_yours_says_so(_chat):
    out = await rt.chat(_body("hi", agent_id="agent-zed"), x_internal_secret="s")
    assert out["turns"] == [{"agent": None, "answer": rt.NOT_YOUR_AGENT, "notes": []}]
    rt._run_turn.assert_not_awaited()


async def test_no_agent_id_routes_by_the_words_as_before(_chat):
    out = await rt.chat(_body("hi mia"), x_internal_secret="s")
    assert out["turns"][0]["agent"]["name"] == "Mia"


# --- the pipe -----------------------------------------------------------------

def _pipe():
    spec = importlib.util.spec_from_file_location("io_gateway_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Pipe()


def _meta(model_id):
    return {"model": {"id": model_id, "name": "Ada", "base_model_id": "io.io"}}


async def test_a_message_sent_to_an_agents_model_names_that_agent_to_the_service():
    p = _pipe()
    p._ask_tasks = AsyncMock(return_value={"turns": [{
        "agent": {"id": "agent-a", "name": "Ada"}, "answer": "Two invoices.", "notes": []}],
        "faces": {"agent-a": "data:image/svg+xml;base64,AAAA"}})
    out = await p.pipe({"model": "io.io",
                        "messages": [{"role": "system", "content": "Be Ada."},
                                     {"role": "user", "content": "what is due"}]},
                       __user__={"email": "o@example.com"},
                       __metadata__=_meta("agent-a"))
    assert p._ask_tasks.await_args.kwargs["agent_id"] == "agent-a"
    sent = p._ask_tasks.await_args.args[2]
    assert sent == [{"role": "user", "content": "what is due"}], "the instructions went twice"
    # Open WebUI shows Ada's face and name on this reply already.
    assert out == "Two invoices."


async def test_a_message_sent_to_the_io_model_itself_is_for_nobody_in_particular():
    p = _pipe()
    p._ask_tasks = AsyncMock(return_value={"turns": [{"agent": None, "answer": "Hi.", "notes": []}]})
    await p.pipe({"model": "io.io", "messages": [{"role": "user", "content": "hi"}]},
                 __user__={"email": "o@example.com"}, __metadata__=_meta("io.io"))
    assert p._ask_tasks.await_args.kwargs["agent_id"] == ""
    # And no metadata at all, as an older Open WebUI would send.
    await p.pipe({"messages": [{"role": "user", "content": "hi"}]},
                 __user__={"email": "o@example.com"})
    assert p._ask_tasks.await_args.kwargs["agent_id"] == ""


async def test_an_approval_question_still_names_the_agent_on_its_own_model():
    p = _pipe()
    p._ask_tasks = AsyncMock(return_value={"turns": [{
        "agent": {"id": "agent-a", "name": "Ada"}, "answer": "",
        "pending": {"calls": [{"function": {"name": "send_email", "arguments": "{}"}}]},
        "notes": []}]})
    out = await p.pipe({"messages": [{"role": "user", "content": "send it"}]},
                       __user__={"email": "o@example.com"}, __metadata__=_meta("agent-a"))
    assert out.startswith("Ada wants to run:") and "send_email" in out


async def test_only_instructions_and_nothing_else_is_answered_not_sent():
    p = _pipe()
    p._ask_tasks = AsyncMock()
    out = await p.pipe({"messages": [{"role": "system", "content": "Be Ada."}]},
                       __user__={"email": "o@example.com"}, __metadata__=_meta("agent-a"))
    assert out == "There was nothing to answer."
    p._ask_tasks.assert_not_awaited()
