"""Events out (2026-10-28): the platform tells the outside what happened.

A person sets a URL on the Agents page under Automation. From then on the
platform POSTs there when something of theirs happens:

    build.finished        an App Builder build or enhance ended
    schedule.finished     a scheduled run ended
    automation.finished   an automation ran (done, failed or waiting)
    approval.requested    an agent stopped to ask
    approval.decided      a question was answered
    minutes.taken         a meeting left minutes behind

Each post is JSON, {"event", "at", "id", "data"}, signed with the hook's
secret: X-IO-Signature is "sha256=" and the HMAC-SHA256 of the body, so a
receiver can tell the platform's posts from anybody's. Three tries with a
short wait between; a hook that keeps failing is noted on its row, never
disabled on its own.

Everything here is best effort and fire-and-forget: emit() returns at once
and nothing that happens on the way out can touch the thing that happened.
The database and the post are seams that tests replace.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("events_out")

EVENTS = ("build.finished", "schedule.finished", "automation.finished",
          "approval.requested", "approval.decided", "minutes.taken")
ALL = "*"
MAX_HOOKS = 5
MAX_URL = 2000
MAX_LABEL = 60
TIMEOUT_SECONDS = 20.0
TRIES = 3
#: How much of a text field (an answer, a result) a post carries.
MAX_TEXT = 4000

_TASKS: set = set()


# --- shaping ---------------------------------------------------------------------

def clean_events(events) -> list[str]:
    """The event names to send, validated: unknown names are dropped, an
    empty or starred list means everything."""
    if not isinstance(events, list):
        return [ALL]
    out = []
    for e in events:
        e = str(e or "").strip()
        if e == ALL:
            return [ALL]
        if e in EVENTS and e not in out:
            out.append(e)
    return out or [ALL]


def wants(hook: dict, event: str) -> bool:
    chosen = hook.get("events") or [ALL]
    return ALL in chosen or event in chosen


def make_secret() -> str:
    return "ehs_" + secrets.token_urlsafe(24)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    """For a receiver written in Python, and for the tests."""
    return hmac.compare_digest(sign(secret, body), str(signature or ""))


def _clip(value):
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT]
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value[:50]]
    return value


def envelope(event: str, data: dict, event_id: str | None = None) -> dict:
    return {"event": event, "at": datetime.now(timezone.utc).isoformat(),
            "id": event_id or uuid.uuid4().hex, "data": _clip(data or {})}


def _iso(dt) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def row_of(h) -> dict:
    """A hook as the page sees it: the secret only as a prefix. The whole
    secret is shown once, when the hook is made."""
    return {"id": str(h.id), "url": h.url, "label": h.label or "",
            "events": list(h.events or [ALL]), "enabled": bool(h.enabled),
            "secret_prefix": (h.secret or "")[:8], "created_at": _iso(h.created_at),
            "last_sent_at": _iso(h.last_sent_at), "last_result": h.last_result or "",
            "fail_count": int(h.fail_count or 0)}


class TooMany(Exception):
    pass


# --- the database -----------------------------------------------------------------

async def _hooks_rows(email: str, enabled_only: bool = False) -> list[dict]:
    from sqlalchemy import select
    from db import session
    from models import EventHook
    async with session() as s:
        q = select(EventHook).where(EventHook.user_email == email)
        if enabled_only:
            q = q.where(EventHook.enabled.is_(True))
        rows = (await s.execute(q.order_by(EventHook.created_at))).scalars().all()
        return [dict(row_of(h), secret=h.secret) for h in rows]


async def _create_row(email: str, fields: dict) -> dict:
    from sqlalchemy import select, func
    from db import session
    from models import EventHook
    async with session() as s:
        count = (await s.execute(
            select(func.count()).select_from(EventHook)
            .where(EventHook.user_email == email))).scalar_one()
        if count >= MAX_HOOKS:
            raise TooMany()
        row = EventHook(id=uuid.uuid4(), user_email=email, secret=make_secret(),
                        created_at=datetime.now(timezone.utc), **fields)
        s.add(row)
        await s.commit()
        return dict(row_of(row), secret=row.secret)


async def _update_row(email: str, hook_id: str, changes: dict) -> dict | None:
    from sqlalchemy import select
    from db import session
    from models import EventHook
    try:
        hid = uuid.UUID(str(hook_id))
    except ValueError:
        return None
    async with session() as s:
        row = (await s.execute(
            select(EventHook).where(EventHook.id == hid, EventHook.user_email == email)
        )).scalar_one_or_none()
        if row is None:
            return None
        for k, v in changes.items():
            setattr(row, k, v)
        await s.commit()
        return row_of(row)


async def _delete_row(email: str, hook_id: str) -> bool:
    from sqlalchemy import select
    from db import session
    from models import EventHook
    try:
        hid = uuid.UUID(str(hook_id))
    except ValueError:
        return False
    async with session() as s:
        row = (await s.execute(
            select(EventHook).where(EventHook.id == hid, EventHook.user_email == email)
        )).scalar_one_or_none()
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
    return True


async def _note_row(hook_id: str, ok: bool, result: str) -> None:
    from sqlalchemy import select
    from db import session
    from models import EventHook
    try:
        hid = uuid.UUID(str(hook_id))
    except ValueError:
        return
    async with session() as s:
        row = (await s.execute(select(EventHook).where(EventHook.id == hid))).scalar_one_or_none()
        if row is None:
            return
        row.last_sent_at = datetime.now(timezone.utc)
        row.last_result = (result or "")[:200]
        row.fail_count = 0 if ok else int(row.fail_count or 0) + 1
        await s.commit()


async def _post_once(url: str, body: bytes, signature: str, event: str) -> tuple[bool, str]:
    """One POST. (ok, a short word for the row)."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.post(url, content=body, headers={
            "Content-Type": "application/json", "X-IO-Signature": signature,
            "X-IO-Event": event, "User-Agent": "io-platform-events/1"})
    return r.status_code < 300, ("ok" if r.status_code < 300 else f"http {r.status_code}")


