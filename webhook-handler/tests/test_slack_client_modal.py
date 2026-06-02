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


# ---------------------------------------------------------------------------
# Task A2 — open_dm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_open_dm_returns_channel_id():
    """ok=True response returns the DM channel id."""
    respx.post(f"{SLACK}/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": True, "channel": {"id": "D123"}})
    )
    client = SlackClient(bot_token="xoxb-test")
    result = await client.open_dm("U456")
    assert result == "D123"


@pytest.mark.asyncio
@respx.mock
async def test_open_dm_not_ok_returns_none():
    """ok=False response returns None."""
    respx.post(f"{SLACK}/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "user_not_found"})
    )
    client = SlackClient(bot_token="xoxb-test")
    result = await client.open_dm("U999")
    assert result is None


@pytest.mark.asyncio
async def test_open_dm_empty_user_id_returns_none():
    """Empty user_id short-circuits without making a network call."""
    client = SlackClient(bot_token="xoxb-test")
    result = await client.open_dm("")
    assert result is None


# ---------------------------------------------------------------------------
# Task A3 — post_ephemeral + blocks on post_to_response_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_post_ephemeral_sends_channel_user_and_returns_true():
    """post_ephemeral sends channel+user in body and returns True on ok."""
    import json as _json

    route = respx.post(f"{SLACK}/chat.postEphemeral").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SlackClient(bot_token="xoxb-test")
    result = await client.post_ephemeral("C111", "U222", "hello ephemeral")
    assert result is True
    body = _json.loads(route.calls.last.request.content)
    assert body["channel"] == "C111"
    assert body["user"] == "U222"
    assert body["text"] == "hello ephemeral"
    assert "blocks" not in body


@pytest.mark.asyncio
@respx.mock
async def test_post_ephemeral_with_blocks():
    """post_ephemeral includes blocks in body when provided."""
    import json as _json

    route = respx.post(f"{SLACK}/chat.postEphemeral").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SlackClient(bot_token="xoxb-test")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "block text"}}]
    result = await client.post_ephemeral("C111", "U222", "fallback", blocks=blocks)
    assert result is True
    body = _json.loads(route.calls.last.request.content)
    assert body["blocks"] == blocks


@pytest.mark.asyncio
@respx.mock
async def test_post_ephemeral_not_ok_returns_false():
    """post_ephemeral returns False on API error."""
    respx.post(f"{SLACK}/chat.postEphemeral").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
    )
    client = SlackClient(bot_token="xoxb-test")
    result = await client.post_ephemeral("C000", "U000", "oops")
    assert result is False


@pytest.mark.asyncio
@respx.mock
async def test_post_to_response_url_with_blocks():
    """post_to_response_url includes blocks in body when given."""
    import json as _json

    route = respx.post("https://hooks.slack.com/callback/test").mock(
        return_value=httpx.Response(200, text="ok")
    )
    client = SlackClient(bot_token="xoxb-test")
    blocks = [{"type": "divider"}]
    result = await client.post_to_response_url(
        "https://hooks.slack.com/callback/test",
        "fallback",
        blocks=blocks,
    )
    assert result is True
    body = _json.loads(route.calls.last.request.content)
    assert body["blocks"] == blocks
    assert body["text"] == "fallback"


@pytest.mark.asyncio
@respx.mock
async def test_post_to_response_url_without_blocks_unchanged():
    """Existing callers without blocks still work; blocks absent from body."""
    import json as _json

    route = respx.post("https://hooks.slack.com/callback/test2").mock(
        return_value=httpx.Response(200, text="ok")
    )
    client = SlackClient(bot_token="xoxb-test")
    result = await client.post_to_response_url(
        "https://hooks.slack.com/callback/test2",
        "plain",
        response_type="in_channel",
        replace_original=True,
    )
    assert result is True
    body = _json.loads(route.calls.last.request.content)
    assert body["response_type"] == "in_channel"
    assert body["replace_original"] is True
    assert "blocks" not in body
