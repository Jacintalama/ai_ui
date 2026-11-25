"""Calendly: event types, bookings and booking links, as you, with a token.

Read off Calendly's API v2 docs (2026-11-24) before a line was written,
because each of these fails without saying so:

**A personal token has SCOPES now**, chosen when it is made, and a new
token has none until boxes are ticked. The connect form says which, and a
403 that names a missing scope says to make a token with it.

**Listing anything needs the person's user URI**, which only /users/me
knows, and **an event is named by a URI** while a path takes its last part.
The prepare step reads and fills both, so a model never has to.

**Times are UTC.** A time with no offset is read in the person's own
Calendly time zone, or "book Tuesday at 3" lands eight hours out.

**A 400 says only "The supplied parameters are invalid."** Which parameter,
and why, is in `details`, and that is what the model gets now.

No cancel: the same no-destroy rule as the trackers. Each invitee's own
cancel and reschedule links are shown instead.
"""
import datetime
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import account_summary as acc
import agent_jev
import agent_tools
import app_triage
import calendly_args as CAL
import connections as C
import connector_drill
import mytools

HERE = os.path.dirname(__file__)
PANEL = os.path.join(HERE, "..", "..", "gdrive", "integrations-ui.js")
TENANTS = os.path.join(HERE, "..", "..", "..", "mcp-proxy", "tenants.py")

ME_URI = "https://api.calendly.com/users/AAAA1111"
ME = {"resource": {"uri": ME_URI, "name": "Me", "email": "me@x.com",
                   "timezone": "Asia/Manila",
                   "scheduling_url": "https://calendly.com/me"}}
TYPES = {"collection": [
    {"uri": "https://api.calendly.com/event_types/T30", "name": "30 Minute Meeting",
     "slug": "30min", "scheduling_url": "https://calendly.com/me/30min",
     "active": True, "duration": 30},
    {"uri": "https://api.calendly.com/event_types/T60", "name": "Intro call",
     "slug": "intro", "scheduling_url": "https://calendly.com/me/intro",
     "active": True, "duration": 60},
    {"uri": "https://api.calendly.com/event_types/T15", "name": "Quick intro chat",
     "slug": "quick", "scheduling_url": "https://calendly.com/me/quick",
     "active": True, "duration": 15},
]}
NOW = datetime.datetime(2026, 11, 24, 12, 0, tzinfo=datetime.timezone.utc)


class _R:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def _getter(me=ME, types=TYPES):
    calls = []

    async def get(path, extra=None):
        calls.append((path, dict(extra or {})))
        if path == "/users/me":
            return me
        if path == "/event_types":
            return types
        return None
    return get, calls


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(CAL, "_now", lambda: NOW)


def _tool(name):
    return next(t for t in mytools.PROVIDER_TOOLS["calendly"] if t.name == name)


# --- the credential --------------------------------------------------------

def test_calendly_is_a_provider():
    p = C.provider("calendly")
    assert p is not None and p.label == "Calendly"


def test_the_token_goes_as_a_bearer_to_the_api_host():
    auth = C.vendor_auth("calendly", {"token": "eyJabc"})
    assert auth.base_url == "https://api.calendly.com"
    assert auth.headers["Authorization"] == "Bearer eyJabc"
    assert auth.params == {}


def test_a_missing_token_is_refused_by_name():
    with pytest.raises(ValueError) as e:
        C.vendor_auth("calendly", {})
    assert "token" in str(e.value)


def test_the_form_says_where_the_token_lives_and_which_boxes_to_tick():
    p = C.provider("calendly")
    assert [f.name for f in p.fields] == ["token"]
    assert "Developer" in p.where and "Personal access tokens" in p.where
    for scope in CAL.SCOPES:
        assert scope in p.where, scope


def test_the_scopes_cover_every_tool():
    assert set(CAL.SCOPES) == {"users:read", "event_types:read",
                               "scheduled_events:read",
                               "scheduled_events:write",
                               "scheduling_links:write"}


