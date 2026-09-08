"""The Open WebUI tool that lets an agent work with its owner's schedules.

Loaded by path, the same way tests/test_agents_tool.py loads
open-webui-functions/agents_tool.py, because this file lives outside the
tasks service and is never imported by anything in it.

The security property under test is not "it does not send the secret". It is
that there is no secret to send: the tool authenticates with the caller's
email alone, and tasks.routes_schedules._resolve_caller then forces every
call onto that person.
"""
import importlib.util
import json
import os
from unittest import mock
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

TOOL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "schedules_tool.py")

BASE = "http://test-tasks:8210"
OWNER = {"email": "owner@example.com"}


def _load():
    spec = importlib.util.spec_from_file_location("schedules_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tool():
    mod = _load()
    t = mod.Tools()
    t.valves.tasks_url = BASE
    return t


#: A real schedule id. They are UUIDs: routes_schedules parses every one of
#: them with uuid.UUID, and the tool refuses anything else before it builds a
#: path, so a mock id like "sch-1" would exercise a value production can
#: never produce.
SID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

#: Exactly what routes_schedules._serialize returns, field for field. A
#: trimmed mock made the "does the tool leak the API's shape" assertions
#: below vacuous: they cannot catch user_email being printed if the row they
#: are given has no user_email in it.
ROW = {
    "id": SID,
    "user_email": "owner@example.com",
    "name": "Morning inbox",
    "cron_expr": "0 8 * * *",
    "tz": "Europe/London",
    "persona": "",
    "prompt": "what needs a reply",
    "enabled": True,
    "last_run_at": "2026-09-08T08:00:00+00:00",
    "last_run_status": "ok",
    "last_result": "Three emails need a reply.",
    "last_result_at": "2026-09-08T08:00:12+00:00",
    "delivery_channel_id": None,
    "delivery_platform": "discord",
    "kind": "agent",
    "agent_id": None,
    "tool_mode": None,
}

#: What POST /schedules really replies with. It returns {"id": ...} and
#: nothing else, so mocking a whole row there would test a shape the server
#: never sends.
CREATED = {"id": SID}


def test_the_valves_have_nowhere_to_put_a_secret(tool):
    """Not "it does not send one": there is no field for one. A later edit
    that adds it back has to add the field, which shows up in review."""
    fields = set(type(tool.valves).model_fields)
    assert fields == {"tasks_url", "timeout_seconds"}
    assert not any("secret" in f.lower() for f in fields)


@respx.mock
async def test_listing_asks_as_the_caller_and_carries_no_operator_header(tool):
    route = respx.get(BASE + "/schedules").mock(
        return_value=httpx.Response(200, json=[ROW]))
    out = await tool.list_my_schedules(__user__=OWNER)
    sent = route.calls[0].request
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert "Morning inbox" in out


@respx.mock
async def test_a_schedule_reads_back_as_a_sentence_not_a_dump(tool):
    respx.get(BASE + "/schedules").mock(
        return_value=httpx.Response(200, json=[ROW]))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert "0 8 * * *" in out
    assert "Europe/London" in out
    assert "on" in out.lower()
    assert "user_email" not in out, "that is the API's shape, not a person's"
    assert ROW["user_email"] not in out, "nor is the owner's address"
    assert ROW["last_result"] not in out, "a whole past run is not a listing"


@respx.mock
async def test_nothing_scheduled_says_so(tool):
    respx.get(BASE + "/schedules").mock(
        return_value=httpx.Response(200, json=[]))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert "nothing" in out.lower() or "no schedules" in out.lower()


@respx.mock
async def test_a_failure_is_a_sentence_and_never_leaks_the_url(tool):
    respx.get(BASE + "/schedules").mock(
        side_effect=httpx.ConnectError("boom"))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert isinstance(out, str) and out
    assert BASE not in out
    assert "boom" not in out
    assert "Traceback" not in out


@respx.mock
async def test_a_broken_shape_is_still_a_sentence(tool):
    """It talks to another service over HTTP, so the shape is not ours to
    trust."""
    respx.get(BASE + "/schedules").mock(
        return_value=httpx.Response(200, json={"unexpected": "object"}))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert isinstance(out, str) and out
    assert "Traceback" not in out


async def test_no_email_does_nothing_at_all(tool):
    """No respx mock on purpose: if it tried to call, the test would error
    rather than pass."""
    out = await tool.list_my_schedules(__user__={})
    assert "could not tell" in out.lower() or "who" in out.lower()


# ------------------------------------------------------------------- writing

# The names have to classify correctly under the real safety gate, because
# that gate is what stops a read-only agent changing anything. Getting this
# wrong is not theoretical: my_account was classified as a write for a day
# because "my" and "account" are neither kind of verb, and a read-only agent
# was refused a read.

def test_every_method_classifies_the_way_the_spec_says():
    from agent_tools import is_write_tool
    assert is_write_tool("list_my_schedules") is False
    for name in ("create_schedule", "enable_schedule", "disable_schedule",
                 "delete_schedule", "trigger_schedule_now"):
        assert is_write_tool(name) is True, name


def test_the_run_now_method_is_a_write_on_purpose_not_by_default():
    """run_schedule_now contains no verb the classifier knows, so it would
    land on the default and be right by accident. trigger is on the write
    list, so the name carries the meaning."""
    from agent_tools import is_write_tool
    assert is_write_tool("run_schedule_now") is True, "the default, by accident"
    assert is_write_tool("trigger_schedule_now") is True, "the verb, on purpose"
    tool_methods = [m for m in dir(_load().Tools) if not m.startswith("_")]
    assert "trigger_schedule_now" in tool_methods
    assert "run_schedule_now" not in tool_methods


@respx.mock
async def test_creating_sends_the_persons_own_timezone(tool):
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "source": "browser",
                   "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    out = await tool.create_schedule(
        name="Morning inbox", cron_expr="0 8 * * *",
        prompt="what needs a reply", __user__=OWNER)
    body = json.loads(route.calls[0].request.read())
    assert body["tz"] == "Europe/London"
    assert "Europe/London" in out


