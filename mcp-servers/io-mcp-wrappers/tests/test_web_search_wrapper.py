import json
import pytest
from unittest.mock import AsyncMock

from io_mcp_web_search.tools import web_search_tool_spec, make_web_search_handler


@pytest.mark.asyncio
async def test_calls_gateway_search(monkeypatch):
    client = AsyncMock()
    client.post = AsyncMock(return_value={"results": [{"title": "a", "url": "u", "snippet": "s"}]})
    handler = make_web_search_handler(client)
    result = await handler({"query": "hello", "count": 3})
    client.post.assert_called_once_with("/web-search/web_search",
                                         json={"query": "hello", "count": 3})
    body = json.loads(result[0].text)
    assert body["ok"] is True
    assert body["data"]["results"][0]["url"] == "u"


@pytest.mark.asyncio
async def test_auth_error_envelope(monkeypatch):
    from io_mcp_base.errors import GatewayError
    client = AsyncMock()
    client.post = AsyncMock(side_effect=GatewayError(kind="auth",
                                                      detail="gateway rejected token"))
    handler = make_web_search_handler(client)
    # When the handler raises GatewayError, the BASE's call_tool catches it
    # and returns error_response — but here we're calling the handler directly,
    # which doesn't catch. So we expect either:
    #   (a) The handler raises GatewayError (and base catches it), OR
    #   (b) The handler catches and returns error_response itself
    # The plan's expected behavior is (a) — handler raises, base wraps.
    # So this test should expect the exception:
    with pytest.raises(GatewayError) as ei:
        await handler({"query": "x"})
    assert ei.value.kind == "auth"


def test_tool_spec_shape():
    t = web_search_tool_spec()
    assert t.name == "web_search"
    assert "query" in t.inputSchema["properties"]
    assert "query" in t.inputSchema["required"]
