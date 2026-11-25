"""Calendly: what a model says, made into what Calendly's API v2 takes.

Pure decisions plus one `prepare` step that reads as the person, the same
split as clickup_people, trello_people and github_refs, so every rule here
is tested with no vendor and no network
(tests/test_calendly_is_a_connector.py).

Read off Calendly's docs on 2026-11-24, and each of these fails without
saying so:

- LISTING ANYTHING NEEDS THE PERSON'S USER URI. /event_types and
  /scheduled_events take `user=https://api.calendly.com/users/...`, which
  only /users/me knows. It is filled here, always with the person's own,
  so a model never has to find it and can never name somebody else's.
- AN EVENT IS NAMED BY A URI, and a path takes only its last part. A model
  hands back the uri it was given, so the id is cut out of it here.
- TIMES ARE UTC. A time with no offset is read in the person's own
  Calendly time zone, or "book Tuesday at 3" lands eight hours out for
  somebody in Manila.
- AN EVENT TYPE IS A URI TOO, but a person says "my 30 minute meeting". It
  is found by name, slug, booking page or uri, and when nothing fits the
  answer names the ones that exist.
"""
from __future__ import annotations

import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

API = "https://api.calendly.com"

#: What a personal access token needs ticked, one per kind of tool. A new
#: token has NO scopes until boxes are ticked, so the connect form names
#: these. users:read is also what the connect check itself reads.
SCOPES = ("users:read", "event_types:read", "scheduled_events:read",
          "scheduled_events:write", "scheduling_links:write")

#: How many a list asks for: one more than a tool result shows
#: (mytools.MAX_ITEMS), so `truncated` in the answer is true exactly when
#: there are more, and the model narrows the window rather than paging.
PAGE = 26

#: Open times are asked for this far ahead when no end is given.
WINDOW_DAYS = 7

#: Calendly takes at most this many extra guests on a booking.
MAX_GUESTS = 10

Get = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]

#: The tools that need the person's user URI or time zone.
NEEDS_ME = frozenset({"list_event_types", "list_events",
                      "list_available_times", "create_scheduling_link",
                      "book_meeting"})
#: The tools whose path names one booking.
NAMES_AN_EVENT = frozenset({"get_event", "list_invitees"})
#: The tools that name one of the person's event types.
NAMES_AN_EVENT_TYPE = frozenset({"list_available_times",
                                 "create_scheduling_link", "book_meeting"})

NO_ME = ("Calendly did not say who you are, so there is nothing to look "
         "in. Reconnect Calendly from Connections and try again.")
NO_TYPES = ("Your Calendly event types could not be read just now. Try "
            "again in a minute.")
HOW_TO_WRITE_A_TIME = "Use ISO 8601, for example 2026-12-01T15:00."


def _now() -> datetime.datetime:
    """A seam, so a test can freeze the clock."""
    return datetime.datetime.now(datetime.timezone.utc)


def last_part(value: Any) -> str:
    """The id at the end of a Calendly uri, or the value itself."""
    return str(value or "").strip().rstrip("/").rsplit("/", 1)[-1].strip()


