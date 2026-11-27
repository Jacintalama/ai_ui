"""A person's own MCP tool asks first unless their server marked it a read.

is_write_call judges the inner tool_name of a call_tool. For a built tool the
name is the whole story; for an own tool it is not, because two people's
servers can mark the same name differently. So an own tool is judged per
person, from what that person's server said at the last listing, and
anything not known is a write.

And the tasks loop now says it is the tasks loop, with the internal secret,
on every /meta/* call: mcp-proxy only runs an own tool that can change
something for a caller that held it for approval first.
"""
import os

import httpx
import respx

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import agent_tools  # noqa: E402
import own_mcp  # noqa: E402
from agent_tools import is_write_call  # noqa: E402

A = "a@x.com"
B = "b@x.com"


def setup_function():
    own_mcp.remember(A, [{"name": "own-acme_list_customers", "read_only": True},
                         {"name": "own-acme_create_invoice", "read_only": False}])
    own_mcp.remember(B, [])


def test_an_own_tool_marked_read_only_by_its_owner_does_not_ask():
    assert is_write_call("call_tool", {"tool_name": "own-acme_list_customers"},
                         email=A) is False


def test_an_own_write_asks():
    assert is_write_call("call_tool", {"tool_name": "own-acme_create_invoice"},
                         email=A) is True


def test_the_same_name_for_someone_else_asks():
    assert is_write_call("call_tool", {"tool_name": "own-acme_list_customers"},
                         email=B) is True


def test_an_own_tool_with_no_email_asks():
    assert is_write_call("call_tool", {"tool_name": "own-acme_list_customers"}) is True


def test_built_tools_are_judged_as_before():
    assert is_write_call("call_tool", {"tool_name": "web-search_web_search"},
                         email=A) is False
    assert is_write_call("call_tool", {"tool_name": "clickup_create_task"},
                         email=A) is True
    assert is_write_call("send_email", None, email=A) is True


@respx.mock
async def test_the_loop_sends_the_secret_on_every_meta_call(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "s3cret")
    route = respx.post("http://mcp-proxy:8000/meta/search_tools").mock(
        return_value=httpx.Response(200, json={"results": []}))
    await agent_tools.tools_for_message(A, "check my invoices")
    sent = route.calls[0].request.headers
    assert sent["x-internal-secret"] == "s3cret" and sent["x-user-email"] == A


def test_the_header_helper_has_the_secret_only_when_set(monkeypatch):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "s3cret")
    assert agent_tools._proxy_headers(A) == {"X-User-Email": A,
                                             "X-Internal-Secret": "s3cret"}
    monkeypatch.delenv("INTERNAL_CALLBACK_SECRET")
    assert agent_tools._proxy_headers(A) == {"X-User-Email": A}


def test_every_meta_post_uses_the_helper():
    """Four posts reach mcp-proxy's /meta routes; none may carry the bare
    email header on its own, or that call loses the right to run a write."""
    import inspect
    src = inspect.getsource(agent_tools)
    assert src.count('headers={"X-User-Email": user_email}') == 0
    assert src.count("headers=_proxy_headers(user_email)") == 4
