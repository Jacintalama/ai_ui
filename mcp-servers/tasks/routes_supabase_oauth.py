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
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

import crypto_utils
from auth import AdminUser, current_admin
from db import session
from models import ProjectSupabase
from routes_projects import _require_role, _validate_slug

router = APIRouter()  # mounted at root; this module's paths are absolute

_KNOWN_REGIONS: list[str] = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "eu-west-1", "eu-west-2", "eu-west-3",
    "eu-central-1", "eu-central-2", "eu-north-1",
    "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
    "ap-northeast-2", "sa-east-1",
]

_PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9-]{2,40}$")

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
        await _require_role(s, slug, user.email, "owner")
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


async def _ensure_fresh_token(s, row) -> str:
    """Return a usable access_token, refreshing via OAuth if expired or near expiry."""
    if not row.oauth_access_token_encrypted:
        raise HTTPException(status_code=409, detail="Project is not connected via OAuth.")
    expires_at = row.oauth_expires_at
    needs_refresh = expires_at is None or expires_at <= datetime.now(timezone.utc) + timedelta(seconds=30)
    access = crypto_utils.decrypt(row.oauth_access_token_encrypted)
    if not needs_refresh:
        return access
    if not row.oauth_refresh_token_encrypted:
        raise HTTPException(status_code=401, detail="OAuth token expired and no refresh token. Re-connect Supabase.")
    refresh = crypto_utils.decrypt(row.oauth_refresh_token_encrypted)
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh},
            auth=(CLIENT_ID, CLIENT_SECRET),
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail=f"OAuth refresh failed (HTTP {resp.status_code}). Re-connect Supabase.",
        )
    tok = resp.json()
    new_access = tok.get("access_token")
    new_refresh = tok.get("refresh_token") or refresh  # may not always rotate
    expires_in = int(tok.get("expires_in", 3600))
    row.oauth_access_token_encrypted = crypto_utils.encrypt(new_access)
    row.oauth_refresh_token_encrypted = crypto_utils.encrypt(new_refresh)
    row.oauth_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
    row.updated_at = datetime.utcnow()
    await s.commit()
    return new_access


class SupabaseProjectListItem(BaseModel):
    ref: str
    name: str
    region: str | None = None
    organization_id: str | None = None
    is_linked: bool = False


@router.get("/api/projects/{slug}/supabase/oauth/projects",
            response_model=list[SupabaseProjectListItem])
