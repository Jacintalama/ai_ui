"""Proving a user's own Discord or Slack credentials before storing them.

Same contract as telegram_api and for the same reason: a stored row must mean
credentials that worked at least once, so the Channels page can never show a
saved bot that was never going to run.

Everything here goes through the module's client seam, so no test opens a
socket and no token is ever real.
"""
import httpx
import pytest

import discord_api
import slack_api


class _FakeClient:
    """Stands in for httpx.AsyncClient. Records the last request."""

    def __init__(self, handler, **_kw):
        self._handler = handler
        self.seen: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, **kw):
        self.seen.update({"method": method, "url": url, **kw})
        return self._handler(method, url, kw)

    async def get(self, url, **kw):
        return await self.request("GET", url, **kw)

    async def post(self, url, **kw):
        return await self.request("POST", url, **kw)


def _responder(status=200, payload=None):
    def handler(method, url, kw):
        return httpx.Response(status, json=payload if payload is not None else {},
                              request=httpx.Request(method, url))
    return handler


def _install(monkeypatch, module, handler):
    holder = {}

    def factory(**kw):
        client = _FakeClient(handler, **kw)
        holder["client"] = client
        return client

    monkeypatch.setattr(module, "_client_factory", factory)
    return holder


# --- Discord ------------------------------------------------------------

async def test_discord_get_me_returns_the_bot_identity(monkeypatch):
    _install(monkeypatch, discord_api,
             _responder(200, {"id": "42", "username": "helper", "bot": True}))
    me = await discord_api.get_me("token-not-real")
    assert me["username"] == "helper"
    assert me["id"] == "42"


async def test_discord_sends_a_real_user_agent(monkeypatch):
    """Discord sits behind Cloudflare, which 403s a default python user agent.
    That is not hypothetical: it is exactly how the terminal channel's client
    was silently broken for a day."""
    holder = _install(monkeypatch, discord_api, _responder(200, {"username": "x"}))
    await discord_api.get_me("token-not-real")
    ua = holder["client"].seen["headers"]["User-Agent"]
    assert ua and "python" not in ua.lower()


async def test_discord_authorizes_as_a_bot_not_a_bearer(monkeypatch):
    """Discord bot tokens use the Bot scheme. Bearer silently 401s, which
    would read to the user as "your token is wrong"."""
    holder = _install(monkeypatch, discord_api, _responder(200, {"username": "x"}))
    await discord_api.get_me("token-not-real")
    assert holder["client"].seen["headers"]["Authorization"].startswith("Bot ")


async def test_discord_rejects_a_bad_token_with_something_readable(monkeypatch):
    _install(monkeypatch, discord_api,
             _responder(401, {"message": "401: Unauthorized", "code": 0}))
    with pytest.raises(discord_api.DiscordError) as e:
        await discord_api.get_me("token-not-real")
    assert "Unauthorized" in e.value.description


async def test_discord_never_leaks_the_token_when_the_network_fails(monkeypatch):
    def boom(method, url, kw):
        raise httpx.ConnectError("no route to host")
    _install(monkeypatch, discord_api, boom)
    with pytest.raises(discord_api.DiscordError) as e:
        await discord_api.get_me("super-secret-token")
    assert "super-secret-token" not in e.value.description


# --- Slack --------------------------------------------------------------

async def test_slack_auth_test_names_the_workspace(monkeypatch):
    _install(monkeypatch, slack_api,
             _responder(200, {"ok": True, "team": "Acme", "user": "io",
                              "team_id": "T1", "user_id": "U1"}))
    who = await slack_api.auth_test("xoxb-not-real")
    assert who["team"] == "Acme"
    assert who["user"] == "io"


async def test_slack_reports_its_own_error_string(monkeypatch):
    """Slack answers 200 with ok:false, so a status check alone would treat
    an invalid token as success."""
    _install(monkeypatch, slack_api,
             _responder(200, {"ok": False, "error": "invalid_auth"}))
    with pytest.raises(slack_api.SlackError) as e:
        await slack_api.auth_test("xoxb-not-real")
    assert "invalid_auth" in e.value.description


async def test_slack_opens_a_socket_url_to_prove_the_app_token(monkeypatch):
    """The app token is only useful if Socket Mode is actually switched on,
    and forgetting that is the single most common setup mistake. Asking for a
    connection URL proves both at once, without connecting."""
    _install(monkeypatch, slack_api,
             _responder(200, {"ok": True, "url": "wss://wss-primary.slack.com/link/?ticket=x"}))
    url = await slack_api.open_connection("xapp-not-real")
    assert url.startswith("wss://")


async def test_slack_says_so_when_socket_mode_is_off(monkeypatch):
    _install(monkeypatch, slack_api,
             _responder(200, {"ok": False, "error": "not_allowed_token_type"}))
    with pytest.raises(slack_api.SlackError) as e:
        await slack_api.open_connection("xoxb-wrong-kind")
    assert "Socket Mode" in e.value.description


async def test_slack_never_leaks_the_token_when_the_network_fails(monkeypatch):
    def boom(method, url, kw):
        raise httpx.ConnectError("down")
    _install(monkeypatch, slack_api, boom)
    with pytest.raises(slack_api.SlackError) as e:
        await slack_api.auth_test("xoxb-super-secret")
    assert "xoxb-super-secret" not in e.value.description
