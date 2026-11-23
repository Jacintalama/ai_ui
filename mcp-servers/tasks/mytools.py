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
import datetime
import json
import logging
import re
from dataclasses import dataclass, field as _dc_field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote as _quote
import n8n_nodes
import aiui_link

import httpx
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

import connection_health as H
import host_guard
import connections as C
from auth import current_user, CurrentUser

logger = logging.getLogger("tasks.mytools")

#: Most rows any tool returns. A whole API page buries the answer and eats the
#: model's context; nobody asks "list my repos" wanting 200 of them.
MAX_ITEMS = 25

VENDOR_TIMEOUT_SEC = 20

#: Path arguments whose value really is a path, so `/` keeps its meaning
#: (GitHub's file path). Every other value is one segment. See _call.
_SLASHES_ALLOWED = frozenset({"path"})


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
    #: Extra request headers for THIS tool, built from the arguments.
    #:
    #: For a vendor that takes an argument in a header rather than a body.
    #: Dropbox's file download is the first: `Dropbox-API-Arg` carries the
    #: path and the body must be empty, so there is nowhere else to put it.
    #:
    #: Only ever sent to the vendor's own hosts, alongside the credential
    #: and under the same test, because a header built from a person's
    #: arguments is their data and a stranger has no claim on it either.
    #:
    #: Signature is `head(args) -> dict`. A ValueError reaches the model as
    #: a sentence, like `shape`.
    head: Optional[Callable[[Dict[str, Any]], Dict[str, str]]] = None
    #: Read the answer from a response that is NOT JSON.
    #:
    #: A download answers with the file's bytes, and its metadata comes
    #: back in a response header. Without this the body is thrown away by
    #: `_no_body_result` and the tool answers "done" having read nothing.
    #:
    #: Signature is `raw(body: bytes, headers) -> Any`. Taking the two
    #: pieces rather than the response object is what lets it be tested
    #: without a vendor, a network or httpx.
    raw: Optional[Callable[..., Any]] = None
    #: The RAW request body, for a vendor that wants the thing itself
    #: rather than JSON describing it.
    #:
    #: Dropbox uploads a file by PUTting its bytes with the destination in
    #: a header, which `_payload_for` cannot express: there is no JSON
    #: body at all. So this returns the bytes and `_call` sends them in
    #: place of a payload.
    #:
    #: ONLY EVER TO THE VENDOR'S OWN HOST, and this one matters more than
    #: the header rule above it. A JSON payload is built from our own
    #: shapers; a raw body IS the person's file, so sending it to a
    #: stranger would hand somebody's document to a third party rather
    #: than leak a credential. `_call` refuses outright rather than
    #: stripping anything.
    #:
    #: Signature is `send(args) -> bytes`. A ValueError reaches the model
    #: as a sentence, like `head` and `shape`.
    send: Optional[Callable[[Dict[str, Any]], bytes]] = None
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
    #: A tool that does its own work as this person, writes included,
    #: instead of one vendor call. `run` cannot: it only gets a GET.
    #: `link_aiui` (2026-11-19) makes an AIUI key and saves it in the
    #: person's n8n, which is a POST and needs to know whose key to make.
    #:
    #: Signature is `act(email, auth, args) -> dict`. `method` and `path`
    #: are unused.
    act: Optional[Callable[..., Any]] = None


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


def _no_body_result(tool: "Tool") -> Dict[str, Any]:
    """What to answer when the vendor sent no body at all.

    Graph answers sendMail with 202 Accepted and nothing else, and it is
    not alone in that. The old blanket fallback was `items: []`, which is
    the right answer to a search that found nothing and exactly the wrong
    answer to a send: a model told "items: []" after being asked to send
    an email has every reason to believe it did not go, and to try again.

    So a WRITE that came back empty says it was done, and a read that came
    back empty still says nothing was found.
    """
    # `_writes`, not `tool.writes`. The field is None on almost every write
    # ("ask the method"), so asking it directly sent Todoist's 204 on
    # completing a task back as `items: []` (2026-11-23).
    if _writes(tool):
        return {"ok": True, "done": True}
    return {"ok": True, "items": []}


def _same_host(vendor_base: str, tool_base: str) -> bool:
    """Whether a tool's base is still the vendor the credential is for.

    No base at all is the ordinary case and is the vendor. Anything that
    cannot be parsed counts as elsewhere, which is the safe direction:
    a base nobody can read is not proof it is the same vendor, and the
    cost of guessing wrong is somebody's credential.

    Scheme counts. http to the same name is still refused, because a
    credential must not be sent in the clear.
    """
    base = str(tool_base or "").strip()
    if not base:
        return True
    try:
        from urllib.parse import urlsplit
        a, b = urlsplit(str(vendor_base or "")), urlsplit(base)
        if not a.hostname or not b.hostname:
            return False
        return (a.hostname.lower() == b.hostname.lower()
                and (a.scheme or "").lower() == (b.scheme or "").lower()
                and a.port == b.port)
    except Exception:                                       # noqa: BLE001
        return False


#: A vendor's OTHER hostnames, the ones its own credential belongs to.
#:
#: `_same_host` compares hostnames, which is the right test for "is this
#: still the vendor" almost everywhere and the wrong one for a vendor that
#: splits its API across two names. Dropbox is the first: RPC calls go to
#: api.dropboxapi.com and file CONTENT to content.dropboxapi.com, both
#: take the same bearer token, and neither can be inferred from the other.
#:
#: Named explicitly, per provider, so the guard keeps its shape: a host
#: nobody listed is still a stranger and still gets no credential. That is
#: what stops an n8n tool reading the public template library at
#: api.n8n.io from carrying a self-hosted X-N8N-API-KEY to n8n's cloud.
VENDOR_HOSTS: Dict[str, tuple] = {
    "dropbox": ("content.dropboxapi.com",),
}


def _is_vendor_host(provider_id: str, tool_base: str) -> bool:
    """Whether a tool's base is a SECOND host of the same vendor.

    https only, for the same reason `_same_host` insists on it: a
    credential must not be sent in the clear, and a name on a list is not
    a reason to relax that.

    No base at all is False here rather than True: this answers "is this
    other host the vendor", and `_same_host` already answers the ordinary
    case. A default of True would hand every credential to every tool
    that named no base, which is the opposite of the question.
    """
    base = str(tool_base or "").strip()
    if not base:
        return False
    try:
        from urllib.parse import urlsplit
        u = urlsplit(base)
        if (u.scheme or "").lower() != "https" or not u.hostname:
            return False
        allowed = tuple(h.lower() for h in (VENDOR_HOSTS.get(provider_id) or ()))
        return u.hostname.lower() in allowed
    except Exception:                                       # noqa: BLE001
        return False


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
    """Whether this tool changes anything at the vendor.

    A COMPOSITE CANNOT WRITE, whatever `method` says. `run` is handed
    `get(path)`, which does one authenticated GET, and nothing else, and
    `method` on such a tool is documented as unused. Asking the method
    made ClickUp's `find_list` a write, so a 403 while climbing somebody's
    workspace told them to reconnect to allow writing, which would not
    have helped: a 403 there is a space they cannot see.
    """
    if tool.writes is not None:
        return bool(tool.writes)
    if tool.run:
        return False
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
            # GraphQL's dialect (Linear, 2026-11-23): a LIST of objects,
            # each with its own message.
            listed = payload.get("errors")
            if isinstance(listed, list) and listed:
                found = "; ".join(
                    str(e.get("message") if isinstance(e, dict) else e)
                    for e in listed[:3])
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


async def _outlook_prepare(tool_name, args, get):
    """Put a time window on a calendar read.

    calendarView REQUIRES startDateTime and endDateTime and answers
    400 without them. A model asked "what is on my calendar" has no
    reason to know that, so the window is supplied here rather than
    left to be discovered.
    """
    if tool_name != "list_events":
        return args, None
    args = dict(args or {})
    args.update(_outlook_window(args))
    return args, None


def _n8n_json(value, field: str):
    """A list or dict, whether it arrived as one or as JSON in a string.

    A model writes JSON into a string argument far more often than it
    builds the structure, and n8n answers 400 either way without saying
    which part it minded.
    """
    if isinstance(value, (list, dict)):
        return value
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except Exception:                                       # noqa: BLE001
        raise ValueError(
            "The %s could not be read as JSON. Send it as a list of node "
            "objects, or as JSON text." % field)


def _n8n_set_is_empty(node) -> bool:
    """A Set node whose assignments are empty, in either shape.

    v3 nests them, {"assignments": {"assignments": [...]}}, and older
    ones use {"values": {"string": [...]}}. Only the v3 shape is judged,
    because a `values` block is what anybody copying a real template
    will have and refusing those would block the one reliable way to get
    a node right.
    """
    if not isinstance(node, dict):
        return False
    if not str(node.get("type") or "").endswith(".set"):
        return False
    params = node.get("parameters")
    if not isinstance(params, dict):
        return False
    if "values" in params:
        return False
    block = params.get("assignments")
    if isinstance(block, dict):
        return not (block.get("assignments") or [])
    if isinstance(block, list):
        return not block
    return False


