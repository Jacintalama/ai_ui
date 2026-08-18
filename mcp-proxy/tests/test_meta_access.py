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
