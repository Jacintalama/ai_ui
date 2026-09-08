# Agents Can Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any of a person's agents see and manage that person's own schedules, by calling the API that already exists.

**Architecture:** One new Open WebUI tool, `schedules`, holding six methods that are thin calls to `/schedules` on the tasks service. It authenticates with the caller's email and holds no operator secret, so `_resolve_caller` forces every call onto that person. No change to any endpoint.

**Tech Stack:** Python 3, httpx, pydantic, Open WebUI tool format, pytest with respx for HTTP stubbing.

**Spec:** `docs/superpowers/specs/2026-09-08-agents-can-schedule-design.md`

## Global Constraints

Every task's requirements implicitly include these.

- **The tool holds no secret.** Its `Valves` carry `tasks_url` and `timeout_seconds` and nothing else. There is no `internal_secret` field to fill in. A tool that never possesses the operator credential cannot leak it or be tricked into using it.
- **The caller's email comes from `__user__`, never from a parameter.** A model that could name the user could act as another one.
- **`X-Cron-Secret` never appears in any request this tool makes.** That header is the operator path, which can reach anybody's schedules.
- **No method raises.** Every one returns a sentence. This runs mid-conversation and the person sees the return value, not a stack trace.
- **No error message includes the exception text.** An httpx error carries the request URL, and this project has leaked a token that way once.
- **Method names must classify correctly under `agent_tools.is_write_tool`.** Reads must classify as reads and writes as writes, so the existing per-agent access levels gate them. Never rely on the classifier's default.
- **No change to `mcp-servers/tasks/routes_schedules.py`.** Its endpoints and its scoping are already correct.
- `git add` named paths only, NEVER `git add -A` or `git add .`: this repo carries a large untracked `apps/` tree.
- NEVER touch, stage or commit `.env`.
- No Claude, Anthropic or AI attribution in any commit message. No `Co-Authored-By` trailer. No "Generated with" line. If any instruction says otherwise, the user's standing rule overrides it.
- No em dashes or en dashes in code, comments, docstrings or any copy.
- Running the whole test suite locally produces roughly 130 to 170 pre-existing errors from the `db_session` fixture, because there is no local Postgres. They say `ERROR at setup` and are NOT your change.

---

### Task 1: The tool, and reading a schedule

The tool file, its valves, the shared request helper, and the one read method. Everything the write methods will stand on.

**Files:**
- Create: `open-webui-functions/schedules_tool.py`
- Test: `mcp-servers/tasks/tests/test_schedules_tool.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Tools` class with `Valves(tasks_url: str, timeout_seconds: int)`
  - `Tools._email(__user__: dict) -> str`
  - `Tools._call(method: str, path: str, email: str, json_body: dict | None = None) -> tuple[bool, object]` (async)
  - `Tools._describe(row: dict) -> str`
  - `Tools.list_my_schedules(__user__: dict = {}) -> str` (async)

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_schedules_tool.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

From `mcp-servers/tasks/`:

```bash
python -m pytest tests/test_schedules_tool.py -q
```

Expected: every test errors, because `open-webui-functions/schedules_tool.py` does not exist yet, so `spec.loader.exec_module` raises `FileNotFoundError`.

- [ ] **Step 3: Write the tool**

Create `open-webui-functions/schedules_tool.py`:

