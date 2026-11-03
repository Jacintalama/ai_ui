"""The looking half of the Trello trigger (2026-11-03).

Once a minute: find every enabled Trello rule, ask Trello as that rule's
owner what is on the list it watches, and fire the rule on each card that
has changed since the rule last looked. `trello_trigger.py` makes every
decision; this does the talking and the bookkeeping.

Deliberately the same shape as `email_poller.py`, because that one has been
through a round of real failures already and every invariant in it was paid
for. The four that matter are the same here:

  A new rule starts at its creation time, never at zero, or it fires on
  every card the list has ever held.

  The look carries an overlap, because Trello stamps its own clock, and the
  marks on the cursor drop the duplicates that overlap produces.

  Five cards per rule per tick, oldest first, and the cursor still advances
  past the rest. A flood must not become fifty agent turns.

  A failed look does NOT move the cursor, because nothing was read and so
  nothing was handled. `checked_at` still moves, so a rule that has quietly
  stopped looking is distinguishable from one nobody has touched.

**Nothing here may raise.** A poller that dies takes every rule with it, and
it dies in a background task where nobody sees the traceback, so one
person's revoked Trello token must not stop another person's rule. Every
rule is wrapped on its own, and the loop is wrapped again around all of
them.

It calls Trello's REST API directly with the owner's own stored credential,
the same way `mytools.py` does, rather than going out through mcp-proxy and
back: the credential is already decryptable in this process and the extra
hop would only add a way to fail.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text as sql_text

import automations
import connections as C
import trello_trigger
from db import session

logger = logging.getLogger("trello_poller")

#: One tick a minute, the same heartbeat the scheduler and the email poller
#: use. Somebody who needs faster than that has a webhook already.
TICK_SECONDS = 60

#: A slow board must not hold the tick open behind every other rule.
READ_TIMEOUT_SECONDS = 20

NOT_CONNECTED = ("Trello is not connected for this account. Open "
                 "Connections and connect Trello.")
REJECTED = ("Your Trello connection was rejected. Reconnect it from "
            "Connections.")
GONE = ("That Trello list no longer exists, or this account can no longer "
        "see it.")


# --- reading ------------------------------------------------------------------

async def _secrets(owner: str) -> dict:
    """Seam over the only function that decrypts a stored credential, so a
    test never needs the database."""
    from routes_connections import secrets_for
    return await secrets_for(owner, "trello")


async def _cards(owner: str, list_id: str) -> list[dict]:
    """The cards on this list, as this person. Raises on failure, because
    the caller decides what a failure means for one rule.

    `fields` is named rather than left to default: a Trello card carries
    around forty of them, and this wants six. The request is smaller, and
    so is everything downstream of it.
    """
    creds = await _secrets(owner)
    if not creds:
        raise RuntimeError(NOT_CONNECTED)
    try:
        auth = C.vendor_auth("trello", creds)
    except ValueError:
        raise RuntimeError(REJECTED)

    params = dict(auth.params)
    params["fields"] = "name,url,due,desc,idList,idBoard,dateLastActivity"
    params["limit"] = trello_trigger.FETCH
    url = auth.base_url + "/lists/" + list_id + "/cards"
    try:
        async with httpx.AsyncClient(timeout=READ_TIMEOUT_SECONDS) as client:
            r = await client.get(url, headers=auth.headers, params=params)
    except Exception as exc:                                # noqa: BLE001
        # The exception text can carry the URL, and Trello's credential
        # rides in the query string. The type, never the message.
        logger.warning("trello poller: unreachable (%s)", type(exc).__name__)
        raise RuntimeError("Could not reach Trello just now.")

    if r.status_code in (401, 403):
        raise RuntimeError(REJECTED)
    if r.status_code == 404:
        raise RuntimeError(GONE)
    if r.status_code >= 400:
        # Never r.text: Trello echoes the request, credential included.
        raise RuntimeError("Trello answered %d" % r.status_code)
    try:
        data = r.json()
    except Exception:                                       # noqa: BLE001
        raise RuntimeError("Trello answered something that is not a list")
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


# --- the cursor ----------------------------------------------------------------

async def _rules() -> list[dict]:
    """Every enabled Trello rule, with its owner and its cursor.

    One query across all owners, because the poller is not acting for
    anybody in particular. `created_at` is the cursor's starting point: a
    rule with no cursor row yet must begin at its own creation, never at
    zero, or it fires on every card the list already holds.
    """
    async with session() as s:
        rows = (await s.execute(sql_text(
            "SELECT a.id, a.user_email, a.name, a.agent_id, a.instructions, "
            "       a.trigger, a.trigger_query, a.deliver_to, a.hook_token, "
            "       COALESCE(c.after_epoch, "
            "                EXTRACT(EPOCH FROM a.created_at)::bigint) AS after_epoch, "
            "       COALESCE(c.seen_marks, '') AS seen_marks "
            "  FROM tasks.automation a "
            "  LEFT JOIN tasks.automation_trello_cursor c ON c.automation_id = a.id "
            " WHERE a.trigger = :kind AND a.enabled = true"),
            {"kind": automations.TRIGGER_TRELLO})).mappings().all()
    return [dict(r) for r in rows]


async def _save_cursor(automation_id, owner: str, after_epoch: int,
                       seen_marks: list, error: str = "") -> None:
    """Where this rule has got to. Upsert, because the first tick of a rule
    is also the first time its row exists."""
    async with session() as s:
        await s.execute(sql_text(
            "INSERT INTO tasks.automation_trello_cursor "
            "  (automation_id, user_email, after_epoch, seen_marks, checked_at, last_error) "
            "VALUES (:id, :owner, :after, :seen, now(), :err) "
            "ON CONFLICT (automation_id) DO UPDATE SET "
            "  after_epoch = EXCLUDED.after_epoch, "
            "  seen_marks = EXCLUDED.seen_marks, "
            "  checked_at = EXCLUDED.checked_at, "
            "  last_error = EXCLUDED.last_error"),
            {"id": automation_id, "owner": owner, "after": int(after_epoch),
             "seen": ",".join(seen_marks)[:16000], "err": error[:500]})
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
    failed run per card for ever.
    """
    from routes_agent_turn import _agents_for
    agents = await _agents_for(owner)
    agent = next((a for a in agents if a.get("id") == agent_id), None)
    return (agent or {}).get("name") or None


