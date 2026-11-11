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
import asyncio
import json
import logging
import os
import time
import urllib.parse
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import connections as C
import crypto_utils
import oauth_refresh as F
import trello_connect as T
from auth import current_user, CurrentUser

logger = logging.getLogger("tasks.connections")

router = APIRouter(prefix="/connections")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

#: A vendor that has not answered in this long is treated as unreachable. Long
#: enough for a cold API, short enough that a wedged host does not hold the
#: user's browser open.
VERIFY_TIMEOUT_SEC = 12

#: A renewal happens while somebody waits for a tool call, so it gets less
#: patience than a connect does. Failing it is cheap: the token in hand is
#: still good for another SKEW_SEC and the call goes out on that.
REFRESH_TIMEOUT_SEC = 10


def _now() -> float:
    """Seam, so a test can say what time it is without freezing the clock for
    everything else in the process."""
    return time.time()


#: One renewal at a time per credential, keyed by whose it is.
#:
#: Two tool calls arriving together would otherwise both renew, and a vendor
#: that ROTATES its refresh token retires the first answer when it issues the
#: second, so the loser of the race stores a refresh token that no longer
#: works. In process only, which is enough: there is one tasks container, and
#: the worst a second one could do is waste a renewal.
_REFRESH_LOCKS: Dict[tuple, asyncio.Lock] = {}


def _refresh_lock(email: str, provider_id: str) -> asyncio.Lock:
    key = (email, provider_id)
    lock = _REFRESH_LOCKS.get(key)
    if lock is None:
        lock = _REFRESH_LOCKS[key] = asyncio.Lock()
    return lock


async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL",
                                 "https://ai-ui.coolestdomain.win")


#: The public shape of a callback, and the only URL of ours a person
#: connecting ever sees: it sits in the address bar while they approve, and
#: it is what gets registered with the vendor.
#:
#: /connect/<app>/callback rather than /api/tasks/connections/<app>/oauth/
#: callback (2026-11-03). The old one is not wrong and nothing about it
#: restricted anybody, but "api/tasks" is the name of a container and a
#: database schema, and a person deciding whether to trust us with their
#: Trello should not be reading our plumbing to do it.
#:
#: The old path still serves the same handler and always will: tokens were
#: issued against it, and a registered callback that stops answering is a
#: connect that fails with nothing to explain it.
PUBLIC_CALLBACK = "/connect/{provider}/callback"


def _redirect_uri(provider_id: str) -> str:
    """Where the vendor sends the browser back. Must match what was registered
    with them exactly, character for character."""
    return (PUBLIC_BASE_URL.rstrip("/")
            + PUBLIC_CALLBACK.format(provider=provider_id))


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
    """True only when the vendor can be connected in one click AND this
    deployment registered an app for it.

    Named `oauth` on the wire because that is what the card has called it
    since it existed, and renaming a field the page reads buys nothing. It
    means "offer the button rather than the paste form", which for Trello is
    true without any OAuth being involved: it has none (2026-10-30).

    Import is local so a missing module can never break the listing.
    """
    try:
        if provider_id == T.PROVIDER_ID:
            return T.configured()
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

    # Trello is one click but not OAuth 2.0: it has no code exchange, only
    # its own 1/authorize flow. Same button, same popup, different road.
    if provider_id == T.PROVIDER_ID:
        if not T.configured():
            raise HTTPException(
                status_code=503,
                detail="One-click connect is not set up for this app yet.")
        state = O.STATES.mint(user.email)
        back = (_redirect_uri(provider_id) + "?state="
                + urllib.parse.quote(state, safe=""))
        return {"url": T.authorize_url(back)}

    if not O.configured(provider_id):
        raise HTTPException(
            status_code=503,
            detail="One-click connect is not set up for this app yet.")

    client_id, _ = O.client_credentials(provider_id)

    # A PKCE vendor needs a one-time secret minted NOW and kept beside the
    # state, because the authorize URL and the exchange are two separate
    # requests and the verifier has to survive between them without ever
    # travelling through the browser. Empty for every other vendor, and
    # `authorize_url` ignores it for them rather than appending an unknown
    # parameter to somebody else's consent screen.
    verifier = O.new_verifier() if O.PROVIDERS[provider_id].pkce else ""
    state = O.STATES.mint(user.email, verifier=verifier)

    # A FIRST GitHub connect goes to the install page, where the person
    # picks their repositories and comes straight back (2026-11-04, Ralph:
    # "use the default one please like in the vercel").
    #
    # GitHub splits this in two. Authorising says who you are; installing
    # grants repository access. Our app is registered with "request user
    # authorization during installation", and GitHub's docs are explicit
    # that such an app CANNOT have a separate setup URL: the install
    # redirects to the callback as part of the authorization flow. So the
    # install page gives both in one approval, which is the whole point.
    #
    # Only for somebody with nothing stored. For an app already installed,
    # that same URL shows Configure instead, finishes on GitHub and never
    # redirects back with a code. That was measured in the log as seven
    # oauth/start calls and zero callbacks when this route pointed every
    # connect at the install page, so the two cases genuinely differ and
    # the ordinary authorize URL is what a reconnect needs.
    if provider_id == "github" and not await _has_connection(user.email,
                                                             provider_id):
        install = O.install_url(state)
        if install:
            return {"url": install}

    return {"url": O.authorize_url(provider_id, client_id=client_id,
                                   redirect_uri=_redirect_uri(provider_id),
                                   state=state, verifier=verifier)}