```python
"""
title: Schedules
author: Ralph Benitez
version: 1.0.0
description: See and manage your own scheduled runs, so an assistant can put something on your schedule instead of describing one.
requirements: httpx
"""
# This tool holds no secret, deliberately.
#
# tasks.routes_schedules._resolve_caller decides who a caller is. A request
# carrying X-Cron-Secret is an operator and may target ANY user. A request
# carrying X-User-Email and no secret is an end user, and is forced onto that
# email: the listing is filtered by it, and a create overwrites whatever
# user_email the body claimed.
#
# So this tool sends the caller's email and nothing else. The dangerous path,
# the one that can delete somebody else's schedules, needs a credential this
# file does not have and has no field to store.
import os

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(
            default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    # ------------------------------------------------------------------ plumbing

    def _email(self, __user__: dict) -> str:
        """Who is asking, from Open WebUI rather than from a parameter.

        Never a method argument: a model that could name the user could act
        as another one.
        """
        return ((__user__ or {}).get("email") or "").strip()

    async def _call(self, method: str, path: str, email: str,
                    json_body: dict = None):
        """One request as this person. Returns (ok, data) or (False, sentence).

        Never raises, and never includes the exception text: an httpx error
        carries the request URL, and this project has leaked a token that way
        once.
        """
        url = self.valves.tasks_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(
                    timeout=self.valves.timeout_seconds) as client:
                response = await client.request(
                    method, url,
                    headers={"X-User-Email": email},
                    json=json_body)
                response.raise_for_status()
                return True, (response.json() if response.content else {})
        except Exception:                                   # noqa: BLE001
            return False, "I could not reach your schedules just now."

    def _describe(self, row: dict) -> str:
        """One schedule as a person reads it, not as the API returns it."""
        row = row if isinstance(row, dict) else {}
        name = str(row.get("name") or "unnamed")
        when = str(row.get("cron_expr") or "?")
        tz = str(row.get("tz") or "")
        state = "on" if row.get("enabled") else "off"
        said = '"%s" runs on %s' % (name, when)
        if tz:
            said += " (%s)" % tz
        said += ", currently %s" % state
        last = row.get("last_run_status")
        if last:
            said += ", last run %s" % str(last)
        return said + " [id %s]" % str(row.get("id") or "?")

    # --------------------------------------------------------------- reading

    async def list_my_schedules(self, __user__: dict = {}) -> str:
        """
        List this person's scheduled runs: what each one does, when it runs,
        whether it is on, and how the last run went.

        Call this whenever they ask what is scheduled, what runs
        automatically, what their cron jobs are, or whether something is
        still running. Call it before changing or deleting one, so the id you
        act on belongs to a schedule that exists.
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedules these are, so I did not look."
        ok, data = await self._call("GET", "/schedules", email)
        if not ok:
            return data
        if not isinstance(data, list):
            return "Your schedules came back in a shape I did not understand."
        if not data:
            return "You have nothing scheduled."
        lines = ["You have %d scheduled:" % len(data)]
        for row in data:
            lines.append("  " + self._describe(row))
        return "\n".join(lines)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_schedules_tool.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add open-webui-functions/schedules_tool.py \
        mcp-servers/tasks/tests/test_schedules_tool.py
git commit -m "Let an agent see what its owner has scheduled"
```

---

### Task 2: Putting something on the schedule

The five write methods, the timezone read, and the rule that a schedule an agent creates runs as that agent.

**Files:**
- Modify: `open-webui-functions/schedules_tool.py` (append methods)
- Test: `mcp-servers/tasks/tests/test_schedules_tool.py` (append tests)

**Interfaces:**
- Consumes: `_email`, `_call`, `_describe` from Task 1.
- Produces:
  - `Tools._timezone_for(email: str) -> tuple[str, bool]` (async), returning (zone, detected)
  - `Tools._agent_id_from(__model__: dict) -> str | None`
  - `Tools.create_schedule(name, cron_expr, prompt, __user__={}, __model__={}) -> str` (async)
  - `Tools.enable_schedule(schedule_id, __user__={}) -> str` (async)
  - `Tools.disable_schedule(schedule_id, __user__={}) -> str` (async)
  - `Tools.delete_schedule(schedule_id, __user__={}) -> str` (async)
  - `Tools.trigger_schedule_now(schedule_id, __user__={}) -> str` (async)

- [ ] **Step 1: Write the failing test**

Append to `mcp-servers/tasks/tests/test_schedules_tool.py`:

