"""GatewayClient — httpx wrapper that authenticates every call to the
API Gateway as the user whose JWT is in IO_USER_JWT.

Reads env at construct time and fails fast if anything is missing.
Logs MUST NEVER contain the JWT; errors MUST NEVER stringify the
Authorization header. See test_gateway_client.py for the contract.
"""
from __future__ import annotations

import asyncio
import os
import httpx
from typing import Any

from .errors import GatewayError


class GatewayClient:
    def __init__(self) -> None:
        jwt = os.environ.get("IO_USER_JWT", "")
        gateway = os.environ.get("IO_GATEWAY_URL", "")
        if not jwt:
            raise RuntimeError("IO_USER_JWT not set (or empty)")
        if not gateway:
            raise RuntimeError("IO_GATEWAY_URL not set")
        self._jwt = jwt
        self.base_url = gateway.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._jwt}"}

    def _handle(self, resp: httpx.Response) -> Any:
        sc = resp.status_code
        if 200 <= sc < 300:
            return resp.json() if resp.content else None
        if sc == 401 or sc == 403:
            raise GatewayError(kind="auth", detail="gateway rejected token",
                              request=resp.request)
        if sc == 404:
            raise GatewayError(kind="not_found", request=resp.request)
        if sc == 429:
            try:
                retry_after = int(resp.headers.get("Retry-After", "0"))
            except ValueError:
                retry_after = 0
            raise GatewayError(kind="rate_limit", retry_after=retry_after,
                              request=resp.request)
        if 500 <= sc < 600:
            raise GatewayError(kind="server", detail=str(sc),
                              request=resp.request)
        raise GatewayError(kind="server", detail=str(sc), request=resp.request)

    async def _do(self, method: str, path: str, *, params=None, json=None,
                  timeout: float = 30.0) -> Any:
        last_err: GatewayError | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    resp = await c.request(method, self.base_url + path,
                                            params=params, json=json,
                                            headers=self._headers())
                    try:
                        return self._handle(resp)
                    except GatewayError as e:
                        if e.kind == "server" and attempt == 1:
                            last_err = e
                            await asyncio.sleep(1.0)
                            continue
                        raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                err = GatewayError(
                    kind="network",
                    detail="timeout" if isinstance(e, httpx.TimeoutException)
                                     else str(e)[:120],
                    cause=e,
                )
                if attempt == 1:
                    last_err = err
                    await asyncio.sleep(1.0)
                    continue
                raise err from e
        assert last_err is not None
        raise last_err

    async def get(self, path: str, *, params=None, timeout: float = 30.0) -> Any:
        return await self._do("GET", path, params=params, timeout=timeout)

    async def post(self, path: str, *, json=None, timeout: float = 30.0) -> Any:
        return await self._do("POST", path, json=json, timeout=timeout)