async def _has_connection(email: str, provider_id: str) -> bool:
    """Whether this person already has this app connected.

    Existence only, so nothing is decrypted to answer a question about
    which page to open.

    Fails CLOSED, to False, on purpose. Unreachable means "treat them as
    new", which sends them to the install page: that page works for a
    first install and, for somebody who turns out to be installed already,
    shows them their repository selection. The other way round, a blip
    would send a first-timer to authorize and leave them connected to
    nothing.
    """
    try:
        conn = await _connect()
    except Exception:                                       # noqa: BLE001
        return False
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM tasks.user_connections "
            "WHERE email = $1 AND provider = $2", email, provider_id)
        return row is not None
    except Exception:                                       # noqa: BLE001
        logger.warning("could not check for an existing connection",
                       exc_info=True)
        return False
    finally:
        try:
            await conn.close()
        except Exception:                                   # noqa: BLE001
            pass


#: The clean public path, mounted at the root rather than under this
#: router's /connections prefix, because the point of it is the shape.
#: One handler, two paths: a second implementation would be a second thing
#: to keep correct, and this one decides who a grant belongs to.
public_router = APIRouter()


@public_router.get("/connect/{provider_id}/callback")
async def oauth_callback_public(provider_id: str, code: str = "",
                                state: str = "", error: str = ""):
    """The callback people actually see. Delegates, never duplicates."""
    return await oauth_callback(provider_id, code=code, state=state,
                                error=error)


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

    # Trello lands here with the token after the '#', which the browser keeps
    # to itself and never sends. So this serves a page that reads it there
    # and posts it to /oauth/token below. Nothing is decided here.
    if provider and provider_id == T.PROVIDER_ID:
        if error:
            return _oauth_done(False, "Cancelled, or Trello refused the "
                                      "request.")
        return _trello_catch_fragment(state)

    if not provider or not O.supports_oauth(provider_id):
        return _oauth_done(False, "Unknown app.")
    if error:
        return _oauth_done(False, "Cancelled, or " + provider.label
                           + " refused the request.")

    started = O.STATES.take(state)
    if not started:
        # Expired, replayed or forged. All three get the same answer.
        return _oauth_done(False, "That approval link has expired. Start the "
                                  "connection again.")
    email = started.email
    if not code:
        return _oauth_done(False, provider.label + " did not return a code.")

    client_id, client_secret = O.client_credentials(provider_id)
    prov = O.PROVIDERS[provider_id]

    # Checked BEFORE anything is sent. A code can be spent once, so
    # exchanging one we cannot prove ownership of would burn it and earn an
    # `invalid_grant` the person has no way to act on.
    if prov.pkce and not started.verifier:
        logger.warning("oauth: %s callback had no PKCE verifier", provider_id)
        return _oauth_done(False, "That approval link has expired. Start the "
                                  "connection again.")

    try:
        auth = (client_id, client_secret) if prov.token_auth == "basic" else None
        body = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": _redirect_uri(provider_id)}
        if O.client_in_body(provider_id):
            body.update({"client_id": client_id,
                         "client_secret": client_secret})
        if prov.pkce:
            # The half that never went through the browser, which is what
            # makes a stolen code worthless.
            body["code_verifier"] = started.verifier
        # GitHub answers in `key=value&key=value` unless asked for JSON, and
        # every provider here is read with r.json(). Harmless to the others.
        headers = {"Accept": "application/json"}
        # Empty unless the vendor documents base64URL, which only Airtable
        # does. Notion's standard Basic still rides on httpx's `auth`.
        headers.update(O.basic_header(provider_id))
        # HubSpot and GitHub want a form; Notion and ClickUp document JSON.
        sent = ({"data": body} if prov.token_body == "form"
                else {"json": body})
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.post(prov.token_endpoint, auth=auth,
                                  headers=headers, **sent)
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

    # GitHub and ClickUp hand back a token and nothing else, so the account
    # has to be asked for by name. Doing it here also proves the token works
    # before any card claims a connection, which is the same question the
    # paste form and the Test button ask, through the same function.
    if not label:
        ok, vendor_label, why = await _ask_vendor(provider, values)
        if not ok:
            logger.warning("oauth: %s approved but the token did not work "
                           "(%s)", provider_id, why)
            return _oauth_done(False, provider.label + " approved the "
                               "connection, but the token it gave back did "
                               "not work.")
        label = vendor_label or provider.label

    # A GitHub App that is authorised but not INSTALLED anywhere reaches no
    # repositories at all, while /user answers perfectly and the card says
    # Connected as the right person. Measured on the first real connect
    # (2026-11-03): login right, installations 0, repositories 0.
    #
    # Refused rather than stored, because the alternative is a connection
    # that passes every check we make and does nothing, which costs an
    # afternoon to tell apart from a broken tool.
    if provider_id == "github" and O.GITHUB_APP_SLUG:
        reach = await _github_installations(values)
        if reach == 0:
            # Not a refusal with nowhere to go. Authorising and installing
            # are two acts, this is the second one, and the person has no
            # way to find that page on their own.
            logger.warning("oauth: github authorised with no installation")
            return _oauth_done(
                False, "Authorised. One more step: IO needs to be installed "
                       "on the account that holds your repositories before "
                       "it can see any code.",
                link=O.install_url(), link_text="Install IO on GitHub")

    try:
        await _store_connection(email, provider_id, values, label)
    except Exception as e:
        logger.warning("oauth: %s could not store (%s)", provider_id,
                       type(e).__name__)
        return _oauth_done(False, "Could not save that connection.")

    logger.info("oauth: %s connected %s as %s", email, provider_id, label)

    if provider_id == "github":
        # A GitHub connect ALWAYS ends with a way to choose repositories,
        # even when one is already installed (2026-11-04, Ralph: "it didnt
        # choose my repo or any of my option it just connected").
        #
        # The link used to appear only for somebody with NO installation.
        # That is the one case where it is unmissable and the only case it
        # was offered: anybody who had installed it once was shown
        # "Connected" and no way to change which repositories it covers,
        # which is the thing they came to do. GitHub's own page says
        # Configure rather than Install in that state and edits the
        # selection, so it is the right destination either way.
        return _oauth_done(
            True, _github_said(label, await _github_repos(values)),
            link=O.install_url(), link_text="Choose which repositories")

    return _oauth_done(True, "Connected to " + label
                       + ". You can close this window.")