@respx.mock
async def test_an_undetected_timezone_is_disclosed_not_hidden(tool):
    """A schedule an hour off looks like it worked, so the zone used has to
    be a sentence somebody can correct."""
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Asia/Manila", "source": "default",
                   "detected": False}))
    respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    out = await tool.create_schedule(
        name="Morning inbox", cron_expr="0 8 * * *", prompt="hi",
        __user__=OWNER)
    assert "Asia/Manila" in out
    assert "no timezone" in out.lower() or "did not" in out.lower()


@respx.mock
async def test_a_schedule_an_agent_makes_runs_as_that_agent(tool):
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    await tool.create_schedule(
        name="n", cron_expr="0 8 * * *", prompt="p", __user__=OWNER,
        __model__={"id": "agent-research-assistant-0001"})
    body = json.loads(route.calls[0].request.read())
    assert body["agent_id"] == "agent-research-assistant-0001"


@respx.mock
async def test_a_plain_model_is_not_passed_off_as_an_agent(tool):
    """agent_id has to be one of this person's agents. gpt-5 is not one, and
    sending it would make a schedule that can never run."""
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    await tool.create_schedule(
        name="n", cron_expr="0 8 * * *", prompt="p", __user__=OWNER,
        __model__={"id": "gpt-5"})
    body = json.loads(route.calls[0].request.read())
    assert body.get("agent_id") is None


@respx.mock
async def test_creating_never_lets_the_caller_name_the_owner(tool):
    """The endpoint overwrites it anyway. Not sending it means the tool does
    not depend on that."""
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    await tool.create_schedule(name="n", cron_expr="0 8 * * *", prompt="p",
                               __user__=OWNER)
    sent = route.calls[0].request
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert "user_email" not in sent.read().decode()


@respx.mock
async def test_a_failed_create_does_not_claim_a_schedule_exists(tool):
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(500, json={"detail": "nope"}))
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__=OWNER)
    assert "could not" in out.lower()
    assert "scheduled" not in out.lower() or "not" in out.lower()
    assert BASE not in out


