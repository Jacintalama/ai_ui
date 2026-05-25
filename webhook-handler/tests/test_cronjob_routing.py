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


# ── interaction-routing tests (Tasks 8 + 9) ──────────────────────────
import asyncio
from handlers.discord_commands import (
    DiscordCommandHandler, MESSAGE_COMPONENT, MODAL_SUBMIT, MODAL,
    CHANNEL_MESSAGE, UPDATE_MESSAGE, DEFERRED_CHANNEL_MESSAGE, DEFERRED_UPDATE_MESSAGE,
)

# --- shared fakes/helpers for interaction tests (mirror test_discord_commands_appselect.py) ---
class FakeDiscord:
    def __init__(self): self.edits = []
    async def edit_original(self, *, interaction_token, content, components=None):
        self.edits.append((content, components))

class _StubRouter:
    def __init__(self):
        self.created = []; self.listed = False; self.menued = None
        self.ran = None; self.paused = None; self.resumed = None; self.deleted = None
    async def run_cron_create(self, ctx, *, cron_expr, name, prompt):
        self.created.append((cron_expr, name, prompt))
    async def run_cron_list(self, ctx): self.listed = True
    async def run_cron_menu(self, ctx, sid): self.menued = sid
    async def run_cron_runnow(self, ctx, sid): self.ran = sid
    async def run_cron_pause(self, ctx, sid): self.paused = sid
    async def run_cron_resume(self, ctx, sid): self.resumed = sid
    async def run_cron_delete(self, ctx, sid): self.deleted = sid

def _handler(router):
    return DiscordCommandHandler(FakeDiscord(), router)

async def _drain():
    for _ in range(3):
        await asyncio.sleep(0)

def _component_payload(custom_id, values=None):
    data = {"custom_id": custom_id}
    if values is not None:
        data["values"] = values
    return {"type": MESSAGE_COMPONENT, "data": data, "token": "tok", "id": "iid",
            "member": {"user": {"id": "d1", "username": "ralph"}}, "channel_id": "c1"}

def _modal_payload(custom_id, fields):
    rows = [{"components": [{"custom_id": k, "value": v}]} for k, v in fields.items()]
    return {"type": MODAL_SUBMIT, "data": {"custom_id": custom_id, "components": rows},
            "token": "tok", "id": "iid",
            "member": {"user": {"id": "d1", "username": "ralph"}}, "channel_id": "c1"}


@pytest.mark.asyncio
async def test_cron_new_opens_fresh_ephemeral_with_frequency():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:new"))
    assert resp["type"] == CHANNEL_MESSAGE
    ids = [b["custom_id"] for row in resp["data"]["components"] for b in row["components"]]
    assert "cron:freq:daily" in ids

@pytest.mark.asyncio
async def test_cron_freq_daily_updates_to_hour_select():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:freq:daily"))
    assert resp["type"] == UPDATE_MESSAGE
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:hour:daily"

@pytest.mark.asyncio
async def test_cron_freq_weekly_updates_to_dow_select():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:freq:weekly"))
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:dow"

@pytest.mark.asyncio
async def test_cron_dow_select_updates_to_hour_select_with_dow():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:dow", values=["1"]))
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:hour:weekly:1"

@pytest.mark.asyncio
async def test_cron_freq_hourly_opens_modal():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:freq:hourly"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:create:0_*_*_*_*"

@pytest.mark.asyncio
async def test_cron_freq_custom_opens_custom_modal():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:freq:custom"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:customcron"

@pytest.mark.asyncio
async def test_cron_hour_select_opens_create_modal_with_built_cron():
    resp = await _handler(_StubRouter())._handle_message_component(
        _component_payload("cron:hour:weekly:1", values=["18"]))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:create:0_18_*_*_1"

@pytest.mark.asyncio
async def test_cron_create_modal_submit_invokes_run_cron_create():
    router = _StubRouter()
    resp = await _handler(router)._handle_modal_submit(
        _modal_payload("cron:create:0_9_*_*_*", {"name": "m", "prompt": "do x"}))
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    await _drain()
    assert router.created == [("0 9 * * *", "m", "do x")]

@pytest.mark.asyncio
async def test_cron_custom_modal_submit_uses_typed_cron():
    router = _StubRouter()
    await _handler(router)._handle_modal_submit(
        _modal_payload("cron:customcron", {"cron": "*/30 * * * *", "name": "", "prompt": "p"}))
    await _drain()
    assert router.created == [("*/30 * * * *", "", "p")]


@pytest.mark.asyncio
async def test_cron_list_routes_to_run_cron_list():
    router = _StubRouter()
    resp = await _handler(router)._handle_message_component(_component_payload("cron:list"))
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    assert router.listed is True

@pytest.mark.asyncio
async def test_cron_select_routes_to_menu():
    router = _StubRouter()
    await _handler(router)._handle_message_component(_component_payload("cron:select", values=["s1"]))
    await _drain()
    assert router.menued == "s1"

@pytest.mark.asyncio
async def test_cron_runnow_pause_resume_delconfirm_route():
    for verb, attr in [("runnow", "ran"), ("pause", "paused"),
                       ("resume", "resumed"), ("delconfirm", "deleted")]:
        router = _StubRouter()
        await _handler(router)._handle_message_component(_component_payload(f"cron:{verb}:s1"))
        await _drain()
        assert getattr(router, attr) == "s1"

@pytest.mark.asyncio
async def test_cron_delete_shows_confirm_inline():
    resp = await _handler(_StubRouter())._handle_message_component(_component_payload("cron:delete:s1"))
    assert resp["type"] == UPDATE_MESSAGE
    ids = [b["custom_id"] for row in resp["data"]["components"] for b in row["components"]]
    assert ids == ["cron:delconfirm:s1", "cron:delcancel"]