```python


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
    body = route.calls[0].request.read().decode()
    assert '"tz": "Europe/London"' in body.replace("'", '"')
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
    body = route.calls[0].request.read().decode().replace("'", '"')
    assert '"agent_id": "agent-research-assistant-0001"' in body


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
    body = route.calls[0].request.read().decode().replace("'", '"')
    assert '"agent_id": null' in body or "agent_id" not in body


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


@pytest.mark.parametrize("method,verb,path", [
    ("enable_schedule", "POST", "/schedules/sch-1/enable"),
    ("disable_schedule", "POST", "/schedules/sch-1/disable"),
    ("delete_schedule", "DELETE", "/schedules/sch-1"),
    ("trigger_schedule_now", "POST", "/schedules/sch-1/run-now"),
])
@respx.mock
async def test_each_write_hits_its_own_endpoint_as_the_caller(
        tool, method, verb, path):
    route = respx.request(verb, BASE + path).mock(
        return_value=httpx.Response(200, json=ROW))
    out = await getattr(tool, method)("sch-1", __user__=OWNER)
    sent = route.calls[0].request
    assert sent.headers["X-User-Email"] == "owner@example.com"
    assert "x-cron-secret" not in {k.lower() for k in sent.headers}
    assert isinstance(out, str) and out


@pytest.mark.parametrize("method", [
    "enable_schedule", "disable_schedule", "delete_schedule",
    "trigger_schedule_now",
])
async def test_no_email_stops_every_write_before_it_calls(tool, method):
    """No respx mock: a call would error the test rather than pass it."""
    out = await getattr(tool, method)("sch-1", __user__={})
    assert isinstance(out, str) and out
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_schedules_tool.py -q
```

Expected: the Task 1 tests still pass; every new test fails with `AttributeError: 'Tools' object has no attribute 'create_schedule'` or similar.

- [ ] **Step 3: Write the write methods**

Append to `open-webui-functions/schedules_tool.py`:

```python
    # --------------------------------------------------------------- writing

    async def _timezone_for(self, email: str):
        """(zone, detected) for this person.

        /prefs/timezone always returns a zone plus a `detected` flag, so a
        caller never has to know what the platform default is. A failed read
        is not a reason to refuse a schedule, only a reason to say which zone
        was used.
        """
        ok, data = await self._call("GET", "/prefs/timezone", email)
        if not ok or not isinstance(data, dict):
            return "", False
        zone = data.get("timezone")
        return (str(zone) if zone else ""), bool(data.get("detected"))

    def _agent_id_from(self, __model__: dict):
        """The agent making this call, when the caller IS an agent.

        A schedule an agent creates should run as that agent. But this tool
        is on every model, and "gpt-5" is not one of this person's agents:
        sending it as agent_id would make a schedule that can never run. Only
        an id shaped like one this platform mints is passed on.
        """
        model_id = str((__model__ or {}).get("id") or "")
        return model_id if model_id.startswith("agent-") else None

    async def create_schedule(self, name: str, cron_expr: str, prompt: str,
                              __user__: dict = {}, __model__: dict = {}) -> str:
        """
        Put something on this person's schedule, so it runs by itself from
        now on.

        Call this when they ask for something to happen regularly or at a
        set time: "check my inbox every morning at eight", "remind me on
        Fridays", "run this every hour".

        :param name: A short name they will recognise on their Cron Jobs
            page, e.g. "Morning inbox".
        :param cron_expr: Five-field cron. "0 8 * * *" is every day at eight
            in the morning. "0 9 * * 1" is nine on Mondays. "0 * * * *" is
            hourly.
        :param prompt: What should happen when it runs, written as an
            instruction, e.g. "list my unread email and say what needs a
            reply today".
        """
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule this is, so I did not make one."

        zone, detected = await self._timezone_for(email)
        body = {"name": name, "cron_expr": cron_expr, "prompt": prompt,
                "agent_id": self._agent_id_from(__model__)}
        if zone:
            body["tz"] = zone

        ok, data = await self._call("POST", "/schedules", email, body)
        if not ok:
            return "I could not put that on your schedule just now, so nothing was made."
        if not isinstance(data, dict) or not data.get("id"):
            return "Your schedule may not have been made: the reply did not name one."

        said = "Done. " + self._describe(data) + "."
        if zone and not detected:
            said += (" I used %s, because I have no timezone recorded for you. "
                     "Tell me your zone if that is wrong." % zone)
        said += (" The result will appear on your Cron Jobs page, since this "
                 "was not made from a chat channel.")
        return said

    async def enable_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules back on, so it runs again.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/enable" % schedule_id, __user__,
            "turned back on")

    async def disable_schedule(self, schedule_id: str,
                               __user__: dict = {}) -> str:
        """
        Turn one of this person's schedules off, leaving it in place so it
        can be turned back on later. Prefer this to deleting when they say
        pause, stop for now, or hold off.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/disable" % schedule_id, __user__,
            "turned off")

    async def delete_schedule(self, schedule_id: str,
                              __user__: dict = {}) -> str:
        """
        Delete one of this person's schedules for good. This cannot be
        undone, so prefer disable_schedule unless they clearly want it gone.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "DELETE", "/schedules/%s" % schedule_id, __user__, "deleted")

    async def trigger_schedule_now(self, schedule_id: str,
                                   __user__: dict = {}) -> str:
        """
        Run one of this person's schedules right now, without waiting for
        its next scheduled time. Leaves the schedule itself unchanged.

        Call list_my_schedules first if you do not already have the id.
        """
        return await self._simple_write(
            "POST", "/schedules/%s/run-now" % schedule_id, __user__,
            "started now")

    async def _simple_write(self, method: str, path: str, __user__: dict,
                            done: str) -> str:
        """The four one-line writes, which differ only in verb, path and the
        word used to report success."""
        email = self._email(__user__)
        if not email:
            return "I could not tell whose schedule that is, so I left it alone."
        ok, data = await self._call(method, path, email)
        if not ok:
            return "I could not change that schedule just now, so nothing happened."
        if isinstance(data, dict) and data.get("id"):
            return "Done, %s: %s." % (done, self._describe(data))
        return "Done, %s." % done
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_schedules_tool.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run the safety classifier tests too**

The method names are only correct if the real classifier agrees.

```bash
python -m pytest tests/test_schedules_tool.py tests/test_agent_tools_classify.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add open-webui-functions/schedules_tool.py \
        mcp-servers/tasks/tests/test_schedules_tool.py