def test_the_probe_asks_who_the_token_belongs_to():
    p = C.provider("calendly")
    assert (p.probe_path, p.probe_method) == ("/users/me", "GET")


def test_the_card_is_named_after_the_account():
    assert C.account_label("calendly", ME) == "me@x.com"
    assert C.account_label(
        "calendly", {"resource": {"name": "Only a name"}}) == "Only a name"


# --- how Calendly refuses --------------------------------------------------

def test_a_400_says_which_parameter_and_why():
    said = mytools._refusal(_R(400, {
        "title": "Invalid Argument",
        "message": "The supplied parameters are invalid.",
        "details": [{"parameter": "start_time",
                     "message": "must be in the future"}]}),
        "Calendly", {"token": "eyJabc"}, "calendly", "list_available_times")
    assert "The supplied parameters are invalid." in said
    assert "start_time: must be in the future" in said


def test_a_missing_scope_says_which_box_to_tick():
    said = mytools._refusal(_R(403, {
        "title": "Permission Denied",
        "message": "This token does not have the required scopes.",
        "required_scopes": ["scheduling_links:write"]}),
        "Calendly", {"token": "eyJabc"}, "calendly", "create_scheduling_link",
        writes=True)
    assert "scheduling_links:write" in said
    assert "new token" in said and "Connections" in said


def test_a_403_without_scopes_still_reads_as_before():
    said = mytools._refusal(_R(403, {"title": "Permission Denied",
                                     "message": "Event in the past"}),
                            "Calendly", {"token": "eyJabc"}, "calendly",
                            "book_meeting", writes=True)
    assert "Event in the past" in said
    assert "scope" not in said.lower()


def test_a_revoked_token_says_reconnect():
    said = mytools._refusal(_R(401, {"title": "Unauthenticated",
                                     "message": "The access token was revoked"}),
                            "Calendly", {"token": "eyJabc"}, "calendly", "whoami")
    assert "Reconnect" in said


def test_the_token_is_never_repeated_back():
    said = mytools._refusal(_R(400, {
        "message": "bad", "details": [{"parameter": "x",
                                       "message": "eyJsecrettoken123 is wrong"}]}),
        "Calendly", {"token": "eyJsecrettoken123"}, "calendly", "list_events")
    assert "eyJsecrettoken123" not in said


# --- the tools -------------------------------------------------------------

READS = {"whoami", "list_event_types", "list_events", "get_event",
         "list_invitees", "list_available_times"}
WRITES = {"create_scheduling_link", "book_meeting"}


def test_six_reads_two_writes_and_no_cancel():
    tools = {t.name: t for t in mytools.PROVIDER_TOOLS["calendly"]}
    assert set(tools) == READS | WRITES
    assert {n for n, t in tools.items() if mytools._writes(t)} == WRITES
    assert not any("cancel" in n or "delete" in n for n in tools)


@pytest.mark.parametrize("name", sorted(READS))
def test_a_read_only_agent_may_run_the_reads(name):
    assert not agent_tools.is_write_tool("my-calendly_" + name)


@pytest.mark.parametrize("name", sorted(WRITES))
def test_a_read_only_agent_may_not_run_the_writes(name):
    assert agent_tools.is_write_tool("my-calendly_" + name)


@pytest.mark.parametrize("name", ["list_event_types", "list_events",
                                  "list_invitees"])
def test_a_list_asks_for_one_more_than_it_shows(name):
    """So `truncated` in the answer is true exactly when there are more."""
    assert CAL.PAGE == mytools.MAX_ITEMS + 1
    assert mytools._query_for(_tool(name), {})["count"] == CAL.PAGE


def test_answers_come_out_of_calendlys_envelopes():
    assert _tool("whoami").unwrap(ME) == ME["resource"]
    assert _tool("list_event_types").unwrap(TYPES) == TYPES["collection"]


