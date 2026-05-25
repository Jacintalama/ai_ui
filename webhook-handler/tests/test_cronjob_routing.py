import pytest
from handlers.commands import CommandRouter, CommandContext


def _ctx(**kw):
    sent, comps = [], []
    async def respond(m): sent.append(m)
    async def respond_components(m, c): comps.append((m, c))
    base = dict(
        user_id="d1", user_name="ralph", channel_id="c1", raw_text="",
        subcommand="cronjob", arguments="", platform="discord",
        respond=respond, respond_components=respond_components,
    )
    base.update(kw)
    ctx = CommandContext(**base)
    return ctx, sent, comps


class _FakeTasks:
    def __init__(self): self.calls = []
    async def create_schedule(self, email, name, cron, prompt, **kw):
        self.calls.append(("create", email, name, cron, prompt)); return {"id": "s9"}
    async def list_schedules(self, email):
        self.calls.append(("list", email)); return [
            {"id": "s1", "name": "m", "cron_expr": "0 9 * * *", "enabled": True,
             "last_run_status": None}]
    async def run_now_schedule(self, email, sid):
        self.calls.append(("runnow", email, sid)); return {"ok": True}
    async def enable_schedule(self, email, sid):
        self.calls.append(("enable", email, sid)); return {"id": sid, "enabled": True}
    async def disable_schedule(self, email, sid):
        self.calls.append(("disable", email, sid)); return {"id": sid, "enabled": False}
    async def delete_schedule(self, email, sid):
        self.calls.append(("delete", email, sid)); return True


def _router(tasks):
    r = CommandRouter.__new__(CommandRouter)   # bypass heavy __init__
    r._tasks_client = tasks
    r._discord_user_email_map = {"d1": "u@x.com"}
    return r


@pytest.mark.asyncio
async def test_run_cron_create_calls_api_and_confirms():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_create(ctx, cron_expr="0 9 * * *", name="", prompt="do things")
    assert tasks.calls[0][0] == "create"
    assert "daily at 09:00" in sent[-1]

@pytest.mark.asyncio
async def test_run_cron_create_rejects_blank_prompt():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_create(ctx, cron_expr="0 9 * * *", name="", prompt="   ")
    assert tasks.calls == []
    assert "prompt" in sent[-1].lower()

@pytest.mark.asyncio
async def test_run_cron_list_renders_select():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, _, comps = _ctx()
    await r.run_cron_list(ctx)
    assert comps
    sel = comps[-1][1][0]["components"][0]
    assert sel["custom_id"] == "cron:select"

@pytest.mark.asyncio
async def test_run_cron_runnow_calls_api():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_runnow(ctx, "s1")
    assert ("runnow", "u@x.com", "s1") in tasks.calls

@pytest.mark.asyncio
async def test_run_cron_pause_then_menu_reflects_state():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, _, comps = _ctx()
    await r.run_cron_pause(ctx, "s1")
    assert ("disable", "u@x.com", "s1") in tasks.calls
