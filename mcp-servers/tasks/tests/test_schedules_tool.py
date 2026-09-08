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


ROW = {
    "id": "sch-1", "name": "Morning inbox", "cron_expr": "0 8 * * *",
    "tz": "Europe/London", "prompt": "what needs a reply",
    "enabled": True, "last_run_status": "ok",
    "delivery_channel_id": None, "delivery_platform": "discord",
    "kind": "agent", "agent_id": None, "tool_mode": None,
}


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
        return_value=httpx.Response(201, json=dict(ROW, tz="Europe/London")))
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
        return_value=httpx.Response(201, json=dict(ROW, tz="Asia/Manila")))
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
        return_value=httpx.Response(201, json=ROW))
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
        return_value=httpx.Response(201, json=ROW))
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
        return_value=httpx.Response(201, json=ROW))
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
async def test_a_broken_timezone_read_still_creates_the_schedule(tool):
    """Not knowing the zone is a reason to say which one was used, not a
    reason to refuse the whole request."""
    respx.get(BASE + "/prefs/timezone").mock(
        side_effect=httpx.ConnectError("down"))
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json=ROW))
    out = await tool.create_schedule(name="n", cron_expr="0 8 * * *",
                                     prompt="p", __user__=OWNER)
    assert route.called
    assert "down" not in out


@pytest.mark.parametrize("method,verb,path,response,done", [
    ("enable_schedule", "POST", "/schedules/sch-1/enable",
     {"status": "enabled"}, "turned back on"),
    ("disable_schedule", "POST", "/schedules/sch-1/disable",
     {"status": "disabled"}, "turned off"),
    ("delete_schedule", "DELETE", "/schedules/sch-1",
     {"status": "deleted"}, "deleted"),
    ("trigger_schedule_now", "POST", "/schedules/sch-1/run-now",
     {"status": "dispatched"}, "started now"),
])
@respx.mock
async def test_each_write_hits_its_own_endpoint_as_the_caller(
        tool, method, verb, path, response, done):
    """The four endpoints really reply with a status dict, not a schedule,
    so that is what is mocked here: this exercises the sentence a person
    actually gets, not the dead branch that reads an id off a row that never
    comes back."""
    route = respx.request(verb, BASE + path).mock(
        return_value=httpx.Response(200, json=response))
    out = await getattr(tool, method)("sch-1", __user__=OWNER)
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
    out = await getattr(tool, method)("sch-1", __user__={})
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
        return_value=httpx.Response(201, json={"id": "sch-9"}))
    out = await tool.create_schedule(
        name="Morning inbox", cron_expr="0 8 * * *",
        prompt="what needs a reply", __user__=OWNER)
    assert "Morning inbox" in out
    assert "0 8 * * *" in out
    assert "currently on" in out
    assert "sch-9" in out


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
