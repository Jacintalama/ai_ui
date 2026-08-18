"""Who may search for a tool, and who may run one.

The meta endpoints are the whole tool surface: three endpoints that between
them can find any of ~350 tools, read its schema, and execute it. Every one of
them guarded its access check with `if user_email:`, so a caller the proxy
could not identify SKIPPED the check instead of failing it.

That is not a theoretical shape. `/meta/*` is routed to the public internet by
Caddy, and api-gateway reads a JWT only if one is present. An unauthenticated
POST from anywhere therefore reached `call_tool` with no user, took the
`if user_email:` branch as false, and executed the tool with the platform's
own shared credentials. It was proved against production with a read-only
Trello call that returned a real private workspace.

`/servers` had the correct behaviour all along ("User not identified"), which
is what makes this a slip rather than a design: two endpoints, one condition,
opposite answers.

The rule these tests pin down: an unidentified caller gets nothing, and an
identified caller with no grants also gets nothing. "No access configured"
must never widen into "access to everything".
"""
import pytest
from fastapi import HTTPException

from access import may_use_server, require_identified, servers_for_caller


# --- an unidentified caller is refused, not served -----------------------

@pytest.mark.parametrize("anonymous", [None, "", "   "])
def test_an_unidentified_caller_is_refused(anonymous):
    with pytest.raises(HTTPException) as excinfo:
        require_identified(anonymous)
    assert excinfo.value.status_code == 401


def test_the_refusal_says_what_to_do_about_it():
    with pytest.raises(HTTPException) as excinfo:
        require_identified(None)
    assert str(excinfo.value.detail).strip()


def test_an_identified_caller_passes():
    require_identified("ralph@example.com")   # must not raise


# --- "no grants" is deny, never allow-all --------------------------------

def test_a_user_with_no_grants_gets_no_servers():
    """The trap this whole class of bug lives in: an empty allow-list read as
    "unfiltered". Every one of these must be an empty set, never None."""
    for empty in (None, [], set(), ()):
        assert servers_for_caller("ralph@example.com", empty) == set()


def test_a_user_gets_exactly_their_own_servers():
    assert servers_for_caller("ralph@example.com", ["scheduler", "github"]) == {
        "scheduler", "github"}


def test_servers_for_caller_still_refuses_an_unidentified_caller():
    """Belt and braces: even if a caller reaches this without the guard."""
    with pytest.raises(HTTPException):
        servers_for_caller(None, ["github"])


# --- the per-tool decision -----------------------------------------------

def test_an_empty_allow_list_denies_every_server():
    """`if allowed_servers and tool.tenant_id not in allowed_servers` was the
    original check. An empty set is falsy, so it admitted EVERY server. This
    is that exact expression's replacement and it must deny instead."""
    assert may_use_server(set(), "clickup") is False
    assert may_use_server(set(), "trello") is False


def test_a_granted_server_is_allowed():
    assert may_use_server({"scheduler", "github"}, "scheduler") is True


def test_a_server_outside_the_grant_is_denied():
    assert may_use_server({"scheduler"}, "clickup") is False


# --- the endpoints must actually use it ----------------------------------

def _main_source():
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8", errors="replace")


@pytest.mark.parametrize("endpoint", [
    "meta_search_tools", "meta_describe_tools", "meta_call_tool"])
def test_every_meta_endpoint_demands_an_identified_caller(endpoint):
    """A unit-tested helper nothing calls is worth nothing. This pins the
    call site, because the bug was never in the decision, it was in whether
    the decision got made at all."""
    src = _main_source()
    start = src.index(f"async def {endpoint}(")
    body = src[start:start + 2500]
    assert "require_identified(user_email)" in body, (
        f"{endpoint} does not refuse an unidentified caller")


def test_no_meta_endpoint_still_gates_its_access_check_on_having_a_user():
    """`if user_email:` around an access check is the bug itself: no user
    means the check is skipped, which is backwards. Guard against it coming
    back by any route."""
    src = _main_source()
    for endpoint in ("meta_search_tools", "meta_describe_tools", "meta_call_tool"):
        start = src.index(f"async def {endpoint}(")
        body = src[start:start + 2500]
        assert "if user_email:" not in body, (
            f"{endpoint} still makes its access check conditional on having a user")


# --- the direct execution paths ------------------------------------------
# /meta/* is not the only way to run a tool. /servers advertises
# "POST /{server_id}/{tool_name}", and a legacy flat route runs one too. Both
# carried the same fail-open, so fixing only the meta endpoints closed one
# door of three: /mcp/trello/list_workspaces still answered an anonymous
# request with a real private workspace after the first fix was live.

EXECUTING_ENDPOINTS = ["execute_server_tool", "execute_tool_endpoint_legacy"]


def _endpoint_body(name, span=3200):
    src = _main_source()
    start = src.index(f"async def {name}(")
    return src[start:start + span]


@pytest.mark.parametrize("endpoint", EXECUTING_ENDPOINTS + ["get_server_tools"])
def test_every_executing_endpoint_demands_an_identified_caller(endpoint):
    assert "require_identified(" in _endpoint_body(endpoint), (
        f"{endpoint} can still be reached without a caller")


@pytest.mark.parametrize("endpoint", EXECUTING_ENDPOINTS)
def test_no_executing_endpoint_makes_its_access_check_optional(endpoint):
    """`if user:` around the access check is the same bug as `if user_email:`,
    written against the UserInfo object instead of the address."""
    body = _endpoint_body(endpoint)
    assert "if user:\n" not in body, (
        f"{endpoint} still only checks access when it happens to have a user")


def test_identity_can_never_come_from_a_query_parameter():
    """`?user_email=` was accepted as identity "for testing/demo". It is a
    complete authentication bypass: appending
    ?user_email=<an MCP-Admin address> to any tool URL granted every server,
    because MCP-Admin membership is looked up from that address alone.
    """
    src = _main_source()
    assert 'query_params.get("user_email")' not in src
    # The impersonation path constructed a UserInfo out of thin air:
    assert 'user_id="query_param"' not in src


def test_the_legacy_route_does_not_dump_every_request_header():
    """It printed every header to container stdout, Cookie and Authorization
    included. Truncating a session cookie to 50 characters does not make it
    safe to log."""
    body = _endpoint_body("execute_tool_endpoint_legacy")
    assert "for key, value in request.headers.items()" not in body


def test_no_endpoint_returns_the_raw_request_headers():
    """/debug/headers returned dict(request.headers) to anyone who asked."""
    assert "return dict(request.headers)" not in _main_source()


def test_the_openapi_spec_lists_nothing_for_an_unidentified_caller():
    """Standard mode (META_TOOLS_MODE=false) builds the spec by walking every
    server and tool and skipping the ones the user cannot reach, guarded by
    `if user_email:`. Unidentified therefore meant "list the entire estate".
    It is currently masked because meta-tools mode returns earlier, but that
    is an environment variable, not a fix.
    """
    src = _main_source()
    assert "        if user_email:\n            if not await user_has_tenant_access_async" not in src
