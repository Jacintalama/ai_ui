"""Supabase configuration per project.

GET    — anyone with viewer+ on the project (so members can confirm one is set)
POST   — project owner only (no platform-admin bypass; mis-configuring secrets
         is high-risk so we require explicit project ownership)
DELETE — project owner only (same reasoning)

The anon key is Fernet-encrypted at rest and never returned from the API.
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import crypto_utils
from auth import AdminUser, current_admin
from db import session
from models import ProjectSupabase
from routes_projects import _require_role, _validate_slug

router = APIRouter(prefix="/api/projects")

# Supabase URLs are like https://abcdefgh.supabase.co. Allow any https host
# with at least one dot — keep liberal so self-hosted works.
_URL_RE = re.compile(r"^https://[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(:\d+)?(/.*)?$")


class SupabaseConfigRequest(BaseModel):
    supabase_url: str = Field(min_length=10, max_length=300)
    anon_key: str = Field(min_length=20, max_length=2000)


class SupabaseConfigStatus(BaseModel):
    configured: bool
    supabase_url: str | None = None
    configured_by: str | None = None
    configured_at: str | None = None


@router.get("/{slug}/supabase", response_model=SupabaseConfigStatus)
async def get_supabase(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "viewer", is_admin=user.is_admin)
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
    if row is None:
        return SupabaseConfigStatus(configured=False)
    return SupabaseConfigStatus(
        configured=True,
        supabase_url=row.supabase_url,
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
    )


@router.post("/{slug}/supabase", response_model=SupabaseConfigStatus)
async def set_supabase(
    slug: str,
    body: SupabaseConfigRequest,
    user: AdminUser = Depends(current_admin),
):
    _validate_slug(slug)
    url = body.supabase_url.strip()
    if not _URL_RE.match(url):
        raise HTTPException(status_code=400, detail="supabase_url must be an https://… URL")
    enc_key = crypto_utils.encrypt(body.anon_key.strip())

    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        existing = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if existing:
            existing.supabase_url = url
            existing.anon_key_encrypted = enc_key
            existing.configured_by = user.email
            existing.updated_at = datetime.utcnow()
            row = existing
        else:
            row = ProjectSupabase(
                slug=slug, supabase_url=url, anon_key_encrypted=enc_key,
                configured_by=user.email,
            )
            s.add(row)
        await s.commit()
        await s.refresh(row)
    return SupabaseConfigStatus(
        configured=True,
        supabase_url=row.supabase_url,
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
    )


@router.delete("/{slug}/supabase", status_code=204)
async def delete_supabase(slug: str, user: AdminUser = Depends(current_admin)):
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is not None:
            await s.delete(row)
            await s.commit()
    return None