async def _fire(automation: dict, payload: dict, agent_name: str) -> None:
    import automation_runner
    await automation_runner.fire(automation, payload, agent_name)


#: Seams, so a test never needs a board, an agent or a model.
_cards_seam = _cards
_rules_seam = _rules
_save_cursor_seam = _save_cursor
_agent_name_seam = _agent_name
_fire_seam = _fire


async def _record_skipped(automation: dict, skipped: int, cap: int) -> None:
    import automation_runner
    await automation_runner.record_skipped(automation, skipped, cap)


_record_skipped_seam = _record_skipped


async def check_rule(rule: dict) -> dict:
    """Look once for one rule. Returns what happened, for the log and the
    tests. Never raises.

    The order matters and is the whole correctness of this function: read,
    decide, fire, and only then write the cursor. Writing it first would
    lose every card in the batch if the process died mid-fire; writing it
    last means at worst a card fires twice, and the marks are what make even
    that not happen.
    """
    rid, owner = rule.get("id"), str(rule.get("user_email") or "")
    list_id = str(rule.get("trigger_query") or "").strip()
    after = int(rule.get("after_epoch") or 0)
    seen = _seen_list(rule.get("seen_marks"))

    if after <= 0:
        # A second line of defence. The cursor is meant to start at the
        # rule's creation time (the COALESCE in _rules), and a zero here
        # would treat every card on the list as new and fire an agent turn
        # per card. That is the one mistake in this file that spends real
        # money, so it is refused in code as well as in the query: start
        # from now and look properly on the next tick.
        logger.warning("trello rule %s had no cursor; starting from now", rid)
        await _save_cursor_seam(rid, owner, _now_epoch(), seen, "")
        return {"fired": 0, "skipped": 0, "error": "no cursor"}

    if not owner or trello_trigger.list_problem(list_id):
        # Refused at creation, so this is a rule from before the check or
        # one edited in the database by hand.
        await _save_cursor_seam(rid, owner, after, seen,
                                "This rule does not say which list to watch.")
        return {"fired": 0, "skipped": 0, "error": "no list"}

    try:
        found = await _cards_seam(owner, list_id)
    except Exception as exc:                                # noqa: BLE001
        # The cursor does NOT move: nothing was read, so nothing has been
        # handled. checked_at still moves, so the page can tell a rule that
        # is failing from one nobody has touched.
        logger.warning("trello rule %s: could not read the list", rid,
                       exc_info=not isinstance(exc, RuntimeError))
        await _save_cursor_seam(rid, owner, after, seen, str(exc))
        return {"fired": 0, "skipped": 0, "error": str(exc)}

    to_fire, skipped, cursor, now_seen = trello_trigger.new_cards(
        found, seen, after)
    if not to_fire:
        await _save_cursor_seam(rid, owner, cursor, now_seen, "")
        return {"fired": 0, "skipped": skipped, "error": ""}

    name = await _agent_name_seam(owner, str(rule.get("agent_id") or ""))
    if name is None:
        # The cursor still advances. Otherwise every tick for ever would
        # re-read the same cards and record the same failure.
        await _save_cursor_seam(rid, owner, cursor, now_seen,
                                "This rule's agent no longer exists.")
        return {"fired": 0, "skipped": skipped, "error": "no agent"}

    fired = 0
    for card in to_fire:
        try:
            await _fire_seam(rule, trello_trigger.payload_for(card), name)
            fired += 1
        except Exception:                                   # noqa: BLE001
            # fire() already swallows and records its own failures, so
            # reaching here means something further out broke. The rest of
            # the batch still runs: one bad card must not strand the others
            # behind it.
            logger.warning("trello rule %s: firing on card %s failed",
                           rid, card.get("id"), exc_info=True)
    await _save_cursor_seam(rid, owner, cursor, now_seen, "")
    if skipped:
        # Written down, not only logged. The cursor has moved past these
        # and they will never fire, so a log line on the server is the one
        # place the person who was flooded cannot look.
        await _record_skipped_seam(rule, skipped, trello_trigger.BURST)
        logger.info("trello rule %s: %d fired, %d skipped by the burst cap",
                    rid, fired, skipped)
    return {"fired": fired, "skipped": skipped, "error": ""}


