"""GatewayClient — httpx wrapper that authenticates every call to the
API Gateway as the user whose JWT is in IO_USER_JWT.

Reads env at construct time and fails fast if anything is missing.
Logs MUST NEVER contain the JWT; errors MUST NEVER stringify the
Authorization header. See test_gateway_client.py for the contract.
"""
from __future__ import annotations

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

    async def get(self, path: str, *, params: dict[str, Any] | None = None,
                  timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(self.base_url + path,
                                     params=params, headers=self._headers())
            return self._handle(resp)

    async def post(self, path: str, *, json: dict[str, Any] | None = None,
                   timeout: float = 30.0) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self.base_url + path,
                                      json=json, headers=self._headers())
            return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> Any:
        if 200 <= resp.status_code < 300:
            return resp.json() if resp.content else None
        raise GatewayError(kind="server", detail=str(resp.status_code),
                          request=resp.request)
