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
from fastapi import APIRouter, Depends, Header, HTTPException

import agent_activity
from agent_runner import _owui_user_id_for
from agent_templates import TEMPLATES
from auth import CurrentUser, current_user
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


# ---------------------------------------------------------------------------
# What this person can actually use.
#
# The form used to offer a hardcoded list of 7 tools to every account. Nine
# users could tick the Gmail box; one of them had a Gmail token. For the
# other eight, checking it did nothing -- the box lied. Everything below
# answers, per person, what would really work.
# ---------------------------------------------------------------------------

#: Fallback labels for the tools the platform ships with today, matching the
#: names already shown on the agent form (static/agents.html). A tool with
#: no entry here falls back to its own `name` column -- see _label_for.
_LABELS = {
    "server:mcp-proxy": "Your connected apps",
    "gmail": "Gmail",
    "calendar": "Calendar",
    "gdrive": "Drive",
    "documents": "Documents",
    "excel_creator": "Excel",
    "executive_dashboard": "Dashboard",
    "remember": "Memory",
}

#: Native tool id -> the public table that proves THIS user connected it.
#: Every other native tool (documents, excel_creator, executive_dashboard,
#: remember) needs nothing and is always available.
_TOKEN_TABLES = {
    "gmail": "gmail_tokens",
    "calendar": "calendar_tokens",
    "gdrive": "gdrive_tokens",
}

#: Where every connection in this module is made -- gmail/calendar/gdrive and
#: the Connect Your Own App providers behind server:mcp-proxy alike.
# Opens the Connections panel on the Agents page itself. The previous
# value pointed at /tasks/static/connections.html, which has never
# existed, so every Connect link went nowhere.
CONNECT_URL = "#connections"

#: id -> public.tool.name, refreshed by the most recent real call to
#: _installed_tool_ids. A test that mocks _installed_tool_ids leaves this
#: empty, which is exactly why _label_for still has to cope with an id that
#: is in neither this nor _LABELS.
_tool_names: dict = {}


async def _installed_tool_ids() -> list:
    """Every tool id installed on this platform, from public.tool.

    Not a hardcoded array: a tool an admin installs later must show up here
    on its own, with no code change to this module. Ordered by id so the
    list is stable across requests.
    """
    import asyncpg

    conn = await asyncpg.connect(_database_url())
    try:
        rows = await conn.fetch("SELECT id, name FROM public.tool ORDER BY id")
    finally:
        await conn.close()
    _tool_names.update({r["id"]: r["name"] for r in rows if r["name"]})
    return [r["id"] for r in rows]


async def _connected_providers(email: str) -> set:
    """Everything `email` has connected right now, by provider id.

    One connection, one query, covering the three token tables plus
    tasks.user_connections in a single UNION ALL, every branch scoped to
    `email` in the same WHERE clause -- there is no branch here a caller
    could leave unscoped, only whether the whole query is asked for the
    right person.

    Fails toward "nothing connected" on any read error, never toward
    "connected": a tool wrongly reported as unconnected is a nag the user
    can click through; a tool wrongly reported as connected is one an agent
    will pick and then fail to actually run.
    """
    import asyncpg

    query = """
        SELECT 'gmail' AS provider
          FROM public.gmail_tokens WHERE user_email = $1
        UNION ALL
        SELECT 'calendar'
          FROM public.calendar_tokens WHERE user_email = $1
        UNION ALL
        SELECT 'gdrive'
          FROM public.gdrive_tokens WHERE user_email = $1
        UNION ALL
        SELECT provider
          FROM tasks.user_connections WHERE email = $1
    """
    try:
        conn = await asyncpg.connect(_database_url())
    except Exception:
        logger.warning("could not reach the database to read connection state")
        return set()
    try:
        rows = await conn.fetch(query, email)
    except Exception:
        logger.warning("could not read connection state", exc_info=True)
        return set()
    finally:
        await conn.close()
    return {r["provider"] for r in rows}


def _label_for(tool_id: str) -> str:
    """A human label for `tool_id`: the map above, then its own DB name,
    then the bare id -- always something, never empty."""
    return _LABELS.get(tool_id) or _tool_names.get(tool_id) or tool_id


async def tools_for_email(email: str) -> dict:
    """Every tool the agent form may offer `email`, and whether ticking it
    would actually do anything right now.

    Never raises: a broken read here must not stop the Agents page from
    loading. Both halves fail toward the emptiest honest answer -- no tools,
    nothing connected -- rather than guessing a tool is ready when it might
    not be.
    """
    try:
        installed = await _installed_tool_ids()
    except Exception:
        logger.warning("could not list installed tools", exc_info=True)
        installed = []

    try:
        connected = await _connected_providers(email)
    except Exception:
        logger.warning("could not read connection state", exc_info=True)
        connected = set()

    tools = []
    for tool_id in installed:
        needs_connection = tool_id in _TOKEN_TABLES
        tools.append({
            "id": tool_id,
            "label": _label_for(tool_id),
            "connected": (tool_id in connected) if needs_connection else True,
            "connect_url": CONNECT_URL if needs_connection else None,
        })

    # server:mcp-proxy is not a row in public.tool: it fronts whatever the
    # user connected under Connect Your Own App (ClickUp, Trello, GitHub,
    # Notion, n8n).
    #
    # ALWAYS listed, exactly like Gmail, and greyed when nothing is behind
    # it. Offering it only once something was connected read as the safer
    # choice and was the more dangerous one: nobody on this platform has
    # connected a proxy app yet, so the umbrella vanished from the form
    # entirely, and the starter agent Ada uses precisely this tool. Editing
    # Ada would have saved it with the checkbox that was never rendered
    # unticked, silently stripping the only tool it has.
    tools.append({
        "id": "server:mcp-proxy",
        "label": _LABELS["server:mcp-proxy"],
        "connected": bool(connected - set(_TOKEN_TABLES)),
        "connect_url": CONNECT_URL,
    })

    return {"tools": tools}


@router.get("/activity")
async def activity(user: CurrentUser = Depends(current_user)) -> dict:
    """Which of the caller's agents are working right now, and how long the
    last run of each took.

    Scoped to the caller, the same way the tools route is. An admin's model
    listing carries every user's agents, and one person's agent working is
    not another person's agent working.
    """
    return {"activity": await agent_activity.activity_for(user.email)}


@router.get("/templates")
async def templates() -> dict:
    """The starter agents, for a user who has none.

    Deleting both agents used to be a dead end: they are seeded once and the
    record of that seeding makes sure they never come back on their own,
    which is what makes a delete stick. This is the way back, and it is a
    deliberate act rather than something that happens to you.

    No caller identity needed: these are the same two definitions for
    everybody, and creating one goes through the ordinary create form so the
    person sees what they are making.
    """
    return {"templates": [
        {"slug": t["slug"], "name": t["name"],
         "instructions": t["instructions"], "tool_ids": list(t["tool_ids"])}
        for t in TEMPLATES
    ]}


@router.get("/tools")
async def list_tools(user: CurrentUser = Depends(current_user)) -> dict:
    """What the agent form may offer the signed-in caller right now."""
    return await tools_for_email(user.email)
