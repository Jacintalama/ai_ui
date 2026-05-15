"""GatewayError — typed wrapper around HTTP failures, NEVER stringifies the
Authorization header.

The paranoid invariant: if a JWT is in the request headers when GatewayError
is constructed, that JWT must not appear in str() or repr() of the error.
This is what protects against the leak Lukas flagged in the 2026-05-14
standup: agent reads its own logs/error to debug -> log content goes back
out to the internet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx


ErrorKind = Literal["auth", "not_found", "rate_limit", "server", "network", "internal"]


@dataclass
class GatewayError(Exception):
    kind: ErrorKind
    detail: str = ""
    retry_after: int | None = None
    request: httpx.Request | None = None
    cause: BaseException | None = None

    def __post_init__(self) -> None:
        # Strip Authorization from any stored request copy. Even if upstream
        # code passes in a request with the header, we never retain it.
        if self.request is not None and "Authorization" in self.request.headers:
            # httpx.Request.headers is mutable; remove in place on our copy.
            self.request.headers.pop("Authorization", None)
        # Initialize Exception with a sanitized message.
        super().__init__(self._safe_message())

    def _safe_message(self) -> str:
        parts = [f"GatewayError(kind={self.kind!r}"]
        if self.detail:
            parts.append(f"detail={self.detail!r}")
        if self.retry_after is not None:
            parts.append(f"retry_after={self.retry_after}")
        if self.request is not None:
            parts.append(f"method={self.request.method}")
            parts.append(f"url={self.request.url}")
        return ", ".join(parts) + ")"

    def __str__(self) -> str:
        return self._safe_message()

    def __repr__(self) -> str:
        return self._safe_message()
