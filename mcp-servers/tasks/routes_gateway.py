"""Multi-platform gateway state, and the user-token mint.

webhook-handler has no database driver and no DATABASE_URL, so every piece of
gateway state is reached through this module over HTTP.

Two routers, deliberately separate:

  router       prefix /gateway       X-Internal-Secret. Mounted BARE only, so
                                     it is reachable at http://tasks:8210 from
                                     inside the docker network and from nowhere
                                     else. Do not mount it under /tasks.
  page_router  prefix /tasks/gateway X-User-Email, injected by api-gateway from
                                     the browser's Open WebUI session cookie.

Never log a pairing code and never log a minted token.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

import gateway_pairing as gp
from db import session
from models import GatewayLink, GatewayPairingCode, GatewaySession
from owui_token import mint_owui_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway")

# Sessions idle longer than this are pruned on write. The Open WebUI chat they
# point at is never deleted: it is the user's data and lives in their sidebar.
SESSION_RETENTION_DAYS = 30

# One token covers every Open WebUI call in a turn, not one call, so it has to
# outlive the slowest turn rather than the slowest request. A voice memo can
# spend a minute in CPU transcription before the model is even asked. COUPLED to
# OWUIUserClient's timeout in webhook-handler/gateway/owui.py, which must stay
# comfortably below this: a call that outlives its own credential succeeds and
# then the write after it gets a 401, silently costing the user that turn in
# their sidebar. Still per-request and still short-lived.
GATEWAY_TOKEN_TTL_SECONDS = 300

# Expired and redeemed codes are swept on the write path. Nothing else prunes
# this table, and resolve is reachable from an unauthenticated public route, so
# without this a caller could grow it without bound.
PAIRING_CODE_RETENTION_HOURS = 24


def _require_internal(secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResolveIn(BaseModel):
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)
    platform_user_name: str = ""


class SessionIn(BaseModel):
    platform: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    owui_chat_id: str = Field(min_length=1)
    owui_user_id: str = Field(min_length=1)


@router.post("/resolve")
async def resolve(body: ResolveIn,
                  x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Who is this platform user, and if we do not know, how do they tell us?

    Linked   -> {linked: true, email, owui_user_id, owui_token}
    Unlinked -> {linked: false, code, expires_at}

    A repeat call while a code is still live reuses the same ROW rather than
    inserting another, so a user only ever has one live code. The code VALUE
    is re-minted on every call though, because only the hash is stored, so the
    original value can never be recovered to return again. Re-minting also
    invalidates whatever code was issued before, which is fine: the newest
    message a bot sends always carries the working one.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == body.platform,
                GatewayLink.platform_user_id == body.platform_user_id,
            )
        )).scalar_one_or_none()

        if link:
            return {
                "linked": True,
                "email": link.email,
                "owui_user_id": link.owui_user_id,
                "owui_token": mint_owui_token(
                    link.owui_user_id, ttl_seconds=GATEWAY_TOKEN_TTL_SECONDS),
            }

        now = _now()
        await s.execute(delete(GatewayPairingCode).where(
            GatewayPairingCode.expires_at
            < now - timedelta(hours=PAIRING_CODE_RETENTION_HOURS)))

        live = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.platform == body.platform,
                GatewayPairingCode.platform_user_id == body.platform_user_id,
                GatewayPairingCode.redeemed_at.is_(None),
                GatewayPairingCode.expires_at > now,
            ).order_by(GatewayPairingCode.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if live:
            # The code itself is not recoverable from the hash, so a resend has
            # to re-mint. Reuse the ROW and overwrite its hash, which keeps the
            # one-live-code-per-user property intact.
            code = gp.generate_code()
            live.code_hash = gp.hash_code(code)
            live.expires_at = now + timedelta(seconds=gp.CODE_TTL_SECONDS)
            live.platform_user_name = body.platform_user_name or live.platform_user_name
            expires_at = live.expires_at
            await s.commit()
            return {"linked": False, "code": code,
                    "expires_at": expires_at.isoformat()}

        code = gp.generate_code()
        row = GatewayPairingCode(
            code_hash=gp.hash_code(code),
            platform=body.platform,
            platform_user_id=body.platform_user_id,
            platform_user_name=body.platform_user_name or None,
            expires_at=now + timedelta(seconds=gp.CODE_TTL_SECONDS),
        )
        s.add(row)
        await s.commit()
        log.info("gateway: issued a pairing code for %s user %s",
                 body.platform, body.platform_user_id)   # never the code
        return {"linked": False, "code": code,
                "expires_at": row.expires_at.isoformat()}


@router.get("/session")
async def get_session(platform: str, chat_id: str,
                      x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == platform,
                GatewaySession.chat_id == chat_id,
            )
        )).scalar_one_or_none()
    if not row:
        return {"owui_chat_id": None}
    return {"owui_chat_id": row.owui_chat_id, "owui_user_id": row.owui_user_id}


@router.put("/session")
async def put_session(body: SessionIn,
                      x_internal_secret: str = Header(default="")) -> dict[str, str]:
    """Upsert the conversation -> Open WebUI chat mapping, and prune old rows."""
    _require_internal(x_internal_secret)
    now = _now()
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == body.platform,
                GatewaySession.chat_id == body.chat_id,
            )
        )).scalar_one_or_none()
        if row:
            row.owui_chat_id = body.owui_chat_id
            row.owui_user_id = body.owui_user_id
            row.updated_at = now
        else:
            s.add(GatewaySession(
                platform=body.platform,
                chat_id=body.chat_id,
                owui_chat_id=body.owui_chat_id,
                owui_user_id=body.owui_user_id,
                updated_at=now,
            ))
        # Scoped to this user on purpose: unscoped, every message swept every
        # other user's rows and could not use the (owui_user_id, updated_at)
        # index, so one person's write paid for everyone's housekeeping.
        # The tradeoff is that a user who starts one conversation and never
        # returns leaves a row nothing will collect, since only their own next
        # write matches. Accepted: the row is a pointer, and the conversation it
        # points at is an Open WebUI chat we never delete anyway, so the cost is
        # a few dozen bytes and no data is retained that would not be retained
        # regardless.
        await s.execute(delete(GatewaySession).where(
            GatewaySession.owui_user_id == body.owui_user_id,
            GatewaySession.updated_at < now - timedelta(days=SESSION_RETENTION_DAYS),
        ))
        await s.commit()
    return {"status": "ok"}


@router.get("/sessions/recent")
async def recent_sessions(owui_user_id: str, limit: int = 10,
                          x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Backs /resume. Newest first, capped."""
    _require_internal(x_internal_secret)
    limit = max(1, min(limit, 25))
    async with session() as s:
        rows = (await s.execute(
            select(GatewaySession)
            .where(GatewaySession.owui_user_id == owui_user_id)
            .order_by(GatewaySession.updated_at.desc())
            .limit(limit)
        )).scalars().all()
    return {"sessions": [
        {"platform": r.platform, "chat_id": r.chat_id,
         "owui_chat_id": r.owui_chat_id,
         "updated_at": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows
    ]}


# ---------------------------------------------------------------------------
# User-facing. X-User-Email is injected by api-gateway from the caller's Open
# WebUI session cookie, so reaching these endpoints already proves who you are.
# That is what makes redeeming a code inherently an act by a known account: the
# gateway never learns a password and the user never pastes a token.
# ---------------------------------------------------------------------------
from fastapi import Depends                             # noqa: E402
from fastapi.responses import FileResponse              # noqa: E402

from auth import CurrentUser, current_user              # noqa: E402
from models import GatewayRedeemBudget                  # noqa: E402

page_router = APIRouter(prefix="/tasks/gateway")


class RedeemIn(BaseModel):
    # Bounded on purpose. An 8 character code pasted with spaces or dashes fits
    # easily, and normalize_code scans every character it is given, so an
    # unbounded body would buy an O(n) scan on a public endpoint.
    code: str = Field(min_length=1, max_length=24)


@page_router.get("/link", include_in_schema=False)
def link_page() -> FileResponse:
    """Inert HTML. Everything it can do goes back through POST /link."""
    return FileResponse("static/gateway-link.html", media_type="text/html")


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    A minted token carries the id, not the address, so pairing resolves it once
    here. Raw asyncpg because public."user" is Open WebUI's own table and has no
    model in this service; same approach as routes_knowledge_graph.py.
    """
    import asyncpg

    conn = await asyncpg.connect(os.environ.get("DATABASE_URL", ""))
    try:
        row = await conn.fetchrow(
            'SELECT id FROM public."user" WHERE lower(email) = lower($1) LIMIT 1',
            email)
    finally:
        await conn.close()
    return row["id"] if row else None


async def _locked_minutes(s, email: str, now: datetime) -> int | None:
    """Whole minutes left on this account's lockout, or None if it is not locked."""
    row = (await s.execute(
        select(GatewayRedeemBudget).where(GatewayRedeemBudget.email == email)
    )).scalar_one_or_none()
    if row is None or row.locked_until is None or row.locked_until <= now:
        return None
    return max(1, int((row.locked_until - now).total_seconds() // 60) + 1)


async def _record_failure(s, email: str, now: datetime) -> None:
    """Charge a wrong guess to the account that made it.

    Counting on the account rather than the code is the whole point: a wrong
    code matches no row, so the only way to count it on the code would be to
    increment every live one, which would let one guesser lock out every
    pending pairing on the platform.

    A served lock resets the window. Re-locking on the first later typo would
    punish someone who already waited out a lockout far more than an attacker,
    who simply waits either way.
    """
    row = (await s.execute(
        select(GatewayRedeemBudget).where(GatewayRedeemBudget.email == email)
    )).scalar_one_or_none()

    if row is None:
        s.add(GatewayRedeemBudget(email=email, failures=1, window_started_at=now))
        await s.commit()
        return

    window_expired = (
        row.window_started_at is None
        or row.window_started_at < now - timedelta(seconds=gp.REDEEM_WINDOW_SECONDS)
    )
    lock_served = row.locked_until is not None and row.locked_until <= now

    if window_expired or lock_served:
        row.failures = 1
        row.window_started_at = now
        row.locked_until = None
    else:
        row.failures = (row.failures or 0) + 1
        if row.failures >= gp.MAX_REDEEM_ATTEMPTS:
            row.locked_until = now + timedelta(seconds=gp.REDEEM_LOCKOUT_SECONDS)
            row.failures = 0
            row.window_started_at = now
    await s.commit()


@page_router.post("/link")
async def redeem(body: RedeemIn,
                 user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Turn a pairing code into a link, as the signed-in user."""
    code = gp.normalize_code(body.code)
    now = _now()

    async with session() as s:
        locked_for = await _locked_minutes(s, user.email, now)
        if locked_for is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many wrong codes. Try again in {locked_for} minutes.")

        if len(code) != gp.CODE_LENGTH:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=400,
                                detail="That code does not look right.")

        row = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.code_hash == gp.hash_code(code),
                GatewayPairingCode.redeemed_at.is_(None),
            ).limit(1)
        )).scalar_one_or_none()

        if row is None:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=404,
                                detail="That code is not valid. Ask for a new one.")
        if row.expires_at <= now:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=410,
                                detail="That code has expired. Ask for a new one.")

        owui_user_id = await _owui_user_id_for(user.email)
        if not owui_user_id:
            raise HTTPException(status_code=404,
                                detail="No IO account for that address.")

        existing = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == row.platform,
                GatewayLink.platform_user_id == row.platform_user_id,
            )
        )).scalar_one_or_none()
        if existing:
            existing.owui_user_id = owui_user_id
            existing.email = user.email
            existing.platform_user_name = row.platform_user_name
            existing.linked_at = now
        else:
            s.add(GatewayLink(
                platform=row.platform,
                platform_user_id=row.platform_user_id,
                owui_user_id=owui_user_id,
                email=user.email,
                platform_user_name=row.platform_user_name,
            ))
        row.redeemed_at = now
        platform, name = row.platform, row.platform_user_name or ""

        # A success wipes the slate: the account clearly is not guessing.
        await s.execute(
            delete(GatewayRedeemBudget).where(GatewayRedeemBudget.email == user.email))
        await s.commit()

    log.info("gateway: linked a %s account to %s", platform, user.email)
    return {"status": "linked", "platform": platform, "platform_user_name": name}


@page_router.get("/connections")
async def list_connections(
        user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Which chat surfaces this account has connected.

    Drives the page's top half. Returns every platform the registry knows about,
    connected or not, so the page can render "Connect" for the ones that are not
    rather than silently omitting them.
    """
    async with session() as s:
        rows = (await s.execute(
            select(GatewayLink).where(GatewayLink.email == user.email)
            .order_by(GatewayLink.linked_at.desc())
        )).scalars().all()

    linked = {
        r.platform: {
            "platform": r.platform,
            "name": r.platform_user_name or "",
            "linked_at": r.linked_at.isoformat() if r.linked_at else None,
        }
        for r in rows
    }
    return {
        "telegram_bot": os.environ.get("GATEWAY_TELEGRAM_BOT", ""),
        "connections": [
            linked.get(name, {"platform": name, "name": "", "linked_at": None})
            for name in ("telegram", "cli")
        ],
    }


@page_router.delete("/connections/{platform}")
async def disconnect(platform: str,
                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    """Unlink one surface from this account.

    Deletes only the link. Session rows are left alone deliberately: they point
    at real Open WebUI chats which are the user's own data, and if this account
    re-pairs the same surface it picks the conversation back up. If a DIFFERENT
    account pairs it, the owner check in get_or_create_chat starts them a fresh
    chat rather than showing them this one.
    """
    async with session() as s:
        result = await s.execute(
            delete(GatewayLink).where(
                GatewayLink.email == user.email,
                GatewayLink.platform == platform,
            ))
        await s.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="That was not connected.")
    log.info("gateway: disconnected %s from %s", platform, user.email)
    return {"status": "disconnected", "platform": platform}