git commit -m "Let an agent put something on its owner's schedule"
```

---

### Task 3: Installing it

The script that puts the tool into Open WebUI. Without this the file is inert: a tool with no row and no generated specs is invisible to every model.

**Files:**
- Create: `scripts/insert_schedules_tool.py`
- Test: `mcp-servers/tasks/tests/test_schedules_tool.py` (append one test)

**Interfaces:**
- Consumes: `open-webui-functions/schedules_tool.py` from Tasks 1 and 2.
- Produces: a runnable script; no importable interface.

- [ ] **Step 1: Write the failing test**

Append to `mcp-servers/tasks/tests/test_schedules_tool.py`:

```python


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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/test_schedules_tool.py -q -k install
```

Expected: FAIL with `AssertionError` on `script.exists()`.

- [ ] **Step 3: Write the install script**

Create `scripts/insert_schedules_tool.py`:

```python
"""Install/refresh the "Schedules" tool via the OWUI API.

Run on the server:
  OPENWEBUI_API_KEY=sk-... python3 scripts/insert_schedules_tool.py

Reads the tool source from open-webui-functions/schedules_tool.py, creates or
updates tool id `schedules`, then writes its valves. OWUI computes the
function specs from the content during create/update, and a tool without
generated specs is invisible to every model.

Note what is missing: there is no INTERNAL_CALLBACK_SECRET here. Every other
insert script in this directory passes one. This tool authenticates with the
caller's own email and must never hold the operator credential, so there is
nothing to pass and no valve to put it in.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

src = open(os.path.join(os.path.dirname(__file__), "..",
                        "open-webui-functions", "schedules_tool.py"),
           encoding="utf-8").read()


def call(path, payload=None, method="POST"):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


body = {"id": "schedules", "name": "Schedules", "content": src,
        "meta": {"description": "See and manage your own scheduled runs"},
        "access_control": None}
status, out = call("/api/v1/tools/create", body)
if status != 200:
    status, out = call("/api/v1/tools/id/schedules/update", body)
print("tool upsert:", status)
if status != 200:
    sys.exit(f"tool upsert failed: {out}")

valves = {"tasks_url": "http://tasks:8210", "timeout_seconds": 30}
status, out = call("/api/v1/tools/id/schedules/valves/update", valves)
print("valves:", status)
if status != 200:
    sys.exit(f"valves update failed: {out}")

print("installed. Every agent reaches it through _every_tool_for, which reads "
      "public.tool, so no per-agent change is needed.")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python -m pytest tests/test_schedules_tool.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/insert_schedules_tool.py \
        mcp-servers/tasks/tests/test_schedules_tool.py
git commit -m "Install the schedules tool without an operator secret"
```

---

### Task 4: Prove it on the real site

**STOP. Do not deploy or install without Ralph saying yes.** Deploying is his call every time.

**Files:**
- No new files. `.deploy-state` is written by the deploy step, not by hand.

- [ ] **Step 1: Ask, and wait**

Tell Ralph exactly this: nothing here changes a running service, because the tool is a database row in Open WebUI rather than code in a container. The install script needs `OPENWEBUI_API_KEY` and adds one row to `public.tool`. Every agent picks it up automatically, because `_every_tool_for` reads `public.tool` at turn time. Rolling it back is deleting that row. Then wait for a yes.

- [ ] **Step 2: Deploy the tool source and run the installer**

The tool file is not read by any container, so only the script and the source need to reach the box.

```bash
scp open-webui-functions/schedules_tool.py \
    root@46.224.193.25:/root/proxy-server/open-webui-functions/schedules_tool.py
scp scripts/insert_schedules_tool.py \
    root@46.224.193.25:/root/proxy-server/scripts/insert_schedules_tool.py
ssh root@46.224.193.25 "cd /root/proxy-server && sed -i 's/\r$//' open-webui-functions/schedules_tool.py scripts/insert_schedules_tool.py"
```

Then run the installer on the box, reading the key from the server's own `.env` and never printing it:

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && set -a && . ./.env && set +a && OPENWEBUI_URL=http://localhost:3000 python3 scripts/insert_schedules_tool.py"
```

Expected: `tool upsert: 200` then `valves: 200`.

- [ ] **Step 3: Confirm the row and its specs**

A tool without generated specs is invisible to every model, so check the specs exist rather than only the row.

```bash
ssh root@46.224.193.25 'docker exec postgres sh -c "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -tAc \"select id, jsonb_array_length(specs::jsonb) from public.tool where id='"'"'schedules'"'"'\""'
```

Expected: `schedules|6`.

- [ ] **Step 4: Confirm every agent can now reach it**

```bash
ssh root@46.224.193.25 'docker exec tasks python -c "
import asyncio, routes_agent_turn as rt
print(asyncio.run(rt._every_tool_for(\"ralphbenitez32@gmail.com\")))
"'
```

Expected: the list now contains `schedules`.

- [ ] **Step 5: Run a real turn that reads**

Reading is safe and needs no access level, so it proves the wiring without changing anything.

```bash
ssh root@46.224.193.25 'docker exec tasks python -c "
import asyncio, routes_agent_turn as rt
async def m():
    out = await rt._run_turn(\"ralphbenitez32@gmail.com\", \"agent-research-assistant-0001\",
        [{\"role\":\"user\",\"content\":\"What do I have scheduled?\"}])
    print(\"ANSWER:\", (out.get(\"answer\") or \"\")[:600])
    print(\"NOTES:\", out.get(\"notes\"))
asyncio.run(m())
"'
```

Expected: an answer naming real schedules, or "You have nothing scheduled", and `NOTES: []` with no refusal.

- [ ] **Step 6: Hand the write test to Ralph**

A write needs an access level, and both his agents currently have none, so a write will be refused until he sets one. That is correct behaviour, not a bug. Tell him: set an agent to "With access" on its card, then ask it in the panel to schedule something, approve when it asks, and check the Cron Jobs page.

Do not set that level for him. It is the one control that decides what his agents may do.

- [ ] **Step 7: Commit nothing**

There is nothing to commit in this task. The code was committed in Tasks 1 to 3, and the install writes a database row.

---

## Notes for whoever executes this

- `respx` is already used by `tests/test_agents_tool.py`, so it is available. Async tests need no decorator: `pytest.ini` sets `asyncio_mode = auto`.
- Where a test is both parametrized and mocked, `@pytest.mark.parametrize` goes outermost and `@respx.mock` inside it. The other way round, respx wraps the function pytest is parametrizing and the cases do not collect as you expect. The last test needs no `@respx.mock` at all, deliberately: it asserts nothing is called, so an unmocked request errors the test rather than passing it.
- The tool file lives outside the tasks service and nothing imports it, so the tests load it by path with `importlib.util.spec_from_file_location`. Copy that from `tests/test_agents_tool.py` rather than inventing a way.
- If a step's expected output does not match, stop and say so rather than adjusting the test to fit. Every real defect in this feature's history was found by running code against reality.
