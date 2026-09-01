"""The one model in the dropdown that decides who answers.

The pipe holds no routing logic. Everything here is about the seam: it must
ask the tasks service, deliver whatever comes back, and never leave somebody
staring at silence when that call fails.
"""
import importlib.util
import os
from unittest.mock import AsyncMock

import pytest

PIPE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "io_gateway_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("io_gateway_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def test_it_offers_exactly_one_model_called_io(mod):
    pipes = mod.Pipe().pipes()
    assert len(pipes) == 1
    assert pipes[0]["id"] == "io"
    assert pipes[0]["name"] == "IO"


async def test_an_agents_answer_is_delivered_with_its_name(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}],
                        "stream": False},
                       __user__={"email": "owner@example.com"})

    assert "Four unread." in out
    assert "Mia" in out, "the person cannot tell who answered"


async def test_notes_ride_along_with_the_answer(mod, monkeypatch):
    """A refused write that nobody is told about is the worst outcome: the
    person believes it happened."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "a", "name": "Mia"}, "answer": "Here is the draft.",
        "notes": ["Declined to run send_email, because this agent is set to read only."]}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert "Declined to run send_email" in out


async def test_a_pending_approval_is_shown_as_a_question(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "a", "name": "Mia"},
        "pending": {"calls": [{"id": "c1", "function": {
            "name": "send_message",
            "arguments": '{"to": "ralph@example.com"}'}}]}}))

    out = await p.pipe({"messages": [{"role": "user", "content": "mia send it"}]},
                       __user__={"email": "o@e.com"})
    assert "send_message" in out
    assert "ralph@example.com" in out
    assert "yes" in out.lower()


async def test_ios_own_answer_is_delivered_without_a_name_prefix(mod, monkeypatch):
    """When nobody was named, IO answered, and prefixing that with a name
    would invent a speaker."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": None, "answer": "I can help.", "notes": []}))

    out = await p.pipe({"messages": [{"role": "user", "content": "what is the weather"}]},
                       __user__={"email": "o@e.com"})

    assert out == "I can help."
    assert ":" not in out.split("\n")[0], "an agent name was prefixed to IO's own answer"


def test_the_pipe_never_calls_open_webui_itself(mod):
    """It holds no Open WebUI credentials by design. Every model call goes
    through the tasks service, which mints a per-user token."""
    src = open(PIPE_PATH, encoding="utf-8").read()
    assert "chat/completions" not in src
    assert "OPENWEBUI_URL" not in src


async def test_a_tasks_failure_still_says_something(mod, monkeypatch):
    """Somebody is watching this chat. Silence is the one unacceptable
    outcome."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(side_effect=RuntimeError("down")))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert isinstance(out, str) and out.strip()


async def test_a_missing_user_is_reported_not_guessed(mod):
    """Acting without knowing whose account it is would run an agent as the
    wrong person."""
    p = mod.Pipe()
    out = await p.pipe({"messages": [{"role": "user", "content": "hi"}]},
                       __user__=None)
    assert isinstance(out, str) and out.strip()


async def test_an_empty_conversation_is_answered_not_crashed(mod):
    p = mod.Pipe()
    out = await p.pipe({"messages": []}, __user__={"email": "o@e.com"})
    assert isinstance(out, str) and out.strip()


def test_the_secret_is_never_put_in_a_reply(mod):
    """This project has already leaked a token through a client that logged a
    request URL."""
    src = open(PIPE_PATH, encoding="utf-8").read()
    assert "INTERNAL_CALLBACK_SECRET" in src
    for bad in ["print(", "logger.info(secret", "f\"{secret}"]:
        assert bad not in src, bad


def test_no_dashes_in_the_pipe_copy(mod):
    src = open(PIPE_PATH, encoding="utf-8").read()
    assert "\u2014" not in src and "\u2013" not in src


def test_empty_is_never_rendered_for_a_real_response_shape(mod):
    """EMPTY is how a whole class of bug becomes visible to the person: an
    agent or IO answering with nothing and the pipe silently papering over
    it. It must never appear for a response shape the endpoint can actually
    produce; it is a tell for a malformed one.

    The three shapes the endpoint guarantees per Task 2: agent named with an
    answer, agent named with a pending approval, and no agent named with the
    gateway's own answer. The endpoint guarantees `answer` is always a
    non-empty string when it is present at all.
    """
    p = mod.Pipe()

    agent_with_answer = {
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}
    agent_with_pending = {
        "agent": {"id": "agent-m", "name": "Mia"},
        "pending": {"calls": [{"id": "c1", "function": {
            "name": "send_message",
            "arguments": '{"to": "ralph@example.com"}'}}]}}
    no_agent_with_answer = {
        "agent": None, "answer": "I can help.", "notes": []}

    for shape in (agent_with_answer, agent_with_pending, no_agent_with_answer):
        out = p._render(shape)
        assert mod.EMPTY not in out, "EMPTY leaked through a real response shape: %r" % (shape,)
