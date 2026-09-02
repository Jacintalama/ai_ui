"""The one model in the dropdown that decides who answers.

The pipe holds no routing logic. Everything here is about the seam: it must
ask the tasks service, deliver whatever comes back, and never leave somebody
staring at silence when that call fails.
"""
import importlib.util
import json
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
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={"turns": [{
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}]}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}],
                        "stream": False},
                       __user__={"email": "owner@example.com"})

    assert "Four unread." in out
    assert "Mia" in out, "the person cannot tell who answered"


async def test_notes_ride_along_with_the_answer(mod, monkeypatch):
    """A refused write that nobody is told about is the worst outcome: the
    person believes it happened."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={"turns": [{
        "agent": {"id": "a", "name": "Mia"}, "answer": "Here is the draft.",
        "notes": ["Declined to run send_email, because this agent is set to read only."]}]}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert "Declined to run send_email" in out


async def test_a_pending_approval_is_shown_as_a_question(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={"turns": [{
        "agent": {"id": "a", "name": "Mia"},
        "pending": {"calls": [{"id": "c1", "function": {
            "name": "send_message",
            "arguments": '{"to": "ralph@example.com"}'}}]}}]}))

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
        "turns": [{"agent": None, "answer": "I can help.", "notes": []}]}))

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
    assert chr(0x2014) not in src and chr(0x2013) not in src


def test_empty_is_never_rendered_for_a_real_response_shape(mod):
    """EMPTY is how a whole class of bug becomes visible to the person: an
    agent or IO answering with nothing and the pipe silently papering over
    it. It must never appear for a response shape the endpoint can actually
    produce; it is a tell for a malformed one.

    The shapes the endpoint guarantees, one turns list each: an agent named
    with an answer, an agent named with a pending approval, no agent named
    with the gateway's own answer, and two agents each with their own turn.
    The endpoint guarantees `answer` is always a non-empty string on every
    turn where it is present at all.
    """
    p = mod.Pipe()

    agent_with_answer = {"turns": [{
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}]}
    agent_with_pending = {"turns": [{
        "agent": {"id": "agent-m", "name": "Mia"},
        "pending": {"calls": [{"id": "c1", "function": {
            "name": "send_message",
            "arguments": '{"to": "ralph@example.com"}'}}]}}]}
    no_agent_with_answer = {"turns": [{
        "agent": None, "answer": "I can help.", "notes": []}]}
    two_turns = {"turns": [
        {"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Here.", "notes": []},
        {"agent": {"id": "agent-a", "name": "Ada"}, "answer": "Here too.", "notes": []}]}

    for shape in (agent_with_answer, agent_with_pending, no_agent_with_answer,
                 two_turns):
        out = p._render(shape)
        assert mod.EMPTY not in out, "EMPTY leaked through a real response shape: %r" % (shape,)


@pytest.mark.parametrize("bad_shape", [
    None,
    [],
    "a string",
    {"agent": "Mia"},
    {},
    {"turns": "not a list"},
    {"turns": [None, "not a dict", 123]},
])
def test_render_survives_malformed_shapes_without_raising(mod, bad_shape):
    """_render's input comes over HTTP from another service, which is no
    more trustworthy than the model output _approval_question already
    guards. A response that parses as JSON but is not the expected shape
    must still produce a readable sentence, not an AttributeError that
    takes the whole turn down."""
    p = mod.Pipe()
    out = p._render(bad_shape)
    assert isinstance(out, str) and out.strip()


async def test_a_none_response_from_ask_tasks_still_says_something(mod, monkeypatch):
    """A response that fails to parse as the expected shape must not turn
    into a framework error in somebody's chat window."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value=None))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert isinstance(out, str) and out.strip()


def test_approval_question_truncates_long_values_but_not_keys_or_call_count(mod):
    """_approval_question caps two things today: one argument value at
    MAX_ARG_CHARS, and the arguments shown per call at MAX_ARGS_SHOWN. A long
    value must not bury the question being asked, or the "Reply yes" line.
    This does not extend that behaviour: the argument KEY is never truncated,
    and the number of CALLS in one block is never capped, only the arguments
    shown for each one."""
    p = mod.Pipe()
    long_value = "body " * (mod.MAX_ARG_CHARS * 2)
    long_key = "a_very_long_argument_key_" + ("z" * mod.MAX_ARG_CHARS)
    assert len(long_key) > mod.MAX_ARG_CHARS, "the key must actually be long"

    calls = [{"id": "c0", "function": {"name": "send_message",
             "arguments": json.dumps({long_key: long_value})}}]
    extra = mod.MAX_ARGS_SHOWN + 3
    for i in range(extra):
        calls.append({"id": "c%d" % (i + 1), "function": {
            "name": "tool_%d" % i, "arguments": "{}"}})

    out = p._approval_question("Mia", calls)

    assert long_value not in out, "the long argument value was not truncated"
    assert long_value[:mod.MAX_ARG_CHARS] in out
    assert long_key in out, "the argument key must not be truncated"
    for i in range(extra):
        assert "tool_%d" % i in out, "every call in the block must appear"
    assert "Reply yes" in out


# --- rendering more than one turn -------------------------------------------

async def test_two_turns_render_both_names_in_order(mod, monkeypatch):
    """"hi mia and ada" must produce Mia's answer above Ada's, each under its
    own name, with a blank line between them."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={"turns": [
        {"agent": {"id": "agent-m", "name": "Mia"},
         "answer": "Nothing urgent in your inbox right now.", "notes": []},
        {"agent": {"id": "agent-a", "name": "Ada"},
         "answer": "What do you want me to look into?", "notes": []},
    ]}))

    out = await p.pipe(
        {"messages": [{"role": "user", "content": "hi mia and ada, are you there?"}]},
        __user__={"email": "owner@example.com"})

    mia_pos = out.find("Mia:")
    ada_pos = out.find("Ada:")
    assert mia_pos != -1 and ada_pos != -1
    assert mia_pos < ada_pos, "Mia was named first and must render first"
    assert "Nothing urgent" in out
    assert "What do you want me to look into" in out
    assert out.count("\n\n") >= 1, "turns must be separated by a blank line"


def test_a_single_turn_renders_exactly_as_before(mod):
    """A one-element turns list must render identically to the old
    single-shape output: a name prefix, then the answer, nothing else."""
    p = mod.Pipe()
    out = p._render({"turns": [{
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}]})
    assert out == "Mia:\nFour unread."


async def test_a_malformed_turns_value_returns_a_readable_sentence(mod):
    """turns must be a list. A string, a number, or a dict in its place must
    not raise, and must not silently render as nothing."""
    p = mod.Pipe()
    for bad in ("not a list", 123, {"agent": "Mia"}):
        out = p._render({"turns": bad})
        assert isinstance(out, str) and out.strip()
        assert out == mod.EMPTY
