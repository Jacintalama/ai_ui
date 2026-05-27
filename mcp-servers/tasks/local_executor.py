"""LocalExecutor — runs the claude CLI as a subprocess inside this container.

This is the original execution flow, lifted out of claude_executor.py into
a class so RemoteExecutor can implement the same interface. Behavior is
intentionally identical to the pre-refactor function — same flags, same
env, same timeout, same output cap. The only contract change is that the
spawned subprocess lives on `self._proc` instead of a caller-supplied
`proc_holder` dict.
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from claude_executor import (
    CLAUDE_SANDBOX_DIR,
    CLAUDE_WORKSPACE,
    EXECUTION_TIMEOUT_SECONDS,
    MAX_LOG_BYTES,
    MAX_PROMPT_CHARS,
)


class LocalExecutor:
    """Run claude as a subprocess in the tasks container."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        slug: str | None,         # unused for local; preserved for interface parity
        execution_id: str,        # unused for local; preserved for interface parity
        user_jwt: str | None = None,  # unused for local; forwarded to remote only
        schedule_id: str | None = None,  # unused for local; remote-only memory roundtrip
    ) -> AsyncIterator[str]:
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n[truncated by tasks service]"

        cwd = CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE
        env = {**os.environ, "IS_SANDBOX": "1"}
        effort = os.environ.get("AIUI_AGENT_EFFORT", "low")

        self._proc = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
            "--effort", effort,
            prompt,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert self._proc.stdout is not None
        bytes_yielded = 0
        try:
            async with asyncio.timeout(EXECUTION_TIMEOUT_SECONDS):
                while True:
                    chunk = await self._proc.stdout.read(4096)
                    if not chunk:
                        break
                    if bytes_yielded >= MAX_LOG_BYTES:
                        self._proc.kill()
                        yield "\n[OUTPUT CAP exceeded — process killed]\n"
                        break
                    bytes_yielded += len(chunk)
                    yield chunk.decode("utf-8", errors="replace")
                await self._proc.wait()
        except asyncio.TimeoutError:
            self._proc.kill()
            await self._proc.wait()
            yield f"\nFAILED: timeout after {EXECUTION_TIMEOUT_SECONDS}s\n"
        except asyncio.CancelledError:
            try:
                self._proc.kill()
            except Exception:
                pass
            raise
        finally:
            self._proc = None

    async def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
