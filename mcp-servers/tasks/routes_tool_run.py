"""Run ONE tool with the person's own connection, from n8n (2026-11-19).

    POST /api/tasks/tools/run
    Authorization: Bearer iok_...           a key with the `tools` scope
    {"app": "github", "tool": "list_my_repos", "args": {}}

Lukas, at stand-up on 2026-11-18: a person's n8n workflows should use the
apps that person already connected in AIUI, without connecting them again
inside n8n. `/agents/run` already let a workflow run a whole agent, but a
workflow wants a fixed step ("add this card"), not a chat turn worded
differently each time.

So the step runs here, through the same `mytools._call` the chat uses,
with the credential AIUI already holds. The vendor credential never leaves
AIUI; the only secret in n8n is the AIUI key, which only this route
accepts and which the person revokes in one place.

Nobody watches a workflow run to say yes, so a key does not get the whole
catalogue (decided 2026-11-19):

- a READ tool always runs;
- a WRITE tool runs only once the person approved a workflow AIUI built
  with that step in it (`automation_key.allowed_writes`,
  `aiui_link.approve_steps`); approving the workflow approved its steps;
- nothing of n8n's own, and not `link_aiui`, ever runs from a key that
  sits in n8n: it must not be able to change n8n or mint more keys.

Every failure is a status n8n marks as failed, never a 200 with an error
inside it. Arguments and results are never logged: they are mail, files
and records.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import automation_keys
import connections as C
import mytools
import routes_automation

logger = logging.getLogger("routes_tool_run")
router = APIRouter(prefix="/tools")

#: The Google apps are their own services, reached the way email_poller
#: reaches Gmail: POST <url>/<tool> with X-User-Email. Reads only for now.
GOOGLE_READS: dict[str, tuple[str, str, frozenset]] = {
    "gdrive": (os.environ.get("GDRIVE_URL", "http://mcp-gdrive:8000"),
               "Google Drive",
               frozenset({"gdrive_search_files", "gdrive_list_files",
                          "gdrive_read_file"})),
    "gmail": (os.environ.get("GMAIL_URL", "http://mcp-gmail:8000"),
              "Gmail",
              frozenset({"gmail_search_emails", "gmail_read_email"})),
    "calendar": (os.environ.get("CALENDAR_URL", "http://mcp-calendar:8000"),
                 "Google Calendar",
                 frozenset({"calendar_list_events"})),
}
GOOGLE_TIMEOUT_SECONDS = 60.0

#: Never from a key, whatever its approvals say.
NEVER_APPS = frozenset({"n8n"})
NEVER_TOOLS = frozenset({"link_aiui"})

NOT_FOR_TOOLS = ("This key cannot run tools. Ask AIUI to link your n8n "
                 "again.")
NOT_APPROVED = ("This step was not approved in AIUI. Ask AIUI to add it to "
                "the workflow, and it will ask you first.")
NEVER_HERE = ("This cannot be run from a workflow. Ask AIUI in the chat "
              "instead.")


class RunToolIn(BaseModel):
    app: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    args: Any = Field(default_factory=dict)


def step_name(app: str, tool: str) -> str:
    """How an approved write step is written down on a key."""
    return f"{app}.{tool}"


def _who(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]


def _not_connected(label: str) -> str:
    return (f"You have not connected your {label} account yet. Open "
            f"Connections in AIUI and connect {label}, then run this again.")


async def _owner(authorization: str) -> dict:
    token = ""
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail=routes_automation.NO_KEY)
    owner = await automation_keys.owner_for(token)
    if not owner:
        raise HTTPException(status_code=401, detail=routes_automation.BAD_KEY)
    if automation_keys.SCOPE_TOOLS not in (owner.get("scopes") or []):
        raise HTTPException(status_code=403, detail=NOT_FOR_TOOLS)
    return owner


def _missing(tool: "mytools.Tool", args: dict) -> list[str]:
    """Required arguments not given. The chat's served boundary checks
    these with pydantic; `_call` does not, so this route must."""
    return [name for name, spec in (tool.args or {}).items()
            if len(spec) > 2 and spec[2]
            and (args.get(name) is None or args.get(name) == "")]


async def _run_google(app: str, tool: str, email: str, args: dict) -> Any:
    url, label, _ = GOOGLE_READS[app]
    try:
        async with httpx.AsyncClient(timeout=GOOGLE_TIMEOUT_SECONDS) as client:
            r = await client.post(url.rstrip("/") + "/" + tool,
                                  headers={"X-User-Email": email}, json=args)
    except (httpx.HTTPError, OSError):
        raise HTTPException(status_code=502,
                            detail=f"{label} did not answer. Try again in a minute.")
    if r.status_code in (401, 403):
        raise HTTPException(status_code=409, detail=_not_connected(label))
    try:
        payload = r.json()
    except ValueError:
        payload = None
    if r.status_code >= 400:
        said = payload.get("detail") if isinstance(payload, dict) else None
        raise HTTPException(status_code=422, detail=(
            said if isinstance(said, str) else f"{label} returned an error "
            f"({r.status_code})."))
    # The Google services answer a refusal as 200 {"error": "..."}: a
    # success to n8n. Not connected is the commonest, and their sentence
    # carries a link and the address, so ours is said instead.
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        if "not connected" in payload["error"].lower():
            raise HTTPException(status_code=409, detail=_not_connected(label))
        raise HTTPException(status_code=422, detail=payload["error"])
    return payload


@router.post("/run")
async def run_tool(body: RunToolIn, authorization: str = Header(default="")) -> Any:
    owner = await _owner(authorization)
    email = owner["email"]
    app = body.app.strip().lower()
    name = body.tool.strip()
    if not isinstance(body.args, dict):
        raise HTTPException(status_code=422, detail="args must be a JSON object.")
    args = body.args

    if app in NEVER_APPS or name in NEVER_TOOLS:
        raise HTTPException(status_code=403, detail=NEVER_HERE)

    if app in GOOGLE_READS:
        _, label, reads = GOOGLE_READS[app]
        if name not in reads:
            raise HTTPException(status_code=404, detail=(
                f"{label} has no tool {name!r} here. Tools: "
                + ", ".join(sorted(reads)) + "."))
        async with routes_automation._slots:
            out = await _run_google(app, name, email, args)
        logger.info("tools/run %s %s.%s ok", _who(email), app, name)
        return out

    tools = {t.name: t for t in mytools.PROVIDER_TOOLS.get(app, [])}
    if not tools:
        apps = sorted([a for a in mytools.PROVIDER_TOOLS if a not in NEVER_APPS]
                      + list(GOOGLE_READS))
        raise HTTPException(status_code=404, detail=(
            f"No app called {app!r}. Apps: " + ", ".join(apps) + "."))
    tool = tools.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=(
            f"{app} has no tool {name!r}. Tools: "
            + ", ".join(sorted(tools)) + "."))

    if mytools._writes(tool) and step_name(app, name) not in (
            owner.get("allowed_writes") or []):
        logger.info("tools/run %s %s.%s refused: not approved",
                    _who(email), app, name)
        raise HTTPException(status_code=403, detail=NOT_APPROVED)

    missing = _missing(tool, args)
    if missing:
        raise HTTPException(status_code=422, detail=(
            "Missing: " + ", ".join(missing) + "."))

    prov = C.provider(app)
    label = prov.label if prov else app
    if not await mytools._secrets_for(email, app):
        raise HTTPException(status_code=409, detail=_not_connected(label))

    async with routes_automation._slots:
        out = await mytools._call(app, tool, email, args)
    if isinstance(out, dict) and out.get("ok") is False:
        logger.info("tools/run %s %s.%s refused by the tool",
                    _who(email), app, name)
        raise HTTPException(status_code=422,
                            detail=str(out.get("error") or "The tool failed."))
    logger.info("tools/run %s %s.%s ok", _who(email), app, name)
    return out
