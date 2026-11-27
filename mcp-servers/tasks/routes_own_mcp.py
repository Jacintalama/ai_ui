"""A person's own MCP servers: the Connections routes, and the two routes
only mcp-proxy may call.

Under its own prefix, /own-mcp, and NOT under /connections:
routes_connections has ``POST /{provider_id}`` and ``POST /{provider_id}/test``,
which would read /connections/own-mcp as a provider called "own-mcp".

The person's routes take the caller from the gateway (``current_user``).
The proxy's two routes need the internal secret AND the email: tasks shares
its network with about 30 containers, and Open WebUI and pipelines run code
admins paste in, so an email alone must not be enough to run tools on
somebody's own server with their token.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md, section 4.
"""
from __future__ import annotations

import hmac
import logging
import os
import urllib.parse
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import host_guard
import own_mcp
import own_mcp_client
import own_mcp_store as store
from auth import CurrentUser, current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/own-mcp", tags=["own-mcp"])


class ServerIn(BaseModel):
    label: str = ""
    url: str = ""
    token: str = ""


class CallIn(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = {}


# --- shared ----------------------------------------------------------------

async def _problem(body: ServerIn) -> str:
    """Why this server cannot be used, judged before anything is sent."""
    said = own_mcp.label_problem(body.label)
    if said:
        return said
    said = own_mcp.address_problem(body.url)
    if said:
        return said
    return await host_guard.problem(body.url.strip())


async def _list(url: str, token: str, label: str, slug: str,
                key: tuple[str, str] | None = None):
    """(used, not_used) from the server, or raise Refused."""
    listed = await own_mcp_client.list_tools(url, token, label=label, key=key)
    return own_mcp.snapshot(slug, listed)


def _card(row: dict, not_used: list[str] | None = None) -> dict:
    tools = row.get("tools") or []
    checked = row.get("checked_at")
    return {
        "id": row["id"],
        "label": row["label"],
        "host": row["host"],
        "tool_count": len(tools),
        "read_only_count": sum(1 for t in tools if t.get("read_only")),
        "tools": [t.get("tool") for t in tools],
        "not_used": not_used or [],
        "check_ok": bool(row.get("check_ok", True)),
        "checked_at": checked.isoformat() if hasattr(checked, "isoformat") else checked,
    }


async def _remember(email: str) -> list[dict]:
    """This person's rows, and the read-only memory refreshed from them."""
    rows = await store.list_for(email)
    own_mcp.remember(email, [t for r in rows for t in r.get("tools") or []])
    return rows


# --- the person's routes ---------------------------------------------------

@router.get("/servers")
async def list_servers(user: CurrentUser = Depends(current_user)):
    rows = await _remember(user.email)
    return {"servers": [_card(r) for r in rows]}


@router.post("/servers/test")
async def test_server(body: ServerIn, user: CurrentUser = Depends(current_user)):
    said = await _problem(body)
    if said:
        return {"ok": False, "problem": said}
    label = body.label.strip()
    try:
        used, not_used = await _list(body.url.strip(), body.token.strip(),
                                     label, own_mcp.slug_for(label, set()) or "x")
    except own_mcp_client.Refused as e:
        return {"ok": False, "problem": str(e)}
    if not used:
        return {"ok": False, "not_used": not_used,
                "problem": f"Your {label} server answered, but offers no tools I can use."}
    return {"ok": True, "not_used": not_used,
            "tools": [{"name": t["tool"], "read_only": t["read_only"]} for t in used]}


@router.post("/servers")
async def add_server(body: ServerIn, user: CurrentUser = Depends(current_user)):
    rows = await store.list_for(user.email)
    if len(rows) >= own_mcp.MAX_SERVERS:
        raise HTTPException(400, f"You can add up to {own_mcp.MAX_SERVERS} of your "
                                 f"own servers. Remove one to add another.")
    said = await _problem(body)
    if said:
        raise HTTPException(400, said)
    label, url, token = body.label.strip(), body.url.strip(), body.token.strip()
    slug = own_mcp.slug_for(label, {r["slug"] for r in rows})
    try:
        used, not_used = await _list(url, token, label, slug)
    except own_mcp_client.Refused as e:
        raise HTTPException(400, str(e)) from None
    if not used:
        raise HTTPException(400, f"Your {label} server answered, but offers no "
                                 f"tools I can use, so it was not saved.")
    host = urllib.parse.urlsplit(url).hostname or ""
    server_id = await store.add(user.email, slug, label, host, url, token, used)
    logger.info("own mcp server added: %s for %s (%d tools)",
                server_id, user.email, len(used))
    rows = await _remember(user.email)
    row = next((r for r in rows if r["id"] == server_id), None)
    return _card(row or {"id": server_id, "label": label, "host": host,
                         "tools": used}, not_used)


@router.post("/servers/{server_id}/refresh")
async def refresh_server(server_id: str, user: CurrentUser = Depends(current_user)):
    row = next((r for r in await store.list_for(user.email)
                if r["id"] == server_id), None)
    secrets = await store.secrets_of(user.email, server_id) if row else None
    if not row or not secrets:
        raise HTTPException(404, "Server not found")
    try:
        used, not_used = await _list(secrets["url"], secrets["token"], row["label"],
                                     row["slug"], key=(user.email, server_id))
    except own_mcp_client.Refused as e:
        await store.record_check(user.email, server_id, False)
        fresh = next((r for r in await _remember(user.email) if r["id"] == server_id), row)
        return dict(_card(fresh), problem=str(e))
    if used:
        await store.set_tools(user.email, server_id, used)
    else:
        await store.record_check(user.email, server_id, False)
    fresh = next((r for r in await _remember(user.email) if r["id"] == server_id), row)
    card = _card(fresh, not_used)
    if not used:
        card["problem"] = (f"Your {row['label']} server answered, but offers no "
                           f"tools I can use. The tools it had are kept.")
    return card


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str, user: CurrentUser = Depends(current_user)):
    if not await store.remove(user.email, server_id):
        raise HTTPException(404, "Server not found")
    own_mcp_client.forget((user.email, server_id))
    await _remember(user.email)
    logger.info("own mcp server removed: %s for %s", server_id, user.email)
    return {"removed": True}