@respx.mock
async def test_a_broken_timezone_read_is_disclosed_not_hidden(tool):
    """Not knowing the zone is a reason to say which one was used, not a
    reason to refuse the whole request, and not a reason to say nothing.

    The failure mode this closes: with the read down, no tz was sent, the
    server quietly defaulted to Asia/Manila, and the person was told their
    schedule was made without a zone named anywhere. A schedule an hour off
    looks like it worked, so the fallback has to be sent explicitly and said
    out loud."""
    respx.get(BASE + "/prefs/timezone").mock(
        side_effect=httpx.ConnectError("down"))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__=OWNER)
    assert route.called
    body = json.loads(route.calls[0].request.read())
    assert body["tz"] == "Asia/Manila", "the zone said has to be the zone sent"
    assert "Asia/Manila" in out, "the zone that applies has to be named"
    assert "could not read your timezone" in out.lower()
    assert "down" not in out
    assert BASE not in out


@pytest.mark.parametrize("method,verb,suffix,response,done", [
    ("enable_schedule", "POST", "/enable", {"status": "enabled"},
     "turned back on"),
    ("disable_schedule", "POST", "/disable", {"status": "disabled"},
     "turned off"),
    ("delete_schedule", "DELETE", "", {"status": "deleted"}, "deleted"),
    ("trigger_schedule_now", "POST", "/run-now", {"status": "dispatched"},
     "started now"),
])
@respx.mock
async def test_each_write_hits_its_own_endpoint_as_the_caller(
        tool, method, verb, suffix, response, done):
    """The four endpoints really reply with a status dict, not a schedule,
    so that is what is mocked here: this exercises the sentence a person
    actually gets, not the dead branch that reads an id off a row that never
    comes back."""
    route = respx.request(verb, BASE + "/schedules/" + SID + suffix).mock(
        return_value=httpx.Response(200, json=response))
    out = await getattr(tool, method)(SID, __user__=OWNER)
    sent = route.calls[0].request
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert out == "Done, %s." % done


@pytest.mark.parametrize("method", [
    "enable_schedule", "disable_schedule", "delete_schedule",
    "trigger_schedule_now",
])
async def test_no_email_stops_every_write_before_it_calls(tool, method):
    """No respx mock: a call would error the test rather than pass it."""
    out = await getattr(tool, method)(SID, __user__={})
    assert isinstance(out, str) and out


@respx.mock
async def test_creating_reports_the_schedule_actually_made_not_the_bare_id_reply(tool):
    """POST /schedules returns only {"id": ...} for real, nothing else. The
    reply has to describe the schedule as it was actually made (from what
    was sent), not from fields read off that bare response and defaulted
    away, which would wrongly tell a person their new schedule is off."""
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))
    out = await tool.create_schedule(
        name="Morning inbox", cron_expr="0 8 * * *",
        prompt="what needs a reply", __user__=OWNER)
    assert "Morning inbox" in out
    assert "0 8 * * *" in out
    assert "currently on" in out
    assert SID in out


async def test_creating_with_no_email_does_not_call(tool):
    """No respx mock: a call would error the test rather than pass it."""
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__={})
    assert isinstance(out, str) and out


@respx.mock
async def test_creating_with_no_id_in_the_reply_does_not_claim_success(tool):
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json={}))
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__=OWNER)
    assert isinstance(out, str) and out
    assert "did not name" in out.lower()


# --------------------------------------------------- the id is not a free path

# Every id-taking method puts a value the MODEL chose into a URL, and httpx
# resolves dot segments before it sends. So an id of "../connections/github"
# does not ask for a schedule called that: it leaves /schedules entirely and
# asks a different endpoint of the tasks service, with this person's own
# X-User-Email attached, which is all that endpoint authenticates on.
#
# delete_schedule is the worst of the four because nothing follows the id, so
# it is a general "DELETE any path on this service as this person" primitive:
# DELETE /connections/github drops their GitHub credential, and
# DELETE /vercel/connect drops their Vercel token. Both then report
# "Done, deleted."
#
# It is same-user only, so it is not a cross-tenant hole. It is still the
# vector agent_access names: an agent doing something its owner did not
# intend, at the prompting of text it read somewhere else. And it defeats the
# argument this whole tool rests on, because "the endpoint enforces the
# scoping" cannot apply to an endpoint that was never meant to be called.
#
# So these assert on the REQUESTS MADE, not on the sentence returned. A
# refusal sentence with the request already sent would pass a
# sentence-shaped assertion and still have deleted the credential.

