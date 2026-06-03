"""Discord ↔ email link store — SYSTEM endpoints (not user-scoped).

Called by the webhook-handler, authed with X-Internal-Secret (the same secret
the schedule-result callback uses). NOT the cron secret, NOT X-User-Email.
"""
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from db import session
from models import DiscordLink

router = APIRouter(prefix="/discord-links")


def _require_internal(x_internal_secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


class RequestIn(BaseModel):
    discord_id: str = Field(min_length=1)
    discord_username: str = ""
    email: str = Field(min_length=3)


class DecideIn(BaseModel):
    decided_by: str = ""


@router.post("/request")
async def request_link(body: RequestIn, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == body.discord_id)
        )).scalar_one_or_none()
        if link:
            link.email = body.email
            link.discord_username = body.discord_username
            link.status = "pending"
            link.requested_at = datetime.utcnow()
            link.decided_at = None
            link.decided_by = None
        else:
            s.add(DiscordLink(
                discord_id=body.discord_id,
                discord_username=body.discord_username,
                email=body.email,
                status="pending",
            ))
        await s.commit()
    return {"status": "pending"}


@router.post("/{discord_id}/approve")
async def approve_link(
    discord_id: str, body: DecideIn, x_internal_secret: str = Header(default=""),
) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="no link request")
        link.status = "approved"
        link.decided_at = datetime.utcnow()
        link.decided_by = body.decided_by
        email = link.email
        await s.commit()
    return {"email": email}


@router.post("/{discord_id}/reject")
async def reject_link(
    discord_id: str, body: DecideIn, x_internal_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_internal(x_internal_secret)
    async with session() as s:
        await s.execute(
            update(DiscordLink).where(DiscordLink.discord_id == discord_id).values(
                status="rejected", decided_at=datetime.utcnow(), decided_by=body.decided_by,
            )
        )
        await s.commit()
    return {"status": "rejected"}


@router.get("/resolve/{discord_id}")
async def resolve_link(
    discord_id: str, x_internal_secret: str = Header(default=""),
) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
    if link and link.status == "approved":
        return {"email": link.email}
    return {"email": None}


class ThreadIn(BaseModel):
    thread_id: str


@router.get("/{discord_id}/thread")
async def get_thread(discord_id: str, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
    return {"thread_id": link.schedules_thread_id if link else None}


@router.post("/{discord_id}/thread")
async def set_thread(
    discord_id: str, body: ThreadIn, x_internal_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
        if link:
            link.schedules_thread_id = body.thread_id
        else:
            # Unlinked users have no link row yet. Create a placeholder so the
            # thread mapping persists — otherwise an UPDATE matches zero rows and
            # the bot creates a fresh thread on every open. email is NOT NULL, so
            # use the synthetic identity the rest of the system uses for unlinked
            # Discord users; status stays "pending" so resolve_link never treats
            # this as an approved link. A later /request upserts the real email
            # and preserves schedules_thread_id.
            s.add(DiscordLink(
                discord_id=discord_id,
                email=f"discord-{discord_id}@aiui.local",
                status="pending",
                schedules_thread_id=body.thread_id,
            ))
        await s.commit()
    return {"status": "ok"}


@router.get("/{discord_id}/builder-thread")
async def get_builder_thread(discord_id: str, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
    return {"thread_id": link.builder_thread_id if link else None}


@router.post("/{discord_id}/builder-thread")
async def set_builder_thread(
    discord_id: str, body: ThreadIn, x_internal_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(DiscordLink).where(DiscordLink.discord_id == discord_id)
        )).scalar_one_or_none()
        if link:
            link.builder_thread_id = body.thread_id
        else:
            # Same placeholder rationale as set_thread (unlinked users) so the
            # App Builder thread mapping persists across opens.
            s.add(DiscordLink(
                discord_id=discord_id,
                email=f"discord-{discord_id}@aiui.local",
                status="pending",
                builder_thread_id=body.thread_id,
            ))
        await s.commit()
    return {"status": "ok"}