def _oauth_done(ok: bool, message: str, link: str = "",
                link_text: str = "") -> HTMLResponse:
    """A tiny page for the popup: tell the opener, then say what happened.

    The message goes in through textContent, never interpolated markup: it can
    carry a vendor-supplied workspace name.

    `link` is a way forward when there is one, and a page carrying one does
    NOT close itself: a popup that vanishes before anybody can read, let
    alone click, is the same as no link at all.
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
    href = _js(str(link or ""))
    label = _js(str(link_text or "Continue"))
    style = ("font-family:-apple-system,Segoe UI,sans-serif;background:#111113;"
             "color:#ededee;display:flex;align-items:center;"
             "justify-content:center;height:100vh;margin:0;text-align:center")
    # Assembled first, then unescaped once. Attaching .replace to the last
    # literal of a concatenation chain only rewrites that literal, which left
    # eight placeholders sitting in the markup.
    page = (
        "<!doctype html><meta charset=@utf-8@><title>Connection</title>"
        "<body style=@" + style + "@>"
        "<div><p id=@m@ style=@font-size:15px@></p>"
        "<p><a id=@a@ hidden style=@color:#8ab4f8;font-size:15px@></a></p></div>"
        "<script>"
        "document.getElementById('m').textContent = " + safe + ";"
        "var _h = " + href + ", _a = document.getElementById('a');"
        "if (_h) { _a.href = _h; _a.textContent = " + label + "; _a.hidden = false; }"
        "try { window.opener && window.opener.postMessage(" + payload +
        ", '*'); } catch (e) {}"
        "if (!_h) { setTimeout(function () "
        "{ try { window.close(); } catch (e) {} }, 2500); }"
        "</script></body>"
    )
    return HTMLResponse(page.replace("@", chr(34)))


def _trello_catch_fragment(state: str) -> HTMLResponse:
    """The page Trello returns to, whose only job is to hand the token back.

    A URL fragment is never sent to a server, so this is the only way to
    receive a token from Trello's 1/authorize flow. The page reads
    location.hash, posts it to /oauth/token, and then shows whatever that
    says.

    The fragment is cleared from the address bar immediately, so the token
    does not sit in history or get copied out of the bar by somebody sharing
    a link.
    """
    import json as _json

    def _js(value):
        return (_json.dumps(value)
                .replace("<", chr(92) + "u003c")
                .replace(">", chr(92) + "u003e")
                .replace("&", chr(92) + "u0026"))

    style = ("font-family:-apple-system,Segoe UI,sans-serif;background:#111113;"
             "color:#ededee;display:flex;align-items:center;"
             "justify-content:center;height:100vh;margin:0;text-align:center")
    body = (
        "<!doctype html><meta charset=utf-8>"
        "<title>Connecting Trello</title>"
        "<body style=" + _js(style) + "><div id=m>Connecting Trello...</div>"
        "<script>(function(){"
        "var state=" + _js(str(state or "")) + ";"
        "var hash=location.hash||'';"
        # Out of the address bar before anything else, token included.
        "try{history.replaceState(null,'',location.pathname);}catch(e){}"
        "var m=document.getElementById('m');"
        "function done(ok,text){"
        "  m.textContent=text;"
        "  try{if(window.opener)window.opener.postMessage("
        "    {aiuiOauth:true,ok:!!ok},location.origin);}catch(e){}"
        "  if(ok)setTimeout(function(){try{window.close();}catch(e){}},900);"
        "}"
        "fetch('/api/tasks/connections/trello/oauth/token',{method:'POST',"
        "  headers:{'Content-Type':'application/json'},"
        "  body:JSON.stringify({state:state,fragment:hash})})"
        " .then(function(r){return r.json().catch(function(){return {};});})"
        " .then(function(d){done(d&&d.ok,(d&&d.message)||'Could not connect "
        "Trello.');})"
        " .catch(function(){done(false,'Could not reach the server.');});"
        "})();</script></body>")
    return HTMLResponse(body)


async def _github_installations(values: dict) -> int:
    """How many accounts this GitHub App is installed on, for this person.

    -1 when the question could not be asked, which is deliberately NOT zero:
    a network blip must not look like "install it", and must not throw away
    a grant somebody just approved.
    """
    try:
        auth = C.vendor_auth("github", values)
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.get(auth.base_url + "/user/installations",
                                 headers=auth.headers, params=auth.params)
        if r.status_code != 200:
            return -1
        return int((r.json() or {}).get("total_count") or 0)
    except Exception:                                       # noqa: BLE001
        logger.warning("github: could not count installations", exc_info=True)
        return -1


#: How many repository names the done page will read out. Somebody with
#: forty does not need forty on a popup; they need to know it worked and
#: where to change it.
REPOS_NAMED = 4

#: Installations to ask about. Almost everybody has one. The cap is here so
#: a person who belongs to many organisations cannot turn one connect into
#: twenty vendor calls.
MAX_INSTALLATIONS_ASKED = 3


async def _github_repos(values: dict) -> Optional[List[str]]:
    """Which repositories IO can actually see, for this person.

    None when the question could not be asked, which is NOT the empty list:
    "we could not look" and "it has been given none" need different words,
    and only one of them is alarming.

    Authorisation says who you are; INSTALLATION is what grants repository
    access, and the two are chosen on different pages. So a token can be
    perfectly valid and reach nothing at all.
    """
    try:
        auth = C.vendor_auth("github", values)
        names: List[str] = []
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SEC) as client:
            r = await client.get(auth.base_url + "/user/installations",
                                 headers=auth.headers, params=auth.params)
            if r.status_code != 200:
                return None
            installs = ((r.json() or {}).get("installations")
                        or [])[:MAX_INSTALLATIONS_ASKED]
            for inst in installs:
                iid = (inst or {}).get("id")
                if iid is None:
                    continue
                rr = await client.get(
                    auth.base_url + "/user/installations/%s/repositories" % iid,
                    headers=auth.headers,
                    params=dict(auth.params or {}, per_page="100"))
                if rr.status_code != 200:
                    continue
                for repo in ((rr.json() or {}).get("repositories") or []):
                    full = str((repo or {}).get("full_name") or "").strip()
                    if full and full not in names:
                        names.append(full)
        return names
    except Exception:                                       # noqa: BLE001
        logger.warning("github: could not list repositories", exc_info=True)
        return None


def _github_said(label: str, repos: Optional[List[str]]) -> str:
    """What the done page says after a GitHub connect.

    Pure, so every wording below is testable without a vendor.
    """
    head = "Connected to " + str(label) + "."
    if repos is None:
        # We could not look. Saying nothing about repositories is better
        # than guessing, and the link below still leads to the answer.
        return head
    if not repos:
        return (head + " It cannot see any repositories yet, because none "
                "have been given to it.")
    shown = ", ".join(repos[:REPOS_NAMED])
    more = len(repos) - REPOS_NAMED
    n = "1 repository" if len(repos) == 1 else "%d repositories" % len(repos)
    return (head + " It can see " + n + ": " + shown
            + (" and %d more." % more if more > 0 else "."))


class TrelloTokenBody(BaseModel):
    state: str = ""
    #: Whatever was after the '#'. Parsed on this side so the page stays as
    #: small and dumb as possible.
    fragment: str = ""


@router.post("/trello/oauth/token")
async def trello_oauth_token(body: TrelloTokenBody) -> dict:
    """Finish a Trello one-click connect.

    Deliberately NOT authenticated by the session, for the same reason the
    OAuth 2.0 callback is not: the person this grant belongs to is the one
    named by `state`, minted for them when they started and spendable once.
    Trusting the session instead would let anyone who can make a signed-in
    browser follow this URL attach their own Trello to somebody else's
    account.
    """
    import oauth_providers as O

    email = O.STATES.consume(body.state)
    if not email:
        # Expired, replayed or forged. All three get the same answer.
        return {"ok": False, "message": "That approval expired. Start the "
                                        "connection again."}
    token = T.token_from_fragment(body.fragment)
    if not T.looks_like_token(token):
        # Never echo what ARRIVED: it is either a credential or somebody
        # else's error page, and neither belongs in a response or a log.
        # Trello's own `error` is a different thing, written to be read, and
        # it is the only account anyone gets of what went wrong.
        why = T.error_from_fragment(body.fragment)
        logger.warning("trello: no usable token in the fragment (%s) [%s]",
                       why or "and no reason given",
                       T.describe_fragment(body.fragment))
        return {"ok": False,
                "message": ("Trello refused: " + why) if why
                else "Trello did not return a token."}

    values = T.stored_values(token)
    ok, label, why = await _ask_vendor(C.provider(T.PROVIDER_ID), values)
    if not ok:
        return {"ok": False,
                "message": why or "Trello would not accept that token."}
    try:
        await _store_connection(email, T.PROVIDER_ID, values,
                                label or "Trello")
    except Exception as e:                                  # noqa: BLE001
        logger.warning("trello: could not store (%s)", type(e).__name__)
        return {"ok": False, "message": "Could not save that connection."}
    return {"ok": True, "message": "Trello connected."}


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


async def _stored_credential(email: str, provider_id: str) -> Dict[str, str]:
    """What is in the row, decrypted, with nothing decided about it."""
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


async def _replace_secrets(email: str, provider_id: str,
                           values: Dict[str, str]) -> None:
    """Write a renewed credential, and nothing else.

    Deliberately NOT `_store_connection`, which also writes `account_label`
    and moves `updated_at`. The card shows `updated_at` as when the person
    connected and the label as which account it is; a renewal is neither of
    those things and must not read as one.
    """
    blob = crypto_utils.encrypt(json.dumps(values))
    conn = await _connect()
    try:
        await conn.execute(
            "UPDATE tasks.user_connections SET secrets_encrypted = $1 "
            "WHERE email = $2 AND provider = $3", blob, email, provider_id)
    finally:
        await conn.close()


async def _renewed(email: str, provider_id: str,
                   values: Dict[str, str]) -> Dict[str, str]:
    """Ask the vendor for a new access token, store it, and hand it back.

    EVERY failure path returns the credential we already have, never {}.
    Returning nothing would make every tool say "You have not connected your
    X account yet", which is false and sends somebody off to connect an
    account they already connected. Handing the old token to the vendor gets
    a 401 instead, and `mytools._refusal` already turns that into "Your X
    credential was rejected. It may have expired. Reconnect it from
    Connections." The right words exist; a renewal must not talk over them.

    It also means a vendor having a bad minute costs nothing, because the
    renewal runs SKEW_SEC early and the token in hand still works.
    """
    try:
        post = F.refresh_post(provider_id, values)
    except ValueError:
        return values

    try:
        async with httpx.AsyncClient(timeout=REFRESH_TIMEOUT_SEC) as client:
            resp = await client.post(post["url"],
                                     headers=post.get("headers"),
                                     json=post.get("json"),
                                     data=post.get("data"),
                                     auth=post.get("auth"))
    except Exception as e:
        logger.warning("connections: could not reach %s to renew a token (%s)",
                       provider_id, type(e).__name__)
        return values

    if resp.status_code >= 400:
        # Never the body: a token endpoint's error echoes what was sent to
        # it, and what was sent to it is a credential.
        logger.warning("connections: %s refused to renew a token (HTTP %s)",
                       provider_id, resp.status_code)
        return values

    try:
        fresh = F.after_refresh(values, resp.json(), now=_now())
    except Exception as e:
        logger.warning("connections: %s answered a renewal with no token (%s)",
                       provider_id, type(e).__name__)
        return values

    try:
        await _replace_secrets(email, provider_id, fresh)
    except Exception as e:
        # Usable for this call even though the next one will renew again.
        logger.warning("connections: renewed %s but could not store it (%s)",
                       provider_id, type(e).__name__)
        return fresh

    logger.info("connections: renewed a %s token", provider_id)
    return fresh


async def secrets_for(email: str, provider_id: str) -> Dict[str, str]:
    """The user's decrypted credential, for the code that will eventually call
    the vendor on their behalf. Returns {} when they have not connected.

    Renews it first when it is about to expire, because this is the one place
    a stored credential is decrypted: every per-user tool call, every
    automation and the Trello poller come through here, and none of them has
    to know. A credential with no expiry, which is every one stored today, is
    handed straight back and asks no vendor anything.

    Not exposed as a route, and never will be. The only reason to decrypt is
    to make a request as that user.
    """
    values = await _stored_credential(email, provider_id)
    if not values:
        return {}
    if not (F.expired(values, now=_now())
            and F.refreshable(provider_id, values)):
        return values

    async with _refresh_lock(email, provider_id):
        # Read again under the lock. Whoever got here first has renewed and
        # written by now, and asking the vendor a second time would retire
        # the token they just stored.
        values = await _stored_credential(email, provider_id) or values
        if not (F.expired(values, now=_now())
                and F.refreshable(provider_id, values)):
            return values
        return await _renewed(email, provider_id, values)
