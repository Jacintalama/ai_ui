"""Heartbeat scheduler: cron-triggered agent runs with per-schedule memory.

Architecture:
- A background coroutine in the tasks service wakes once per minute, queries
  enabled rows from tasks.schedules, and dispatches matching ones through
  the existing remote_executor pipeline.
- Per-schedule MEMORY.md lives on the agent VM at /agent/memory/<id>.md and
  is SCP'd into/out of each run's workdir (handled by remote_executor).
- secret_scrub redacts credentials at three layers: agent-side post-run,
  orchestrator-side rsync-back, and stream-level.

Pure-function entry points (`cron_matches_now`, `should_fire`) are unit-tested.
DB integration (`_tick_once`, `_create_task_from_schedule`, `_finalize_run`,
`schedule_tick_loop`) is covered by live e2e — see plan Task 9.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from croniter import croniter

logger = logging.getLogger("tasks.scheduler")


def cron_matches_now(cron_expr: str, tz: str, now_utc: datetime) -> bool:
    """True if `cron_expr` matches the current minute in `tz`.

    `croniter.match()` returns True iff the expression fires at the given
    timestamp (rounded to the minute). We convert `now_utc` into the
    schedule's local timezone so e.g. "0 20 * * *" + "Asia/Manila" fires
    at 8pm Manila time, not 8pm UTC.
    """
    local_now = now_utc.astimezone(ZoneInfo(tz))
    return croniter.match(cron_expr, local_now)


def should_fire(
    *,
    cron_expr: str,
    tz: str,
    last_run_at: datetime | None,
    now: datetime,
    enabled: bool,
) -> bool:
    """Decide whether this schedule should fire now.

    Rules (short-circuit, top-to-bottom):
      1. disabled → never fire
      2. cron does not match current minute → no
      3. last_run_at within the last 60s → no (dedupe — another tick already
         fired this minute, or a long-running tick is still racing)
      4. otherwise → fire
    """
    if not enabled:
        return False
    if not cron_matches_now(cron_expr, tz, now):
        return False
    if last_run_at is not None:
        if (now - last_run_at).total_seconds() < 60:
            return False
    return True


# ---------------------------------------------------------------------------
# DB integration. Below is *not* unit-tested locally because the tests would
# need a live Postgres connection — covered by the live e2e step (plan Task 9).
# ---------------------------------------------------------------------------
import uuid as _uuid

from sqlalchemy import select, text, update

from db import session
from models import Schedule, TaskItem
from secret_scrub import scrub


# Host-local connector endpoints (published 127.0.0.1 ports) the scheduled agent
# can call with the owner's x-user-email header. (table, base_url, ops-hint)
_CONNECTOR_ACCESS = {
    "Gmail": (
        "gmail_tokens", "http://127.0.0.1:8016",
        "POST /gmail_list_emails {\"unread_only\":true,\"max_results\":20} (list inbox), "
        "/gmail_search_emails {\"query\":\"...\"}, /gmail_read_email {\"message_id\":\"...\"}, "
        "/gmail_send_email {\"to\":\"...\",\"subject\":\"...\",\"body\":\"...\"}, /gmail_list_labels {}",
    ),
    "Google Drive": (
        "gdrive_tokens", "http://127.0.0.1:8017",
        "POST /gdrive_list_files {}, /gdrive_search_files {\"query\":\"...\"}, "
        "/gdrive_read_file {\"file_id\":\"...\"}, /gdrive_get_file_info {\"file_id\":\"...\"}",
    ),
}


async def _connector_access_note(user_email: str) -> str:
    """If the owner has connected Gmail/Drive, return a prompt section telling the
    agent how to reach those connectors (host-local REST, owner-scoped header)."""
    connected: list[tuple[str, str, str]] = []
    async with session() as s:
        for name, (table, base, ops) in _CONNECTOR_ACCESS.items():
            # table is a fixed internal constant, not user input.
            row = (await s.execute(
                text(f"SELECT 1 FROM public.{table} WHERE user_email = :e LIMIT 1"),
                {"e": user_email},
            )).first()
            if row:
                connected.append((name, base, ops))
    if not connected:
        return ""
    lines = [
        "\n\n## Connector access — you ARE connected to these accounts",
        "Use the Bash tool with `curl` to call these LOCAL HTTP endpoints. ALWAYS send "
        f"headers `Content-Type: application/json` and `x-user-email: {user_email}`. "
        "Each returns JSON; if you get `{\"error\": ...}`, report it plainly.",
    ]
    for name, base, ops in connected:
        lines.append(f"- **{name}** (base `{base}`): {ops}")
    lines.append(
        "Example: `curl -s -X POST -H 'Content-Type: application/json' "
        f"-H 'x-user-email: {user_email}' "
        "-d '{\"unread_only\":true,\"max_results\":20}' http://127.0.0.1:8016/gmail_list_emails`"
    )
    return "\n".join(lines)

# Cap concurrent agent runs. Without this, if 10 schedules all fire at
# 20:00 the orchestrator spawns 10 simultaneous SSH+claude sessions and
# the 3.8GB Hetzner VM OOMs. 3 is a conservative bound; tune via env later.
_RUN_SEMAPHORE = asyncio.Semaphore(3)

# Schedule ids with a run dispatched or executing right now, in THIS process.
# The semaphore above caps concurrency but is a QUEUE, not a bound: without
# this, repeated /run-now calls pile up behind it and real cron-scheduled runs
# starve at the back. `run_now` refuses while an id is in here.
#
# Deliberately in memory rather than `Schedule.last_run_status == "running"`,
# which looks like the obvious signal. A run is an asyncio.Task that does not
# survive a restart; the row does. Gating on the row would mean a crash
# mid-run leaves the schedule refusing run-now forever with nothing to clear
# it — and permanently for a spent one-off, which no tick will fire again.
# This set has exactly the lifetime of the thing it describes.
_IN_FLIGHT: set[str] = set()


def is_run_in_flight(schedule_id) -> bool:
    return str(schedule_id) in _IN_FLIGHT


def dispatch_run(sched) -> "asyncio.Task":
    """Mark the schedule in flight and start its run.

    The marking is synchronous, and that is the point: `create_task` does not
    execute a single line of the coroutine until the event loop next yields, so
    a check made inside `_finalize_run` would let a double-click through. Both
    dispatch paths — the cron tick and /run-now — go through here, so "already
    running" means what it says regardless of who started it.
    """
    _IN_FLIGHT.add(str(sched.id))
    return asyncio.create_task(_finalize_run(sched))


VIDEO_SCHEDULE_WAIT_SECONDS = int(os.environ.get("VIDEO_SCHEDULE_WAIT_SECONDS", "900"))
VIDEO_SCHEDULE_POLL_SECONDS = 10


async def _start_video_job(user, cfg: dict, title: str, prompt: str, style: str) -> str:
    """Create + capture + queue a video job through the real route functions,
    reusing every guard (kill switches, SSRF, daily limit, disk). Returns the
    job id. Raises fastapi.HTTPException on any guard failure."""
    from routes_video import (
        CaptureUrlRequest, DraftRequest, capture_from_url, create_draft, queue_job,
    )
    draft = await create_draft(DraftRequest(title=title, prompt=prompt, style=style), user)
    job_id = str(draft["id"])
    await capture_from_url(job_id, CaptureUrlRequest(url=cfg["url"].strip()), user)
    await queue_job(job_id, user)
    return job_id


async def _check_video_job(job_id: str) -> tuple[str, str, str]:
    """One poll: (status, error, share_link). share_link only when done."""
    import uuid as _u
    from video_models import VideoJob
    async with session() as s:
        job = await s.get(VideoJob, _u.UUID(job_id))
    if job is None:
        return "missing", "the job disappeared", ""
    link = ""
    if job.status == "done":
        base = os.environ.get("VIDEO_PUBLIC_BASE", "").rstrip("/")
        if base:
            try:
                from video_capability import mint_video_capability
                tok = mint_video_capability(job.user_email, job.slug, str(job.id))
                link = f"{base}/api/video-jobs/{job.id}/download?cap={tok}"
            except RuntimeError:
                link = ""
    return job.status, (job.error or ""), link


async def _run_video_schedule(sched: Schedule) -> tuple[str, str, dict]:
    """kind='video': render the configured walkthrough directly (no LLM).
    Returns (status, result_message, delivery_extras).

    Only the _start_video_job call below is bounded by _RUN_SEMAPHORE. The
    poll loop that follows can run for up to VIDEO_SCHEDULE_WAIT_SECONDS
    (default 900s), and holding a semaphore slot for that whole span would
    let a few concurrent video schedules starve agent schedules of runners.
    """
    from fastapi import HTTPException
    from auth import CurrentUser
    from video_templates import get_template

    cfg = dict(getattr(sched, "video_config", None) or {})
    url = (cfg.get("url") or "").strip()
    if not url:
        return "failed", "This video schedule has no website URL configured.", {}
    tpl = get_template((cfg.get("template") or "").strip())
    prompt = (cfg.get("prompt") or "").strip()
    if not prompt and tpl:
        prompt = tpl["prompt"]
    style = (tpl or {}).get("style") or "clean_product_demo"
    title = ((cfg.get("title") or sched.name) or "Scheduled video")[:200]
    user = CurrentUser(email=sched.user_email, is_admin=False)
    studio_base = os.environ.get("VIDEO_PUBLIC_BASE", "").rstrip("/")
    studio_url = f"{studio_base}/video-generator" if studio_base else ""
    try:
        async with _RUN_SEMAPHORE:
            job_id = await _start_video_job(user, cfg, title, prompt, style)
    except HTTPException as exc:
        return "failed", f"Could not start the video: {exc.detail}", {}
    except Exception as exc:  # noqa: BLE001
        logger.exception("video schedule %s start failed", sched.id)
        return "failed", f"Could not start the video: {scrub(str(exc))[:300]}", {}

    polls = max(1, VIDEO_SCHEDULE_WAIT_SECONDS // max(1, VIDEO_SCHEDULE_POLL_SECONDS or 1))
    for _ in range(polls):
        await asyncio.sleep(VIDEO_SCHEDULE_POLL_SECONDS)
        try:
            status, error, link = await _check_video_job(job_id)
        except Exception:  # noqa: BLE001
            logger.exception("video schedule %s poll failed", sched.id)
            continue
        if status == "done":
            extras = {"video_job_id": job_id, "video_user_email": sched.user_email}
            if link:
                return "completed", f"\U0001f3ac {title} is ready: {link}", extras
            if studio_url:
                done_msg = (f"\U0001f3ac {title} is ready. "
                            f"Open the web Video Studio to watch it: {studio_url}")
            else:
                done_msg = (f"\U0001f3ac {title} is ready. "
                            "Open the web Video Studio to watch it.")
            return "completed", done_msg, extras
        if status in ("failed", "missing"):
            err = (error or "").strip()
            return "failed", f"Video render failed.{(' ' + err) if err else ''}", {}
    if studio_url:
        timeout_msg = (f"\U0001f3ac {title} is still rendering. "
                       f"Check the web Video Studio shortly: {studio_url}")
    else:
        timeout_msg = (f"\U0001f3ac {title} is still rendering. "
                       "Check the web Video Studio shortly.")
    return "timeout", timeout_msg, {}


async def _create_task_from_schedule(sched: Schedule) -> TaskItem:
    """Build a TaskItem row from a Schedule and persist it.

    Schedules aren't tied to a meeting; we mint a fresh random `meeting_id`
    per run. A shared sentinel would collide with the
    `(meeting_id, md5(description))` unique index on `items` and block every
    repeat run (the description is identical each run).
    The persona is prepended as the system-message-equivalent
    prefix to the prompt body. The agent is reminded to read MEMORY.md
    (which remote_executor SCP's into the workdir before the run).
    """
    desc = (
        f"{sched.persona}\n\n"
        "---\n\n"
        f"Task: {sched.prompt}\n\n"
        "This is a RECURRING scheduled task — produce fresh, complete output "
        "EVERY run. Never skip it just because it ran before.\n"
        "Protocol (IMPORTANT — follow exactly):\n"
        "- There is a file named `MEMORY.md` in your current working directory.\n"
        "- Step 1: Read `./MEMORY.md` (no path prefix) for CONTEXT — what you produced on previous runs — so you can avoid repeating yourself.\n"
        "- Step 2: Use the Write tool to append a new `## <current ISO timestamp UTC>` section to `./MEMORY.md` briefly noting what you are about to produce (no secrets). Do ALL file operations NOW, before your final message.\n"
        "- Step 3: Your FINAL message is delivered to the user verbatim — so make it your COMPLETE answer to the task. Do NOT call any tools in that final message.\n"
        "- Step 4: End that SAME final message with the single word `COMPLETED` on its own last line (your full answer first, then `COMPLETED`). The orchestrator needs that exact sentinel in the same message as your answer.\n"
        "- Constraints: Do NOT use `/home/*/.claude/*` paths. Do NOT use Bash for file IO. Only `./MEMORY.md` via the Write/Edit/Read tools.\n"
        "- OUTPUT STYLE: Your final message is delivered inside a branded card, so write clean prose/markdown and format minimally — a short bold title, then the content, then at most one brief line of context; use minimal emoji and do NOT add your own ASCII boxes, banners, or system glyphs. When the task is to send an EMAIL, compose a polished human business email: a clear Subject, a greeting, a well-organised body, and a courteous sign-off — no robotic symbols inside the email."
    )
    # Append connector access (Gmail/Drive REST) if the owner has connected them,
    # so a task like "read my unread email" can actually reach the mailbox.
    desc = desc + await _connector_access_note(sched.user_email)
    # Use a synthetic slug derived from schedule_id so the remote executor
    # has a per-schedule workdir to drop MEMORY.md into. UUIDs match the
    # _VALID_SLUG regex (lowercase hex + dashes), and prefixing with `sched-`
    # makes them obvious vs. user-built app slugs.
    sched_slug = f"sched-{str(sched.id)[:8]}"
    item = TaskItem(
        id=_uuid.uuid4(),
        meeting_id=_uuid.uuid4(),
        action_type="BUILD",
        assignee_name=sched.user_email.split("@")[0],
        assignee_email=sched.user_email,
        description=desc,
        priority="NICE_TO_HAVE",
        status="pending",
        mode="ai",
        built_app_slug=sched_slug,
    )
    async with session() as s:
        s.add(item)
        await s.commit()
        await s.refresh(item)
    return item


def _deliverable_result(raw_log: str, fallback: str = "") -> str:
    """The text to deliver for a finished scheduled run.

    Scheduled-task agents are told to write their answer FIRST and end with a
    bare ``COMPLETED`` line (see the persona in ``_create_task_from_schedule``).
    ``parse_outcome`` returns the text *after* the sentinel, which is therefore
    empty — and that empty payload is what gets persisted to ``TaskItem.result``.
    So we recover the actual answer (everything *before* the final sentinel)
    from the raw stream-json transcript via ``extract_final_body``. Falls back to
    the stored result, then an empty string, when the transcript yields nothing.
    """
    from claude_executor import extract_final_body
    body = extract_final_body(raw_log).strip() if raw_log else ""
    return body or (fallback or "")


async def _run_scheduled_task(sched: Schedule) -> tuple[str, str, dict]:
    """Dispatch to existing execution flow. Returns a (status, result, extras)
    tuple.

    Bounded by _RUN_SEMAPHORE so a burst of schedules at the same minute
    can't OOM the orchestrator. Routes through routes_execution._run_execution
    (inline import to avoid an import cycle: routes_execution imports models,
    models is imported here at module-top).

    Video schedules dispatch to _run_video_schedule BEFORE the semaphore is
    acquired: that path polls for up to VIDEO_SCHEDULE_WAIT_SECONDS, and
    holding a slot the whole time would let a few concurrent video schedules
    starve agent schedules of runners. _run_video_schedule takes the
    semaphore itself, only around the actual pipeline start.
    """
    if getattr(sched, "kind", "agent") == "video":
        return await _run_video_schedule(sched)
    # A schedule that names an AI Agent runs through the chat path as its
    # owner, with that agent's own tools. Null means the CLI executor below,
    # which is what every schedule did before this existed.
    #
    # Checked AFTER kind: a video schedule renders a walkthrough and has no
    # agent, so the order here decides which wins if a row somehow has both.
    if getattr(sched, "agent_id", None):
        from agent_runner import run_agent
        async with _RUN_SEMAPHORE:
            return await run_agent(sched)
    async with _RUN_SEMAPHORE:
        item = await _create_task_from_schedule(sched)
        # Create a TaskExecution row so _run_execution has something to update.
        from models import TaskExecution
        async with session() as s:
            execution = TaskExecution(task_id=item.id, status="running", log="")
            s.add(execution)
            await s.commit()
            await s.refresh(execution)
        execution_id = execution.id
        from routes_execution import _run_execution
        # Pass the FULL composed description (persona + task + memory protocol)
        # as the prompt, not just sched.prompt — the memory-protocol section
        # needs to reach the agent. item.description was built by
        # _create_task_from_schedule and already includes everything.
        try:
            await _run_execution(
                item.id, execution_id, item.description, user_jwt=None,
                schedule_id=str(sched.id),
            )
        except Exception as exc:
            logger.exception("schedule %s run failed: %s", sched.id, scrub(str(exc)))
            return "failed", "", {}
        # Re-read the task's final status + result (set by _run_execution).
        # Also read the execution's raw transcript: scheduled agents put their
        # answer BEFORE the COMPLETED sentinel, so TaskItem.result (the
        # after-sentinel payload) is empty — recover the answer via the log.
        async with session() as s:
            row = (await s.execute(
                select(TaskItem).where(TaskItem.id == item.id)
            )).scalar_one_or_none()
            ex = (await s.execute(
                select(TaskExecution).where(TaskExecution.id == execution_id)
            )).scalar_one_or_none()
        status = (row.status if row else None) or "unknown"
        raw_log = (ex.log if ex else "") or ""
        result = _deliverable_result(raw_log, (row.result if row else None) or "")
        return status, result, {}


async def _deliver_result(
    channel_id: str, platform: str, schedule_name: str, status: str, result: str,
    schedule_id: str = "", extras: dict | None = None,
) -> None:
    """POST a finished run's result to the webhook-handler, which posts it into
    the user's Discord thread. Best-effort — never raises into the tick loop.
    Requires WEBHOOK_HANDLER_URL + INTERNAL_CALLBACK_SECRET in the env."""
    base = os.environ.get("WEBHOOK_HANDLER_URL", "")
    secret = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not base or not secret or not channel_id:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base.rstrip('/')}/internal/schedule-result",
                headers={"X-Internal-Secret": secret},
                json={
                    "channel_id": channel_id,
                    "platform": platform,
                    "schedule_name": schedule_name,
                    "status": status,
                    "result": scrub(result or "")[:6000],
                    "schedule_id": schedule_id,
                    **(extras or {}),
                },
            )
            if response.status_code >= 400:
                logger.warning(
                    "schedule delivery failed (%s): webhook returned %s %s",
                    channel_id,
                    response.status_code,
                    scrub(getattr(response, "text", ""))[:500],
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule delivery failed (%s): %s", channel_id, scrub(str(exc)))


#: Longest run output kept on the row. Agent output is unbounded; a card and a
#: database row are not.
RESULT_LIMIT = 8000


def result_for_storage(result) -> str | None:
    """What of a run's output is worth keeping on the schedule.

    None for a run that said nothing, so a card can tell "not run yet" from "ran
    and produced an empty answer".

    Scrubbed, because a run's own prompt can hand the agent a credential and
    models repeat what they are given, and this ends up in a row and then on a
    page. Bounded, and it says so when it cuts, because silently showing the
    first 8000 characters of something longer is a lie about what happened.
    """
    text = (result or "").strip()
    if not text:
        return None
    text = scrub(text)
    if len(text) > RESULT_LIMIT:
        return text[:RESULT_LIMIT] + "\n\n[truncated: the full result was longer]"
    return text


async def _finalize_run(sched: Schedule) -> None:
    """Background coroutine: run, record last_run_status, deliver to Discord.

    Dispatched detached via create_task, so guard everything: an unhandled
    raise would vanish into the discarded task and leave the schedule stuck
    on the pre-dispatch last_run_status='running' (audit 2026-06-15).

    Releases the schedule's _IN_FLIGHT slot in a `finally`, not on success: a
    run that blows up must not leave run-now permanently refused, since that is
    the button a user presses precisely when a run has gone wrong."""
    try:
        status, result, extras = await _run_scheduled_task(sched)
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == sched.id).values(
                    last_run_status=status,
                    last_result=result_for_storage(result),
                    last_result_at=datetime.now(timezone.utc),
                )
            )
            await s.commit()
        # Deliver the run's result into the user's Discord thread, if configured.
        delivery_channel = getattr(sched, "delivery_channel_id", None)
        if delivery_channel:
            platform = getattr(sched, "delivery_platform", "discord") or "discord"
            await _deliver_result(delivery_channel, platform, sched.name, status,
                                  result, str(sched.id), extras=extras)
    except Exception as exc:  # noqa: BLE001
        logger.error("schedule run %s failed: %s", sched.id, scrub(str(exc)), exc_info=True)
        try:
            async with session() as s:
                await s.execute(
                    update(Schedule).where(Schedule.id == sched.id).values(
                        last_run_status="failed",
                    )
                )
                await s.commit()
        except Exception:  # noqa: BLE001
            logger.error("could not mark schedule %s failed", sched.id, exc_info=True)
    finally:
        _IN_FLIGHT.discard(str(sched.id))


def fire_values(sched, now) -> dict:
    """Pre-dispatch update values for a firing schedule. A one-time (`run_once`)
    schedule also gets enabled=False so it fires exactly once, then stops."""
    v = {"last_run_at": now, "last_run_status": "running"}
    if getattr(sched, "run_once", False):
        v["enabled"] = False
    return v


async def _tick_once() -> None:
    """One pass of the scheduler. Reads enabled schedules, marks due ones
    as last_run_at=now BEFORE dispatching (so a slow run doesn't get
    re-fired by the next minute's tick), then kicks off background coros."""
    now = datetime.now(timezone.utc)
    async with session() as s:
        rows = (
            await s.execute(select(Schedule).where(Schedule.enabled.is_(True)))
        ).scalars().all()

    fire = [
        r for r in rows
        if should_fire(
            cron_expr=r.cron_expr,
            tz=r.tz,
            last_run_at=r.last_run_at,
            now=now,
            enabled=r.enabled,
        )
    ]
    if not fire:
        return

    logger.info("tick: %d schedule(s) firing", len(fire))
    for sched in fire:
        # Mark last_run_at IMMEDIATELY (pre-run) for dedupe. Even if the
        # run crashes, the next minute's tick won't double-fire the same
        # schedule. last_run_status will be updated by _finalize_run.
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == sched.id).values(
                    **fire_values(sched, now)
                )
            )
            await s.commit()
        dispatch_run(sched)


