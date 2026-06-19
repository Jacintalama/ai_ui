import pytest
from unittest.mock import AsyncMock, MagicMock
from clients.tasks import TasksClient


def _client(resp_json):
    tc = TasksClient.__new__(TasksClient)  # bypass __init__ network setup
    resp = MagicMock()
    resp.json.return_value = resp_json
    tc._request = AsyncMock(return_value=resp)
    return tc


@pytest.mark.asyncio
async def test_start_outreach_posts_payload():
    tc = _client({"task_id": "abc"})
    out = await tc.start_outreach("u@x.com",
        {"role": "Python", "location": "Berlin", "jobdesc": "Hiring", "count": 8})
    assert out == {"task_id": "abc"}
    method, path, email = tc._request.call_args.args[:3]
    assert method == "POST" and path == "/outreach" and email == "u@x.com"
    assert tc._request.call_args.kwargs["json"]["role"] == "Python"


@pytest.mark.asyncio
async def test_get_outreach_status_gets():
    tc = _client({"status": "completed", "found": 12, "sent": 8, "saved": 4,
                  "sheet_url": "http://s", "text": "done"})
    out = await tc.get_outreach_status("u@x.com", "abc")
    assert out["sent"] == 8
    method, path, email = tc._request.call_args.args[:3]
    assert method == "GET" and path == "/outreach/abc" and email == "u@x.com"


@pytest.mark.asyncio
async def test_start_outreach_defaults_direction_hire():
    tc = _client({"task_id": "abc"})
    await tc.start_outreach("u@x.com", {"role": "Python", "count": 8})
    assert tc._request.call_args.kwargs["json"]["direction"] == "hire"


@pytest.mark.asyncio
async def test_start_outreach_passes_reverse_direction():
    tc = _client({"task_id": "abc"})
    await tc.start_outreach("u@x.com", {
        "role": "Python", "count": 8, "mode": "manual", "direction": "reverse"})
    assert tc._request.call_args.kwargs["json"]["direction"] == "reverse"
