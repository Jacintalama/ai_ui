"""Automations: the rows a person sets up, and the webhook that fires one.

    GET    /api/tasks/automations              this person's rules, with runs
    POST   /api/tasks/automations              make one
    PATCH  /api/tasks/automations/{id}         rename, pause, change
    DELETE /api/tasks/automations/{id}
    POST   /api/tasks/automations/{id}/run     run it now, on a test payload
    POST   /api/tasks/hooks/{token}            the trigger: anything may call

The signed-in routes go through the gateway with X-User-Email like every
other page route. The hook is public by design, and the token in its path
is the secret: it is unguessable, shown only to the owner, and a new one
can be issued at any time. Nothing about the hook's body is trusted: it
is handed to the agent as data, under a line saying so.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import automations
from auth import CurrentUser, current_user
from routes_agent_turn import _agents_for
from routes_automation import find_agent

logger = logging.getLogger("routes_automations")
router = APIRouter()

#: Where hook URLs point. The public host, so a copied URL works from
#: anywhere.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://ai-ui.coolestdomain.win")
#: How long a caller that asked to wait may wait for the answer.
WAIT_SECONDS = 420.0


def _base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", PUBLIC_BASE_URL)


class AutomationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    #: The agent's name or id.
    agent: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=automations.MAX_INSTRUCTION_CHARS + 1)
    deliver_to: str = automations.DELIVER_CHAT
    #: webhook (the default, and what every rule was before 2026-10-29)
    #: or email. An email rule must also say WHICH emails.
    trigger: str = automations.TRIGGER_WEBHOOK
    #: A Gmail search ("from:boss@x.com is:unread"). Matching is
    #: Gmail's job, not ours. Required for an email trigger and
    #: ignored for a webhook.
    trigger_query: str = Field(default="", max_length=500)


class AutomationPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    agent: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=automations.MAX_INSTRUCTION_CHARS + 1)
    deliver_to: str | None = None
    enabled: bool | None = None
    trigger_query: str | None = Field(default=None, max_length=500)
    #: True issues a fresh token, which retires the old URL at once.
    new_token: bool = False


class RunIn(BaseModel):
    payload: dict | list | str | None = None


def _shown(a: dict, agents: list[dict]) -> dict:
    out = dict(a)
    agent = next((x for x in agents if x.get("id") == a.get("agent_id")), None)
    out["agent_name"] = (agent or {}).get("name") or a.get("agent_id")
    out["agent_missing"] = agent is None
    out["hook_url"] = automations.hook_url(a["hook_token"], _base())
    return out


async def _agent_for(email: str, wanted: str, agents: list[dict] | None = None) -> dict:
    agents = agents if agents is not None else await _agents_seam(email)
    agent = find_agent(agents, wanted)
    if agent is None:
        names = sorted(str(a.get("name") or "") for a in agents
                       if isinstance(a, dict) and a.get("name"))
        raise HTTPException(status_code=404, detail=(
            f"No agent called {wanted.strip()!r}. "
            + ("Your agents: " + ", ".join(names) + "." if names else "You have no agents yet.")))
    return agent


#: Seams.
_agents_seam = _agents_for
_spawn = asyncio.create_task


async def _fire(automation: dict, payload, agent_name: str) -> dict:
    import automation_runner
    return await automation_runner.fire(automation, payload, agent_name)


async def _cursors_for(email: str) -> dict:
    """{automation_id: {checked_at, last_error}} for this person's email
    rules. Never raises: the page must still list the rules when the cursor
    table cannot be read, just without the "last looked" line."""
    try:
        from sqlalchemy import text as sql_text
        from db import session
        async with session() as s:
            rows = (await s.execute(sql_text(
                "SELECT automation_id, checked_at, last_error "
                "  FROM tasks.automation_email_cursor WHERE user_email = :e"),
                {"e": email})).mappings().all()
        return {str(r["automation_id"]): {
            "checked_at": automations._iso(r["checked_at"]),
            "last_error": r["last_error"] or ""} for r in rows}
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read the email trigger cursors",
                       exc_info=True)
        return {}


_fire_seam = _fire
_cursors_seam = _cursors_for


# --- the rows ------------------------------------------------------------------

@router.get("/automations")
async def list_automations(user: CurrentUser = Depends(current_user)) -> dict:
    agents = await _agents_seam(user.email)
    rows = await automations.list_for(user.email)
    out = []
    # When each email rule last looked, and why it could not (2026-10-29).
    # Without it an email rule on the page is a name and nothing a person
    # can check: a rule that has quietly stopped looking, because a token
    # was revoked, looks exactly like a rule nobody has emailed.
    cursors = await _cursors_seam(user.email)
    for a in rows:
        shown = _shown(a, agents)
        shown["runs"] = await automations.runs(user.email, a["id"])
        if a.get("trigger") == automations.TRIGGER_EMAIL:
            shown.update(cursors.get(str(a["id"])) or
                         {"checked_at": None, "last_error": ""})
        out.append(shown)
    return {"automations": out}


@router.post("/automations")
async def create_automation(body: AutomationIn,
                            user: CurrentUser = Depends(current_user)) -> dict:
    problem = automations.problem_with(body.name, body.instructions,
                                       body.deliver_to, body.trigger,
                                       body.trigger_query)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    agents = await _agents_seam(user.email)
    agent = await _agent_for(user.email, body.agent, agents)
    try:
        row = await automations.create(user.email, body.name, agent["id"],
                                       body.instructions, body.deliver_to,
                                       body.trigger, body.trigger_query)
    except automations.TooMany:
        raise HTTPException(
            status_code=409,
            detail=f"You have {automations.MAX_PER_PERSON} automations, which is "
                   "the limit. Delete one to make another.")
    return _shown(row, agents)


@router.patch("/automations/{automation_id}")
async def update_automation(automation_id: str, body: AutomationPatch,
                            user: CurrentUser = Depends(current_user)) -> dict:
    current = await automations.get(user.email, automation_id)
    if current is None:
        raise HTTPException(status_code=404, detail="No such automation.")
    agents = await _agents_seam(user.email)
    changes: dict = {}
    if body.name is not None:
        changes["name"] = automations.clean_name(body.name)
    if body.instructions is not None:
        changes["instructions"] = body.instructions.strip()
    if body.deliver_to is not None:
        changes["deliver_to"] = body.deliver_to
    if body.enabled is not None:
        changes["enabled"] = bool(body.enabled)
    if body.trigger_query is not None:
        changes["trigger_query"] = body.trigger_query.strip()
    if body.agent is not None:
        changes["agent_id"] = (await _agent_for(user.email, body.agent, agents))["id"]
    if body.new_token:
        changes["hook_token"] = automations.make_token()
    merged = dict(current, **changes)
    problem = automations.problem_with(merged["name"], merged["instructions"],
                                       merged["deliver_to"], merged["trigger"],
                                       merged.get("trigger_query", ""))
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    row = await automations.update(user.email, automation_id, changes) if changes else current
    if row is None:
        raise HTTPException(status_code=404, detail="No such automation.")
    return _shown(row, agents)


@router.delete("/automations/{automation_id}")
async def delete_automation(automation_id: str,
                            user: CurrentUser = Depends(current_user)) -> dict:
    return {"deleted": await automations.delete(user.email, automation_id)}


@router.post("/automations/{automation_id}/run")
async def run_automation(automation_id: str, body: RunIn,
                         user: CurrentUser = Depends(current_user)) -> dict:
    """Run it now, on a payload of the person's choosing, and wait."""
    a = await automations.get(user.email, automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="No such automation.")
    agents = await _agents_seam(user.email)
    agent = next((x for x in agents if x.get("id") == a["agent_id"]), None)
    if agent is None:
        raise HTTPException(status_code=409, detail="This automation's agent no longer exists. Pick another.")
    a["user_email"] = user.email
    return await _fire_seam(a, body.payload, agent.get("name") or a["agent_id"])


