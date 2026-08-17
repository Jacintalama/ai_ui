"""Multi-platform gateway state, and the user-token mint.

webhook-handler has no database driver and no DATABASE_URL, so every piece of
gateway state is reached through this module over HTTP.

Two routers, deliberately separate:

  router       prefix /gateway       X-Internal-Secret. Mounted BARE only, so
                                     it is reachable at http://tasks:8210 from
                                     inside the docker network and from nowhere
                                     else. Do not mount it under /tasks.
  page_router  prefix /tasks/gateway X-User-Email, injected by api-gateway from
                                     the browser's Open WebUI session cookie.

Never log a pairing code and never log a minted token.
"""
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

import discord_api
import gateway_bots as gbots
import gateway_pairing as gp
import nostr_nip19
import nostr_schnorr
import slack_api
import telegram_api
from db import session
from models import GatewayBot, GatewayLink, GatewayPairingCode, GatewaySession
from owui_token import mint_owui_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway")

# Sessions idle longer than this are pruned on write. The Open WebUI chat they
# point at is never deleted: it is the user's data and lives in their sidebar.
SESSION_RETENTION_DAYS = 30

# One token covers every Open WebUI call in a turn, not one call, so it has to
# outlive the slowest turn rather than the slowest request. A voice memo can
# spend a minute in CPU transcription before the model is even asked. COUPLED to
# OWUIUserClient's timeout in webhook-handler/gateway/owui.py, which must stay
# comfortably below this: a call that outlives its own credential succeeds and
# then the write after it gets a 401, silently costing the user that turn in
# their sidebar. Still per-request and still short-lived.
GATEWAY_TOKEN_TTL_SECONDS = 300

# Expired and redeemed codes are swept on the write path. Nothing else prunes
# this table, and resolve is reachable from an unauthenticated public route, so
# without this a caller could grow it without bound.
PAIRING_CODE_RETENTION_HOURS = 24


def _require_internal(secret: str) -> None:
    expected = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="invalid internal secret")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResolveIn(BaseModel):
    platform: str = Field(min_length=1)
    platform_user_id: str = Field(min_length=1)
    platform_user_name: str = ""


class SessionIn(BaseModel):
    platform: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    owui_chat_id: str = Field(min_length=1)
    owui_user_id: str = Field(min_length=1)


@router.post("/resolve")
async def resolve(body: ResolveIn,
                  x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Who is this platform user, and if we do not know, how do they tell us?

    Linked   -> {linked: true, email, owui_user_id, owui_token}
    Unlinked -> {linked: false, code, expires_at}

    A repeat call while a code is still live reuses the same ROW rather than
    inserting another, so a user only ever has one live code. The code VALUE
    is re-minted on every call though, because only the hash is stored, so the
    original value can never be recovered to return again. Re-minting also
    invalidates whatever code was issued before, which is fine: the newest
    message a bot sends always carries the working one.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        link = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == body.platform,
                GatewayLink.platform_user_id == body.platform_user_id,
            )
        )).scalar_one_or_none()

        if link:
            return {
                "linked": True,
                "email": link.email,
                "owui_user_id": link.owui_user_id,
                "owui_token": mint_owui_token(
                    link.owui_user_id, ttl_seconds=GATEWAY_TOKEN_TTL_SECONDS),
            }

        now = _now()
        await s.execute(delete(GatewayPairingCode).where(
            GatewayPairingCode.expires_at
            < now - timedelta(hours=PAIRING_CODE_RETENTION_HOURS)))

        live = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.platform == body.platform,
                GatewayPairingCode.platform_user_id == body.platform_user_id,
                GatewayPairingCode.redeemed_at.is_(None),
                GatewayPairingCode.expires_at > now,
            ).order_by(GatewayPairingCode.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if live:
            # The code itself is not recoverable from the hash, so a resend has
            # to re-mint. Reuse the ROW and overwrite its hash, which keeps the
            # one-live-code-per-user property intact.
            code = gp.generate_code()
            live.code_hash = gp.hash_code(code)
            live.expires_at = now + timedelta(seconds=gp.CODE_TTL_SECONDS)
            live.platform_user_name = body.platform_user_name or live.platform_user_name
            expires_at = live.expires_at
            await s.commit()
            return {"linked": False, "code": code,
                    "expires_at": expires_at.isoformat()}

        code = gp.generate_code()
        row = GatewayPairingCode(
            code_hash=gp.hash_code(code),
            platform=body.platform,
            platform_user_id=body.platform_user_id,
            platform_user_name=body.platform_user_name or None,
            expires_at=now + timedelta(seconds=gp.CODE_TTL_SECONDS),
        )
        s.add(row)
        await s.commit()
        log.info("gateway: issued a pairing code for %s user %s",
                 body.platform, body.platform_user_id)   # never the code
        return {"linked": False, "code": code,
                "expires_at": row.expires_at.isoformat()}


@router.get("/session")
async def get_session(platform: str, chat_id: str,
                      x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == platform,
                GatewaySession.chat_id == chat_id,
            )
        )).scalar_one_or_none()
    if not row:
        return {"owui_chat_id": None}
    return {"owui_chat_id": row.owui_chat_id, "owui_user_id": row.owui_user_id}


@router.put("/session")
async def put_session(body: SessionIn,
                      x_internal_secret: str = Header(default="")) -> dict[str, str]:
    """Upsert the conversation -> Open WebUI chat mapping, and prune old rows."""
    _require_internal(x_internal_secret)
    now = _now()
    async with session() as s:
        row = (await s.execute(
            select(GatewaySession).where(
                GatewaySession.platform == body.platform,
                GatewaySession.chat_id == body.chat_id,
            )
        )).scalar_one_or_none()
        if row:
            row.owui_chat_id = body.owui_chat_id
            row.owui_user_id = body.owui_user_id
            row.updated_at = now
        else:
            s.add(GatewaySession(
                platform=body.platform,
                chat_id=body.chat_id,
                owui_chat_id=body.owui_chat_id,
                owui_user_id=body.owui_user_id,
                updated_at=now,
            ))
        # Scoped to this user on purpose: unscoped, every message swept every
        # other user's rows and could not use the (owui_user_id, updated_at)
        # index, so one person's write paid for everyone's housekeeping.
        # The tradeoff is that a user who starts one conversation and never
        # returns leaves a row nothing will collect, since only their own next
        # write matches. Accepted: the row is a pointer, and the conversation it
        # points at is an Open WebUI chat we never delete anyway, so the cost is
        # a few dozen bytes and no data is retained that would not be retained
        # regardless.
        await s.execute(delete(GatewaySession).where(
            GatewaySession.owui_user_id == body.owui_user_id,
            GatewaySession.updated_at < now - timedelta(days=SESSION_RETENTION_DAYS),
        ))
        await s.commit()
    return {"status": "ok"}