async def _sweep_prebuild_question_timeouts() -> None:
    """Auto-skip pre-build question rounds nobody answered within the
    timeout, so a forgotten Discord/Slack/web build doesn't sit parked
    forever.

    Scoped to `status == 'awaiting_input' AND questions_json IS NOT NULL`,
    the Task-4 structured pre-build questions flow. The separate Jul-13
    mid-build NEEDS_INPUT flow never sets questions_json (its question lives
    in `result`), so this sweep never touches it.
    """
    from claude_executor import questions_timed_out
    from routes_aiuibuilder import _LIVE_BUILD_STATES, _compose_questions_answer_text
    from routes_execution import resume_with_answer

    now = datetime.now(timezone.utc)
    async with session() as s:
        rows = (
            await s.execute(
                select(TaskItem).where(
                    TaskItem.status == "awaiting_input",
                    TaskItem.questions_json.isnot(None),
                )
            )
        ).scalars().all()

    due = [r for r in rows if questions_timed_out(r.questions_asked_at, now)]
    if not due:
        return

    for item in due:
        async with session() as s:
            # Serialize with build starts/answers so we can't create a
            # second concurrently-running build.
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('aiuibuilder:build'))"))
            fresh = (
                await s.execute(select(TaskItem).where(TaskItem.id == item.id))
            ).scalar_one_or_none()
            if fresh is None or fresh.status != "awaiting_input" or not fresh.questions_json:
                continue  # already answered/changed since the read above
            other = (
                await s.execute(
                    select(TaskItem.id).where(
                        TaskItem.action_type == "BUILD",
                        TaskItem.status.in_(_LIVE_BUILD_STATES),
                        TaskItem.id != fresh.id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if other:
                # A build is live right now, leave it parked, retry next tick.
                continue
            answer_text = _compose_questions_answer_text(fresh.questions_json, None)
            fresh.questions_json = None
            fresh.questions_asked_at = None
            await resume_with_answer(s, fresh, answer_text)
            logger.info("auto-skipped unanswered pre-build questions for task %s", fresh.id)


async def schedule_tick_loop() -> None:
    """Main loop: wake once a minute, tick, sleep. Runs forever."""
    logger.info("schedule_tick_loop started")
    while True:
        try:
            await _tick_once()
        except Exception:
            logger.exception("schedule_tick failed")
        try:
            await _sweep_prebuild_question_timeouts()
        except Exception:
            logger.exception("prebuild question timeout sweep failed")
        await asyncio.sleep(60)
