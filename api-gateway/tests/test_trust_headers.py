"""forward_request must not let a client forge the gateway's own headers.

The schedule cap exempts admins on `X-User-Admin: true`, and the tasks service
trusts that header outright. That is only safe because the gateway strips the
client's copy and re-sets it from the validated JWT. Nothing asserted it — the
test that claimed to (tasks/tests/test_schedule_limits.py) only checked that
the parameter appeared in the route's source, and passed with the whole guard
deleted. This is the assertion it was standing in for.

HTTP header names are case-insensitive but Python dicts are not, which is why
main.py strips before it adds: a client sending lowercase `x-user-admin` and
the gateway adding `X-User-Admin` would otherwise put BOTH in the dict, and
the backend would read whichever came first.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from starlette.requests import Request  # noqa: E402


def _request(headers: dict, method: str = "POST", body: bytes = b"{}") -> Request:
    scope = {
        "type": "http", "method": method, "path": "/schedules",
        "query_string": b"", "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _capture_outgoing(monkeypatch):
    """Patch httpx so the request is captured instead of sent."""
    import main

    captured: dict = {}

    class _Headers(dict):
        def multi_items(self):
            return list(self.items())

    class _Resp:
        status_code = 200
        content = b"ok"
        headers = _Headers({"content-type": "application/json"})

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    monkeypatch.setattr(main.httpx, "AsyncClient", _Client)
    return main, captured


def _sent(captured: dict, name: str) -> list[str]:
    """Every value the backend would see for `name`, case-insensitively."""
    return [v for k, v in captured["headers"].items() if k.lower() == name]


def test_a_forged_admin_header_never_reaches_the_backend(monkeypatch):
    main, captured = _capture_outgoing(monkeypatch)
    request = _request({
        "x-user-admin": "true",           # the forgery
        "x-user-email": "attacker@evil.com",
        "content-type": "application/json",
    })
    asyncio.run(main.forward_request(
        request, "http://tasks:8210", "/schedules",
        {"X-User-Admin": "false", "X-User-Email": "real@example.com",
         "X-Gateway-Validated": "true"},
    ))
    assert _sent(captured, "x-user-admin") == ["false"], captured["headers"]
    assert _sent(captured, "x-user-email") == ["real@example.com"], captured["headers"]


def test_the_mixed_case_variant_is_stripped_too(monkeypatch):
    """`X-User-Admin` from the client must not survive alongside the gateway's
    own — the strip is by lowercased name, and this is the case that would
    slip through a plain dict overwrite."""
    main, captured = _capture_outgoing(monkeypatch)
    request = _request({"X-User-Admin": "true", "X-Gateway-Validated": "true"})
    asyncio.run(main.forward_request(
        request, "http://tasks:8210", "/schedules",
        {"X-User-Admin": "false", "X-Gateway-Validated": "true"},
    ))
    assert _sent(captured, "x-user-admin") == ["false"], captured["headers"]
    assert _sent(captured, "x-gateway-validated") == ["true"], captured["headers"]


def test_ordinary_headers_are_still_forwarded(monkeypatch):
    """The strip list is narrow: it must not eat the caller's own headers."""
    main, captured = _capture_outgoing(monkeypatch)
    request = _request({"content-type": "application/json",
                        "x-request-id": "abc123"})
    asyncio.run(main.forward_request(
        request, "http://tasks:8210", "/schedules", {"X-User-Admin": "false"},
    ))
    assert _sent(captured, "x-request-id") == ["abc123"], captured["headers"]
