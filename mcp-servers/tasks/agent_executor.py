"""Swappable agent backends. The orchestrator picks an executor at task
dispatch time based on AGENT_BACKEND env.

Today's options:
  - local  (default): run `claude` as a subprocess inside this container.
  - remote: ssh to a dedicated agent VM and run `claude` there.

The interface is intentionally small so future backends (E2B, OpenHands,
OpenCode) can plug in without touching routes_execution.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class BaseExecutor(Protocol):
    """Contract every agent backend must honor.

    `run` is an async generator that yields stdout lines from a claude
    process (local or remote). It MUST emit exactly one terminal sentinel
    line before the stream closes:

        COMPLETED:   FAILED:   NEEDS_INPUT:   NEEDS_STEPS:

    Wall-clock timeout is enforced by the implementation
    (EXECUTION_TIMEOUT_SECONDS, currently 600s). On timeout the
    implementation MUST yield "FAILED: timeout" and stop the underlying
    process before closing the stream.

    `stop` cancels the in-flight run owned by this executor instance.
    No-op if no run is active.
    """
    async def run(
        self,
        prompt: str,
        slug: str | None,
        execution_id: str,
    ) -> AsyncIterator[str]: ...

    async def stop(self) -> None: ...


def get_executor() -> BaseExecutor:
    """Construct the executor named by AGENT_BACKEND.

    Imports are intentionally lazy — RemoteExecutor pulls in asyncio.ssh
    helpers that we don't want loaded for purely local installs.
    """
    backend = (os.environ.get("AGENT_BACKEND") or "local").strip().lower()
    if backend == "local":
        from local_executor import LocalExecutor  # noqa: WPS433
        return LocalExecutor()
    if backend == "remote":
        from remote_executor import RemoteExecutor  # noqa: WPS433
        return RemoteExecutor()
    raise ValueError(
        f"AGENT_BACKEND={backend!r} is not a known executor "
        f"(expected 'local' or 'remote')"
    )
