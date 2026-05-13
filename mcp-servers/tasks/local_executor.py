"""LocalExecutor — runs claude as a subprocess inside this container.
Full body in Task 2.
"""
from __future__ import annotations
from typing import AsyncIterator


class LocalExecutor:
    async def run(self, prompt: str, slug: str | None, execution_id: str) -> AsyncIterator[str]:
        raise NotImplementedError("filled in Task 2")
        yield  # makes this a generator function for type purposes

    async def stop(self) -> None:
        raise NotImplementedError("filled in Task 2")
