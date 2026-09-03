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
from code_proposals import (ProposalError, consume_proposal, create_proposal,
                            restore_proposal)
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
    # Membership is a database fact, and the database keeps rows for
    # things that are not apps: the cron scheduler writes items rows
    # with action_type BUILD, and rows survive an app being deleted.
    # Without this, a slug named directly by a model reaches the
    # builder, which finds that same row as its source task and spawns
    # a real agent against a directory that does not exist. Checked
    # after membership so a non-member still learns nothing.
    try:
        app_code_access.app_dir(slug, apps_root=_apps_root_override)
    except CodeAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc


class ProposeIn(BaseModel):
    user_email: str
    slug: str
    description: str


class ApplyIn(BaseModel):
    user_email: str
    token: str


@router.get("/apps")
async def list_apps(user_email: str,
                    x_internal_secret: str = Header(default="")) -> dict:
    """The apps this person can see."""
    _require_internal(x_internal_secret)
    async with session() as s:
        # Both halves of the read gate in routes_projects._user_can_see_project:
        # a membership row, or a build task this person owns. Listing only the
        # first would hide an app they can open, which happens for real because
        # the membership grant after a build fails open like every other step
        # in that pipeline.
        rows = (await s.execute(
            text("SELECT DISTINCT slug FROM ("
                 "  SELECT slug FROM tasks.project_members"
                 "   WHERE user_email IN (:email, :team)"
                 "  UNION"
                 "  SELECT built_app_slug AS slug FROM tasks.items"
                 "   WHERE built_app_slug IS NOT NULL"
                 "     AND assignee_email IN (:email, :team)"
                 ") AS visible ORDER BY slug"),
            {"email": user_email, "team": TEAM_EMAIL},
        )).all()

    # Disk truth, not just a database row. tasks.items carries BUILD rows the
    # cron scheduler wrote (sched-...) that were never apps and have no
    # directory, and it keeps rows for apps that were later deleted. Offering
    # either to a model invites somebody to approve a change to a thing that
    # cannot be changed, and the builder would spawn a real agent against a
    # path that does not exist. app_dir answers exactly this and rejects a
    # malformed slug for free.
    visible = []
    for row in rows:
        try:
            app_code_access.app_dir(row[0], apps_root=_apps_root_override)
        except CodeAccessError:
            continue
        visible.append(row[0])
    return {"apps": visible}


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
    return {
        "token": token, "slug": body.slug,
        # Must equal what create_proposal stored. apply executes the stored
        # text, so any divergence means the person approves one change and
        # another one runs. Held by
        # test_what_the_person_approves_is_what_will_run.
        "description": body.description.strip(),
    }


@router.post("/apply")
async def apply(body: ApplyIn,
                x_internal_secret: str = Header(default="")) -> dict:
    """Do the thing the person just approved, and nothing else.

    There is no slug field to send. The app is whichever one the proposal
    was written against, so a caller cannot point an approved change at a
    different app. An extra slug in the body is ignored.
    """
    _require_internal(x_internal_secret)
    try:
        proposal = await consume_proposal(body.user_email, body.token)
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    # The slug is the proposal's, never the caller's. _create_and_spawn_enhance
    # does the editor-or-owner check, the per-slug lock and the 409, so those
    # are deliberately not repeated here.
    try:
        task_id, slug = await _spawn_enhance(
            body.user_email, proposal["slug"], proposal["description"])
    except HTTPException as exc:
        # These three are raised before the builder inserts anything, so no
        # work began and the person's approval should still be good. Any
        # other failure keeps the token spent: restoring one after work may
        # have started could run the same change twice.
        if exc.status_code in (403, 404, 409):
            # Best effort. Giving the approval back is a kindness, and it must
            # never replace the status the person actually needs to see: a 409
            # says "one is already running, try shortly" and a 500 says
            # nothing. Same rule as every post-processing step in the build
            # pipeline, which fails open rather than failing the build.
            try:
                await restore_proposal(body.user_email, body.token)
            except Exception:                                   # noqa: BLE001
                logger.warning("could not give the approval back for %s",
                               proposal["slug"], exc_info=True)
        raise
    return {"task_id": task_id, "slug": slug,
            "description": proposal["description"]}
