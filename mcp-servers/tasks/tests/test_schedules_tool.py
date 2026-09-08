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
