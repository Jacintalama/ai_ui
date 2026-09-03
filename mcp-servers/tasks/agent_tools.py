"""Deciding what an agent may do, and doing it.

Split out of agent_runner because it is the part with teeth: agent_runner
decides what to say, this decides what actually happens to someone's mail.
"""
import inspect
import json
import logging
import os

import httpx
from sqlalchemy import bindparam
from sqlalchemy import text as sql_text

from db import session

logger = logging.getLogger(__name__)

#: Mutating verbs, matched as whole underscore-delimited tokens anywhere in
#: the name. This check runs first, in is_write_tool, and wins over the read
#: check below.
#:
#: That ordering is the fix for a Critical bug: the earlier rule matched a
#: read verb at the start of the name, or as a whole segment anywhere in the
#: name, and returned False (read) the moment it found one. It never asked
#: whether the same name also carried a mutating verb. So search_and_replace
#: read as a read because it starts with "search_", and clickup_delete_
#: list_item read as a read because "_list_" appears mid-string -- both are
#: writes. Putting the write-verb check first and letting it win closes that
#: specific class: a read-looking token elsewhere in the name can no longer
#: hide a delete, create, update, replace, and so on.
#:
#: This does not make the classifier exhaustive. It is a fixed vocabulary,
#: so a mutating verb not on this list (or a read-looking phrase that is
#: secretly destructive, like "get_rid_of_x") can still misclassify. Extend
#: this set when a false negative like that is found; do not read its
#: presence as a guarantee the gate is complete.
_WRITE_VERBS = frozenset({
    "create", "update", "delete", "remove", "send", "reply", "draft",
    "upload", "write", "set", "add", "move", "clear", "mark", "archive",
    "replace", "rename", "edit", "insert", "post", "patch", "destroy",
    "purge", "revoke", "grant", "share", "invite", "assign", "merge",
    "cancel", "trigger", "execute", "sync", "import", "export", "save",
    "publish", "unpublish", "enable", "disable", "reset", "restore",
    "duplicate", "copy", "close", "complete", "approve", "reject", "star",
    "unstar", "label", "tag", "comment",
})

#: Verbs that read, as these tool surfaces currently name things, checked
#: against the first THREE underscore-delimited tokens of the name. Two
#: tokens was not enough: a proxy tool can arrive with a two-part server
#: prefix, e.g. google-drive_gdrive_list_files or web-search_web_search,
#: which pushes the read verb to the third token. Widening to three tokens
#: only fixes those false writes because the write-verb veto above runs
#: first and scans EVERY token in the name, not just the first three -- a
#: mutating verb anywhere in the name has already returned True by the time
#: this set is even consulted, so a read word that happens to land in the
#: first three tokens can never smuggle a write past that veto.
#:
#: "whoami" is included even though it is not really a verb: it is a
#: single-word identity check with no separate verb+noun form, so it has no
#: other way to be recognized once it is wrapped in a per-user proxy prefix
#: (my-clickup_whoami, my-github_whoami, and so on). Plain "whoami" is also
#: pinned in READ_METHODS below; this entry exists for the prefixed form.
#:
#: Not a claim that these verbs can never mutate. "check" was removed from
#: this set for exactly that reason: it means inspect in check_my_access but
#: means tick off in a ClickUp or Trello checklist, and check_item mutates.
#: A verb that reads on one service and writes on another does not belong
#: here; pin the specific read method in READ_METHODS instead.
_READ_VERBS = frozenset({
    "list", "get", "search", "read", "fetch", "find", "describe", "count",
    "query", "view", "show", "whoami",
})

#: The native tools, pinned by name. Two of these are pinned against the
#: classifier's step-4 default, not against the verb rule, which has no
#: opinion on either; see the note beside each. Written out so that
#: renaming a method has to break a test rather than silently change
#: what an unattended agent may do.
READ_METHODS: frozenset[str] = frozenset({
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",
    "list_calendar_events",
    "list_drive_files", "search_drive", "read_drive_file",
    # Pinned by name because "check" is no longer a read verb: this one
    # really does only inspect, and it exists in this repo (mcp-proxy).
    "check_my_access",
    "whoami",
    # Pinned because the verb rule has no opinion here, not because it
    # disagrees: neither "propose" nor "change" is a write verb, so this
    # name falls through to the default, and the default is write. It
    # records what an agent WOULD do and hands back a code the person has
    # to approve, so refusing it would leave a read only agent unable to
    # even say what it would change. Note the same default is the ONLY
    # thing keeping apply_app_change a write, so weakening it, or adding
    # "apply" to _READ_VERBS, would open a real write path.
    "propose_app_change",
})


