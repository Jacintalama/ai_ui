"""Proving a Mattermost server and token before storing them.

Different from the other channels in one way that matters: the HOST comes from
the user. This service is about to make a request to whatever they paste, so
the URL is validated rather than trusted.
"""
import httpx
import pytest

import mattermost_api as mm


class _FakeClient:
    def __init__(self, handler, **_kw):
        self._handler = handler
        self.seen: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self.seen.update({"url": url, **kw})
        return self._handler(url, kw)


def _install(monkeypatch, handler):
    holder = {}

    def factory(**kw):
        holder["client"] = _FakeClient(handler, **kw)
        return holder["client"]

    monkeypatch.setattr(mm, "_client_factory", factory)
    return holder


def _ok(payload=None, status=200):
    def handler(url, kw):
        return httpx.Response(status, json=payload if payload is not None else {},
                              request=httpx.Request("GET", url))
    return handler


# --- the URL, which is user input -------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://mm.example.com", "https://mm.example.com"),
    ("https://mm.example.com/", "https://mm.example.com"),
    ("mm.example.com", "https://mm.example.com"),
    ("http://localhost:8065", "http://localhost:8065"),
])
def test_a_pasted_address_becomes_a_base_url(raw, expected):
    assert mm.normalise_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "https://", "not a url at all",
                                 "ftp://mm.example.com"])
def test_an_address_that_is_not_a_server_is_refused(raw):
    """A typo must not become a request at something nobody meant."""
    with pytest.raises(mm.MattermostError):
        mm.normalise_url(raw)


# --- the credential ---------------------------------------------------

async def test_get_me_returns_the_bot_identity(monkeypatch):
    _install(monkeypatch, _ok({"id": "abc", "username": "io-bot"}))
    me = await mm.get_me("https://mm.example.com", "tok")
    assert me["username"] == "io-bot"
    assert me["url"] == "https://mm.example.com"


async def test_the_token_goes_in_a_bearer_header(monkeypatch):
    holder = _install(monkeypatch, _ok({"username": "x"}))
    await mm.get_me("https://mm.example.com", "tok")
    assert holder["client"].seen["headers"]["Authorization"] == "Bearer tok"
    assert holder["client"].seen["url"].endswith("/api/v4/users/me")


async def test_a_rejected_token_says_so_plainly(monkeypatch):
    _install(monkeypatch, _ok({}, status=401))
    with pytest.raises(mm.MattermostError) as e:
        await mm.get_me("https://mm.example.com", "tok")
    assert "rejected the token" in e.value.description


async def test_pointing_at_something_that_is_not_mattermost_says_so(monkeypatch):
    """The commonest mistake here is a URL that resolves to a web server which
    is not Mattermost at all, and 404 alone tells the user nothing."""
    _install(monkeypatch, _ok({}, status=404))
    with pytest.raises(mm.MattermostError) as e:
        await mm.get_me("https://example.com", "tok")
    assert "bot accounts" in e.value.description.lower()


async def test_a_non_json_answer_is_not_treated_as_success(monkeypatch):
    def handler(url, kw):
        return httpx.Response(200, text="<html>hello</html>",
                              request=httpx.Request("GET", url))
    _install(monkeypatch, handler)
    with pytest.raises(mm.MattermostError) as e:
        await mm.get_me("https://example.com", "tok")
    assert "not like a Mattermost server" in e.value.description


async def test_the_token_never_appears_in_an_error(monkeypatch):
    def boom(url, kw):
        raise httpx.ConnectError("no route")
    _install(monkeypatch, boom)
    with pytest.raises(mm.MattermostError) as e:
        await mm.get_me("https://mm.example.com", "super-secret-token")
    assert "super-secret-token" not in e.value.description
