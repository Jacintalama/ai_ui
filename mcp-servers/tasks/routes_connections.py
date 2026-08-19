"""Connect your own third-party account: the HTTP and storage half.

The rules about which providers exist, what each needs, and how a credential is
checked live in connections.py and are not restated here. This file owns three
things: calling the vendor, encrypting what comes back, and never letting a
secret out again.

Connect is deliberately slow-ish. It makes a real request to ClickUp or GitHub
or Notion before it stores anything, so a card that says Connected means that
vendor confirmed the credential and named the account. The alternative, storing
whatever was pasted and finding out at first use, produces a UI that lies.
"""
import json
import logging
import os
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import connections as C
import crypto_utils
from auth import current_user, CurrentUser

logger = logging.getLogger("tasks.connections")

router = APIRouter(prefix="/connections")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

#: A vendor that has not answered in this long is treated as unreachable. Long
#: enough for a cold API, short enough that a wedged host does not hold the
#: user's browser open.
VERIFY_TIMEOUT_SEC = 12


async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


class ConnectBody(BaseModel):
    #: field name -> value, matching connections.required_fields(provider).
    values: Dict[str, str] = {}


async def _stored(conn, email: str) -> Dict[str, dict]:
    rows = await conn.fetch(
        "SELECT provider, account_label, updated_at FROM tasks.user_connections "
        "WHERE email = $1", email)
    return {r["provider"]: {"account_label": r["account_label"],
                            "updated_at": r["updated_at"].isoformat()}
            for r in rows}


def _describe(provider: C.Provider, stored: dict) -> dict:
    """Everything the card needs, and nothing that could be a secret."""
    hit = stored.get(provider.id)
    return {
        "provider": provider.id,
        "label": provider.label,
        "connected": bool(hit),
        "account_label": (hit or {}).get("account_label"),
        "connected_at": (hit or {}).get("updated_at"),
        "where": provider.where,
        "fields": [{"name": f.name, "label": f.label, "secret": f.secret,
                    "placeholder": f.placeholder} for f in provider.fields],
    }


@router.get("")
async def list_connections(user: CurrentUser = Depends(current_user)):
    """Every provider the user can connect, and whether they have.

    Fails open to "nothing connected" rather than erroring: the dialog listing
    the apps is more useful than an error, and a wrong "connected" is the only
    answer here that would actually mislead.
    """
    stored = {}
    try:
        conn = await _connect()
        try:
            stored = await _stored(conn, user.email)
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("connections: read failed: %s", e)
    return {"connections": [_describe(p, stored)
                            for p in C.PROVIDERS.values()]}


@router.post("/{provider_id}")
async def connect(provider_id: str, body: ConnectBody,
                  user: CurrentUser = Depends(current_user)):
    provider = C.provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Unknown app.")

    values = {k: v for k, v in (body.values or {}).items()
              if k in C.required_fields(provider_id)}

    missing = C.missing_fields(provider_id, values)
    if missing:
        labels = [f.label for f in provider.fields if f.name in missing]
        raise HTTPException(status_code=400,
                            detail="Still needed: " + ", ".join(labels))

    try:
        req = C.verify_request(provider_id, values)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.get(req.url, headers=req.headers,
                                 params=req.params or None)
    except Exception as e:
        # The exception can carry the URL, which for n8n is user-supplied, and
        # for Trello carries the credential in the query string. Log the type
        # only.
        logger.warning("connections: %s unreachable (%s)",
                       provider_id, type(e).__name__)
        raise HTTPException(
            status_code=502,
            detail="Could not reach " + provider.label + " to check that.")

    if r.status_code in (401, 403):
        raise HTTPException(
            status_code=400,
            detail=provider.label + " rejected that credential. Check you "
                   "copied all of it, and that it has not expired.")
    if r.status_code >= 400:
        logger.warning("connections: %s verify returned %s for %s",
                       provider_id, r.status_code,
                       C.redact(provider_id, values))
        raise HTTPException(
            status_code=400,
            detail=provider.label + " returned an error (" +
                   str(r.status_code) + "). The credential may not have the "
                   "right permissions.")

    try:
        payload = r.json()
    except Exception:
        payload = {}
    label = C.account_label(provider_id, payload)

    blob = crypto_utils.encrypt(json.dumps(values))
    try:
        conn = await _connect()
    except Exception as e:
        logger.warning("connections: connect failed: %s", e)
        raise HTTPException(status_code=503, detail="Connections unavailable.")
    try:
        await conn.execute(
            """
            INSERT INTO tasks.user_connections
                (email, provider, secrets_encrypted, account_label, updated_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (email, provider) DO UPDATE
                SET secrets_encrypted = EXCLUDED.secrets_encrypted,
                    account_label = EXCLUDED.account_label,
                    updated_at = now()
            """,
            user.email, provider_id, blob, label)
    except Exception as e:
        logger.warning("connections: write failed: %s", e)
        raise HTTPException(status_code=503, detail="Connections unavailable.")
    finally:
        await conn.close()

    logger.info("connections: %s connected %s as %s",
                user.email, provider_id, label)
    return {"provider": provider_id, "connected": True, "account_label": label}


@router.delete("/{provider_id}")
async def disconnect(provider_id: str,
                     user: CurrentUser = Depends(current_user)):
    if not C.provider(provider_id):
        raise HTTPException(status_code=404, detail="Unknown app.")
    try:
        conn = await _connect()
    except Exception as e:
        logger.warning("connections: connect failed: %s", e)
        raise HTTPException(status_code=503, detail="Connections unavailable.")
    try:
        await conn.execute(
            "DELETE FROM tasks.user_connections "
            "WHERE email = $1 AND provider = $2", user.email, provider_id)
    finally:
        await conn.close()
    return {"provider": provider_id, "connected": False}


async def secrets_for(email: str, provider_id: str) -> Dict[str, str]:
    """The user's decrypted credential, for the code that will eventually call
    the vendor on their behalf. Returns {} when they have not connected.

    Not exposed as a route, and never will be. The only reason to decrypt is to
    make a request as that user.
    """
    try:
        conn = await _connect()
    except Exception:
        return {}
    try:
        row = await conn.fetchrow(
            "SELECT secrets_encrypted FROM tasks.user_connections "
            "WHERE email = $1 AND provider = $2", email, provider_id)
    except Exception:
        return {}
    finally:
        await conn.close()
    if not row:
        return {}
    try:
        return json.loads(crypto_utils.decrypt(row["secrets_encrypted"]))
    except Exception as e:
        logger.warning("connections: could not decrypt %s for a user (%s)",
                       provider_id, type(e).__name__)
        return {}
