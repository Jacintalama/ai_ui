"""When a new email should start an automation (2026-10-29).

All the decisions a poller has to make, with no I/O in any of them, because
every one of them is a way to spend somebody's money or lose their mail:

- what to ask Gmail for, built from what the person ticked
- which of the answers are actually new
- how many of them may run at once
- where the cursor moves to afterwards

`email_poller.py` does the talking; this does the thinking, and is therefore
the part that can be tested without a mailbox.

The payload a rule fires on is the message METADATA, not the body. The agent
has the Gmail tool and can read the message itself if it needs more, which is
cheaper than hauling every body through a poller and is how the rest of the
platform divides that work.
"""
from __future__ import annotations

import re

#: Seconds of overlap on every query. Gmail's `after:` compares against its
#: own clock, not ours, and is inclusive, so a message landing in the same
#: second as the cursor can fall on either side of it. Asking for a little
#: more than we need and dropping what we have already seen costs one
#: duplicate row in a query; the other direction loses somebody's email.
OVERLAP_SECONDS = 120

#: Message ids remembered per rule. Has to comfortably exceed what one
#: OVERLAP_SECONDS window can hold, or the overlap would re-fire mail. Two
#: minutes of a very busy mailbox is nothing like 200 messages.
SEEN_KEPT = 200

#: Messages one rule may fire on in one tick, oldest first. A flood must not
#: queue fifty agent turns: the App Builder has already been stopped dead by
#: a 402 from OpenRouter once, and a per-email trigger is exactly the shape
#: that does that again. The cursor still advances past the rest, and the
#: skipped count is recorded so the person can see it happened.
BURST = 5

#: Gmail's own ceiling on a search is 50, and asking for more than we could
#: ever fire on wastes a round trip.
FETCH = 25


def compose_query(from_address: str = "", subject: str = "",
                  unread_only: bool = False, advanced: str = "") -> str:
    """The Gmail query for what the person ticked.

    `advanced` wins outright: somebody who typed Gmail syntax meant it, and
    silently ANDing boxes onto it would quietly change what they wrote.

    Matching is deliberately Gmail's job. Reimplementing from/subject/label
    here would be a worse version of something it already does well, and
    would drift from it the first time either side changed.
    """
    if advanced.strip():
        return " ".join(advanced.split())
    parts = []
    if from_address.strip():
        parts.append("from:%s" % from_address.strip())
    if subject.strip():
        # Quoted, or a subject with a space becomes two unrelated terms and
        # the rule matches far more than the person asked for.
        parts.append('subject:"%s"' % subject.strip().replace('"', ""))
    if unread_only:
        parts.append("is:unread")
    return " ".join(parts)


def query_problem(query: str) -> str:
    """Why this query cannot be used, or "".

    An empty query matches EVERY email, and this trigger runs an agent per
    message, so an empty one is a bill rather than a rule. Refused at the
    door instead of being discovered on the first tick.
    """
    if not query.strip():
        return ("Say which emails should start it: who it is from, what the "
                "subject contains, or a Gmail search of your own.")
    if "after:" in query or "before:" in query:
        # The poller owns the time window. A hand-written one would fight
        # the cursor and either re-fire old mail or never fire at all.
        return ("Leave the dates out: it already only looks at email that "
                "arrived since it last checked.")
    return ""


def search_query(query: str, after_epoch: int) -> str:
    """What to actually send Gmail: the rule's query, plus the window.

    `after:` takes a unix timestamp and is inclusive, hence the overlap. The
    floor at 0 is not paranoia about negative time, it is that a rule created
    within two minutes of the epoch would otherwise ask for `after:-1`, which
    Gmail rejects, and a rejected query is a rule that never fires.
    """
    since = max(0, int(after_epoch) - OVERLAP_SECONDS)
    return "%s after:%d" % (query.strip(), since)


def _epoch_of(email: dict) -> int:
    """Gmail's own timestamp for a message, in seconds.

    `internal_date` is milliseconds and is set by Gmail. The `date` header is
    written by the SENDER and is routinely wrong, absent, or in a format
    nobody agreed on, so it is not usable as a cursor. A message with no
    internal date sorts as 0, which puts it first and gets it fired rather
    than silently dropped.
    """
    raw = email.get("internal_date")
    try:
        return int(raw) // 1000
    except (TypeError, ValueError):
        return 0


def new_messages(emails, seen_ids, after_epoch: int):
    """(to_fire, skipped, cursor, seen) for one tick.

    `to_fire` is oldest first, so a thread of three emails reaches the agent
    in the order it was written rather than backwards.

    `skipped` is how many were dropped by the burst cap. The cursor still
    moves past them: holding it back would make the same flood arrive again
    on the next tick, for ever.

    The cursor only ever moves FORWARD, and never past a message that was
    not accounted for, so a tick that fires nothing leaves it where it was.
    """
    seen = [s for s in (seen_ids or []) if isinstance(s, str) and s]
    known = set(seen)
    fresh = []
    for e in (emails or []):
        if not isinstance(e, dict):
            continue
        mid = e.get("id")
        if not isinstance(mid, str) or not mid or mid in known:
            continue
        known.add(mid)              # a duplicate inside one page, too
        fresh.append(e)
    fresh.sort(key=_epoch_of)

    to_fire = fresh[:BURST]
    skipped = fresh[BURST:]
    accounted = to_fire + skipped
    cursor = int(after_epoch)
    for e in accounted:
        cursor = max(cursor, _epoch_of(e))
    # Newest first, so the cap keeps what the overlap might show us again.
    ids = [e["id"] for e in reversed(accounted)]
    return to_fire, len(skipped), cursor, (ids + seen)[:SEEN_KEPT]


_WS = re.compile(r"\s+")


def payload_for(email: dict) -> dict:
    """What the agent is told about one email.

    Flat and named, because `automations.message_for` puts this under a line
    saying it is data: an agent reading "from" and "subject" can act on it,
    where a raw Gmail API message would make it guess at nesting.

    The id and thread id are included so the agent can read the full message
    or reply to the right thread with its own Gmail tool.
    """
    return {
        "id": str(email.get("id") or ""),
        "thread_id": str(email.get("thread_id") or ""),
        "from": _WS.sub(" ", str(email.get("from") or "")).strip(),
        "subject": _WS.sub(" ", str(email.get("subject") or "")).strip(),
        "date": str(email.get("date") or ""),
        "snippet": _WS.sub(" ", str(email.get("snippet") or "")).strip(),
    }
