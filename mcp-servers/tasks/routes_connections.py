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
from fastapi.responses import HTMLResponse
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


PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL",
                                 "https://ai-ui.coolestdomain.win")


def _redirect_uri(provider_id: str) -> str:
    """Where the vendor sends the browser back. Must match what was registered
    with them exactly, character for character."""
    return (PUBLIC_BASE_URL.rstrip("/")
            + "/api/tasks/connections/" + provider_id + "/oauth/callback")


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


def _oauth_ready(provider_id: str) -> bool:
    """True only when the vendor supports it AND this deployment registered an
    app. Import is local so a missing module can never break the listing."""
    try:
        import oauth_providers as O
        return O.configured(provider_id)
    except Exception:
        return False


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
        # Whether this deployment can offer click-and-approve. False keeps the
        # paste-a-token form, which is what every provider has today.
        "oauth": _oauth_ready(provider.id),
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


async def _ask_vendor(provider: C.Provider, values: Dict[str, str]) -> tuple:
    """(ok, account_label, error). Never raises, never echoes a credential.

    Shared by connect and test on purpose: "is this credential real" must be
    the same question both times, or a connection can pass one and fail the
    other for no reason a user could understand.
    """
    try:
        req = C.verify_request(provider.id, values)
    except ValueError as e:
        return False, None, str(e)

    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.request(req.method, req.url, headers=req.headers,
                                     params=req.params or None, json=req.body)
    except Exception as e:
        # The exception can carry the URL, which for n8n and Zapier is user
        # supplied and for Trello carries the credential in its query string.
        # Log the type only.
        logger.warning("connections: %s unreachable (%s)", provider.id,
                       type(e).__name__)
        return False, None, ("Could not reach " + provider.label
                             + " just now. Try again in a moment.")

    if r.status_code in (401, 403):
        return False, None, (provider.label + " rejected that credential. It "
                             "may have expired or been revoked. Reconnect it "
                             "to fix this.")
    if r.status_code >= 400:
        # Never r.text: vendors echo the request, credential included.
        logger.warning("connections: %s verify returned %s", provider.id,
                       r.status_code)
        return False, None, (provider.label + " returned an error ("
                             + str(r.status_code) + "). The credential may not "
                             "have the right permissions.")
    try:
        payload = r.json()
    except Exception:
        payload = {}
    return True, C.account_label(provider.id, payload), None


@router.get("/{provider_id}/oauth/start")
async def oauth_start(provider_id: str,
                      user: CurrentUser = Depends(current_user)):
    """Where to send the browser to approve this connection.

    Returns a URL rather than redirecting, so the caller can open it in a popup
    and leave the dialog underneath.
    """
    import oauth_providers as O

    if not C.provider(provider_id):
        raise HTTPException(status_code=404, detail="Unknown app.")
    if not O.configured(provider_id):
        raise HTTPException(
            status_code=503,
            detail="One-click connect is not set up for this app yet.")

    client_id, _ = O.client_credentials(provider_id)
    state = O.STATES.mint(user.email)
    return {"url": O.authorize_url(provider_id, client_id=client_id,
                                   redirect_uri=_redirect_uri(provider_id),
                                   state=state)}


@router.get("/{provider_id}/oauth/callback")
async def oauth_callback(provider_id: str, code: str = "", state: str = "",
                         error: str = ""):
    """Where the vendor sends the browser back.

    Deliberately NOT authenticated by the session. The user this grant belongs
    to is the one named by `state`, minted for them when they started and
    spendable once. Trusting the session instead would let anyone who can make
    a signed-in browser follow this URL attach their own vendor account to
    somebody else's user, silently.
    """
    import oauth_providers as O

    provider = C.provider(provider_id)
    if not provider or not O.supports_oauth(provider_id):
        return _oauth_done(False, "Unknown app.")
    if error:
        return _oauth_done(False, "Cancelled, or " + provider.label
                           + " refused the request.")

    email = O.STATES.consume(state)
    if not email:
        # Expired, replayed or forged. All three get the same answer.
        return _oauth_done(False, "That approval link has expired. Start the "
                                  "connection again.")
    if not code:
        return _oauth_done(False, provider.label + " did not return a code.")

    client_id, client_secret = O.client_credentials(provider_id)
    prov = O.PROVIDERS[provider_id]
    try:
        auth = (client_id, client_secret) if prov.token_auth == "basic" else None
        body = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": _redirect_uri(provider_id)}
        if auth is None:
            body.update({"client_id": client_id,
                         "client_secret": client_secret})
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.post(prov.token_endpoint, json=body, auth=auth)
    except Exception as e:
        logger.warning("oauth: %s token exchange unreachable (%s)",
                       provider_id, type(e).__name__)
        return _oauth_done(False, "Could not reach " + provider.label + ".")

    if r.status_code >= 400:
        # Never r.text: a failed exchange echoes the request, and the request
        # carries the client secret.
        logger.warning("oauth: %s token exchange returned %s",
                       provider_id, r.status_code)
        return _oauth_done(False, provider.label + " rejected the approval.")

    try:
        values, label = O.read_token_response(provider_id, r.json())
    except Exception as e:
        logger.warning("oauth: %s token response unusable (%s)",
                       provider_id, type(e).__name__)
        return _oauth_done(False, provider.label
                           + " did not return a usable token.")

    try:
        await _store_connection(email, provider_id, values, label)
    except Exception as e:
        logger.warning("oauth: %s could not store (%s)", provider_id,
                       type(e).__name__)
        return _oauth_done(False, "Could not save that connection.")

    logger.info("oauth: %s connected %s as %s", email, provider_id, label)
    return _oauth_done(True, "Connected to " + label
                       + ". You can close this window.")


