"""A person's own app code, over HTTP, for the assistant's tool.

Internal only and mounted once, like every other endpoint that acts for a
named user. The caller names a slug, so membership is decided here on every
call and never inferred from an earlier one.

Reading is safe on its own. Changing is not, so it is two calls: propose
writes a token and touches nothing, and apply consumes that token and hands
the work to the ordinary App Builder enhance, which already smoke tests the
result and rolls the app back if it broke.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

import app_code_access
from app_code_access import CodeAccessError
from code_proposals import ProposalError, consume_proposal, create_proposal
from db import session
from routes_gateway import _require_internal
from routes_projects import TEAM_EMAIL, _user_can_see_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/code")

#: Tests point this at a tmp_path. Production leaves it None so
#: app_code_access uses CLAUDE_WORKSPACE.
_apps_root_override: Path | None = None


async def _can_see(user_email: str, slug: str) -> bool:
    """Membership, per call. A seam so tests can drive the endpoints
    without a database."""
    async with session() as s:
        return await _user_can_see_project(s, slug, user_email)


async def _spawn_enhance(user_email: str, slug: str, prompt: str):
    """A seam over the builder, so a test can prove which slug was used
    without starting a real build. Imported lazily for the same reason
    _create_and_spawn_enhance imports its own dependencies lazily: the
    builder module pulls in the execution stack."""
    from routes_aiuibuilder import _create_and_spawn_enhance
    return await _create_and_spawn_enhance(user_email, slug, prompt)


async def _require_member(user_email: str, slug: str) -> None:
    if not await _can_see(user_email, slug):
        raise HTTPException(status_code=403, detail="That is not your app.")


class ProposeIn(BaseModel):
    user_email: str
    slug: str
    description: str


class ApplyIn(BaseModel):
    user_email: str
    token: str
    # Accepted and ignored on purpose: a caller may send it, and the slug
    # that gets built is always the one stored with the proposal.
    slug: str | None = None


@router.get("/apps")
async def list_apps(user_email: str,
                    x_internal_secret: str = Header(default="")) -> dict:
    """The apps this person can see.

    The team bucket is included because the read gate includes it. A list
    narrower than the gate would hide an app the person can open.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        rows = (await s.execute(
            text("SELECT DISTINCT slug FROM tasks.project_members"
                 " WHERE user_email IN (:email, :team) ORDER BY slug"),
            {"email": user_email, "team": TEAM_EMAIL},
        )).all()
    return {"apps": [r[0] for r in rows]}


@router.get("/file")
async def read_one_file(user_email: str, slug: str, path: str,
                        x_internal_secret: str = Header(default="")) -> dict:
    _require_internal(x_internal_secret)
    await _require_member(user_email, slug)
    try:
        text_out = app_code_access.read_file(
            slug, path, apps_root=_apps_root_override)
    except CodeAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return {"slug": slug, "path": path, "text": text_out}


@router.get("/search")
async def search_one_app(user_email: str, slug: str, query: str,
                         x_internal_secret: str = Header(default="")) -> dict:
    _require_internal(x_internal_secret)
    await _require_member(user_email, slug)
    try:
        hits = app_code_access.search_files(
            slug, query, apps_root=_apps_root_override)
    except CodeAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return {"slug": slug, "matches": hits}


@router.post("/propose")
async def propose(body: ProposeIn,
                  x_internal_secret: str = Header(default="")) -> dict:
    """Write down what would change. Nothing happens yet.

    create_proposal owns the rules about an empty or oversized description,
    so they are not repeated here: a second copy would drift from the one
    the storage layer actually enforces.
    """
    _require_internal(x_internal_secret)
    await _require_member(body.user_email, body.slug)
    try:
        token = await create_proposal(body.user_email, body.slug,
                                      body.description)
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return {"token": token, "slug": body.slug,
            "description": body.description.strip()}


@router.post("/apply")
async def apply(body: ApplyIn,
                x_internal_secret: str = Header(default="")) -> dict:
    """Do the thing the person just approved, and nothing else."""
    _require_internal(x_internal_secret)
    try:
        proposal = await consume_proposal(body.user_email, body.token)
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    # The slug is the proposal's, never the caller's. _create_and_spawn_enhance
    # does the editor-or-owner check, the per-slug lock and the 409, so those
    # are deliberately not repeated here.
    task_id, slug = await _spawn_enhance(
        body.user_email, proposal["slug"], proposal["description"])
    return {"task_id": task_id, "slug": slug,
            "description": proposal["description"]}
