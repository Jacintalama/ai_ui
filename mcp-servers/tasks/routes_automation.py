"""Run an agent from outside (2026-10-27): n8n first of all.

    POST /api/tasks/agents/run
    Authorization: Bearer iok_...
    {"agent": "Ada", "message": "What is due this week?"}

The key is one the person made on the Agents page (automation_keys); it
names whose agents may run, the way X-User-Email does everywhere else. The
agent is found by id or by name among that person's own agents, and runs
exactly as it does from Discord: the same turn, brief, skills, memory and
tools (routes_agent_turn._run_turn), on the automation surface, where only
an agent set to `all` may change things. Nobody is watching, so an agent
set to ask has nobody to ask and reads instead.

The answer comes back in the response. A workflow that cannot wait out a
long turn sends `callback_url` instead: the call returns at once with an
id, and the result is POSTed to that URL when the agent finishes. The URL
has to be public: anything on this box or a private network is refused,
because a key holder must not be able to aim this service at its own
internal routes.

The key routes below are for the Agents page and need a signed-in person.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import agent_access
import automation_keys
from auth import CurrentUser, current_user
from routes_agent_turn import _agents_for, _run_turn

logger = logging.getLogger("routes_automation")
router = APIRouter(prefix="/agents")

#: The most one automation message may carry. A workflow pasting a whole
#: mailbox in would spend the turn's context on it before the agent spoke.
MAX_MESSAGE_CHARS = 20_000
#: How many automation runs this process serves at once. The box has 3.8GB
#: and a turn can run tools; a workflow firing on every email must queue
#: here rather than start twenty turns together.
CONCURRENCY = max(1, int(os.environ.get("AUTOMATION_CONCURRENCY", "2")))
#: How long a callback POST may take, and how many times it is tried.
CALLBACK_TIMEOUT_SECONDS = 30.0
CALLBACK_TRIES = 3

STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_ACCEPTED = "accepted"

NO_KEY = ("Send an automation key: Authorization: Bearer iok_... "
          "Make one on the Agents page under Automation.")
BAD_KEY = "That automation key is not valid or has been revoked."
TURN_FAILED = "The agent could not finish this run."

_slots = asyncio.Semaphore(CONCURRENCY)


# --- who is calling ----------------------------------------------------------

async def _email_from(authorization: str) -> str:
    """The owner of the key in the Authorization header, or 401."""
    token = ""
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail=NO_KEY)
    email = await automation_keys.email_for(token)
    if not email:
        raise HTTPException(status_code=401, detail=BAD_KEY)
    return email


def find_agent(agents: list[dict], wanted: str) -> dict | None:
    """The agent with this id, or failing that this name, case blind.
    Exact only: "Ad" must not run Ada from a workflow nobody is watching."""
    w = str(wanted or "").strip()
    if not w:
        return None
    for a in agents:
        if isinstance(a, dict) and str(a.get("id") or "") == w:
            return a
    low = w.lower()
    hits = [a for a in agents if isinstance(a, dict)
            and str(a.get("name") or "").strip().lower() == low]
    return hits[0] if len(hits) == 1 else None


# --- the callback URL -----------------------------------------------------------

def _private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


async def callback_problem(url: str) -> str:
    """Why this callback URL cannot be used, or "" when it can: http or
    https, a host name, and every address it resolves to public."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return "The callback URL could not be read."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "The callback URL must start with http:// or https:// and name a host."
    host = parts.hostname
    if host.lower() in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return "The callback URL must be reachable from the internet."
    try:
        addrs = await asyncio.get_running_loop().run_in_executor(None, _resolve_seam, host)
    except Exception:                                       # noqa: BLE001
        return "The callback host could not be found."
    if not addrs or any(_private(a) for a in addrs):
        return "The callback URL must be reachable from the internet."
    return ""


_resolve_seam = _resolve


# --- the run -----------------------------------------------------------------------

class RunIn(BaseModel):
    #: The agent's id (agent-ada-1a2b) or its name (Ada).
    agent: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    #: Set it and the call returns at once; the result is POSTed here.
    callback_url: str | None = Field(default=None, max_length=2000)


