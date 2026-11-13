"""Tools that run as YOU.

Every ClickUp call the platform makes today is made as whoever owns the shared
container token. On this deployment that is one named person, so a task created
"by" any user is created by him. Connecting your own account stored a
credential and changed none of that, because execution still went through the
vendor MCP containers, and those take their credential from boot-time env with
no per-call seam.

This module is the seam. mcp-proxy already forwards the resolved end-user email
to local servers (that is how Gmail and Drive load the right person's OAuth), so
a server hosted here can look up THAT user's stored credential and call the
vendor's REST API directly as them.

Three decisions worth keeping.

One sub-app per provider, each serving its own openapi.json, because
mcp-proxy discovers a server by fetching `{endpoint}/openapi.json` and indexing
its POST paths. A GET tool would be invisible: callable, and never found.

A curated set rather than a mirror. The shared ClickUp server exposes 172 tools
covering chat channels, doc templates and bulk custom-field operations. Almost
all real use is a dozen verbs. Every tool here is hand-written against the
vendor's REST API, so the surface is what someone would actually ask for.

Failures come back as {"ok": false, "error": "..."} with HTTP 200. The caller
is a model, and a 5xx reaches it as a tool-call failure with nothing usable in
it, whereas a sentence gets read and acted on. "You have not connected your
GitHub yet" is a thing a model can relay; a vendor 401 is not.
"""
import logging
from dataclasses import dataclass, field as _dc_field
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

import connection_health as H
import connections as C
from auth import current_user, CurrentUser

logger = logging.getLogger("tasks.mytools")

#: Most rows any tool returns. A whole API page buries the answer and eats the
#: model's context; nobody asks "list my repos" wanting 200 of them.
MAX_ITEMS = 25

VENDOR_TIMEOUT_SEC = 20


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str
    #: HTTP method and path template against the vendor's base_url. Braces are
    #: filled from the request body.
    method: str
    path: str
    #: Body fields the tool accepts, name -> (type, description, required).
    args: Dict[str, tuple] = _dc_field(default_factory=dict)
    #: Fields kept from each returned object. Everything else is dropped.
    keep: tuple = ()
    #: Pull the list out of the vendor's envelope, when there is one.
    unwrap: Optional[Callable[[Any], Any]] = None
    #: Query parameters to add, name -> body field name.
    query: Dict[str, str] = _dc_field(default_factory=dict)
    #: Body fields sent as the JSON payload (for writes).
    body: tuple = ()
    #: Some vendors nest a write under a key. HubSpot wants
    #: {"properties": {...}}; everything else takes the fields flat.
    wrap_body: str = ""
    #: Values sent when the caller did not give one.
    #:
    #: Not cosmetic. ClickUp requires `type` on a chat message and rejects
    #: it without one, and the payload is built from the args that were
    #: PASSED, so an "optional" field with a default in a comment is simply
    #: absent and the call is a 400 after the person has approved it.
    defaults: Dict[str, Any] = _dc_field(default_factory=dict)
    #: A base URL for THIS tool only, replacing the provider's.
    #:
    #: ClickUp's chat lives on /api/v3 while everything else here is
    #: /api/v2, and until 2026-11-06 there was no way to say so: every
    #: request was `auth.base_url + path`, so chat was simply unreachable
    #: and the chat told Ralph that ClickUp channels could not be made
    #: through an API at all. They can; his account has five.
    #:
    #: Per tool rather than per provider on purpose. Moving the provider's
    #: base to v3 would take list_tasks and create_task with it.
    base: str = ""
    #: A tool that answers with SEVERAL vendor calls instead of one.
    #:
    #: Every tool here maps to a single endpoint, which is right while the
    #: vendor has an endpoint for the question. ClickUp has none for "which
    #: list is called Project 1", so answering it means climbing the tree,
    #: and climbing it one model round per rung is what produced "Stopped
    #: after 7 rounds of tool use" (2026-11-10). The walk belongs on this
    #: side of the loop.
    #:
    #: Signature is `run(get, args)`, where `get(path)` does one
    #: authenticated GET as this person. `method` and `path` are unused.
    run: Optional[Callable[..., Any]] = None
    #: Build the whole JSON body from the arguments, instead of copying
    #: named ones across.
    #:
    #: `body` and `wrap_body` cover a vendor that takes the fields as they
    #: were given, flat or under one key. Airtable does not: a table is
    #: made with a LIST OF FIELD OBJECTS that nothing in the arguments
    #: looks like, and asking a model to write that list itself is asking
    #: it to know which types need an `options` block (2026-11-12). The
    #: shaping belongs on this side, where it can be read and tested
    #: without a vendor.
    #:
    #: Signature is `shape(args) -> dict`. It wins over `body`.
    shape: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    #: Query parameters sent when the caller named none, vendor param name
    #: -> value.
    #:
    #: The same reason `defaults` exists, for the other half of a request.
    #: Jira's `GET /issue/{key}` with no `fields` returns EVERY field the
    #: site has, custom ones included, which is hundreds of keys of a
    #: model's context spent on a question about a summary. A default in a
    #: comment is not sent, so it has to be here.
    query_defaults: Dict[str, Any] = _dc_field(default_factory=dict)
    #: Whether this tool changes anything at the vendor. `None` means "ask
    #: the method", which is right almost everywhere.
    #:
    #: It is overridable because a POST is not always a write. Jira's JQL
    #: search takes GET or POST and we send POST, so it can carry a default
    #: `fields` list. `writes` drives one sentence: a 403 on a write adds
    #: "reconnect it from Connections to allow that". On a search that
    #: sentence is a wrong instruction, because a 403 there means this
    #: person cannot see that project and reconnecting changes nothing.
    writes: Optional[bool] = None


def _payload_for(tool: "Tool", args: Optional[Dict[str, Any]]) -> Optional[Dict]:
    """The JSON body for a write, with the tool's defaults filled in.

    Its own function so a test can read what would be sent without a
    vendor, a connection or a network. The default is applied only when
    the caller gave nothing, so a caller that means "post" keeps it.
    """
    if tool.shape:
        return tool.shape(args or {})
    if not tool.body:
        return None
    given = args or {}
    out = {}
    for key in tool.body:
        value = given.get(key)
        if value in (None, ""):
            value = tool.defaults.get(key)
        if value not in (None, ""):
            out[key] = value
    return {tool.wrap_body: out} if tool.wrap_body else out


