"""Give a new user their own copies of the starter agents, once.

Scout and Triage used to be two rows in one account, shared out with a
wildcard read grant: everybody saw the same two agents and only their owner
could change or delete them. agent_templates.TEMPLATES now holds the recipe
instead of a live row, and this module is what turns that recipe into a
private copy the first time each person is seen.

Idempotence lives in tasks.agent_seed (migration 043), one row per email,
written after the attempt. Without it, a user who deletes both agents would
get them back on the next page load and could never be rid of them. Reading
that row is the whole feature; the rest of this file is plumbing to create
the models themselves.

Nothing here may raise past seed_for_email: a broken seeding path must never
stop the Agents page from listing whatever the person already has.
"""
import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Header, HTTPException

from agent_runner import _owui_user_id_for
from agent_templates import TEMPLATES
from owui_token import mint_owui_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents")

#: Long enough to create two models well within one request, short enough
#: that a leaked value would not matter for long. Never logged or stored.
SEED_TOKEN_TTL_SECONDS = 60


def _base_url() -> str:
    return os.environ.get("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _default_model() -> str:
    """The platform default, read at call time so tests can monkeypatch it.

    Falls back to gpt-4o-mini, which is what both live agents already use.
    """
    return os.environ.get("AGENT_DEFAULT_MODEL", "gpt-4o-mini")


async def _already_seeded(email: str) -> bool:
    """Whether tasks.agent_seed already has this email.

    Raw asyncpg because this table has no ORM model in this service, the same
    approach routes_gateway._owui_user_id_for takes for public."user".
    """
    import asyncpg

    conn = await asyncpg.connect(_database_url())
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM tasks.agent_seed WHERE user_email = $1", email)
    finally:
        await conn.close()
    return row is not None


async def _mark_seeded(email: str) -> None:
    """Record the attempt. Called once per email, ever.

    ON CONFLICT DO NOTHING rather than assuming this is the only writer: two
    concurrent first requests for the same brand new user are possible, and
    the second one racing here must not raise.
    """
    import asyncpg

    conn = await asyncpg.connect(_database_url())
    try:
        await conn.execute(
            "INSERT INTO tasks.agent_seed (user_email) VALUES ($1) "
            "ON CONFLICT (user_email) DO NOTHING", email)
    finally:
        await conn.close()


async def _create_model(token: str, body: dict) -> tuple[int, object]:
    """One call to Open WebUI's /api/v1/models/create, as the given user.

    Returns (status_code, parsed_body_or_text). Split out so tests can stand
    in for it without an HTTP server.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{_base_url()}/api/v1/models/create",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=body)
    try:
        parsed = r.json()
    except ValueError:
        parsed = r.text
    return r.status_code, parsed


def _new_agent_id(slug: str) -> str:
    return f"agent-{slug}-{uuid.uuid4().hex[:4]}"


def _body_for(template: dict, agent_id: str) -> dict:
    """The create payload for one template, scoped to nobody but its owner.

    access_grants is always empty: a copy belongs to one person, and ending
    the old wildcard-share is the reason this feature exists.
    """
    return {
        "id": agent_id,
        "name": template["name"],
        "base_model_id": _default_model(),
        "meta": {"toolIds": template["tool_ids"]},
        "params": {"system": template["instructions"]},
        "access_grants": [],
        "is_active": True,
    }


def _is_duplicate_id_error(status: int, result: object) -> bool:
    if status != 401:
        return False
    detail = result.get("detail") if isinstance(result, dict) else result
    return "already registered" in str(detail).lower()


async def _create_one(token: str, template: dict) -> bool:
    """Create one template's copy. One retry with a fresh id suffix on a
    collision, then give up on this template and let the caller move on to
    the next one."""
    for _ in range(2):
        body = _body_for(template, _new_agent_id(template["slug"]))
        status, result = await _create_model(token, body)
        if status == 200:
            return True
        if not _is_duplicate_id_error(status, result):
            logger.warning(
                "could not create starter agent %s: status=%s",
                template["slug"], status)
            return False
    logger.warning(
        "could not create starter agent %s: id collided twice",
        template["slug"])
    return False


async def seed_for_email(email: str) -> dict:
    """Give this email its own copies of every template, once.

    Fails open: any exception anywhere in this path returns the same
    do-nothing result a caller would see if seeding had simply not run yet.
    """
    try:
        if await _already_seeded(email):
            return {"seeded": False, "created": 0}

        user_id = await _owui_user_id_for(email)
        if not user_id:
            # No account behind this email. Nothing was attempted, so there
            # is nothing to record; a real account under this address later
            # should still get seeded rather than being marked done here.
            return {"seeded": False, "created": 0}

        token = mint_owui_token(user_id, SEED_TOKEN_TTL_SECONDS)

        created = 0
        for template in TEMPLATES:
            if await _create_one(token, template):
                created += 1

        # Written after the attempt, whether or not every template made it,
        # so a partial failure is not retried on every page load.
        await _mark_seeded(email)
        return {"seeded": True, "created": created}
    except Exception:                                   # noqa: BLE001
        # Never surface the exception's own text: it can carry request
        # details, and this project has already leaked a token that way.
        logger.error("agent seeding failed", exc_info=True)
        return {"seeded": False, "created": 0}


@router.post("/seed")
async def seed(x_cron_secret: str = Header(default=""),
               x_user_email: str = Header(default="")) -> dict:
    """Seed the caller's own account. There is no operator path here: a copy
    belongs to one person, so there is no other user to target. x_cron_secret
    is accepted only to keep this route's shape close to
    routes_schedules._resolve_caller; it is not used to authenticate.
    """
    if not x_user_email:
        raise HTTPException(status_code=400, detail="Missing X-User-Email")
    return await seed_for_email(x_user_email)
