"""Asking, once a day, whether each stored credential still works.

`connection_health` learns from the calls people are already making, which
costs nothing and is the right default. Its blind spot is the connector
nobody used this week: nothing asks, so the card keeps saying Connected.
Measured 2026-11-12, my own GitHub credential had been answering 401 for
days while the page said it was fine, and what found it was drilling it by
hand.

That module turned down one version of this and the reasoning still holds:
asking every vendor WHEN THE CONNECTIONS PAGE OPENS spends a request per app
per visit on a question that is almost always "still fine", and spends it
while somebody waits for a page. This is the other shape. Once a day, in the
background, nobody waiting, and it answers the question before it is asked
rather than after it has gone wrong in a chat.

WHY THE TYPED-URL GUARD HAD TO LAND FIRST. This makes requests nobody is
watching, so what those requests may reach had to be settled before it
existed: `host_guard` is that rule, and it refuses an address inside our own
network whether it was typed today or written into the database last month.

A SECOND THING IT BUYS, which was not the point but is worth knowing: it
goes through `secrets_for`, so it renews a token that is about to expire.
Airtable, Dropbox, HubSpot and Jira all issue refresh tokens that themselves
go stale if they are never used, and a connection nobody touches for two
months is exactly the one that would find out the hard way.

THE ONE RULE THAT KEEPS IT FROM EATING ITSELF. Every probe writes down that
we LOOKED, separately from what we learned. `connection_health.note`
deliberately writes nothing when an answer is not evidence about the
credential, 403 above all, because ClickUp answers a plan limit with one and
PR #182 was the cost of reading that as a dead token. So a row that relied
on `note` for its timestamp would still be due on the next tick, and the
next, and would be probed every tick for ever.

NOTHING HERE MAY RAISE. It runs in a background task where a traceback is
seen by nobody, and one person's revoked token must not stop everybody
else's connection from being checked. Each connection is wrapped on its own
and the tick is wrapped again around all of them, the same shape as
`email_poller`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("tasks.connection_sweep")

#: Ask about each connection about this often. Often enough that a dead
#: credential is found the day it dies; rare enough that fourteen
#: connectors across nine people is about a hundred requests a day.
INTERVAL_HOURS = 24

#: How often the tick runs. The work is spread across ticks rather than
#: done in one burst, so this is not the same as the interval above.
TICK_SECONDS = 1800

#: The most connections one tick will ask about. A platform with a thousand
#: connections must not become a thousand outbound requests in a minute.
MAX_PER_TICK = 25

#: Set to 0 to turn the whole thing off without a deploy.
ENABLED = os.environ.get("CONNECTION_SWEEP", "1") not in ("0", "false", "no")


def _as_aware(value) -> Optional[datetime]:
    """A timestamp we can compare, or None meaning "treat it as never".

    `checked_at` is `timestamptz` so asyncpg hands back an aware datetime,
    but comparing a naive one with an aware one raises TypeError, and in a
    background task that kills the loop rather than skipping a row.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def due(rows: Sequence[Dict], now: Optional[datetime] = None,
        interval_hours: int = INTERVAL_HOURS,
        cap: int = MAX_PER_TICK,
        known: Optional[Sequence[str]] = None) -> List[Tuple[str, str]]:
    """Which (email, provider) to ask about on this tick, in order.

    Never checked first, then longest since checked. A row whose provider
    this build does not have is dropped rather than raised on: a connector
    can be removed, and the rows for it outlive it.
    """
    if known is None:
        import connections as C
        known = tuple(C.PROVIDERS)
    known = set(known)

    at = now or datetime.now(timezone.utc)
    cutoff = at - timedelta(hours=interval_hours)

    ready = []
    for r in rows or ():
        provider = (r or {}).get("provider") or ""
        email = (r or {}).get("email") or ""
        if not email or provider not in known:
            continue
        last = _as_aware((r or {}).get("checked_at"))
        if last is not None and last > cutoff:
            continue
        # None sorts first, which is what we want: nothing is known about
        # those at all.
        ready.append((last is not None, last or at, email, provider))

    ready.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return [(e, p) for _known, _at, e, p in ready[:max(0, int(cap))]]


# --- the talking half -----------------------------------------------------
#
# Module-level seams, so the decisions above can be tested without a
# database, a vendor or a clock. The same pattern `app_regression` and the
# pollers use.

async def _rows() -> List[Dict]:
    """Every stored connection, with when it was last looked at."""
    import asyncpg
    conn = await asyncpg.connect(os.environ.get("DATABASE_URL", ""))
    try:
        got = await conn.fetch(
            "SELECT email, provider, checked_at FROM tasks.user_connections")
        return [dict(r) for r in got]
    finally:
        try:
            await conn.close()
        except Exception:                                   # noqa: BLE001
            pass


async def _secrets(email: str, provider: str) -> Dict[str, str]:
    import routes_connections as R
    return await R.secrets_for(email, provider)


async def _ask(email: str, provider: str, values: Dict[str, str]):
    """Ask the vendor who this credential belongs to.

    The same `_ask_vendor` the connect and the Test button use, with the
    email passed so `connection_health.note` records what the answer says.
    Deliberately not a second idea of what "is this credential real" means:
    a connection that passed the Test button and failed here would be
    unexplainable to the person holding it.
    """
    import connections as C
    import routes_connections as R
    provider_obj = C.PROVIDERS.get(provider)
    if provider_obj is None:
        return None
    ok, _label, _err = await R._ask_vendor(provider_obj, values, email)
    return ok


async def _looked(email: str, provider: str) -> None:
    import connection_health as H
    await H.looked(email, provider)


async def sweep_once(now: Optional[datetime] = None) -> Dict[str, int]:
    """One tick. Returns a small tally, and never raises."""
    tally = {"due": 0, "asked": 0, "skipped": 0, "failed": 0}
    try:
        rows = await _rows()
    except Exception as err:                                # noqa: BLE001
        logger.warning("connection sweep: could not read the connections (%s)",
                       type(err).__name__)
        return tally

    try:
        wanted = due(rows, now=now)
    except Exception as err:                                # noqa: BLE001
        logger.warning("connection sweep: could not choose (%s)",
                       type(err).__name__)
        return tally

    tally["due"] = len(wanted)
    for email, provider in wanted:
        try:
            values = await _secrets(email, provider)
            if values:
                await _ask(email, provider, values)
                tally["asked"] += 1
            else:
                # Nothing to ask with. Still stamped, or it is due again
                # on the next tick and every tick after it.
                tally["skipped"] += 1
            await _looked(email, provider)
        except Exception as err:                            # noqa: BLE001
            tally["failed"] += 1
            # Never the vendor's words and never the URL: Trello's
            # credential rides in its query string and an error echoes it.
            logger.warning("connection sweep: %s could not be checked (%s)",
                           provider, type(err).__name__)
    if tally["asked"] or tally["failed"]:
        logger.info("connection sweep: %s", tally)
    return tally


async def sweep_loop() -> None:
    """Forever, slowly. Wrapped twice: once per connection inside
    `sweep_once`, and once here, because a background task that dies takes
    every future check with it and says nothing."""
    if not ENABLED:
        logger.info("connection sweep: off (CONNECTION_SWEEP)")
        return
    # Nothing useful to do in the first seconds of a boot, and a restart
    # loop must not become a burst of vendor requests.
    await asyncio.sleep(90)
    while True:
        try:
            await sweep_once()
        except Exception as err:                            # noqa: BLE001
            logger.warning("connection sweep: tick failed (%s)",
                           type(err).__name__)
        await asyncio.sleep(TICK_SECONDS)
