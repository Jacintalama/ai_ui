#!/usr/bin/env python3
"""Generate the per-user ClickUp tools from ClickUp's own OpenAPI specs.

Why generated rather than written
---------------------------------
2026-11-06. The chat told Ralph it could not create a ClickUp channel and
gave ClickUp's limits as the reason. The limit was ours: six hand-written
tools, all on v2, while chat is v3. Hand-writing the rest means reading
170 endpoints and getting every path and field name right by eye, and a
field name that is wrong by one character fails at the worst moment,
AFTER the person has approved the call. ClickUp publishes the spec, so
the names come from them.

    v2  https://developer.clickup.com/openapi/clickup-api-v2-reference.json
    v3  https://developer.clickup.com/openapi/ClickUp_PUBLIC_API_V3.yaml

Run it, read the diff, commit the output. NOT fetched at runtime: that
would put ClickUp's docs site between a person and their own tools, and
would let the tool list change under us without a commit anyone reviewed.

    python tools/generate_clickup_tools.py --v2 <spec> --v3 <spec> \
        --out clickup_generated.py

What it decides, and why
------------------------
* Path parameters become required args; query parameters become optional
  ones unless the spec says otherwise. Body fields come from the request
  schema, with the spec's own `required` list honoured.
* The leading /v2 or /v3 is stripped from the path, because the provider's
  base URL already ends in /api/v2 and a v3 tool carries its own base.
* `keep` is chosen per resource from RESPONSE_FIELDS below rather than
  left empty. An empty keep returns ClickUp's whole object, and a task is
  roughly 40 fields; 170 tools answering in full is a wall of text for the
  model to read past.
* Destructive operations are MARKED, not hidden. The caller decides.
"""
from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

#: Fields worth keeping per kind of object. Picked by hand because the
#: spec's response schemas are mostly untyped, and because the point is to
#: answer a person's question rather than to mirror ClickUp.
RESPONSE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "task": ("id", "name", "status", "due_date", "url", "assignees",
             "list", "priority"),
    "list": ("id", "name", "task_count", "folder", "space"),
    "folder": ("id", "name", "task_count", "space"),
    "space": ("id", "name", "private", "statuses"),
    "team": ("id", "name", "color", "members"),
    "comment": ("id", "comment_text", "user", "date", "resolved"),
    "checklist": ("id", "name", "items"),
    "tag": ("name", "tag_fg", "tag_bg"),
    "goal": ("id", "name", "due_date", "percent_completed", "owners"),
    "view": ("id", "name", "type", "parent"),
    "webhook": ("id", "endpoint", "events", "status"),
    "time": ("id", "task", "start", "end", "duration", "description"),
    "member": ("id", "username", "email", "role"),
    "doc": ("id", "name", "parent", "date_created"),
    "page": ("id", "name", "content", "date_updated"),
    "channel": ("id", "name", "type", "visibility"),
    "message": ("id", "content", "user_id", "date"),
    "custom_field": ("id", "name", "type", "type_config"),
    "template": ("id", "name"),
    "attachment": ("id", "title", "url", "date"),
}

#: Which of the above a path is about, longest match first so
#: "custom_field" wins over "field".
_RESOURCE_HINTS = (
    ("chat/channels", "channel"), ("chat/messages", "message"),
    ("message", "message"), ("channel", "channel"),
    ("custom_field", "custom_field"), ("field", "custom_field"),
    ("checklist", "checklist"), ("time_entries", "time"), ("time", "time"),
    ("webhook", "webhook"), ("goal", "goal"), ("view", "view"),
    ("comment", "comment"), ("attachment", "attachment"),
    ("template", "template"), ("member", "member"), ("guest", "member"),
    ("user", "member"), ("tag", "tag"), ("doc", "doc"), ("page", "page"),
    ("task", "task"), ("list", "list"), ("folder", "folder"),
    ("space", "space"), ("team", "team"), ("workspace", "team"),
)

#: Envelope keys ClickUp wraps collections in, so a list answer is a list.
_UNWRAP = ("tasks", "lists", "folders", "spaces", "teams", "comments",
           "checklists", "tags", "goals", "views", "webhooks", "members",
           "data", "docs", "pages", "channels", "messages", "fields",
           "templates", "attachments", "time_entries")

