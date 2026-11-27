"""Talking to a person's own MCP server (Streamable HTTP).

Its own small copy of the protocol rather than mcp-proxy's
``mcp_http_client``: the two services are separate builds, and that client
caches sessions per URL, which here would hand one person's session to
another person with a server at the same address. Sessions here are keyed by
(email, server id).

The rules, each because of something that could otherwise happen:

- https only, and ``host_guard.problem`` before EVERY request, not only at
  the connect: a name that answered public on Monday can be repointed on
  Tuesday (``connections.types_a_url`` follows the same rule);
- redirects are never followed, so a public server cannot bounce us onto
  our own network;
- the token is sent as ``Authorization: Bearer`` and removed from anything
  the server says back before it is repeated, and the address never appears
  in a sentence at all, because some vendors put the key in it;
- everything that goes wrong is a ``Refused`` whose text is a sentence for
  the person, naming the server by the label they gave it.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md, section 6.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
from collections import OrderedDict
from typing import Any

import httpx

import host_guard
import own_mcp

logger = logging.getLogger(__name__)

LIST_TIMEOUT = 15.0
CALL_TIMEOUT = 20.0
SESSION_TTL = 3600.0
MAX_SESSIONS = 500
RESULT_CHARS = 20000
SAID_CHARS = 160
PROTOCOL = "2025-03-26"

#: (email, server id) -> (session id, when it was made)
_SESSIONS: "OrderedDict[tuple[str, str], tuple[str, float]]" = OrderedDict()


class Refused(Exception):
    """Something the person should be told, in words they can act on."""


# --- sessions --------------------------------------------------------------

def _remember_session(key: tuple[str, str], session_id: str) -> None:
    _SESSIONS[key] = (session_id, time.monotonic())
    _SESSIONS.move_to_end(key)
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.popitem(last=False)


def _session(key: tuple[str, str] | None) -> str | None:
    if key is None:
        return None
    held = _SESSIONS.get(key)
    if not held:
        return None
    session_id, made = held
    if time.monotonic() - made > SESSION_TTL:
        _SESSIONS.pop(key, None)
        return None
    return session_id


def forget(key: tuple[str, str]) -> None:
    """Drop a cached session (the server was removed or changed)."""
    _SESSIONS.pop(key, None)


# --- what the person is told -----------------------------------------------

def _secrets_in(url: str, token: str) -> list[str]:
    """Everything that must never be repeated: the token, the address, and
    the address's path and query, longest first, because a vendor that
    puts its key in the path echoes the path, not the whole address."""
    out = [token, url] if token else [url]
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        parts = None
    if parts is not None:
        if parts.path and len(parts.path) > 4:
            out.append(parts.path)
        if parts.query:
            out.append(parts.query)
        if parts.hostname:
            out.append(parts.hostname)
    return sorted((s for s in out if s), key=len, reverse=True)


def _clean(text: Any, token: str, url: str = "") -> str:
    """The server's own words, safe to repeat: the token and the address
    removed, one line, at most 160 characters."""
    said = " ".join(str(text or "").split())
    for secret in _secrets_in(url, token):
        said = said.replace(secret, "[hidden]")
    return said[:SAID_CHARS]


def _said(label: str, text: Any, token: str, url: str = "") -> Refused:
    words = _clean(text, token, url)
    if not words:
        return Refused(f"Your {label} server refused that without saying why.")
    return Refused(f"Your {label} server said: {words}")


async def _check(url: str) -> None:
    said = own_mcp.address_problem(url)
    if said:
        raise Refused(said)
    said = await host_guard.problem(url)
    if said:
        raise Refused(said)


# --- the protocol ----------------------------------------------------------

def _parse(text: str) -> dict | None:
    """A JSON-RPC message from a plain JSON body or the last SSE data line."""
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            got = json.loads(text)
            return got if isinstance(got, dict) else None
        except ValueError:
            pass
    last = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                got = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(got, dict):
                last = got
    return last


def _headers(token: str, session_id: str | None) -> dict:
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


async def _post(http: httpx.AsyncClient, url: str, token: str,
                session_id: str | None, payload: dict, label: str,
                timeout: float) -> httpx.Response:
    """One POST, with every way it can fail turned into a sentence."""
    await _check(url)
    try:
        response = await http.post(url, json=payload,
                                   headers=_headers(token, session_id))
    except httpx.TimeoutException:
        raise Refused(f"Your {label} server did not answer in "
                      f"{int(timeout)} seconds.") from None
    except httpx.HTTPError:
        raise Refused(f"Your {label} server could not be reached. "
                      f"Check it is running and try again.") from None
    if response.is_redirect:
        raise Refused(f"Your {label} server tried to send us somewhere else, "
                      f"so I did not follow it.")
    return response


async def _initialize(http, url, token, label, timeout) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                          "clientInfo": {"name": "aiui", "version": "1.0"}}}
    response = await _post(http, url, token, None, payload, label, timeout)
    if response.status_code == 401 or response.status_code == 403:
        raise Refused(f"Your {label} server did not accept the token. "
                      f"Check it and save the server again.")
    if response.status_code not in (200, 201):
        raise _said(label, response.text, token, url)
    message = _parse(response.text)
    if message and isinstance(message.get("error"), dict):
        raise _said(label, message["error"].get("message"), token, url)
    if not message or "result" not in message:
        raise Refused(f"Your {label} server did not answer like an MCP server.")
    session_id = response.headers.get("mcp-session-id", "")
    try:
        await _post(http, url, token, session_id or None,
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    label, timeout)
    except Refused:
        pass   # the notification is a courtesy; the request after it decides
    return session_id


async def _request(url: str, token: str, method: str, params: dict | None,
                   label: str, key: tuple[str, str] | None,
                   timeout: float) -> dict:
    """A JSON-RPC request on a session, re-initialized once if the server
    says the session is gone. Returns the ``result``."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
        for attempt in (1, 2):
            session_id = _session(key)
            if session_id is None:
                session_id = await _initialize(http, url, token, label, timeout)
                if key is not None:
                    _remember_session(key, session_id)
            payload = {"jsonrpc": "2.0", "id": 2, "method": method}
            if params is not None:
                payload["params"] = params
            response = await _post(http, url, token, session_id or None,
                                   payload, label, timeout)
            if response.status_code in (401, 404, 409) and attempt == 1:
                # The session is gone (or never took): drop it and make a
                # new one. With no key nothing is cached, so the next round
                # initializes anyway.
                if key is not None:
                    forget(key)
                continue
            if response.status_code not in (200, 201):
                raise _said(label, response.text, token, url)
            message = _parse(response.text)
            if not message:
                raise Refused(f"Your {label} server sent an answer I could not read.")
            if isinstance(message.get("error"), dict):
                raise _said(label, message["error"].get("message"), token, url)
            result = message.get("result")
            return result if isinstance(result, dict) else {}
    raise Refused(f"Your {label} server kept refusing the session.")