def is_write_tool(method_name: str) -> bool:
    """True when calling this method could change something.

    Unknown counts as a write. That is the whole point: the classifier is
    consulted before an unattended run is allowed to act, so the failure
    direction has to be refusal.

    Order of checks, and why it matters:
    1. If any underscore-delimited token in the name is a known mutating
       verb, this is a write. Checked first, wins over everything below.
    2. Otherwise, if the name is one of the explicitly pinned READ_METHODS,
       it is a read.
    3. Otherwise, if any of the first three tokens is a read verb, it is a
       read.
    4. Otherwise it is a write, by default.
    """
    name = (method_name or "").strip().lower()
    if not name:
        return True
    tokens = name.split("_")
    if any(token in _WRITE_VERBS for token in tokens):
        return True
    if name in READ_METHODS:
        return False
    if any(token in _READ_VERBS for token in tokens[:3]):
        return False
    return True


#: A single tool call gets less than the whole run's budget: several may be
#: needed before the agent can answer.
TOOL_TIMEOUT_SECONDS = 60


def _proxy_url() -> str:
    return os.environ.get("MCP_PROXY_URL", "http://mcp-proxy:8000").rstrip("/")


async def _post_json(url, json=None, headers=None, timeout=None):
    # The json= parameter name deliberately mirrors httpx's own keyword, so
    # inside this function it shadows the module-level `json` import.
    async with httpx.AsyncClient(timeout=timeout or TOOL_TIMEOUT_SECONDS) as c:
        return await c.post(url, json=json, headers=headers)


async def _load_native_tool_source(
    method_name: str, allowed_tool_ids: list[str] | None = None,
) -> str | None:
    """The source of the native Open WebUI tool defining this method.

    Open WebUI keeps each tool as a Python module in public.tool.content and
    exec's it to call the method. Doing the same keeps one source of truth
    for how a tool reaches its service: the Gmail tool, for instance, is a
    thin client for mcp-gmail, and duplicating that mapping here would drift
    the first time somebody edits the tool in the web UI.

    `allowed_tool_ids` scopes the query to the agent's own declared tools
    (its meta.toolIds), so a method that only exists in a tool the agent was
    never given is never even read here. Without that scope, any agent could
    be steered -- by a prompt-injected document, calendar event, or email --
    into naming a method that belongs to a tool it was never granted, and
    that method's source would still be found by a plain substring match and
    executed as the real user. A name not covered by the allowed tools still
    falls through to the caller's proxy path rather than being refused
    outright, because proxy tools are not rows in this table and mcp-proxy
    does its own per-user access control on them.

    An empty or missing list keeps the old, unscoped lookup -- the behaviour
    for a schedule with no agent, or an agent that declares no tools.
    """
    # ORDER BY id: without it, "first row containing the needle" depends on
    # physical scan order, which Postgres does not promise to hold still.
    # Ordering makes the winner among colliding rows deterministic and
    # reproducible, not correct -- two tools defining the same public
    # method name is a situation the platform should avoid in the first
    # place, and this only pins down which one wins when it happens anyway.
    if allowed_tool_ids:
        stmt = sql_text(
            "SELECT content FROM public.tool WHERE id IN :ids ORDER BY id"
        ).bindparams(bindparam("ids", expanding=True))
        params: dict = {"ids": list(allowed_tool_ids)}
    else:
        stmt = sql_text("SELECT content FROM public.tool ORDER BY id")
        params = {}
    async with session() as s:
        rows = (await s.execute(stmt, params)).fetchall()
    needle = "def " + method_name + "("
    for (content,) in rows:
        if content and needle in content:
            return content
    return None


def _filter_supported_kwargs(method, params: dict) -> dict:
    """Drop any argument the model supplied that `method` does not accept.

    Models invent parameters routinely -- a hallucinated keyword otherwise
    turns into a bare TypeError that kills the whole tool call. Open WebUI's
    own tool runner filters to the declared properties before calling for
    the same reason; mirror that here rather than trusting the model's
    argument list verbatim. A method that declares **kwargs accepts
    anything, so nothing is dropped for it.
    """
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return dict(params)

    parameters = signature.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return dict(params)

    accepted = set(parameters) - {"self"}
    dropped = [key for key in params if key not in accepted]
    if dropped:
        # Debug only, and only the names -- never the values the model sent.
        logger.debug("dropping unexpected arguments for %s: %s",
                     getattr(method, "__name__", method), dropped)
    return {key: value for key, value in params.items() if key in accepted}


