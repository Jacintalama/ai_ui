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


async def test_a_hyphenated_server_prefix_reaches_the_proxy_path():
    """F1: the live proxy serves 312 tools, 44 of which have a server prefix
    containing a hyphen (the whole my-* per-user family, plus google-drive_*
    and web-search_*). None of those is a valid Python identifier, so the
    identifier guard must not refuse them outright -- it protects only the
    native path's getattr, and a hyphenated name can never be a native
    method name in the first place. It must fall through to the proxy
    exactly like any other proxy tool, and _load_native_tool_source must
    never be consulted for it, since no valid Python source could define a
    method whose name contains a hyphen."""
    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"result": "ok"})

    source_lookup = AsyncMock(return_value=None)
    with patch("agent_tools._load_native_tool_source", new=source_lookup), \
         patch("agent_tools._post_json", new=fake_post):
        out = await execute_tool_call(
            _call("my-clickup_list_tasks"), "owner@example.com")

    source_lookup.assert_not_called()
    assert captured["headers"]["X-User-Email"] == "owner@example.com"
    assert captured["json"]["tool_name"] == "my-clickup_list_tasks"
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


_ECHO_SOURCE = (
    "class Tools:\n"
    "    async def list_unread_emails(self, max_results=15, __user__=None):\n"
    "        return 'seen-by:' + (__user__ or {}).get('email', 'nobody')\n"
)


@pytest.mark.parametrize("bad_arguments", [42, 3.14, True, [1, 2, 3]])
async def test_non_string_non_dict_arguments_do_not_raise(bad_arguments):
    """F1: arguments can arrive as something dict(...) itself chokes on --
    dict(42), dict(3.14), dict(True) and dict([1, 2, 3]) all raise TypeError,
    not the ValueError the old except clause caught. Both must degrade to
    "no arguments" rather than blowing up execute_tool_call, since the tool
    call came from a model, not validated input."""
    call = {"id": "call_1",
             "function": {"name": "list_unread_emails", "arguments": bad_arguments}}
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=_ECHO_SOURCE)):
        out = await execute_tool_call(call, "owner@example.com")
    assert isinstance(out, str) and out


async def test_a_sync_native_tool_method_is_awaited_only_if_awaitable():
    """F2: create_excel and create_dashboard are plain `def`, not async def.
    Unconditionally awaiting their return value raises and discards the
    finished work; only await when the call actually gives back something
    awaitable. Cover both a sync and an async method here."""
    sync_source = (
        "class Tools:\n"
        "    def create_excel(self, specification='', __user__=None):\n"
        "        return 'xlsx-for:' + (__user__ or {}).get('email', 'nobody')\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=sync_source)):
        sync_out = await execute_tool_call(_call("create_excel"), "owner@example.com")
    assert sync_out == "xlsx-for:owner@example.com"

    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=_ECHO_SOURCE)):
        async_out = await execute_tool_call(_call("list_unread_emails"),
                                            "owner@example.com")
    assert async_out == "seen-by:owner@example.com"


async def test_private_and_dunder_method_names_are_refused():
    """F3: a method name has to be a plain public identifier before it is
    even looked up. The guard has to sit before _load_native_tool_source is
    called at all -- not just before what it returns is used -- because
    execute_tool_call's own except Exception would otherwise swallow a
    raise-if-called side effect and make this test pass either way. So
    assert on the mock's call count, not on anything raised inside it.
    """
    for bad_name in ("__init__", "_email", "_post", "__class__", "__globals__"):
        source_lookup = AsyncMock(return_value=_ECHO_SOURCE)
        with patch("agent_tools._load_native_tool_source", new=source_lookup):
            out = await execute_tool_call(_call(bad_name), "owner@example.com")
        assert isinstance(out, str) and out
        source_lookup.assert_not_called()

    # A normal public name is unaffected by the guard.
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=_ECHO_SOURCE)):
        out = await execute_tool_call(_call("list_unread_emails"), "owner@example.com")
    assert out == "seen-by:owner@example.com"


async def test_unexpected_argument_is_dropped_and_the_call_still_succeeds():
    """F5: a model that hallucinates a parameter must not kill the call.
    Without filtering, the extra 'unexpected' kwarg raises a bare TypeError
    from inside the method call, which the outer except turns into the
    generic failure string instead of the real answer."""
    source = (
        "class Tools:\n"
        "    async def search_emails(self, query='', __user__=None):\n"
        "        return 'q=' + query\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(
            _call("search_emails", {"query": "invoices", "unexpected": "x"}),
            "owner@example.com")
    assert out == "q=invoices"


async def test_a_kwargs_catch_all_method_still_receives_everything():
    """F5: a method that declares **kwargs opts in to accepting anything,
    so nothing supplied by the model should be dropped for it."""
    source = (
        "class Tools:\n"
        "    async def search_emails(self, query='', __user__=None, **kwargs):\n"
        "        return 'q=' + query + ' extra=' + ','.join(sorted(kwargs))\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(
            _call("search_emails", {"query": "invoices", "unexpected": "x"}),
            "owner@example.com")
    assert out == "q=invoices extra=unexpected"


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


# The wrong TYPE, not merely a missing key. Earlier adversarial sweeps
# enumerated malformed `arguments` exhaustively and malformed `tool_call`
# only as None or {}, so every one of these raised AttributeError out of a
# function whose contract is that it never raises.
MALFORMED_CALLS = [
    "not a dict",
    42,
    3.14,
    True,
    ["a", "list"],
    {"id": "x", "function": [1, 2, 3]},
    {"id": "x", "function": "nope"},
    {"id": "x", "function": {"name": {"nested": 1}, "arguments": "{}"}},
    {"id": "x", "function": {"name": 7, "arguments": "{}"}},
]


@pytest.mark.parametrize("call", MALFORMED_CALLS)
async def test_a_malformed_tool_call_returns_a_string_instead_of_raising(call):
    out = await execute_tool_call(call, "owner@example.com")
    assert isinstance(out, str) and out
