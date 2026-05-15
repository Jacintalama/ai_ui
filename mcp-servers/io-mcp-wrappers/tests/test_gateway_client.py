import pytest

from io_mcp_base.client import GatewayClient


def test_missing_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.delenv("IO_USER_JWT", raising=False)
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_empty_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "")
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_missing_gateway_url_raises(monkeypatch):
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    monkeypatch.delenv("IO_GATEWAY_URL", raising=False)
    with pytest.raises(RuntimeError, match="IO_GATEWAY_URL"):
        GatewayClient()


def test_valid_env_constructs(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    client = GatewayClient()
    assert client.base_url == "http://172.22.0.1:8080"


import respx
import httpx


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    return GatewayClient()


@pytest.mark.asyncio
@respx.mock
async def test_get_sends_bearer(client):
    route = respx.get("http://172.22.0.1:8080/gmail/search").mock(
        return_value=httpx.Response(200, json={"results": []}),
    )
    data = await client.get("/gmail/search", params={"q": "hello"})
    assert data == {"results": []}
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer abc.def.ghi"
    assert sent.url.params["q"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_post_sends_bearer_and_body(client):
    route = respx.post("http://172.22.0.1:8080/gmail/send").mock(
        return_value=httpx.Response(200, json={"id": "m1"}),
    )
    data = await client.post("/gmail/send", json={"to": "a@b.com"})
    assert data == {"id": "m1"}
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer abc.def.ghi"


from io_mcp_base.errors import GatewayError


@pytest.mark.asyncio
@respx.mock
async def test_401_returns_auth_error(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(401))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "auth"


@pytest.mark.asyncio
@respx.mock
async def test_404_returns_not_found(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(404))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "not_found"


@pytest.mark.asyncio
@respx.mock
async def test_429_returns_rate_limit_with_retry_after(client):
    respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}),
    )
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "rate_limit"
    assert ei.value.retry_after == 30


@pytest.mark.asyncio
@respx.mock
async def test_5xx_returns_server(client):
    respx.get("http://172.22.0.1:8080/x").mock(return_value=httpx.Response(500))
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "server"


@pytest.mark.asyncio
@respx.mock
async def test_network_error_returns_network(client):
    respx.get("http://172.22.0.1:8080/x").mock(
        side_effect=httpx.ConnectError("conn refused"),
    )
    with pytest.raises(GatewayError) as ei:
        await client.get("/x")
    assert ei.value.kind == "network"


@pytest.mark.asyncio
@respx.mock
async def test_500_retries_once_then_raises(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(500),
    )
    with pytest.raises(GatewayError):
        await client.get("/x")
    assert route.call_count == 2  # one retry


@pytest.mark.asyncio
@respx.mock
async def test_500_then_200_succeeds(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": 1})],
    )
    data = await client.get("/x")
    assert data == {"ok": 1}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_401_does_NOT_retry(client):
    route = respx.get("http://172.22.0.1:8080/x").mock(
        return_value=httpx.Response(401),
    )
    with pytest.raises(GatewayError):
        await client.get("/x")
    assert route.call_count == 1  # NO retry on auth