# --- mcp-proxy only ----------------------------------------------------------

def _require_proxy(secret: str | None) -> None:
    """Both routes below need the internal secret; missing config denies."""
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or not hmac.compare_digest(
            (secret or "").encode(), expected.encode()):
        raise HTTPException(403, "invalid internal secret")


def _caller(email: str | None) -> str:
    email = (email or "").strip().lower()
    if not email:
        raise HTTPException(401, "Missing X-User-Email")
    return email


@router.get("/tools")
async def own_tools(x_internal_secret: str | None = Header(default=None),
                    x_user_email: str | None = Header(default=None)):
    _require_proxy(x_internal_secret)
    email = _caller(x_user_email)
    rows = await _remember(email)
    tools = []
    for r in rows:
        tools.extend(own_mcp.catalogue(r["slug"], r["label"], r.get("tools") or []))
    return {"tools": tools}


@router.post("/call")
async def own_call(body: CallIn,
                   x_internal_secret: str | None = Header(default=None),
                   x_user_email: str | None = Header(default=None)):
    _require_proxy(x_internal_secret)
    email = _caller(x_user_email)
    not_found = HTTPException(404, f"Tool '{body.tool_name}' not found")
    slug = own_mcp.slug_of(body.tool_name)
    row = await store.by_slug(email, slug) if slug else None
    tool = next((t for t in (row or {}).get("tools") or []
                 if t.get("name") == body.tool_name), None)
    if not row or not tool:
        raise not_found
    secrets = await store.secrets_of(email, row["id"])
    if not secrets:
        raise not_found
    # Checked here as well as in the client: a name that answered public at
    # the connect can be repointed since.
    said = (own_mcp.address_problem(secrets["url"])
            or await host_guard.problem(secrets["url"]))
    if said:
        logger.info("own mcp call refused by the address check: %s for %s",
                    row["id"], email)
        return {"result": said, "failed": True}
    try:
        result = await own_mcp_client.call((email, row["id"]), secrets["url"],
                                           secrets["token"], tool["tool"],
                                           body.arguments, row["label"])
    except own_mcp_client.Refused as e:
        await store.record_check(email, row["id"], False)
        return {"result": str(e), "failed": True}
    return {"result": result}
