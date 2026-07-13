"""Seed a project's chat thread with the user's original build request.

The preview/chat thread reads ``ChatMessage`` rows keyed by (slug, user_email).
The initial build prompt was never written there, so the thread opened blank and
the user could not see what they had asked for. Recording the prompt as the first
``role="user"`` message fixes that on every surface that later reads the thread.
"""
from __future__ import annotations

from sqlalchemy import select

from models import ChatMessage


async def seed_user_prompt(s, slug: str | None, user_email: str | None, prompt: str | None) -> None:
    """Idempotently record the user's original request as the first chat message.

    No-op when any input is empty, or when a ``role="user"`` message already
    exists for this (slug, user_email) — so a retried or duplicated build create
    will not double-post. Does not commit; the caller's transaction owns that.
    """
    prompt = (prompt or "").strip()
    slug = (slug or "").strip()
    user_email = (user_email or "").strip()
    if not (slug and user_email and prompt):
        return
    exists = (await s.execute(
        select(ChatMessage.id).where(
            ChatMessage.slug == slug,
            ChatMessage.user_email == user_email,
            ChatMessage.role == "user",
        ).limit(1)
    )).first()
    if exists:
        return
    s.add(ChatMessage(slug=slug, user_email=user_email, role="user", content=prompt[:20_000]))