# --- the two things callers do ---------------------------------------------

async def list_tools(url: str, token: str, *, label: str = "MCP",
                     key: tuple[str, str] | None = None,
                     timeout: float = LIST_TIMEOUT) -> dict:
    """The server's ``tools/list`` result, as it sent it. Raises Refused."""
    return await _request(url, token, "tools/list", None, label, key, timeout)


def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url or "").hostname or ""
    except ValueError:
        return ""


def _text_of(result: dict) -> str:
    """The text parts joined and cut at 20,000; other parts named after."""
    parts, others = [], []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        else:
            others.append(f"[{item.get('type') or 'unknown'} content, not shown]")
    if not parts and result.get("structuredContent") is not None:
        try:
            parts.append(json.dumps(result["structuredContent"]))
        except (TypeError, ValueError):
            pass
    text = "\n".join(parts)
    if len(text) > RESULT_CHARS:
        text = (text[:RESULT_CHARS] + "\n[cut: the answer was longer than "
                f"{RESULT_CHARS} characters]")
    return "\n".join([text] + others) if others else text


async def call(key: tuple[str, str], url: str, token: str, tool: str,
               arguments: dict, label: str,
               timeout: float = CALL_TIMEOUT) -> str:
    """Run one tool and return its text. Raises Refused."""
    try:
        result = await _request(url, token, "tools/call",
                                {"name": tool, "arguments": arguments or {}},
                                label, key, timeout)
    except Refused:
        logger.info("own mcp call refused: server %s for %s", key[1], key[0])
        raise
    text = _text_of(result)
    if result.get("isError"):
        raise _said(label, text, token, url)
    for secret in _secrets_in(url, token):
        if secret != _host(url):
            text = text.replace(secret, "[hidden]")
    return text
