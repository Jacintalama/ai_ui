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
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update

import gateway_bots as gbots
import gateway_pairing as gp
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
BOT_CAPABLE_PLATFORMS = {"telegram"}


def _public_url() -> str:
    """Where Telegram should deliver. Seam so tests need no env."""
    return os.environ.get("GATEWAY_PUBLIC_URL", "").rstrip("/")


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
     "blurb": "Chat with IO from Telegram direct messages, including voice memos."},
    # "any shell" was true and unhelpful: someone on a phone read it, tried,
    # and had nowhere to type. Naming the machines it needs is shorter than
    # the support conversation that follows when it does not.
    {"platform": "cli", "label": "Terminal", "icon": "⌨️",
     "blurb": "Talk to IO from a shell on Mac, Windows or Linux. "
              "One script, nothing to install but Python. Not phones."},

    # Code already exists in this platform, but not behind the gateway yet.
    {"platform": "slack", "label": "Slack", "icon": "💬",
     "blurb": "Use IO from Slack direct messages.",
     "planned": "Slack already talks to IO, but not yet through Channels."},
    {"platform": "discord", "label": "Discord", "icon": "🎮",
     "blurb": "Use IO from Discord direct messages.",
     "planned": "Discord already talks to IO, but not yet through Channels."},

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
    {"platform": "email", "label": "Email", "icon": "✉️",
     "blurb": "Send IO an email and get a reply.",
     "planned": "Not started. The Gmail connector already exists to build on."},
    {"platform": "teams", "label": "Microsoft Teams", "icon": "👥",
     "blurb": "Use IO from Teams chats.",
     "planned": "Not started. Microsoft sign-in already exists to build on."},

    # The only channel here blocked by the OTHER side rather than by us. Every
    # entry above has a documented bot or webhook API we simply have not built
    # against; buzz.xyz is in early access and publishes none, so there is
    # nothing to write an adapter for yet.
    {"platform": "buzz", "label": "Buzz", "icon": "🐝",
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

    bot = row.get("bot")
    if bot and bot.get("enabled"):
        handle = (bot.get("bot_username") or "").strip()
        named = f"Your bot @{handle}" if handle else "Your own bot"
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
        return {"via": "offer", "via_label": "bring your own bot"}

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
           "bot": None,
           # Who else handles your messages on this channel. Empty for the
           # ones that relay through nobody.
           "caveat": entry.get("caveat", ""),
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
        # Buzz publishes no API, so this contract is one we wrote and handed
        # them; see docs/runbooks/buzz-integration.md. The flag is read by
        # BOTH services on purpose. webhook-handler holds the shared secret
        # and serves the endpoint; this service only renders the row, and
        # setting the flag on one of them is exactly how the terminal channel
        # ended up live while the page called it switched off.
        if os.environ.get("BUZZ_ENABLED", "").strip():
            return {**row, "status": "available",
                    "note": "Message IO from Buzz and it will reply with a code."}
        return {**row, "status": "off",
                "note": "Buzz is not connected to this server yet."}

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
    token: str = Field(min_length=1, max_length=200)
    allowed_ids: str = Field(default="", max_length=500)


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
    if not token:
        raise HTTPException(status_code=400, detail="Paste your bot token.")

    try:
        identity = await telegram_api.get_me(token)
    except telegram_api.TelegramError as exc:
        raise HTTPException(status_code=400,
                            detail=f"Telegram said: {exc.description}")

    bot_key = gbots.new_bot_key()
    secret = gbots.new_webhook_secret()

    try:
        encrypted = gbots.encrypt_token(token)
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
            token_encrypted=encrypted, webhook_secret=secret,
            bot_username=identity.get("username", ""),
            allowed_ids=gbots.parse_allowed_ids(body.allowed_ids),
            enabled=True, last_error=None,
        )
        s.add(row)
        await s.commit()

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
                "bot_username": identity.get("username", ""),
                "token_hint": gbots.mask_token(token),
                "enabled": False, "allowed_ids": gbots.parse_allowed_ids(body.allowed_ids),
                "last_error": exc.description}

    log.info("gateway: %s saved their own %s bot", user.email, platform)
    return {"bot_key": bot_key, "platform": platform,
            "bot_username": identity.get("username", ""),
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
    """Off deletes the webhook, so Telegram stops delivering at source rather
    than us dropping updates we keep receiving."""
    async with session() as s:
        row = await _owned_bot(s, user.email, bot_key)
        token = _decrypt_or_503(row)
        secret = row.webhook_secret

    error = ""
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
        try:
            token = gbots.decrypt_token(row.token_encrypted)
        except (InvalidToken, ValueError, RuntimeError) as exc:
            # A token we cannot decrypt is one we cannot call deleteWebhook
            # with either. That must not block removal: the row disappearing
            # is what the user asked for, and an orphaned webhook 404s once
            # bot_key no longer resolves, same as any other undeleted hook
            # below.
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
