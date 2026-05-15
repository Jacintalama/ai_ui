"""GatewayClient — httpx wrapper that authenticates every call to the
API Gateway as the user whose JWT is in IO_USER_JWT.

Reads env at construct time and fails fast if anything is missing.
Logs MUST NEVER contain the JWT; errors MUST NEVER stringify the
Authorization header. See test_gateway_client.py for the contract.
"""
from __future__ import annotations

import os


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
