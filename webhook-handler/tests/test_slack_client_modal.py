"""SlackClient.get_user_email and open_modal (mocked Slack Web API)."""
import httpx
import pytest
import respx

from clients.slack import SlackClient

SLACK = "https://slack.com/api"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_email_happy():
    respx.get(f"{SLACK}/users.info").mock(
        return_value=httpx.Response(200, json={
            "ok": True, "user": {"profile": {"email": "Alice@Example.com"}},
        })
    )
    client = SlackClient(bot_token="xoxb-test")
    assert await client.get_user_email("U123") == "alice@example.com"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_email_no_email():
    respx.get(f"{SLACK}/users.info").mock(
        return_value=httpx.Response(200, json={"ok": True, "user": {"profile": {}}})
    )
    client = SlackClient(bot_token="xoxb-test")
    assert await client.get_user_email("U123") is None


@pytest.mark.asyncio
@respx.mock
async def test_get_user_email_api_error():
    respx.get(f"{SLACK}/users.info").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "missing_scope"})
    )
    client = SlackClient(bot_token="xoxb-test")
    assert await client.get_user_email("U123") is None


@pytest.mark.asyncio
async def test_get_user_email_empty_id_no_call():
    client = SlackClient(bot_token="xoxb-test")
    assert await client.get_user_email("") is None


@pytest.mark.asyncio
@respx.mock
async def test_open_modal_posts_to_views_open():
    route = respx.post(f"{SLACK}/views.open").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SlackClient(bot_token="xoxb-test")
    ok = await client.open_modal("trigger-123", {"type": "modal"})
    assert ok is True
    assert route.called
    sent = route.calls.last.request
    assert b"trigger-123" in sent.content


@pytest.mark.asyncio
@respx.mock
async def test_open_modal_failure_returns_false():
    respx.post(f"{SLACK}/views.open").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "expired_trigger_id"})
    )
    client = SlackClient(bot_token="xoxb-test")
    assert await client.open_modal("t", {"type": "modal"}) is False