def test_upcoming_bookings_come_soonest_first_and_active():
    q = mytools._query_for(_tool("list_events"), {"user": ME_URI})
    assert q["sort"] == "start_time:asc" and q["status"] == "active"
    assert q["user"] == ME_URI


def test_a_one_time_link_is_one_booking_of_an_event_type():
    body = mytools._payload_for(_tool("create_scheduling_link"),
                                {"event_type": TYPES["collection"][0]["uri"]})
    assert body == {"max_event_count": 1,
                    "owner": "https://api.calendly.com/event_types/T30",
                    "owner_type": "EventType"}


def test_a_booking_is_the_shape_calendly_takes():
    body = mytools._payload_for(_tool("book_meeting"), {
        "event_type": "https://api.calendly.com/event_types/T30",
        "start_time": "2026-12-01T07:00:00.000000Z",
        "invitee_email": "ana@client.com", "invitee_name": "Ana",
        "invitee_timezone": "Asia/Manila",
        "guests": "bo@client.com, cy@client.com"})
    assert body == {
        "event_type": "https://api.calendly.com/event_types/T30",
        "start_time": "2026-12-01T07:00:00.000000Z",
        "invitee": {"email": "ana@client.com", "name": "Ana",
                    "timezone": "Asia/Manila"},
        "event_guests": ["bo@client.com", "cy@client.com"]}


def test_more_than_ten_guests_is_refused():
    with pytest.raises(ValueError):
        CAL.booking_body({"event_type": "https://api.calendly.com/event_types/T30",
                          "start_time": "2026-12-01T07:00:00.000000Z",
                          "invitee_email": "a@b.com", "invitee_name": "A",
                          "invitee_timezone": "UTC",
                          "guests": ",".join("g%d@x.com" % i for i in range(11))})


# --- the prepare step: who, which and when --------------------------------

async def test_a_list_is_always_of_your_own_calendar():
    get, calls = _getter()
    args, problem = await CAL.prepare(
        "list_events", {"user": "https://api.calendly.com/users/SOMEONE"}, get)
    assert problem is None and args["user"] == ME_URI
    assert calls[0][0] == "/users/me"


async def test_with_no_window_the_bookings_are_the_upcoming_ones():
    get, _ = _getter()
    args, _ = await CAL.prepare("list_events", {}, get)
    assert args["min_start_time"] == "2026-11-24T12:00:00.000000Z"
    assert "max_start_time" not in args


async def test_a_time_with_no_offset_is_in_your_calendly_time_zone():
    """9am in Manila is 1am UTC. Read as UTC it would be 5pm in Manila."""
    get, _ = _getter()
    args, _ = await CAL.prepare("list_events", {
        "min_start_time": "2026-12-01T09:00",
        "max_start_time": "2026-12-01T18:00:00+08:00"}, get)
    assert args["min_start_time"] == "2026-12-01T01:00:00.000000Z"
    assert args["max_start_time"] == "2026-12-01T10:00:00.000000Z"


async def test_a_utc_time_stays_utc():
    get, _ = _getter()
    args, _ = await CAL.prepare("list_events",
                                {"min_start_time": "2026-12-01T09:00:00Z"}, get)
    assert args["min_start_time"] == "2026-12-01T09:00:00.000000Z"


async def test_a_time_that_is_not_a_time_says_how_to_write_one():
    get, _ = _getter()
    _, problem = await CAL.prepare("list_events",
                                   {"min_start_time": "next tuesday"}, get)
    assert problem and "2026-12-01T15:00" in problem


@pytest.mark.parametrize("said, sent", [("cancelled", "canceled"),
                                        ("Canceled", "canceled"),
                                        ("upcoming", "active")])
async def test_the_status_is_spelled_the_way_calendly_spells_it(said, sent):
    get, _ = _getter()
    args, _ = await CAL.prepare("list_events", {"status": said}, get)
    assert args["status"] == sent


