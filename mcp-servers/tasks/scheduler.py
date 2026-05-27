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
        "- OUTPUT STYLE: Produce clear, concise, professional, well-structured output (short paragraphs; bullet points where useful). Your final message is delivered inside a branded card, so write clean prose/markdown — do NOT add your own ASCII boxes, banners, or system glyphs. When the task is to send an EMAIL, compose a polished human business email: a clear Subject, a greeting, a well-organised body, and a courteous sign-off — no robotic symbols inside the email."
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


async def _run_scheduled_task(sched: Schedule) -> str:
    """Dispatch to existing execution flow. Returns final status string.

    Bounded by _RUN_SEMAPHORE so a burst of schedules at the same minute
    can't OOM the orchestrator. Routes through routes_execution._run_execution
    (inline import to avoid an import cycle: routes_execution imports models,
    models is imported here at module-top).
    """
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
            return "failed", ""
        # Re-read the task's final status + result (set by _run_execution)
        async with session() as s:
            row = (await s.execute(
                select(TaskItem).where(TaskItem.id == item.id)
            )).scalar_one_or_none()
        status = (row.status if row else None) or "unknown"
        result = (row.result if row else None) or ""
        return status, result


async def _deliver_to_discord(
    channel_id: str, schedule_name: str, status: str, result: str,
    schedule_id: str = "",
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
            await client.post(
                f"{base.rstrip('/')}/internal/schedule-result",
                headers={"X-Internal-Secret": secret},
                json={
                    "channel_id": channel_id,
                    "schedule_name": schedule_name,
                    "status": status,
                    "result": scrub(result or "")[:6000],
                    "schedule_id": schedule_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("schedule delivery failed (%s): %s", channel_id, scrub(str(exc)))


async def _finalize_run(sched: Schedule) -> None:
    """Background coroutine: run, record last_run_status, deliver to Discord."""
    status, result = await _run_scheduled_task(sched)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == sched.id).values(
                last_run_status=status,
            )
        )
        await s.commit()
    # Deliver the run's result into the user's Discord thread, if configured.
    delivery_channel = getattr(sched, "delivery_channel_id", None)
    if delivery_channel:
        await _deliver_to_discord(delivery_channel, sched.name, status, result, str(sched.id))


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
                    last_run_at=now,
                    last_run_status="running",
                )
            )
            await s.commit()
        asyncio.create_task(_finalize_run(sched))


async def schedule_tick_loop() -> None:
    """Main loop: wake once a minute, tick, sleep. Runs forever."""
    logger.info("schedule_tick_loop started")
    while True:
        try:
            await _tick_once()
        except Exception:
            logger.exception("schedule_tick failed")
        await asyncio.sleep(60)
