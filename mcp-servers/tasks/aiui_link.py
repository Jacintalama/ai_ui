"""AIUI in a person's own n8n (2026-11-19).

Lukas wants a person's n8n workflows to use the apps that person connected
in AIUI, without connecting them again in n8n. The step that does it is an
ordinary n8n httpRequest node calling `POST /api/tasks/tools/run`
(routes_tool_run), so the vendor credential stays in AIUI and the only
secret in n8n is an AIUI key.

Three things live here:

- `link`: the `link_aiui` tool. Makes an AIUI key with the `tools` scope
  and saves it in the person's n8n as a credential called "AIUI", through
  the n8n connection they already have. Reuses it next time. The key is
  never in the answer: a chat must never show it.
- `check_steps`: refuses an AIUI step with no credential, which n8n would
  accept and fail on every run.
- `approve_steps`: after the person approved a workflow AIUI built, its
  write steps become runnable from their key. Approving the workflow is
  approving its steps; nothing else ever makes a write runnable.

Who can see the credential: n8n keeps a credential private to the n8n user
whose API key created it, and AIUI remembers it per AIUI person by id,
never by name, so two people on one n8n server cannot pick up each
other's.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

import automation_keys

logger = logging.getLogger("aiui_link")

#: Never taken from a request: a model must not be able to point a step
#: somewhere else by changing the host.
PUBLIC_URL = os.environ.get("AIUI_PUBLIC_URL",
                            "https://ai-ui.coolestdomain.win").rstrip("/")
RUN_URL = PUBLIC_URL + "/api/tasks/tools/run"
CREDENTIAL_NAME = "AIUI"
CREDENTIAL_TYPE = "httpHeaderAuth"
KEY_LABEL = "n8n (made by AIUI)"
N8N_TIMEOUT_SECONDS = 20.0

_HTTP_REQUEST = "n8n-nodes-base.httpRequest"


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


#: Every `"app":` / `"tool":` key, whatever its value, and the ones whose
#: value is written out. Both must be exactly one, so a literal name in a
#: nested argument cannot stand in for a name built by an expression.
_KEY = {k: re.compile(r'"%s"\s*:' % k) for k in ("app", "tool")}
_LITERAL = {k: re.compile(r'"%s"\s*:\s*"([a-z0-9_]+)"' % k)
            for k in ("app", "tool")}


def _expression_target(body: str) -> Optional[Tuple[str, str]]:
    """(app, tool) from an n8n expression body, when both are written out.

    A step that takes data from an earlier one (`"number": {{ $json.number
    }}`) is stored by n8n as an expression, `={...}`, which is not JSON
    until it runs. Without reading it, the one workflow everybody asks for
    ("approve each pull request that says ready") was refused on every run
    after the person had said yes to it.

    Only a literal name counts, and only one of each: a name built from an
    expression, or a second `"tool": "..."` hiding in an argument, names
    nothing. That is safe to be loose about because it only chooses what
    to approve; the route still checks the tool actually sent, every run.
    """
    found = {}
    for key, pattern in _LITERAL.items():
        hits = pattern.findall(body)
        if len(hits) != 1 or len(_KEY[key].findall(body)) != 1:
            return None
        found[key] = hits[0]
    return found["app"], found["tool"]


def step_target(node: Any) -> Optional[Tuple[str, str]]:
    """(app, tool) for an AIUI step, or None for any other node.

    The body may be a JSON string, as n8n writes it, an object, as a model
    often does, or an expression (`={...}`) when it uses an earlier step's
    data; see `_expression_target`.
    """
    if not isinstance(node, dict) or node.get("type") != _HTTP_REQUEST:
        return None
    params = node.get("parameters")
    if not isinstance(params, dict) or params.get("url") != RUN_URL:
        return None
    body = params.get("jsonBody")
    if isinstance(body, str) and body.startswith("="):
        return _expression_target(body[1:])
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if not isinstance(body, dict):
        return None
    app, tool = body.get("app"), body.get("tool")
    if not (isinstance(app, str) and isinstance(tool, str) and app and tool):
        return None
    return app.strip().lower(), tool.strip()


def _is_aiui_url(node: Any) -> bool:
    return (isinstance(node, dict) and node.get("type") == _HTTP_REQUEST
            and isinstance(node.get("parameters"), dict)
            and node["parameters"].get("url") == RUN_URL)


def _credentials(node: Any) -> List[dict]:
    creds = node.get("credentials") if isinstance(node, dict) else None
    if not isinstance(creds, dict):
        return []
    return [c for c in creds.values() if isinstance(c, dict)]


def _carries_aiui(node: Any, credential_id: Optional[str]) -> bool:
    for cred in _credentials(node):
        if cred.get("name") == CREDENTIAL_NAME:
            return True
        if credential_id and str(cred.get("id") or "") == str(credential_id):
            return True
    return False


def carries_credentials(nodes: List[Any]) -> bool:
    """Whether any node names a credential at all."""
    return any(_credentials(n) for n in nodes or [])


def check_steps(nodes: List[Any], credential_id: Optional[str] = None) -> None:
    """Refuse two shapes.

    The AIUI credential on a node that does not call our route. It is a
    plain header credential, and n8n sends it to whatever URL the node
    holding it names, so a node pointed anywhere else (or at an
    expression) would hand the key to that host. Matched by the name and,
    when the caller knows it, by the id AIUI remembered, since n8n finds a
    credential by id and a node can call it anything.

    And an AIUI step that names no credential: n8n accepts it and then
    answers 401 from us on every single run.
    """
    for node in nodes or []:
        if _carries_aiui(node, credential_id) and not _is_aiui_url(node):
            raise ValueError(
                '"%s" carries the AIUI credential but does not call AIUI. '
                "That credential only goes on an HTTP Request node whose "
                "URL is exactly %s; use another credential for anything "
                "else." % (str(node.get("name") or "A node"), RUN_URL))
        if not _is_aiui_url(node):
            continue
        cred = ((node.get("credentials") or {}).get(CREDENTIAL_TYPE) or {})
        if not (isinstance(cred, dict) and cred.get("id")):
            raise ValueError(
                '"%s" calls AIUI but carries no credential, so every run '
                "would be refused. Call link_aiui first for the id, then "
                'give the node: "authentication": "genericCredentialType", '
                '"genericAuthType": "httpHeaderAuth", and "credentials": '
                '{"httpHeaderAuth": {"id": "<id from link_aiui>", '
                '"name": "AIUI"}}' % str(node.get("name") or "A node"))


async def approve_steps(email: str, nodes: List[Any]) -> List[str]:
    """Make this workflow's write steps runnable from the person's key.

    Called only after n8n accepted a workflow the person approved in the
    chat. Approvals only grow: a step taken out of a workflow stays
    approved, and revoking the key is the reset.
    """
    import mytools
    from routes_tool_run import step_name

    writes: List[str] = []
    for node in nodes or []:
        target = step_target(node)
        if not target:
            continue
        app, name = target
        tool = {t.name: t for t in mytools.PROVIDER_TOOLS.get(app, [])}.get(name)
        if tool is not None and mytools._writes(tool):
            step = step_name(app, name)
            if step not in writes:
                writes.append(step)
    if not writes:
        return []
    key = await automation_keys.n8n_key(email)
    if not key:
        return []
    await automation_keys.allow_writes(email, key["id"], writes)
    return writes


async def credential_problem(email: str, nodes: List[Any]) -> Optional[str]:
    """Why this workflow may not be sent to n8n, or None.

    `check_steps` with the credential id this person's key is stored
    under, which only the database knows. A workflow naming no credential
    at all cannot carry the key, so it needs no lookup; one that names
    some, when the lookup fails, is refused, because the check it needed
    could not be made.
    """
    if not carries_credentials(nodes):
        return None
    try:
        key = await automation_keys.n8n_key(email)
    except Exception as e:                                  # noqa: BLE001
        logger.warning("aiui_link: key lookup failed (%s)", type(e).__name__)
        return ("I could not check which credentials this workflow uses, "
                "so I did not send it. Try again in a minute.")
    try:
        check_steps(nodes, (key or {}).get("n8n_credential_id"))
    except ValueError as e:
        return str(e)
    return None


async def _save_in_n8n(auth, key: str) -> Tuple[Optional[str], Optional[str]]:
    """(credential id, None) or (None, why not). Never says the key."""
    body = {"name": CREDENTIAL_NAME, "type": CREDENTIAL_TYPE,
            "data": {"name": "Authorization", "value": "Bearer " + key}}
    try:
        async with httpx.AsyncClient(timeout=N8N_TIMEOUT_SECONDS) as client:
            r = await client.post(auth.base_url.rstrip("/") + "/api/v1/credentials",
                                  headers=auth.headers, json=body)
    except Exception as e:                                  # noqa: BLE001
        logger.warning("aiui_link: n8n unreachable (%s)", type(e).__name__)
        return None, ("Your n8n did not answer, so nothing was linked. Try "
                      "again in a minute.")
    if r.status_code >= 400:
        return None, ("Your n8n did not accept a new credential (%d). Its "
                      "API key needs permission to create credentials."
                      % r.status_code)
    try:
        cid = (r.json() or {}).get("id")
    except ValueError:
        cid = None
    if not cid:
        return None, "Your n8n made no credential id, so nothing was linked."
    return str(cid), None


async def link(email: str, auth, args: Dict[str, Any]) -> dict:
    """The `link_aiui` tool. See the module docstring."""
    again = bool((args or {}).get("again"))
    old = await automation_keys.n8n_key(email)
    if old and not again:
        return {"ok": True, "made": False,
                "credential": {"id": old["n8n_credential_id"],
                               "name": CREDENTIAL_NAME}}
    try:
        made = await automation_keys.create(
            email, KEY_LABEL, scopes=(automation_keys.SCOPE_TOOLS,))
    except automation_keys.TooManyKeys:
        return _err("You already have the most automation keys allowed. "
                    "Revoke one on the Agents page under Automation, then "
                    "ask again.")
    cid, problem = await _save_in_n8n(auth, made["key"])
    if problem:
        await automation_keys.revoke(email, made["id"])
        return _err(problem)
    await automation_keys.remember_n8n_credential(email, made["id"], cid)
    if old:
        # Workflows already approved keep working on the new key.
        await automation_keys.allow_writes(
            email, made["id"], list(old.get("allowed_writes") or []))
        await automation_keys.revoke(email, old["id"])
    return {"ok": True, "made": True,
            "credential": {"id": cid, "name": CREDENTIAL_NAME}}