_ESCAPES = [
    "../connections/github",
    "../../graph/mine/prebuild",
    "..%2fconnections%2fgithub",
    "sch-1",
    "",
    None,
    {"id": "x"},
]


@pytest.mark.parametrize("method", [
    "enable_schedule", "disable_schedule", "delete_schedule",
    "trigger_schedule_now",
])
@pytest.mark.parametrize("bad_id", _ESCAPES)
@respx.mock
async def test_an_id_that_is_not_a_schedule_id_sends_no_request_at_all(
        tool, method, bad_id):
    """A catch-all route on purpose, answering anything with a success.

    Leaving respx unrouted is NOT enough: an unmatched request raises inside
    the client, the tool catches it like any other transport failure, and the
    test then passes on code that really did try to leave. Routing everything
    means a request that escapes is recorded and succeeds, so the assertion
    below is about what was SENT rather than about what came back."""
    anything = respx.route().mock(
        return_value=httpx.Response(200, json={"status": "deleted"}))
    out = await getattr(tool, method)(bad_id, __user__=OWNER)
    assert not anything.called, "a request was made for %r" % (bad_id,)
    assert len(respx.calls) == 0, "a request was made for %r" % (bad_id,)
    assert isinstance(out, str) and out
    assert "Done" not in out, "it must not report a change it did not make"


@respx.mock
async def test_deleting_through_a_traversal_never_reaches_connections(tool):
    """The concrete one. If this ever regresses, the person loses their
    ClickUp, Trello, GitHub, Notion or n8n credential and is told it worked."""
    connections = respx.delete(BASE + "/connections/github").mock(
        return_value=httpx.Response(200, json={"status": "deleted"}))
    vercel = respx.delete(BASE + "/vercel/connect").mock(
        return_value=httpx.Response(200, json={"status": "deleted"}))
    out = await tool.delete_schedule("../connections/github", __user__=OWNER)
    assert not connections.called
    assert not vercel.called
    assert len(respx.calls) == 0
    assert "Done, deleted" not in out


@respx.mock
async def test_a_real_id_still_goes_through(tool):
    """The guard has to refuse the escape without refusing the feature."""
    route = respx.delete(BASE + "/schedules/" + SID).mock(
        return_value=httpx.Response(200, json={"status": "deleted"}))
    out = await tool.delete_schedule(SID, __user__=OWNER)
    assert route.called
    assert out == "Done, deleted."


@respx.mock
async def test_an_id_in_another_uuid_spelling_is_normalised_not_echoed(tool):
    """uuid.UUID accepts braces, urn: and no hyphens at all. The path is
    rebuilt from the parsed value, so only the canonical form is ever sent."""
    route = respx.delete(BASE + "/schedules/" + SID).mock(
        return_value=httpx.Response(200, json={"status": "deleted"}))
    out = await tool.delete_schedule("{" + SID.upper() + "}", __user__=OWNER)
    assert route.called
    assert out == "Done, deleted."


# --------------------------------------------------- what the server refused

@respx.mock
async def test_a_refusal_the_server_explains_is_relayed(tool):
    """A person who hit the ten-schedule cap cannot learn that from "I could
    not reach your schedules just now". The endpoint already wrote the
    sentence, so say it."""
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    respx.post(BASE + "/schedules").mock(return_value=httpx.Response(
        400, json={"detail": "You already have 10 schedules. "
                             "Delete one before adding another."}))
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__=OWNER)
    assert "10 schedules" in out
    assert "Delete one before adding another." in out
    assert BASE not in out


@respx.mock
async def test_the_interval_floor_is_relayed_too(tool):
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    respx.post(BASE + "/schedules").mock(return_value=httpx.Response(
        400, json={"detail": "Schedules must be at least 15 minutes apart."}))
    out = await tool.create_schedule(name="n", cron_expr="* * * * *",
                                     prompt="p", __user__=OWNER)
    assert "15 minutes" in out
    assert BASE not in out