#: Seams. Tests replace these rather than opening a database or the net.
_hooks = _hooks_rows
_create = _create_row
_update = _update_row
_delete = _delete_row
_note = _note_row
_post = _post_once
_spawn = asyncio.create_task
_sleep = asyncio.sleep


# --- sending ---------------------------------------------------------------------------

async def deliver(hook: dict, event: str, data: dict, event_id: str | None = None) -> bool:
    """POST one event to one hook, with retries. Never raises."""
    body = json.dumps(envelope(event, data, event_id), ensure_ascii=False,
                      default=str).encode("utf-8")
    signature = sign(str(hook.get("secret") or ""), body)
    ok, word = False, "not sent"
    for attempt in range(TRIES):
        try:
            ok, word = await _post(hook["url"], body, signature, event)
        except Exception as exc:                            # noqa: BLE001
            ok, word = False, type(exc).__name__
        if ok or (word.startswith("http") and not word.startswith("http 5")):
            break
        await _sleep(2 * (attempt + 1))
    try:
        await _note(hook["id"], ok, word)
    except Exception:                                       # noqa: BLE001
        logger.warning("event hook %s: could not note the result", hook.get("id"), exc_info=True)
    if not ok:
        logger.warning("event %s to hook %s failed: %s", event, hook.get("id"), word)
    return ok


async def send(email: str, event: str, data: dict) -> int:
    """Every enabled hook of this person that wants this event, posted to
    in turn. Returns how many were posted to. Never raises."""
    try:
        hooks = await _hooks(email, enabled_only=True)
    except Exception:                                       # noqa: BLE001
        logger.warning("event hooks could not be read for %s", email, exc_info=True)
        return 0
    sent = 0
    event_id = uuid.uuid4().hex
    for hook in hooks:
        if not wants(hook, event):
            continue
        await deliver(hook, event, data, event_id)
        sent += 1
    return sent


def emit(email: str, event: str, data: dict) -> None:
    """Fire and forget. Returns at once; the posts happen in the
    background and nothing about them can reach the caller."""
    if not email or event not in EVENTS:
        return
    try:
        task = _spawn(send(email, event, data))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    except Exception:                                       # noqa: BLE001
        # No running loop, or the loop is closing: the event is lost and
        # the thing that happened is not.
        logger.warning("event %s could not be queued", event, exc_info=True)


# --- what the routes call ---------------------------------------------------------------

async def hooks_for(email: str) -> list[dict]:
    return [{k: v for k, v in h.items() if k != "secret"} for h in await _hooks(email)]


async def create(email: str, url: str, events, label: str) -> dict:
    """The new hook, with its whole secret this once."""
    return await _create(email, {"url": url.strip()[:MAX_URL], "events": clean_events(events),
                                 "label": " ".join(str(label or "").split())[:MAX_LABEL],
                                 "enabled": True})


async def update(email: str, hook_id: str, changes: dict) -> dict | None:
    return await _update(email, hook_id, changes)


async def delete(email: str, hook_id: str) -> bool:
    return await _delete(email, hook_id)


async def test_hook(email: str, hook_id: str) -> bool:
    """One test event, sent now and waited for, so the page can say
    whether the URL answered."""
    hooks = await _hooks(email)
    hook = next((h for h in hooks if h["id"] == str(hook_id)), None)
    if hook is None:
        return False
    return await deliver(hook, "automation.finished",
                         {"test": True, "note": "A test from the Agents page."})
