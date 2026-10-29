"""The looking half of the email trigger (2026-10-29).

Once a minute: find every enabled email rule, ask Gmail as that rule's owner
for what has arrived since the rule last looked, and fire the rule on each
new message. `email_trigger.py` makes every decision; this does the talking
and the bookkeeping.

**Nothing here may raise.** A poller that dies takes every rule with it, and
it dies in a background task where nobody sees the traceback, so one
person's revoked token must not stop another person's rule. Every rule is
wrapped on its own, and the loop is wrapped again around all of them.

**The cursor is written even when nothing fired**, so `checked_at` proves the
rule is alive, and `last_error` says why it is not. A rule that has quietly
stopped looking is the failure mode worth making visible: it looks exactly
like a rule nobody has emailed.

It talks to mcp-gmail directly with `X-User-Email`, which is how every other
part of this service reaches a per-user connector (agent_tools does the
same). The api-gateway strips that header from anything arriving from
outside, so only internal callers can set it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text as sql_text

import automations
import email_trigger
from db import session

logger = logging.getLogger("email_poller")

GMAIL_URL = os.environ.get("GMAIL_URL", "http://mcp-gmail:8000")

#: One tick a minute, the same heartbeat the scheduler uses. A person who
#: needs faster than that has a webhook already.
TICK_SECONDS = 60

#: A slow mailbox must not hold the tick open behind every other rule.
SEARCH_TIMEOUT_SECONDS = 30

NOT_CONNECTED = "Google is not connected for this account."


# --- reading ------------------------------------------------------------------

async def _search(owner: str, query: str) -> list[dict]:
    """What Gmail returns for this query, as that person. Raises on failure,
    because the caller decides what a failure means for one rule.

    The error the gmail service reports for a disconnected account is a 200
    with an `error` key rather than a status code, so that is checked here
    and turned into something the caller can record.
    """
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SECONDS) as client:
        r = await client.post(
            GMAIL_URL.rstrip("/") + "/gmail_search_emails",
            headers={"X-User-Email": owner},
            json={"query": query, "max_results": email_trigger.FETCH})
    if r.status_code != 200:
        raise RuntimeError("gmail answered %d" % r.status_code)
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("gmail answered something that is not an object")
    if data.get("error"):
        # Almost always a revoked or never-made connection. Said in our own
        # words rather than the service's, which carries a connect URL
        # meant for a chat reply.
        raise RuntimeError(NOT_CONNECTED)
    emails = data.get("emails")
    return [e for e in emails if isinstance(e, dict)] if isinstance(emails, list) else []


# --- the cursor ----------------------------------------------------------------

async def _rules() -> list[dict]:
    """Every enabled email rule, with its owner and its cursor.

    One query across all owners, because the poller is not acting for
    anybody in particular. `created_at` is the cursor's starting point: a
    rule with no cursor row yet must begin at its own creation, never at
    zero, or it fires on the whole mailbox's history.
    """
    async with session() as s:
        rows = (await s.execute(sql_text(
            "SELECT a.id, a.user_email, a.name, a.agent_id, a.instructions, "
            "       a.trigger, a.trigger_query, a.deliver_to, a.hook_token, "
            "       COALESCE(c.after_epoch, "
            "                EXTRACT(EPOCH FROM a.created_at)::bigint) AS after_epoch, "
            "       COALESCE(c.seen_ids, '') AS seen_ids "
            "  FROM tasks.automation a "
            "  LEFT JOIN tasks.automation_email_cursor c ON c.automation_id = a.id "
            " WHERE a.trigger = :kind AND a.enabled = true"),
            {"kind": automations.TRIGGER_EMAIL})).mappings().all()
    return [dict(r) for r in rows]


async def _save_cursor(automation_id, owner: str, after_epoch: int,
                       seen_ids: list, error: str = "") -> None:
    """Where this rule has got to. Upsert, because the first tick of a rule
    is also the first time its row exists."""
    async with session() as s:
        await s.execute(sql_text(
            "INSERT INTO tasks.automation_email_cursor "
            "  (automation_id, user_email, after_epoch, seen_ids, checked_at, last_error) "
            "VALUES (:id, :owner, :after, :seen, now(), :err) "
            "ON CONFLICT (automation_id) DO UPDATE SET "
            "  after_epoch = EXCLUDED.after_epoch, "
            "  seen_ids = EXCLUDED.seen_ids, "
            "  checked_at = EXCLUDED.checked_at, "
            "  last_error = EXCLUDED.last_error"),
            {"id": automation_id, "owner": owner, "after": int(after_epoch),
             "seen": ",".join(seen_ids)[:16000], "err": error[:500]})
        await s.commit()


def _seen_list(raw) -> list:
    return [s for s in str(raw or "").split(",") if s]


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


# --- firing --------------------------------------------------------------------

async def _agent_name(owner: str, agent_id: str) -> str | None:
    """This rule's agent's name, or None if the agent is gone.

    None is not an error to log and move on from: a rule pointed at a
    deleted agent can never work again, and firing it would produce a
    failed run per email for ever.
    """
    # From where it lives, not from routes_automations, which only re-exports
    # it: importing it from there would drag that module's imports in behind
    # a function that has nothing to do with routing.
    from routes_agent_turn import _agents_for
    agents = await _agents_for(owner)
    agent = next((a for a in agents if a.get("id") == agent_id), None)
    return (agent or {}).get("name") or None


async def _fire(automation: dict, payload: dict, agent_name: str) -> None:
    import automation_runner
    await automation_runner.fire(automation, payload, agent_name)


#: Seams, so a test never needs a mailbox, an agent or a model.
_search_seam = _search
_rules_seam = _rules
_save_cursor_seam = _save_cursor
_agent_name_seam = _agent_name
_fire_seam = _fire


async def check_rule(rule: dict) -> dict:
    """Look once for one rule. Returns what happened, for the log and the
    tests. Never raises.

    The order matters and is the whole correctness of this function: read,
    decide, fire, and only then write the cursor. Writing it first would
    lose every message in the batch if the process died mid-fire; writing
    it last means at worst a message fires twice, and `seen_ids` is what
    makes even that not happen.
    """
    rid, owner = rule.get("id"), str(rule.get("user_email") or "")
    query = str(rule.get("trigger_query") or "")
    after = int(rule.get("after_epoch") or 0)
    seen = _seen_list(rule.get("seen_ids"))

    if after <= 0:
        # A second line of defence. The cursor is meant to start at the
        # rule's creation time (the COALESCE in _rules), and a zero here
        # would ask Gmail for the whole mailbox and fire an agent turn per
        # message in it. That is the one mistake in this file that spends
        # real money, so it is refused in code as well as in the query:
        # start from now and look properly on the next tick.
        logger.warning("email rule %s had no cursor; starting from now", rid)
        await _save_cursor_seam(rid, owner, int(_now_epoch()), seen, "")
        return {"fired": 0, "skipped": 0, "error": "no cursor"}

    if not owner or email_trigger.query_problem(query):
        # Refused at creation, so this is a rule from before the check or
        # one edited in the database by hand. Recorded rather than fired:
        # an empty query matches every email the person has.
        await _save_cursor_seam(rid, owner, after, seen,
                                "This rule does not say which emails to look for.")
        return {"fired": 0, "skipped": 0, "error": "no query"}

    try:
        found = await _search_seam(owner, email_trigger.search_query(query, after))
    except Exception as exc:                                # noqa: BLE001
        # The cursor does NOT move: nothing was read, so nothing has been
        # handled. checked_at still moves, so the page can tell a rule that
        # is failing from one nobody has emailed.
        logger.warning("email rule %s: could not read the mailbox", rid,
                       exc_info=not isinstance(exc, RuntimeError))
        await _save_cursor_seam(rid, owner, after, seen, str(exc))
        return {"fired": 0, "skipped": 0, "error": str(exc)}

    to_fire, skipped, cursor, now_seen = email_trigger.new_messages(found, seen, after)
    if not to_fire:
        await _save_cursor_seam(rid, owner, cursor, now_seen, "")
        return {"fired": 0, "skipped": skipped, "error": ""}

    name = await _agent_name_seam(owner, str(rule.get("agent_id") or ""))
    if name is None:
        # The cursor still advances. Otherwise every tick for ever would
        # re-read the same mail and record the same failure.
        await _save_cursor_seam(rid, owner, cursor, now_seen,
                                "This rule's agent no longer exists.")
        return {"fired": 0, "skipped": skipped, "error": "no agent"}

    fired = 0
    for message in to_fire:
        try:
            await _fire_seam(rule, email_trigger.payload_for(message), name)
            fired += 1
        except Exception:                                   # noqa: BLE001
            # fire() already swallows and records its own failures, so
            # reaching here means something further out broke. The rest of
            # the batch still runs: one bad message must not strand the
            # others behind it.
            logger.warning("email rule %s: firing on message %s failed",
                           rid, message.get("id"), exc_info=True)
    await _save_cursor_seam(rid, owner, cursor, now_seen, "")
    if skipped:
        logger.info("email rule %s: %d fired, %d skipped by the burst cap",
                    rid, fired, skipped)
    return {"fired": fired, "skipped": skipped, "error": ""}


async def tick_once() -> dict:
    """One pass over every enabled email rule. Never raises.

    Rules are taken one at a time rather than gathered. Each one can run
    agent turns with tools behind it, and this box has 3.8GB of RAM; the
    same reason a round of named agents in the main chat speaks in turn.
    """
    try:
        rules = await _rules_seam()
    except Exception:                                       # noqa: BLE001
        logger.warning("the email poller could not list its rules", exc_info=True)
        return {"rules": 0, "fired": 0}
    fired = 0
    for rule in rules:
        try:
            fired += (await check_rule(rule)).get("fired", 0)
        except Exception:                                   # noqa: BLE001
            # check_rule is already total; this is the belt to its braces,
            # because one person's rule must never stop everybody else's.
            logger.warning("email rule %s: the check itself failed",
                           rule.get("id"), exc_info=True)
    return {"rules": len(rules), "fired": fired}


async def email_poll_loop() -> None:
    """Wake once a minute, look, sleep. Runs forever."""
    logger.info("email_poll_loop started")
    while True:
        started = datetime.now(timezone.utc)
        try:
            out = await tick_once()
            if out.get("fired"):
                logger.info("email poller: fired %d of %d rules in %.1fs",
                            out["fired"], out["rules"],
                            (datetime.now(timezone.utc) - started).total_seconds())
        except Exception:                                   # noqa: BLE001
            logger.exception("the email poller tick failed")
        await asyncio.sleep(TICK_SECONDS)
