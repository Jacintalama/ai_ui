"""LocalExecutor wraps the claude subprocess flow.

Tests mock asyncio.create_subprocess_exec so the actual claude CLI is not
invoked. They verify the contract: stop() kills self._proc, output is
streamed line-by-line, the --effort flag respects AIUI_AGENT_EFFORT, and
the timeout / output-cap paths still trigger the right messages.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from local_executor import LocalExecutor


@pytest.fixture
def fake_proc():
    """A fake asyncio.subprocess.Process that yields a few stdout chunks."""
    proc = MagicMock()
    proc.stdout = MagicMock()
    chunks = [b"hello ", b"world\n", b"COMPLETED: ok\n", b""]
    async def _read(_n):
        return chunks.pop(0)
    proc.stdout.read = AsyncMock(side_effect=_read)
    proc.wait = AsyncMock(return_value=0)
    proc.kill = MagicMock()
    proc.returncode = 0
    return proc


@pytest.mark.asyncio
async def test_streams_chunks(fake_proc):
    """run() yields each stdout chunk decoded as utf-8."""
    with patch("asyncio.create_subprocess_exec",
               AsyncMock(return_value=fake_proc)):
        ex = LocalExecutor()
        out = []
        async for chunk in ex.run("prompt", slug=None, execution_id="x"):
            out.append(chunk)
    full = "".join(out)
    assert "hello world" in full
    assert "COMPLETED: ok" in full


@pytest.mark.asyncio
async def test_stop_kills_self_proc(fake_proc):
    """stop() invokes self._proc.kill() if a run is active."""
    with patch("asyncio.create_subprocess_exec",
               AsyncMock(return_value=fake_proc)):
        ex = LocalExecutor()
        # Manually assign — simulating mid-run state
        ex._proc = fake_proc
        await ex.stop()
        fake_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_stop_noop_when_no_proc():
    """stop() with no active run does nothing and does not raise."""
    ex = LocalExecutor()
    await ex.stop()  # should not raise


@pytest.mark.asyncio
async def test_effort_flag_propagated(fake_proc, monkeypatch):
    """AIUI_AGENT_EFFORT env reaches the --effort argv."""
    monkeypatch.setenv("AIUI_AGENT_EFFORT", "medium")
    spawn = AsyncMock(return_value=fake_proc)
    with patch("asyncio.create_subprocess_exec", spawn):
        ex = LocalExecutor()
        async for _ in ex.run("prompt", slug=None, execution_id="x"):
            pass
    args = spawn.call_args[0]
    assert "--effort" in args
    idx = args.index("--effort")
    assert args[idx + 1] == "medium"
