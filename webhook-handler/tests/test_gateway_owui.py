"""Open WebUI calls that carry a per-user token.

The single most important assertion in this file is that the Authorization
header is the token we were handed. If it were ever the shared admin key, every
user's answers would be built from the admin's Brain and an admin testing it
would see nothing wrong.
"""
import httpx
import pytest
import respx

from gateway.owui import OWUIError, OWUIUserClient

BASE = "http://open-webui:8080"


def _client(token: str = "user-token") -> OWUIUserClient:
    return OWUIUserClient(BASE, token)


@respx.mock
async def test_completion_carries_the_user_token_and_returns_the_text():
    route = respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hi there"}}]}))

    out = await _client().chat_completion(
        [{"role": "user", "content": "hi"}], "auto_router.auto")

    assert out == "hi there"
    assert route.calls[0].request.headers["Authorization"] == "Bearer user-token"


@respx.mock
async def test_completion_passes_chat_id_when_given():
    import json
    route = respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}]}))

    await _client().chat_completion([{"role": "user", "content": "hi"}],
                                    "auto_router.auto", chat_id="chat-1")

    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "chat-1"
    assert body["stream"] is False


@respx.mock
async def test_an_empty_choices_list_raises_rather_than_returning_blank():
    respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": []}))
    with pytest.raises(OWUIError):
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")


@respx.mock
async def test_a_5xx_raises_with_its_status():
    respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 503


@respx.mock
async def test_a_timeout_raises_with_status_zero():
    respx.post(f"{BASE}/api/chat/completions").mock(
        side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 0


@respx.mock
async def test_create_chat_returns_the_new_id():
    import json
    route = respx.post(f"{BASE}/api/v1/chats/new").mock(
        return_value=httpx.Response(200, json={"id": "chat-9", "title": "Hello"}))

    chat_id = await _client().create_chat("Hello", "auto_router.auto")

    assert chat_id == "chat-9"
    body = json.loads(route.calls[0].request.content)
    # ChatForm is {chat: dict}; anything else is a 422.
    assert set(body) == {"chat"}
    assert body["chat"]["title"] == "Hello"
    assert body["chat"]["models"] == ["auto_router.auto"]


@respx.mock
async def test_get_chat_unwraps_the_inner_chat_object():
    respx.get(f"{BASE}/api/v1/chats/chat-9").mock(
        return_value=httpx.Response(200, json={
            "id": "chat-9", "title": "Hello",
            "chat": {"title": "Hello", "messages": [{"role": "user",
                                                     "content": "hi"}]}}))
    chat = await _client().get_chat("chat-9")
    assert chat["messages"][0]["content"] == "hi"


@respx.mock
async def test_update_chat_wraps_the_object_again():
    import json
    route = respx.post(f"{BASE}/api/v1/chats/chat-9").mock(
        return_value=httpx.Response(200, json={"id": "chat-9"}))

    await _client().update_chat("chat-9", {"title": "Hello", "messages": []})

    assert json.loads(route.calls[0].request.content) == {
        "chat": {"title": "Hello", "messages": []}}


@respx.mock
async def test_transcribe_uploads_the_file_and_returns_the_text(tmp_path):
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"not really opus")
    route = respx.post(f"{BASE}/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hello from a voice memo"}))

    out = await _client().transcribe(str(clip))

    assert out == "hello from a voice memo"
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer user-token"
    assert b"memo.ogg" in sent.content
    # audio/ogg matches Open WebUI's default audio/* allowlist; .ogg (not .oga)
    # is what its extension check accepts.
    assert b"audio/ogg" in sent.content


@respx.mock
async def test_transcribe_raises_when_the_response_has_no_text(tmp_path):
    clip = tmp_path / "memo.ogg"
    clip.write_bytes(b"x")
    respx.post(f"{BASE}/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={}))
    with pytest.raises(OWUIError):
        await _client().transcribe(str(clip))


@respx.mock
async def test_a_transport_error_other_than_connect_raises_with_status_zero():
    # A reset mid-request. Previously escaped untyped, leaving the caller unable
    # to tell a network failure from a model failure.
    respx.post(f"{BASE}/api/chat/completions").mock(
        side_effect=httpx.ReadError("connection reset"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 0


@respx.mock
async def test_a_non_json_200_raises_a_typed_error():
    # What a proxy returning an HTML error page with the wrong status looks like.
    respx.post(f"{BASE}/api/chat/completions").mock(
        return_value=httpx.Response(200, text="<html>gateway timeout</html>"))
    with pytest.raises(OWUIError) as exc:
        await _client().chat_completion([{"role": "user", "content": "hi"}], "m")
    assert exc.value.status == 502


@respx.mock
async def test_get_chat_raises_when_the_chat_object_is_missing():
    # Must not return {}: a caller could round-trip that into update_chat and
    # overwrite the user's real chat history with nothing.
    respx.get(f"{BASE}/api/v1/chats/chat-9").mock(
        return_value=httpx.Response(200, json={"id": "chat-9"}))
    with pytest.raises(OWUIError):
        await _client().get_chat("chat-9")


def test_the_client_timeout_fits_inside_the_token_life():
    # These live in two different services and are coupled. One token covers a
    # whole turn, so a single call allowed to outlive it means the call succeeds
    # and the write after it gets a 401, which is silent: the user gets their
    # answer and loses that turn from their sidebar.
    import inspect

    signature = inspect.signature(OWUIUserClient.__init__)
    timeout = signature.parameters["timeout"].default
    assert timeout < 300, (
        "must stay below GATEWAY_TOKEN_TTL_SECONDS in "
        "mcp-servers/tasks/routes_gateway.py")
