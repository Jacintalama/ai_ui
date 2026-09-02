"""The Open WebUI tool that reaches the user's agents from any model.

Loaded by path, the same way tests/test_account_tool.py loads
open-webui-functions/account_tool.py, because this file lives outside the
tasks service and is never imported by anything in it.

The tool talks to another service over HTTP, so its shape is not ours to
trust: a malformed response must produce a sentence, never a traceback,
since this runs mid-conversation and the person on the other end only sees
the tool's return value, not a stack trace.
"""
import importlib.util
import os

import httpx
import pytest
import respx

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "agents_tool.py")

CHAT_URL = "http://test-tasks:8210/agents/chat"
SECRET = "sekrit-value-should-never-appear-anywhere-in-output"


def _load():
    spec = importlib.util.spec_from_file_location("agents_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


@pytest.fixture
def tool(mod):
    t = mod.Tools()
    t.valves.tasks_url = "http://test-tasks:8210"
    t.valves.internal_secret = SECRET
    return t


# --- no identifiable user: never makes a request ---------------------------


async def test_no_user_returns_a_readable_sentence(tool):
    out = await tool.ask_agents("hi mia")
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


async def test_user_with_no_email_returns_a_readable_sentence(tool):
    out = await tool.ask_agents("hi mia", __user__={"name": "Bob"})
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


async def test_user_with_empty_email_returns_a_readable_sentence(tool):
    out = await tool.ask_agents("hi mia", __user__={"email": ""})
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


# --- the normal path ---------------------------------------------------


@respx.mock
async def test_two_turns_render_both_names_in_order(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"turns": [
        {"agent": {"id": "agent-m", "name": "Mia"},
         "answer": "Nothing urgent in your inbox.", "notes": []},
        {"agent": {"id": "agent-a", "name": "Ada"},
         "answer": "What do you want me to look into?", "notes": []},
    ]}))

    out = await tool.ask_agents("hi mia and ada",
                                __user__={"email": "owner@example.com"})

    mia_pos = out.find("Mia:")
    ada_pos = out.find("Ada:")
    assert mia_pos != -1 and ada_pos != -1
    assert mia_pos < ada_pos, "Mia was named first and must render first"
    assert "Nothing urgent" in out
    assert "What do you want me to look into" in out


@respx.mock
async def test_a_no_agent_turn_has_no_name_prefix(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={
        "turns": [{"agent": None, "answer": "I can help.", "notes": []}]}))

    out = await tool.ask_agents("what is the weather",
                                __user__={"email": "owner@example.com"})

    assert "I can help." in out
    # No agent means no name was ever spoken, so no line may look like a
    # "Name:" prefix in front of the answer.
    assert "None:" not in out


@respx.mock
async def test_notes_ride_along_with_the_answer(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"turns": [
        {"agent": {"id": "a", "name": "Mia"}, "answer": "Here is the draft.",
         "notes": ["Declined to run send_email, because this agent is set to read only."]}]}))

    out = await tool.ask_agents("mia send it",
                                __user__={"email": "owner@example.com"})
    assert "Declined to run send_email" in out


@respx.mock
async def test_the_leading_line_instructs_relaying_verbatim(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"turns": [
        {"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Four unread.",
         "notes": []}]}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    first_line = out.split("\n")[0]
    assert "verbatim" in first_line.lower() or "exactly" in first_line.lower()
    assert "Four unread." in out


@respx.mock
async def test_no_turns_returns_a_readable_sentence(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"turns": []}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()


# --- the request itself fails ---------------------------------------------


@respx.mock
async def test_the_http_call_raising_returns_a_readable_sentence(tool):
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("boom"))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "could not reach your agents" in out


@respx.mock
async def test_a_non_200_status_returns_a_readable_sentence(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(500, json={
        "detail": "internal error"}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "could not reach your agents" in out


# --- malformed shapes: the response crossed a process boundary -----------
# Each of these must survive with a sentence, not an AttributeError, because
# a 200 with the wrong shape is exactly what a bug on the other side would
# produce, and this tool runs mid-conversation.


@respx.mock
async def test_a_non_json_body_does_not_raise(tool):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, content=b"not json at all"))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "could not reach your agents" in out


@respx.mock
async def test_a_non_dict_body_does_not_raise(tool):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=["not", "a", "dict"]))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()


@respx.mock
async def test_a_non_list_turns_does_not_raise(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={
        "turns": "not a list"}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()


@respx.mock
async def test_a_non_dict_turn_is_skipped_not_raised(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={
        "turns": ["not-a-dict", {"agent": {"id": "a", "name": "Mia"},
                                 "answer": "Here.", "notes": []}]}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "Mia" in out
    assert "Here." in out


# --- the secret and the internal URL never leak into the answer ----------


@respx.mock
async def test_the_secret_and_url_never_appear_on_the_success_path(tool):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json={"turns": [
        {"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Four unread.",
         "notes": []}]}))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert SECRET not in out
    assert tool.valves.tasks_url not in out


@respx.mock
async def test_the_secret_and_url_never_appear_on_the_failure_path(tool):
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("boom"))

    out = await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})

    assert SECRET not in out
    assert tool.valves.tasks_url not in out


# --- the chat id is stable across a conversation on this path --------------


@respx.mock
async def test_the_chat_id_is_stable_for_the_same_user(tool):
    """The tool is never given a real chat id, only the message text. The
    pin has to persist across turns on this path anyway, so the chat id it
    sends must be the same value every time for the same user."""
    seen = []

    def _capture(request):
        import json
        seen.append(json.loads(request.content)["chat_id"])
        return httpx.Response(200, json={"turns": []})

    respx.post(CHAT_URL).mock(side_effect=_capture)

    await tool.ask_agents("hi mia", __user__={"email": "owner@example.com"})
    await tool.ask_agents("now check my calendar",
                          __user__={"email": "owner@example.com"})

    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert seen[0], "the chat id must not be empty"


# --- no dashes in the copy this tool writes --------------------------------


def test_no_dashes_in_the_tool_copy():
    with open(TOOL_PATH, "rb") as f:
        data = f.read()
    assert chr(0x2014).encode("utf-8") not in data
    assert chr(0x2013).encode("utf-8") not in data