@respx.mock
async def test_a_write_relays_what_the_server_said(tool):
    respx.post(BASE + "/schedules/" + SID + "/enable").mock(
        return_value=httpx.Response(404, json={"detail": "not found"}))
    out = await tool.enable_schedule(SID, __user__=OWNER)
    assert "not found" in out
    assert "Done" not in out
    assert BASE not in out


@respx.mock
async def test_a_server_error_is_never_relayed_verbatim(tool):
    """A 500 body is where an unhandled exception surfaces, and this project
    has leaked a credential through error text once. Below 500 is a sentence
    the service wrote on purpose; 500 and up is not."""
    leak = "asyncpg.connect('postgres://user:hunter2@db:5432') failed"
    respx.get(BASE + "/schedules").mock(
        return_value=httpx.Response(500, json={"detail": leak}))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert leak not in out
    assert "hunter2" not in out
    assert BASE not in out
    assert isinstance(out, str) and out


@respx.mock
async def test_a_refusal_that_is_not_a_string_detail_is_not_relayed(tool):
    """FastAPI's own validation errors put a LIST of objects in detail. That
    is the API's shape, not a sentence, so it does not get read out."""
    respx.get(BASE + "/schedules").mock(return_value=httpx.Response(
        422, json={"detail": [{"loc": ["body", "cron_expr"],
                               "msg": "field required"}]}))
    out = await tool.list_my_schedules(__user__=OWNER)
    assert "loc" not in out
    assert isinstance(out, str) and out


# -------------------------------------------------------------- who is asking

@pytest.mark.parametrize("supplied", [None, "owner@example.com", 7, [], ""])
async def test_the_caller_lookup_never_raises_on_a_shape_it_did_not_expect(
        tool, supplied):
    """__user__ arrives from another process's plumbing, so it is not always
    the dict it is annotated as. _email is the sibling of _agent_id_from,
    which already guards this; a bare .get on a string is an AttributeError
    out of a method whose whole contract is that it returns a sentence.

    No respx mock: a request would error the test rather than pass it."""
    assert tool._email(supplied) == ""
    out = await tool.list_my_schedules(__user__=supplied)
    assert isinstance(out, str) and out


# ------------------------------------------------- the whole chain, for real

@respx.mock
async def test_an_agents_own_id_reaches_the_tool_through_the_real_chain():
    """The defect this closes: _run_native handed a native tool __user__ and
    nothing else, so __model__ was always {}, _agent_id_from always answered
    None, and every schedule an agent made ran through the plain executor
    instead of as the agent, without its persona or its connected tools.

    Both real paths go through that one function, so this was true of the
    agent chat panel and of scheduled runs alike. The older test passed only
    because it called create_schedule directly with __model__ supplied, which
    is the same defect shape this branch already fixed once: an assertion
    about behaviour no production caller can reach.

    So this one starts where production starts. agent_runner._chat, a fake
    Open WebUI asking for the tool, the real tool source, and a real request
    on the wire."""
    import agent_runner

    source = open(TOOL_PATH, encoding="utf-8").read()
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))

    asked = {"name": "Morning inbox", "cron_expr": "0 8 * * *",
             "prompt": "say what needs a reply"}
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "create_schedule",
                              "arguments": json.dumps(asked)}}]}}]}
        return {"choices": [{"message": {"content": "That is on for eight."}}]}

    with mock.patch.object(agent_runner, "_post_chat", new=fake_post), \
         mock.patch("agent_tools._load_native_tool_source",
                    new=AsyncMock(return_value=source)), \
         mock.patch.dict(os.environ, {"TASKS_URL": BASE}):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-research-assistant-0001",
            messages=[{"role": "user",
                       "content": "check my inbox every morning at eight"}],
            tool_ids=["schedules"], user_email="owner@example.com",
            tool_mode="full")

    assert route.called, "the tool never called /schedules"
    body = json.loads(route.calls[0].request.read())
    assert body["agent_id"] == "agent-research-assistant-0001", \
        "the schedule would run through the executor, not as the agent"
    sent = route.calls[0].request
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert answer == "That is on for eight."
    assert notes == []


