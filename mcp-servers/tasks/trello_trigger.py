"""When something on a Trello list should start an automation (2026-11-03).

Every decision a poller has to make, with no I/O in any of them, because
each one is a way to spend somebody's money or miss the thing they were
watching for:

- which list a rule may watch
- which of the cards on it are actually new
- how many of them may run at once
- where the cursor moves to afterwards

`trello_poller.py` does the talking; this does the thinking, and is
therefore the part that can be tested without a board.

**Why a list and not a board.** A list is the unit people name: Incoming,
Review, Done. "When a card lands in Review" is a sentence somebody says,
where "when anything changes on the board" is not a rule so much as a
firehose, and reading it would mean the actions API and a page of events
per card. One list is one cheap call that returns exactly the cards and
their last activity.

**What counts as something happening.** A card whose `dateLastActivity` is
newer than the cursor: it was created here, moved here, or edited while it
sat here. Trello does not say, in the cards call, which of those it was.
Rather than guess, the rule is described to the person as what it actually
is, and the agent is handed the card and can look further with the Trello
tools it already has. The alternative is one actions call per card per
tick, to label an event that the agent mostly does not need labelled.

**Why the mark is id AND time.** An email can only arrive once, so its id
is enough to know it has been handled. A card is a thing that keeps
changing, so the id alone would fire once and then never again however
much happened to it. `id@epoch` fires once per change and never twice for
the same one.
"""
from __future__ import annotations

from datetime import datetime, timezone

#: Seconds of overlap on every look. Trello stamps `dateLastActivity` with
#: its own clock, not ours, so a card changing in the same second as the
#: cursor can fall on either side of it. Looking a little further back and
#: dropping what we have already acted on costs nothing; the other
#: direction silently loses the card somebody was waiting for.
OVERLAP_SECONDS = 120

#: Card marks remembered per rule. Has to comfortably exceed what one
#: OVERLAP_SECONDS window can hold. Two minutes of even a busy list is
#: nothing like 200 changes.
SEEN_KEPT = 200

#: Cards one rule may fire on in one tick, oldest first. Somebody dragging
#: twenty cards into Review at once must not become twenty agent turns: the
#: App Builder has been stopped dead by a 402 from OpenRouter before, and a
#: per-card trigger is exactly the shape that does it again. The cursor
#: still advances past the rest and the skipped count is recorded, so a
#: person can see it happened.
BURST = 5

#: Cards asked for in one look. A list with more than this in it has more
#: going on than a per-card trigger should be driving, and the cap keeps one
#: enormous list from holding the tick open for every other rule.
FETCH = 50

#: How much of a card's own description the agent is handed. The rest is one
#: tool call away, and a card with an essay on it must not push the rule's
#: own instructions out of the turn.
MAX_DESC_CHARS = 800

#: A Trello id is 24 hex characters. Checked before it is spent, so a rule
#: cannot be saved pointing at something that was never an id.
ID_LENGTH = 24


def looks_like_id(value) -> bool:
    v = str(value or "").strip()
    return (len(v) == ID_LENGTH
            and all(c in "0123456789abcdefABCDEF" for c in v))


def list_problem(list_id) -> str:
    """Why this rule cannot watch this, or "".

    Refused at the door rather than discovered on the first tick, which is
    the same reason an empty Gmail query is refused: a rule that cannot
    work should not be saveable, because a rule that quietly never fires is
    indistinguishable from one nobody has triggered.
    """
    raw = str(list_id or "").strip()
    if not raw:
        return "Choose the Trello list to watch."
    if not looks_like_id(raw):
        return ("That is not a Trello list. Pick one from the list of your "
                "boards.")
    return ""


def _epoch_of(card: dict) -> int:
    """Trello's own timestamp for the card's last activity, in seconds.

    Trello's, never anything a person typed: a due date is set by whoever
    made the card and says nothing about when it changed, and using it as a
    cursor would fire on cards due next week and never on the one that just
    moved.

    A card whose timestamp cannot be read returns 0, which puts it before
    every cursor and therefore drops it. That is the deliberate direction:
    the other way round, one unreadable card fires its rule on every tick
    for ever.
    """
    raw = str(card.get("dateLastActivity") or "").strip()
    if not raw:
        return 0
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return int(datetime.fromisoformat(raw).timestamp())
    except (TypeError, ValueError):
        return 0


def mark(card_id: str, when: int) -> str:
    """What this rule has already acted on: this card, at this change.

    The id alone would be wrong. A card is not an email: it is a thing that
    keeps changing, and remembering only its id means a rule fires the first
    time it is touched and then stays silent however much happens to it
    afterwards.
    """
    return "%s@%d" % (card_id, int(when))


def new_cards(cards, seen_marks, after_epoch: int):
    """(to_fire, skipped, cursor, seen) for one tick.

    `to_fire` is oldest first, so three cards moved in a row reach the agent
    in the order they were moved rather than backwards.

    `skipped` is how many the burst cap dropped. The cursor still moves past
    them, because holding it back would make the same flood arrive again on
    the next tick, for ever.

    The cursor only moves FORWARD and never past a card that was not
    accounted for, so a tick that fires nothing leaves it where it was.

    Unlike the Gmail search, the vendor does no filtering for us here:
    Trello returns every card on the list whatever its age, so the window is
    applied on this side. That is what keeps a brand new rule from firing on
    a list of a hundred old cards, and it is why `after_epoch` must be the
    rule's creation time and never zero.
    """
    seen = [s for s in (seen_marks or []) if isinstance(s, str) and s]
    known = set(seen)
    since = max(0, int(after_epoch) - OVERLAP_SECONDS)

    fresh = []
    for card in (cards or []):
        if not isinstance(card, dict):
            continue
        cid = card.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        when = _epoch_of(card)
        if when <= since:
            continue
        this = mark(cid, when)
        if this in known:
            continue
        known.add(this)             # a duplicate inside one page, too
        fresh.append((when, this, card))

    fresh.sort(key=lambda row: row[0])
    to_fire = fresh[:BURST]
    skipped = fresh[BURST:]
    accounted = to_fire + skipped

    cursor = int(after_epoch)
    for when, _, _ in accounted:
        cursor = max(cursor, when)
    # Newest first, so the cap keeps what the overlap might show us again.
    marks = [m for _, m, _ in reversed(accounted)]
    return ([c for _, _, c in to_fire], len(skipped), cursor,
            (marks + seen)[:SEEN_KEPT])


def payload_for(card: dict) -> dict:
    """What the agent is told about one card.

    Flat and named, because `automations.message_for` puts this under a line
    saying it is data: an agent reading "name" and "list_id" can act on it,
    where a raw Trello card object would make it guess at nesting and read
    past forty fields it does not need.

    The ids are included so the agent can comment on the right card or move
    it, with the Trello tools it already has.
    """
    desc = " ".join(str(card.get("desc") or "").split())
    return {
        "id": str(card.get("id") or ""),
        "name": " ".join(str(card.get("name") or "").split()),
        "url": str(card.get("url") or ""),
        "list_id": str(card.get("idList") or ""),
        "board_id": str(card.get("idBoard") or ""),
        "due": str(card.get("due") or ""),
        "changed": str(card.get("dateLastActivity") or ""),
        "description": desc[:MAX_DESC_CHARS],
    }
