"""The chat's cron tool: email the answer, say what a job can do, and change one.

Live 2026-11-26, in the main chat: "Every Friday at 4pm, email me a summary
of this week's unread Gmail" was answered "Set up. Every Friday at 4pm you
will get an email". The job it made was read only, so the email could never
go: Run now was refused after 29 seconds. The same answer ended "ask here to
change one", and the tool had no way to change one.
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
SID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def _load():
    spec = importlib.util.spec_from_file_location("schedules_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tool():
    t = _load().Tools()
    t.valves.tasks_url = BASE
    return t


def _zone():
    respx.get(BASE + "/prefs/timezone").mock(return_value=httpx.Response(
        200, json={"timezone": "Asia/Manila", "detected": True}))


@respx.mock
async def test_email_me_is_sent_and_the_answer_says_it_will_be_emailed(tool):
    _zone()
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json={"id": SID, "email_me": True}))
    out = await tool.create_schedule(
        name="Weekly digest", cron_expr="0 16 * * 5",
        prompt="Summarize this week's unread Gmail.", email_me=True,
        __user__=OWNER)
    body = json.loads(route.calls[0].request.read())
    assert body["email_me"] is True
    assert "emailed to you" in out
    assert "cannot send" not in out, "an emailing job is not told it cannot"


@respx.mock
async def test_a_job_that_is_not_emailed_says_plainly_it_only_reads(tool):
    _zone()
    route = respx.post(BASE + "/schedules").mock(
        return_value=httpx.Response(201, json={"id": SID}))
    out = await tool.create_schedule(
        name="Inbox", cron_expr="0 9 * * 1-5", prompt="what needs a reply",
        __user__=OWNER)
    body = json.loads(route.calls[0].request.read())
    assert body["email_me"] is False
    assert "read only" in out and "cannot send, post or change" in out
    assert "email_me" in out, "the way to have it emailed instead"


@respx.mock
async def test_no_gmail_means_nothing_was_scheduled_and_why(tool):
    _zone()
    respx.post(BASE + "/schedules").mock(return_value=httpx.Response(
        400, json={"detail": "To email you the answer, connect Gmail first: "
                             "open Connections, connect Gmail, then turn this on."}))
    out = await tool.create_schedule(
        name="Weekly digest", cron_expr="0 16 * * 5", prompt="p",
        email_me=True, __user__=OWNER)
    assert out.startswith("Nothing was scheduled")
    assert "connect Gmail" in out


def test_the_create_docstring_says_when_to_email_and_what_a_job_cannot_do():
    doc = _load().Tools.create_schedule.__doc__
    assert ":param email_me:" in doc
    assert "email me" in doc.lower()
    assert "only read" in doc.lower()


# --- changing one ----------------------------------------------------------------

@respx.mock
async def test_a_change_sends_only_what_was_given(tool):
    route = respx.patch(BASE + "/schedules/" + SID).mock(
        return_value=httpx.Response(200, json={"status": "updated"}))
    out = await tool.update_schedule(SID, cron_expr="0 17 * * 5", __user__=OWNER)
    sent = route.calls[0].request
    assert json.loads(sent.read()) == {"cron_expr": "0 17 * * 5"}
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert out.startswith("Done") and "0 17 * * 5" in out


@respx.mock
async def test_a_change_can_turn_email_on(tool):
    route = respx.patch(BASE + "/schedules/" + SID).mock(
        return_value=httpx.Response(200, json={"status": "updated"}))
    out = await tool.update_schedule(SID, email_me=True, __user__=OWNER)
    assert json.loads(route.calls[0].request.read()) == {"email_me": True}
    assert "emailed to you" in out


async def test_a_change_with_nothing_in_it_sends_nothing(tool):
    out = await tool.update_schedule(SID, __user__=OWNER)
    assert "nothing" in out.lower()


async def test_a_change_to_an_id_that_is_not_one_sends_nothing(tool):
    out = await tool.update_schedule("../connections/github", name="x",
                                     __user__=OWNER)
    assert "not one of your schedule ids" in out


async def test_a_change_with_no_email_sends_nothing(tool):
    out = await tool.update_schedule(SID, name="x", __user__={})
    assert isinstance(out, str) and out


@respx.mock
async def test_a_refused_change_relays_why(tool):
    respx.patch(BASE + "/schedules/" + SID).mock(return_value=httpx.Response(
        400, json={"detail": "invalid cron_expr"}))
    out = await tool.update_schedule(SID, cron_expr="nope", __user__=OWNER)
    assert "invalid cron_expr" in out and not out.startswith("Done")


def test_changing_is_a_write():
    from agent_tools import is_write_tool
    assert is_write_tool("update_schedule") is True


def test_a_listed_job_says_when_it_is_emailed():
    t = _load().Tools()
    row = {"id": SID, "name": "Weekly digest", "cron_expr": "0 16 * * 5",
           "tz": "Asia/Manila", "enabled": True, "email_me": True}
    assert "emailed to you" in t._describe(row)
    row["email_me"] = False
    assert "emailed" not in t._describe(row)
