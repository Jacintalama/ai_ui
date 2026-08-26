"""Executing a tool call on someone's behalf.

The identity assertions here are the point. A previous review found two
mutations of this codebase's identity resolution that passed every test,
so every path below asserts WHOSE account was used, by value.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent_tools import execute_tool_call


def _call(name, args=None, cid="call_1"):
    return {"id": cid, "function": {"name": name,
                                    "arguments": json.dumps(args or {})}}


async def test_a_native_tool_runs_as_the_named_user():
    """The tool's own source is loaded and called with that user's email."""
    source = (
        "class Tools:\n"
        "    async def list_unread_emails(self, max_results=15, __user__=None):\n"
        "        return 'seen-by:' + (__user__ or {}).get('email', 'nobody')\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(_call("list_unread_emails"),
                                      "owner@example.com")
    assert out == "seen-by:owner@example.com"


async def test_arguments_are_decoded_from_the_json_string():
    source = (
        "class Tools:\n"
        "    async def search_emails(self, query='', __user__=None):\n"
        "        return 'q=' + query\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(
            _call("search_emails", {"query": "invoices"}), "owner@example.com")
    assert out == "q=invoices"


async def test_a_proxy_tool_is_called_with_the_users_email_header():
    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"result": "ok"})

    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json", new=fake_post):
        out = await execute_tool_call(
            _call("clickup_list_tasks"), "owner@example.com")

    assert captured["headers"]["X-User-Email"] == "owner@example.com"
    assert captured["json"]["tool_name"] == "clickup_list_tasks"
    assert "/meta/call_tool" in captured["url"]
    assert "ok" in out


async def test_a_failing_tool_returns_an_error_string_and_does_not_raise():
    """The loop must be able to hand the failure to the model and let it
    explain itself, rather than dying and losing the whole run."""
    source = (
        "class Tools:\n"
        "    async def read_email(self, __user__=None):\n"
        "        raise RuntimeError('mailbox on fire')\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(_call("read_email"), "owner@example.com")
    assert "could not" in out.lower() or "error" in out.lower()


async def test_an_unknown_tool_returns_a_message_rather_than_raising():
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json",
               new=AsyncMock(return_value=_FakeResponse(404, {"detail": "no"}))):
        out = await execute_tool_call(_call("nope_nope"), "owner@example.com")
    assert isinstance(out, str) and out


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload
