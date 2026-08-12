"""The gateway's half of the tasks client.

These endpoints hand back a token that acts as a specific user, so the tests
pin the header, the path and the returned shape. A silent shape change here
would surface as "the model answered as the wrong person".
"""
import httpx
import pytest
import respx

from clients.tasks import TasksAPIError, TasksClient

BASE = "http://tasks-test:8210"


def _client() -> TasksClient:
    return TasksClient(BASE, internal_secret="s3cr3t")


@respx.mock
async def test_resolve_sends_the_internal_secret_and_no_user_email():
    route = respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(200, json={
            "linked": True, "email": "a@b.c",
            "owui_user_id": "u1", "owui_token": "tok"}))
    out = await _client().gateway_resolve("telegram", "111", "Ralph")

    assert out["linked"] is True
    assert out["owui_token"] == "tok"
    sent = route.calls[0].request
    assert sent.headers["X-Internal-Secret"] == "s3cr3t"
    assert "X-User-Email" not in sent.headers


@respx.mock
async def test_resolve_passes_the_platform_user_through():
    route = respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(200, json={
            "linked": False, "code": "ABCD2345", "expires_at": "2026-08-10T12:00:00Z"}))
    out = await _client().gateway_resolve("telegram", "111", "Ralph")

    assert out["code"] == "ABCD2345"
    import json
    body = json.loads(route.calls[0].request.content)
    assert body == {"platform": "telegram", "platform_user_id": "111",
                    "platform_user_name": "Ralph"}


@respx.mock
async def test_get_session_returns_the_whole_mapping():
    # Both fields matter to the caller: owui_user_id is what lets
    # get_or_create_chat notice a session pointing at a different user's chat
    # (a re-paired account), not just the chat id.
    respx.get(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(
            200, json={"owui_chat_id": "chat-1", "owui_user_id": "u1"}))
    assert await _client().gateway_get_session("telegram", "42") == {
        "owui_chat_id": "chat-1", "owui_user_id": "u1"}


@respx.mock
async def test_get_session_returns_a_null_chat_id_when_unmapped():
    respx.get(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(200, json={"owui_chat_id": None}))
    result = await _client().gateway_get_session("telegram", "42")
    assert result.get("owui_chat_id") is None


@respx.mock
async def test_put_session_sends_all_four_fields():
    route = respx.put(f"{BASE}/gateway/session").mock(
        return_value=httpx.Response(200, json={"status": "ok"}))
    await _client().gateway_put_session("telegram", "42", "chat-1", "u1")

    import json
    assert json.loads(route.calls[0].request.content) == {
        "platform": "telegram", "chat_id": "42",
        "owui_chat_id": "chat-1", "owui_user_id": "u1"}


@respx.mock
async def test_recent_sessions_returns_the_list():
    respx.get(f"{BASE}/gateway/sessions/recent").mock(
        return_value=httpx.Response(200, json={"sessions": [
            {"platform": "telegram", "chat_id": "42",
             "owui_chat_id": "chat-1", "updated_at": "2026-08-10T10:00:00Z"}]}))
    out = await _client().gateway_recent_sessions("u1")
    assert len(out) == 1 and out[0]["owui_chat_id"] == "chat-1"


@respx.mock
async def test_a_server_error_raises_tasks_api_error():
    respx.post(f"{BASE}/gateway/resolve").mock(
        return_value=httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(TasksAPIError):
        await _client().gateway_resolve("telegram", "111")


@respx.mock
async def test_an_unreachable_service_raises_with_status_zero():
    respx.post(f"{BASE}/gateway/resolve").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TasksAPIError) as exc:
        await _client().gateway_resolve("telegram", "111")
    assert exc.value.status == 0
