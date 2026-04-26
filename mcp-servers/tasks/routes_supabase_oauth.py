"""Supabase OAuth integration — start + callback endpoints.

Flow:
  1. Browser → GET /api/projects/{slug}/supabase/oauth/start
     We generate a CSRF state token, store it (slug + user_email),
     302-redirect to Supabase's authorize URL.

  2. User authorizes on supabase.com.

  3. Supabase → GET /api/supabase/oauth/callback?code=...&state=...
     We validate state, exchange code for access_token + refresh_token via
     POST https://api.supabase.com/v1/oauth/token, encrypt + store on the
     project_supabase row, 302-redirect back to the App Builder preview
     page so the user sees their project.

State is signed with the AIUI_FERNET_KEY (so we don't need a separate store).
Tokens are encrypted with the same key before persisting.
"""
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

import crypto_utils
from auth import AdminUser, current_admin
from db import session
from models import ProjectSupabase
from routes_projects import _require_role, _validate_slug

router = APIRouter()  # mounted at root; this module's paths are absolute

CLIENT_ID = os.environ.get("AIUI_SUPABASE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AIUI_SUPABASE_CLIENT_SECRET", "")
PUBLIC_BASE_URL = os.environ.get(
    "AIUI_PUBLIC_BASE_URL", "https://ai-ui.coolestdomain.win"
).rstrip("/")
REDIRECT_URI = f"{PUBLIC_BASE_URL}/api/supabase/oauth/callback"

AUTHORIZE_URL = "https://api.supabase.com/v1/oauth/authorize"
TOKEN_URL = "https://api.supabase.com/v1/oauth/token"

STATE_TTL_SECONDS = 600  # 10 minutes max between start and callback


def _make_state(slug: str, email: str) -> str:
    """Sign + encrypt the state — no separate store needed."""
    payload = {
        "slug": slug,
        "email": email,
        "nonce": secrets.token_urlsafe(16),
        "ts": int(time.time()),
    }
    return crypto_utils.encrypt(json.dumps(payload))


def _read_state(state: str) -> dict:
    try:
        plain = crypto_utils.decrypt(state)
        payload = json.loads(plain)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    if int(time.time()) - int(payload.get("ts", 0)) > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired — start over.")
    return payload


@router.get("/api/projects/{slug}/supabase/oauth/start")
async def oauth_start(slug: str, user: AdminUser = Depends(current_admin)):
    """Begin the OAuth flow for a project. Owner-only. 302 → Supabase."""
    _validate_slug(slug)
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Supabase OAuth is not configured on this server.",
        )
    async with session() as s:
        await _require_role(s, slug, user.email, "owner", is_admin=user.is_admin)
    state = _make_state(slug, user.email)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    return RedirectResponse(
        url=f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=302
    )


@router.get("/api/supabase/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """Receive the authorization code from Supabase, exchange for tokens.

    Note: this endpoint is unauthenticated (Supabase calls it from the
    browser), but the encrypted state binds the callback to (slug, email).
    """
    if error:
        # Build a redirect to the App Builder with the error in a query string.
        msg = (error_description or error)[:300]
        return RedirectResponse(
            url=f"{PUBLIC_BASE_URL}/tasks/app-builder?{urlencode({'supabase_oauth_error': msg})}",
            status_code=302,
        )

    payload = _read_state(state)
    slug = payload["slug"]
    email = payload["email"]

    # Exchange code for tokens.
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Supabase token exchange failed: HTTP {resp.status_code} — {resp.text[:300]}",
        )
    tok = resp.json()
    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    expires_in = int(tok.get("expires_in", 3600))
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Supabase response")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

    enc_access = crypto_utils.encrypt(access_token)
    enc_refresh = crypto_utils.encrypt(refresh_token) if refresh_token else None

    async with session() as s:
        existing = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if existing:
            existing.oauth_access_token_encrypted = enc_access
            existing.oauth_refresh_token_encrypted = enc_refresh
            existing.oauth_expires_at = expires_at
            existing.configured_by = email
            existing.updated_at = datetime.utcnow()
        else:
            row = ProjectSupabase(
                slug=slug,
                supabase_url=None,
                anon_key_encrypted=None,
                configured_by=email,
                oauth_access_token_encrypted=enc_access,
                oauth_refresh_token_encrypted=enc_refresh,
                oauth_expires_at=expires_at,
            )
            s.add(row)
        await s.commit()

    # Bounce the user back to the App Builder preview where the Supabase tab
    # will see the new tokens and show the project picker.
    return RedirectResponse(
        url=f"{PUBLIC_BASE_URL}/tasks/app-builder?{urlencode({'supabase_oauth_ok': slug})}",
        status_code=302,
    )