def _n8n_check(nodes, conns) -> None:
    """Refuse the two shapes that make a workflow which cannot do
    anything. n8n will not: it has no opinion about whether yours is
    finished, so it accepts both happily and you find out in the canvas.

    Measured 2026-11-18, from a real request for "a manual trigger and a
    Set node that sets message = hello from IO":

        nodes: Manual Trigger, Set message with "assignments": []
        connections: {}

    The model was not being careless. n8n exposes no node schema to an
    API key at all, so a refusal that says the shape is one of only two
    places it can learn one; the other is the argument descriptions.

    Deliberately narrow: two shapes we have actually seen, not a
    validator with opinions about n8n's hundreds of nodes.
    """
    named = [n for n in nodes if isinstance(n, dict)]
    aiui_link.check_steps(named)
    if len(named) > 1 and not conns:
        first = str(named[0].get("name") or "the first node")
        second = str(named[1].get("name") or "the next one")
        raise ValueError(
            "These %d nodes are not connected to anything, so the "
            "workflow would do nothing. `connections` is keyed by the "
            "SOURCE NODE'S NAME, not its id. To join them: "
            '{"%s": {"main": [[{"node": "%s", "type": "main", '
            '"index": 0}]]}}' % (len(named), first, second))
    for node in named:
        if _n8n_set_is_empty(node):
            raise ValueError(
                '"%s" is a Set node with nothing to set, so it would '
                "pass its input straight through. Its parameters need "
                'the nested shape: {"mode": "manual", "assignments": '
                '{"assignments": [{"id": "a1", "name": "message", '
                '"value": "hello", "type": "string"}]}}'
                % str(node.get("name") or "A Set node"))


#: What a model is told about building nodes. Generated from the
#: catalogue rather than written out here, so the shapes a model is
#: given and the shapes the code builds can never drift apart. The
#: catalogue itself was read off the live instance; see n8n_nodes.
_NODE_HELP = (
    "The nodes, as n8n writes them. Each needs id, name, type, "
    "typeVersion, position and parameters. Use these exact types and "
    "typeVersions, which are the ones this n8n writes:\n\n"
    + n8n_nodes.describe()
    + "\n\nA workflow needs a trigger to be switched on, and a manual "
      "trigger does not count. Two or more nodes with nothing joining "
      "them is refused."
)


def _n8n_forms(item, base: str) -> list:
    """Where each form in this workflow actually answers, or why nowhere.

    A fact with no tool behind it gets invented. Asked on 2026-11-18 for a
    form's URL, the chat produced `n8n.srv1041674.hstgr.io/form/<workflow
    id>`: the wrong host, which appears nowhere in this repo, and the wrong
    path, because n8n serves a form at the trigger node's own `path` or
    `webhookId` and never at the workflow id. The person then spent two
    replies being told to flush their DNS and check their router over an
    NXDOMAIN that a made-up hostname had caused.

    The host is already in the credential the call just used, so it is
    never guessed here. And a form trigger created over the API carries
    neither `path` nor `webhookId` (n8n assigns one in the editor), so the
    honest answer in that case is that the form has no address at all,
    which is the answer the model had no way to give.
    """
    forms = []
    for node in (item.get("nodes") or []):
        if not str(node.get("type") or "").endswith("formTrigger"):
            continue
        where = (node.get("parameters") or {}).get("path") or \
            node.get("webhookId")
        name = node.get("name")
        if where:
            forms.append({"node": name,
                          "url": "%s/form/%s" % (str(base).rstrip("/"),
                                                 where)})
        else:
            forms.append({
                "node": name, "url": None,
                "why": "this form has no address yet: the node carries no "
                       "path and n8n has not given it a webhook id, which "
                       "it does when the trigger is opened in the editor"})
    return forms


def _n8n_workflow_body(args):
    given = args or {}
    nodes = _n8n_json(given.get("nodes"), "nodes")
    conns = _n8n_json(given.get("connections"), "connections")
    _n8n_check(nodes if isinstance(nodes, list) else [],
               conns if isinstance(conns, dict) else {})
    body = {"name": given.get("name") or "",
            "nodes": nodes if isinstance(nodes, list) else [],
            "connections": conns if isinstance(conns, dict) else {},
            # What n8n's own UI writes, and what the real instance
            # accepted on 2026-11-17. Some versions refuse a create with
            # no settings at all.
            "settings": {"executionOrder": "v1"}}
    # `active` is DELIBERATELY absent. n8n creates inactive by itself
    # (measured: active=False straight after a create), and a workflow
    # that starts running the moment a model wrote it is the thing
    # nobody asked for.
    return body


async def _n8n_prepare(tool_name, args, get):
    """Refuse to delete a workflow that is currently running.

    n8n 2.x carries `isArchived` on the record and its public API has no
    verb to set it (POST .../archive answers 405), so DELETE is a hard
    delete with nothing to undo it. Twelve of the thirty-two workflows on
    the instance this was built against run unattended.

    Deactivating first makes destroying a running automation two
    deliberate steps instead of one mistaken one.

    A lookup that could not be made does NOT refuse: `get` returns None
    then, and treating an unreachable instance as a protected workflow
    would turn an outage into a permissions error. The vendor decides in
    the end either way.
    """
    if tool_name != "delete_workflow":
        return args, None
    wid = str((args or {}).get("workflow_id") or "").strip()
    if not wid:
        return args, None
    found = await get("/api/v1/workflows/" + wid)
    if not isinstance(found, dict):
        return args, None
    if found.get("active"):
        name = found.get("name") or wid
        return args, (
            "%r is active, so it is running on its own right now, and n8n "
            "has no way to undo a delete. Deactivate it first, then delete "
            "it." % name)
    return args, None


PREPARE = {"clickup": _clickup_prepare, "trello": _trello_prepare,
           "linkedin": _linkedin_prepare,
           "outlook": _outlook_prepare,
           "n8n": _n8n_prepare,
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
    if (provider_id == "github" and r.status_code == 422
            and "own pull request" in (getattr(r, "text", "") or "").lower()):
        # GitHub puts this reason in `errors`, a LIST, and `message` says
        # only "Unprocessable Entity" (2026-11-19).
        return ("GitHub does not let you approve your own pull request. "
                "Someone else has to review it.")
    if r.status_code == 404:
        return label + " could not find that." + _vendor_said(r, creds)
    if r.status_code < 400 and _graphql_refused(r):
        # A GraphQL vendor refuses with 200 (Linear, 2026-11-23): the body
        # is {"errors": [...]} and the data is null. Read as a success, a
        # failed create reached the model as done.
        return label + " refused that." + _vendor_said(r, creds)
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


def _graphql_refused(r) -> bool:
    """Whether a 2xx answer is really a GraphQL refusal.

    A property of the body, not a list of vendors: `errors` is a non-empty
    list AND nothing usable came back, meaning `data` is absent, null, or
    every root field in it is null. A partial answer, where some data did
    come back beside an error, is still an answer.
    """
    try:
        payload = r.json()
    except Exception:                                       # noqa: BLE001
        return False
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors")
    if not (isinstance(errors, list) and errors):
        return False
    data = payload.get("data")
    if data is None:
        return True
    return isinstance(data, dict) and all(v is None for v in data.values())


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

    # The connect resolved this host once. A name that answered public then
    # and points inside a week later is requested on every call after that,
    # and the literal rule in `vendor_auth` above cannot see it because it
    # is a name rather than an address. So the lookup runs here too, before
    # ANY of the three request paths below: the single call, a prepare
    # step's reads, and a composite tool's walk.
    #
    # Only for a provider whose address the person typed. A vendor host
    # written in our own source is not user input, and asking DNS about
    # api.trello.com on every tool call would be cost with nothing bought.
    #
    # What is still not claimed: a name that answers public to this lookup
    # and private to the socket a moment later. That needs the resolved
    # address pinned through to the connection, which httpx does not hand
    # over without reaching under it. This closes the week-long window; it
    # does not close the millisecond one.
    if C.types_a_url(provider_id):
        inside = await host_guard.problem(auth.base_url)
        if inside:
            logger.warning("mytools: %s points at an address inside the "
                           "network; refused", provider_id)
            return _err(inside)

    if tool.act:
        try:
            return await tool.act(email, auth, args or {})
        except Exception as e:                              # noqa: BLE001
            logger.warning("mytools: %s %s failed (%s)", provider_id,
                           tool.name, type(e).__name__)
            return _err(label + ": that could not be done just now. Try "
                        "again in a minute.")

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

    # A VALUE STAYS IN ITS OWN SEGMENT. It went in raw, and httpx folds
    # `..`, so `tag="../../space/1"` on a remove-tag DELETE reached a
    # different endpoint, and `#` cut the path short. Since 2026-11-19 a
    # write approved once runs unattended from n8n with values an earlier
    # step filled in from outside (a webhook, an email subject), so the
    # approved endpoint has to be the one that runs. Encoded, `?`, `#` and
    # `/` cannot leave the segment; a `..` segment is refused outright,
    # because httpx folds it even inside a file path.
    path = tool.path
    for key, value in (args or {}).items():
        placeholder = "{" + key + "}"
        if placeholder in path:
            text = str(value)
            if ".." in text.split("/"):
                return _err("%s cannot contain a \"..\" segment." % key)
            path = path.replace(placeholder, _quote(
                text, safe="/" if key in _SLASHES_ALLOWED else ""))
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

    # A SHAPER MAY REFUSE, and its refusal has to reach the model as an
    # answer. This sat outside the try, so a ValueError from `shape`
    # escaped the whole call: a chat turn got a 500 and never saw the
    # sentence telling it what to fix. Found by running it live on
    # 2026-11-18, after the unit tests were green, because those call
    # the shaper directly and assert the raise.
    #
    # A refusal that cannot be read is a crash with good intentions.
    try:
        payload = _payload_for(tool, args)
    except ValueError as e:
        return _err(str(e))

    # The AIUI key may only ride to our own route (aiui_link). Here and not
    # in the shaper because the credential id it is stored under is in the
    # database, and the shaper cannot wait on one.
    if provider_id == "n8n" and tool.name in ("create_workflow",
                                              "update_workflow"):
        problem = await aiui_link.credential_problem(
            email, (payload or {}).get("nodes") or [])
        if problem:
            return _err(problem)

    url = (tool.base or auth.base_url) + path
    # A CREDENTIAL ONLY GOES TO ITS OWN VENDOR. `base` lets one tool point
    # elsewhere, and the headers used to go out whatever it was set to, so
    # a tool reading n8n's PUBLIC template library at api.n8n.io would have
    # carried a self-hosted X-N8N-API-KEY to n8n's cloud: a credential
    # handed to a third party by a tool whose whole point is that it needs
    # none (2026-11-18, before any such tool existed).
    #
    # Same host, different path or version, still gets it: that is what
    # `base` is documented for ("moving the provider's base to v3"), and
    # it is the same vendor. Different host does not, because by
    # definition that is not the vendor the credential belongs to. The
    # query params go the same way, since Trello's credential rides there.
    own = (_same_host(auth.base_url, tool.base)
           or _is_vendor_host(provider_id, tool.base))
    if not own:
        params = _query_for(tool, args)

    # A header-carried argument, for a vendor with nowhere else to put it.
    # Built here and not inside the request so a refusal from it reads as
    # an answer, which is the lesson `shape` already carries above.
    sending = dict(auth.headers) if own else None
    if tool.head:
        try:
            extra = tool.head(args or {})
        except ValueError as e:
            return _err(str(e))
        if own and extra:
            sending.update(extra)

    # THE BODY ITSELF, for a vendor that takes the file rather than JSON
    # about it. Refused outright for a foreign host rather than stripped,
    # because this is not a credential that can be left behind: it is the
    # person's own document, and the only safe thing to do with it is not
    # to send it.
    content = None
    if tool.send:
        if not own:
            logger.warning("mytools: %s %s points at a host that is not the "
                           "vendor, so a file body was refused", provider_id,
                           tool.name)
            return _err(label + ": that could not be done just now. Try "
                        "again in a minute.")
        try:
            content = tool.send(args or {})
        except ValueError as e:
            return _err(str(e))

    try:
        async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SEC) as client:
            if content is None:
                r = await client.request(tool.method, url,
                                         headers=sending,
                                         params=params or None, json=payload)
            else:
                # Never both. httpx would set Content-Type for the JSON and
                # send the bytes, which is a request no vendor can read.
                r = await client.request(tool.method, url,
                                         headers=sending,
                                         params=params or None,
                                         content=content)
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

    # A response that was never meant to be JSON. Before the parse, not
    # after it: the bytes of a text file parse as JSON often enough
    # (a number, a quoted string, `true`) that falling through would read
    # some files and not others.
    if tool.raw:
        try:
            return {"ok": True, "item": _trim(tool.raw(r.content, r.headers),
                                              tool.keep)}
        except Exception:                                   # noqa: BLE001
            logger.warning("mytools: %s could not read %s body",
                           provider_id, tool.name)
            return _err(label + " answered with something this tool could "
                                "not read.")

    try:
        data = r.json()
    except Exception:
        return _no_body_result(tool)

    data = _as_list(data, tool)
    if isinstance(data, list):
        return {"ok": True, "count": len(data),
                "items": _trim(data[:MAX_ITEMS], tool.keep),
                "truncated": len(data) > MAX_ITEMS}
    item = _trim(data, tool.keep)
    out = {"ok": True, "item": item}
    if provider_id == "n8n" and isinstance(item, dict):
        forms = _n8n_forms(item, auth.base_url)
        if forms:
            out["forms"] = forms
        # The person approved this workflow (in the chat, or by giving the
        # agent that built it "all" access, which is how every other write
        # of that agent is approved), so its AIUI write steps become
        # runnable from their key (aiui_link). A key never reaches here:
        # the tools route refuses every n8n tool. Fails open: the
        # workflow exists either way, and a step left unapproved says so
        # when it runs.
        if tool.name in ("create_workflow", "update_workflow"):
            try:
                approved = await aiui_link.approve_steps(
                    email, (payload or {}).get("nodes") or [])
            except Exception as e:                          # noqa: BLE001
                logger.warning("mytools: approving AIUI steps failed (%s)",
                               type(e).__name__)
                approved = []
            if approved:
                out["approved_steps"] = approved
    return out


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

