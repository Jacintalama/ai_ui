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
    db_uri: str | None = Field(default=None, max_length=500)


class SupabaseConfigStatus(BaseModel):
    configured: bool
    supabase_url: str | None = None
    has_db_uri: bool = False
    configured_by: str | None = None
    configured_at: str | None = None
    # OAuth state
    oauth_connected: bool = False
    linked_project_ref: str | None = None


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
        has_db_uri=bool(row.db_uri_encrypted),
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
        oauth_connected=bool(row.oauth_access_token_encrypted),
        linked_project_ref=row.linked_project_ref,
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
    db_uri = (body.db_uri or "").strip() or None
    if db_uri:
        if not db_uri.startswith("postgresql://"):
            raise HTTPException(status_code=400, detail="db_uri must start with postgresql://")
        # Catch the two most common Supabase pasting mistakes UP FRONT so we
        # never save something we know won't work.
        import re as _re
        from urllib.parse import unquote as _unq
        m = _re.match(
            r"^postgres(?:ql)?://(?:([^:@/]+)(?::([^@]+))?@)?\[?([^:/\]]+)\]?",
            db_uri,
        )
        if not m:
            raise HTTPException(status_code=400, detail="DB URI must look like postgresql://user:password@host:port/dbname")
        password = _unq(m.group(2)) if m.group(2) else ""
        host = m.group(3) or ""
        # If the user wrapped their real password in [brackets] (kept them
        # from Supabase's [YOUR-PASSWORD] placeholder), auto-strip them and
        # rewrite the URI to use the cleaned password.
        if password.startswith("[") and password.endswith("]") and len(password) > 2:
            inner = password[1:-1]
            if inner.upper() not in ("YOUR-PASSWORD", "PASSWORD") and inner:
                # Re-build URI with stripped brackets.
                db_uri = db_uri.replace(f":{password}@", f":{inner}@", 1)
                password = inner
        if password.upper() in ("YOUR-PASSWORD", "[YOUR-PASSWORD]", "PASSWORD") or not password:
            raise HTTPException(
                status_code=400,
                detail="Your DB URI still has the literal placeholder '[YOUR-PASSWORD]'. "
                       "Replace it with your real database password from Supabase → "
                       "Project Settings → Database → Database password (DON'T keep the brackets).",
            )
        if host.startswith("db.") and host.endswith(".supabase.co"):
            raise HTTPException(
                status_code=400,
                detail="That's Supabase's DIRECT connection (IPv6-only — our server can't "
                       "reach it). In Supabase → Project Settings → Database → Connection "
                       "string, change the dropdown from 'Direct connection' to "
                       "'Transaction pooler' (port 6543, host aws-0-<region>.pooler.supabase.com), "
                       "then paste THAT URI here.",
            )
    enc_key = crypto_utils.encrypt(body.anon_key.strip())
    enc_db = crypto_utils.encrypt(db_uri) if db_uri else None

    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        existing = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if existing:
            existing.supabase_url = url
            existing.anon_key_encrypted = enc_key
            existing.db_uri_encrypted = enc_db if enc_db is not None else existing.db_uri_encrypted
            existing.configured_by = user.email
            existing.updated_at = datetime.utcnow()
            row = existing
        else:
            row = ProjectSupabase(
                slug=slug, supabase_url=url, anon_key_encrypted=enc_key,
                db_uri_encrypted=enc_db,
                configured_by=user.email,
            )
            s.add(row)
        await s.commit()
        await s.refresh(row)
    return SupabaseConfigStatus(
        configured=True,
        supabase_url=row.supabase_url,
        has_db_uri=bool(row.db_uri_encrypted),
        configured_by=row.configured_by,
        configured_at=row.configured_at.isoformat() if row.configured_at else None,
        oauth_connected=bool(row.oauth_access_token_encrypted),
        linked_project_ref=row.linked_project_ref,
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
