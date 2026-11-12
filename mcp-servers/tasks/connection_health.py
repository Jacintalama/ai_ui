"""Whether a stored credential still works, learned from real calls.

A card said Connected for as long as a credential was STORED. Connecting
proved it once and nothing proved it again, so a revoked token left the
card reading Connected until some tool call failed in a chat, which is the
worst place to find out. Measured on 2026-11-12: my own GitHub credential
had been answering 401 for days while the page showed it connected.

The obvious fix is to ask every vendor when the Connections page opens.
That spends a request per app per visit to answer a question that is
almost always "still fine", and spends it at the moment somebody is
waiting for a page.

This is the cheaper and the more accurate answer: the calls are already
being made. A tool call IS the question, asked in earnest, and `_refusal`
already reads the vendor's answer. So nothing here makes a request of its
own. It writes down what the real ones came back with.

THREE THINGS THIS MODULE REFUSES TO DO, each of which has already cost
something once:

  - It never treats a 403 as a dead credential. That is the rule PR #182
    paid for: ClickUp answers a plan limit with 403 and the old code told
    Ralph to reconnect a credential that had just read his whole
    workspace. A flag set on a 403 would call a working connection broken,
    permanently, over a paywall.
  - It never stores a word the vendor said. The row holds a boolean and a
    time. Vendors echo the request in their errors and Trello's credential
    rides in its query string, so the sentence shown to a person is
    composed from the app's NAME instead.
  - It never raises. This is bookkeeping alongside somebody's real
    request, and it is not worth failing that request for.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger("tasks.connection_health")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

#: What was last written for each (email, provider), so a composite tool
#: making five calls of its own does not become five identical updates.
#: Only ever holds a verdict a write actually succeeded with, because a
#: memo of a failed write is a flag that never lands.
_SAID: Dict[Tuple[str, str], bool] = {}


async def _connect():
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


def verdict(status_code) -> Optional[bool]:
    """True the credential works, False it is rejected, None we learned nothing.

    Pure, and the whole decision. Everything else here is plumbing.
    """
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        return None
    if status_code == 401:
        # "We do not know who you are." The only answer that means this.
        return False
    if 200 <= status_code < 400:
        return True
    # 403 lands here on purpose, with the 4xx and 5xx that follow it: a
    # permission, a quota, a paywall, a wrong path, or a vendor having a
    # bad minute. None of them is evidence about the credential.
    return None


def forget(email: str, provider: str) -> None:
    """Drop what we remember about one connection.

    Called when a credential is REPLACED. The connect proved the new one
    against the vendor before storing it, and a memo left over from the
    old one would suppress the write that says so.
    """
    _SAID.pop((email or "", provider or ""), None)


def forget_all() -> None:
    _SAID.clear()


async def note(email: str, provider: str, status_code) -> None:
    """Write down what this answer says about the credential, if anything."""
    says = verdict(status_code)
    if says is None:
        return

    key = (email or "", provider or "")
    if _SAID.get(key) is says:
        return

    try:
        conn = await _connect()
    except Exception as err:                                # noqa: BLE001
        logger.warning("health: could not reach the database (%s)",
                       type(err).__name__)
        return

    try:
        await conn.execute(
            """
            UPDATE tasks.user_connections
               SET check_ok = $1, checked_at = now()
             WHERE email = $2 AND provider = $3
            """,
            says, email, provider)
    except Exception as err:                                # noqa: BLE001
        # Not remembered, so the next call tries again rather than the
        # memo swallowing every retry.
        logger.warning("health: could not record %s (%s)", provider,
                       type(err).__name__)
        return
    finally:
        try:
            await conn.close()
        except Exception:                                   # noqa: BLE001
            pass

    _SAID[key] = says


async def rejected(email: str) -> set:
    """The providers whose credential was rejected the last time it was
    used, as a set of provider ids.

    The read side of `note`. `check_ok` is nullable with no default, so
    three states live in that column: true means a call worked, false
    means a call came back 401, and NULL means nothing has been learned
    about it yet. Only false is reported here. NULL must never read as
    broken, because it is every connection nobody has used since the
    column existed.

    Fails toward "nothing is rejected", the opposite way round to the
    write: telling somebody to reconnect a credential that works is the
    PR #182 mistake in another costume, and here there is no vendor
    answer to correct it with.
    """
    try:
        conn = await _connect()
    except Exception as err:                                # noqa: BLE001
        logger.warning("health: could not reach the database (%s)",
                       type(err).__name__)
        return set()
    try:
        rows = await conn.fetch(
            """
            SELECT provider
              FROM tasks.user_connections
             WHERE email = $1 AND check_ok IS FALSE
            """,
            email)
    except Exception as err:                                # noqa: BLE001
        logger.warning("health: could not read what is rejected (%s)",
                       type(err).__name__)
        return set()
    finally:
        try:
            await conn.close()
        except Exception:                                   # noqa: BLE001
            pass
    return {r["provider"] for r in rows}