def _query_for(tool: "Tool", args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The query string for one call: what the caller named, then the tool's
    own defaults for anything they did not.

    Its own function for the same reason as `_payload_for`: a test can read
    what would be sent with no vendor and no network.
    """
    given = args or {}
    params: Dict[str, Any] = {}
    for param_name, arg_name in (tool.query or {}).items():
        v = given.get(arg_name)
        if v not in (None, ""):
            params[param_name] = v
    for param_name, value in (tool.query_defaults or {}).items():
        if params.get(param_name) in (None, "") and value not in (None, ""):
            params[param_name] = value
    return params


def _writes(tool: "Tool") -> bool:
    """Whether this tool changes anything at the vendor."""
    if tool.writes is not None:
        return bool(tool.writes)
    return str(tool.method or "").upper() != "GET"


async def _secrets_for(email: str, provider: str) -> Dict[str, str]:
    """Seam so tests need no database. Wraps the only function that decrypts a
    stored credential, and that function is deliberately not a route."""
    from routes_connections import secrets_for
    return await secrets_for(email, provider)


def _trim(obj: Any, keep: tuple) -> Any:
    """Keep only the named fields. Vendors return dozens per object and the
    extras are noise a model has to read past."""
    if not keep:
        return obj
    if isinstance(obj, list):
        return [_trim(o, keep) for o in obj]
    if not isinstance(obj, dict):
        return obj
    return {k: obj.get(k) for k in keep if k in obj}


def _as_list(payload: Any, tool: Tool) -> Any:
    if tool.unwrap:
        try:
            payload = tool.unwrap(payload)
        except Exception:
            pass
    return payload


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


#: The most of a vendor's own words we will repeat. Their messages are a
#: sentence; anything longer is not a message.
MAX_VENDOR_NOTE = 160


def _vendor_said(r, creds: Dict[str, str]) -> str:
    """The vendor's own explanation, when it is safe to repeat.

    This exists because of a real afternoon (2026-11-03). Asked to read a
    file, the answer was "GitHub could not find that. Check the id you
    asked for", which sends somebody hunting a wrong repository name that
    is not wrong. GitHub had said exactly what was the matter: "This
    repository is empty." We were throwing away the one account of the
    failure and replacing it with a guess.

    Why this is not simply `r.text`. For Trello the credential rides in the
    QUERY STRING and its errors echo the request, so repeating a vendor's
    words verbatim is how a token ends up rendered into a chat. So the rule
    is a property, not a vendor list: say it only when no part of this
    person's credential appears in it. That holds for a vendor nobody has
    thought about yet, which a list does not.
    """
    try:
        payload = r.json()
    except Exception:                                       # noqa: BLE001
        return ""
    message = ""
    if isinstance(payload, dict):
        # ClickUp puts its reason in "err" (2026-11-10).
        found = (payload.get("message") or payload.get("error")
                 or payload.get("err") or "")
        # Airtable NESTS it: {"error": {"type": ..., "message": ...}}.
        # str() on that drops a Python dict into the middle of a chat
        # reply, braces and quotes and all, which is the vendor's own
        # reason turned back into the noise this function exists to
        # replace. The type is the fallback because Airtable sends one
        # with no message at all on some refusals.
        if isinstance(found, dict):
            found = found.get("message") or found.get("type") or ""
        if not found:
            # Jira's dialect, and it names no "message" at all:
            #   {"errorMessages": ["..."], "errors": {"duedate": "..."}}
            # `errors` is per FIELD, which is the likeliest real failure on
            # a live site: a project whose create screen requires a field
            # we did not send. The field name is half the answer, so it is
            # kept rather than only the sentence. Three at most, because
            # a misconfigured screen can name a dozen.
            errors = payload.get("errors")
            if isinstance(errors, dict) and errors:
                found = "; ".join(str(k) + ": " + str(v)
                                  for k, v in list(errors.items())[:3])
            if not found:
                general = payload.get("errorMessages")
                if isinstance(general, (list, tuple)) and general:
                    found = "; ".join(str(g) for g in general[:2])
        message = str(found or "")
    message = " ".join(c for c in message.split() if c)
    message = "".join(c for c in message if c.isprintable())
    if len(message) > MAX_VENDOR_NOTE:
        # Between words, not through one. Measured live 2026-11-12: the
        # hard cut landed inside "and/or" and the reply read "...that the
        # model names and/ If you connected Airtable before", which looks
        # like something went wrong on our side rather than a long
        # sentence politely shortened. The dots are so a message that
        # simply stops is not mistaken for the whole answer.
        cut = message[:MAX_VENDOR_NOTE]
        at = cut.rfind(" ")
        message = (cut[:at] if at > 0 else cut).rstrip(" ,;:") + "..."
    if not message:
        return ""
    for value in (creds or {}).values():
        v = str(value or "")
        if len(v) >= 8 and v in message:
            return ""
    return " " + message


async def _read_once(client, auth, provider_id: str, path: str,
                     extra: Optional[Dict[str, Any]] = None,
                     base: str = ""):
    """One authenticated GET as this person, as the vendor answered it.

    Shared by the two things that read before they answer: a provider's
    prepare step, and a composite tool's walk. Those two want opposite
    things from a failure, which is why this hands back the response
    rather than deciding, but the request itself is written once.
    """
    params = dict(auth.params)
    params.update({k: v for k, v in (extra or {}).items()
                   if v not in (None, "")})
    try:
        return await client.request("GET", (base or auth.base_url) + path,
                                    headers=auth.headers,
                                    params=params or None, json=None)
    except Exception as e:                                  # noqa: BLE001
        # The exception text can carry the URL, and some vendors take the
        # credential in the query string. Log the type, never the message.
        logger.warning("mytools: %s read unreachable (%s)", provider_id,
                       type(e).__name__)
        return None


async def _prepared(prepare, tool: "Tool", args: Dict[str, Any], auth,
                    provider_id: str):
    """Run a provider's prepare step with reads made as this person.

    A read that fails returns None to the step, which then decides; it never
    raises, so a lookup that could not be made is never why a call failed."""
    async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SEC) as client:
        async def get(path: str, extra: Optional[Dict[str, Any]] = None):
            r = await _read_once(client, auth, provider_id, path, extra)
            if r is None or r.status_code >= 400:
                return None
            try:
                return r.json()
            except Exception:                               # noqa: BLE001
                return None
        try:
            return await prepare(tool.name, args, get)
        except Exception as e:                              # noqa: BLE001
            logger.warning("mytools: %s prepare failed (%s)", provider_id,
                           type(e).__name__)
            return args, None


def _clickup_prepare(tool_name, args, get):
    import clickup_people
    return clickup_people.prepare(tool_name, args, get)


def _trello_prepare(tool_name, args, get):
    import trello_people
    return trello_people.prepare(tool_name, args, get)


def _github_prepare(tool_name, args, get):
    import github_refs
    return github_refs.prepare(tool_name, args, get)


#: Per provider, a step between the model's arguments and the vendor.
#: ClickUp (2026-11-10): people by name or email, columns as said, lists by
#: name. Trello (2026-11-11): members by name or username, and the flags
#: archive_card and complete_card exist to set. GitHub (2026-11-11): the
#: sha a new branch starts from, and the sha a file write updates.
#:
#: Each of these returns early for a tool it has nothing to do for, because
#: this runs on EVERY call to that provider.
async def _linkedin_prepare(tool_name, args, get):
    """Fill in the author's Person URN for a share.

    Returns (args, problem). A lookup that could not be made REFUSES,
    rather than letting the share go out with no author: that is a 400
    from LinkedIn after the model has already been told the post went
    live.
    """
    args = dict(args or {})
    if tool_name != "create_post" or args.get("author"):
        return args, None
    me = await get("/userinfo")
    sub = (me or {}).get("sub") if isinstance(me, dict) else None
    if not sub:
        return args, ("LinkedIn did not say who you are, so there is "
                      "nobody to post as. Reconnect LinkedIn from "
                      "Connections and try again.")
    args["author"] = "urn:li:person:" + str(sub)
    return args, None


PREPARE = {"clickup": _clickup_prepare, "trello": _trello_prepare,
           "linkedin": _linkedin_prepare,
           "github": _github_prepare}


def _unreachable(label: str) -> str:
    return "Could not reach " + label + " just now. Try again in a moment."


#: Words that mean "you are not allowed", and words that mean "you have
#: run out". The two are opposite advice and a 403 carries either.
_NOT_ALLOWED_WORDS = ("permission", "scope", "not authorized", "unauthorized",
                      "forbidden", "insufficient", "read-only", "read only")
_RAN_OUT_WORDS = ("plan", "limit", "quota", "usage", "upgrade", "billing",
                  "paywall", "trial")


def _scope_hint(said: str, label: str) -> str:
    """One sentence for a write a vendor refused on permission grounds.

    A token carries what was approved on the day it was made, so every
    write tool that ships is newer than somebody's connection and the
    first thing it meets is a 403 nobody can read. Airtable's is
    "Invalid permissions, or the requested model was not found", which
    sounds like a wrong base id and sends a person hunting one.

    The guard is the whole point. PR #182 is the afternoon this cost:
    ClickUp refused a create_space for a plan limit and Ralph was told
    to reconnect a credential that had just read his entire workspace.
    So a refusal that says anything about money, usage or a plan gets
    nothing added, however much of a write it was.
    """
    low = (said or "").lower()
    if any(word in low for word in _RAN_OUT_WORDS):
        return ""
    if not any(word in low for word in _NOT_ALLOWED_WORDS):
        return ""
    return (" If you connected " + label + " before IO could write, "
            "reconnect it from Connections to allow that.")


def _refusal(r, label: str, creds: Dict[str, str], provider_id: str,
             tool_name: str, writes: bool = False) -> str:
    """The sentence for a vendor's refusal, or "" when it did not refuse.

    One function because two kinds of tool need the same words now: a
    single-call tool, and a composite one making several calls of its
    own. A second copy would drift, and it would drift in error text,
    which is the part nobody re-reads.
    """
    if r.status_code == 401:
        return ("Your " + label + " credential was rejected. It may have "
                "expired. Reconnect it from Connections.")
    if r.status_code == 403:
        # 401 and 403 are DIFFERENT answers and must not share a sentence.
        # 401 is "we do not know who you are". 403 is "we know, and you may
        # not do this", which is a plan limit, a quota or a permission far
        # more often than a bad token.
        #
        # Measured 2026-11-11, from a real conversation: ClickUp answered a
        # create_space with
        #     {"err": "Your plan is limited to 5 usages of feature, 5
        #      usage.", "ECODE": "PAYWALL_004"}
        # and this function threw that away and told Ralph to reconnect a
        # credential that had just read his whole workspace. He would have
        # reconnected, failed again, and had no way to find out why. The
        # chat even told him his credential was "failing on writes", which
        # create_task had disproved seconds earlier.
        #
        # Same rule the 400 path already follows: the vendor's own account
        # of the failure is the one thing worth keeping.
        said = _vendor_said(r, creds)
        if said:
            return (label + " would not allow that." + said
                    + (_scope_hint(said, label) if writes else ""))
        return (label + " would not allow that. That is usually a "
                "permission or a plan limit rather than a bad credential. "
                "If it keeps happening, reconnect it from Connections.")
    if r.status_code == 404:
        return label + " could not find that." + _vendor_said(r, creds)
    if r.status_code >= 400:
        # Never r.text: vendors echo the request, credential included.
        # _vendor_said repeats the vendor's own reason only when no part of
        # the credential is in it. Without it the model read "returned an
        # error (400)" and had nothing to correct (ClickUp, 2026-11-10).
        logger.warning("mytools: %s %s returned %s", provider_id, tool_name,
                       r.status_code)
        return (label + " returned an error (" + str(r.status_code) + ")."
                + _vendor_said(r, creds))
    return ""


class _VendorRefused(Exception):
    """A vendor said no in the middle of a composite tool's own walk.

    It carries the sentence already worded for the person, so the walk
    needs to know nothing about HTTP status codes and cannot invent a
    second vocabulary for the same failures.
    """


async def _run_composite(provider_id: str, tool: Tool, auth,
                         creds: Dict[str, str], label: str,
                         args: Dict[str, Any], email: str = "") -> dict:
    """Run a tool that answers with several vendor calls.

    Everything a single-call tool gets stays the same: this person's own
    credential and nobody else's, the vendor's own words only where they
    are safe to repeat, and a sentence rather than a status code when it
    fails.

    Unlike a prepare step, a failure here is fatal and says so. There is
    no single call behind this tool to fall back to: the walk IS the
    answer, so a walk that could not be made has no answer to give.
    """
    async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SEC) as client:
        async def get(path: str, extra: Optional[Dict[str, Any]] = None):
            r = await _read_once(client, auth, provider_id, path, extra,
                                 base=tool.base)
            if r is None:
                raise _VendorRefused(_unreachable(label))
            # What this answer says about the stored credential, if
            # anything. A 401 marks it, a working call clears it, a 403
            # says nothing at all. Before the refusal, which returns.
            await H.note(email, provider_id, r.status_code)
            problem = _refusal(r, label, creds, provider_id, tool.name)
            if problem:
                raise _VendorRefused(problem)
            try:
                return r.json()
            except Exception:                               # noqa: BLE001
                return {}

        try:
            return await tool.run(get, args)
        except _VendorRefused as e:
            return _err(str(e))


async def _call(provider_id: str, tool: Tool, email: str,
                args: Dict[str, Any]) -> dict:
    label = (C.provider(provider_id) or C.Provider).label if C.provider(
        provider_id) else provider_id

    creds = await _secrets_for(email, provider_id)
    if not creds:
        return _err("You have not connected your " + label + " account yet. "
                    "Open Connections in the sidebar and connect " + label +
                    ", then ask again.")
    try:
        auth = C.vendor_auth(provider_id, creds)
    except ValueError:
        return _err("Your " + label + " connection is incomplete. Reconnect it "
                    "from Connections.")

    # Before prepare, because prepare exists to fix up the arguments of a
    # call to one endpoint, and a composite tool has no such call behind
    # it to fix up.
    if tool.run:
        return await _run_composite(provider_id, tool, auth, creds, label,
                                    args, email=email)

    prepare = PREPARE.get(provider_id)
    if prepare:
        args, problem = await _prepared(prepare, tool, args, auth, provider_id)
        if problem:
            return _err(problem)

    path = tool.path
    for key, value in (args or {}).items():
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))
    # An OPTIONAL segment nobody filled is an empty segment, not a missing
    # value. list_folder's `path` is how somebody asks for the root of a
    # repository, and leaving it out is the ordinary way to do that.
    for name, spec in (tool.args or {}).items():
        if len(spec) > 2 and not spec[2]:
            path = path.replace("{" + name + "}", "")
    if "{" in path:
        missing = path.split("{", 1)[1].split("}", 1)[0]
        return _err("Missing required value: " + missing)
    # ".../contents/" is not ".../contents". Measured against GitHub on
    # 2026-11-03: the first 404s, so listing a repository's root failed
    # while every other path worked, which is the hardest kind of bug to
    # read from a tool result.
    path = path.rstrip("/") or "/"

    params = dict(auth.params)
    params.update(_query_for(tool, args))

    payload = _payload_for(tool, args)

    url = (tool.base or auth.base_url) + path
    try:
        async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SEC) as client:
            r = await client.request(tool.method, url, headers=auth.headers,
                                     params=params or None, json=payload)
    except Exception as e:
        # The exception text can carry the URL, and Trello's credential rides
        # in the query string. Log the type, never the message.
        logger.warning("mytools: %s unreachable (%s)", provider_id,
                       type(e).__name__)
        return _err(_unreachable(label))

    # Before the refusal below, which returns.
    await H.note(email, provider_id, r.status_code)

    problem = _refusal(r, label, creds, provider_id, tool.name,
                       writes=_writes(tool))
    if problem:
        return _err(problem)

    try:
        data = r.json()
    except Exception:
        return {"ok": True, "items": []}

    data = _as_list(data, tool)
    if isinstance(data, list):
        return {"ok": True, "count": len(data),
                "items": _trim(data[:MAX_ITEMS], tool.keep),
                "truncated": len(data) > MAX_ITEMS}
    return {"ok": True, "item": _trim(data, tool.keep)}


# --- the curated surface --------------------------------------------------
# Hand-written against each vendor's REST API. `keep` is the shortlist of
# fields a model actually needs to answer a question or act on the result.

#: How much of one file, and of one file's diff, a model is handed. A repo
#: file can be any size at all and a tool result goes straight into a turn,
#: so the cap is the difference between reading a file and losing the
#: conversation. Both say when they have cut, so nothing silently looks
#: complete.
MAX_FILE_CHARS = 40_000
MAX_PATCH_CHARS = 8_000


def _github_file(payload: Any) -> Any:
    """GitHub returns a file's content base64 encoded. Decoded here, because
    a model handed base64 will either try to decode it itself or describe it
    as binary.

    A directory comes back as a LIST from the same endpoint, which is what
    list_folder uses; passed through untouched so one path serves both.
    """
    if not isinstance(payload, dict):
        return payload
    raw = str(payload.get("content") or "")
    text, cut = "", False
    if raw:
        import base64 as _b64
        try:
            text = _b64.b64decode(raw).decode("utf-8", "replace")
        except Exception:                                   # noqa: BLE001
            text = ""
    if len(text) > MAX_FILE_CHARS:
        text, cut = text[:MAX_FILE_CHARS], True
    return {"path": payload.get("path"), "size": payload.get("size"),
            "truncated": cut or bool(payload.get("truncated")),
            "content": text}


def _github_patches(payload: Any) -> Any:
    """A pull request's files, with each diff trimmed.

    One generated lockfile can be a megabyte of patch on its own and would
    push every other file in the review out of the turn. The file is still
    listed with its counts, so a reviewer sees that it changed.
    """
    if not isinstance(payload, list):
        return payload
    out = []
    for f in payload:
        if not isinstance(f, dict):
            continue
        patch = str(f.get("patch") or "")
        if len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS] + chr(10) + "... diff trimmed ..."
        out.append({**f, "patch": patch})
    return out


GITHUB_TOOLS = [
    Tool(name="list_my_repos",
         summary="List the GitHub repositories you own or collaborate on, most recently updated first.",
         method="GET", path="/user/repos",
         query={"sort": "sort", "per_page": "limit"},
         args={"limit": ("integer", "How many to return", False),
               "sort": ("string", "updated, created, pushed or full_name", False)},
         keep=("full_name", "private", "html_url", "description", "updated_at")),
    Tool(name="list_my_issues",
         summary="List GitHub issues assigned to you across all your repositories.",
         method="GET", path="/issues",
         query={"state": "state", "per_page": "limit"},
         args={"state": ("string", "open, closed or all", False),
               "limit": ("integer", "How many to return", False)},
         keep=("number", "title", "state", "html_url", "repository_url", "updated_at")),
    Tool(name="list_repo_issues",
         summary="List issues in one GitHub repository, given its owner and name.",
         method="GET", path="/repos/{owner}/{repo}/issues",
         query={"state": "state", "per_page": "limit"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "state": ("string", "open, closed or all", False),
               "limit": ("integer", "How many to return", False)},
         keep=("number", "title", "state", "html_url", "user", "updated_at")),
    Tool(name="create_issue",
         summary="Open a new issue in one of your GitHub repositories.",
         method="POST", path="/repos/{owner}/{repo}/issues",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "title": ("string", "Issue title", True),
               "body": ("string", "Issue description", False)},
         body=("title", "body"),
         keep=("number", "title", "html_url", "state")),
    # --- reading code, and reviewing a pull request (2026-11-03) ----------
    # Asked for directly: "i want the system can read repo codes can review
    # PR all of it like claude". The set before this was four lists and one
    # create, so the chat answered, correctly, that anything inside the
    # repository was out of its reach.
    Tool(name="read_file",
         summary="Read one file from a GitHub repository, given its path. "
                 "Use this to look at the actual code.",
         method="GET", path="/repos/{owner}/{repo}/contents/{path}",
         query={"ref": "ref"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "path": ("string", "Path inside the repo, like src/app.py", True),
               "ref": ("string", "Branch, tag or commit. Defaults to the "
                                 "default branch", False)},
         unwrap=_github_file,
         keep=("path", "size", "truncated", "content")),
    Tool(name="list_folder",
         summary="List the files and folders at one path in a GitHub "
                 "repository. Use an empty path for the top level.",
         method="GET", path="/repos/{owner}/{repo}/contents/{path}",
         query={"ref": "ref"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "path": ("string", "Folder inside the repo. Empty for the root", False),
               "ref": ("string", "Branch, tag or commit", False)},
         keep=("name", "path", "type", "size")),
    Tool(name="list_repo_pull_requests",
         summary="List the pull requests in one GitHub repository.",
         method="GET", path="/repos/{owner}/{repo}/pulls",
         query={"state": "state", "per_page": "limit"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "state": ("string", "open, closed or all", False),
               "limit": ("integer", "How many to return", False)},
         keep=("number", "title", "state", "html_url", "user", "draft",
               "updated_at")),
    Tool(name="read_pull_request",
         summary="Read one pull request: its title, description, state and "
                 "how much it changes.",
         method="GET", path="/repos/{owner}/{repo}/pulls/{number}",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Pull request number", True)},
         keep=("number", "title", "state", "body", "html_url", "user",
               "additions", "deletions", "changed_files", "mergeable_state")),
    Tool(name="read_pull_request_changes",
         summary="Read the actual code changes in a pull request, file by "
                 "file, with the diff. Use this to review a PR.",
         method="GET", path="/repos/{owner}/{repo}/pulls/{number}/files",
         query={"per_page": "limit"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Pull request number", True),
               "limit": ("integer", "How many files to return", False)},
         unwrap=_github_patches,
         keep=("filename", "status", "additions", "deletions", "patch")),
    Tool(name="comment_on_pull_request",
         summary="Leave a comment on a pull request, written as you. This is "
                 "how a review is delivered.",
         method="POST", path="/repos/{owner}/{repo}/issues/{number}/comments",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Pull request number", True),
               "body": ("string", "The comment, markdown is fine", True)},
         body=("body",),
         keep=("id", "html_url", "created_at")),
    Tool(name="comment_on_issue",
         summary="Leave a comment on a GitHub issue, written as you.",
         method="POST", path="/repos/{owner}/{repo}/issues/{number}/comments",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Issue number", True),
               "body": ("string", "The comment, markdown is fine", True)},
         body=("body",),
         keep=("id", "html_url", "created_at")),
    Tool(name="list_my_pull_requests",
         summary="List open pull requests you have raised across GitHub.",
         method="GET", path="/search/issues",
         query={"q": "q", "per_page": "limit"},
         args={"q": ("string", "Search query, defaults to your open PRs", False),
               "limit": ("integer", "How many to return", False)},
         unwrap=lambda d: d.get("items", []),
         keep=("number", "title", "state", "html_url", "updated_at")),
    Tool(name="whoami",
         summary="Show which GitHub account is currently connected to your assistant.",
         method="GET", path="/user",
         keep=("login", "name", "html_url", "public_repos")),
    # --- opening a pull request, and search (2026-11-11) ------------------
    # The second half of the connector boundary work. `my-github` had 13
    # tools against the shared server's 32, and that gap is the whole
    # reason the shared one is still on, which means four admins act as
    # somebody else's GitHub account.
    #
    # Only SIX of the 19 are real: seven were the same capability under
    # another name (get_file_contents is read_file, get_me is whoami,
    # list_issues is list_repo_issues, and so on) and the rest are niche.
    # create_branch and push_files are deliberately absent: both need a
    # commit sha read before the call, which is a prepare step, and that
    # belongs in its own change rather than hidden in this one.
    Tool(name="list_branches",
         summary="List the branches in a GitHub repository, with the commit "
                 "each one points at.",
         method="GET", path="/repos/{owner}/{repo}/branches",
         query={"per_page": "limit"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "limit": ("integer", "How many to return", False)},
         keep=("name", "commit", "protected")),
    Tool(name="list_commits",
         summary="List recent commits in a GitHub repository, newest first.",
         method="GET", path="/repos/{owner}/{repo}/commits",
         query={"sha": "branch", "path": "path", "per_page": "limit"},
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "branch": ("string", "Only commits on this branch. The "
                                    "repository's default branch when left "
                                    "out", False),
               "path": ("string", "Only commits that touched this file", False),
               "limit": ("integer", "How many to return", False)},
         keep=("sha", "commit", "html_url")),
    Tool(name="create_pull_request",
         summary="Open a pull request in a GitHub repository. It is opened "
                 "for review only: nothing lands on the base branch until "
                 "somebody approves and completes it.",
         method="POST", path="/repos/{owner}/{repo}/pulls",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "title": ("string", "Pull request title", True),
               "head": ("string", "The branch to merge FROM, the one that "
                                  "holds your commits", True),
               "base": ("string", "The branch to merge INTO, usually main", True),
               "body": ("string", "What the pull request does, and how it "
                                  "was checked", False)},
         body=("title", "head", "base", "body"),
         keep=("number", "title", "state", "html_url", "head", "base")),
    Tool(name="search_repositories",
         summary="Search GitHub for repositories.",
         method="GET", path="/search/repositories",
         query={"q": "query", "sort": "sort", "per_page": "limit"},
         args={"query": ("string", "GitHub search syntax, so qualifiers "
                                   "like user:someone or language:python "
                                   "work", True),
               "sort": ("string", "stars, forks or updated", False),
               "limit": ("integer", "How many to return", False)},
         unwrap=lambda d: d.get("items", []),
         keep=("full_name", "private", "html_url", "description",
               "updated_at")),
    Tool(name="search_code",
         summary="Search the CODE inside GitHub repositories, to find where "
                 "something is written.",
         method="GET", path="/search/code",
         query={"q": "query", "per_page": "limit"},
         args={"query": ("string", "GitHub search syntax, so qualifiers "
                                   "like repo:owner/name, path: and "
                                   "language: work", True),
               "limit": ("integer", "How many to return", False)},
         unwrap=lambda d: d.get("items", []),
         keep=("name", "path", "html_url", "repository")),
    Tool(name="search_issues",
         summary="Search GitHub issues and pull requests.",
         method="GET", path="/search/issues",
         query={"q": "query", "sort": "sort", "per_page": "limit"},
         args={"query": ("string", "GitHub search syntax, so qualifiers "
                                   "like repo:owner/name, is:open and "
                                   "author: work", True),
               "sort": ("string", "created, updated or comments", False),
               "limit": ("integer", "How many to return", False)},
         unwrap=lambda d: d.get("items", []),
         keep=("number", "title", "state", "html_url", "updated_at")),
    # --- making a change, which needs a read first (2026-11-11) ----------
    # Held back from the six above on purpose: these two need the sha they
    # act on, and that is a prepare step. With them the chain is complete
    # and runs as the person who typed, which is what makes switching the
    # shared `github` server off a real option rather than a capability cut.
    Tool(name="create_branch",
         summary="Create a new branch in a GitHub repository. It starts "
                 "from the branch you name, or from the repository's "
                 "default branch.",
         method="POST", path="/repos/{owner}/{repo}/git/refs",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "branch": ("string", "Name for the new branch", True),
               "base": ("string", "The branch to start it from. The "
                                  "repository's default branch when left "
                                  "out", False)},
         body=("ref", "sha"),
         keep=("ref", "object")),
    Tool(name="write_file",
         summary="Write one file in a GitHub repository, on a branch. What "
                 "you send REPLACES the whole file, so send the file as it "
                 "should end up rather than only the changed lines.",
         method="PUT", path="/repos/{owner}/{repo}/contents/{path}",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "path": ("string", "Path inside the repo, like src/app.py", True),
               "content": ("string", "The file's complete new text", True),
               "message": ("string", "Commit message", True),
               "branch": ("string", "Branch to commit on. Make one with "
                                    "create_branch first rather than "
                                    "committing to the default branch",
                          False)},
         body=("message", "content", "branch", "sha"),
         keep=("content", "commit")),
]

#: ClickUp's chat endpoints, which are not on the v2 base every other
#: ClickUp tool here uses. Verified against ClickUp's own reference on
#: 2026-11-06: POST /api/v3/workspaces/{workspace_id}/chat/channels.
CLICKUP_V3 = "https://api.clickup.com/api/v3"

#: ClickUp is GENERATED from ClickUp's own OpenAPI specs, all 172
#: operations, rather than hand-written. Six were written by hand and the
#: chat told Ralph that ClickUp could not do the rest; it could, and a
#: field name wrong by one character fails after somebody has approved the
#: call. See tools/generate_clickup_tools.py.
#:
#: `whoami` is kept by hand because nothing in the spec answers "which
#: account am I actually connected as", which is the first question when
#: a connection is bound to the wrong person, and that happened on
#: 2026-11-06.
def _clickup_tools():
    import clickup_find
    import clickup_generated
    mine = Tool(name="whoami",
                summary="Show which ClickUp account is currently connected "
                        "to your assistant.",
                method="GET", path="/user",
                unwrap=lambda d: d.get("user", {}),
                keep=("id", "username", "email"))
    #: Every ClickUp write takes an id and ClickUp has no endpoint that
    #: takes a name, so this is the one tool here that is not a single
    #: call. See clickup_find for what it costs and why that is worth it.
    finder = Tool(
        name="find_list",
        summary="Find a ClickUp list by name and give back its list id, "
                "with the space and folder it sits in. Use this FIRST "
                "whenever somebody names where something goes, like 'in "
                "Project 1', and you need an id to create a task or read "
                "tasks, because ClickUp's other endpoints only take ids. "
                "One call searches every space, every folder and the "
                "lists that are in no folder.",
        method="POST", path="",
        args={"name": ("string", "The list, folder or space name as the "
                       "person said it, like 'Project 1'", True),
              "workspace_id": ("string", "Search only this workspace. "
                               "Optional, and all of them otherwise",
                               False)},
        run=clickup_find.find_list)
    return [mine, finder] + [_clickup_said(t)
                             for t in clickup_generated.build(Tool)
                             if t.name not in ("whoami", "find_list")]


#: What the two everyday ClickUp writes tell a model, over the generated
#: wording (2026-11-10). Tool search reads the summary, and "move this to
#: done" or "assign it to Ralph" has to find update_task. The assignee wording
#: is true because clickup_people looks names and emails up before the call.
#:
#: create_task carries the assignee wording as well, and that is not a
#: duplicate. Measured on the box for Ralph's own sentence, "create a
#: ClickUp task called Buy milk 7 in Project 1 and assign it to ralph":
#:
#:     create_task 0.7623, add_task_to_list, add_guest_to_task,
#:     create_task_comment, create_checklist
#:       -> update_task offered: False
#:
#: update_task says "assign" and is not returned; create_task says nothing
#: about it and is always returned, because the search matches the whole
#: sentence and his begins "create a ClickUp task called". So the model
#: created the task unassigned, reported with perfect accuracy that it had
#: no tool to assign anybody, and when pressed made a SECOND task with the
#: same name. Rewording update_task to climb the ranking was considered and
#: rejected, the same as when find_list hit this wall: it is guessing at a
#: ranking function. The wording goes on the tool the model already lands on.
#:
#: It also NAMES update_task, because a model whose search returned neither
#: has no other way to learn that changing a task is possible at all.
_CLICKUP_SUMMARIES = {
    "create_task": "Create a new task. Assign people in the SAME call with "
                   "assignees, which takes a person's name, their email or "
                   "their ClickUp id and looks it up, and set its column "
                   "with status: there is no need to create the task first "
                   "and change it afterwards. If the task ALREADY exists "
                   "and you only need to change it, use update_task "
                   "instead, or the list ends up with two tasks of the "
                   "same name.",
    "update_task": "Update a task: move it to another column (status), assign "
                   "or unassign people, rename it, or change its due date or "
                   "priority.",
}
_CLICKUP_ARG_SAYS = {
    ("create_task", "assignees"):
        "A list of the people to assign: their ClickUp user id (a whole "
        "number), their email or their name. Names and emails are looked up.",
    ("update_task", "assignees"):
        "An object with add and rem, each a list of people: their ClickUp "
        "user id, their email or their name. Either may be left out.",
    ("create_task", "status"):
        "The column to put it in, as the list names it, for example to do "
        "or in progress.",
    ("update_task", "status"):
        "The column to move it to, as the list names it, for example in "
        "progress or complete. Done also means the list's last column.",
}


#: Said on EVERY ClickUp tool that takes a list_id, because the prepare
#: step looks a name up now (clickup_people.needs_list_lookup).
#:
#: A model is told only what the argument description says, and ClickUp's
#: own spec gives this one the description "list_id", which says nothing.
#: Measured on the box the day find_list shipped: tool search ranks it
#: FIRST for "which ClickUp list is Project 1" and nowhere in the top
#: eight for "create a task in Project 1", because the search text is the
#: person's own words. So the tool the model does find has to be the one
#: that accepts the name, and it has to say so here.
#:
#: On every such tool rather than a hand-picked few: there are 174 of
#: them, generated, and a list of names would go stale on the next
#: regeneration without failing anything.
_LIST_ID_SAYS = ("The list. Either its ClickUp list id, or the list's NAME "
                 "as the person said it, like 'Project 1'. A name is looked "
                 "up for you, so there is no need to find the id first.")


def _clickup_said(tool: "Tool") -> "Tool":
    from dataclasses import replace
    summary = _CLICKUP_SUMMARIES.get(tool.name, tool.summary)
    args = dict(tool.args or {})
    if "list_id" in args:
        kind, _old, required = args["list_id"]
        args["list_id"] = (kind, _LIST_ID_SAYS, required)
    for (name, field), said in _CLICKUP_ARG_SAYS.items():
        if name == tool.name and field in args:
            kind, _old, required = args[field]
            args[field] = (kind, said, required)
    if summary == tool.summary and args == (tool.args or {}):
        return tool
    return replace(tool, summary=summary, args=args)


CLICKUP_TOOLS = _clickup_tools()

#: By name, because a test or a route that wants one tool should not have
#: to scan 174 of them to say which.
CLICKUP_TOOLS_BY_NAME = {t.name: t for t in CLICKUP_TOOLS}

TRELLO_TOOLS = [
    Tool(name="list_my_boards",
         summary="List the Trello boards your account can see.",
         method="GET", path="/members/me/boards",
         keep=("id", "name", "url", "closed")),
    Tool(name="list_board_lists",
         summary="List the lists (columns) on one Trello board, given its id.",
         method="GET", path="/boards/{board_id}/lists",
         args={"board_id": ("string", "Board id from list_my_boards", True)},
         keep=("id", "name", "closed")),
    Tool(name="list_cards",
         summary="List the cards in one Trello list, given the list id.",
         method="GET", path="/lists/{list_id}/cards",
         args={"list_id": ("string", "List id from list_board_lists", True)},
         keep=("id", "name", "due", "url", "idMembers")),
    Tool(name="create_card",
         summary="Create a new Trello card in one of your lists.",
         method="POST", path="/cards",
         query={"idList": "list_id", "name": "name", "desc": "description"},
         args={"list_id": ("string", "List id from list_board_lists", True),
               "name": ("string", "Card title", True),
               "description": ("string", "Card description", False)},
         keep=("id", "name", "url")),
    Tool(name="update_card",
         summary="Move a Trello card to another list, or rename it, or "
                 "change its description or due date.",
         method="PUT", path="/cards/{card_id}",
         query={"idList": "list_id", "name": "name", "desc": "description",
                "due": "due"},
         args={"card_id": ("string", "Card id from list_cards", True),
               "list_id": ("string", "Move the card to this list id", False),
               "name": ("string", "New card title", False),
               "description": ("string", "New card description", False),
               "due": ("string", "Due date, ISO 8601", False)},
         keep=("id", "name", "due", "url", "idList")),
    Tool(name="comment_on_card",
         summary="Add a comment to a Trello card, written as you.",
         method="POST", path="/cards/{card_id}/actions/comments",
         query={"text": "text"},
         args={"card_id": ("string", "Card id from list_cards", True),
               "text": ("string", "The comment to add", True)},
         keep=("id", "data")),
    Tool(name="whoami",
         summary="Show which Trello account is currently connected to your assistant.",
         method="GET", path="/members/me",
         keep=("id", "username", "fullName", "url")),
    # The five below close the practical half of the gap against the SHARED
    # Trello connector, measured 2026-11-11 at 7 tools here against its 25.
    # That gap is the whole reason the shared one is still switched on, and
    # the reason four admins act as somebody else's Trello account.
    Tool(name="list_board_members",
         summary="List the people on one Trello board, with the username and "
                 "member id you need to put somebody on a card.",
         method="GET", path="/boards/{board_id}/members",
         args={"board_id": ("string", "Board id from list_my_boards", True)},
         keep=("id", "username", "fullName")),
    Tool(name="assign_member_to_card",
         summary="Put somebody on a Trello card. Takes their name, their "
                 "Trello username or their member id and looks it up, so "
                 "there is no need to find the id first.",
         method="POST", path="/cards/{card_id}/idMembers",
         query={"value": "member"},
         args={"card_id": ("string", "Card id from list_cards", True),
               "member": ("string", "Who to put on it: a name, a Trello "
                                    "username, or a member id from "
                                    "list_board_members", True)},
         keep=("id",)),
    Tool(name="remove_member_from_card",
         summary="Take somebody off a Trello card. Takes their name, their "
                 "Trello username or their member id and looks it up.",
         method="DELETE", path="/cards/{card_id}/idMembers/{member}",
         args={"card_id": ("string", "Card id from list_cards", True),
               "member": ("string", "Who to take off: a name, a Trello "
                                    "username, or a member id from "
                                    "list_board_members", True)},
         keep=("id",)),
    Tool(name="archive_card",
         summary="Archive a Trello card, which takes it off the board "
                 "without destroying it. This is how a card is retired.",
         method="PUT", path="/cards/{card_id}",
         query={"closed": "closed"},
         args={"card_id": ("string", "Card id from list_cards", True)},
         keep=("id", "name", "closed")),
    Tool(name="complete_card",
         summary="Mark a Trello card complete, ticking its due-date "
                 "checkbox. Use this when a board marks finished work with "
                 "the tick rather than by moving the card.",
         method="PUT", path="/cards/{card_id}",
         query={"dueComplete": "dueComplete"},
         args={"card_id": ("string", "Card id from list_cards", True)},
         keep=("id", "name", "dueComplete")),
    Tool(name="list_my_cards",
         summary="List the Trello cards you are on, across every board.",
         method="GET", path="/members/me/cards",
         keep=("id", "name", "due", "dueComplete", "url", "idList",
               "idBoard")),
]

NOTION_TOOLS = [
    Tool(name="search",
         summary="Search the Notion pages and databases your integration can reach.",
         method="POST", path="/search",
         args={"query": ("string", "What to search for", False)},
         body=("query",),
         unwrap=lambda d: d.get("results", []),
         keep=("id", "object", "url", "properties", "last_edited_time")),
    Tool(name="get_page",
         summary="Read one Notion page's properties, given its page id.",
         method="GET", path="/pages/{page_id}",
         args={"page_id": ("string", "Notion page id", True)},
         keep=("id", "url", "properties", "last_edited_time")),
    Tool(name="query_database",
         summary="List the rows in one Notion database, given its database id.",
         method="POST", path="/databases/{database_id}/query",
         args={"database_id": ("string", "Notion database id", True)},
         unwrap=lambda d: d.get("results", []),
         keep=("id", "url", "properties", "last_edited_time")),
    Tool(name="whoami",
         summary="Show which Notion workspace is currently connected to your assistant.",
         method="GET", path="/users/me",
         keep=("id", "name", "type", "bot")),
]

N8N_TOOLS = [
    Tool(name="list_my_workflows",
         summary="List the workflows on your own n8n instance.",
         method="GET", path="/api/v1/workflows",
         query={"limit": "limit"},
         args={"limit": ("integer", "How many to return", False)},
         unwrap=lambda d: d.get("data", d),
         keep=("id", "name", "active", "updatedAt")),
    Tool(name="get_workflow",
         summary="Read one workflow from your n8n instance, given its id.",
         method="GET", path="/api/v1/workflows/{workflow_id}",
         args={"workflow_id": ("string", "Workflow id", True)},
         keep=("id", "name", "active", "nodes", "updatedAt")),
    Tool(name="list_executions",
         summary="List recent workflow runs on your n8n instance, newest first.",
         method="GET", path="/api/v1/executions",
         query={"limit": "limit", "status": "status"},
         args={"limit": ("integer", "How many to return", False),
               "status": ("string", "success, error or waiting", False)},
         unwrap=lambda d: d.get("data", d),
         keep=("id", "workflowId", "status", "startedAt", "stoppedAt")),
]

#: Airtable field types that need no `options` block to be created.
#:
#: Every other type needs one: singleSelect wants its choices, number its
#: precision, date its format, checkbox an icon and a colour. Asked for a
#: Status column a model reaches for singleSelect, Airtable answers 422,
#: and the person gets NO TABLE rather than a table with a text column in
#: it. So a type from this list is honoured and anything else is made
#: text, which is a column that exists and that Airtable itself can
#: change in two clicks.
_AIRTABLE_PLAIN_TYPES = ("singleLineText", "multilineText", "email", "url",
                         "phoneNumber")
_AIRTABLE_TEXT = "singleLineText"
#: More columns than any table described in a sentence.
_AIRTABLE_MAX_COLUMNS = 50


def _airtable_fields(given: Any) -> List[Dict[str, str]]:
    """The `fields` Airtable wants, from however the columns were named.

    Columns arrive as plain strings ("Name", "Status", "Role") or as
    objects carrying a type, and both are reasonable things for a model
    to send, so both are read here.

    Order is kept, because Airtable makes the FIRST field the table's
    primary one. Names are deduplicated case-insensitively, because
    Airtable refuses a table with two fields of one name and a model
    listing columns out of a sentence repeats itself. An empty list
    becomes one column, because a table with no fields is refused too
    and "make me a table called Leads" should mean something.
    """
    out: List[Dict[str, str]] = []
    seen = set()
    for item in (given if isinstance(given, (list, tuple)) else []):
        kind = _AIRTABLE_TEXT
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            asked = str(item.get("type") or "").strip()
            if asked in _AIRTABLE_PLAIN_TYPES:
                kind = asked
        else:
            name = str(item or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "type": kind})
        if len(out) >= _AIRTABLE_MAX_COLUMNS:
            break
    return out or [{"name": "Name", "type": _AIRTABLE_TEXT}]


def _airtable_table_body(args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": str(args.get("name") or "").strip(),
                            "fields": _airtable_fields(args.get("columns"))}
    description = str(args.get("description") or "").strip()
    if description:
        body["description"] = description
    return body


#: How many rows Airtable takes in one create. Above it the call is a
#: 422, which loses every row rather than the eleventh.
_AIRTABLE_MAX_ROWS = 10


def _airtable_records_body(args: Dict[str, Any]) -> Dict[str, Any]:
    given = args.get("rows")
    rows = [r for r in (given if isinstance(given, (list, tuple)) else [])
            if isinstance(r, dict) and r]
    return {"records": [{"fields": r} for r in rows[:_AIRTABLE_MAX_ROWS]],
            "typecast": True}


def _airtable_record_body(args: Dict[str, Any]) -> Dict[str, Any]:
    fields = args.get("fields")
    # `typecast` is the difference between a model writing "Active" into
    # a single-select column and Airtable refusing a word where it keeps
    # option ids. A model has the word and has never seen the id.
    return {"fields": fields if isinstance(fields, dict) else {},
            "typecast": True}


AIRTABLE_TOOLS = [
    Tool(name="list_my_bases",
         summary="List the Airtable bases your access token can reach.",
         method="GET", path="/meta/bases",
         unwrap=lambda d: (d or {}).get("bases", []),
         keep=("id", "name", "permissionLevel")),
    Tool(name="list_tables",
         summary="List the tables inside one Airtable base, given its base id.",
         method="GET", path="/meta/bases/{base_id}/tables",
         args={"base_id": ("string", "Base id from list_my_bases", True)},
         unwrap=lambda d: (d or {}).get("tables", []),
         keep=("id", "name", "primaryFieldId")),
    Tool(name="list_records",
         summary="List rows from one Airtable table, given the base id and table name.",
         method="GET", path="/{base_id}/{table}",
         query={"maxRecords": "limit", "view": "view"},
         args={"base_id": ("string", "Base id from list_my_bases", True),
               "table": ("string", "Table id or name from list_tables", True),
               "limit": ("integer", "How many rows to return", False),
               "view": ("string", "Optional view name", False)},
         unwrap=lambda d: (d or {}).get("records", []),
         keep=("id", "createdTime", "fields")),
    Tool(name="create_table",
         summary="Create a new table in one of your Airtable bases, with the "
                 "columns you name. Every column is made a text column.",
         method="POST", path="/meta/bases/{base_id}/tables",
         args={"base_id": ("string", "Base id from list_my_bases", True),
               "name": ("string", "What to call the table", True),
               "columns": ("array",
                           "The column names in order, as a list of strings "
                           'like ["Name", "Status", "Role"]. The first one '
                           "is the table's primary column.", True),
               "description": ("string", "Optional note about the table",
                               False)},
         shape=_airtable_table_body,
         keep=("id", "name", "primaryFieldId", "fields")),
    Tool(name="create_record",
         summary="Add a row to one of your Airtable tables.",
         method="POST", path="/{base_id}/{table}",
         args={"base_id": ("string", "Base id from list_my_bases", True),
               "table": ("string", "Table id or name from list_tables", True),
               "fields": ("object",
                          "The row, as column name to value, like "
                          '{"Name": "Ada", "Role": "engineer"}. Column names '
                          "have to match the table's exactly.", True)},
         shape=_airtable_record_body,
         keep=("id", "createdTime", "fields")),
    Tool(name="create_records",
         summary="Add several rows to one of your Airtable tables in a "
                 "single call, up to ten at a time.",
         method="POST", path="/{base_id}/{table}",
         args={"base_id": ("string", "Base id from list_my_bases", True),
               "table": ("string", "Table id or name from list_tables", True),
               "rows": ("array",
                        "The rows, as a list of objects of column name to "
                        'value, like [{"Name": "Ada"}, {"Name": "Lin"}]. Up '
                        "to ten.", True)},
         shape=_airtable_records_body,
         unwrap=lambda d: (d or {}).get("records", []),
         keep=("id", "createdTime", "fields")),
    Tool(name="update_record",
         summary="Change some columns of one row in an Airtable table, "
                 "leaving every column you do not name as it is.",
         method="PATCH", path="/{base_id}/{table}/{record_id}",
         args={"base_id": ("string", "Base id from list_my_bases", True),
               "table": ("string", "Table id or name from list_tables", True),
               "record_id": ("string", "Row id from list_records", True),
               "fields": ("object",
                          "Only the columns to change, as column name to "
                          'value, like {"Status": "Done"}.', True)},
         shape=_airtable_record_body,
         keep=("id", "createdTime", "fields")),
    Tool(name="whoami",
         summary="Show which Airtable account is currently connected to your assistant.",
         method="GET", path="/meta/whoami",
         keep=("id", "email", "scopes")),
]

HUBSPOT_TOOLS = [
    Tool(name="list_contacts",
         summary="List contacts from your HubSpot CRM, most recently created first.",
         method="GET", path="/crm/v3/objects/contacts",
         query={"limit": "limit"},
         args={"limit": ("integer", "How many to return", False)},
         unwrap=lambda d: (d or {}).get("results", []),
         keep=("id", "properties", "createdAt", "updatedAt")),
    Tool(name="list_deals",
         summary="List deals from your HubSpot CRM pipeline.",
         method="GET", path="/crm/v3/objects/deals",
         query={"limit": "limit"},
         args={"limit": ("integer", "How many to return", False)},
         unwrap=lambda d: (d or {}).get("results", []),
         keep=("id", "properties", "createdAt", "updatedAt")),
    Tool(name="list_companies",
         summary="List companies from your HubSpot CRM.",
         method="GET", path="/crm/v3/objects/companies",
         query={"limit": "limit"},
         args={"limit": ("integer", "How many to return", False)},
         unwrap=lambda d: (d or {}).get("results", []),
         keep=("id", "properties", "createdAt")),
    Tool(name="create_contact",
         summary="Add a new contact to your HubSpot CRM.",
         method="POST", path="/crm/v3/objects/contacts",
         args={"email": ("string", "Contact email address", True),
               "firstname": ("string", "First name", False),
               "lastname": ("string", "Last name", False)},
         body=("email", "firstname", "lastname"),
         wrap_body="properties",
         keep=("id", "properties")),
    Tool(name="whoami",
         summary="Show which HubSpot portal is currently connected to your assistant.",
         method="GET", path="/account-info/v3/details",
         keep=("portalId", "accountType", "timeZone", "uiDomain")),
]

ZAPIER_TOOLS = [
    # One tool, because a Catch Hook is one door. What happens on the other
    # side is whatever Zap the user built, so the assistant's job is to hand
    # it a payload and say it went.
    Tool(name="send_to_zap",
         summary="Send data to your connected Zapier Zap, triggering whatever "
                 "automation you built on it (Slack post, Sheet row, email, "
                 "anything Zapier can do).",
         method="POST", path="/",
         args={"message": ("string", "The main text to send", True),
               "subject": ("string", "Optional subject or title", False),
               "data": ("string", "Optional extra detail", False)},
         body=("message", "subject", "data"),
         keep=("status", "id", "request_id")),
]

# --- Jira -----------------------------------------------------------------
#
# Two vendor facts shape every tool below, and both are things a connector
# written from memory gets wrong.
#
# `/rest/api/3/search` is GONE from Jira Cloud. The replacement is
# `/rest/api/3/search/jql`, which pages with `nextPageToken` instead of
# `startAt` and, unless it is given `fields`, answers with bare ids and
# keys. So the search is a POST carrying a default field list, rather than
# a GET hoping a model thought to ask for a summary.
#
# v3 takes RICH TEXT. A description or a comment is an Atlassian Document
# Format document, and a plain string is a 400. Asking a model to write
# that nesting itself is the Airtable field-types mistake again, so it is
# built here where it can be read and tested without a vendor.

#: What a search and a single issue read bring back when nobody says
#: otherwise. Enough to answer "what is on my board", short enough not to
#: bury it.
_JIRA_FIELDS = ("summary", "status", "assignee", "issuetype", "priority",
                "updated")

#: Jira requires an issue type on every create and a project has no
#: universal default. Task exists in every stock Jira project.
_JIRA_DEFAULT_TYPE = "Task"


def _jira_adf(text: Any) -> Optional[Dict[str, Any]]:
    """Plain text as an Atlassian Document Format document.

    Returns None for nothing, because an empty document is NOT an empty
    string to Jira: a text node with no text is invalid and the whole
    request is refused after the person has approved it.
    """
    # Line endings first: a paste carries \r\n, and "\r\n\r\n" holds no
    # "\n\n" to split on, so a two-paragraph description would arrive as
    # one paragraph with carriage returns inside the text node.
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        return None
    paragraphs = [p.strip() for p in body.split("\n\n")]
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph",
                     "content": [{"type": "text", "text": p}]}
                    for p in paragraphs if p],
    }


def _jira_field_list(given: Any) -> List[str]:
    """The fields to ask for, however the caller wrote them.

    A list is the documented shape and a comma-separated string is what a
    model writes about half the time, so both are accepted rather than one
    of them becoming a silent request for a field called
    "summary, status".
    """
    if isinstance(given, str):
        names = [n.strip() for n in given.split(",")]
    elif isinstance(given, (list, tuple)):
        names = [str(n).strip() for n in given]
    else:
        names = []
    names = [n for n in names if n]
    return names or list(_JIRA_FIELDS)


def _jira_search_body(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = args.get("limit")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = MAX_ITEMS
    limit = max(1, min(limit, MAX_ITEMS))
    return {"jql": str(args.get("jql") or "").strip(),
            "maxResults": limit,
            "fields": _jira_field_list(args.get("fields"))}


def _jira_issue_body(args: Dict[str, Any]) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "project": {"key": str(args.get("project_key") or "").strip()},
        "summary": str(args.get("summary") or "").strip(),
        "issuetype": {"name": str(args.get("issue_type")
                                  or _JIRA_DEFAULT_TYPE).strip()
                      or _JIRA_DEFAULT_TYPE},
    }
    doc = _jira_adf(args.get("description"))
    if doc:
        fields["description"] = doc
    return {"fields": fields}


def _jira_comment_body(args: Dict[str, Any]) -> Dict[str, Any]:
    doc = _jira_adf(args.get("comment"))
    return {"body": doc} if doc else {}


JIRA_TOOLS = [
    Tool(name="list_my_projects",
         summary="List the Jira projects you can see, with the key each one "
                 "uses for its issues.",
         method="GET", path="/project/search",
         unwrap=lambda d: (d or {}).get("values", []),
         keep=("id", "key", "name", "projectTypeKey")),
    Tool(name="search_issues",
         summary="Search your Jira issues with JQL, for example "
                 '"project = IO AND status != Done ORDER BY updated DESC".',
         method="POST", path="/search/jql",
         args={"jql": ("string",
                       "A JQL query. Fields are Jira's own: project, "
                       "status, assignee, created, updated. "
                       '"assignee = currentUser() AND resolution = '
                       'Unresolved" is everything open and mine.', True),
               "limit": ("integer", "How many issues to return, up to 25",
                         False),
               "fields": ("array",
                          "Which issue fields to bring back, as a list of "
                          'names like ["summary", "status"]. Leave it out '
                          "for the usual ones.", False)},
         shape=_jira_search_body,
         # A search changes nothing, whatever the method says.
         writes=False,
         unwrap=lambda d: (d or {}).get("issues", []),
         keep=("id", "key", "fields")),
    Tool(name="get_issue",
         summary="Read one Jira issue by its key, like IO-42.",
         method="GET", path="/issue/{issue_key}",
         args={"issue_key": ("string", "The issue key, like IO-42", True),
               "fields": ("string",
                          "Optional comma-separated field names. Leave it "
                          "out for the usual ones.", False)},
         query={"fields": "fields"},
         query_defaults={"fields": ",".join(_JIRA_FIELDS)},
         keep=("id", "key", "fields")),
    Tool(name="create_issue",
         summary="Create a Jira issue in one of your projects.",
         method="POST", path="/issue",
         args={"project_key": ("string",
                               "The project key from list_my_projects, like "
                               "IO", True),
               "summary": ("string", "The issue's title", True),
               "description": ("string", "Optional detail", False),
               "issue_type": ("string",
                              'The issue type, like Task, Bug or Story. '
                              "Defaults to Task.", False)},
         shape=_jira_issue_body,
         keep=("id", "key", "self")),
    Tool(name="comment_on_issue",
         summary="Add a comment to one of your Jira issues.",
         method="POST", path="/issue/{issue_key}/comment",
         args={"issue_key": ("string", "The issue key, like IO-42", True),
               "comment": ("string", "What to say", True)},
         shape=_jira_comment_body,
         keep=("id", "created", "author")),
    Tool(name="whoami",
         summary="Show which Jira account is currently connected to your "
                 "assistant.",
         method="GET", path="/myself",
         keep=("accountId", "displayName", "emailAddress", "timeZone")),
]

# --- Dropbox ---------------------------------------------------------------
#
# Three vendor facts shape these, and each one is a connector that quietly
# does not work if it is got wrong.
#
# THE ROOT FOLDER IS THE EMPTY STRING. "/" is not the root to Dropbox, it
# is an invalid path, and "Documents" with no leading slash is invalid
# too. A model asked to list somebody's files writes one of those about
# half the time, so the normalising is on this side.
#
# EVERYTHING IS A POST, reads included, with the arguments in a JSON body.
# There is no GET endpoint anywhere in the v2 API, which is also why the
# connect probe is a POST.
#
# search_v2 BURIES EACH FILE TWO LEVELS DOWN, under
# matches[].metadata.metadata. One level of unwrapping leaves a list of
# envelopes with no name in them.

#: Fields worth keeping off a file or folder entry. ".tag" is how a folder
#: is told from a file, and without it a listing is ambiguous.
_DROPBOX_KEEP = (".tag", "name", "path_display", "id", "size",
                 "server_modified")


def _dropbox_path(given: Any) -> str:
    """A path Dropbox will accept.

    The root is "", not "/". A leading slash is required everywhere else.
    """
    path = str(given or "").strip()
    if path in ("", "/", "root", "~", "."):
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or ""


def _dropbox_limit(given: Any) -> int:
    try:
        limit = int(given)
    except (TypeError, ValueError):
        return MAX_ITEMS
    return max(1, min(limit, MAX_ITEMS))


def _dropbox_folder_body(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"path": _dropbox_path(args.get("path")),
            "limit": _dropbox_limit(args.get("limit")),
            # Recursive on a real account is a very long answer to "what
            # is in my Dropbox", and the result is capped anyway, so it
            # would be a long wait for an arbitrary slice.
            "recursive": False}


def _dropbox_search_body(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        # Dropbox answers 400 to an empty query, and by then the model has
        # spent a round to be told nothing.
        return {}
    return {"query": query,
            "options": {"max_results": _dropbox_limit(args.get("limit"))}}


DROPBOX_TOOLS = [
    Tool(name="list_folder",
         summary="List the files and folders in one of your Dropbox "
                 "folders. Leave the path out for the top level.",
         method="POST", path="/files/list_folder",
         args={"path": ("string",
                        "The folder, like /Documents. Leave it out or "
                        "give \"/\" for the top level.", False),
               "limit": ("integer", "How many entries to return", False)},
         shape=_dropbox_folder_body,
         writes=False,
         unwrap=lambda d: (d or {}).get("entries", []),
         keep=_DROPBOX_KEEP),
    Tool(name="search_files",
         summary="Search your Dropbox for files and folders by name.",
         method="POST", path="/files/search_v2",
         args={"query": ("string", "Words to look for in the name", True),
               "limit": ("integer", "How many results to return", False)},
         shape=_dropbox_search_body,
         writes=False,
         unwrap=lambda d: [
             (m.get("metadata") or {}).get("metadata") or {}
             for m in ((d or {}).get("matches") or [])],
         keep=_DROPBOX_KEEP),
    Tool(name="get_metadata",
         summary="Read the details of one Dropbox file or folder: its "
                 "size, when it changed, and whether it is a folder.",
         method="POST", path="/files/get_metadata",
         args={"path": ("string", "The file or folder, like /a/b.pdf", True)},
         shape=lambda a: {"path": _dropbox_path(a.get("path"))},
         writes=False,
         keep=_DROPBOX_KEEP),
    Tool(name="whoami",
         summary="Show which Dropbox account is currently connected to "
                 "your assistant.",
         method="POST", path="/users/get_current_account",
         writes=False,
         keep=("account_id", "email", "name")),
]

# --- LinkedIn --------------------------------------------------------------
#
# The narrowest connector here, because LinkedIn's open permissions are
# narrow: openid, profile and email name the person, w_member_social
# posts as them, and everything else (a feed, connections, a company page,
# any analytics) is partner-gated. Read off LinkedIn's own documentation
# on 2026-11-13, not from a guide.
#
# THE ENDPOINT IS /v2/ugcPosts. The newer /rest/posts belongs to the
# Versioned API that Community Management uses, so a connector written
# from the newest-looking page asks for access nobody has granted us.
#
# A SHARE NEEDS THE AUTHOR'S PERSON URN, and no tool call carries it. The
# prepare step fetches it from /userinfo, which is the same seam ClickUp
# uses to turn a list name into an id.

#: The word, and only this word, that narrows a post to first-degree
#: connections. Anything else means public, because a typo must not
#: quietly change who can see somebody's post.
_LINKEDIN_CONNECTIONS = "connections"


def _linkedin_post_body(args: Dict[str, Any]) -> Dict[str, Any]:
    text = str(args.get("text") or "").strip()
    author = str(args.get("author") or "").strip()
    if not text or not author:
        return {}
    audience = str(args.get("audience") or "").strip().lower()
    content: Dict[str, Any] = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }
    url = str(args.get("url") or "").strip()
    if url:
        media: Dict[str, Any] = {"status": "READY", "originalUrl": url}
        title = str(args.get("title") or "").strip()
        if title:
            media["title"] = {"text": title}
        content["shareMediaCategory"] = "ARTICLE"
        content["media"] = [media]
    return {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": content},
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility":
                "CONNECTIONS" if audience == _LINKEDIN_CONNECTIONS
                else "PUBLIC"},
    }


LINKEDIN_TOOLS = [
    Tool(name="whoami",
         summary="Show which LinkedIn account is currently connected to "
                 "your assistant.",
         method="GET", path="/userinfo",
         writes=False,
         keep=("sub", "name", "email")),
    Tool(name="create_post",
         summary="Publish a post on LinkedIn as you. It goes out under "
                 "your own name and is PUBLIC unless you ask for "
                 "connections only.",
         method="POST", path="/ugcPosts",
         args={"text": ("string", "What the post says", True),
               "url": ("string",
                       "Optional link to share. The post then shows a "
                       "preview card for it.", False),
               "title": ("string", "Optional title for the link", False),
               "audience": ("string",
                            'Who can see it: "public" (the default) or '
                            '"connections".', False)},
         shape=_linkedin_post_body,
         keep=("id",)),
]

PROVIDER_TOOLS: Dict[str, List[Tool]] = {
    "github": GITHUB_TOOLS,
    "clickup": CLICKUP_TOOLS,
    "trello": TRELLO_TOOLS,
    "notion": NOTION_TOOLS,
    "n8n": N8N_TOOLS,
    "airtable": AIRTABLE_TOOLS,
    "hubspot": HUBSPOT_TOOLS,
    "zapier": ZAPIER_TOOLS,
    "jira": JIRA_TOOLS,
    "dropbox": DROPBOX_TOOLS,
    "linkedin": LINKEDIN_TOOLS,
}

#: Every tool of every provider, for checks that should hold everywhere.
ALL_TOOLS_FLAT = [t for tools in PROVIDER_TOOLS.values() for t in tools]

#: A declared type a model can act on. `array` is here because the ClickUp
#: catalogue carries real array fields now: declaring one a string is what
#: let a model send an email address where ClickUp wanted [252150963]
#: (2026-11-09). A type missing from this map reads as a string, which is
#: why "number" is absent and harmless: ClickUp's ids arrive as text.
_TYPES = {"string": (str, ""), "integer": (int, 0), "boolean": (bool, False),
          "array": (list, None), "object": (dict, None)}


def _model_for(provider_id: str, tool: Tool):
    """A pydantic model per tool, so the generated OpenAPI names each argument
    and mcp-proxy hands the model a real schema instead of a free-form blob.

    **The description goes in the schema (2026-11-10).** It used to be
    unpacked here and thrown away, so every word written for a model about
    an argument was lost on the way out: that an assignee may be a name or
    an email, that a status is the column as the list names it, that a
    list_id may be the list's name. The model was handed a field name and
    a type. mcp-proxy caches this document and `describe_tools` serves it,
    so this is the only channel there is, and a lookup nothing announces
    is a lookup nothing uses.

    It survived because every test for that wording asserted
    `tool.args[field][1]`, which was right all along. Nothing read what
    was served. See test_the_model_is_told_what_an_argument_means.py,
    which goes through the HTTP surface for that reason.

    `Field(...)` marks a field required while still putting a value in the
    class namespace, which is what lets a required field carry a
    description too. The old code had to leave required fields out of the
    namespace entirely, and that is why they could not have one.
    """
    annotations = {}
    ns: Dict[str, Any] = {}
    for name, (kind, desc, required) in (tool.args or {}).items():
        py, _unused = _TYPES.get(kind, (str, ""))
        annotations[name] = py if required else Optional[py]
        ns[name] = Field(... if required else None,
                         description=str(desc or "").strip() or None)
    ns["__annotations__"] = annotations
    return type(provider_id.title() + tool.name.title().replace("_", "") + "Args",
                (BaseModel,), ns)


def _sub_app(provider_id: str, tools: List[Tool]) -> FastAPI:
    prov = C.provider(provider_id)
    app = FastAPI(title=(prov.label if prov else provider_id) + " (your account)",
                  description="Tools that act as the signed-in user's own "
                              + (prov.label if prov else provider_id)
                              + " account, never the platform's.",
                  version="1.0.0")

    for tool in tools:
        model = _model_for(provider_id, tool)

        def make(tool=tool, model=model):
            async def handler(body=None, user=Depends(current_user)):
                args = body.model_dump(exclude_none=True) if body else {}
                return await _call(provider_id, tool, user.email, args)
            # Set explicitly rather than written in the signature: the model is
            # built per tool at runtime, so a literal annotation would name a
            # local that FastAPI cannot resolve.
            handler.__annotations__ = {"body": Optional[model],
                                       "user": CurrentUser}
            return handler

        app.post("/" + tool.name, summary=tool.summary,
                 name=tool.name)(make())
    return app


def build_app() -> FastAPI:
    """One parent app mounting a sub-app per provider, so each provider serves
    its own openapi.json at `/<provider>/openapi.json`, which is exactly what
    mcp-proxy fetches when it discovers a server."""
    parent = FastAPI(title="Per-user tools")
    for provider_id, tools in PROVIDER_TOOLS.items():
        parent.mount("/" + provider_id, _sub_app(provider_id, tools))
    return parent
