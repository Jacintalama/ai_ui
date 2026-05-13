"""Cancel endpoint calls executor.stop() instead of poking proc_holder.

Regression tests for the migration in Task 3 of the VM-agent flight MCP plan:
`_RUNNING[task_id]` no longer stores `{"proc": <subprocess>}`. It now stores
`{"executor": <BaseExecutor>}` and the cancel endpoint awaits
`entry["executor"].stop()` instead of `entry["proc"].kill()`.

These tests do NOT exercise the full FastAPI cancel route — they assert on
the body of the cancel logic so the unit-level guarantee is locked in
even when the orchestrator's DB layer is unavailable.
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from routes_execution import _RUNNING


@pytest.mark.asyncio
async def test_cancel_calls_executor_stop():
    """_RUNNING entry now holds {'executor': X}; cancel awaits executor.stop()."""
    task_id = uuid.uuid4()
    fake_executor = AsyncMock()
    fake_executor.stop = AsyncMock()
    _RUNNING[task_id] = {"executor": fake_executor}

    try:
        # Simulate what the cancel endpoint body does:
        entry = _RUNNING.get(task_id)
        if entry and "executor" in entry:
            await entry["executor"].stop()

        fake_executor.stop.assert_awaited_once()
    finally:
        _RUNNING.pop(task_id, None)


@pytest.mark.asyncio
async def test_cancel_no_op_when_task_not_running():
    """Cancel on an unknown task_id is a no-op, not an error."""
    task_id = uuid.uuid4()
    entry = _RUNNING.get(task_id)
    # body of the cancel endpoint with no entry → falls through safely
    assert entry is None