#: How many BYTES of a download are asked for, as a `Range` header.
#:
#: A char cap is no use on a download: by the time the characters can be
#: counted the bytes are already in this process, and somebody's cloud
#: storage holds video. This box has 3.8GB of RAM, so the cap goes on the
#: request and the rest is never sent.
#:
#: Four bytes per character is UTF-8's widest, so this cannot cut a file
#: that would have fit under MAX_FILE_CHARS.
MAX_FILE_BYTES = 4 * MAX_FILE_CHARS


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
         summary="Leave a plain comment on a pull request, written as you. "
                 "To approve it or ask for changes, use review_pull_request.",
         method="POST", path="/repos/{owner}/{repo}/issues/{number}/comments",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Pull request number", True),
               "body": ("string", "The comment, markdown is fine", True)},
         body=("body",),
         keep=("id", "html_url", "created_at")),
    Tool(name="review_pull_request",
         summary="Review a pull request as you: APPROVE it, "
                 "REQUEST_CHANGES on it, or leave a COMMENT review. GitHub "
                 "does not let anyone approve their own pull request.",
         method="POST", path="/repos/{owner}/{repo}/pulls/{number}/reviews",
         args={"owner": ("string", "Repository owner", True),
               "repo": ("string", "Repository name", True),
               "number": ("integer", "Pull request number", True),
               "event": ("string", "APPROVE, REQUEST_CHANGES or COMMENT",
                         True),
               "body": ("string", "What the review says. Needed for "
                                  "REQUEST_CHANGES and COMMENT, optional "
                                  "for APPROVE", False)},
         body=("event", "body"),
         writes=True,
         keep=("id", "state", "html_url", "submitted_at")),
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
         # Notion searches over POST because the query is a body. On a
         # read, a 403 means the page was never shared with the
         # integration, and "reconnect to allow that" is a wrong
         # instruction for it.
         writes=False,
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
         # Reads rows. POST because the filter and sort are a body.
         writes=False,
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
         writes=False,
         keep=("id", "name", "active", "updatedAt")),
    Tool(name="get_workflow",
         summary="Read one workflow from your n8n instance, given its id.",
         method="GET", path="/api/v1/workflows/{workflow_id}",
         args={"workflow_id": ("string", "Workflow id", True)},
         writes=False,
         # `connections` is not optional here. update_workflow tells
         # the model to read a workflow and send it back with its
         # changes, so anything this drops, an update destroys.
         # Found live 2026-11-18: created with connections, read
         # back with none.
         keep=("id", "name", "active", "nodes", "connections",
               "updatedAt")),
    Tool(name="list_executions",
         summary="List recent workflow runs on your n8n instance, newest first.",
         method="GET", path="/api/v1/executions",
         query={"limit": "limit", "status": "status"},
         args={"limit": ("integer", "How many to return", False),
               "status": ("string", "success, error or waiting", False)},
         unwrap=lambda d: d.get("data", d),
         writes=False,
         keep=("id", "workflowId", "status", "startedAt", "stoppedAt")),
    Tool(name="create_workflow",
         summary="Build a new workflow on your own n8n instance. It "
                 "is created switched OFF, so nothing runs until you "
                 "turn it on.",
         method="POST", path="/api/v1/workflows",
         args={"name": ("string", "What to call the workflow", True),
                              "nodes": ("array",
                         _NODE_HELP, True),
               "connections": ("object",
                               "Which node feeds which, keyed by the "
                               "SOURCE NODE'S NAME, never its id. To "
                               "join Manual Trigger to Set message: "
                               "{\"Manual Trigger\": {\"main\": "
                               "[[{\"node\": \"Set message\", "
                               "\"type\": \"main\", \"index\": "
                               "0}]]}}. Two or more nodes with no "
                               "connections is refused, because the "
                               "workflow would do nothing.",
                               False)},
         shape=_n8n_workflow_body,
         writes=True,
         keep=("id", "name", "active", "createdAt")),
    Tool(name="update_workflow",
         summary="Change a workflow on your own n8n instance: its "
                 "name, its nodes or how they connect. Sends the "
                 "whole workflow, so read it first and send it back "
                 "with your changes.",
         method="PUT", path="/api/v1/workflows/{workflow_id}",
         args={"workflow_id": ("string", "The workflow id", True),
               "name": ("string", "What to call it", True),
               "nodes": ("array", "The full set of nodes", True),
               "connections": ("object",
                               "Which node feeds which, keyed by the "
                               "source node's name", False)},
         shape=_n8n_workflow_body,
         writes=True,
         keep=("id", "name", "active", "updatedAt")),
    Tool(name="activate_workflow",
         summary="Switch a workflow ON so n8n runs it on its own. It "
                 "needs a real trigger: a webhook, a schedule or a "
                 "polling node. A MANUAL trigger is not enough and "
                 "n8n will refuse it.",
         method="POST",
         path="/api/v1/workflows/{workflow_id}/activate",
         args={"workflow_id": ("string", "The workflow id", True)},
         writes=True,
         keep=("id", "name", "active")),
    Tool(name="deactivate_workflow",
         summary="Switch a workflow OFF so n8n stops running it on "
                 "its own.",
         method="POST",
         path="/api/v1/workflows/{workflow_id}/deactivate",
         args={"workflow_id": ("string", "The workflow id", True)},
         writes=True,
         keep=("id", "name", "active")),
    Tool(name="delete_workflow",
         summary="Delete a workflow from your own n8n instance. This "
                 "cannot be undone: n8n has no trash. A workflow that "
                 "is currently switched on has to be switched off "
                 "first.",
         method="DELETE", path="/api/v1/workflows/{workflow_id}",
         args={"workflow_id": ("string", "The workflow id", True)},
         writes=True,
         keep=("id", "name")),
    Tool(name="link_aiui",
         summary="Link AIUI to your n8n, so a workflow can use the apps "
                 "you connected in AIUI without connecting them again. "
                 "Makes an AIUI key and saves it in your n8n as a "
                 "credential called AIUI, once; later calls return the "
                 "same credential id. Use the id on aiuiTool nodes.",
         method="POST", path="",
         args={"again": ("boolean", "Make a new credential and retire the "
                                    "old key, when the old one was deleted "
                                    "in n8n", False)},
         writes=True,
         act=aiui_link.link),
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