#: Operations nobody should reach from a chat by accident. They STAY,
#: because a person who asks to delete a list means it and the platform
#: holds every write for approval anyway. They are named here so the
#: summary can say plainly what is about to happen, which is what somebody
#: reads before pressing yes.
_DESTRUCTIVE = ("delete", "remove")

#: A value to send when the caller gave none, for a field ClickUp
#: REQUIRES and where there is one obvious answer. Without it a model
#: that omits the field gets a 400 after the person approved the call.
#: Keyed by (tool name, field) so it can never leak to another endpoint.
DEFAULTS: Dict[Tuple[str, str], Any] = {
    # type is required and is one of message or post. A person asking to
    # "send a message" means message; post is a different thing in
    # ClickUp's UI and is never what they meant implicitly.
    ("create_chat_message", "type"): "message",
    ("create_a_reply_message", "type"): "message",
}

#: Not tools. /v2/oauth/token is how THIS SERVICE exchanges a code for a
#: token; it needs the client secret, which a person's own connection does
#: not carry, and offering it to a model is offering a door with no room
#: behind it.
_NOT_A_USER_TOOL = ("/oauth/token",)


def _snake(name: str) -> str:
    """GetAuthorizedUser -> get_authorized_user."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


def _safe_arg(name: str) -> str:
    n = re.sub(r"[^0-9a-zA-Z_]", "_", str(name))
    if not n or n[0].isdigit():
        n = "f_" + n
    return n + "_" if keyword.iskeyword(n) else n


def _resource_of(path: str) -> str:
    low = path.lower()
    for needle, resource in _RESOURCE_HINTS:
        if needle in low:
            return resource
    return ""


def _schema_of(spec: Dict, components: Dict) -> Dict:
    body = spec.get("requestBody") or {}
    content = body.get("content") or {}
    for media in ("application/json", "application/json; charset=utf-8"):
        if media in content:
            return _resolve(content[media].get("schema") or {}, components)
    return {}


def _resolve(node: Any, components: Dict, depth: int = 0) -> Any:
    """Inline $refs so the generator sees real field names.

    The same job mcp-proxy does at index time, for the same reason: a
    pointer is not a field name. Depth-capped because a schema may refer
    to itself.
    """
    if depth > 10:
        return node if isinstance(node, dict) else {}
    if isinstance(node, list):
        return [_resolve(x, components, depth + 1) for x in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and "/" in ref:
        target = components.get(ref.rsplit("/", 1)[-1])
        if isinstance(target, dict):
            return _resolve(target, components, depth + 1)
        return {}
    return {k: _resolve(v, components, depth + 1) for k, v in node.items()}


def _type_of(schema: Dict) -> str:
    t = schema.get("type")
    if t in ("string", "boolean", "integer", "number", "array", "object"):
        # An array stays an array, and so does an object. Collapsing either
        # to "string" is what told a model that `assignees` was free text.
        # On 2026-11-09 create_task's version, an array of ids, got an
        # email address; update_task's version, an object {add, rem}, got
        # the right dict three times and could not pass a field declared
        # str. The two are genuinely different shapes one operation apart,
        # so this has to come from the spec rather than from the name.
        return {"integer": "integer", "number": "number",
                "boolean": "boolean", "array": "array",
                "object": "object"}.get(t, "string")
    any_of = schema.get("anyOf") or schema.get("oneOf") or []
    for option in any_of:
        if isinstance(option, dict) and option.get("type") not in (None, "null"):
            return _type_of(option)
    return "string"


#: How many of an object's keys are named in its description. Enough to
#: show the shape, not so many that `features` (nine of them) crowds out
#: the sentence ClickUp wrote.
OBJECT_KEYS_SHOWN = 6


def _describe(schema: Dict, fallback: str = "",
              shape: Optional[Dict] = None) -> str:
    """What one argument is, including the values it will accept.

    The enum matters. ClickUp declares type as one of message or post,
    priority as 1 to 4, and so on, and a model that is not told invents a
    value and gets a 400 after somebody approved the call. Dropping the
    enum was throwing away the most useful half of the spec.
    """
    # The title is the field name in prose ("Assignees"), used only when
    # ClickUp wrote no description. Once a shape sentence is produced it
    # adds nothing, and "...add, rem required. Assignees" reads like a
    # generated string rather than a sentence, so `from_title` drops it
    # in that case and keeps it otherwise.
    from_title = not schema.get("description") and bool(schema.get("title"))
    d = schema.get("description") or schema.get("title") or ""
    text = " ".join(str(d).split())[:140]
    choices = schema.get("enum")
    if isinstance(choices, list) and 0 < len(choices) <= 12:
        shown = ", ".join(str(c) for c in choices if c is not None)
        if shown:
            text = text.rstrip(".") + ". One of: " + shown
    # What goes IN the list, for the same reason the enum is carried. In
    # the v2 spec 20 body fields are arrays and 8 of them have no
    # description at all, so each was presented to the model as a plain
    # string described by repeating its own name. `assignees` is the one
    # that cost Ralph two approvals on 2026-11-09.
    # A QUERY parameter keeps its description on the parameter and its type
    # one level down, under `schema`, so the two do not live together and
    # the caller says where the shape is. Body fields pass neither and read
    # from themselves. Seven of get_filtered_team_tasks's filters are
    # arrays, and without this they read as plain strings.
    kind = shape if isinstance(shape, dict) else schema
    if kind.get("type") == "array":
        items = kind.get("items")
        item_type = items.get("type") if isinstance(items, dict) else None
        said = {"integer": "A list of whole numbers.",
                "number": "A list of numbers.",
                "boolean": "A list of true or false values.",
                "object": "A list of objects."}.get(
                    item_type, "A list of text values.")
        # FIRST, not appended. ClickUp's descriptions run long and the cap
        # below is what the model sees; appended, the shape was the part
        # that got cut off, which is the one fact it cannot guess.
        text = said + ("" if from_title
                       else (" " + text if text else ""))
    elif kind.get("type") == "object":
        # Which keys, and which of them cannot be left out. 18 body fields
        # in v2 are objects and 13 of those have no description, so each
        # read as a bare string named after itself: `features` with nine
        # required sub-fields, `tag` with name, tag_fg and tag_bg.
        props = kind.get("properties")
        names = ([n for n in props if isinstance(n, str)][:OBJECT_KEYS_SHOWN]
                 if isinstance(props, dict) else [])
        required = kind.get("required")
        required = ([r for r in required if isinstance(r, str)]
                    if isinstance(required, (list, tuple)) else [])
        if names:
            said = "An object with " + ", ".join(names)
            shown = [r for r in required if r in names][:OBJECT_KEYS_SHOWN]
            if shown:
                said += "; " + ", ".join(shown) + " required"
            said += "."
        else:
            said = "An object."
        text = said + ("" if from_title
                       else (" " + text if text else ""))
    # The fallback is the field's own name, which tells a model nothing it
    # cannot already read. It is a last resort, not the first choice, so it
    # applies only when neither the spec nor the shape said anything.
    if not text:
        text = " ".join(str(fallback).split())[:140]
    return text[:200]


def _envelope_key(op: Dict, components: Dict) -> str:
    """The single key a collection is wrapped in, or "".

    ClickUp answers {"tasks": [...]} rather than a bare list, and without
    this every listing tool hands the model an envelope it has to open,
    and the 25-item cap and the keep list apply to the wrapper rather than
    to the rows. Read from the response schema rather than guessed from
    the name: GetTasks also carries last_page, so "exactly one key that is
    an array" is the test, not "the first key".
    """
    responses = op.get("responses") or {}
    body = (responses.get("200") or responses.get("201") or {})
    content = (body.get("content") or {}).get("application/json") or {}
    schema = _resolve(content.get("schema") or {}, components)
    props = schema.get("properties") or {}
    arrays = [k for k, v in props.items()
              if isinstance(v, dict) and v.get("type") == "array"]
    return arrays[0] if len(arrays) == 1 and arrays[0] in _UNWRAP else ""


def operations(spec: Dict, version: str) -> List[Dict]:
    """Every operation in one spec, as the facts a Tool needs."""
    components = ((spec.get("components") or {}).get("schemas") or {})
    out: List[Dict] = []
    for path, methods in (spec.get("paths") or {}).items():
        shared = methods.get("parameters") or []
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            if not isinstance(op, dict):
                continue
            if any(skip in path for skip in _NOT_A_USER_TOOL):
                continue
            op_id = op.get("operationId") or ""
            summary = op.get("summary") or op_id
            name = _snake(op_id or summary)
            # Some operationIds have no case boundaries to split on:
            # "createatimeentry", "addtagsfromtimeentries". _snake cannot
            # help, and the result is a name a person cannot read and a
            # model cannot match a request against. The summary already
            # says it in words, so use that instead.
            # Prefer whichever reads as words. "startatime_entry" splits
            # once and still says nothing; "Start a time Entry" gives
            # start_a_time_entry. More word breaks wins.
            from_summary = _snake(summary)
            if from_summary and from_summary.count("_") > name.count("_"):
                name = from_summary
            if not name:
                continue

            args: Dict[str, Tuple[str, str, bool]] = {}
            query: Dict[str, str] = {}
            for param in _resolve(list(shared) + list(op.get("parameters") or []),
                                  components):
                if not isinstance(param, dict):
                    continue
                pname = param.get("name")
                if not pname:
                    continue
                arg = _safe_arg(pname)
                where = param.get("in")
                schema = param.get("schema") or {}
                # The same name can appear twice. /team/{team_id}/
                # time_entries/{timer_id} declares team_id as a required
                # PATH parameter and again as an optional QUERY one, and
                # whichever is read second used to win. Losing the path's
                # required flag means the brace is never filled and the
                # call fails with "Missing required value" only after
                # somebody approved it, so required is sticky here.
                already = args.get(arg)
                required = (bool(param.get("required")) or where == "path"
                            or bool(already and already[2]))
                args[arg] = (_type_of(schema),
                             _describe(param, str(pname), shape=schema),
                             required)
                if where == "query":
                    query[str(pname)] = arg

            body_fields: List[str] = []
            schema = _schema_of(op, components)
            props = (schema.get("properties") or {})
            required_names = set(schema.get("required") or [])
            for fname, fschema in props.items():
                if not isinstance(fschema, dict):
                    continue
                arg = _safe_arg(fname)
                # A body field may share a name with a PATH parameter
                # (time entries carry team_id in both). Declaring it again
                # from the body would drop the required flag the path
                # needs, and the call would then fail with "Missing
                # required value" only once somebody had approved it.
                already = args.get(arg)
                required = (fname in required_names) or bool(
                    already and already[2])
                args[arg] = (_type_of(fschema),
                             (already[1] if already else
                              _describe(fschema, str(fname))),
                             required)
                body_fields.append(fname)

            resource = _resource_of(path)
            envelope = _envelope_key(op, components)
            out.append({
                "name": name,
                "summary": summary,
                "description": op.get("description") or "",
                "method": method.upper(),
                # The provider base already ends in /api/v2, and a v3 tool
                # carries its own, so the version prefix comes off here.
                "path": re.sub(r"^/api/v[23]|^/v[23]", "", path) or "/",
                "version": version,
                "args": args,
                "query": query,
                "body": tuple(body_fields),
                "resource": resource,
                "keep": RESPONSE_FIELDS.get(resource, ()),
                "defaults": {f: v for (n, f), v in DEFAULTS.items()
                             if n == name and f in body_fields},
                "envelope": envelope,
                "destructive": any(w in name for w in _DESTRUCTIVE),
                "tags": op.get("tags") or [],
            })
    return out


#: A summary shorter than this is unfindable. mcp-proxy matches a
#: person's words against this sentence, so "Add Dependency." competes
#: with 172 others on three words. ClickUp's own summaries are that
#: terse, so the spec's longer `description` is folded in.
MIN_SUMMARY = 24


def _summary_for(op: Dict) -> str:
    """What the model reads when deciding which of 173 tools to use."""
    summary = " ".join(str(op.get("summary") or "").split()).replace('"', "'")
    detail = str(op.get("description") or "")
    # ClickUp's descriptions carry HTML, markdown links and literal
    # backslash-escapes from their docs pipeline. All of it reaches the
    # model verbatim otherwise, and a link is noise it cannot follow.
    detail = re.sub(r"<[^>]+>", "", detail)
    detail = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", detail)
    detail = detail.replace("\\", " ").replace("`", "")
    detail = " ".join(detail.split()).replace('"', "'")
    # First sentence only: ClickUp's descriptions run to paragraphs and
    # the whole thing lands in every tool listing the model reads.
    first = re.split(r"(?<=[.!?])\s", detail)[0] if detail else ""
    if first and first.lower() not in summary.lower():
        joined = summary.rstrip(".") + ". " + first
    else:
        joined = summary
    joined = joined.strip()
    if op["destructive"]:
        joined = joined.rstrip(".") + ". This deletes something."
    if not joined.endswith((".", "!", "?")):
        joined += "."
    if len(joined) < MIN_SUMMARY:
        # Nothing useful in the spec: say where it acts, which is at
        # least something to match on.
        where = op.get("resource") or "ClickUp"
        joined = joined.rstrip(".") + " in ClickUp (%s)." % where
    if len(joined) > 300:
        # Cut at a sentence if there is one, else a word. A summary that
        # stops mid-word reads as a bug in the tool listing.
        cut = joined[:300]
        stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        joined = (cut[:stop + 1] if stop > 80
                  else cut.rsplit(" ", 1)[0].rstrip(",;:") + ".")
    return joined


def render(ops: List[Dict]) -> str:
    """The generated module."""
    lines = [
        '"""ClickUp tools, GENERATED from ClickUp\'s own OpenAPI specs.',
        "",
        "Do not edit by hand. Regenerate with:",
        "",
        "    python tools/generate_clickup_tools.py --v2 <v2.json> \\",
        "        --v3 <v3.yaml> --out clickup_generated.py",
        "",
        "Written rather than fetched at runtime on purpose: fetching would",
        "put ClickUp's docs site between a person and their own tools, and",
        "would let the tool list change with no commit anyone reviewed.",
        "",
        "Takes the Tool class rather than importing it: mytools builds its",
        "provider table from this file, so importing mytools here would be a",
        "cycle, and whichever module was imported first would fail.",
        '"""',
        "",
        'CLICKUP_V3 = "https://api.clickup.com/api/v3"',
        "",
        "",
        "def _envelope(key):",
        '    """ClickUp wraps a collection: {"tasks": [...]}. Open it so the',
        "    item cap and the keep list apply to the rows rather than to the",
        '    wrapper."""',
        "    return lambda d: (d or {}).get(key, [])",
        "",
        "",
        "def build(Tool):",
        '    """Every ClickUp operation, as Tool objects."""',
        "    return [",
    ]
    seen = set()
    for op in sorted(ops, key=lambda o: o["name"]):
        if op["name"] in seen:
            continue
        seen.add(op["name"])
        summary = _summary_for(op)
        lines.append("        Tool(")
        lines.append('            name=%r,' % op["name"])
        lines.append('            summary=%r,' % summary)
        lines.append('            method=%r, path=%r,' % (op["method"], op["path"]))
        if op["version"] == "v3":
            lines.append("            base=CLICKUP_V3,")
        if op["args"]:
            lines.append("            args={")
            for arg, (t, d, req) in op["args"].items():
                lines.append("                %r: (%r, %r, %r)," % (arg, t, d, req))
            lines.append("            },")
        if op["query"]:
            lines.append("            query=%r," % (op["query"],))
        if op["body"]:
            lines.append("            body=%r," % (op["body"],))
        if op["defaults"]:
            lines.append("            defaults=%r," % (op["defaults"],))
        if op["envelope"]:
            lines.append("            unwrap=_envelope(%r)," % op["envelope"])
        if op["keep"]:
            lines.append("            keep=%r," % (op["keep"],))
        lines.append("        ),")
    lines.append("    ]")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", required=True)
    ap.add_argument("--v3", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    with open(a.v2, encoding="utf-8") as fh:
        v2 = json.load(fh)
    import yaml
    with open(a.v3, encoding="utf-8") as fh:
        v3 = yaml.safe_load(fh)

    ops = operations(v2, "v2") + operations(v3, "v3")
    text = render(ops)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    by_version: Dict[str, int] = {}
    for op in ops:
        by_version[op["version"]] = by_version.get(op["version"], 0) + 1
    print("generated %d tools (%s) -> %s"
          % (len({o["name"] for o in ops}),
             ", ".join("%s %d" % kv for kv in sorted(by_version.items())),
             a.out))
    no_keep = sorted({o["name"] for o in ops if not o["keep"]})
    if no_keep:
        print("  %d with no keep list (full objects): %s"
              % (len(no_keep), ", ".join(no_keep[:6])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
