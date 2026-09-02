"""The Open WebUI tool the model calls to check what is connected.

Loaded by path, the same way tests/test_io_gateway_pipe.py loads
open-webui-functions/io_gateway_pipe.py, because this file lives outside the
tasks service and is never imported by anything in it.

The tool talks to another service over HTTP, so its shape is not ours to
trust: a malformed response must produce a sentence, never a traceback, since
this runs mid-conversation and the person on the other end only sees the
tool's return value, not a stack trace.
"""
import importlib.util
import os

import httpx
import pytest
import respx

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "account_tool.py")

SUMMARY_URL = "http://test-tasks:8210/account/summary"
SECRET = "sekrit-value-should-never-appear-anywhere-in-output"


def _load():
    spec = importlib.util.spec_from_file_location("account_tool", TOOL_PATH)
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


# --- no identifiable user: never makes a request -----------------------


async def test_no_user_returns_a_readable_sentence(tool):
    out = await tool.my_account()
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


async def test_user_with_no_email_returns_a_readable_sentence(tool):
    out = await tool.my_account(__user__={"name": "Bob"})
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


async def test_user_with_empty_email_returns_a_readable_sentence(tool):
    out = await tool.my_account(__user__={"email": ""})
    assert isinstance(out, str) and out.strip()
    assert "could not tell whose account" in out


# --- the normal path -----------------------------------------------------


@respx.mock
async def test_a_normal_response_renders_connected_and_offers_the_rest(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": [{"id": "gmail", "label": "Gmail"}],
        "not_connected": [
            {"id": "clickup", "label": "ClickUp", "how": "key",
             "connect_url": "#aiui-connect:clickup",
             "where": "ClickUp, under Settings then Apps"},
            {"id": "notion", "label": "Notion", "how": "login",
             "connect_url": "#aiui-connect:notion", "where": ""},
        ]}))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert "Connected: Gmail" in out
    # Byte for byte: the frontend in the next task matches this literal
    # string, so a reformat (extra space, different quoting, percent
    # encoding) means the button silently never appears.
    assert "[Connect ClickUp](#aiui-connect:clickup)" in out
    assert "[Connect Notion](#aiui-connect:notion)" in out
    assert "needs an API key from ClickUp, under Settings then Apps" in out
    assert "opens a login" in out


@respx.mock
async def test_nothing_connected_still_offers_what_is_missing(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": [],
        "not_connected": [
            {"id": "clickup", "label": "ClickUp", "how": "key",
             "connect_url": "#aiui-connect:clickup", "where": "ClickUp"},
        ]}))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert "Nothing is connected yet." in out
    assert "[Connect ClickUp](#aiui-connect:clickup)" in out


# --- the request itself fails ---------------------------------------------


@respx.mock
async def test_the_http_call_raising_returns_a_readable_sentence(tool):
    respx.get(SUMMARY_URL).mock(side_effect=httpx.ConnectError("boom"))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "could not check your connected apps" in out


@respx.mock
async def test_a_non_200_status_returns_a_readable_sentence(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(500, json={
        "detail": "internal error"}))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "could not check your connected apps" in out


# --- malformed shapes: the response crossed a process boundary -----------
# Each of these must survive with a sentence, not an AttributeError, because
# a 200 with the wrong shape is exactly what a bug on the other side would
# produce, and this tool runs mid-conversation.


@respx.mock
async def test_a_non_dict_body_does_not_raise(tool):
    respx.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=["not", "a", "dict"]))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "Nothing is connected yet." in out


@respx.mock
async def test_a_non_list_connected_does_not_raise(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": "gmail, drive",
        "not_connected": [
            {"id": "clickup", "label": "ClickUp", "how": "key",
             "connect_url": "#aiui-connect:clickup", "where": "ClickUp"},
        ]}))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "Nothing is connected yet." in out
    assert "[Connect ClickUp](#aiui-connect:clickup)" in out


@respx.mock
async def test_a_non_list_not_connected_does_not_raise(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": [{"id": "gmail", "label": "Gmail"}],
        "not_connected": {"clickup": "missing"},
    }))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "Connected: Gmail" in out


@respx.mock
async def test_a_non_dict_entry_in_either_list_is_skipped_not_raised(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": ["not-a-dict", {"id": "gmail", "label": "Gmail"}],
        "not_connected": [123, {
            "id": "clickup", "label": "ClickUp", "how": "key",
            "connect_url": "#aiui-connect:clickup", "where": "ClickUp"}],
    }))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert isinstance(out, str) and out.strip()
    assert "Connected: Gmail" in out
    assert "[Connect ClickUp](#aiui-connect:clickup)" in out


# --- the secret and the internal URL never leak into the answer ----------


@respx.mock
async def test_the_secret_and_url_never_appear_on_the_success_path(tool):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json={
        "connected": [{"id": "gmail", "label": "Gmail"}],
        "not_connected": []}))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert SECRET not in out
    assert tool.valves.tasks_url not in out


@respx.mock
async def test_the_secret_and_url_never_appear_on_the_failure_path(tool):
    respx.get(SUMMARY_URL).mock(side_effect=httpx.ConnectError("boom"))

    out = await tool.my_account(__user__={"email": "owner@example.com"})

    assert SECRET not in out
    assert tool.valves.tasks_url not in out
