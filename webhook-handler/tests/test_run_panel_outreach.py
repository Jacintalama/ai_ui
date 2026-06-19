import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext


def _ctx(notify, platform="discord"):
    # channel_id is a REQUIRED CommandContext field (no default).
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="outreach",
        subcommand="", arguments="", platform=platform, respond=AsyncMock(),
        respond_components=AsyncMock(), notify_channel=notify,
    )


def _router(tasks_client):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = tasks_client
    r._background_tasks = set()
    r._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    return r


@pytest.mark.asyncio
async def test_run_panel_outreach_unlinked_prompts_link():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "", "Hiring", 10)
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_panel_outreach_empty_jobdesc():
    r = _router(MagicMock())
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "", "   ", 10)
    ctx.respond.assert_awaited()  # asks for a description; no task started
    r._tasks_client.start_outreach.assert_not_called()


@pytest.mark.asyncio
async def test_run_panel_outreach_starts_and_acks():
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring", 8)
    tc.start_outreach.assert_awaited_once()
    ctx.respond.assert_awaited()  # the "Searching GitHub…" ack


@pytest.mark.asyncio
async def test_run_panel_outreach_slack_stays_auto():
    # Regression: run_panel_outreach is shared with Slack, which must keep the
    # OLD auto-send behaviour (mode="auto"), not Discord's manual review flow.
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock(), platform="slack")
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring", 8)
    tc.start_outreach.assert_awaited_once()
    _email, payload = tc.start_outreach.await_args.args
    assert payload["mode"] == "auto"


@pytest.mark.asyncio
async def test_run_panel_outreach_discord_is_manual():
    # Discord uses the find→review→send flow (mode="manual").
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock(), platform="discord")
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring", 8)
    tc.start_outreach.assert_awaited_once()
    _email, payload = tc.start_outreach.await_args.args
    assert payload["mode"] == "manual"


@pytest.mark.asyncio
async def test_watch_outreach_posts_summary_on_completed():
    tc = MagicMock()
    tc.get_outreach_status = AsyncMock(return_value={
        "status": "completed", "found": 12, "sent": 8, "saved": 4,
        "sheet_url": "http://sheet", "text": "Emailed 8, saved 4"})
    r = _router(tc)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_outreach(ctx, "u@x.com", "abc", poll_seconds=0, max_polls=2)
    assert posted and "8" in posted[0]


@pytest.mark.asyncio
async def test_watch_outreach_posts_error_on_failed():
    tc = MagicMock()
    tc.get_outreach_status = AsyncMock(return_value={"status": "failed", "text": "no candidates"})
    r = _router(tc)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_outreach(ctx, "u@x.com", "abc", poll_seconds=0, max_polls=2)
    assert posted and ("couldn't" in posted[0].lower() or "failed" in posted[0].lower()
                       or "no candidates" in posted[0].lower())


@pytest.mark.asyncio
async def test_run_panel_reverse_sends_direction_reverse_and_manual():
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "Berlin", "6 yrs Python", 8)
    tc.start_outreach.assert_awaited_once()
    _email, payload = tc.start_outreach.await_args.args
    assert payload["direction"] == "reverse"
    assert payload["mode"] == "manual"
    ctx.respond.assert_awaited()  # the "Searching…" ack


@pytest.mark.asyncio
async def test_run_panel_reverse_is_manual_even_on_slack():
    # Reverse is review-before-send on ALL platforms (NOT auto like Slack hire).
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock(), platform="slack")
    await r.run_panel_reverse(ctx, "Backend", "", "skills", 8)
    _email, payload = tc.start_outreach.await_args.args
    assert payload["mode"] == "manual"
    assert payload["direction"] == "reverse"


@pytest.mark.asyncio
async def test_run_panel_reverse_unlinked_prompts_link():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "", "skills", 8)
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_panel_reverse_empty_background_does_not_start():
    r = _router(MagicMock())
    ctx = _ctx(AsyncMock())
    await r.run_panel_reverse(ctx, "Backend", "", "   ", 8)
    ctx.respond.assert_awaited()  # asks for background; no task started
    r._tasks_client.start_outreach.assert_not_called()
