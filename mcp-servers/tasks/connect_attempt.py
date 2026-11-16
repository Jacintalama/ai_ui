"""Every attempt to connect an app, and how far it got.

Measured 2026-11-16: nine people are on this platform and ONE has ever
connected anything. Asked whether the other eight ever TRIED, the honest
answer was that we cannot know. Every failure path in the OAuth callback was
a `logger.warning` and nothing more, and a container log begins at the last
deploy: 41,651 lines starting Friday 14:10 UTC, zero of them about oauth. We
deploy several times a day, so each deploy destroyed the only record there
was.

Two situations therefore looked identical, and they call for opposite
responses:

    nobody wants connectors
    connectors are broken for everybody who is not Ralph

A row per attempt tells them apart, and keeps telling them apart after the
next rebuild.

WHAT THIS DELIBERATELY DOES NOT STORE, and the reason is already written on
migration 068: not one word the vendor said. Vendors echo the request back
in their errors, and Trello's credential rides in its query string, so a
free-text column here would be a credential store with extra steps. So the
row holds a stage from a CLOSED SET WE CHOSE and an integer HTTP status, and
`clean` refuses anything else rather than trusting each call site to be
careful. An invented stage is how a sentence gets in: "github said: Bad
credentials {...}" is a perfectly good stage name as far as a text column is
concerned.

The status is kept because it is the difference between a dead credential
(401), a plan limit (403) and the vendor having a bad minute (5xx), and
those three need different answers from us. It is an integer or it is
nothing.

Failing open, like every other post-step in this service: nobody loses a
connection they completed because we could not write a log row about it.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

#: The one stage that means the person now has a working connection. There is
#: exactly one on purpose: "did anybody get through" must not be a judgement
#: made at read time.
OK_STAGE = "connected"

#: Every stage an attempt can reach, in the order it would reach them. A
#: stage not in here cannot be written, and a stage in here that nothing
#: writes is caught by a test, because a stage nothing records will never
#: explain anything.
STAGES = frozenset({
    "started",                 # we sent them to the vendor
    "declined",                # cancelled, or the vendor refused the request
    "state_bad",               # came back with a state we cannot verify
    "no_code",                 # came back approved with nothing to exchange
    "verifier_missing",        # PKCE verifier gone, so the exchange cannot run
    "exchange_unreachable",    # we could not reach the vendor's token endpoint
    "exchange_refused",        # the vendor refused the exchange (status kept)
    "token_unusable",          # a 200 whose body held no usable token
    "probe_unreachable",       # approved, then a call we needed went nowhere
    "token_rejected",          # approved, but the token did not work for us
    "no_install",              # GitHub: authorised with no installation
    "no_site",                 # Jira: a token that reaches no site
    "store_failed",            # it worked and we could not save it
    OK_STAGE,
})

#: `declined` earns its place over "they pressed cancel": the vendor also
#: lands here when OUR authorize URL is wrong, and `invalid_scope` across
#: several people is a bug of ours that currently looks like shyness.

_STATUS_FLOOR, _STATUS_CEILING = 100, 599


def ok(stage: str) -> bool:
    """Did this attempt end with a working connection."""
    return stage == OK_STAGE


def _status(value: Any) -> Optional[int]:
    """An HTTP status code, or nothing at all.

    `bool` is excluded before `int` because `isinstance(True, int)` is True
    and `True` is not a status code. A float is not one either, and neither
    is the vendor's error body, which is the thing most likely to be handed
    in by mistake.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.strip().isdigit():
        code = int(value.strip())
    else:
        return None
    return code if _STATUS_FLOOR <= code <= _STATUS_CEILING else None


def clean(stage: Any, status: Any = None) -> Tuple[str, Optional[int]]:
    """The whole safety decision, pure, so it can be tested without a table.

    Raises on a stage we did not choose. That is deliberately louder than
    dropping it: a call site passing free text should fail its own test,
    not write a quiet row nobody can read.
    """
    if not isinstance(stage, str) or stage not in STAGES:
        raise ValueError("unknown connect stage: %r" % (stage,))
    return stage, _status(status)


async def _write(email: str, provider: str, stage: str,
                 status: Optional[int]) -> None:
    """The only place a row is written. A seam, so the tests above never
    need a database to prove what does and does not reach one."""
    import asyncpg
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO tasks.connect_attempt "
            "(email, provider, stage, http_status) VALUES ($1, $2, $3, $4)",
            email or "", provider or "", stage, status)
    finally:
        await conn.close()


async def record(email: str, provider: str, stage: str,
                 status: Any = None) -> None:
    """Write down that somebody tried, and how far they got.

    Never raises. A connect that completed must not be undone by a failed
    log write, and a connect that failed must not fail twice.
    """
    try:
        safe_stage, safe_status = clean(stage, status)
    except ValueError:
        logger.warning("connect_attempt: refused an unknown stage for %s; "
                       "nothing recorded", provider)
        return
    try:
        await _write(email, provider, safe_stage, safe_status)
    except Exception:                                       # noqa: BLE001
        logger.warning("connect_attempt: could not record a %s attempt at "
                       "stage %s", provider, safe_stage, exc_info=True)


async def recent(limit: int = 500) -> List[Dict[str, Any]]:
    """The attempts, newest first. Fails open to an empty list, which
    `summary` reports as "nobody tried" rather than as an error, so the
    caller must not read an empty answer as proof of anything."""
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            rows = await conn.fetch(
                "SELECT email, provider, stage, http_status, at "
                "FROM tasks.connect_attempt ORDER BY at DESC LIMIT $1",
                max(1, int(limit)))
        finally:
            await conn.close()
        return [dict(r) for r in rows]
    except Exception:                                       # noqa: BLE001
        logger.warning("connect_attempt: could not read the attempts",
                       exc_info=True)
        return []


def summary(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The answer to the question this table exists for.

    Pure, and tolerant of a stage it has never heard of, because it reads
    rows written by call sites that may be newer than it is. Anything that
    is not the one success stage counts as a failure, which is the safe
    direction: it can under-report success and never invent it.
    """
    by_provider: Dict[str, Dict[str, int]] = {}
    got_through = set()
    attempts = 0
    for row in rows:
        attempts += 1
        row = row if isinstance(row, dict) else {}
        provider = str(row.get("provider") or "unknown")
        seen = by_provider.setdefault(provider, {"attempts": 0,
                                                 "connected": 0, "failed": 0})
        seen["attempts"] += 1
        if ok(row.get("stage")):
            seen["connected"] += 1
            got_through.add(str(row.get("email") or ""))
        else:
            seen["failed"] += 1
    return {"attempts": attempts,
            "people_who_got_through": len(got_through),
            "by_provider": by_provider}
