"""The shared ClickUp connector is off, and not merely because it is broken.

On 2026-11-06 Ralph asked the main chat to make a list in ClickUp. The chat
called `clickup_clickup_create_list`, told him it had succeeded, and nothing
was created. Two faults behind that, and this file is about the second:

  1. The container behind the shared connector had been crash-looping for
     days. Every call returned unavailable, so "success" was the model's
     own wording rather than a result.

  2. It would not have helped if it HAD been up. The shared connector
     spends one CLICKUP_API_TOKEN for everybody, and that token belongs to
     a single teammate: `GET /v2/user` on it answers Lukas Herajt, and the
     only workspace it can see is his personal one. Anything "created in
     ClickUp" through it lands in his account, not in the workspace of the
     person who asked.

A per-user connector already exists and works: `my-clickup`, which acts as
the signed-in person's own connected account and was serving while the
shared one was down. That is the one models should reach, so the shared
entry is off by name rather than left to auto-enable on the presence of a
token.

Deliberately NOT changed at the time: `trello`. Same shape and the same
one-token-for-everyone concern, but it recovered on 2026-11-06 and served
25 tools against `my-trello`'s 7, so turning it off would have removed
work people could do.

SUPERSEDED 2026-11-11. That gap was the whole reason, and #178, #179 and
#180 closed it: `my-trello` has 13 tools now and `my-github` 21. So
`trello`, `github` and `n8n` were switched off too, for the same reason
ClickUp was. See test_the_shared_connectors_are_off.py, which also records
why n8n turned out to be the cheapest of the three rather than the hardest.
"""
import os

import pytest

import tenants


@pytest.fixture(autouse=True)
def _as_the_server_sees_it(monkeypatch):
    """Every assertion here runs with CLICKUP_API_TOKEN SET.

    Without this the file lies. `enabled` used to be
    `bool(os.getenv("CLICKUP_API_TOKEN"))`, so on a laptop with no token
    it was already False and the test passed while the server, which has
    the token, had it True. The token is still set on the server because
    the container itself needs it, so the only honest world to test in is
    the one where it exists.
    """
    monkeypatch.setenv("CLICKUP_API_TOKEN", "pk_whatever")
    monkeypatch.setenv("TRELLO_API_KEY", "trello_whatever")
    import importlib
    importlib.reload(tenants)
    yield
    monkeypatch.undo()
    importlib.reload(tenants)


def _clickup():
    return tenants.ALL_SERVERS["clickup"]


def test_the_shared_clickup_connector_is_not_enabled():
    assert _clickup().enabled is False, (
        "the shared ClickUp connector is reachable again; it spends one "
        "person's token for everybody")


def test_the_credential_is_no_longer_what_decides():
    """The fixture above has the token set. If `enabled` still reads it,
    this file is back where it started."""
    import inspect
    src = inspect.getsource(tenants)
    block = src[src.index('"clickup": MCPServerConfig('):]
    block = block[:block.index("),")]
    assert 'os.getenv("CLICKUP_API_TOKEN")' not in block, (
        "the shared connector is auto-enabled by the presence of a token "
        "again")


def test_the_per_user_one_is_still_on():
    """Turning off the shared connector must not leave people with no way
    to reach ClickUp at all."""
    mine = tenants.ALL_SERVERS["my-clickup"]
    assert mine.enabled is True
    assert mine.access_class == tenants.AccessClass.PUBLIC
    assert "my-tools" in mine.endpoint_url or "mytools" in mine.endpoint_url


def test_trello_is_off_too_now():
    """This asked to be told if somebody turned Trello off as well. That
    happened on 2026-11-11, deliberately, once #178 had closed the tool
    gap that was the reason to leave it on.

    The old assertion was `enabled is not None`, which False satisfies, so
    it would never have noticed either way. Asserting the actual state
    instead, so this file tracks reality rather than permitting anything.
    """
    assert tenants.ALL_SERVERS["trello"].enabled is False
    assert tenants.ALL_SERVERS["my-trello"].enabled is True


def test_no_other_shared_connector_was_switched_off_by_this():
    """A guard on the edit itself: exactly one SHARED server should have
    gone from auto-enabled to off, and it should be ClickUp."""
    shared_off = sorted(
        sid for sid, cfg in tenants.ALL_SERVERS.items()
        if cfg.access_class == tenants.AccessClass.SHARED
        and cfg.enabled is False
        and cfg.endpoint_url and "mcp-" in str(cfg.endpoint_url))
    assert "clickup" in shared_off
    # Since 2026-11-11 it is no longer the only one; the three that
    # followed have their own file.
    assert {"trello", "github", "n8n"} <= set(shared_off)
