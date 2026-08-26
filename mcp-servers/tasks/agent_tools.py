"""Deciding what an agent may do, and doing it.

Split out of agent_runner because it is the part with teeth: agent_runner
decides what to say, this decides what actually happens to someone's mail.
"""
import inspect
import json
import logging
import os

import httpx
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
#: against the first token or the second (proxy tools arrive
#: server-qualified, e.g. clickup_list_tasks, so the read verb is the second
#: segment). Only consulted once the write-verb veto above has cleared the
#: name, so a read verb sitting elsewhere (the "search" in
#: search_and_replace) no longer marks a write as safe.
#:
#: Not a claim that these verbs can never mutate. "check" was removed from
#: this set for exactly that reason: it means inspect in check_my_access but
#: means tick off in a ClickUp or Trello checklist, and check_item mutates.
#: A verb that reads on one service and writes on another does not belong
#: here; pin the specific read method in READ_METHODS instead.
_READ_VERBS = frozenset({
    "list", "get", "search", "read", "fetch", "find", "describe", "count",
    "query", "view", "show",
})

#: The native tools, pinned by name. The verb rule already agrees with every
#: one of these; they are written out so that renaming a method has to break
#: a test rather than silently change what an unattended agent may do.
READ_METHODS: frozenset[str] = frozenset({
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",
    "list_calendar_events",
    "list_drive_files", "search_drive", "read_drive_file",
    # Pinned by name because "check" is no longer a read verb: this one
    # really does only inspect, and it exists in this repo (mcp-proxy).
    "check_my_access",
    "whoami",
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
    3. Otherwise, if the first token or the second token is a read verb,
       it is a read.
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
    if tokens[0] in _READ_VERBS:
        return False
    if len(tokens) > 1 and tokens[1] in _READ_VERBS:
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


async def _load_native_tool_source(method_name: str) -> str | None:
    """The source of the native Open WebUI tool defining this method.

    Open WebUI keeps each tool as a Python module in public.tool.content and
    exec's it to call the method. Doing the same keeps one source of truth
    for how a tool reaches its service: the Gmail tool, for instance, is a
    thin client for mcp-gmail, and duplicating that mapping here would drift
    the first time somebody edits the tool in the web UI.
    """
    # ORDER BY id: without it, "first row containing the needle" depends on
    # physical scan order, which Postgres does not promise to hold still.
    # Ordering makes the winner among colliding rows deterministic and
    # reproducible, not correct -- two tools defining the same public
    # method name is a situation the platform should avoid in the first
    # place, and this only pins down which one wins when it happens anyway.
    async with session() as s:
        rows = (await s.execute(
            sql_text("SELECT content FROM public.tool ORDER BY id"))).fetchall()
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


async def execute_tool_call(tool_call: dict, user_email: str) -> str:
    """Run one tool call as `user_email` and return a string for the model.

    Never raises. A tool that fails returns its failure as the tool result so
    the agent can say what went wrong, which is far more useful to the owner
    than a run that dies with nothing.
    """
    fn = (tool_call or {}).get("function") or {}
    name = (fn.get("name") or "").strip()
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

    # A tool name is only ever a plain public method or tool identifier.
    # Refuse anything else here, before either the native source scan or
    # the getattr lookup that follows it -- this is what keeps a private
    # helper (_email, _post) or a dunder (__init__, __class__) from ever
    # being resolved and run, even if its name happens to match a "def"
    # substring somewhere in a tool module.
    if not name.isidentifier() or name.startswith("_"):
        logger.error("tool call requested a non-public method name %r", name)
        return "The tool " + name + " is not available."

    try:
        source = await _load_native_tool_source(name)
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
