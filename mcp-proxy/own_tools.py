"""A caller's own MCP tools, for that caller only.

A person can add their own MCP servers in Connections. tasks holds the
servers, the encrypted address and token, and makes the calls; this module
asks tasks "what are this caller's own tools?" and forwards "run this one
for this caller". The proxy never sees an address or a token.

Own tools are NEVER put in TOOLS_CACHE, which is one catalogue shared by
everyone. Each of the three /meta/* routes asks ``for_caller(email)`` after
the caller is identified, and answers a name starting ``own-`` from that
caller's own tools only.

Who is calling matters for a tool that can change something. The tasks loop
(main chat assistant, agents, cron, Discord) holds a write for approval
before it calls, and proves it is the tasks loop with the internal secret.
A model in Open WebUI calling this proxy directly as a tool server has no
way to ask first, so it may only run own tools the server marked read-only.

``OWN_MCP=0`` switches all of it off: the routes answer exactly as before.

Design: docs/superpowers/specs/2026-11-26-own-mcp-servers-design.md, section 5.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

PREFIX = "own-"
CACHE_SECONDS = 60.0
MAX_CALLERS = 200
MAX_VECTORS = 2000
LIST_TIMEOUT = 3.0
#: The tasks side gives a call 20 s; this leaves room for it to answer.
CALL_TIMEOUT = 30.0

REFUSE_DIRECT = ("This tool can change things in your {server} server, so I "
                 "only run it where I can ask you first. Switch to Auto (Free) "
                 "and ask again.")

#: email -> (when fetched, {name: entry})
_CACHE: "OrderedDict[str, tuple[float, Dict[str, dict]]]" = OrderedDict()
#: hash of a tool's text -> its embedding
_VECTORS: "OrderedDict[str, List[float]]" = OrderedDict()


def enabled() -> bool:
    return os.environ.get("OWN_MCP", "1").strip().lower() not in ("0", "false", "no")


def is_own(name: Any) -> bool:
    return isinstance(name, str) and name.startswith(PREFIX)


def tasks_url() -> str:
    return os.environ.get("TASKS_URL", "http://tasks:8210").rstrip("/")


def _secret() -> str:
    return os.environ.get("INTERNAL_CALLBACK_SECRET", "")


def caller_is_tasks(request) -> bool:
    """True when the request carries our internal secret."""
    expected = _secret()
    got = request.headers.get("x-internal-secret", "")
    return bool(expected) and hmac.compare_digest(got.encode(), expected.encode())


# --- the caller's own tools ------------------------------------------------

def _keep(email: str, tools: Dict[str, dict]) -> None:
    _CACHE[email] = (time.monotonic(), tools)
    _CACHE.move_to_end(email)
    while len(_CACHE) > MAX_CALLERS:
        _CACHE.popitem(last=False)


async def for_caller(email: str) -> Dict[str, dict]:
    """This caller's own tools by name, {} on any failure or when off.

    An own server that cannot be listed must never break search for the
    built tools, so every failure is an empty answer.
    """
    if not enabled() or not email or not _secret():
        return {}
    email = email.strip().lower()
    held = _CACHE.get(email)
    if held and time.monotonic() - held[0] < CACHE_SECONDS:
        return held[1]
    try:
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT) as http:
            r = await http.get(tasks_url() + "/own-mcp/tools",
                               headers={"X-Internal-Secret": _secret(),
                                        "X-User-Email": email})
        if r.status_code != 200:
            print(f"  [own-tools] tasks answered {r.status_code}")
            return {}
        listed = (r.json() or {}).get("tools") or []
    except Exception as e:                                  # noqa: BLE001
        print(f"  [own-tools] could not ask tasks: {type(e).__name__}")
        return {}
    tools = {t["name"]: t for t in listed
             if isinstance(t, dict) and is_own(t.get("name"))}
    _keep(email, tools)
    return tools


# --- ranking ---------------------------------------------------------------

def _embed(texts: List[str]) -> Optional[List[List[float]]]:
    """Embeddings from the model already loaded for the catalogue, or None."""
    from tool_embeddings import generate_embeddings_batch, get_embedding_model
    if get_embedding_model() is None:
        return None
    return generate_embeddings_batch(texts)


def _text(entry: dict) -> str:
    return f"{entry.get('name', '')}: {entry.get('description', '')}"


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _result(entry: dict, score: float) -> dict:
    return {"tool_name": entry["name"], "server_id": entry.get("server_id", ""),
            "display_name": entry["name"], "description": entry.get("description", ""),
            "relevance_score": round(float(score), 4)}


def _vectors_for(entries: List[dict]) -> Optional[List[List[float]]]:
    keys = [hashlib.sha256(_text(e).encode()).hexdigest() for e in entries]
    missing = [i for i, k in enumerate(keys) if k not in _VECTORS]
    if missing:
        got = _embed([_text(entries[i]) for i in missing])
        if got is None:
            return None
        for i, vec in zip(missing, got):
            _VECTORS[keys[i]] = list(vec)
            _VECTORS.move_to_end(keys[i])
        while len(_VECTORS) > MAX_VECTORS:
            _VECTORS.popitem(last=False)
    out = []
    for i, k in enumerate(keys):
        vec = _VECTORS.get(k)
        if vec is None:   # dropped by the bound while this call ran
            got = _embed([_text(entries[i])])
            if got is None:
                return None
            vec = list(got[0])
        out.append(vec)
    return out


def rank(query: str, tools: Dict[str, dict], limit: int) -> List[dict]:
    """The caller's own tools ranked against the query, in the shape
    search_tools returns. Keyword scores when no model is loaded."""
    entries = [e for e in tools.values() if isinstance(e, dict) and e.get("name")]
    if not entries:
        return []
    query_vec = _embed([query])
    vectors = _vectors_for(entries) if query_vec else None
    if query_vec and vectors:
        scored = [(_cosine(query_vec[0], v), e) for v, e in zip(vectors, entries)]
    else:
        words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
        scored = []
        for e in entries:
            name, desc = e["name"].lower(), str(e.get("description", "")).lower()
            if any(w in name for w in words):
                scored.append((0.8, e))
            elif any(w in desc for w in words):
                scored.append((0.5, e))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_result(e, s) for s, e in scored[:limit]]


def merge(built: List[dict], own: List[dict], limit: int) -> List[dict]:
    """Built and own results by score, stable, cut at limit."""
    both = list(built or []) + list(own or [])
    both.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return both[:limit]


# --- describe and call -----------------------------------------------------

def describe(name: str, tools: Dict[str, dict]) -> dict:
    entry = tools.get(name)
    if not entry:
        return {"tool_name": name, "error": "Tool not found"}
    return {"tool_name": name, "server_id": entry.get("server_id", ""),
            "server_name": entry.get("server_name", ""), "display_name": name,
            "description": entry.get("description", ""),
            "request_body": entry.get("request_body", {}), "parameters": [],
            "endpoint": f"/{entry.get('server_id', '')}/{name}"}


async def call(email: str, name: str, arguments: Dict[str, Any]) -> dict:
    """Forward one call to tasks. A 404 there is a 404 here."""
    async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as http:
        r = await http.post(tasks_url() + "/own-mcp/call",
                            json={"tool_name": name, "arguments": arguments or {}},
                            headers={"X-Internal-Secret": _secret(),
                                     "X-User-Email": email})
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    if r.status_code != 200:
        return {"result": "Your own server could not be reached just now. "
                          "Try again in a minute.", "failed": True}
    return r.json()


async def run(request, email: str, name: str, arguments: Dict[str, Any]) -> dict:
    """The whole call_tool path for an own tool."""
    tools = await for_caller(email)
    entry = tools.get(name)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    if not entry.get("read_only") and not caller_is_tasks(request):
        return {"result": REFUSE_DIRECT.format(server=entry.get("server_name") or "own")}
    return await call(email, name, arguments)