#: Where Dropbox serves file CONTENT. Not the same hostname as the rest of
#: the API, and listed in VENDOR_HOSTS so the credential still goes with it.
DROPBOX_CONTENT = "https://content.dropboxapi.com/2"


def _dropbox_arg(args: Dict[str, Any]) -> Dict[str, str]:
    """The headers for a download: the argument, and a cap on the answer.

    A content download takes no body at all. Its argument goes in
    `Dropbox-API-Arg`, and because that is an HTTP header it has to be
    ASCII: a path with an accent in it sent raw is a header a client or a
    proxy may refuse before Dropbox ever sees it. `json.dumps` escapes
    non-ASCII by default, which is exactly what Dropbox asks for.

    `Range` is what keeps a download bounded. See MAX_FILE_BYTES.
    """
    arg = json.dumps({"path": _dropbox_path(args.get("path"))})
    return {"Dropbox-API-Arg": arg,
            "Range": "bytes=0-%d" % (MAX_FILE_BYTES - 1)}


def _as_text(body: bytes) -> Optional[str]:
    """A file's text, or None when it is not text at all.

    Two tells, and both are needed. A NUL byte does not occur in UTF-8
    text and does occur in almost every binary format, including UTF-16,
    which would otherwise decode to something that looks like words. And
    a strict decode is what separates the rest.

    Strict, never "replace": a PDF decoded with "replace" is forty
    thousand replacement characters, which spends the turn and leaves an
    assistant describing junk as though it had read the document.

    THE TAIL RETRY is where the two safeguards meet. `Range` cuts at a
    byte, so the last character of a long file can arrive in halves, and
    that failure says nothing about whether the file is text. Up to three
    bytes come off the end before giving up, three being the longest
    incomplete UTF-8 sequence there is.
    """
    body = body or b""
    if b"\x00" in body:
        return None
    for drop in range(4):
        end = len(body) - drop
        if end < 0:
            break
        try:
            return body[:end].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def _dropbox_file(body: bytes, headers: Any = None) -> Dict[str, Any]:
    """One Dropbox file, read.

    The bytes are the file; the metadata arrives in a header, which is
    why this takes both. `size` from Dropbox is the WHOLE file's size,
    so comparing it with what arrived is how a capped download knows it
    is holding a slice and says so.
    """
    meta: Any = {}
    try:
        raw = (headers or {}).get("Dropbox-API-Result") or ""
        if raw:
            meta = json.loads(raw)
    except Exception:                                       # noqa: BLE001
        meta = {}
    if not isinstance(meta, dict):
        meta = {}

    body = body or b""
    path = meta.get("path_display") or meta.get("name") or ""
    size = meta.get("size")
    if not isinstance(size, int):
        size = len(body)

    text = _as_text(body)
    if text is None:
        return {"path": path, "size": size, "truncated": False, "content": "",
                # Said as a fact about the file, not as an error, because
                # nothing went wrong: a model told only "failed" retries,
                # and a model told nothing describes the junk.
                "why": "this is not a text file, so there is nothing to read "
                       "out of it. Its name, size and when it last changed "
                       "are still readable with get_metadata."}

    cut = len(text) > MAX_FILE_CHARS
    if cut:
        text = text[:MAX_FILE_CHARS]
    # The Range cap means a big file never fully arrives. Presenting the
    # first slice as the document is the quiet version of inventing it.
    if size > len(body):
        cut = True
    return {"path": path, "size": size, "truncated": cut, "content": text}


def _dropbox_upload_arg(args: Dict[str, Any]) -> Dict[str, str]:
    """The headers for a save: where it goes, and that it ADDS.

    `mode: add` with `autorename` is the whole safety of this tool, and
    it is the vendor's guarantee rather than a check of ours. A save onto
    an occupied path becomes "notes (1).txt" and the file that was there
    is untouched, which is what lets the catalogue go on saying Dropbox
    cannot change or delete anything while a write exists.

    A FOLDER IS NOT SOMEWHERE A FILE CAN BE SAVED, and this is the one
    argument a model gets wrong: `_dropbox_path` turns "/" into the root,
    which is the right answer for listing a folder and a file named
    nothing for this. Refused here, with the sentence saying what to send
    instead.
    """
    given = str(args.get("path") or "").strip()
    if not given or given.endswith("/") or not _dropbox_path(given):
        raise ValueError("Give the file name as well as the folder, like "
                         "/Documents/notes.txt. A folder on its own is not "
                         "somewhere a file can be saved.")
    arg = json.dumps({"path": _dropbox_path(given), "mode": "add",
                      "autorename": True, "mute": False})
    return {"Dropbox-API-Arg": arg,
            "Content-Type": "application/octet-stream"}


def _dropbox_bytes(args: Dict[str, Any]) -> bytes:
    """The file itself, bounded before it is sent.

    Same reasoning as the download's `Range` cap, from the other
    direction: this box has 3.8GB of RAM and a model asked to "save
    everything we discussed" will write as much as it is allowed to.

    `None` and "" are DIFFERENT. An empty file is a perfectly good thing
    to save, so only a content argument that was never given is refused.
    """
    content = args.get("content")
    if content is None:
        raise ValueError("Say what to put in the file, as `content`.")
    text = str(content)
    body = text.encode("utf-8")
    if len(body) > MAX_FILE_BYTES:
        raise ValueError("That is too long to save in one go. The most is "
                         "about %d characters and this is %d, so save it in "
                         "parts or shorten it." % (MAX_FILE_CHARS, len(text)))
    return body


def _dropbox_direct_link(url: Any) -> str:
    """A share link that downloads, rather than opening Dropbox's viewer.

    Dropbox hands back a PREVIEW link, ending `dl=0`. Somebody who says
    "so they can download it" means `dl=1`, and both are worth returning
    because the preview is the better link to send a person and the
    direct one is the better link to give a program.

    Rebuilt through the query parser rather than by string replacement,
    because the `rlkey` in a modern share link is what makes it work and
    a careless replace is how it gets lost.
    """
    text = str(url or "")
    if not text:
        return ""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(text)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k != "dl"]
    query.append(("dl", "1"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def _dropbox_link_from_error(payload: Any) -> Optional[str]:
    """The existing link, read out of Dropbox's own refusal to make one.

    A second request for a link is always a 409, and the link is usually
    inside it, so the ordinary case costs no extra round trip. `metadata`
    can be absent (the inner object comes back tagged `other`), and then
    this returns None and the caller asks properly.
    """
    try:
        inner = ((payload or {}).get("error") or {}).get(
            "shared_link_already_exists") or {}
        url = str((inner.get("metadata") or {}).get("url") or "").strip()
        return url or None
    except Exception:                                       # noqa: BLE001
        return None


def _dropbox_said(payload: Any) -> str:
    """Dropbox's own words for a failure, when it gave any."""
    try:
        said = str((payload or {}).get("error_summary") or "").strip()
        return (" Dropbox said: " + said.rstrip("/. ") + ".") if said else ""
    except Exception:                                       # noqa: BLE001
        return ""


async def _dropbox_share(email: str, auth, args: Dict[str, Any]) -> dict:
    """The `share_link` tool: a link for one file, made or recovered.

    An `act` tool because this is a request whose FAILURE is the answer,
    and sometimes a second request after it. `_call` cannot express that:
    `_refusal` turns every 409 into a sentence and returns. Putting a
    conflict seam there would push one vendor's quirk into the path of
    every provider, so the two-step lives here.
    """
    path = _dropbox_path((args or {}).get("path"))
    if not path:
        return _err("Give the file to share, with its name, like "
                    "/Documents/notes.txt. A share link is for one file.")

    base = str(auth.base_url or "").rstrip("/")

    def _body(r):
        try:
            return r.json() or {}
        except Exception:                                   # noqa: BLE001
            return {}

    def _answer(url: str, existing: bool) -> dict:
        return {"ok": True, "path": path, "url": url,
                "download_url": _dropbox_direct_link(url),
                "existing": existing}

    try:
        async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SEC) as client:
            made = await client.post(
                base + "/sharing/create_shared_link_with_settings",
                headers=auth.headers, json={"path": path})
            payload = _body(made)

            if made.status_code < 300:
                url = str(payload.get("url") or "").strip()
                if url:
                    return _answer(url, False)
                return _err("Dropbox made a share link but did not say what "
                            "it was.")

            # The token was approved before sharing was asked for, which
            # is true of every connection made before 2026-11-20.
            if str((payload.get("error") or {}).get(".tag")) == "missing_scope":
                return _err("Your Dropbox connection does not include "
                            "permission to share files. Reconnect Dropbox "
                            "from Connections and approve the new "
                            "permission, then ask again.")

            if made.status_code != 409:
                logger.warning("mytools: dropbox share_link returned %s",
                               made.status_code)
                return _err("Dropbox would not make a share link for that."
                            + _dropbox_said(payload))

            # 409 is the ORDINARY case: the file already has a link.
            url = _dropbox_link_from_error(payload)
            if url:
                return _answer(url, True)

            listed = await client.post(base + "/sharing/list_shared_links",
                                       headers=auth.headers,
                                       json={"path": path,
                                             "direct_only": True})
            found = _body(listed)
            links = found.get("links") if isinstance(found, dict) else None
            first = (links or [{}])[0] if links else {}
            url = str((first or {}).get("url") or "").strip()
            if url:
                return _answer(url, True)
            return _err("That file already has a share link, but Dropbox "
                        "would not give it back. Open the file in Dropbox "
                        "and use Share there to copy the link.")
    except Exception as e:                                  # noqa: BLE001
        # Never the message: a vendor's exception text can carry the URL.
        logger.warning("mytools: dropbox share_link failed (%s)",
                       type(e).__name__)
        return _err(_unreachable("Dropbox"))


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
    # The one tool that makes the other three worth having: without it the
    # chat can say a document exists and nothing about what it says.
    Tool(name="read_file",
         summary="Read what is written inside one Dropbox file, given its "
                 "path. Use this for text: notes, code, csv, markdown.",
         method="POST", path="/files/download",
         # A different hostname from the rest of Dropbox. See
         # DROPBOX_CONTENT and VENDOR_HOSTS.
         base=DROPBOX_CONTENT,
         args={"path": ("string", "The file, like /Documents/notes.txt",
                        True)},
         # The argument goes in a header and the body stays empty, so
         # there is deliberately no `shape` and no `body` here.
         head=_dropbox_arg,
         raw=_dropbox_file,
         writes=False,
         keep=("path", "size", "truncated", "content", "why")),
    # The only write Dropbox has here, and it cannot destroy anything:
    # `mode: add` with `autorename` means a clash is saved alongside under
    # a numbered name. See _dropbox_upload_arg.
    Tool(name="upload_file",
         summary="Save a new text file into your Dropbox at the path you "
                 "give, including the file name. It adds a file and never "
                 "replaces one: if something is already there, Dropbox "
                 "keeps both and numbers the new one.",
         method="POST", path="/files/upload",
         base=DROPBOX_CONTENT,
         args={"path": ("string",
                        "Where to save it, with the file name, like "
                        "/Documents/notes.txt", True),
               "content": ("string", "The text to write in the file", True)},
         # Destination in a header, the file as the body. No `shape`.
         head=_dropbox_upload_arg,
         send=_dropbox_bytes,
         writes=True,
         keep=("name", "path_display", "size", "server_modified")),
    # An `act` tool, because a second request for a link is a 409 whose
    # body IS the answer. See _dropbox_share.
    Tool(name="share_link",
         summary="Make a link to one of your Dropbox files that you can "
                 "send to somebody, or give back the link that file "
                 "already has. Returns a link to view and a link that "
                 "downloads straight away.",
         method="POST", path="/sharing/create_shared_link_with_settings",
         args={"path": ("string",
                        "The file to share, like /Documents/notes.txt",
                        True)},
         act=_dropbox_share,
         writes=True),
    Tool(name="whoami",
         summary="Show which Dropbox account is currently connected to "
                 "your assistant.",
         method="POST", path="/users/get_current_account",
         writes=False,
         keep=("account_id", "email", "name")),
]