async def list_oauth_projects(slug: str, user: AdminUser = Depends(current_admin)):
    """List the user's Supabase projects (via Management API).
    Owner-only on our project, requires the OAuth token."""
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None or not row.oauth_access_token_encrypted:
            raise HTTPException(status_code=409,
                                detail="Connect Supabase first (no OAuth token stored).")
        access = await _ensure_fresh_token(s, row)
        currently_linked = row.linked_project_ref

    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.get(
            "https://api.supabase.com/v1/projects",
            headers={"Authorization": f"Bearer {access}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Supabase API error (HTTP {resp.status_code}): {resp.text[:300]}",
        )
    data = resp.json() or []
    return [
        SupabaseProjectListItem(
            ref=p.get("id") or "",
            name=p.get("name") or "(unnamed)",
            region=p.get("region"),
            organization_id=p.get("organization_id"),
            is_linked=(p.get("id") == currently_linked),
        )
        for p in data
    ]


class LinkProjectRequest(BaseModel):
    project_ref: str = Field(min_length=10, max_length=40)


class LinkProjectResponse(BaseModel):
    project_ref: str
    project_name: str
    supabase_url: str


async def _link_project(s, row: ProjectSupabase, project_ref: str,
                        access: str) -> LinkProjectResponse:
    """Fetch project + anon key from Management API and persist them on `row`.

    Caller must have already validated slug + ownership and obtained a fresh
    access token. Commits via the supplied session.
    """
    headers = {"Authorization": f"Bearer {access}"}
    async with httpx.AsyncClient(timeout=15.0) as c:
        det = await c.get(f"https://api.supabase.com/v1/projects/{project_ref}",
                          headers=headers)
        if det.status_code == 404:
            raise HTTPException(status_code=404, detail="Project not found in your Supabase organization.")
        if det.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Supabase API: {det.status_code} — {det.text[:300]}")
        project = det.json()
        project_name = project.get("name") or project_ref

        keys = await c.get(f"https://api.supabase.com/v1/projects/{project_ref}/api-keys",
                           headers=headers)
        if keys.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Supabase keys API: {keys.status_code} — {keys.text[:300]}")
        anon_key = None
        for k in keys.json() or []:
            if k.get("name") == "anon" or k.get("api_key", "").startswith("eyJ"):
                anon_key = k.get("api_key")
                break
        if not anon_key:
            raise HTTPException(status_code=502, detail="No anon key found for this project.")

    supabase_url = f"https://{project_ref}.supabase.co"
    row.linked_project_ref = project_ref
    row.supabase_url = supabase_url
    row.anon_key_encrypted = crypto_utils.encrypt(anon_key)
    row.updated_at = datetime.utcnow()
    await s.commit()

    return LinkProjectResponse(
        project_ref=project_ref,
        project_name=project_name,
        supabase_url=supabase_url,
    )


@router.post("/api/projects/{slug}/supabase/oauth/link",
             response_model=LinkProjectResponse)
async def link_oauth_project(
    slug: str,
    body: LinkProjectRequest,
    user: AdminUser = Depends(current_admin),
):
    """Link a Supabase project: fetches its anon key + URL via Management API
    and stores them on project_supabase. Owner-only."""
    _validate_slug(slug)
    project_ref = body.project_ref.strip()
    if not project_ref or not project_ref.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid project_ref.")

    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None or not row.oauth_access_token_encrypted:
            raise HTTPException(status_code=409, detail="Connect Supabase first.")
        access = await _ensure_fresh_token(s, row)
        return await _link_project(s, row, project_ref, access)


def _sanitize_suggested_name(slug: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9-]", "-", slug).strip("-")
    if len(cleaned) < 2:
        cleaned = (cleaned + "-app")[:40]
    return cleaned[:40]


class AutoLinkLinked(BaseModel):
    action: Literal["linked"] = "linked"
    project_ref: str
    project_name: str
    supabase_url: str


class _PickProject(BaseModel):
    ref: str
    name: str
    region: str | None = None
    organization_id: str | None = None


class AutoLinkPick(BaseModel):
    action: Literal["pick"] = "pick"
    projects: list[_PickProject]


class _Org(BaseModel):
    slug: str
    name: str


class AutoLinkCreate(BaseModel):
    action: Literal["create"] = "create"
    organizations: list[_Org]
    regions: list[str]
    suggested_name: str


@router.post("/api/projects/{slug}/supabase/oauth/auto-link")
async def auto_link_oauth(
    slug: str,
    user: AdminUser = Depends(current_admin),
) -> AutoLinkLinked | AutoLinkPick | AutoLinkCreate:
    """Decide what to do after OAuth based on project count.

    - 0 projects -> action: "create" (frontend shows a create form)
    - 1 project  -> action: "linked" (auto-linked using `_link_project`)
    - 2+         -> action: "pick"   (frontend shows a picker)
    """
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None or not row.oauth_access_token_encrypted:
            raise HTTPException(status_code=409,
                                detail="Connect Supabase first (no OAuth token stored).")
        access = await _ensure_fresh_token(s, row)

        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.get(
                "https://api.supabase.com/v1/projects",
                headers={"Authorization": f"Bearer {access}"},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Supabase API error (HTTP {resp.status_code}): {resp.text[:300]}",
            )
        projects = resp.json() or []

        if len(projects) == 1:
            ref = projects[0].get("id") or ""
            return await _link_project(s, row, ref, access)

        if len(projects) >= 2:
            return AutoLinkPick(projects=[
                _PickProject(
                    ref=p.get("id") or "",
                    name=p.get("name") or "(unnamed)",
                    region=p.get("region"),
                    organization_id=p.get("organization_id"),
                )
                for p in projects
            ])

        # Zero projects -> need to create one.
        async with httpx.AsyncClient(timeout=15.0) as c:
            org_resp = await c.get(
                "https://api.supabase.com/v1/organizations",
                headers={"Authorization": f"Bearer {access}"},
            )
        if org_resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Supabase organizations API: {org_resp.status_code} — {org_resp.text[:300]}",
            )
        orgs = org_resp.json() or []
        return AutoLinkCreate(
            organizations=[_Org(slug=o.get("slug") or "",
                                name=o.get("name") or o.get("slug") or "(unnamed)")
                           for o in orgs],
            regions=list(_KNOWN_REGIONS),
            suggested_name=_sanitize_suggested_name(slug),
        )


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    region: str
    organization_id: str = Field(min_length=1)
    db_password: str = Field(min_length=12, max_length=72)


class CreateProjectResponse(BaseModel):
    action: Literal["creating"] = "creating"
    project_ref: str
    status: str


@router.post("/api/projects/{slug}/supabase/oauth/create-project",
             response_model=CreateProjectResponse)