# --- the hook ---------------------------------------------------------------------

async def _payload_of(request: Request):
    """Whatever was posted: JSON as JSON, a form as a dict, anything else
    as text. Never raises on a body it cannot read."""
    ctype = (request.headers.get("content-type") or "").lower()
    raw = await request.body()
    if not raw:
        return dict(request.query_params) or None
    if "json" in ctype:
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return raw.decode("utf-8", "replace")
    if "form" in ctype:
        try:
            form = await request.form()
            return {k: str(v) for k, v in form.items()}
        except Exception:                                   # noqa: BLE001
            return raw.decode("utf-8", "replace")
    return raw.decode("utf-8", "replace")


@router.post("/hooks/{token}")
async def hook(token: str, request: Request) -> dict:
    """The trigger. Returns at once with 202 and the run is done in the
    background; `?wait=1` waits for the answer and returns it."""
    a = await automations.by_token(token)
    if a is None or not a.get("enabled"):
        # The same answer for a wrong token and a paused rule, so the URL
        # says nothing about which it was.
        raise HTTPException(status_code=404, detail="No such hook.")
    # The row carries its owner; by_token reads it without the owner's
    # session, so it is put on the dict here from the row itself.
    payload = await _payload_of(request)
    wait = str(request.query_params.get("wait", "")).lower() in ("1", "true", "yes")
    email = a.get("user_email") or ""
    if not email:
        # row_of leaves the owner out on purpose for the page; the token
        # lookup adds it (see automations._by_token_row). Without it the
        # agent cannot be found, so refuse rather than guess.
        raise HTTPException(status_code=404, detail="No such hook.")
    agents = await _agents_seam(email)
    agent = next((x for x in agents if x.get("id") == a["agent_id"]), None)
    if agent is None:
        import automation_runner
        await automations.record_run(email, a["id"], automation_runner.STATUS_FAILED,
                                     automations.trigger_summary(payload),
                                     "This automation's agent no longer exists.", "none")
        raise HTTPException(status_code=409, detail="This automation's agent no longer exists.")
    name = agent.get("name") or a["agent_id"]
    if wait:
        try:
            return dict(await asyncio.wait_for(_fire_seam(a, payload, name), WAIT_SECONDS),
                        id=a["id"])
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="The agent is still working; the result will be delivered.")
    _spawn(_fire_seam(a, payload, name))
    return {"id": a["id"], "status": "accepted"}