# --- Todoist ---------------------------------------------------------------
#
# API v1 (https://api.todoist.com/api/v1), with the person's own token.
# Two vendor facts live here rather than in a prompt:
#
# LISTS COME WRAPPED, as {"results": [...], "next_cursor": ...}. Read as a
# bare list, every listing is one object with no task in it.
#
# PRIORITY RUNS BACKWARDS. In the app p1 is the red, urgent one; in the API
# urgent is 4 and normal is 1. A model told "make it p1" writes 1, which is
# the lowest there is, so a person's words are turned around here.

_TODOIST_TASK_KEEP = ("id", "content", "description", "due", "priority",
                      "project_id", "section_id", "parent_id", "labels",
                      "checked", "added_at")

#: What a person says -> the API's number. p1 is urgent, and urgent is 4.
_TODOIST_PRIORITY = {"p1": 4, "urgent": 4, "highest": 4,
                     "p2": 3, "high": 3,
                     "p3": 2, "medium": 2,
                     "p4": 1, "normal": 1, "low": 1, "none": 1}


def _todoist_results(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return payload


def _todoist_priority(given: Any) -> int:
    """A priority said the way the app says it, as the API's number.

    A bare number is read as the app's p-number too, because "priority 1"
    from a person means p1, the urgent one, and read as the API's 1 it is
    the lowest.
    """
    text = str(given).strip().lower()
    if text.isdigit():
        text = "p" + text
    if text not in _TODOIST_PRIORITY:
        raise ValueError("Todoist priority is p1 (urgent), p2, p3 or p4 "
                         "(normal). Got: %s" % given)
    return _TODOIST_PRIORITY[text]


def _todoist_labels(given: Any) -> List[str]:
    if isinstance(given, str):
        given = given.split(",")
    return [str(x).strip() for x in (given or []) if str(x).strip()]


def _todoist_task_body(args: Dict[str, Any], new: bool = True) -> Dict[str, Any]:
    """The body for a new task, or for changing one.

    An empty field is LEFT OUT, never sent blank: description "" on an
    update wipes the one already there, for somebody who only asked to
    change the due date. And an update never carries project_id, because
    v1 ignores it there and moves a task with /move instead.
    """
    given = args or {}
    out: Dict[str, Any] = {}
    for arg, key in (("content", "content"), ("description", "description"),
                     ("due", "due_string")):
        value = str(given.get(arg) or "").strip()
        if value:
            out[key] = value
    if new:
        if "content" not in out:
            raise ValueError("A Todoist task needs words: say what the task "
                             "is in `content`.")
        for arg in ("project_id", "section_id", "parent_id"):
            value = str(given.get(arg) or "").strip()
            if value:
                out[arg] = value
    if given.get("priority") not in (None, ""):
        out["priority"] = _todoist_priority(given["priority"])
    labels = _todoist_labels(given.get("labels"))
    if labels:
        out["labels"] = labels
    if not new and not out:
        raise ValueError("Nothing to change on that Todoist task. Give a new "
                         "content, description, due, priority or labels, or "
                         "use move_task to move it.")
    return out


def _todoist_move_body(args: Dict[str, Any]) -> Dict[str, Any]:
    given = args or {}
    out = {k: str(given[k]).strip() for k in ("project_id", "section_id",
                                              "parent_id")
           if str(given.get(k) or "").strip()}
    if not out:
        raise ValueError("Say where to move the task: a project_id, a "
                         "section_id or a parent_id.")
    return out


def _todoist_comment_body(args: Dict[str, Any]) -> Dict[str, Any]:
    given = args or {}
    text = str(given.get("text") or "").strip()
    if not text:
        raise ValueError("Say what the comment is in `text`.")
    return {"task_id": str(given.get("task_id") or ""), "content": text}


_TODOIST_TASK_ID = ("string", "The task's id, from list_tasks or find_tasks",
                    True)
_TODOIST_PRIORITY_SAYS = ("Priority as the app shows it: p1 (urgent, red), "
                          "p2, p3 or p4 (normal). Write p1 for urgent.")

TODOIST_TOOLS = [
    Tool(name="whoami",
         summary="Show which Todoist account is connected to your assistant.",
         method="GET", path="/user",
         keep=("id", "email", "full_name", "tz_info")),
    Tool(name="list_projects",
         summary="List your Todoist projects, with the id each task tool "
                 "needs. Inbox is one of them.",
         method="GET", path="/projects",
         unwrap=_todoist_results,
         query_defaults={"limit": MAX_ITEMS},
         keep=("id", "name", "parent_id", "is_favorite", "inbox_project")),
    Tool(name="list_sections",
         summary="List the sections inside one Todoist project.",
         method="GET", path="/sections",
         query={"project_id": "project_id"},
         args={"project_id": ("string", "Project id from list_projects",
                              True)},
         unwrap=_todoist_results,
         keep=("id", "name", "project_id")),
    Tool(name="list_tasks",
         summary="List the open tasks in one Todoist project, or every open "
                 "task when no project is given.",
         method="GET", path="/tasks",
         query={"project_id": "project_id", "section_id": "section_id",
                "label": "label"},
         query_defaults={"limit": MAX_ITEMS},
         args={"project_id": ("string", "Project id from list_projects",
                              False),
               "section_id": ("string", "Section id from list_sections",
                              False),
               "label": ("string", "Only tasks with this label name", False)},
         unwrap=_todoist_results,
         keep=_TODOIST_TASK_KEEP),
    Tool(name="find_tasks",
         summary="Find Todoist tasks with Todoist's own filter language: "
                 "what is due today, overdue, this week, by label or by "
                 "project.",
         method="GET", path="/tasks/filter",
         query={"query": "filter"},
         query_defaults={"limit": MAX_ITEMS},
         args={"filter": ("string",
                          "A Todoist filter, for example \"today | overdue\", "
                          "\"7 days\", \"p1\", \"#Work\" (a project) or "
                          "\"@waiting\" (a label). One filter only: a comma "
                          "between two is refused.", True)},
         unwrap=_todoist_results,
         keep=_TODOIST_TASK_KEEP),
    Tool(name="get_task",
         summary="Read one open Todoist task in full.",
         method="GET", path="/tasks/{task_id}",
         args={"task_id": _TODOIST_TASK_ID},
         keep=_TODOIST_TASK_KEEP),
    Tool(name="create_task",
         summary="Add a task to Todoist. With no project it goes to the "
                 "Inbox. The due date can be plain words like \"tomorrow "
                 "9am\" or \"every monday\".",
         method="POST", path="/tasks",
         args={"content": ("string", "What the task is", True),
               "description": ("string", "More detail under the task",
                               False),
               "project_id": ("string", "Project id from list_projects; "
                                        "leave out for the Inbox", False),
               "section_id": ("string", "Section id from list_sections",
                              False),
               "parent_id": ("string", "Make it a sub-task of this task id",
                             False),
               "due": ("string", "When it is due, in plain words: "
                                 "\"tomorrow 9am\", \"next friday\", "
                                 "\"every monday\"", False),
               "priority": ("string", _TODOIST_PRIORITY_SAYS, False),
               "labels": ("array", "Label names, for example "
                                   "[\"work\", \"waiting\"]", False)},
         shape=_todoist_task_body,
         keep=_TODOIST_TASK_KEEP),
    Tool(name="update_task",
         summary="Change a Todoist task's words, due date, priority or "
                 "labels. To move it to another project use move_task.",
         method="POST", path="/tasks/{task_id}",
         args={"task_id": _TODOIST_TASK_ID,
               "content": ("string", "New task text", False),
               "description": ("string", "New description", False),
               "due": ("string", "New due date in plain words", False),
               "priority": ("string", _TODOIST_PRIORITY_SAYS, False),
               "labels": ("array", "The task's labels, replacing the ones "
                                   "it has", False)},
         shape=lambda a: _todoist_task_body(a, new=False),
         keep=_TODOIST_TASK_KEEP),
    Tool(name="move_task",
         summary="Move a Todoist task to another project or section, or "
                 "under another task.",
         method="POST", path="/tasks/{task_id}/move",
         args={"task_id": _TODOIST_TASK_ID,
               "project_id": ("string", "Project id to move it to", False),
               "section_id": ("string", "Section id to move it to", False),
               "parent_id": ("string", "Task id to put it under", False)},
         shape=_todoist_move_body,
         keep=_TODOIST_TASK_KEEP),
    Tool(name="complete_task",
         summary="Tick a Todoist task off as done. A recurring task moves "
                 "on to its next date instead.",
         method="POST", path="/tasks/{task_id}/close",
         args={"task_id": _TODOIST_TASK_ID}),
    Tool(name="reopen_task",
         summary="Reopen a Todoist task that was ticked off.",
         method="POST", path="/tasks/{task_id}/reopen",
         args={"task_id": _TODOIST_TASK_ID}),
    Tool(name="comment_on_task",
         summary="Add a comment to a Todoist task, written as you.",
         method="POST", path="/comments",
         args={"task_id": _TODOIST_TASK_ID,
               "text": ("string", "The comment to add", True)},
         shape=_todoist_comment_body,
         keep=("id", "content", "posted_at")),
]


# --- Asana -----------------------------------------------------------------
#
# REST at https://app.asana.com/api/1.0, with the person's own token. What
# is written here rather than left to a prompt:
#
# EVERYTHING IS WRAPPED IN `data`, both ways. Answers are {"data": ...} and
# a write is refused unless its body is {"data": {...}} too.
#
# "MY TASKS" NEEDS assignee=me AND workspace, together; either alone is 400.
#
# A PROJECT'S TASKS INCLUDE FINISHED ONES unless completed_since=now.
#
# SEARCH IS PREMIUM ONLY (402 on a free account), so there is no search
# tool: it would fail for most of the people who tried it.

_ASANA_TASK_FIELDS = ("name,notes,due_on,due_at,completed,assignee.name,"
                      "projects.name,memberships.section.name,permalink_url")
_ASANA_TASK_KEEP = ("gid", "name", "notes", "due_on", "due_at", "completed",
                    "assignee", "projects", "memberships", "permalink_url")
_ASANA_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _asana_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _asana_due(given: Any) -> str:
    """A due date as Asana takes it: a calendar date, YYYY-MM-DD.

    Asana does not read "tomorrow", so anything else is refused with a
    sentence before the person approves a write that cannot succeed.
    """
    text = str(given or "").strip()
    if _ASANA_DATE.match(text):
        try:
            datetime.date.fromisoformat(text)
            return text
        except ValueError:
            pass
    raise ValueError("Asana takes a due date as YYYY-MM-DD, for example "
                     "2026-11-24. Got: %s" % given)


def _asana_task_body(args: Dict[str, Any], new: bool = True) -> Dict[str, Any]:
    """The body for a new task, or for changing one, wrapped in `data`.

    An empty field is LEFT OUT: notes "" would wipe the description of
    somebody who only asked to change the due date. `projects` and
    `workspace` are create-only to Asana, so an update never carries them.
    """
    given = args or {}
    out: Dict[str, Any] = {}
    for key in ("name", "notes", "assignee"):
        value = str(given.get(key) or "").strip()
        if value:
            out[key] = value
    if str(given.get("due_on") or "").strip():
        out["due_on"] = _asana_due(given["due_on"])
    if new:
        if "name" not in out:
            raise ValueError("An Asana task needs a name: say what the task "
                             "is in `name`.")
        project = str(given.get("project_id") or "").strip()
        workspace = str(given.get("workspace_id") or "").strip()
        if project:
            out["projects"] = [project]
        elif workspace:
            out["workspace"] = workspace
        else:
            raise ValueError("Say where the task lives: a project_id from "
                             "list_projects, or a workspace_id from "
                             "list_workspaces.")
    elif not out:
        raise ValueError("Nothing to change on that Asana task. Give a new "
                         "name, notes, due_on or assignee.")
    return {"data": out}


def _asana_comment_body(args: Dict[str, Any]) -> Dict[str, Any]:
    text = str((args or {}).get("text") or "").strip()
    if not text:
        raise ValueError("Say what the comment is in `text`.")
    return {"data": {"text": text}}


_ASANA_TASK_ID = ("string", "The task's gid, from my_tasks or "
                            "list_project_tasks", True)
_ASANA_WORKSPACE = ("string", "Workspace gid from list_workspaces", True)
_ASANA_ASSIGNEE = ("string", "Who has it: \"me\", an email, or a user gid",
                   False)
_ASANA_LIST = {"limit": MAX_ITEMS}

ASANA_TOOLS = [
    Tool(name="whoami",
         summary="Show which Asana account is connected, and its "
                 "workspaces.",
         method="GET", path="/users/me",
         query_defaults={"opt_fields": "name,email,workspaces.name"},
         unwrap=_asana_data,
         keep=("gid", "name", "email", "workspaces")),
    Tool(name="list_workspaces",
         summary="List the Asana workspaces you belong to. Every other "
                 "Asana tool starts from one of these.",
         method="GET", path="/workspaces",
         query_defaults=dict(_ASANA_LIST),
         unwrap=_asana_data,
         keep=("gid", "name")),
    Tool(name="list_projects",
         summary="List the open projects in one Asana workspace.",
         method="GET", path="/projects",
         query={"workspace": "workspace_id"},
         query_defaults={"archived": "false", **_ASANA_LIST},
         args={"workspace_id": _ASANA_WORKSPACE},
         unwrap=_asana_data,
         keep=("gid", "name")),
    Tool(name="list_sections",
         summary="List the sections (columns) of one Asana project.",
         method="GET", path="/projects/{project_id}/sections",
         query_defaults=dict(_ASANA_LIST),
         args={"project_id": ("string", "Project gid from list_projects",
                              True)},
         unwrap=_asana_data,
         keep=("gid", "name")),
    Tool(name="list_project_tasks",
         summary="List the open tasks in one Asana project, with due dates, "
                 "who has them and a link to each.",
         method="GET", path="/projects/{project_id}/tasks",
         query_defaults={"completed_since": "now",
                         "opt_fields": _ASANA_TASK_FIELDS, **_ASANA_LIST},
         args={"project_id": ("string", "Project gid from list_projects",
                              True)},
         unwrap=_asana_data,
         keep=_ASANA_TASK_KEEP),
    Tool(name="my_tasks",
         summary="List the open Asana tasks assigned to you in one "
                 "workspace.",
         method="GET", path="/tasks",
         query={"workspace": "workspace_id"},
         query_defaults={"assignee": "me", "completed_since": "now",
                         "opt_fields": _ASANA_TASK_FIELDS, **_ASANA_LIST},
         args={"workspace_id": _ASANA_WORKSPACE},
         unwrap=_asana_data,
         keep=_ASANA_TASK_KEEP),
    Tool(name="get_task",
         summary="Read one Asana task in full.",
         method="GET", path="/tasks/{task_id}",
         query_defaults={"opt_fields": _ASANA_TASK_FIELDS},
         args={"task_id": _ASANA_TASK_ID},
         unwrap=_asana_data,
         keep=_ASANA_TASK_KEEP),
    Tool(name="create_task",
         summary="Add a task to Asana, in a project or straight into a "
                 "workspace.",
         method="POST", path="/tasks",
         args={"name": ("string", "What the task is", True),
               "notes": ("string", "More detail under the task", False),
               "project_id": ("string", "Project gid from list_projects",
                              False),
               "workspace_id": ("string", "Workspace gid, when there is no "
                                          "project", False),
               "due_on": ("string", "Due date as YYYY-MM-DD", False),
               "assignee": _ASANA_ASSIGNEE},
         shape=_asana_task_body,
         unwrap=_asana_data,
         keep=_ASANA_TASK_KEEP),
    Tool(name="update_task",
         summary="Change an Asana task's name, notes, due date or who has "
                 "it.",
         method="PUT", path="/tasks/{task_id}",
         args={"task_id": _ASANA_TASK_ID,
               "name": ("string", "New name", False),
               "notes": ("string", "New notes", False),
               "due_on": ("string", "New due date as YYYY-MM-DD", False),
               "assignee": _ASANA_ASSIGNEE},
         shape=lambda a: _asana_task_body(a, new=False),
         unwrap=_asana_data,
         keep=_ASANA_TASK_KEEP),
    Tool(name="complete_task",
         summary="Mark an Asana task complete.",
         method="PUT", path="/tasks/{task_id}",
         args={"task_id": _ASANA_TASK_ID},
         shape=lambda a: {"data": {"completed": True}},
         unwrap=_asana_data,
         keep=("gid", "name", "completed")),
    Tool(name="reopen_task",
         summary="Mark a completed Asana task as not done again.",
         method="PUT", path="/tasks/{task_id}",
         args={"task_id": _ASANA_TASK_ID},
         shape=lambda a: {"data": {"completed": False}},
         unwrap=_asana_data,
         keep=("gid", "name", "completed")),
    Tool(name="move_to_section",
         summary="Move an Asana task into a section (column) of its "
                 "project.",
         method="POST", path="/sections/{section_id}/addTask",
         args={"section_id": ("string", "Section gid from list_sections",
                              True),
               "task_id": _ASANA_TASK_ID},
         shape=lambda a: {"data": {"task": str((a or {}).get("task_id")
                                               or "")}},
         unwrap=_asana_data),
    Tool(name="comment_on_task",
         summary="Add a comment to an Asana task, written as you.",
         method="POST", path="/tasks/{task_id}/stories",
         args={"task_id": _ASANA_TASK_ID,
               "text": ("string", "The comment to add", True)},
         shape=_asana_comment_body,
         unwrap=_asana_data,
         keep=("gid", "text", "created_at")),
]


# --- Linear ----------------------------------------------------------------
#
# GraphQL at https://api.linear.app/graphql, with the person's own key sent
# bare. Every tool is a POST of a query, so every read says writes=False,
# and the shaping builds {"query", "variables"} so nothing a model writes is
# ever pasted into a query string. A refusal can come back as 200; see
# _graphql_refused.

_LINEAR_ISSUE = ("id identifier title priority dueDate url "
                 "state { name type } assignee { name } team { key name }")
#: Finished work, by Linear's own state types.
_LINEAR_OPEN = '{ state: { type: { nin: ["completed", "canceled"] } } }'
_LINEAR_PRIORITY = {"none": 0, "no priority": 0, "urgent": 1, "high": 2,
                    "medium": 3, "normal": 3, "low": 4}


def _linear_dig(*path):
    """Unwrap {"data": {...}} down `path`, then into `nodes` if it is a
    connection. An answer missing a step is handed back as it came."""
    def dig(payload):
        cur = payload.get("data") if isinstance(payload, dict) else None
        for step in path:
            if not isinstance(cur, dict) or cur.get(step) is None:
                return payload
            cur = cur[step]
        if isinstance(cur, dict) and isinstance(cur.get("nodes"), list):
            return cur["nodes"]
        return cur
    return dig


def _linear_priority(given: Any) -> int:
    """Linear's number: 1 is urgent, 4 is low, 0 is none. Unlike Todoist
    it runs the way a person counts, so a number is taken as it is."""
    text = str(given).strip().lower()
    if text in ("0", "1", "2", "3", "4"):
        return int(text)
    if text in _LINEAR_PRIORITY:
        return _LINEAR_PRIORITY[text]
    raise ValueError("Linear priority is urgent, high, medium, low or none. "
                     "Got: %s" % given)


def _linear_input(args: Dict[str, Any]) -> Dict[str, Any]:
    """The fields an issue create or update takes, left out when empty, so
    an update that changes the state never blanks the description."""
    given = args or {}
    out: Dict[str, Any] = {}
    for arg, key in (("title", "title"), ("description", "description"),
                     ("state_id", "stateId"), ("assignee_id", "assigneeId")):
        value = str(given.get(arg) or "").strip()
        if value:
            out[key] = value
    if given.get("priority") not in (None, ""):
        out["priority"] = _linear_priority(given["priority"])
    due = str(given.get("due_date") or "").strip()
    if due:
        try:
            if len(due) != 10:
                raise ValueError
            datetime.date.fromisoformat(due)
        except ValueError:
            raise ValueError("Linear takes a due date as YYYY-MM-DD, for "
                             "example 2026-12-01. Got: %s" % due) from None
        out["dueDate"] = due
    return out


def _linear_query(query: str, **variables) -> Dict[str, Any]:
    return {"query": query, "variables": variables}


def _linear_needs(args: Dict[str, Any], name: str, what: str) -> str:
    value = str((args or {}).get(name) or "").strip()
    if not value:
        raise ValueError("Say which " + what + " in `" + name + "`.")
    return value


def _linear_create(args: Dict[str, Any]) -> Dict[str, Any]:
    team = _linear_needs(args, "team_id", "team (an id from list_teams)")
    fields = _linear_input(args)
    if "title" not in fields:
        raise ValueError("A Linear issue needs a title.")
    return _linear_query(
        "mutation($input: IssueCreateInput!) { issueCreate(input: $input) "
        "{ success issue { " + _LINEAR_ISSUE + " } } }",
        input={"teamId": team, **fields})


def _linear_update(args: Dict[str, Any]) -> Dict[str, Any]:
    issue = _linear_needs(args, "issue", "issue, like ENG-123")
    fields = _linear_input(args)
    if not fields:
        raise ValueError("Nothing to change on that Linear issue. Give a new "
                         "title, description, state_id, priority, due_date "
                         "or assignee_id.")
    return _linear_query(
        "mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate("
        "id: $id, input: $input) { success issue { " + _LINEAR_ISSUE
        + " } } }", id=issue, input=fields)


def _linear_comment(args: Dict[str, Any]) -> Dict[str, Any]:
    issue = _linear_needs(args, "issue", "issue, like ENG-123")
    body = _linear_needs(args, "body", "comment text")
    return _linear_query(
        "mutation($input: CommentCreateInput!) { commentCreate(input: "
        "$input) { success comment { id body url } } }",
        input={"issueId": issue, "body": body})


def _linear_search(args: Dict[str, Any]) -> Dict[str, Any]:
    text = _linear_needs(args, "text", "words to search for")
    return _linear_query(
        "query($term: String!) { searchIssues(term: $term, first: %d) "
        "{ nodes { %s } } }" % (MAX_ITEMS, _LINEAR_ISSUE), term=text)


_LINEAR_ISSUE_ARG = ("string", "The issue, by its identifier like ENG-123 "
                               "(or its id)", True)
_LINEAR_TEAM_ARG = ("string", "Team id from list_teams", True)
_LINEAR_PRIORITY_SAYS = ("Priority: urgent, high, medium, low or none",
                         )

LINEAR_TOOLS = [
    Tool(name="whoami",
         summary="Show which Linear account is connected.",
         method="POST", path="/graphql", writes=False,
         shape=lambda a: _linear_query("query { viewer { id name email } }"),
         unwrap=_linear_dig("viewer")),
    Tool(name="list_teams",
         summary="List the Linear teams you belong to, with the id every "
                 "issue tool needs and each team's key (the ENG in ENG-123).",
         method="POST", path="/graphql", writes=False,
         shape=lambda a: _linear_query(
             "query { teams(first: 50) { nodes { id key name } } }"),
         unwrap=_linear_dig("teams")),
    Tool(name="list_states",
         summary="List one Linear team's workflow states (Todo, In "
                 "Progress, Done...), with the id update_issue needs to "
                 "move an issue.",
         method="POST", path="/graphql", writes=False,
         args={"team_id": _LINEAR_TEAM_ARG},
         shape=lambda a: _linear_query(
             "query($id: String!) { team(id: $id) { states { nodes "
             "{ id name type } } } }",
             id=_linear_needs(a, "team_id", "team (an id from list_teams)")),
         unwrap=_linear_dig("team", "states")),
    Tool(name="my_issues",
         summary="List the open Linear issues assigned to you, most "
                 "recently changed first.",
         method="POST", path="/graphql", writes=False,
         shape=lambda a: _linear_query(
             "query { viewer { assignedIssues(first: %d, orderBy: updatedAt, "
             "filter: %s) { nodes { %s } } } }"
             % (MAX_ITEMS, _LINEAR_OPEN, _LINEAR_ISSUE)),
         unwrap=_linear_dig("viewer", "assignedIssues")),
    Tool(name="team_issues",
         summary="List one Linear team's open issues, most recently changed "
                 "first.",
         method="POST", path="/graphql", writes=False,
         args={"team_id": _LINEAR_TEAM_ARG},
         shape=lambda a: _linear_query(
             "query($id: String!) { team(id: $id) { issues(first: %d, "
             "orderBy: updatedAt, filter: %s) { nodes { %s } } } }"
             % (MAX_ITEMS, _LINEAR_OPEN, _LINEAR_ISSUE),
             id=_linear_needs(a, "team_id", "team (an id from list_teams)")),
         unwrap=_linear_dig("team", "issues")),
    Tool(name="search_issues",
         summary="Search Linear issues by words in the title or "
                 "description.",
         method="POST", path="/graphql", writes=False,
         args={"text": ("string", "What to search for", True)},
         shape=_linear_search,
         unwrap=_linear_dig("searchIssues")),
    Tool(name="get_issue",
         summary="Read one Linear issue in full, with its description and "
                 "latest comments.",
         method="POST", path="/graphql", writes=False,
         args={"issue": _LINEAR_ISSUE_ARG},
         shape=lambda a: _linear_query(
             "query($id: String!) { issue(id: $id) { " + _LINEAR_ISSUE
             + " description comments(first: 10) { nodes { body createdAt "
             "user { name } } } } }",
             id=_linear_needs(a, "issue", "issue, like ENG-123")),
         unwrap=_linear_dig("issue")),
    Tool(name="create_issue",
         summary="Create a Linear issue in one of your teams.",
         method="POST", path="/graphql",
         args={"team_id": _LINEAR_TEAM_ARG,
               "title": ("string", "The issue's title", True),
               "description": ("string", "Detail, in Markdown", False),
               "priority": ("string", _LINEAR_PRIORITY_SAYS[0], False),
               "state_id": ("string", "State id from list_states; leave "
                                      "out for the team's default", False),
               "assignee_id": ("string", "User id to assign it to", False),
               "due_date": ("string", "Due date as YYYY-MM-DD", False)},
         shape=_linear_create,
         unwrap=_linear_dig("issueCreate", "issue")),
    Tool(name="update_issue",
         summary="Change a Linear issue: move it to another state, retitle "
                 "it, change its priority, due date or who has it.",
         method="POST", path="/graphql",
         args={"issue": _LINEAR_ISSUE_ARG,
               "title": ("string", "New title", False),
               "description": ("string", "New description, in Markdown",
                               False),
               "priority": ("string", _LINEAR_PRIORITY_SAYS[0], False),
               "state_id": ("string", "State id from list_states", False),
               "assignee_id": ("string", "User id to assign it to", False),
               "due_date": ("string", "Due date as YYYY-MM-DD", False)},
         shape=_linear_update,
         unwrap=_linear_dig("issueUpdate", "issue")),
    Tool(name="comment_on_issue",
         summary="Add a comment to a Linear issue, written as you.",
         method="POST", path="/graphql",
         args={"issue": _LINEAR_ISSUE_ARG,
               "body": ("string", "The comment, in Markdown", True)},
         shape=_linear_comment,
         unwrap=_linear_dig("commentCreate", "comment")),
]


# --- Vercel ----------------------------------------------------------------

#: Vercel pages its collections under a key named after the thing.
def _vercel_projects(d):
    return (d or {}).get("projects", [])


def _vercel_deployments(d):
    return (d or {}).get("deployments", [])


VERCEL_TOOLS = [
    Tool(name="whoami",
         summary="Show which Vercel account is connected to your "
                 "assistant.",
         method="GET", path="/v2/user",
         writes=False,
         unwrap=lambda d: (d or {}).get("user") or {},
         keep=("id", "username", "email", "name")),
    Tool(name="list_projects",
         summary="List the projects in your own Vercel account.",
         method="GET", path="/v9/projects",
         args={"limit": ("integer", "How many projects to return", False)},
         query={"limit": "limit"},
         query_defaults={"limit": "20"},
         writes=False,
         unwrap=_vercel_projects,
         keep=("id", "name", "framework", "updatedAt")),
    Tool(name="list_deployments",
         summary="List recent deployments in your own Vercel account, "
                 "with whether each one is ready or failed.",
         method="GET", path="/v6/deployments",
         args={"limit": ("integer", "How many deployments to return",
                         False),
               "project_id": ("string",
                              "Only this project, by its id", False)},
         query={"limit": "limit", "projectId": "project_id"},
         query_defaults={"limit": "20"},
         writes=False,
         unwrap=_vercel_deployments,
         # `state` is the one people actually want: READY, ERROR, BUILDING.
         keep=("uid", "name", "url", "state", "target", "created")),
    Tool(name="get_project",
         summary="Read one of your Vercel projects by name or id.",
         method="GET", path="/v9/projects/{project_id}",
         args={"project_id": ("string",
                              "The project's name or id", True)},
         writes=False,
         keep=("id", "name", "framework", "updatedAt", "targets")),
]

# --- Outlook ---------------------------------------------------------------

#: How far ahead a calendar read looks when nobody said.
_OUTLOOK_DEFAULT_DAYS = 7

#: What is worth keeping off a message. Graph returns about forty fields
#: per message, most of them routing metadata nobody reads.
_OUTLOOK_MAIL_KEEP = ("id", "subject", "from", "toRecipients",
                      "receivedDateTime", "bodyPreview", "isRead", "webLink")

_OUTLOOK_EVENT_KEEP = ("id", "subject", "start", "end", "location",
                       "organizer", "attendees", "isAllDay", "webLink")

#: Graph wraps every collection in {"value": [...]}.
def _odata_value(d):
    return (d or {}).get("value", [])


def _outlook_stamp(when) -> str:
    """ISO 8601 with an explicit offset.

    A value with no offset is read as UTC, which moves somebody's day by
    up to thirteen hours without saying so.
    """
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _outlook_window(args):
    """startDateTime and endDateTime, which calendarView REQUIRES.

    Pure, so a test can read what would be sent with no clock stubbing
    beyond what it chooses to pass in.
    """
    given = args or {}
    start = str(given.get("start") or "").strip()
    end = str(given.get("end") or "").strip()
    now = datetime.datetime.now(datetime.timezone.utc)
    if not start:
        start = _outlook_stamp(now)
    if not end:
        base = now
        try:
            base = datetime.datetime.fromisoformat(
                start.replace("Z", "+00:00"))
        except Exception:                                   # noqa: BLE001
            pass
        end = _outlook_stamp(base + datetime.timedelta(
            days=_OUTLOOK_DEFAULT_DAYS))
    return {"startDateTime": start, "endDateTime": end}


def _outlook_people(given):
    """One string of addresses into Graph's recipient shape.

    A model writes "a@x.com, b@y.com" far more often than it builds a list
    of objects, and semicolons are what Outlook itself puts between
    addresses, so both separators are accepted.
    """
    raw = str(given or "").replace(";", ",")
    return [{"emailAddress": {"address": a.strip()}}
            for a in raw.split(",") if a.strip()]


def _outlook_send_body(args):
    given = args or {}
    body = {"message": {
        "subject": given.get("subject") or "",
        "body": {"contentType": "Text", "content": given.get("body") or ""},
        "toRecipients": _outlook_people(given.get("to"))},
        # Named rather than left out: Graph defaults it to true, and a sent
        # mail missing from Sent Items is the kind of thing somebody
        # notices a week later.
        "saveToSentItems": True}
    cc = _outlook_people(given.get("cc"))
    if cc:
        body["message"]["ccRecipients"] = cc
    return body


def _outlook_event_body(args):
    given = args or {}
    window = _outlook_window({"start": given.get("start"),
                              "end": given.get("end")})
    event = {
        "subject": given.get("subject") or "",
        "start": {"dateTime": window["startDateTime"], "timeZone": "UTC"},
        "end": {"dateTime": window["endDateTime"], "timeZone": "UTC"},
    }
    if given.get("body"):
        event["body"] = {"contentType": "Text", "content": given["body"]}
    if given.get("location"):
        event["location"] = {"displayName": given["location"]}
    people = _outlook_people(given.get("attendees"))
    if people:
        event["attendees"] = [dict(p, type="required") for p in people]
    return event


OUTLOOK_TOOLS = [
    Tool(name="whoami",
         summary="Show which Outlook or Microsoft account is connected to "
                 "your assistant.",
         method="GET", path="/me",
         writes=False,
         keep=("id", "displayName", "mail", "userPrincipalName")),
    Tool(name="list_mail",
         summary="List the most recent messages in your Outlook inbox.",
         method="GET", path="/me/messages",
         args={"limit": ("integer", "How many messages to return", False)},
         query={"$top": "limit"},
         query_defaults={
             "$top": "25",
             "$select": ",".join(_OUTLOOK_MAIL_KEEP),
             "$orderby": "receivedDateTime desc"},
         writes=False,
         unwrap=_odata_value,
         keep=_OUTLOOK_MAIL_KEEP),
    Tool(name="search_mail",
         summary="Search your Outlook mail for words in the subject, body "
                 "or sender.",
         method="GET", path="/me/messages",
         args={"query": ("string", "Words to look for", True),
               "limit": ("integer", "How many messages to return", False)},
         query={"$search": "query", "$top": "limit"},
         # NO $orderby here, deliberately. Graph refuses $search combined
         # with $orderby, so copying the listing's defaults would make
         # every search a 400.
         query_defaults={"$top": "25"},
         writes=False,
         unwrap=_odata_value,
         keep=_OUTLOOK_MAIL_KEEP),
    Tool(name="get_mail",
         summary="Read one Outlook message in full, by its id.",
         method="GET", path="/me/messages/{message_id}",
         args={"message_id": ("string", "The message id", True)},
         writes=False,
         keep=_OUTLOOK_MAIL_KEEP + ("body",)),
    Tool(name="send_mail",
         summary="Send an email from your own Outlook account. It goes out "
                 "under your name and lands in your Sent Items.",
         method="POST", path="/me/sendMail",
         args={"to": ("string",
                      "Who to send it to. Several addresses can be "
                      "separated by commas.", True),
               "subject": ("string", "The subject line", True),
               "body": ("string", "What to say", True),
               "cc": ("string", "Anyone to copy, comma separated", False)},
         shape=_outlook_send_body,
         writes=True),
    Tool(name="list_events",
         summary="List what is on your Outlook calendar, including "
                 "recurring meetings. Defaults to the next seven days.",
         # calendarView, NOT /me/events. events returns the series master
         # of a recurring meeting; calendarView expands it into the
         # occurrences that are actually in the week somebody asked about.
         method="GET", path="/me/calendarView",
         args={"start": ("string",
                         "When to look from, like 2026-11-16T00:00:00Z. "
                         "Leave it out for now.", False),
               "end": ("string", "When to look until. Leave it out for "
                                 "seven days ahead.", False),
               "limit": ("integer", "How many events to return", False)},
         query={"startDateTime": "startDateTime",
                "endDateTime": "endDateTime", "$top": "limit"},
         query_defaults={"$top": "50", "$orderby": "start/dateTime"},
         writes=False,
         unwrap=_odata_value,
         keep=_OUTLOOK_EVENT_KEEP),
    Tool(name="create_event",
         summary="Put a new event on your own Outlook calendar.",
         method="POST", path="/me/events",
         args={"subject": ("string", "What the event is called", True),
               "start": ("string",
                         "When it starts, like 2026-11-17T09:00:00Z", True),
               "end": ("string", "When it ends", False),
               "body": ("string", "Any notes", False),
               "location": ("string", "Where it is", False),
               "attendees": ("string",
                             "Who to invite, comma separated", False)},
         shape=_outlook_event_body,
         writes=True,
         keep=_OUTLOOK_EVENT_KEEP),
    Tool(name="list_contacts",
         summary="List the contacts saved in your own Outlook address book.",
         method="GET", path="/me/contacts",
         args={"limit": ("integer", "How many contacts to return", False)},
         query={"$top": "limit"},
         query_defaults={"$top": "50"},
         writes=False,
         unwrap=_odata_value,
         keep=("id", "displayName", "emailAddresses", "companyName",
               "mobilePhone")),
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
    "outlook": OUTLOOK_TOOLS,
    "vercel": VERCEL_TOOLS,
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
    "todoist": TODOIST_TOOLS,
    "asana": ASANA_TOOLS,
    "linear": LINEAR_TOOLS,
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
