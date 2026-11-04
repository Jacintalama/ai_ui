"""A first GitHub connect picks repositories in the same approval.

Ralph, 2026-11-04, looking at a popup that said "Connected" above a link
he still had to click: "why is this like this? please fix use the default
one please like in the vercel".

He is describing the two-act split GitHub makes. Authorising says who you
are; INSTALLING grants repository access. Our app is registered with
"request user authorization during installation", and GitHub's docs are
explicit that such an app cannot have a separate setup URL: the install
redirects to the Callback URL as part of the authorization flow. So the
install page gives both in one approval.

It is not symmetric, which is why this is conditional rather than a
straight swap. For an app somebody has already installed, that same URL
shows Configure, finishes on GitHub and never redirects back with a code.
That was measured as seven oauth/start calls and zero callbacks the last
time every connect was pointed at it.
"""
import asyncio
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import oauth_providers as O
import routes_connections as R


class _Who:
    email = "ralph@example.com"


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setattr(O, "GITHUB_APP_SLUG", "aiuiteams-hub", raising=False)
    monkeypatch.setattr(O, "configured", lambda p: True)
    monkeypatch.setattr(O, "client_credentials", lambda p: ("cid", "sec"))
    seen = {"has": False}
    async def _has(email, provider):
        return seen["has"]
    monkeypatch.setattr(R, "_has_connection", _has)
    return seen


def _start(provider="github"):
    return asyncio.run(R.oauth_start(provider, user=_Who()))["url"]


def test_a_first_connect_goes_to_the_page_that_picks_repositories(github):
    github["has"] = False
    url = _start()
    assert "installations/new" in url, url


def test_the_state_rides_along_so_the_callback_knows_who_it_is(github):
    """Without it the code comes back belonging to nobody."""
    github["has"] = False
    assert "state=" in _start()


def test_a_reconnect_uses_the_url_that_always_returns(github):
    """The install page shows Configure for an app already installed,
    finishes on GitHub, and never comes back with a code."""
    github["has"] = True
    url = _start()
    assert "installations/new" not in url
    assert "login/oauth/authorize" in url


def test_an_unconfigured_slug_never_breaks_the_connect(github, monkeypatch):
    """GITHUB_APP_SLUG unset makes install_url empty. Returning that would
    send somebody to nowhere instead of to a working authorize page."""
    github["has"] = False
    monkeypatch.setattr(O, "GITHUB_APP_SLUG", "", raising=False)
    assert "login/oauth/authorize" in _start()


def test_nothing_else_is_sent_to_an_install_page(github):
    """Only GitHub splits authorising from installing. Every other app
    keeps its own authorize URL, which is not GitHub-shaped: ClickUp's is
    app.clickup.com/api, so the property to assert is that it is not sent
    to an install page, not that it looks like GitHub's."""
    github["has"] = False
    url = _start("clickup")
    assert "installations/new" not in url
    assert "clickup.com" in url


def test_not_knowing_counts_as_new():
    """_has_connection fails closed to False. The install page works for a
    first install and shows an existing installation its repositories; the
    other way round, a blip sends a first-timer to authorize and leaves
    them connected to nothing."""
    # Not the `github` fixture: it replaces _has_connection, so reading
    # the source through it would read the fake and pass on anything.
    import inspect
    src = inspect.getsource(R._has_connection)
    assert src.count("return False") >= 2
    assert "fetchrow" in src


def test_checking_decrypts_nothing():
    """It answers which page to open. That is no reason to decrypt
    somebody's credential."""
    import inspect
    src = inspect.getsource(R._has_connection)
    assert "SELECT 1 FROM tasks.user_connections" in src
    assert "secrets_encrypted" not in src
    # The CALL, not the word: this function's own docstring says "nothing
    # is decrypted", which contains it and failed this test first time.
    assert "decrypt(" not in src
