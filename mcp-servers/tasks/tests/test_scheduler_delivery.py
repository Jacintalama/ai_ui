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
