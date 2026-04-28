"""Per-user chat history for a project (the in-preview Chat tab).

Chat is the user's #1 priority — never auto-clears. Only an explicit DELETE
wipes a user's history for a single project.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as _del
from sqlalchemy import select

from auth import AdminUser, current_admin
from db import session
from models import ChatMessage
from routes_projects import _require_role, _validate_slug

router = APIRouter(prefix="/api/projects")

MAX_MESSAGES = 200


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


@router.get("/{slug}/chat", response_model=list[ChatMessageOut])
async def list_chat(
    slug: str,
    limit: int = 200,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    limit = max(1, min(limit, MAX_MESSAGES))
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        rows = (await s.execute(
            select(ChatMessage).where(
                ChatMessage.slug == slug,
                ChatMessage.user_email == user.email,
            ).order_by(ChatMessage.created_at.asc()).limit(limit)
        )).scalars().all()
    return [
        ChatMessageOut(
            id=str(m.id), role=m.role, content=m.content,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in rows
    ]


@router.post("/{slug}/chat", response_model=ChatMessageOut, status_code=201)
async def append_chat(
    slug: str,
    body: ChatMessageIn,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        msg = ChatMessage(
            slug=slug, user_email=user.email,
            role=body.role, content=body.content,
        )
        s.add(msg)
        await s.commit()
        await s.refresh(msg)
    return ChatMessageOut(
        id=str(msg.id), role=msg.role, content=msg.content,
        created_at=msg.created_at.isoformat() if msg.created_at else "",
    )


@router.delete("/{slug}/chat", status_code=204)
async def clear_chat(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer")
        await s.execute(_del(ChatMessage).where(
            ChatMessage.slug == slug,
            ChatMessage.user_email == user.email,
        ))
        await s.commit()
    return None