@respx.mock
async def test_the_chain_cannot_be_talked_into_naming_a_different_agent():
    """__model__ is set after the model's own arguments, so a tool call that
    names it is overwritten rather than obeyed. A model that could choose the
    agent id could make a schedule run as an agent its owner did not pick."""
    import agent_runner

    source = open(TOOL_PATH, encoding="utf-8").read()
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Europe/London", "detected": True}))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=CREATED))

    asked = {"name": "n", "cron_expr": "0 8 * * *", "prompt": "p",
             "__model__": {"id": "agent-somebody-elses-9999"}}
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "create_schedule",
                              "arguments": json.dumps(asked)}}]}}]}
        return {"choices": [{"message": {"content": "done"}}]}

    with mock.patch.object(agent_runner, "_post_chat", new=fake_post), \
         mock.patch("agent_tools._load_native_tool_source",
                    new=AsyncMock(return_value=source)), \
         mock.patch.dict(os.environ, {"TASKS_URL": BASE}):
        await agent_runner._chat(
            token="t", model="agent-research-assistant-0001",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=["schedules"], user_email="owner@example.com",
            tool_mode="full")

    body = json.loads(route.calls[0].request.read())
    assert body["agent_id"] == "agent-research-assistant-0001"
    assert "9999" not in json.dumps(body)


# ---------------------------------------------------------------- installing

def test_the_install_script_never_writes_a_secret_into_the_valves():
    """Every other insert script sends internal_secret. This tool has no
    field for one, and sending it would either be dropped or, worse,
    accepted by a future edit that added the field back."""
    import pathlib
    script = pathlib.Path(__file__).resolve().parents[3] / "scripts" \
        / "insert_schedules_tool.py"
    assert script.exists(), script
    body = script.read_text(encoding="utf-8")
    assert "internal_secret" not in body
    assert "INTERNAL_CALLBACK_SECRET" not in body
    assert "schedules_tool.py" in body, "it must read the tool source"
    assert '"id": "schedules"' in body or "'id': 'schedules'" in body


def test_the_install_script_refreshes_an_existing_tool():
    """When the tool already exists, the script must call update, not create.
    Create returns 200 with null when the id is taken, which would silently
    skip the real install. The script checks if the tool exists first by
    calling GET /api/v1/tools/id/schedules, then picks the endpoint by that."""
    import pathlib
    from unittest import mock

    script_path = pathlib.Path(__file__).resolve().parents[3] / "scripts" \
        / "insert_schedules_tool.py"

    calls = []

    def mock_urlopen(request, timeout=30):
        """Simulate the API: tool exists, so GET succeeds and update is called."""
        from unittest.mock import MagicMock
        url = request.full_url
        method = request.get_method()
        calls.append((method, url))

        response = MagicMock()
        response.status = 200
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=None)

        if method == "GET" and "/id/schedules" in url and "valves" not in url:
            # GET /api/v1/tools/id/schedules -> tool exists
            response.read.return_value = b"{}"
        elif method == "POST" and "/id/schedules/update" in url:
            # POST /api/v1/tools/id/schedules/update -> update called (correct)
            response.read.return_value = b'{"id": "schedules"}'
        elif method == "POST" and "/tools/create" in url:
            # POST /api/v1/tools/create -> should NOT be called
            raise AssertionError("Should call update for existing tool, not create")
        elif method == "POST" and "/valves/update" in url:
            # POST /api/v1/tools/id/schedules/valves/update
            response.read.return_value = b"{}"
        else:
            response.read.return_value = b"{}"

        return response

    # Mock the environment and urllib
    with mock.patch.dict(os.environ, {"OPENWEBUI_API_KEY": "test-key"}):
        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
            # Import the script and run it (this executes the module-level code)
            spec = importlib.util.spec_from_file_location(
                "insert_schedules_tool_test", script_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

    # Verify GET was called to check existence
    get_calls = [url for method, url in calls if method == "GET"]
    assert any("/id/schedules" in url for url in get_calls), \
        "Should call GET to check if tool exists"

    # Verify update was called (not create)
    post_calls = [url for method, url in calls if method == "POST"]
    update_calls = [u for u in post_calls if "/update" in u and "valves" not in u]
    assert update_calls, "Should call update endpoint when tool exists"
