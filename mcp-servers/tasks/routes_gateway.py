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
from sqlalchemy import delete, select, update

import gateway_pairing as gp
from db import session
from models import GatewayLink, GatewayPairingCode, GatewaySession
from owui_token import mint_owui_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway")

# Sessions idle longer than this are pruned on write. The Open WebUI chat they
# point at is never deleted: it is the user's data and lives in their sidebar.
SESSION_RETENTION_DAYS = 30


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

    A repeat call while a code is still live returns THAT SAME CODE rather than
    issuing another. Otherwise someone who messages twice gets two codes, only
    one works, and the resend cooldown reads as an error to a person who did
    nothing wrong.
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
                "owui_token": mint_owui_token(link.owui_user_id),
            }

        now = _now()
        live = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.platform == body.platform,
                GatewayPairingCode.platform_user_id == body.platform_user_id,
                GatewayPairingCode.redeemed_at.is_(None),
                GatewayPairingCode.expires_at > now,
                GatewayPairingCode.attempts < gp.MAX_REDEEM_ATTEMPTS,
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
        await s.execute(delete(GatewaySession).where(
            GatewaySession.updated_at < now - timedelta(days=SESSION_RETENTION_DAYS)
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
