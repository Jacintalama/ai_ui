"""Generic per-key bot state KV — SYSTEM endpoints (not user-scoped).

Called by the webhook-handler, authed with X-Internal-Secret (the same secret
the discord-links + schedule-result callbacks use). Lets the bot persist
conversational state (pending intents, clarify replies, current app) so a
redeploy doesn't wipe in-flight chats. Values are arbitrary JSON; an optional
ttl_seconds sets an expiry (expired rows read back as absent).
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select

from db import session
from models import BotState

router = APIRouter(prefix="/state")


def _require_internal(x_internal_secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StateIn(BaseModel):
    value: Any
    ttl_seconds: int | None = None


@router.get("/{key}")
async def get_state(key: str, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(BotState).where(BotState.state_key == key)
        )).scalar_one_or_none()
    if row is None:
        return {"value": None}
    if row.expires_at is not None and row.expires_at < _utcnow():
        return {"value": None}
    return {"value": row.value}


@router.put("/{key}")
async def put_state(
    key: str, body: StateIn, x_internal_secret: str = Header(default=""),
) -> dict[str, str]:
    _require_internal(x_internal_secret)
    expires = _utcnow() + timedelta(seconds=body.ttl_seconds) if body.ttl_seconds else None
    async with session() as s:
        row = (await s.execute(
            select(BotState).where(BotState.state_key == key)
        )).scalar_one_or_none()
        if row:
            row.value = body.value
            row.updated_at = _utcnow()
            row.expires_at = expires
        else:
            s.add(BotState(
                state_key=key, value=body.value,
                updated_at=_utcnow(), expires_at=expires))
        await s.commit()
    return {"status": "ok"}


@router.delete("/{key}")
async def delete_state(key: str, x_internal_secret: str = Header(default="")) -> dict[str, str]:
    _require_internal(x_internal_secret)
    async with session() as s:
        await s.execute(sa_delete(BotState).where(BotState.state_key == key))
        await s.commit()
    return {"status": "ok"}