async def _run_native(source: str, method_name: str, params: dict,
                       user_email: str) -> str:
    namespace: dict = {}
    exec(compile(source, "<owui_tool>", "exec"), namespace)   # noqa: S102
    tools_cls = namespace.get("Tools")
    if tools_cls is None:
        raise RuntimeError("tool module defines no Tools class")
    instance = tools_cls()
    method = getattr(instance, method_name, None)
    if method is None:
        raise RuntimeError("tool module has no method " + method_name)

    call_kwargs = _filter_supported_kwargs(method, params)
    # Identity always comes from the caller, never from the model's
    # arguments -- set last so nothing supplied above can override it.
    call_kwargs["__user__"] = {"email": user_email}

    # Most native tools are async, but some (excel_creator, executive_
    # dashboard) are plain `def`. Awaiting a plain return value raises, so
    # only await when the call actually gave back something awaitable.
    result = method(**call_kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, str) else json.dumps(result)


async def execute_tool_call(
    tool_call: dict, user_email: str,
    allowed_native_tools: list[str] | None = None,
) -> str:
    """Run one tool call as `user_email` and return a string for the model.

    `allowed_native_tools` is the calling agent's own declared tool ids
    (meta.toolIds). It scopes the native lookup below so an agent cannot run
    a native method that belongs to a tool it was never given -- see
    _load_native_tool_source. Leave it None (the default) to keep the old,
    unscoped lookup.

    Never raises. A tool that fails returns its failure as the tool result so
    the agent can say what went wrong, which is far more useful to the owner
    than a run that dies with nothing.
    """
    # Shape checks before anything is read off these, and note that they sit
    # OUTSIDE the try below. `(tool_call or {})` only substitutes for a FALSY
    # value, so a truthy non-mapping (a bare string, an int, a list) used to
    # sail through into .get() and raise AttributeError straight out of a
    # function whose whole contract is that it never raises. The values here
    # come from a model's tool-call plumbing, so the wrong type is exactly
    # the malformation to expect.
    if not isinstance(tool_call, dict):
        logger.error("tool call was not an object")
        return "That tool call was malformed, so nothing was run."
    fn = tool_call.get("function")
    if not isinstance(fn, dict):
        logger.error("tool call carried no function object")
        return "That tool call named no tool, so nothing was run."
    name = fn.get("name")
    if not isinstance(name, str):
        logger.error("tool call named no tool, or named one that was not text")
        return "That tool call named no tool, so nothing was run."
    name = name.strip()
    raw_args = fn.get("arguments") or "{}"
    try:
        # raw_args is usually a JSON string, but a model (or a hand-built
        # tool_call in a test) can hand back arguments already decoded as
        # some other type. dict(...) raises TypeError, not ValueError, for
        # anything that is not a mapping or an iterable of pairs -- an int,
        # a float, a bool, a plain list of numbers -- so both must be caught
        # here or a malformed call crashes the run instead of degrading.
        params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (ValueError, TypeError):
        params = {}
    if not isinstance(params, dict):
        params = {}

    if not name:
        return "That tool call named no tool, so nothing was run."

    try:
        # The native path is the one with teeth: it execs the tool source
        # and calls getattr(instance, name) on the result. A private helper
        # (_email, _post) or a dunder (__init__, __class__) must never reach
        # that getattr, even if its name happens to match a "def" substring
        # somewhere in a tool module -- so refuse a leading underscore here,
        # immediately before the native source lookup, before either it or
        # the getattr that follows can run.
        #
        # A name that merely fails isidentifier() (a hyphen, most often) is
        # a different case: it can never be a native method name -- Python
        # method names cannot contain a hyphen -- so it is simply not
        # eligible for the native path, and native lookup is skipped for
        # it. It is NOT refused outright, because a hyphenated name such as
        # my-clickup_list_tasks is a perfectly ordinary proxy tool name.
        # The proxy path performs no attribute lookup, so there is nothing
        # here for it to defend; mcp-proxy does its own validation and
        # per-user access control on /meta/call_tool.
        if name.startswith("_"):
            logger.error("tool call requested a non-public method name %r", name)
            return "The tool " + name + " is not available."

        source = None
        if name.isidentifier():
            source = await _load_native_tool_source(name, allowed_native_tools)
        if source:
            return await _run_native(source, name, params, user_email)

        response = await _post_json(
            _proxy_url() + "/meta/call_tool",
            json={"tool_name": name, "arguments": params},
            headers={"X-User-Email": user_email},
            timeout=TOOL_TIMEOUT_SECONDS)
        if response.status_code == 403:
            return ("You do not have access to the service behind the tool "
                    + name + ".")
        if response.status_code == 404:
            return "The tool " + name + " is not available."
        if response.status_code >= 400:
            return "The tool " + name + " could not be run this time."
        payload = response.json()
        return payload if isinstance(payload, str) else json.dumps(payload)
    except Exception:                                       # noqa: BLE001
        # Never surface the exception text: an httpx error carries the URL.
        logger.error("tool call %s failed", name, exc_info=True)
        return "The tool " + name + " could not be run this time."
