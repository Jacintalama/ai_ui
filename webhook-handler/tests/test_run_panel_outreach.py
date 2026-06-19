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
async def test_run_panel_outreach_slack_now_manual():
    # Slack hire now also uses review-before-send (mode="manual") — same as Discord.
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock(), platform="slack")
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring", 8)
    tc.start_outreach.assert_awaited_once()
    _email, payload = tc.start_outreach.await_args.args
    assert payload["mode"] == "manual"


@pytest.mark.asyncio
async def test_slack_hire_uses_manual_review(monkeypatch):
    # Slack "Find Engineers" must now post a review (mode="manual"), not auto-send.
    tc = MagicMock()
    captured = {}

    async def fake_start_outreach(email, payload):
        captured["mode"] = payload["mode"]
        return {"task_id": "t-slack-hire"}

    tc.start_outreach = fake_start_outreach
    r = _router(tc)
    monkeypatch.setattr(r, "_resolve_email_for_ctx",
                        AsyncMock(return_value="seeker@example.com"))

    ctx = _ctx(AsyncMock(), platform="slack")
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring a dev", 5)

    assert captured["mode"] == "manual"


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


def _review_ctx(captured: dict, platform="discord"):
    """A review-capable CommandContext whose edit_message captures the rendered
    payload (mirrors discord_commands._out_ctx: edit the component's own message
    in place)."""
    async def edit_message(msg: dict) -> None:
        captured.clear()
        captured.update(msg)
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="outreach",
        subcommand="outreach", arguments="", platform=platform,
        respond=AsyncMock(), edit_message=edit_message)


@pytest.mark.asyncio
async def test_run_outreach_select_reverse_renders_company_copy():
    # REGRESSION (review-demanded): on RE-RENDER the builder must read
    # direction/role/location FROM the tasks-client response and produce
    # company-oriented copy — not the hire defaults baked into the (empty) args.
    tc = MagicMock()
    tc.patch_outreach_candidate = AsyncMock(return_value={
        "status": "review", "direction": "reverse",
        "role": "Senior Python backend", "location": "Berlin",
        "candidates": [{
            "id": "c0", "name": "Acme Corp", "github_url": "acme.com/careers",
            "email": "jobs@acme.com", "subject": "S", "body": "B",
            "selected": True, "status": "draft"}]})
    r = _router(tc)
    captured: dict = {}
    ctx = _review_ctx(captured)
    # NB: discord_commands still passes role=""/location="" — the handler must
    # IGNORE those and read from the response instead.
    await r.run_outreach_select(ctx, "task-1", ["c0"], "", "")
    tc.patch_outreach_candidate.assert_awaited_once()
    title = captured["embeds"][0]["title"]
    assert title == "Found 1 companies for Senior Python backend"
    assert "apply" in captured["embeds"][0]["footer"]["text"].lower()
    sel = captured["components"][0]["components"][0]
    assert "apply" in sel["placeholder"].lower()
    send = captured["components"][2]["components"][0]
    assert send["label"] == "\U0001f4e7 Send applications (1)"


@pytest.mark.asyncio
async def test_run_outreach_select_hire_still_renders_engineer_copy():
    tc = MagicMock()
    tc.patch_outreach_candidate = AsyncMock(return_value={
        "status": "review", "direction": "hire", "role": "Python", "location": "Manila",
        "candidates": [{
            "id": "c0", "name": "Alice", "github_url": "gh/a", "email": "a@x.com",
            "subject": "S", "body": "B", "selected": True, "status": "draft"}]})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_select(_review_ctx(captured), "task-1", ["c0"], "", "")
    assert captured["embeds"][0]["title"] == "\U0001f50d Found 1 · Python · Manila"
    assert "email" in captured["embeds"][0]["footer"]["text"].lower()


@pytest.mark.asyncio
async def test_run_outreach_send_zero_selected_uses_company_pick_one():
    tc = MagicMock()
    tc.send_outreach = AsyncMock(return_value={
        "status": "review", "direction": "reverse", "role": "Backend", "location": "",
        "text": "", "candidates": []})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_send(_review_ctx(captured), "task-1")
    assert "Pick at least one company first." in captured["content"]


@pytest.mark.asyncio
async def test_run_outreach_send_sent_locks_with_backend_text():
    tc = MagicMock()
    tc.send_outreach = AsyncMock(return_value={
        "status": "sent", "direction": "reverse",
        "text": "Emailed 2 companies, saved 3", "sheet_url": "http://sheet"})
    r = _router(tc)
    captured: dict = {}
    await r.run_outreach_send(_review_ctx(captured), "task-1")
    assert "Emailed 2 companies" in captured["content"]
    assert captured["components"] == []   # locked, no components
