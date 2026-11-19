# -*- coding: utf-8 -*-
"""The n8n nodes IO can build, with the shapes this platform's n8n writes.

WHERE THESE CAME FROM. Not a changelog. Every shape below was read out
of a real workflow on the live instance on 2026-11-18, by surveying all
33 workflows and taking the newest typeVersion each node appeared with.

That distinction matters more than it looks. A changelog says what the
newest n8n supports. It does not say what THIS instance accepts, and a
node tagged with a typeVersion the instance does not know loads as a
broken node in the editor, which is worse than an older shape that
works. When the instance is upgraded, re-run the survey rather than
reading release notes:

    scripts/n8n_survey.py   (prints every node type and version in use)

WHY THIS EXISTS. IO knew two nodes, manualTrigger and set, out of the
27 in real use. Asked for anything useful, "call this API every morning
and post the result", it had no shape for httpRequest (51 uses, the
single most used node on the instance) or scheduleTrigger, and would
invent one. An invented shape creates a node that exists, loads wrong,
and reports no error.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

import aiui_link


@dataclass(frozen=True)
class NodeShape:
    """One node type, as this instance writes it."""

    type: str
    type_version: float
    summary: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    #: A workflow with no trigger cannot be switched on at all.
    is_trigger: bool = False
    #: Whether this trigger is enough to ACTIVATE a workflow. Measured
    #: live: a manual trigger is a trigger, and n8n still answers 400
    #: "no trigger node" when you try to activate a workflow that has
    #: only one. The distinction has no other way to be known.
    activates: bool = False


NODES: Dict[str, NodeShape] = {
    # --- triggers ---------------------------------------------------
    "manualTrigger": NodeShape(
        type="n8n-nodes-base.manualTrigger",
        type_version=1,
        summary="Runs only when somebody clicks Execute in n8n. Fine for "
                "testing, but a workflow with only this cannot be "
                "switched on.",
        parameters={},
        is_trigger=True,
        activates=False),
    "scheduleTrigger": NodeShape(
        type="n8n-nodes-base.scheduleTrigger",
        type_version=1.2,
        summary="Runs on a timetable. The rule below is every Monday at "
                "14:00; `field` may be minutes, hours, days, weeks or "
                "months.",
        parameters={"rule": {"interval": [
            {"field": "weeks", "triggerAtDay": [1], "triggerAtHour": 14}]}},
        is_trigger=True,
        activates=True),
    "webhook": NodeShape(
        type="n8n-nodes-base.webhook",
        type_version=2.1,
        summary="Runs when something POSTs to its URL. `path` is the "
                "last part of that URL and must be unique on the "
                "instance.",
        parameters={"httpMethod": "POST", "options": {},
                    "path": "my-hook"},
        is_trigger=True,
        activates=True),

    # --- doing things -----------------------------------------------
    "httpRequest": NodeShape(
        type="n8n-nodes-base.httpRequest",
        type_version=4.4,
        summary="Calls a URL. The most used node on this instance. A "
                "value beginning `=` is an expression, so "
                "\"={{ $json.url }}\" takes the url from the item "
                "coming in.",
        parameters={"url": "https://example.com", "options": {}}),
    # 2026-11-19: a step that uses an app the person connected in AIUI.
    # Not read off the live instance like the rest: it is an httpRequest
    # (shape above) aimed at our own route, with the credential link_aiui
    # saves. See aiui_link.
    "aiuiTool": NodeShape(
        type="n8n-nodes-base.httpRequest",
        type_version=4.4,
        summary="Runs ONE tool of an app the person connected in AIUI "
                "(Trello, Airtable, GitHub, Google Drive and the rest), "
                "with their own account. Use this instead of n8n's own "
                "node for that app, so nothing is connected twice. Call "
                "link_aiui first for the credential id, and set "
                "\"credentials\": {\"httpHeaderAuth\": {\"id\": \"<id>\", "
                "\"name\": \"AIUI\"}} on the node. jsonBody names the app, "
                "the tool and its args. To use an earlier step's data, "
                "make jsonBody an expression and keep app and tool "
                "written out: \"={\\\"app\\\": \\\"github\\\", \\\"tool\\\": "
                "\\\"review_pull_request\\\", \\\"args\\\": {\\\"owner\\\": "
                "\\\"o\\\", \\\"repo\\\": \\\"r\\\", \\\"number\\\": "
                "{{ $json.number }}, \\\"event\\\": \\\"APPROVE\\\"}}\". "
                "A step whose app or tool comes from an expression is "
                "never approved. The AIUI credential goes on nothing "
                "else. Writing tools in it run only because the person "
                "approves this workflow.",
        parameters={"method": "POST", "url": aiui_link.RUN_URL,
                    "authentication": "genericCredentialType",
                    "genericAuthType": "httpHeaderAuth",
                    "sendBody": True, "specifyBody": "json",
                    "jsonBody": "{\"app\": \"github\", \"tool\": "
                                "\"list_my_repos\", \"args\": {}}",
                    "options": {}}),
    "code": NodeShape(
        type="n8n-nodes-base.code",
        type_version=2,
        summary="Runs JavaScript over the items. `$input.all()` is "
                "everything coming in; return a list of {json: {...}}.",
        parameters={"jsCode": "return $input.all();"}),
    "set": NodeShape(
        type="n8n-nodes-base.set",
        type_version=3.4,
        summary="Sets fields on each item. The assignments are NESTED "
                "one level, which is the mistake worth knowing about. "
                "An empty list sets nothing and is refused.",
        parameters={"assignments": {"assignments": [
            {"id": "f1", "name": "message", "type": "string",
             "value": "hello"}]}}),
    "respondToWebhook": NodeShape(
        type="n8n-nodes-base.respondToWebhook",
        type_version=1.5,
        summary="Answers the caller of a webhook. Only works in a "
                "workflow that starts with a webhook node.",
        parameters={"respondWith": "text",
                    "responseBody": "={{ $json.result }}",
                    "options": {}}),

    # --- choosing a path --------------------------------------------
    "if": NodeShape(
        type="n8n-nodes-base.if",
        type_version=2.3,
        summary="Splits into two outputs, true then false. Connect both "
                "by index: output 0 is true, output 1 is false.",
        parameters={"conditions": {
            "combinator": "and",
            "conditions": [{
                "id": "c1",
                "leftValue": "={{ $json.status }}",
                "operator": {"operation": "equals", "type": "string"},
                "rightValue": "completed"}],
            "options": {"caseSensitive": True, "leftValue": "",
                        "typeValidation": "strict", "version": 3}},
            "options": {}}),
    "switch": NodeShape(
        type="n8n-nodes-base.switch",
        type_version=3.4,
        summary="Like If, but with one output per rule rather than two.",
        parameters={"rules": {"values": [{
            "conditions": {
                "combinator": "and",
                "conditions": [{
                    "id": "r1",
                    "leftValue": "={{ $json.label }}",
                    "operator": {"operation": "equals", "type": "string"},
                    "rightValue": "urgent"}],
                "options": {"caseSensitive": True, "leftValue": "",
                            "typeValidation": "strict", "version": 3}}}]},
            "options": {}}),
    "merge": NodeShape(
        type="n8n-nodes-base.merge",
        type_version=3.2,
        summary="Joins several branches back into one. `numberInputs` "
                "must match how many branches feed it.",
        parameters={"mode": "combine", "combineBy": "combineByPosition",
                    "numberInputs": 2, "options": {}}),
}


def _copy(value: Any) -> Any:
    """A deep-ish copy of plain JSON.

    The catalogue is module state. Handing a caller the SAME dict every
    time would mean one built node's edits reaching into the catalogue
    and into every node built after it, which is the kind of bug that
    only shows up on the second workflow of a session.
    """
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def build(kind: str, name: str, position: List[int]) -> Dict[str, Any]:
    """One node, ready to put in a workflow body."""
    shape = NODES.get(kind)
    if shape is None:
        raise ValueError(
            "I do not know an n8n node called %r. I can build: %s"
            % (kind, ", ".join(sorted(NODES))))
    return {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "type": shape.type,
        "typeVersion": shape.type_version,
        "position": list(position),
        "parameters": _copy(shape.parameters),
    }


def describe() -> str:
    """The catalogue as text a model can build from.

    Deliberately includes the parameters, not just the names. A list of
    node names tells a model nothing it could not guess; the shape is
    the whole value here, because the shape is what it was getting
    wrong.
    """
    import json

    lines = []
    for kind in sorted(NODES):
        s = NODES[kind]
        note = ""
        if s.is_trigger and not s.activates:
            note = "  (a trigger, but NOT enough to switch a workflow on)"
        elif s.is_trigger:
            note = "  (a trigger)"
        lines.append("%s%s\n  %s\n  type %s, typeVersion %s\n  parameters: %s"
                     % (kind, note, s.summary, s.type, s.type_version,
                        json.dumps(s.parameters)))
    return "\n\n".join(lines)
