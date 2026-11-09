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
from pydantic import BaseModel

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


def _payload_for(tool: "Tool", args: Optional[Dict[str, Any]]) -> Optional[Dict]:
    """The JSON body for a write, with the tool's defaults filled in.

    Its own function so a test can read what would be sent without a
    vendor, a connection or a network. The default is applied only when
    the caller gave nothing, so a caller that means "post" keeps it.
    """
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
        message = str(payload.get("message") or payload.get("error") or "")
    message = " ".join(c for c in message.split() if c)
    message = "".join(c for c in message if c.isprintable())[:MAX_VENDOR_NOTE]
    if not message:
        return ""
    for value in (creds or {}).values():
        v = str(value or "")
        if len(v) >= 8 and v in message:
            return ""
    return " " + message


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
    for param_name, arg_name in (tool.query or {}).items():
        v = (args or {}).get(arg_name)
        if v not in (None, ""):
            params[param_name] = v

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
        return _err("Could not reach " + label + " just now. Try again in a "
                    "moment.")

    if r.status_code in (401, 403):
        return _err("Your " + label + " credential was rejected. It may have "
                    "expired or lack permission. Reconnect it from "
                    "Connections.")
    if r.status_code == 404:
        return _err(label + " could not find that."
                    + _vendor_said(r, creds))
    if r.status_code >= 400:
        # Never r.text: vendors echo the request, credential included.
        logger.warning("mytools: %s %s returned %s", provider_id, tool.name,
                       r.status_code)
        return _err(label + " returned an error (" + str(r.status_code) + ").")

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
    import clickup_generated
    mine = Tool(name="whoami",
                summary="Show which ClickUp account is currently connected "
                        "to your assistant.",
                method="GET", path="/user",
                unwrap=lambda d: d.get("user", {}),
                keep=("id", "username", "email"))
    return [mine] + [t for t in clickup_generated.build(Tool)
                     if t.name != "whoami"]


CLICKUP_TOOLS = _clickup_tools()

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

PROVIDER_TOOLS: Dict[str, List[Tool]] = {
    "github": GITHUB_TOOLS,
    "clickup": CLICKUP_TOOLS,
    "trello": TRELLO_TOOLS,
    "notion": NOTION_TOOLS,
    "n8n": N8N_TOOLS,
    "airtable": AIRTABLE_TOOLS,
    "hubspot": HUBSPOT_TOOLS,
    "zapier": ZAPIER_TOOLS,
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
    and mcp-proxy hands the model a real schema instead of a free-form blob."""
    fields = {}
    annotations = {}
    for name, (kind, desc, required) in (tool.args or {}).items():
        py, default = _TYPES.get(kind, (str, ""))
        if required:
            annotations[name] = py
            fields[name] = ...
        else:
            annotations[name] = Optional[py]
            fields[name] = None
    ns = {"__annotations__": annotations}
    ns.update({k: v for k, v in fields.items() if v is not ...})
    for k, v in fields.items():
        if v is ...:
            ns.pop(k, None)
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
