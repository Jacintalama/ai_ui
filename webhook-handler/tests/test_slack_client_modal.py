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


# ---------------------------------------------------------------------------
# Task A1 — post_message with blocks + attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_post_message_with_blocks_and_attachments():
    """Blocks and attachments are forwarded in the JSON body; ts is returned."""
    import json as _json

    route = respx.post(f"{SLACK}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "ts": "1111.2222"})
    )
    client = SlackClient(bot_token="xoxb-test")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]
    attachments = [{"color": "#36a64f", "blocks": []}]
    ts = await client.post_message(
        "C999",
        "fallback",
        blocks=blocks,
        attachments=attachments,
    )
    assert ts == "1111.2222"
    body = _json.loads(route.calls.last.request.content)
    assert body["blocks"] == blocks
    assert body["attachments"] == attachments
    assert body["text"] == "fallback"
    assert body["channel"] == "C999"


@pytest.mark.asyncio
@respx.mock
async def test_post_message_text_only_still_works():
    """Existing text-only callers keep working; blocks/attachments absent from body."""
    import json as _json

    route = respx.post(f"{SLACK}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "ts": "9999.0001"})
    )
    client = SlackClient(bot_token="xoxb-test")
    ts = await client.post_message("C001", "plain text", thread_ts="1234.5678")
    assert ts == "9999.0001"
    body = _json.loads(route.calls.last.request.content)
    assert body["text"] == "plain text"
    assert body["thread_ts"] == "1234.5678"
    assert "blocks" not in body
    assert "attachments" not in body
