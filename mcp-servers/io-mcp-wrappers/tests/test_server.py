import json
import pytest
from mcp.types import Tool, TextContent

from io_mcp_base.server import build_server, ok_response, error_response
from io_mcp_base.errors import GatewayError


def test_ok_response_envelope():
    tc = ok_response({"id": "x"})
    assert isinstance(tc, list) and len(tc) == 1 and isinstance(tc[0], TextContent)
    body = json.loads(tc[0].text)
    assert body == {"ok": True, "data": {"id": "x"}}


def test_error_response_from_gateway_error():
    err = GatewayError(kind="auth", detail="gateway rejected token")
    tc = error_response(err)
    body = json.loads(tc[0].text)
    assert body == {"error": "auth", "detail": "gateway rejected token"}


def test_error_response_with_retry_after():
    err = GatewayError(kind="rate_limit", retry_after=30)
    body = json.loads(error_response(err)[0].text)
    assert body == {"error": "rate_limit", "retry_after": 30}


def test_error_response_swallows_internal_exception():
    err = ValueError("something broke with details")
    body = json.loads(error_response(err)[0].text)
    assert body == {"error": "internal"}
    assert "details" not in json.dumps(body)


def test_build_server_has_correct_name():
    """Smoke check: server is constructed with the name we pass."""
    tool = Tool(name="echo", description="t", inputSchema={"type": "object"})
    async def handler(args):
        return ok_response({"echoed": args})
    srv = build_server("io-echo", [(tool, handler)])
    assert srv.name == "io-echo"
