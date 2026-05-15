"""GatewayError MUST NEVER stringify with the Authorization header in it."""
import httpx

from io_mcp_base.errors import GatewayError


def _request_with_jwt(jwt: str) -> httpx.Request:
    return httpx.Request(
        "GET",
        "http://172.22.0.1:8080/gmail/search",
        headers={"Authorization": f"Bearer {jwt}"},
    )


SECRET = "secret-token-do-not-leak-12345"


def test_str_does_not_contain_jwt():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert SECRET not in str(err)


def test_repr_does_not_contain_jwt():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert SECRET not in repr(err)


def test_str_does_not_contain_authorization_header_key():
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert "Authorization" not in str(err)


def test_kind_and_detail_round_trip():
    out = GatewayError(kind="rate_limit", detail="slow down", retry_after=42)
    assert out.kind == "rate_limit"
    assert out.detail == "slow down"
    assert out.retry_after == 42


def test_init_without_request_works():
    err = GatewayError(kind="network", detail="connection reset")
    assert err.kind == "network"
    assert "secret" not in str(err).lower()


def test_chained_exception_repr_no_leak():
    """If GatewayError wraps an httpx exception that stringifies the request,
    our __repr__ must STILL strip the header.
    """
    try:
        raise httpx.HTTPError("boom")
    except httpx.HTTPError as inner:
        err = GatewayError(kind="server", detail="500",
                          request=_request_with_jwt(SECRET), cause=inner)
    assert SECRET not in repr(err)
    assert SECRET not in str(err)


def test_args_does_not_contain_jwt():
    """Exception.args[0] is what Python's default traceback formatter uses.
    Ensure the sanitized message is what ends up in args, not a raw repr of
    the request with Authorization header.
    """
    err = GatewayError(kind="auth", detail="gateway rejected token",
                      request=_request_with_jwt(SECRET))
    assert SECRET not in str(err.args)


def test_request_header_stripped_in_place():
    """After construction, the stored request object itself must no longer
    carry the Authorization header — so that even direct attribute access
    on err.request cannot leak the JWT.
    """
    req = _request_with_jwt(SECRET)
    err = GatewayError(kind="auth", detail="check", request=req)
    assert "Authorization" not in err.request.headers
    assert SECRET not in str(err.request.headers)


def test_cause_with_request_error_no_leak_on_gateway_error():
    """Regression: when cause is an httpx.RequestError that carries its own
    request (with Authorization header), GatewayError's str/repr must NOT
    include the JWT even if the cause's str does.
    """
    inner_req = _request_with_jwt(SECRET)
    # ConnectError is a RequestError — it stores the request on itself.
    inner = httpx.ConnectError("connection refused", request=inner_req)
    err = GatewayError(kind="network", detail="connect failed",
                      request=_request_with_jwt(SECRET), cause=inner)
    # Our str/repr must be clean.
    assert SECRET not in str(err)
    assert SECRET not in repr(err)
    # Document: err.cause still has the original request with header removed
    # only on err.request, not on cause. Callers must not log repr(err.cause).
    # This test confirms the contract boundary is str(err)/repr(err) only.
