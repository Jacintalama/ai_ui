"""My Workspace: the aggregated apps+schedules+videos view, its runner, and the
my_workspace intent that runs it from chat."""
from unittest.mock import AsyncMock, MagicMock

from handlers import commands as cmd
from handlers import intent_router as ir
from handlers.commands import CommandRouter, CommandContext, build_workspace_summary


def _router(tc=None):
    return CommandRouter(openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
                         discord_user_email_map={"100": "a@x.com"}, tasks_client=tc or MagicMock())


def _ctx(text="my stuff", platform="discord"):
    return CommandContext(user_id="100", user_name="t", channel_id="c", raw_text=text,
                          subcommand="my", arguments=text, platform=platform,
                          respond=AsyncMock(), metadata={}, respond_components=AsyncMock())


# --- pure summary ---

def test_summary_lists_counts_and_names():
    s = build_workspace_summary(
        apps=[{"name": "Shop", "public_url": "https://shop"}, {"slug": "port-1"}],
        schedules=[{"name": "Daily briefing"}],
        videos={"videos": [{"title": "Promo", "status": "done"}]})
    assert "Apps (2)" in s and "Shop - https://shop" in s and "port-1" in s
    assert "Schedules (1)" in s and "Daily briefing" in s
    assert "Videos (1)" in s and "Promo [done]" in s


def test_summary_empty_is_friendly():
    s = build_workspace_summary([], [], [])
    assert "Apps (0)" in s and "none yet" in s
    assert "Videos (0)" in s


def test_summary_video_list_shape_and_truncation():
    apps = [{"slug": f"a{i}"} for i in range(7)]
    s = build_workspace_summary(apps, [], [{"title": "v"}])  # videos as a bare list
    assert "Apps (7)" in s and "and 2 more" in s
    assert "Videos (1)" in s


# --- runner ---

async def test_run_workspace_renders_summary():
    tc = MagicMock()
    tc.list_projects = AsyncMock(return_value=[{"name": "Shop"}])
    tc.list_schedules = AsyncMock(return_value=[])
    tc.list_videos = AsyncMock(return_value={"videos": []})
    r = _router(tc)
    r._resolve_email_for_ctx = AsyncMock(return_value="a@x.com")
    ctx = _ctx()
    await r.run_workspace(ctx)
    msg = ctx.respond.await_args.args[0]
    assert "Your workspace" in msg and "Shop" in msg


async def test_run_workspace_not_linked_bails():
    r = _router()
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    await r.run_workspace(_ctx())
    r._respond_not_linked.assert_awaited_once()


async def test_run_workspace_degrades_on_service_error():
    tc = MagicMock()
    tc.list_projects = AsyncMock(side_effect=RuntimeError("down"))
    tc.list_schedules = AsyncMock(return_value=[{"name": "S"}])
    tc.list_videos = AsyncMock(return_value=[])
    r = _router(tc)
    r._resolve_email_for_ctx = AsyncMock(return_value="a@x.com")
    ctx = _ctx()
    await r.run_workspace(ctx)  # must not raise
    msg = ctx.respond.await_args.args[0]
    assert "Apps (0)" in msg and "Schedules (1)" in msg  # apps degraded, schedules shown


# --- intent wiring ---

async def test_plan_chat_step_my_workspace_returns_workspace(monkeypatch):
    monkeypatch.setattr(ir, "classify",
                        AsyncMock(return_value=ir.IntentResult("my_workspace", 0.9, "my stuff")))
    r = _router()
    step = await r.plan_chat_step("100", "show my stuff", threshold=0.6)
    assert step.kind == "workspace"


async def test_render_workspace_calls_run_workspace():
    r = _router()
    r.run_workspace = AsyncMock()
    await r._render_chat_step(_ctx(), cmd.ChatStep("workspace", ""))
    r.run_workspace.assert_awaited_once()