async def create_oauth_project(
    slug: str,
    body: CreateProjectRequest,
    user: AdminUser = Depends(current_admin),
):
    """Create a brand-new Supabase project on behalf of the user.

    Returns immediately after the POST — provisioning happens asynchronously
    on Supabase's side (30-90s). Frontend polls /create-status to watch it.
    """
    _validate_slug(slug)
    if not _PROJECT_NAME_RE.match(body.name):
        raise HTTPException(status_code=400,
                            detail="Project name must be 2-40 chars, alphanumeric + dashes.")
    if body.region not in _KNOWN_REGIONS:
        raise HTTPException(status_code=400, detail="Unknown region.")

    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None or not row.oauth_access_token_encrypted:
            raise HTTPException(status_code=409, detail="Connect Supabase first.")
        access = await _ensure_fresh_token(s, row)

        payload = {
            "name": body.name,
            "organization_id": body.organization_id,
            "region": body.region,
            "plan": "free",
            "db_pass": body.db_password,
        }
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://api.supabase.com/v1/projects",
                headers={"Authorization": f"Bearer {access}",
                         "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code == 403:
            raise HTTPException(
                status_code=422,
                detail=("Your Supabase OAuth app doesn't have permission to "
                        "create projects. Open the Supabase dashboard, create "
                        "a project there, then come back and click 'Refresh "
                        "projects'."),
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Supabase create-project API: {resp.status_code} — {resp.text[:300]}",
            )
        created = resp.json() or {}
        ref = created.get("id") or created.get("ref") or ""
        if not ref:
            raise HTTPException(status_code=502,
                                detail="Supabase did not return a project_ref.")

        # Persist NOW so /create-status can poll. anon key + url come later.
        row.linked_project_ref = ref
        row.updated_at = datetime.utcnow()
        await s.commit()

    return CreateProjectResponse(
        project_ref=ref,
        status=created.get("status") or "COMING_UP",
    )


_TERMINAL_FAIL_STATUSES = {"INIT_FAILED", "REMOVED", "RESTORE_FAILED",
                           "PAUSE_FAILED", "UNKNOWN"}


class CreateStatusCreating(BaseModel):
    status: Literal["creating"] = "creating"
    message: str


class CreateStatusReady(BaseModel):
    status: Literal["ready"] = "ready"
    project_ref: str
    supabase_url: str
    anon_key_present: bool = True


class CreateStatusFailed(BaseModel):
    status: Literal["failed"] = "failed"
    message: str


@router.get("/api/projects/{slug}/supabase/oauth/create-status")
async def create_status(
    slug: str,
    user: AdminUser = Depends(current_admin),
) -> CreateStatusCreating | CreateStatusReady | CreateStatusFailed:
    """Polled by the frontend while a newly-created project is provisioning."""
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None or not row.oauth_access_token_encrypted:
            raise HTTPException(status_code=409, detail="Connect Supabase first.")
        ref = row.linked_project_ref
        if not ref:
            raise HTTPException(status_code=409, detail="No project being provisioned.")
        access = await _ensure_fresh_token(s, row)

        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.get(
                f"https://api.supabase.com/v1/projects/{ref}",
                headers={"Authorization": f"Bearer {access}"},
            )
        if resp.status_code == 404:
            return CreateStatusFailed(
                message="Project not found — it may have been deleted on Supabase.",
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Supabase API: {resp.status_code} — {resp.text[:300]}",
            )
        project = resp.json() or {}
        status = (project.get("status") or "").upper()

        if status == "ACTIVE_HEALTHY":
            # Auto-link now: project finished provisioning, so its anon key
            # is live. Reuse `_link_project` to fetch + persist.
            linked = await _link_project(s, row, ref, access)
            return CreateStatusReady(
                project_ref=linked.project_ref,
                supabase_url=linked.supabase_url,
                anon_key_present=True,
            )
        if status in _TERMINAL_FAIL_STATUSES:
            return CreateStatusFailed(
                message=f"Project provisioning failed (status={status}). "
                        "Try creating a new project on supabase.com directly.",
            )
        return CreateStatusCreating(
            message="Provisioning your Supabase project — usually 30-90s...",
        )


@router.delete("/api/projects/{slug}/supabase/oauth", status_code=204)
async def disconnect_oauth(slug: str, user: AdminUser = Depends(current_admin)):
    """Drop OAuth tokens + linked_project_ref. Manual config (URL/key/db_uri)
    stays put if previously set."""
    _validate_slug(slug)
    async with session() as s:
        await _require_role(s, slug, user.email, "owner")
        row = (await s.execute(
            select(ProjectSupabase).where(ProjectSupabase.slug == slug)
        )).scalar_one_or_none()
        if row is None:
            return None
        row.oauth_access_token_encrypted = None
        row.oauth_refresh_token_encrypted = None
        row.oauth_expires_at = None
        row.linked_project_ref = None
        row.oauth_org_slug = None
        await s.commit()
    return None