async def test_when_calendly_cannot_say_who_you_are_nothing_is_sent():
    get, _ = _getter(me=None)
    _, problem = await CAL.prepare("list_event_types", {}, get)
    assert problem and "Reconnect Calendly" in problem


@pytest.mark.parametrize("given", [
    "https://api.calendly.com/scheduled_events/EV123",
    "https://api.calendly.com/scheduled_events/EV123/", "EV123"])
async def test_a_booking_is_named_by_its_uri_or_its_id(given):
    get, calls = _getter()
    args, problem = await CAL.prepare("get_event", {"event": given}, get)
    assert problem is None and args["event_id"] == "EV123"
    assert calls == [], "naming a booking needs no read"


async def test_a_booking_must_be_named():
    get, _ = _getter()
    _, problem = await CAL.prepare("list_invitees", {}, get)
    assert problem and "list_events" in problem


@pytest.mark.parametrize("given", [
    "30 Minute Meeting", "30 minute meeting", "30min",
    "https://calendly.com/me/30min", "https://calendly.com/me/30min/",
    "https://api.calendly.com/event_types/T30", "T30"])
async def test_an_event_type_is_found_however_it_is_named(given):
    get, _ = _getter()
    args, problem = await CAL.prepare("create_scheduling_link",
                                      {"event_type": given}, get)
    assert problem is None
    assert args["event_type"] == "https://api.calendly.com/event_types/T30"


async def test_part_of_a_name_finds_the_one_it_fits():
    get, _ = _getter()
    args, problem = await CAL.prepare("create_scheduling_link",
                                      {"event_type": "30 minute"}, get)
    assert problem is None and args["event_type"].endswith("/T30")


async def test_an_exact_slug_beats_a_name_that_only_contains_it():
    """"intro" is in two names, but it IS Intro call's slug."""
    get, _ = _getter()
    args, problem = await CAL.prepare("create_scheduling_link",
                                      {"event_type": "intro"}, get)
    assert problem is None and args["event_type"].endswith("/T60")


async def test_two_types_that_both_fit_are_named_back():
    types = {"collection": [
        {"uri": "https://api.calendly.com/event_types/A", "name": "Demo EU"},
        {"uri": "https://api.calendly.com/event_types/B", "name": "Demo US"}]}
    get, _ = _getter(types=types)
    _, problem = await CAL.prepare("create_scheduling_link",
                                   {"event_type": "demo"}, get)
    assert problem and "Demo EU" in problem and "Demo US" in problem


async def test_an_event_type_you_do_not_have_lists_the_ones_you_do():
    get, _ = _getter()
    _, problem = await CAL.prepare("create_scheduling_link",
                                   {"event_type": "Board meeting"}, get)
    assert problem and "Board meeting" in problem
    assert "30 Minute Meeting" in problem and "Intro call" in problem


async def test_with_no_event_types_it_says_to_make_one():
    get, _ = _getter(types={"collection": []})
    _, problem = await CAL.prepare("create_scheduling_link",
                                   {"event_type": "30min"}, get)
    assert problem and "no Calendly event types" in problem


async def test_open_times_default_to_the_next_seven_days():
    get, _ = _getter()
    args, problem = await CAL.prepare("list_available_times",
                                      {"event_type": "30min"}, get)
    assert problem is None
    assert args["start_time"] == "2026-11-24T12:01:00.000000Z"
    assert args["end_time"] == "2026-12-01T12:01:00.000000Z"


async def test_open_times_from_earlier_today_start_now():
    """Calendly refuses a start in the past; "what is free today" gives one."""
    get, _ = _getter()
    args, _ = await CAL.prepare("list_available_times", {
        "event_type": "30min", "start_time": "2026-11-24T00:00",
        "end_time": "2026-11-25T00:00"}, get)
    assert args["start_time"] == "2026-11-24T12:01:00.000000Z"
    assert args["end_time"] == "2026-11-24T16:00:00.000000Z"