def _oauth_done(ok: bool, message: str) -> HTMLResponse:
    """A tiny page for the popup: tell the opener, then say what happened.

    The message goes in through textContent, never interpolated markup: it can
    carry a vendor-supplied workspace name.
    """
    import json as _json

    def _js(value):
        """JSON safe to sit inside a <script> block.

        json.dumps escapes quotes and backslashes and NOT "<", so a vendor
        workspace called "</script><script>..." would close the block it is
        embedded in and run, on our own origin.
        """
        return (_json.dumps(value)
                .replace("<", chr(92) + "u003c")
                .replace(">", chr(92) + "u003e")
                .replace("&", chr(92) + "u0026"))

    payload = _js({"aiuiOauth": True, "ok": bool(ok)})
    safe = _js(str(message))
    style = ("font-family:-apple-system,Segoe UI,sans-serif;background:#111113;"
             "color:#ededee;display:flex;align-items:center;"
             "justify-content:center;height:100vh;margin:0;text-align:center")
    # Assembled first, then unescaped once. Attaching .replace to the last
    # literal of a concatenation chain only rewrites that literal, which left
    # eight placeholders sitting in the markup.
    page = (
        "<!doctype html><meta charset=@utf-8@><title>Connection</title>"
        "<body style=@" + style + "@>"
        "<div><p id=@m@ style=@font-size:15px@></p></div>"
        "<script>"
        "document.getElementById('m').textContent = " + safe + ";"
        "try { window.opener && window.opener.postMessage(" + payload +
        ", '*'); } catch (e) {}"
        "setTimeout(function () { try { window.close(); } catch (e) {} }, 2500);"
        "</script></body>"
    )
    return HTMLResponse(page.replace("@", chr(34)))


async def _store_connection(email: str, provider_id: str,
                            values, label: str) -> None:
    """Upsert an encrypted credential. Shared by the paste flow and by OAuth."""
    blob = crypto_utils.encrypt(json.dumps(values))
    conn = await _connect()
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
            email, provider_id, blob, label)
    finally:
        await conn.close()


@router.post("/{provider_id}/test")
async def test_connection(provider_id: str,
                          user: CurrentUser = Depends(current_user)):
    """Ask the vendor, right now, whether the stored credential still works.

    Connecting proved it once and nothing proved it again, so a revoked token
    left the card reading "Connected" until some tool call failed in a chat,
    which is the worst place to discover it.

    A failure never deletes the stored credential. A vendor having a bad minute
    must not throw away something the user pasted; they decide whether to
    replace it.
    """
    provider = C.provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Unknown app.")

    values = await secrets_for(user.email, provider_id)
    if not values:
        return {"provider": provider_id, "ok": False,
                "error": "Not connected yet. Add a credential first."}

    ok, label, error = await _ask_vendor(provider, values)
    return {"provider": provider_id, "ok": ok,
            "account_label": label, "error": error}


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

    ok, label, error = await _ask_vendor(provider, values)
    if not ok:
        # 502 when the vendor could not be reached, 400 when it answered and
        # said no. Telling someone their token is wrong because ClickUp was
        # down sends them off to regenerate a perfectly good credential.
        unreachable = error and error.startswith("Could not reach")
        raise HTTPException(status_code=502 if unreachable else 400,
                            detail=error)

    try:
        await _store_connection(user.email, provider_id, values, label)
    except Exception as e:
        logger.warning("connections: write failed: %s", e)
        raise HTTPException(status_code=503, detail="Connections unavailable.")

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