@router.get("/sessions/recent")
async def recent_sessions(owui_user_id: str, limit: int = 10,
                          x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Backs /resume. Newest first, capped."""
    _require_internal(x_internal_secret)
    limit = max(1, min(limit, 25))
    async with session() as s:
        rows = (await s.execute(
            select(GatewaySession)
            .where(GatewaySession.owui_user_id == owui_user_id)
            .order_by(GatewaySession.updated_at.desc())
            .limit(limit)
        )).scalars().all()
    return {"sessions": [
        {"platform": r.platform, "chat_id": r.chat_id,
         "owui_chat_id": r.owui_chat_id,
         "updated_at": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows
    ]}


# ---------------------------------------------------------------------------
# User-facing. X-User-Email is injected by api-gateway from the caller's Open
# WebUI session cookie, so reaching these endpoints already proves who you are.
# That is what makes redeeming a code inherently an act by a known account: the
# gateway never learns a password and the user never pastes a token.
# ---------------------------------------------------------------------------
from fastapi import Depends                             # noqa: E402
from fastapi.responses import HTMLResponse               # noqa: E402

from auth import CurrentUser, current_user              # noqa: E402
from models import GatewayRedeemBudget                  # noqa: E402

page_router = APIRouter(prefix="/tasks/gateway")


class RedeemIn(BaseModel):
    # Bounded on purpose. An 8 character code pasted with spaces or dashes fits
    # easily, and normalize_code scans every character it is given, so an
    # unbounded body would buy an O(n) scan on a public endpoint.
    code: str = Field(min_length=1, max_length=24)


# Two paths, one page. "/channels" is what the sidebar links to and what the
# address bar shows, because "gateway/link" describes the mechanism rather than
# the thing, and it is the URL a user would copy to a colleague.
#
# "/link" stays forever: it is baked into every pairing message already sent,
# including ones sitting unread in somebody's Telegram, and webhook-handler
# builds it from GATEWAY_PUBLIC_URL. Breaking it would strand those.
@page_router.get("/channels", include_in_schema=False)
@page_router.get("/link", include_in_schema=False)
def link_page() -> HTMLResponse:
    """Inert HTML. Everything it can do goes back through POST /link.

    CHANNEL_CATALOGUE is a hardcoded tuple: the list of channels, and every
    row's status/note/blurb/icon/can_bring_bot, never depends on who is
    asking. So none of that needs the round trip to GET /connections before
    it can draw. It is computed here, with _channel_status(entry, {}) -- the
    SAME function /connections calls, with an empty `linked` dict standing in
    for "no user" -- and injected into the page as window.__CHANNELS__, so
    all ten rows are already in the HTML response and paint before the
    browser has made a single request.

    Each row also gets _route_for(row, shared): without it, `via`/`via_label`
    stay empty on every row (the two fields the page's script needs to draw
    the "via IO's bot, or bring your own" line under an unconnected but
    offerable channel like Telegram). That line would then only ever appear
    once GET /connections returns, so on a slow or failed request the first,
    fastest-painting version of the page silently under-explains itself. The
    shared bot handle is a server-wide env var, never a per-user value, so
    calling it here adds no user identity to this route.

    That empty dict is also what keeps this route free of any user identity:
    no current_user dependency, no database session. The per-user status
    (which channels this account actually linked, and any bot it saved)
    still only ever comes from GET /connections, called by the page's own
    script after it draws the static shell.
    """
    path = os.path.join(os.path.dirname(__file__), "static", "gateway-link.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    shared = _shared_bot_handle()
    rows = []
    for entry in CHANNEL_CATALOGUE:
        row = _channel_status(entry, {})
        row.update(_route_for(row, shared))
        rows.append(row)
    payload = json.dumps(rows)
    # A raw </script> inside the JSON would close the tag early and let the
    # rest of the payload run as markup. The data is ours today (it comes
    # from CHANNEL_CATALOGUE and env vars, nothing a user supplied), but the
    # escape is what keeps that true if this ever picks up a user-shaped
    # field.
    payload = payload.replace("<", "\\u003c")
    seed = f"<script>window.__CHANNELS__ = {payload};</script>\n"

    idx = html.find("<script>")
    html = seed + html if idx == -1 else html[:idx] + seed + html[idx:]

    # Never cache this page. It went out with no cache directives at all, so a
    # browser was free to hold its own copy and did: after a deploy that
    # replaced every channel logo, the page kept rendering the old marks and
    # looked like the deploy had simply not worked.
    #
    # It is also the wrong page to cache on the merits. The markup carries
    # window.__CHANNELS__, which is computed per request from the catalogue
    # and from env vars, so a stale copy can claim a channel is off when it
    # is live, or name a bot the server no longer has.
    return HTMLResponse(content=html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    A minted token carries the id, not the address, so pairing resolves it once
    here. Raw asyncpg because public."user" is Open WebUI's own table and has no
    model in this service; same approach as routes_knowledge_graph.py.
    """
    import asyncpg

    conn = await asyncpg.connect(os.environ.get("DATABASE_URL", ""))
    try:
        row = await conn.fetchrow(
            'SELECT id FROM public."user" WHERE lower(email) = lower($1) LIMIT 1',
            email)
    finally:
        await conn.close()
    return row["id"] if row else None


async def _locked_minutes(s, email: str, now: datetime) -> int | None:
    """Whole minutes left on this account's lockout, or None if it is not locked."""
    row = (await s.execute(
        select(GatewayRedeemBudget).where(GatewayRedeemBudget.email == email)
    )).scalar_one_or_none()
    if row is None or row.locked_until is None or row.locked_until <= now:
        return None
    return max(1, int((row.locked_until - now).total_seconds() // 60) + 1)


async def _record_failure(s, email: str, now: datetime) -> None:
    """Charge a wrong guess to the account that made it.

    Counting on the account rather than the code is the whole point: a wrong
    code matches no row, so the only way to count it on the code would be to
    increment every live one, which would let one guesser lock out every
    pending pairing on the platform.

    A served lock resets the window. Re-locking on the first later typo would
    punish someone who already waited out a lockout far more than an attacker,
    who simply waits either way.
    """
    row = (await s.execute(
        select(GatewayRedeemBudget).where(GatewayRedeemBudget.email == email)
    )).scalar_one_or_none()

    if row is None:
        s.add(GatewayRedeemBudget(email=email, failures=1, window_started_at=now))
        await s.commit()
        return

    window_expired = (
        row.window_started_at is None
        or row.window_started_at < now - timedelta(seconds=gp.REDEEM_WINDOW_SECONDS)
    )
    lock_served = row.locked_until is not None and row.locked_until <= now

    if window_expired or lock_served:
        row.failures = 1
        row.window_started_at = now
        row.locked_until = None
    else:
        row.failures = (row.failures or 0) + 1
        if row.failures >= gp.MAX_REDEEM_ATTEMPTS:
            row.locked_until = now + timedelta(seconds=gp.REDEEM_LOCKOUT_SECONDS)
            row.failures = 0
            row.window_started_at = now
    await s.commit()


@page_router.post("/link")
async def redeem(body: RedeemIn,
                 user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Turn a pairing code into a link, as the signed-in user."""
    code = gp.normalize_code(body.code)
    now = _now()

    async with session() as s:
        locked_for = await _locked_minutes(s, user.email, now)
        if locked_for is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many wrong codes. Try again in {locked_for} minutes.")

        if len(code) != gp.CODE_LENGTH:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=400,
                                detail="That code does not look right.")

        row = (await s.execute(
            select(GatewayPairingCode).where(
                GatewayPairingCode.code_hash == gp.hash_code(code),
                GatewayPairingCode.redeemed_at.is_(None),
            ).limit(1)
        )).scalar_one_or_none()

        if row is None:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=404,
                                detail="That code is not valid. Ask for a new one.")
        if row.expires_at <= now:
            await _record_failure(s, user.email, now)
            raise HTTPException(status_code=410,
                                detail="That code has expired. Ask for a new one.")

        owui_user_id = await _owui_user_id_for(user.email)
        if not owui_user_id:
            raise HTTPException(status_code=404,
                                detail="No IO account for that address.")

        existing = (await s.execute(
            select(GatewayLink).where(
                GatewayLink.platform == row.platform,
                GatewayLink.platform_user_id == row.platform_user_id,
            )
        )).scalar_one_or_none()
        if existing:
            existing.owui_user_id = owui_user_id
            existing.email = user.email
            existing.platform_user_name = row.platform_user_name
            existing.linked_at = now
        else:
            s.add(GatewayLink(
                platform=row.platform,
                platform_user_id=row.platform_user_id,
                owui_user_id=owui_user_id,
                email=user.email,
                platform_user_name=row.platform_user_name,
            ))
        row.redeemed_at = now
        platform, name = row.platform, row.platform_user_name or ""

        # A success wipes the slate: the account clearly is not guessing.
        await s.execute(
            delete(GatewayRedeemBudget).where(GatewayRedeemBudget.email == user.email))
        await s.commit()

    log.info("gateway: linked a %s account to %s", platform, user.email)
    return {"status": "linked", "platform": platform, "platform_user_name": name}


#: Platforms that can actually honour a saved token today. Every other channel
#: shows the controls in an inert state, so the page never grows a button that
#: lies.
BOT_CAPABLE_PLATFORMS = {"telegram", "buzz", "discord", "slack"}

#: Channels where switching a bot ON means registering a webhook with the
#: platform, because the platform calls us. Everything else is a connection IO
#: holds open, which webhook-handler reconciles by polling what is enabled here
#: — nothing to register, and no push that could get out of step.
#:
#: This distinction was missing, and toggle/remove called Telegram for every
#: platform. A user toggling their Buzz connection sent its Nostr key to
#: api.telegram.org, and Telegram's inevitable rejection was then stored as the
#: truth: the row stayed disabled, carrying a Telegram error, and they could
#: not switch their own connection back on.
WEBHOOK_PLATFORMS = {"telegram"}

#: Whose words an error message is quoting, so a Slack scope problem is not
#: reported as something Telegram said.
PLATFORM_LABEL = {"telegram": "Telegram", "discord": "Discord",
                  "slack": "Slack", "buzz": "Buzz"}

# What a user has to fill in to connect a channel with their own credentials,
# described here rather than drawn in the page. Every channel that can carry a
# personal connection needs a form, and hardcoding one channel's fields into
# the markup meant the next channel needed new UI before anyone could set it
# up. Adding a channel is now an entry here.
#
# `secret` decides two things at once: the field renders as a password, and
# its value is the one encrypted at rest. `pitch` is what the user is told
# they are agreeing to, which is not boilerplate: it is the only place they
# learn what saving this actually grants.
CONNECT_FORMS: dict[str, dict] = {
    "telegram": {
        "title": "Use my own bot",
        "pitch": "Your bot, your token, your data. Nobody else can see it or "
                 "configure it. Saving it lets IO send messages as that bot.",
        "submit": "Save & enable",
        "fields": [
            {"name": "token", "label": "Bot token", "secret": True,
             "placeholder": "paste the token",
             "help": "Get one from BotFather on Telegram."},
            {"name": "allowed_ids", "label": "Allowed Telegram user IDs",
             "secret": False, "placeholder": "leave empty for just you",
             "help": ""},
        ],
    },
    "discord": {
        "title": "Use my own bot",
        "pitch": "Your bot in your own server. Nobody else can see the token "
                 "or configure it. IO answers direct messages sent to it, and "
                 "never reads your server's channels.",
        "submit": "Save & enable",
        "fields": [
            {"name": "token", "label": "Bot token", "secret": True,
             "placeholder": "paste the token",
             "help": "Discord Developer Portal, your application, Bot, Reset "
                     "Token. Then invite the bot to a server you are in, "
                     "because Discord only lets you DM a bot you share a "
                     "server with."},
            {"name": "allowed_ids", "label": "Allowed Discord user IDs",
             "secret": False, "placeholder": "leave empty for just you",
             "help": ""},
        ],
    },
    "slack": {
        "title": "Use my own bot",
        "pitch": "Your Slack app in your own workspace. Nobody else can see "
                 "the tokens or configure them. IO connects out to Slack, so "
                 "there is nothing to publish and nothing for us to install, "
                 "and it answers direct messages only.",
        "submit": "Save & enable",
        "fields": [
            # Bot token first: it is the one a person recognises, and the one
            # that names the workspace back to them when it works.
            {"name": "token", "label": "Bot token", "secret": True,
             "placeholder": "xoxb-...",
             "help": "Your app's OAuth & Permissions page, after installing it "
                     "to your workspace. Needs the chat:write, im:history, "
                     "im:read, im:write and users:read scopes."},
            {"name": "app_token", "label": "App-level token", "secret": True,
             "placeholder": "xapp-...",
             "help": "Basic Information, App-Level Tokens, with the "
                     "connections:write scope. Switch Socket Mode on and "
                     "subscribe to the message.im event, or the app connects "
                     "and never hears anything."},
            {"name": "allowed_ids", "label": "Allowed Slack member IDs",
             "secret": False, "placeholder": "leave empty for just you",
             "help": ""},
        ],
    },
    "buzz": {
        "title": "Connect my Buzz workspace",
        "pitch": "Your workspace, your data. Nobody else can see it or "
                 "configure it. IO joins your Buzz relay as its own agent and "
                 "answers only the people you allow.",
        "submit": "Save & connect",
        "fields": [
            {"name": "endpoint", "label": "Relay URL", "secret": False,
             "placeholder": "wss://buzz.yourteam.com/relay",
             "help": "Your Buzz workspace's relay, the same URL its app uses."},
            # `optional` is what lets this be left blank in the browser. The
            # page requires every secret field otherwise, which made the
            # mint-my-own path — the NORMAL one here — impossible to use: the
            # label said "(optional)" and the button refused to save.
            {"name": "token", "label": "Agent key (optional)", "secret": True,
             "optional": True,
             "placeholder": "leave empty and IO creates its own",
             "help": "Only if you already have one. Nostr identities are not "
                     "issued by anyone, so IO can make its own and show you "
                     "its public key."},
        ],
    },
}



def _public_url() -> str:
    """Where Telegram should deliver. Seam so tests need no env."""
    return os.environ.get("GATEWAY_PUBLIC_URL", "").rstrip("/")


def _saved_label(row: GatewayBot) -> str:
    noun = IDENTITY_NOUN.get(row.platform, "bot")
    label = _identity_label(row.platform, (row.bot_username or "").strip())
    return f"Your {noun} {label}" if label else f"Your {noun} is saved."


def _error_label(row: GatewayBot) -> str:
    if not row.last_error:
        return ""
    if row.platform == "buzz":
        return f"Buzz connection failed: {row.last_error}"
    # Name whoever actually refused. This said "Telegram said:" for every
    # channel, so a Slack scope problem was reported as a Telegram complaint.
    who = PLATFORM_LABEL.get(row.platform, row.platform.title())
    return f"{who} said: {row.last_error}"


def _bot_view(row: GatewayBot) -> dict[str, Any]:
    """What the browser is allowed to know. Never the token.

    `token_hint` is empty here on purpose and is NOT derivable from a stored
    row: only the save response ever knows the plaintext, and only once."""
    return {
        "bot_key": row.bot_key,
        "platform": row.platform,
        "bot_username": row.bot_username or "",
        "token_hint": "",
        "enabled": bool(row.enabled),
        "allowed_ids": row.allowed_ids or "",
        "last_error": row.last_error or "",
        # Whole sentences, decided here rather than assembled in the page.
        # What a connection IS differs per channel, and so does who is
        # reporting a failure: Telegram rejects a token, while a Buzz error is
        # our own connection attempt failing, so "Buzz said" would be a lie.
        "display": _saved_label(row),
        "error_text": _error_label(row),
        # Not a secret, so it comes back and prefills the field on edit. A user
        # editing their allow list should not have to retype their relay URL.
        "endpoint": row.endpoint or "",
        # Whether the connection this service does NOT hold is actually up.
        "connected_at": row.connected_at.isoformat() if row.connected_at else "",
    }


# Every channel the gateway knows about, whether or not it can be used here.
# Showing the ones that are not ready, with the reason, turns this page from a
# login box into something a person can read to understand what is coming. The
# alternative, listing only what works, quietly hides the roadmap.
#
# "ready" is decided at request time, not here: a channel is offerable only if
# this server is actually configured for it. See _channel_status.
CHANNEL_CATALOGUE = (
    # Built and routed through the gateway.
    {"platform": "telegram", "label": "Telegram", "icon": "✈️",
     "connect_headline": "Quick connect · use IO's bot",
     "blurb": "Chat with IO from Telegram direct messages, including voice memos."},
    # "any shell" was true and unhelpful: someone on a phone read it, tried,
    # and had nowhere to type. Naming the machines it needs is shorter than
    # the support conversation that follows when it does not.
    {"platform": "cli", "label": "Terminal", "icon": "⌨️",
     "connect_headline": "Quick connect · from your shell",
     "blurb": "Talk to IO from a shell on Mac, Windows or Linux. "
              "One script, nothing to install but Python. Not phones."},

    # Code already exists in this platform, but not behind the gateway yet.
    # Both were already talking to IO before Channels existed, through the
    # command router. What they lacked is an answer from the sender's OWN
    # account: Slack fell through to one shared model with one shared prompt,
    # the same for everybody, and Discord fell through to silence. No `planned`
    # key, because these are switched on per server like the terminal is.
    {"platform": "slack", "label": "Slack", "icon": "💬",
     "blurb": "Use IO from Slack direct messages.",
     "caveat": "Messages you send from Slack pass through Slack, and Slack "
               "vouches for who you are."},
    {"platform": "discord", "label": "Discord", "icon": "🎮",
     "blurb": "Use IO from Discord direct messages.",
     "caveat": "Messages you send from Discord pass through Discord, and "
               "Discord vouches for who you are."},

    # Not started, and nothing else in this codebase to build on.
    {"platform": "mattermost", "label": "Mattermost", "icon": "💠",
     "blurb": "Use IO from Mattermost channels and direct messages.",
     "planned": "Not started. Needs a bot account and a webhook route."},
    {"platform": "matrix", "label": "Matrix", "icon": "🔷",
     "blurb": "Use IO from Matrix rooms and direct messages.",
     "planned": "Not started. Needs a homeserver login this box does not hold."},

    # Specified, blocked on things that are not code.
    {"platform": "whatsapp", "label": "WhatsApp", "icon": "📱",
     "blurb": "Message IO from WhatsApp.",
     "planned": "Needs Meta business verification and template approval."},
    {"platform": "signal", "label": "Signal", "icon": "🔒",
     "blurb": "Message IO from Signal.",
     "planned": "Needs a daemon this server does not have the memory for."},

    # Plausible next, because the platform already has the hard part.
    {"platform": "teams", "label": "Microsoft Teams", "icon": "👥",
     "blurb": "Use IO from Teams chats.",
     "planned": "Not started. Microsoft sign-in already exists to build on."},

    # The only channel here where the work is not ours alone. Every entry above
    # is reached by us calling somebody's API; Buzz is a Nostr workspace, so IO
    # is not called at all. It joins the workspace as an agent, which means the
    # person who owns that workspace has to mint it an identity there first.
    # That is why this row carries setup steps and the others do not.
    {"platform": "buzz", "label": "Buzz", "icon": "🐝",
     # Reads as what it is once the workspace form sits above it: the second
     # half. It used to say "Quick connect", above a form without which no
     # code can ever arrive.
     "connect_headline": "Then pair your account",
     # What the user has to do on the far side before anything here can work.
     # It lives on the row because it used to live only in a chat message, and
     # the row instead said "message IO from Buzz and it will reply with a
     # code" — which no Buzz user could ever make happen, since IO was not in
     # their workspace to be messaged.
     "setup": {
         "headline": "How Buzz connects",
         "steps": [
             "Copy your workspace's relay URL, the wss:// address the Buzz app "
             "itself connects to. That is the only thing you need to find.",
             "Paste it below and save. IO creates its own identity and shows "
             "you its public key, an npub. Nobody issues these, so there is "
             "nothing to create in Buzz first.",
             "If your workspace only accepts members you invite, add that npub "
             "there. Then message IO from Buzz and it replies with a code.",
         ],
     },
     # Every other channel offers IO's own bot as the easy way in. Buzz has no
     # such thing to offer, so the row says what is actually on offer here.
     "offer_label": "connect your own Buzz workspace",
     # Shown once saved. IO generated this identity itself, and a workspace
     # that only admits invited members needs the public half of it.
     "identity_public": {
         "label": "IO's identity in your workspace",
         "help": "If your Buzz workspace only accepts members you invite, add "
                 "this npub there. Then message IO from Buzz.",
     },
     "blurb": "Use IO from Buzz, where your people, agents and projects "
              "sit in one place.",
     # Every channel that is not this browser relays through somebody, and a
     # user deserves to know who before they connect it rather than after.
     # Buzz carries the message AND vouches for who sent it, which is the
     # same trust Slack and Teams ask for. Nothing cryptographic changes that:
     # the message was typed into Buzz.
     "caveat": "Messages you send from Buzz pass through Buzz, and Buzz "
               "vouches for who you are."},
)



def _shared_bot_handle() -> str:
    """The bot IO operates, for channels that have one."""
    return os.environ.get("GATEWAY_TELEGRAM_BOT", "").strip()


#: Channels where IO operates an identity everyone can use. Telegram has one
#: bot serving every account; Buzz cannot, because an identity there lives
#: inside somebody's workspace and IO is not a member of anyone's until they
#: invite it. So a Buzz row must never offer "IO's bot" as a way in.
SHARED_BOT_PLATFORMS = {"telegram"}


#: What a personal connection IS on each channel. Telegram's is a bot with an
#: @handle; Buzz's is a keypair with an npub, and calling that "your bot" sends
#: someone looking for something Buzz does not have.
IDENTITY_NOUN = {"buzz": "agent"}


def _identity_label(platform: str, handle: str) -> str:
    """How to print a saved connection's identity on a row."""
    if not handle:
        return ""
    if platform == "buzz":
        # An npub is 63 characters. The ends are what a person compares
        # against what Buzz shows them.
        return nostr_nip19.shorten(handle)
    return "@" + handle


def _route_for(row: dict, shared: str) -> dict[str, str]:
    """WHICH bot IO uses to reach this account on this channel.

    "Connected" alone does not tell a user the thing they actually want to
    know, which is whose bot is carrying their messages: the one IO runs and
    can see, or their own. That distinction is the entire point of bringing
    your own bot, so the page has to name it.

    Derived rather than stored, and it matches the routing rule: an enabled
    personal bot is where IO reaches you, so it wins the moment it exists,
    even before the pairing that follows.

    Generic on purpose. Every channel gets this the moment it can carry a
    personal bot; nothing here is Telegram-specific.
    """
    # No personal bot is possible here, so there is no whose-bot question to
    # answer. The terminal is the case that makes this obvious: you connect a
    # device, not a bot, and naming IO's Telegram bot on that row would be
    # simply false.
    if not row.get("can_bring_bot"):
        return {"via": "", "via_label": ""}

    # A channel where IO runs no identity of its own. Naming a shared bot on
    # such a row would offer a way in that does not exist, which is exactly
    # what the Buzz row did when it borrowed Telegram's sentence.
    if row["platform"] not in SHARED_BOT_PLATFORMS:
        shared = ""

    bot = row.get("bot")
    if bot and bot.get("enabled"):
        noun = IDENTITY_NOUN.get(row["platform"], "bot")
        label = _identity_label(row["platform"], (bot.get("bot_username") or "").strip())
        named = f"Your {noun} {label}" if label else f"Your own {noun}"
        if row.get("status") != "connected":
            # Saved a bot but never paired: the row used to say only "ready to
            # connect" and nothing else, while the panel below it plainly
            # showed the saved bot. Two states that look identical on the row
            # and are not: one has work left, the other does not.
            return {"via": "own",
                    "via_label": named + " is saved. Message it to finish."}
        return {"via": "own", "via_label": named}

    if row.get("status") == "connected":
        return {"via": "shared",
                "via_label": f"IO's bot {shared}" if shared else "IO's own bot"}

    # Not connected but available, and this channel CAN carry a personal bot, so
    # the row can still answer the whose-bot question instead of saying only "ready".
    # Without this, nothing on the page reveals that bringing your own bot is
    # possible until after someone has already paired the other way.
    if row.get("status") == "available":
        if shared:
            return {"via": "offer",
                    "via_label": f"via IO's bot {shared}, or bring your own"}
        return {"via": "offer", "via_label": row.get("offer_label")
                or f"bring your own {IDENTITY_NOUN.get(row['platform'], 'bot')}"}

    return {"via": "", "via_label": ""}


def _channel_status(entry: dict, linked: dict) -> dict:
    """One row for the page: what this channel is and what you can do with it.

    status is one of:
      connected   this account has linked it
      available   configured on this server, ready to link
      off         built, but not switched on here
      planned     not built yet, with a reason
    """
    platform = entry["platform"]
    row = {"platform": platform, "label": entry["label"], "icon": entry["icon"],
           "blurb": entry.get("blurb", ""), "name": "", "linked_at": None,
           "note": "",
           # The page draws the same three controls on every row. These two say
           # which of them can actually do anything here.
           "can_bring_bot": platform in BOT_CAPABLE_PLATFORMS,
           # Whether IO runs an identity on this channel that anyone can use.
           # Where it does not, bringing your own is not an alternative to the
           # quick path, it IS the path, and the page has to order the two
           # accordingly or it shows step two above step one.
           "has_shared_bot": platform in SHARED_BOT_PLATFORMS,
           "bot": None,
           # Who else handles your messages on this channel. Empty for the
           # ones that relay through nobody.
           "caveat": entry.get("caveat", ""),
           # What the expanded row calls its first path in. Named per
           # channel because the page used to infer it from whether a
           # personal bot was possible, which is a binary that was wrong
           # the moment a third kind of channel existed.
           "connect_headline": entry.get("connect_headline", "Quick connect"),
           # The form for bringing your own connection, so the page
           # renders whatever a channel needs instead of one
           # channel's fields written into the markup.
           "connect_form": CONNECT_FORMS.get(platform),
           # What this channel offers instead of IO's own bot, where there
           # isn't one. Read by _route_for.
           "offer_label": entry.get("offer_label", ""),
           # An identity the user must carry somewhere else once it exists.
           # Only Buzz: a workspace that admits known members needs IO's
           # public key, and nothing else on this page has that shape.
           "identity_public": entry.get("identity_public"),
           # What a personal connection is called here. "Remove bot" on a
           # keypair is the same wrong word as "Use my own bot" was.
           "identity_noun": IDENTITY_NOUN.get(platform, "bot"),
           # What the user must do on the far side first, for the channels
           # where connecting is not something this server can do alone.
           # None on every channel we reach by calling an API.
           "setup": entry.get("setup"),
           # Filled by _route_for once this account's bots are known. Present
           # here so every row carries one shape, including the user-free
           # catalogue injected into the page.
           "via": "", "via_label": ""}

    if platform in linked:
        row.update(linked[platform], status="connected")
        return row

    if "planned" in entry:
        return {**row, "status": "planned", "note": entry["planned"]}

    # Presence of the config is the signal, so this cannot drift from reality
    # the way a hand-maintained list would. Telegram is keyed on the bot handle
    # rather than the token, which keeps secrets off this service entirely.
    if platform == "telegram":
        bot = os.environ.get("GATEWAY_TELEGRAM_BOT", "").strip()
        if bot:
            return {**row, "status": "available",
                    "note": f"Message {bot} on Telegram and it will send you a code."}
        return {**row, "status": "off",
                "note": "No Telegram bot is configured on this server yet."}

    if platform == "buzz":
        # The flag is read by BOTH services on purpose. webhook-handler runs
        # the agent connection; this service only renders the row, and setting
        # the flag on one of them is exactly how the terminal channel ended up
        # live while the page called it switched off.
        #
        # It stays unset until the agent transport exists. Flipping it early is
        # what put "message IO from Buzz and it will reply with a code" on this
        # row, an instruction no Buzz user could carry out: IO was not in their
        # workspace to be messaged. The pairing note below is only true once IO
        # is an agent there, so it lives behind the same flag.
        if os.environ.get("BUZZ_ENABLED", "").strip():
            # Note the ORDER. On Telegram you message IO's bot first and pair
            # second. Here there is nothing to message until you have given IO
            # an identity in your workspace, so connecting comes first and the
            # note must not imply otherwise.
            return {**row, "status": "available",
                    "note": "Once your workspace is connected, message IO "
                            "from Buzz and it will reply with a code."}
        return {**row, "status": "off",
                "note": "The Buzz channel is switched off on this server."}

    # Both read the SAME flag their service reads. Setting it on one service
    # only is exactly how the terminal channel ended up live while the page
    # called it switched off.
    if platform in ("slack", "discord"):
        flag = f"GATEWAY_{platform.upper()}_ENABLED"
        if os.environ.get(flag, "").strip():
            return {**row, "status": "available",
                    "note": f"Message IO on {entry['label']} and it will "
                            "reply with a code."}
        return {**row, "status": "off",
                "note": f"{entry['label']} talks to IO already, but not yet "
                        "as your own account. Not switched on here."}

    if platform == "cli":
        if os.environ.get("GATEWAY_CLI_ENABLED", "").strip():
            return {**row, "status": "available",
                    "note": "Download the one-file client and it will print a code."}
        return {**row, "status": "off",
                "note": "The terminal client is switched off on this server."}

    return {**row, "status": "off", "note": ""}


@page_router.get("/connections")
async def list_connections(
        user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Every channel, with this account's status for each."""
    async with session() as s:
        rows = (await s.execute(
            select(GatewayLink).where(GatewayLink.email == user.email)
            .order_by(GatewayLink.linked_at.desc())
        )).scalars().all()
        bots = (await s.execute(
            select(GatewayBot).where(GatewayBot.email == user.email)
        )).scalars().all()

    linked = {
        r.platform: {
            "name": r.platform_user_name or "",
            "linked_at": r.linked_at.isoformat() if r.linked_at else None,
        }
        for r in rows
    }
    by_platform = {b.platform: _bot_view(b) for b in bots}

    shared = _shared_bot_handle()
    connections = []
    for entry in CHANNEL_CATALOGUE:
        row = _channel_status(entry, linked)
        row["bot"] = by_platform.get(row["platform"])
        row.update(_route_for(row, shared))
        connections.append(row)

    return {
        "telegram_bot": shared,
        "connections": connections,
    }


@page_router.delete("/connections/{platform}")
async def disconnect(platform: str,
                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    """Unlink one surface from this account.

    Deletes only the link. Session rows are left alone deliberately: they point
    at real Open WebUI chats which are the user's own data, and if this account
    re-pairs the same surface it picks the conversation back up. If a DIFFERENT
    account pairs it, the owner check in get_or_create_chat starts them a fresh
    chat rather than showing them this one.
    """
    async with session() as s:
        result = await s.execute(
            delete(GatewayLink).where(
                GatewayLink.email == user.email,
                GatewayLink.platform == platform,
            ))
        await s.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="That was not connected.")
    log.info("gateway: disconnected %s from %s", platform, user.email)
    return {"status": "disconnected", "platform": platform}


# --- A bot the user brought themselves ---------------------------------------
# Hermes configures one bot per server. Here a bot belongs to one account, so
# every read below filters on the session email and never on a path value.

class BotIn(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    #: May be empty where the platform lets IO mint its own credential. Which
    #: platforms those are is decided per platform below, not by this field:
    #: a blank Telegram token is still refused.
    token: str = Field(default="", max_length=200)
    #: A second credential, for a channel that needs two. Slack Socket Mode is
    #: the only one: xoxb- sends and xapp- opens the websocket. Empty
    #: everywhere else, and refused where it is required.
    app_token: str = Field(default="", max_length=200)
    allowed_ids: str = Field(default="", max_length=500)
    #: Only platforms IO connects OUT to send one. Telegram never does.
    endpoint: str = Field(default="", max_length=300)


def _buzz_test(row: GatewayBot, token: str) -> dict[str, Any]:
    """What we can honestly say about a Buzz connection from this service.

    Deliberately does not claim more than it knows. `connected_at` is written
    by whichever process actually holds the socket, so an empty one means "not
    up yet" and never "broken", and the two read very differently to someone
    who just pressed a button.
    """
    try:
        npub = nostr_nip19.encode(
            nostr_schnorr.pubkey_from_seckey(nostr_nip19.decode(token, "nsec")),
            "npub")
    except Exception:                                          # noqa: BLE001
        return {"ok": False,
                "detail": "The saved key could not be read. Remove this "
                          "connection and paste the key again."}

    who = f"IO connects to {row.endpoint} as {nostr_nip19.shorten(npub)}."
    if row.last_error:
        return {"ok": False, "detail": f"{who} Last attempt failed: {row.last_error}"}
    if not row.connected_at:
        return {"ok": True,
                "detail": f"{who} Connecting now, it takes up to a minute."}
    return {"ok": True, "detail": f"{who} Connected. Message it from Buzz."}


async def _socket_bot_test(row: GatewayBot, token: str) -> dict[str, Any]:
    """What we can honestly say about a Discord or Slack bot from here.

    Two separate facts, kept separate on purpose:

      the credential  — re-checked live, right now, against the platform
      the connection  — whatever webhook-handler last reported, because this
                        service does not hold the socket

    Reporting only the first would call a bot "working" while its websocket has
    been refused all day. Reporting only the second cannot tell a user whether
    the token they just pasted is the problem. An empty `connected_at` means
    "not up yet", never "broken": those read very differently to somebody who
    pressed a button ten seconds after saving.
    """
    who = ""
    try:
        if row.platform == "discord":
            me = await discord_api.get_me(token)
            who = f"@{me.get('username', '')}" if me.get("username") else "your bot"
        else:
            team = (await slack_api.auth_test(token)).get("team", "")
            who = f"the {team} workspace" if team else "your workspace"
    except (discord_api.DiscordError, slack_api.SlackError) as exc:
        label = PLATFORM_LABEL.get(row.platform, row.platform.title())
        return {"ok": False, "detail": f"{label} said: {exc.description}"}

    label = PLATFORM_LABEL.get(row.platform, row.platform.title())
    if row.last_error:
        return {"ok": False,
                "detail": f"The credentials for {who} are good, but the last "
                          f"connection attempt failed: {row.last_error}"}
    if not row.connected_at:
        return {"ok": True,
                "detail": f"The credentials for {who} are good. Connecting "
                          f"now, it takes up to a minute."}
    return {"ok": True,
            "detail": f"Connected to {who}. Send it a direct message on "
                      f"{label}."}


def new_agent_key() -> str:
    """A fresh Nostr identity for IO, as an `nsec1...`.

    A Nostr identity is a keypair and nothing else. Nobody issues one: there is
    no registry, no approval, and no API to ask. So IO can mint its own, and
    that is the ordinary path rather than a fallback, because it means a user
    never has to obtain or paste a private key at all.

    Retried on the vanishing chance that 32 random bytes land outside the
    group order, which would be an unusable key.
    """
    for _ in range(8):
        raw = secrets.token_bytes(32)
        try:
            nostr_schnorr.pubkey_from_seckey(raw)
        except ValueError:                              # pragma: no cover
            continue
        return nostr_nip19.encode(raw, "nsec")
    raise RuntimeError("could not generate a usable key")   # pragma: no cover


async def _prepare_discord(body: BotIn) -> tuple[str, str]:
    """Validate a user's own Discord bot. Returns (username, token to store).

    One token, checked against Discord before anything is written, so a stored
    row always means a credential that worked at least once.

    Nothing here can check the part that actually strands people: Discord will
    not deliver a DM to a bot the sender shares no server with, so a perfectly
    valid token can still result in silence. That is why the form's help says
    to invite the bot somewhere rather than leaving them to find out.
    """
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Paste your bot token.")
    try:
        me = await discord_api.get_me(token)
    except discord_api.DiscordError as exc:
        raise HTTPException(status_code=400,
                            detail=f"Discord said: {exc.description}")
    return me.get("username", ""), token


async def _prepare_slack(body: BotIn) -> tuple[str, str, str]:
    """Validate a user's own Slack app. Returns (workspace, xoxb, xapp).

    BOTH tokens are checked, because they fail in different ways and only one
    of those failures is visible later. A bad bot token is obvious the first
    time IO tries to reply. A bad app-level token, or Socket Mode left switched
    off, means the websocket never opens and the app simply never hears
    anything — indistinguishable from nobody having messaged it.

    The workspace name is what comes back to the row, because it is the thing
    a person recognises. "Your bot xoxb-…" tells them nothing; "Your bot Acme"
    tells them they connected the workspace they meant.
    """
    token = (body.token or "").strip()
    app_token = (body.app_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Paste your bot token.")
    if not app_token:
        raise HTTPException(
            status_code=400,
            detail="Paste your app-level token too. Slack needs both: the "
                   "xoxb- token sends messages and the xapp- token opens the "
                   "connection.")
    try:
        who = await slack_api.auth_test(token)
    except slack_api.SlackError as exc:
        raise HTTPException(status_code=400,
                            detail=f"Slack said: {exc.description}")
    try:
        await slack_api.open_connection(app_token)
    except slack_api.SlackError as exc:
        raise HTTPException(status_code=400, detail=exc.description)
    return who.get("team", ""), token, app_token


def _prepare_buzz(body: BotIn) -> tuple[str, str, str]:
    """Validate a Buzz connection. Returns (npub, relay url, nsec to store).

    The key is OPTIONAL, and leaving it empty is the normal path. Buzz has no
    "create an agent" step to send someone to, and requiring one made the form
    ask for something a user could not produce. A keypair is self-minted, so
    IO makes its own and shows the public half, which is all a workspace needs
    in order to let it in.

    A pasted key is still accepted for anyone who does have one. It is checked
    before a row is written, matching Telegram's rule that a stored row means
    credentials that were good at least once. Telegram can be asked directly;
    a relay cannot be reached from this service, so what is proven here is what
    can be proven locally: the checksum, the length, and that the key is a real
    point on the curve.
    """
    endpoint = (body.endpoint or "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Paste your relay URL.")
    if not endpoint.startswith(("wss://", "ws://")):
        raise HTTPException(
            status_code=400,
            detail="A relay URL starts with wss://. Copy the one your Buzz app uses.")
    if len(endpoint) > 300:
        raise HTTPException(status_code=400, detail="That relay URL is too long.")

    nsec = (body.token or "").strip() or new_agent_key()
    try:
        seckey = nostr_nip19.decode(nsec, "nsec")
    except nostr_nip19.Bech32Error as exc:
        # The message is written for a person and says which mistake it was.
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        pubkey = nostr_schnorr.pubkey_from_seckey(seckey)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="That key is not a usable Nostr key. Leave the field empty "
                   "and IO will create one for you.")

    # The FULL npub, not a shortened one: this is what the user copies into
    # Buzz to let IO in, so it has to be the real thing.
    return nostr_nip19.encode(pubkey, "npub"), endpoint, nsec


class BotToggleIn(BaseModel):
    enabled: bool


@page_router.post("/bots")
async def save_bot(body: BotIn,
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Store a user's own bot token and point it at this server.

    getMe runs BEFORE anything is written, so a stored row always means a token
    that worked at least once. If setWebhook then fails the row survives but
    disabled, with the reason on it: a half-live bot that silently swallows
    messages is worse than one the page can tell you is broken."""
    platform = body.platform.strip().lower()
    if platform not in BOT_CAPABLE_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"{platform} cannot take your own bot yet.")

    token = body.token.strip()

    # Each platform proves its credentials before anything is stored, in
    # whatever way that platform allows: Telegram and Discord can be asked
    # directly, Slack needs asking twice because it issues two tokens, and Buzz
    # is a relay this service cannot reach so it is checked arithmetically.
    # Each branch owns its own "you left it empty" message, because "Paste your
    # bot token" is wrong for Buzz (which mints its own) and incomplete for
    # Slack (which needs two).
    endpoint = ""
    app_token = ""
    if platform == "buzz":
        display_name, endpoint, token = _prepare_buzz(body)
    elif platform == "discord":
        display_name, token = await _prepare_discord(body)
    elif platform == "slack":
        display_name, token, app_token = await _prepare_slack(body)
    else:
        if not token:
            raise HTTPException(status_code=400, detail="Paste your bot token.")
        try:
            display_name = (await telegram_api.get_me(token)).get("username", "")
        except telegram_api.TelegramError as exc:
            raise HTTPException(status_code=400,
                                detail=f"Telegram said: {exc.description}")

    bot_key = gbots.new_bot_key()
    secret = gbots.new_webhook_secret()

    try:
        encrypted = gbots.encrypt_token(token)
        # Encrypted with the same key and by the same rule: a credential that
        # opens a socket carrying every DM the app can see is no less sensitive
        # than the one that sends the replies.
        app_encrypted = gbots.encrypt_token(app_token) if app_token else None
    except (RuntimeError, ValueError) as exc:
        # RuntimeError: AIUI_FERNET_KEY is missing. ValueError: it is set but
        # is not a valid Fernet key (wrong length, not base64). Either way,
        # refuse rather than store plaintext.
        log.error("gateway: cannot store a bot token: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="This server cannot store bot tokens securely right now.")

    async with session() as s:
        await s.execute(
            delete(GatewayBot).where(GatewayBot.email == user.email,
                                     GatewayBot.platform == platform))
        row = GatewayBot(
            bot_key=bot_key, email=user.email, platform=platform,
            token_encrypted=encrypted, app_token_encrypted=app_encrypted,
            webhook_secret=secret,
            bot_username=display_name, endpoint=endpoint,
            allowed_ids=gbots.parse_allowed_ids(body.allowed_ids),
            enabled=True, last_error=None,
        )
        s.add(row)
        await s.commit()

    if platform not in WEBHOOK_PLATFORMS:
        # Nothing to register. webhook-handler reconciles what is open against
        # what is enabled here, so the connection comes up on its own within
        # one poll. A push from this service would be one more thing to get out
        # of step, and would not survive either service restarting.
        log.info("gateway: %s saved their own %s connection", user.email, platform)
        return {"bot_key": bot_key, "platform": platform,
                "bot_username": display_name, "endpoint": endpoint,
                "token_hint": gbots.mask_token(token), "enabled": True,
                "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
                "last_error": ""}

    hook_url = f"{_public_url()}/webhook/telegram/{bot_key}"
    try:
        await telegram_api.set_webhook(token, hook_url, secret)
    except telegram_api.TelegramError as exc:
        async with session() as s:
            await s.execute(
                update(GatewayBot).where(GatewayBot.bot_key == bot_key,
                                         GatewayBot.email == user.email)
                .values(enabled=False, last_error=exc.description))
            await s.commit()
        log.warning("gateway: setWebhook failed for %s", user.email)
        return {"bot_key": bot_key, "platform": platform,
                "bot_username": display_name,
                "token_hint": gbots.mask_token(token),
                "enabled": False, "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
                "last_error": exc.description}

    log.info("gateway: %s saved their own %s bot", user.email, platform)
    return {"bot_key": bot_key, "platform": platform,
            "bot_username": display_name,
            "token_hint": gbots.mask_token(token),
            "enabled": True,
            "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
            "last_error": ""}


@page_router.get("/bots")
async def list_bots(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    async with session() as s:
        rows = (await s.execute(
            select(GatewayBot).where(GatewayBot.email == user.email)
        )).scalars().all()
    return {"bots": [_bot_view(r) for r in rows]}


async def _owned_bot(s, email: str, bot_key: str) -> GatewayBot:
    """One bot, or a 404. Filtered on the session email, never on the path
    alone, so bot_key is a lookup handle and not an authorisation."""
    row = (await s.execute(
        select(GatewayBot).where(GatewayBot.bot_key == bot_key,
                                 GatewayBot.email == email)
    )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No such bot.")
    return row


def _decrypt_or_503(row: GatewayBot) -> str:
    """Decrypt one bot's token, turning any failure into a clean error a user
    can act on instead of a 500.

    Covers a rotated AIUI_FERNET_KEY (InvalidToken: the blob was encrypted
    under a key that no longer exists), a corrupt blob (InvalidToken), and a
    malformed key value in the env (crypto_utils raises RuntimeError when
    AIUI_FERNET_KEY is missing, ValueError when it is present but not a valid
    Fernet key; either only surfaces on the first decrypt call in this
    process, since the module caches its Fernet instance after that)."""
    try:
        return gbots.decrypt_token(row.token_encrypted)
    except (InvalidToken, ValueError, RuntimeError) as exc:
        log.error("gateway: could not decrypt a bot token for %s: %s",
                  row.email, exc)
        raise HTTPException(
            status_code=503,
            detail="This bot's saved token could not be read. Remove it and "
                   "reconnect it.")


def _decrypt_internal(row: GatewayBot) -> str:
    """Decrypt one bot's token for an internal endpoint, raising 500 on failure.

    Differs from _decrypt_or_503 in status code: webhook-handler treats
    502/503/504 as transient and asks Telegram to redeliver. A decryption
    failure is permanent: the key rotated or the row is corrupt, and it will
    fail identically on every retry. Reporting it as transient would make
    Telegram retry that message forever. Returning 500 (permanent failure)
    prevents that infinite loop.

    Covers the same errors as _decrypt_or_503: rotated AIUI_FERNET_KEY,
    corrupt blob, and malformed key in the env.
    """
    try:
        return gbots.decrypt_token(row.token_encrypted)
    except (InvalidToken, ValueError, RuntimeError) as exc:
        log.error("gateway: could not decrypt a bot token for %s: %s",
                  row.email, exc)
        raise HTTPException(
            status_code=500,
            detail="This bot's saved token could not be read.")


@page_router.post("/bots/{bot_key}/test")
async def test_bot(bot_key: str,
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """Prove the bot works and say exactly what Telegram said.

    Two modes, because a bot saved thirty seconds ago has nobody to talk to
    yet: unpaired, getMe proves the credential; paired, a real message proves
    the whole path."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        token = _decrypt_or_503(row)
        link = (await s.execute(
            select(GatewayLink).where(GatewayLink.email == user.email,
                                      GatewayLink.platform == row.platform)
        )).scalars().first()
        chat_id = row.owner_platform_user_id or (
            link.platform_user_id if link else "")

    if row.platform == "buzz":
        # This service holds no Buzz socket, so it cannot prove the connection
        # by using it. What it CAN do is answer the two questions a user
        # actually has: is the key I pasted the identity I meant, and is the
        # connection up. The first is arithmetic, the second is whatever
        # webhook-handler last reported.
        return _buzz_test(row, token)

    if row.platform in ("discord", "slack"):
        # Same shape as Buzz and for the same reason: this service holds no
        # socket for either, so it cannot prove the connection by using it.
        # What it CAN do is re-prove the credentials right now and report what
        # webhook-handler last said about the connection, which are the two
        # questions someone pressing this button actually has.
        return await _socket_bot_test(row, token)

    try:
        if chat_id:
            await telegram_api.send_message(
                token, chat_id, "IO is connected. This message came from your own bot.")
            detail = "Sent. Check your Telegram."
        else:
            identity = await telegram_api.get_me(token)
            detail = (f"Your bot @{identity.get('username','')} is alive. "
                      "Now message it and send your code.")
    except telegram_api.TelegramError as exc:
        async with session() as s:
            await s.execute(
                update(GatewayBot).where(GatewayBot.bot_key == bot_key,
                                         GatewayBot.email == user.email)
                .values(last_error=exc.description))
            await s.commit()
        return {"ok": False, "detail": f"Telegram said: {exc.description}"}

    async with session() as s:
        await s.execute(update(GatewayBot)
                        .where(GatewayBot.bot_key == bot_key,
                               GatewayBot.email == user.email)
                        .values(last_error=None))
        await s.commit()
    return {"ok": True, "detail": detail}


@page_router.patch("/bots/{bot_key}")
async def toggle_bot(bot_key: str, body: BotToggleIn,
                     user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """On Telegram, off deletes the webhook, so Telegram stops delivering at
    source rather than us dropping updates we keep receiving.

    Every other channel is a connection webhook-handler holds open, and it
    reconciles against `enabled` here, so flipping the column IS the act and
    there is nothing to call.

    Calling Telegram regardless is what this used to do, and it was already
    broken for Buzz before Discord and Slack existed: toggling a Buzz
    connection sent its Nostr key to api.telegram.org, then stored Telegram's
    rejection as the row's error and left it disabled. The user could not
    switch their own connection back on, and the reason given named the wrong
    company.
    """
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        platform = row.platform
        token = _decrypt_or_503(row) if platform in WEBHOOK_PLATFORMS else ""
        secret = row.webhook_secret

    error = ""
    if platform in WEBHOOK_PLATFORMS:
        try:
            if body.enabled:
                await telegram_api.set_webhook(
                    token, f"{_public_url()}/webhook/telegram/{bot_key}", secret)
            else:
                await telegram_api.delete_webhook(token)
        except telegram_api.TelegramError as exc:
            error = exc.description

    async with session() as s:
        await s.execute(
            update(GatewayBot).where(GatewayBot.bot_key == bot_key,
                                     GatewayBot.email == user.email)
            .values(enabled=bool(body.enabled) and not error,
                    last_error=error or None))
        await s.commit()
        row = await _owned_bot(s, user.email, bot_key)
        return _bot_view(row)


@page_router.delete("/bots/{bot_key}")
async def remove_bot(bot_key: str,
                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    """Remove the row even if Telegram will not let go of the webhook.

    An orphaned webhook points at a bot_key that no longer resolves, which
    404s, so it is inert. Keeping the row because a remote call failed would
    leave the user unable to get rid of their own token."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        if row.platform not in WEBHOOK_PLATFORMS:
            # Nothing registered anywhere, so there is nothing to unregister.
            # Deleting the row is the whole act: webhook-handler drops the
            # connection within one poll because it is no longer listed.
            token = None
        else:
            try:
                token = gbots.decrypt_token(row.token_encrypted)
            except (InvalidToken, ValueError, RuntimeError) as exc:
                # A token we cannot decrypt is one we cannot call deleteWebhook
                # with either. That must not block removal: the row
                # disappearing is what the user asked for, and an orphaned
                # webhook 404s once bot_key no longer resolves, same as any
                # other undeleted hook below.
                log.warning(
                    "gateway: could not decrypt a bot token while removing it, "
                    "deleting the row without clearing the webhook: %s", exc)
                token = None

    if token:
        try:
            await telegram_api.delete_webhook(token)
        except telegram_api.TelegramError:
            log.warning("gateway: could not clear the webhook while removing a bot")

    async with session() as s:
        await s.execute(delete(GatewayBot).where(
            GatewayBot.bot_key == bot_key, GatewayBot.email == user.email))
        await s.commit()
    log.info("gateway: %s removed their own bot", user.email)
    return {"status": "removed"}


# --- What webhook-handler needs to serve an inbound update --------------------
# Internal only. This hands back a DECRYPTED token, so it lives on `router`,
# which is mounted bare at http://tasks:8210 and is unreachable from a browser.


class BotClaimIn(BaseModel):
    platform_user_id: str = Field(min_length=1, max_length=64)


@router.get("/bots/{bot_key}")
async def bot_config(bot_key: str,
                     x_internal_secret: str = Header(default="")) -> dict[str, Any]:
    """Everything needed to answer one inbound update on this bot."""
    _require_internal(x_internal_secret)
    async with session() as s:
        row = (await s.execute(
            select(GatewayBot).where(GatewayBot.bot_key == bot_key)
        )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown bot")
    return {
        "platform": row.platform,
        "owner_email": row.email,
        "token": _decrypt_internal(row),
        "webhook_secret": row.webhook_secret,
        "allowed_ids": row.allowed_ids or "",
        "owner_platform_user_id": row.owner_platform_user_id or "",
        "enabled": bool(row.enabled),
    }


@router.get("/bots")
async def bots_for_platform(platform: str,
                            x_internal_secret: str = Header(default="")
                            ) -> dict[str, Any]:
    """Every enabled connection on one platform, with its credentials.

    Telegram never needs this: an inbound webhook names its own bot_key, so the
    config is fetched one at a time on demand. Buzz has no inbound call at all,
    so webhook-handler has to be told which relays to hold open, and it asks
    here rather than being pushed at. Polling converges after a restart on
    either side; a push does not.

    A row whose token cannot be decrypted is skipped rather than failing the
    whole listing, or one user's rotated key would take every other user's
    connection down with it.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        rows = (await s.execute(
            select(GatewayBot).where(GatewayBot.platform == platform,
                                     GatewayBot.enabled.is_(True))
        )).scalars().all()

    out = []
    for row in rows:
        try:
            token = _decrypt_internal(row)
        except HTTPException:
            log.error("gateway: skipping %s, its token could not be read",
                      row.bot_key)
            continue
        # Slack needs both halves to run: the bot token sends and the
        # app-level token opens the websocket. Sent only when there is one, so
        # every other platform's payload is unchanged.
        app_token = ""
        if row.app_token_encrypted:
            try:
                app_token = gbots.decrypt_token(row.app_token_encrypted)
            except (InvalidToken, ValueError, RuntimeError):
                log.error("gateway: skipping %s, its app token could not be read",
                          row.bot_key)
                continue
        out.append({
            "bot_key": row.bot_key,
            "owner_email": row.email,
            "token": token,
            "app_token": app_token,
            "endpoint": row.endpoint or "",
            "allowed_ids": row.allowed_ids or "",
            "owner_platform_user_id": row.owner_platform_user_id or "",
        })
    return {"bots": out}


class BotStateIn(BaseModel):
    connected: bool
    error: str = Field(default="", max_length=300)


@router.post("/bots/{bot_key}/state")
async def bot_state(bot_key: str, body: BotStateIn,
                    x_internal_secret: str = Header(default="")) -> dict[str, bool]:
    """webhook-handler reporting whether a held-open connection is actually up.

    Without this the page can only say what was SAVED, never what is running,
    and a relay that has been refusing us for a day looks identical to one
    working perfectly. Telegram needs no equivalent: it reports failures by
    simply not calling us, which the user notices immediately.
    """
    _require_internal(x_internal_secret)
    async with session() as s:
        await s.execute(
            update(GatewayBot).where(GatewayBot.bot_key == bot_key)
            .values(last_error=(body.error or None) if not body.connected else None,
                    connected_at=_now() if body.connected else None))
        await s.commit()
    return {"ok": True}


@router.post("/bots/{bot_key}/claim")
async def bot_claim(bot_key: str, body: BotClaimIn,
                    x_internal_secret: str = Header(default="")) -> dict[str, bool]:
    """The first account to message a bot becomes the one it serves.

    Conditional on the column still being NULL, so two updates arriving
    together cannot race one another into overwriting the claim. Claiming does
    NOT link an IO account: that still needs a pairing code."""
    _require_internal(x_internal_secret)
    async with session() as s:
        result = await s.execute(
            update(GatewayBot)
            .where(GatewayBot.bot_key == bot_key,
                   GatewayBot.owner_platform_user_id.is_(None))
            .values(owner_platform_user_id=body.platform_user_id))
        await s.commit()
    return {"claimed": bool(result.rowcount)}