async def _run(email: str, agent: dict, message: str) -> dict:
    """One turn, as this agent, for this automation. Never raises: a
    workflow reads a status, not a stack trace."""
    try:
        async with _slots:
            out = await _run_turn_seam(
                email, agent["id"], [{"role": "user", "content": message}],
                brief=True, surface=agent_access.SURFACE_AUTOMATION)
        pending = isinstance(out.get("pending"), dict) and bool(out["pending"].get("calls"))
        notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
        if pending:
            # Cannot happen on this surface (ask reads), but the shape is
            # the turn's to define, so it is handled rather than assumed.
            notes.append("The agent stopped to ask for approval, which an "
                         "automation cannot give.")
        return {"status": STATUS_DONE, "answer": str(out.get("answer") or ""),
                "notes": notes}
    except HTTPException as exc:
        # The turn's own sentence for a known case: the agent is gone, or is
        # on a model that cannot run an agent. Worth passing on as it is.
        return {"status": STATUS_FAILED, "answer": "",
                "notes": [str(exc.detail) if exc.detail else TURN_FAILED]}
    except Exception:                                       # noqa: BLE001
        logger.warning("automation run failed for %s", agent.get("id"), exc_info=True)
        return {"status": STATUS_FAILED, "answer": "", "notes": [TURN_FAILED]}


async def _post_callback(url: str, payload: dict) -> bool:
    """POST the result, a few times if need be. Never raises."""
    for attempt in range(CALLBACK_TRIES):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT_SECONDS) as client:
                r = await client.post(url, json=payload)
            if r.status_code < 500:
                return r.status_code < 300
        except Exception:                                   # noqa: BLE001
            logger.warning("callback to %s failed (try %d)", url, attempt + 1,
                           exc_info=True)
        await asyncio.sleep(2 * (attempt + 1))
    return False


async def _run_then_post(email: str, agent: dict, message: str,
                         run_id: str, url: str) -> None:
    result = await _run(email, agent, message)
    payload = dict(result, id=run_id,
                   agent={"id": agent["id"], "name": agent.get("name") or agent["id"]})
    await _post_callback_seam(url, payload)


#: Seams. Tests replace these rather than running a turn or posting out.
_run_turn_seam = _run_turn
_post_callback_seam = _post_callback
_agents_seam = _agents_for
_spawn = asyncio.create_task


@router.post("/run")
async def run_agent(body: RunIn, authorization: str = Header(default="")) -> dict:
    """Run one of the key owner's agents on a message."""
    email = await _email_from(authorization)
    agents = await _agents_seam(email)
    agent = find_agent(agents, body.agent)
    if agent is None:
        names = sorted(str(a.get("name") or "") for a in agents
                       if isinstance(a, dict) and a.get("name"))
        raise HTTPException(
            status_code=404,
            detail=(f"No agent called {body.agent.strip()!r}. "
                    + ("Your agents: " + ", ".join(names) + "." if names
                       else "You have no agents yet.")))
    who = {"id": agent["id"], "name": agent.get("name") or agent["id"]}
    run_id = uuid.uuid4().hex
    if body.callback_url:
        problem = await callback_problem(body.callback_url)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        _spawn(_run_then_post(email, agent, body.message, run_id, body.callback_url))
        return {"id": run_id, "status": STATUS_ACCEPTED, "agent": who}
    result = await _run(email, agent, body.message)
    return dict(result, id=run_id, agent=who)


# --- the keys, for the Agents page ------------------------------------------------

class KeyIn(BaseModel):
    label: str = Field(default="", max_length=200)


@router.get("/keys")
async def list_keys(user: CurrentUser = Depends(current_user)) -> dict:
    return {"keys": await automation_keys.list_keys(user.email)}


@router.post("/keys")
async def make_key(body: KeyIn, user: CurrentUser = Depends(current_user)) -> dict:
    """A new key. The response carries the key itself, this once."""
    try:
        return await automation_keys.create(user.email, body.label)
    except automation_keys.TooManyKeys:
        raise HTTPException(
            status_code=409,
            detail=f"You have {automation_keys.MAX_ACTIVE_KEYS} keys, which is "
                   "the limit. Revoke one to make another.")


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    return {"revoked": await automation_keys.revoke(user.email, key_id)}
