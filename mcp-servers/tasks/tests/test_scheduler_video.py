import pytest

import scheduler


class _Sched:
    def __init__(self, cfg):
        self.id = "sid-1"
        self.user_email = "u@x.com"
        self.name = "Weekly site video"
        self.kind = "video"
        self.video_config = cfg


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(scheduler, "VIDEO_SCHEDULE_POLL_SECONDS", 0)
    monkeypatch.setattr(scheduler, "VIDEO_SCHEDULE_WAIT_SECONDS", 3)


@pytest.mark.asyncio
async def test_video_schedule_success_returns_link_and_extras(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        assert user.email == "u@x.com"
        assert cfg["url"] == "https://site.com"
        return "job-1"
    checks = iter([("rendering", "", ""), ("done", "", "https://dl/x.mp4?cap=t")])
    async def check(job_id):
        return next(checks)
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "completed"
    assert "https://dl/x.mp4?cap=t" in result
    assert extras == {"video_job_id": "job-1", "video_user_email": "u@x.com"}


@pytest.mark.asyncio
async def test_video_schedule_failure_is_clean(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        return "job-1"
    async def check(job_id):
        return ("failed", "Could not capture that page", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "failed"
    assert "Could not capture that page" in result
    assert extras == {}


@pytest.mark.asyncio
async def test_video_schedule_timeout_points_to_studio(monkeypatch):
    async def start(user, cfg, title, prompt, style):
        return "job-1"
    async def check(job_id):
        return ("rendering", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "timeout"
    assert "still rendering" in result


@pytest.mark.asyncio
async def test_video_schedule_poll_loop_does_not_hold_semaphore(monkeypatch):
    """The poll loop must run outside _RUN_SEMAPHORE: a probe inside
    _check_video_job asserts a free slot is available while polling, which
    would fail if _run_video_schedule held the semaphore across the wait."""
    full_width = scheduler._RUN_SEMAPHORE._value
    seen_free_slots = []
    async def start(user, cfg, title, prompt, style):
        return "job-1"
    checks = iter([("rendering", "", ""), ("done", "", "https://dl/x.mp4?cap=t")])
    async def check(job_id):
        seen_free_slots.append(scheduler._RUN_SEMAPHORE._value)
        return next(checks)
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "completed"
    # Every slot must be free while polling; width-1 here would mean the
    # poll loop is still holding the slot it took for the start call.
    assert seen_free_slots and all(v == full_width for v in seen_free_slots)


@pytest.mark.asyncio
async def test_video_schedule_start_httperror_is_clean(monkeypatch):
    from fastapi import HTTPException
    async def start(user, cfg, title, prompt, style):
        raise HTTPException(429, "Daily video limit reached")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    status, result, extras = await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com"}))
    assert status == "failed"
    assert "Daily video limit reached" in result


@pytest.mark.asyncio
async def test_video_schedule_missing_url_fails_fast(monkeypatch):
    called = False
    async def start(user, cfg, title, prompt, style):
        nonlocal called; called = True
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    status, result, extras = await scheduler._run_video_schedule(_Sched({}))
    assert status == "failed" and not called


@pytest.mark.asyncio
async def test_template_key_fills_prompt_and_style(monkeypatch):
    seen = {}
    async def start(user, cfg, title, prompt, style):
        seen["prompt"], seen["style"] = prompt, style
        return "job-1"
    async def check(job_id):
        return ("done", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    await scheduler._run_video_schedule(
        _Sched({"url": "https://site.com", "template": "cinematic"}))
    assert seen["style"] == "cinematic"
    assert "cinematic showcase" in seen["prompt"].lower()


@pytest.mark.asyncio
async def test_no_template_no_prompt_stays_empty_for_walk_default(monkeypatch):
    seen = {}
    async def start(user, cfg, title, prompt, style):
        seen["prompt"] = prompt
        return "job-1"
    async def check(job_id):
        return ("done", "", "")
    monkeypatch.setattr(scheduler, "_start_video_job", start)
    monkeypatch.setattr(scheduler, "_check_video_job", check)
    await scheduler._run_video_schedule(_Sched({"url": "https://site.com"}))
    assert seen["prompt"] == ""