async def test_a_window_that_ends_before_it_starts_is_refused():
    get, _ = _getter()
    _, problem = await CAL.prepare("list_available_times", {
        "event_type": "30min", "start_time": "2026-12-05T09:00",
        "end_time": "2026-12-04T09:00"}, get)
    assert problem and "end_time" in problem


async def test_a_booking_is_in_your_time_zone_unless_told_otherwise():
    get, _ = _getter()
    args, problem = await CAL.prepare("book_meeting", {
        "event_type": "Intro call", "start_time": "2026-12-01T15:00",
        "invitee_email": "ana@client.com", "invitee_name": "Ana"}, get)
    assert problem is None
    assert args["event_type"].endswith("/T60")
    assert args["start_time"] == "2026-12-01T07:00:00.000000Z"
    assert args["invitee_timezone"] == "Asia/Manila"


@pytest.mark.parametrize("missing, word", [
    ("start_time", "start_time"), ("invitee_email", "invitee_email"),
    ("invitee_name", "invitee_name")])
async def test_a_booking_needs_when_and_who(missing, word):
    full = {"event_type": "Intro call", "start_time": "2026-12-01T15:00",
            "invitee_email": "ana@client.com", "invitee_name": "Ana"}
    full.pop(missing)
    get, _ = _getter()
    _, problem = await CAL.prepare("book_meeting", full, get)
    assert problem and word in problem


async def test_a_time_zone_calendly_would_not_know_is_refused():
    get, _ = _getter()
    _, problem = await CAL.prepare("book_meeting", {
        "event_type": "Intro call", "start_time": "2026-12-01T15:00",
        "invitee_email": "ana@client.com", "invitee_name": "Ana",
        "invitee_timezone": "PST"}, get)
    assert problem and "America/Los_Angeles" in problem


async def test_the_tools_with_nothing_to_fill_read_nothing():
    get, calls = _getter()
    args, problem = await CAL.prepare("whoami", {}, get)
    assert problem is None and calls == []


# --- the rest of the wiring ----------------------------------------------

def test_mytools_runs_the_prepare_step_for_calendly():
    assert mytools.PREPARE.get("calendly") is not None


def test_the_panel_offers_calendly_as_a_real_card():
    src = open(PANEL, encoding="utf-8").read()
    line = [l for l in src.splitlines() if "id: 'calendly'" in l]
    assert line and "real: true" in line[0] and "token: true" in line[0]


def test_mcp_proxy_can_reach_the_calendly_tools():
    src = open(TENANTS, encoding="utf-8").read()
    assert 'server_id="my-calendly"' in src
    assert 'MCP_MYTOOLS_URL + "/calendly"' in src


def test_the_triage_agent_knows_what_calendly_is_for():
    app = app_triage.APPS.get("calendly")
    assert app is not None and app.label == "Calendly"
    assert "book" in app.note.lower()
    assert set(app.tools) <= {t.name for t in mytools.PROVIDER_TOOLS["calendly"]}
    assert "cancel" in app.cannot.lower()


def test_the_router_can_pick_it_because_the_note_says_its_name():
    note = " ".join(str(agent_jev.TOOL_NOTES.get("server:mcp-proxy", "")).split())
    assert "calendly" in note.lower()


def test_the_making_clause_names_a_booking_and_a_scheduling_link():
    making = " ".join(str(agent_jev.MAKES_CLAUSE).split()).lower()
    assert "booking" in making and "scheduling link" in making


def test_the_drill_can_find_an_event_and_an_event_type():
    F = connector_drill.FROM_RESULT
    assert ("list_events", "uri") in F["event"]
    assert ("list_event_types", "uri") in F["event_type"]


def test_the_assistant_counts_it_among_the_apps_you_can_connect():
    assert "calendly" in acc.ALL_PROVIDER_IDS
    assert acc.connect_hint("calendly")["label"] == "Calendly"
