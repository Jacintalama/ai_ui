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


def step_target(node: Any) -> Optional[Tuple[str, str]]:
    """(app, tool) for an AIUI step, or None for any other node.

    The body may be a JSON string, as n8n writes it, or an object, as a
    model often does. An expression body (`={{ ... }}`) cannot be read
    before it runs, so it names nothing and is never approved.
    """
    if not isinstance(node, dict) or node.get("type") != _HTTP_REQUEST:
        return None
    params = node.get("parameters")
    if not isinstance(params, dict) or params.get("url") != RUN_URL:
        return None
    body = params.get("jsonBody")
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


def check_steps(nodes: List[Any]) -> None:
    """Refuse an AIUI step that names no credential. n8n accepts it and
    then answers 401 from us on every single run."""
    for node in nodes or []:
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