def stamp(when: datetime.datetime) -> str:
    """UTC, in the form Calendly's own examples use."""
    return when.astimezone(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z")


def _zone(name: Any):
    try:
        return ZoneInfo(str(name or "UTC"))
    except Exception:                                       # noqa: BLE001
        return datetime.timezone.utc


def parse_time(value: Any, tz_name: Any) -> datetime.datetime:
    """A time a model wrote, as an aware datetime.

    No offset means the person's own Calendly time zone, never UTC.
    Raises ValueError with a sentence the model can act on.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("A time is missing. " + HOW_TO_WRITE_A_TIME)
    iso = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        when = datetime.datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError('"%s" is not a date and time Calendly can read. %s'
                         % (text, HOW_TO_WRITE_A_TIME)) from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_zone(tz_name))
    return when


def to_utc(value: Any, tz_name: Any) -> str:
    return stamp(parse_time(value, tz_name))


#: What a person or a model calls a status -> Calendly's spelling.
_STATUS = {"cancelled": "canceled", "canceled": "canceled",
           "active": "active", "upcoming": "active", "booked": "active",
           "scheduled": "active"}


def _events_window(args: Dict[str, Any], tz: str) -> None:
    for key in ("min_start_time", "max_start_time"):
        if args.get(key) not in (None, ""):
            args[key] = to_utc(args[key], tz)
    if not args.get("min_start_time") and not args.get("max_start_time"):
        # "What is booked" means from now on, not since the account began.
        args["min_start_time"] = stamp(_now())
    status = str(args.get("status") or "").strip().lower()
    if status:
        args["status"] = _STATUS.get(status, status)


def _free_window(args: Dict[str, Any], tz: str) -> None:
    """start_time and end_time for open times, both required by Calendly.

    A start in the past is moved to now: Calendly refuses one, and "what
    is free today" is exactly how a model comes to send it.
    """
    soonest = _now() + datetime.timedelta(minutes=1)
    start = (parse_time(args["start_time"], tz)
             if args.get("start_time") not in (None, "") else soonest)
    if start < soonest:
        start = soonest
    if args.get("end_time") not in (None, ""):
        end = parse_time(args["end_time"], tz)
        if end <= start:
            raise ValueError("end_time has to be after start_time.")
    else:
        end = start + datetime.timedelta(days=WINDOW_DAYS)
    args["start_time"], args["end_time"] = stamp(start), stamp(end)


def _booking(args: Dict[str, Any], tz: str) -> None:
    if args.get("start_time") in (None, ""):
        raise ValueError("Say when the meeting starts, in start_time. "
                         + HOW_TO_WRITE_A_TIME)
    args["start_time"] = to_utc(args["start_time"], tz)
    if "@" not in str(args.get("invitee_email") or ""):
        raise ValueError("Say who it is for in invitee_email: the address "
                         "the invitation goes to.")
    if not str(args.get("invitee_name") or "").strip():
        raise ValueError("Say the invitee's name, in invitee_name.")
    theirs = str(args.get("invitee_timezone") or "").strip()
    if theirs:
        try:
            ZoneInfo(theirs)
        except Exception:                                   # noqa: BLE001
            raise ValueError(
                '"%s" is not a time zone Calendly knows. Use a name like '
                'America/Los_Angeles or Europe/London.' % theirs) from None
    args["invitee_timezone"] = theirs or tz


def _names(rows: List[dict]) -> str:
    return ", ".join('"%s"' % (r.get("name") or last_part(r.get("uri")))
                     for r in rows[:10])


def pick_event_type(given: Any, types: List[dict]
                    ) -> Tuple[Optional[str], Optional[str]]:
    """(uri, None) for the one event type `given` names, or (None, why).

    Strictest first: a uri, a booking page, a name, a slug, an id, and
    only then a name that merely contains the words. So "intro" is the
    event type whose slug IS intro, not every one with intro in its name.
    """
    rows = [t for t in (types or []) if isinstance(t, dict) and t.get("uri")]
    if not rows:
        return None, ("You have no Calendly event types yet. Make one in "
                      "Calendly first, then ask again.")
    text = str(given or "").strip()
    if not text:
        return None, ("Say which event type, by its name. Yours are: "
                      + _names(rows) + ".")
    low = text.lower().rstrip("/")
    tail = last_part(text).lower()

    def field(t, key):
        return str(t.get(key) or "").strip().lower().rstrip("/")

    steps = (
        lambda t: field(t, "uri") == low,
        lambda t: field(t, "scheduling_url") == low,
        lambda t: field(t, "name") == low,
        lambda t: field(t, "slug") in (low, tail),
        lambda t: last_part(t.get("uri")).lower() == tail,
        lambda t: low in field(t, "name"),
    )
    for fits in steps:
        hits = [t for t in rows if fits(t)]
        if len(hits) == 1:
            return str(hits[0]["uri"]), None
        if len(hits) > 1:
            return None, ('More than one of your Calendly event types fits '
                          '"%s": %s. Say which.' % (text, _names(hits)))
    return None, ('You have no Calendly event type called "%s". Yours are: '
                  '%s.' % (text, _names(rows)))


def _guests(given: Any) -> List[str]:
    if isinstance(given, (list, tuple)):
        parts = [str(g) for g in given]
    else:
        parts = str(given or "").replace(";", ",").replace(" ", ",").split(",")
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if "@" in p and p.lower() not in (o.lower() for o in out):
            out.append(p)
    if len(out) > MAX_GUESTS:
        raise ValueError("Calendly takes at most %d guests on a booking."
                         % MAX_GUESTS)
    return out


def _event_type_uri(args: Dict[str, Any]) -> str:
    uri = str((args or {}).get("event_type") or "")
    if not uri.startswith(API + "/event_types/"):
        raise ValueError("Say which of your event types, by its name or its "
                         "uri from list_event_types.")
    return uri


def scheduling_link_body(args: Dict[str, Any]) -> Dict[str, Any]:
    """A one-time link: it books one meeting and then stops working."""
    return {"max_event_count": 1, "owner": _event_type_uri(args),
            "owner_type": "EventType"}


def booking_body(args: Dict[str, Any]) -> Dict[str, Any]:
    a = args or {}
    body: Dict[str, Any] = {
        "event_type": _event_type_uri(a),
        "start_time": str(a.get("start_time") or ""),
        "invitee": {"email": str(a.get("invitee_email") or "").strip(),
                    "name": str(a.get("invitee_name") or "").strip(),
                    "timezone": str(a.get("invitee_timezone") or "UTC")},
    }
    guests = _guests(a.get("guests"))
    if guests:
        body["event_guests"] = guests
    return body


async def prepare(tool_name: str, args: Dict[str, Any], get: Get
                  ) -> Tuple[Dict[str, Any], Optional[str]]:
    """The arguments Calendly should receive, or a reason to send nothing.

    Runs on EVERY Calendly call, so a tool with nothing to fill returns
    before reading anything.
    """
    args = dict(args or {})
    if tool_name in NAMES_AN_EVENT:
        event = last_part(args.get("event") or args.get("event_id"))
        if not event:
            return args, ("Say which booking, by its uri from list_events.")
        args["event_id"] = event
        return args, None
    if tool_name not in NEEDS_ME:
        return args, None

    me = await get("/users/me", None)
    user = me.get("resource") if isinstance(me, dict) else None
    uri = str((user or {}).get("uri") or "") if isinstance(user, dict) else ""
    if not uri:
        return args, NO_ME
    # Always the person's own, whatever the model sent.
    args["user"] = uri
    tz = str(user.get("timezone") or "UTC")
    try:
        if tool_name == "list_events":
            _events_window(args, tz)
        elif tool_name == "list_available_times":
            _free_window(args, tz)
        elif tool_name == "book_meeting":
            _booking(args, tz)
    except ValueError as e:
        return args, str(e)

    if tool_name in NAMES_AN_EVENT_TYPE:
        listed = await get("/event_types", {"user": uri, "count": 100})
        rows = listed.get("collection") if isinstance(listed, dict) else None
        if not isinstance(rows, list):
            return args, NO_TYPES
        found, problem = pick_event_type(args.get("event_type"), rows)
        if problem:
            return args, problem
        args["event_type"] = found
    return args, None
