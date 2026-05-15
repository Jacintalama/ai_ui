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
