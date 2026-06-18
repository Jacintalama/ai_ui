import os
import sys

import pytest

# Make the tasks/ dir importable when running this test directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_deliver_result_logs_webhook_non_2xx(monkeypatch, caplog):
    import scheduler

    class _Response:
        status_code = 502
        text = "Slack delivery failed"

    class _Client:
        requests = []

        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            self.requests.append((url, headers, json))
            return _Response()

    monkeypatch.setenv("WEBHOOK_HANDLER_URL", "http://webhook-handler:8086")
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", "secret")
    monkeypatch.setattr(scheduler.httpx, "AsyncClient", _Client)

    with caplog.at_level("WARNING", logger="tasks.scheduler"):
        await scheduler._deliver_result(
            "D1", "slack", "daily digest", "completed", "ok", "sid1"
        )

    assert _Client.requests
    assert any(
        "schedule delivery failed" in record.message
        and "D1" in record.message
        and "502" in record.message
        for record in caplog.records
    )


def test_deliverable_result_recovers_answer_before_sentinel():
    """Scheduled agents write the answer BEFORE the bare COMPLETED sentinel, so
    parse_outcome's after-sentinel payload (stored as TaskItem.result) is empty.
    _deliverable_result must recover the answer body from the raw transcript."""
    import scheduler

    transcript = (
        '{"type":"result","is_error":false,'
        '"result":"**Daily Quote**\\n\\n> Stay hungry.\\n\\nCOMPLETED"}\n'
    )
    out = scheduler._deliverable_result(transcript, "")
    assert "Daily Quote" in out
    assert "Stay hungry" in out
    assert "COMPLETED" not in out  # the sentinel is stripped
    assert out.strip() != ""


def test_deliverable_result_falls_back_to_stored_when_no_transcript():
    import scheduler

    assert scheduler._deliverable_result("", "stored payload") == "stored payload"
    assert scheduler._deliverable_result("", "") == ""


class _CapturingSession:
    """Async-CM fake that records the bound params of each execute()."""

    def __init__(self, captured):
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        try:
            self.captured.append(stmt.compile().params)
        except Exception:
            self.captured.append({})
        return None

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_finalize_run_marks_failed_instead_of_dying_silently(monkeypatch, caplog):
    """_finalize_run runs detached via create_task. A raise in the run/update
    used to vanish into the discarded task, leaving the schedule stuck
    'running'. It must catch, log, and write last_run_status='failed'.
    (audit 2026-06-15.)"""
    import logging
    from types import SimpleNamespace
    import scheduler

    captured = []
    monkeypatch.setattr(scheduler, "session", lambda: _CapturingSession(captured))

    async def boom(_sched):
        raise RuntimeError("agent unreachable")

    monkeypatch.setattr(scheduler, "_run_scheduled_task", boom)
    sched = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", name="daily digest",
        delivery_channel_id=None, delivery_platform=None,
    )

    with caplog.at_level(logging.ERROR):
        await scheduler._finalize_run(sched)  # must NOT raise

    assert any(p.get("last_run_status") == "failed" for p in captured), (
        "a failed run must be recorded as last_run_status='failed'")
    assert any("fail" in r.message.lower() for r in caplog.records), (
        "the failure must be logged, not swallowed")
