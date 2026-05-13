"""RemoteExecutor — ssh + rsync to a dedicated agent VM.
Full body in Task 8.
"""
from __future__ import annotations
from typing import AsyncIterator


class RemoteExecutor:
    async def run(self, prompt: str, slug: str | None, execution_id: str) -> AsyncIterator[str]:
        raise NotImplementedError("filled in Task 8")
        yield

    async def stop(self) -> None:
        raise NotImplementedError("filled in Task 8")
