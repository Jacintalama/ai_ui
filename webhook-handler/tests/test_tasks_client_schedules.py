import pytest
from clients.tasks import TasksClient


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


@pytest.mark.asyncio
async def test_enable_disable_runnow_hit_expected_paths(monkeypatch):
    calls = []

    async def fake_request(self, method, path, user_email, **kwargs):
        calls.append((method, path, user_email))
        return _FakeResp({"ok": True})

    monkeypatch.setattr(TasksClient, "_request", fake_request, raising=True)
    c = TasksClient(base_url="http://tasks:8210")

    await c.enable_schedule("u@x.com", "s1")
    await c.disable_schedule("u@x.com", "s1")
    await c.run_now_schedule("u@x.com", "s1")

    assert calls == [
        ("POST", "/schedules/s1/enable", "u@x.com"),
        ("POST", "/schedules/s1/disable", "u@x.com"),
        ("POST", "/schedules/s1/run-now", "u@x.com"),
    ]