async def tick_once() -> dict:
    """One pass over every enabled Trello rule. Never raises.

    Rules are taken one at a time rather than gathered. Each one can run
    agent turns with tools behind it, and this box has 3.8GB of RAM.
    """
    try:
        rules = await _rules_seam()
    except Exception:                                       # noqa: BLE001
        logger.warning("the trello poller could not list its rules",
                       exc_info=True)
        return {"rules": 0, "fired": 0}
    fired = 0
    for rule in rules:
        try:
            fired += (await check_rule(rule)).get("fired", 0)
        except Exception:                                   # noqa: BLE001
            # check_rule is already total; this is the belt to its braces,
            # because one person's rule must never stop everybody else's.
            logger.warning("trello rule %s: the check itself failed",
                           rule.get("id"), exc_info=True)
    return {"rules": len(rules), "fired": fired}


async def trello_poll_loop() -> None:
    """Wake once a minute, look, sleep. Runs forever."""
    logger.info("trello_poll_loop started")
    while True:
        started = datetime.now(timezone.utc)
        try:
            out = await tick_once()
            if out.get("fired"):
                logger.info("trello poller: fired %d of %d rules in %.1fs",
                            out["fired"], out["rules"],
                            (datetime.now(timezone.utc) - started).total_seconds())
        except Exception:                                   # noqa: BLE001
            logger.exception("the trello poller tick failed")
        await asyncio.sleep(TICK_SECONDS)
