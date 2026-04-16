"""Scheduled jobs — weekly recap POST to n8n."""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from db import session
from models import TaskItem

logger = logging.getLogger("tasks")
router = APIRouter(prefix="/cron")

WEEKLY_RECAP_URL = os.environ.get(
    "WEEKLY_RECAP_WEBHOOK",
    "https://n8n.srv1041674.hstgr.cloud/webhook/cronjob-weekly-recap",
)
CRON_SECRET = os.environ.get("CRON_SHARED_SECRET", "")

PH_TZ = timezone(timedelta(hours=8))

TYPE_ICON = {"BUILD": "🔨", "INTEGRATE": "🔗", "RESEARCH": "🔍", "ASK_USER": "❓"}
PRI_LABEL = {"CRITICAL": "CRITICAL", "IMPORTANT": "IMPORTANT", "NICE_TO_HAVE": "NICE"}


def _first_name(name: str, email: str) -> str:
    """Pick a short display name: first word of assignee_name, else email prefix."""
    if name and name.strip():
        return name.strip().split()[0]
    return (email or "unknown").split("@")[0]


def _week_window_utc(now_utc: datetime) -> tuple[datetime, datetime, str, str]:
    """Return (start_utc, end_utc, start_date_str, end_date_str) for Mon-Fri PH."""
    now_ph = now_utc.astimezone(PH_TZ)
    monday_ph = (now_ph - timedelta(days=now_ph.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    friday_end_ph = (monday_ph + timedelta(days=4)).replace(hour=23, minute=59, second=59)
    return (
        monday_ph.astimezone(timezone.utc),
        friday_end_ph.astimezone(timezone.utc),
        monday_ph.date().isoformat(),
        friday_end_ph.date().isoformat(),
    )


def _format_body(meetings: list[dict[str, Any]], tasks: list[dict[str, Any]],
                 start: str, end: str) -> str:
    """Pre-format the whole recap as a markdown string — one block, n8n-friendly."""
    lines: list[str] = []
    lines.append(f"# 📅 Weekly Recap — {start} to {end}")
    lines.append("")

    # Meetings section
    lines.append(f"## 🗓️ Meetings this week ({len(meetings)})")
    lines.append("")
    if not meetings:
        lines.append("_No meetings recorded this week._")
        lines.append("")
    for m in meetings:
        lines.append(f"### {m['title']}")
        if m.get("attendees"):
            lines.append(f"**Attendees:** {m['attendees']}")
        summary = (m.get("summary") or "").strip()
        if summary:
            # Strip leading "Title: ..." and the first heading so it reads cleanly
            for ln in summary.splitlines():
                s = ln.strip()
                if s.startswith("Title:") or s == m["title"]:
                    continue
                lines.append(ln)
                if len("\n".join(lines)) > 1800:
                    lines.append("_…(truncated)_")
                    break
        if m.get("fathom_link"):
            lines.append(f"🎬 {m['fathom_link']}")
        lines.append("")

    # Task stats
    by_status: dict[str, int] = {}
    by_assignee: dict[str, dict[str, int]] = {}
    completed_tasks = []
    pending_tasks = []
    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        em = t["assignee_email"]
        by_assignee.setdefault(em, {"name": t["assignee_name"], "completed": 0, "pending": 0})
        if t["status"] == "completed":
            by_assignee[em]["completed"] += 1
            completed_tasks.append(t)
        elif t["status"] in ("pending", "awaiting_input", "claimed_manual"):
            by_assignee[em]["pending"] += 1
            pending_tasks.append(t)

    lines.append("---")
    lines.append("")
    lines.append(f"## 📊 Tasks ({len(tasks)} created this week)")
    lines.append("")
    lines.append(f"✅ Completed: {by_status.get('completed', 0)}")
    lines.append(f"⏳ Pending: {sum(by_status.get(s, 0) for s in ('pending', 'awaiting_input', 'claimed_manual'))}")
    lines.append(f"✗ Failed: {by_status.get('failed', 0)}")
    lines.append("")
    if by_assignee:
        lines.append("**By admin:**")
        for em, stats in by_assignee.items():
            lines.append(f"- {_first_name(stats['name'], em)} — ✅ {stats['completed']} done, ⏳ {stats['pending']} pending")
        lines.append("")

    # Completed detail
    if completed_tasks:
        lines.append("---")
        lines.append("")
        lines.append("## ✅ Completed tasks")
        lines.append("")
        for t in completed_tasks:
            nm = _first_name(t["assignee_name"], t["assignee_email"])
            mode = "⚡ AI" if t.get("mode") == "ai" else "✋ Manual"
            lines.append(f"**{nm}** — {t['description']} ({mode})")
            if t.get("result"):
                lines.append(f"> {t['result'][:500]}")
            lines.append("")

    # Pending detail
    if pending_tasks:
        lines.append("---")
        lines.append("")
        lines.append("## ⏳ Still pending")
        lines.append("")
        for t in pending_tasks:
            icon = TYPE_ICON.get(t["action_type"], "•")
            nm = _first_name(t["assignee_name"], t["assignee_email"])
            pri = PRI_LABEL.get(t["priority"], t["priority"])
            lines.append(f"- {icon} **{nm}** — {t['description']} ({pri})")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by AIUI tasks service · every Friday 11:30 PM Asia/Manila*")

    return "\n".join(lines)


@router.post("/weekly-recap")
async def weekly_recap(x_cron_secret: str = Header(default="")):
    """Build the weekly recap and POST it to the n8n webhook.

    Protected by X-Cron-Secret header (must match CRON_SHARED_SECRET env var).
    """
    if CRON_SECRET and x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=403, detail="Bad or missing X-Cron-Secret")

    now_utc = datetime.now(timezone.utc)
    start_utc, end_utc, start_str, end_str = _week_window_utc(now_utc)
    # Some columns are TIMESTAMP WITHOUT TIME ZONE — strip tzinfo for comparison.
    start_naive = start_utc.replace(tzinfo=None)
    end_naive = end_utc.replace(tzinfo=None)

    # Fetch meetings + tasks via raw SQL (model isn't defined for meetings here)
    from sqlalchemy import text
    async with session() as s:
        meetings_rows = (
            await s.execute(
                text(
                    "SELECT id::text, title, date, attendees, summary, fathom_link "
                    "FROM meetings.records WHERE created_at >= :a AND created_at <= :b "
                    "ORDER BY created_at"
                ),
                {"a": start_naive, "b": end_naive},
            )
        ).mappings().all()

        tasks_rows = (
            await s.execute(
                select(TaskItem)
                .where(TaskItem.created_at >= start_naive, TaskItem.created_at <= end_naive)
                .order_by(TaskItem.created_at)
            )
        ).scalars().all()

    meetings = [dict(m) for m in meetings_rows]
    tasks = [
        {
            "id": str(t.id),
            "description": t.description,
            "action_type": t.action_type,
            "priority": t.priority,
            "assignee_email": t.assignee_email,
            "assignee_name": t.assignee_name,
            "status": t.status,
            "mode": t.mode,
            "result": t.result,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "meeting_id": str(t.meeting_id),
        }
        for t in tasks_rows
    ]

    body = _format_body(meetings, tasks, start_str, end_str)
    payload = {
        "recap_type": "weekly",
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "week_start": start_str,
        "week_end": end_str,
        "timezone": "Asia/Manila",
        "body": body,
    }

    # Post to n8n
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(WEEKLY_RECAP_URL, json=payload)
            logger.info("Weekly recap POST -> n8n: %s", resp.status_code)
            return {
                "ok": resp.is_success,
                "n8n_status": resp.status_code,
                "meetings_count": len(meetings),
                "tasks_count": len(tasks),
            }
    except Exception as exc:
        logger.exception("Weekly recap failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"n8n POST failed: {exc}")
