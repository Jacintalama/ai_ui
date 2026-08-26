# Agent Tool Execution, Phase 1, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a scheduled agent actually run its tools, with the owner choosing per schedule whether it may only read or may also write.

**Architecture:** Open WebUI already injects each agent's tool specs and returns `tool_calls`; it just never executes them. `tasks` gains a loop that executes the requested call as the schedule's owner and hands the result back, repeating until the model answers. Tools are executed by loading each tool's own source from `public.tool` and calling it the way Open WebUI does, or by posting to `mcp-proxy`'s `/meta/call_tool` for proxy-backed tools.

**Tech Stack:** Python 3.11, FastAPI, httpx, asyncpg/SQLAlchemy, pytest with `asyncio_mode = auto`, plain HTML/JS for the Cron page.

## Global Constraints

- Never add Claude, Anthropic, or any AI attribution to commits, PRs, code comments, or docs. Author is Ralph Benitez only.
- No em-dashes or en-dashes in anything a person reads, including UI copy, run results, and commit messages.
- Never log or store a minted token, and never include an httpx exception's own text in a user-visible message: it can carry the request URL, and this project has already leaked a token that way.
- Every failure must still end in a message the schedule's owner can read.
- A schedule with `agent_id IS NULL` must behave exactly as it does today. That is every schedule currently on production.
- Unknown tool methods are classified as WRITE. The default must fail toward refusing, never toward acting.
- Tools are executed as the schedule's OWNER, never as a fixed or ambient identity.
- `read_only` is the default for any schedule that does not specify a mode, including every existing row.
- Do not deploy, do not touch the server, do not touch `.env`.
- Local test runs show roughly 130 pre-existing `ERROR at setup` failures from `db_session` (no local Postgres). Those are not your change. Confirm any failure you see says `ERROR at setup` before worrying about it.

---

## File Structure

| Path | Responsibility |
|---|---|
| `mcp-servers/tasks/agent_tools.py` | NEW. Classify a tool method as read or write; execute one tool call as a given user. The only file that knows how a tool is invoked. |
| `mcp-servers/tasks/agent_runner.py` | MODIFY. Replace the single-shot `_chat` with a loop that executes tool calls and feeds results back. |
| `mcp-servers/tasks/migrations/042_schedule_tool_mode.sql` | NEW. Add the nullable `tool_mode` column. |
| `mcp-servers/tasks/models.py` | MODIFY. Add `tool_mode` to the `Schedule` model. |
| `mcp-servers/tasks/routes_schedules.py` | MODIFY. Accept and return `tool_mode`. |
| `mcp-servers/tasks/static/cron.html` | MODIFY. A "Tool access" control, and the mode on the schedule card. |

Tasks 1 and 2 are independent of 3 and 4, but Task 5 consumes all of them.

---

### Task 1: Classify a tool method as read or write

**Files:**
- Create: `mcp-servers/tasks/agent_tools.py`
- Test: `mcp-servers/tasks/tests/test_agent_tools_classify.py`

**Interfaces:**
- Produces: `is_write_tool(method_name: str) -> bool`, and the module constant `READ_METHODS: frozenset[str]`.

Context: the seven native Open WebUI tools and their methods were read off production. Every one of them is classified correctly by the verb rule alone, but the explicit set is kept as a pin so that renaming a method cannot silently flip its classification without a test failing.

- [ ] **Step 1: Write the failing test**

```python
"""The read/write split that decides what an unattended agent may do.

Worth testing hard: a classifier that returned False for everything would
let a 7am cron send mail, and would pass any test that only checked reads.
So the writes are asserted individually, by name, from the real tool list.
"""
import pytest

from agent_tools import is_write_tool


READS = [
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",            # gmail
    "list_calendar_events",                   # calendar
    "list_drive_files", "search_drive", "read_drive_file",   # gdrive
]

WRITES = [
    "draft_email", "reply_to_email", "send_email",           # gmail
    "create_calendar_event", "update_calendar_event",
    "delete_calendar_event",                                 # calendar
    "create_document",                                       # documents
    "create_excel", "create_simple_excel",                   # excel_creator
    "create_dashboard", "create_simple_dashboard",           # executive_dashboard
    "upload_drive_file",                                     # gdrive
    "remember",                                              # remember
]


@pytest.mark.parametrize("name", READS)
def test_reads_are_not_writes(name):
    assert is_write_tool(name) is False


@pytest.mark.parametrize("name", WRITES)
def test_writes_are_writes(name):
    assert is_write_tool(name) is True


def test_an_unknown_method_counts_as_a_write():
    """The default has to fail toward refusing. A tool nobody classified
    must not be able to act unattended."""
    assert is_write_tool("frobnicate_the_widget") is True


def test_an_empty_name_counts_as_a_write():
    assert is_write_tool("") is True


def test_classification_ignores_case_and_server_prefix():
    """Proxy tools arrive qualified, e.g. clickup_create_task, and casing
    is not guaranteed."""
    assert is_write_tool("SEARCH_emails") is False
    assert is_write_tool("clickup_create_task") is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_classify.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_tools'`

- [ ] **Step 3: Write the implementation**

```python
"""Deciding what an agent may do, and doing it.

Split out of agent_runner because it is the part with teeth: agent_runner
decides what to say, this decides what actually happens to someone's mail.
"""
import logging

logger = logging.getLogger(__name__)

#: Verb prefixes that only ever read. Anything else is treated as a write.
#: Deliberately a prefix rule and not a substring one: "unread" contains
#: "read" and delete_calendar_event contains "eve", and a substring rule
#: would quietly reclassify both.
_READ_PREFIXES = (
    "list_", "get_", "search_", "read_", "fetch_", "find_",
    "describe_", "count_",
)

#: The native tools, pinned by name. The verb rule already agrees with every
#: one of these; they are written out so that renaming a method has to break
#: a test rather than silently change what an unattended agent may do.
READ_METHODS = frozenset({
    "list_unread_emails", "list_important_emails", "list_recent_emails",
    "search_emails", "read_email",
    "list_calendar_events",
    "list_drive_files", "search_drive", "read_drive_file",
})


def is_write_tool(method_name: str) -> bool:
    """True when calling this method could change something.

    Unknown counts as a write. That is the whole point: the classifier is
    consulted before an unattended run is allowed to act, so the failure
    direction has to be refusal.
    """
    name = (method_name or "").strip().lower()
    if not name:
        return True
    if name in READ_METHODS:
        return False
    # Proxy tools arrive server-qualified (clickup_create_task). Match the
    # verb anywhere a segment starts, not just at the front of the string.
    for prefix in _READ_PREFIXES:
        if name.startswith(prefix) or ("_" + prefix) in name:
            return False
    return True
```

- [ ] **Step 4: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_classify.py -q`
Expected: PASS, 25 passed (parametrize expands READS and WRITES)

- [ ] **Step 5: Prove the test bites**

Temporarily change `is_write_tool` to `return False` and re-run. Every test in `WRITES` plus both default tests must fail. Restore afterwards. A classifier is exactly the kind of function that passes a weak suite while being wrong, so confirm this by hand.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_tools.py mcp-servers/tasks/tests/test_agent_tools_classify.py
git commit -m "feat(agents): classify tool methods as read or write

Unknown counts as a write, so a tool nobody classified cannot act on a
schedule with nobody watching."
```

---

### Task 2: Execute one tool call as a given user

**Files:**
- Modify: `mcp-servers/tasks/agent_tools.py`
- Test: `mcp-servers/tasks/tests/test_agent_tools_execute.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond living in the same module.
- Produces: `async def execute_tool_call(tool_call: dict, user_email: str) -> str`, which always returns a string suitable to hand back to the model as a tool result, and never raises.

Context, all verified on production:

- The native tools are rows in `public.tool` with a `content` column holding a Python module that defines `class Tools` with async methods taking `__user__: dict`. Gmail's whole job is to POST to `http://mcp-gmail:8000`. Open WebUI executes these by exec'ing that source, so we do the same, which keeps one source of truth for the method-to-endpoint mapping.
- Proxy-backed tools are executed with `POST {MCP_PROXY_URL}/meta/call_tool`, body `{"tool_name": ..., "arguments": {...}}`, identity via the `X-User-Email` header. That endpoint does its own per-user access check and returns 403 when the user may not reach that server.
- A tool call from the model looks like `{"id": "call_abc", "function": {"name": "list_unread_emails", "arguments": "{\"max_results\": 5}"}}`. `arguments` is a JSON **string**.

- [ ] **Step 1: Write the failing test**

```python
"""Executing a tool call on someone's behalf.

The identity assertions here are the point. A previous review found two
mutations of this codebase's identity resolution that passed every test,
so every path below asserts WHOSE account was used, by value.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent_tools import execute_tool_call


def _call(name, args=None, cid="call_1"):
    return {"id": cid, "function": {"name": name,
                                    "arguments": json.dumps(args or {})}}


async def test_a_native_tool_runs_as_the_named_user():
    """The tool's own source is loaded and called with that user's email."""
    source = (
        "class Tools:\n"
        "    async def list_unread_emails(self, max_results=15, __user__=None):\n"
        "        return 'seen-by:' + (__user__ or {}).get('email', 'nobody')\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(_call("list_unread_emails"),
                                      "owner@example.com")
    assert out == "seen-by:owner@example.com"


async def test_arguments_are_decoded_from_the_json_string():
    source = (
        "class Tools:\n"
        "    async def search_emails(self, query='', __user__=None):\n"
        "        return 'q=' + query\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(
            _call("search_emails", {"query": "invoices"}), "owner@example.com")
    assert out == "q=invoices"


async def test_a_proxy_tool_is_called_with_the_users_email_header():
    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(200, {"result": "ok"})

    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json", new=fake_post):
        out = await execute_tool_call(
            _call("clickup_list_tasks"), "owner@example.com")

    assert captured["headers"]["X-User-Email"] == "owner@example.com"
    assert captured["json"]["tool_name"] == "clickup_list_tasks"
    assert "/meta/call_tool" in captured["url"]
    assert "ok" in out


async def test_a_failing_tool_returns_an_error_string_and_does_not_raise():
    """The loop must be able to hand the failure to the model and let it
    explain itself, rather than dying and losing the whole run."""
    source = (
        "class Tools:\n"
        "    async def read_email(self, __user__=None):\n"
        "        raise RuntimeError('mailbox on fire')\n"
    )
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=source)):
        out = await execute_tool_call(_call("read_email"), "owner@example.com")
    assert "could not" in out.lower() or "error" in out.lower()


async def test_an_unknown_tool_returns_a_message_rather_than_raising():
    with patch("agent_tools._load_native_tool_source",
               new=AsyncMock(return_value=None)), \
         patch("agent_tools._post_json",
               new=AsyncMock(return_value=_FakeResponse(404, {"detail": "no"}))):
        out = await execute_tool_call(_call("nope_nope"), "owner@example.com")
    assert isinstance(out, str) and out


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_execute.py -q`
Expected: FAIL, `ImportError: cannot import name 'execute_tool_call'`

- [ ] **Step 3: Write the implementation**

Append to `mcp-servers/tasks/agent_tools.py`:

```python
import json
import os

import httpx

from db import session
from sqlalchemy import text as sql_text

#: A single tool call gets less than the whole run's budget: several may be
#: needed before the agent can answer.
TOOL_TIMEOUT_SECONDS = 60


def _proxy_url() -> str:
    return os.environ.get("MCP_PROXY_URL", "http://mcp-proxy:8000").rstrip("/")


async def _post_json(url, json=None, headers=None, timeout=None):
    async with httpx.AsyncClient(timeout=timeout or TOOL_TIMEOUT_SECONDS) as c:
        return await c.post(url, json=json, headers=headers)


async def _load_native_tool_source(method_name: str) -> str | None:
    """The source of the native Open WebUI tool defining this method.

    Open WebUI keeps each tool as a Python module in public.tool.content and
    exec's it to call the method. Doing the same keeps one source of truth
    for how a tool reaches its service: the Gmail tool, for instance, is a
    thin client for mcp-gmail, and duplicating that mapping here would drift
    the first time somebody edits the tool in the web UI.
    """
    async with session() as s:
        rows = (await s.execute(
            sql_text("SELECT content FROM public.tool"))).fetchall()
    needle = "def " + method_name + "("
    for (content,) in rows:
        if content and needle in content:
            return content
    return None


async def _run_native(source: str, method_name: str, params: dict,
                      user_email: str) -> str:
    namespace: dict = {}
    exec(compile(source, "<owui_tool>", "exec"), namespace)   # noqa: S102
    tools_cls = namespace.get("Tools")
    if tools_cls is None:
        raise RuntimeError("tool module defines no Tools class")
    instance = tools_cls()
    method = getattr(instance, method_name, None)
    if method is None:
        raise RuntimeError("tool module has no method " + method_name)
    result = await method(__user__={"email": user_email}, **params)
    return result if isinstance(result, str) else json.dumps(result)


async def execute_tool_call(tool_call: dict, user_email: str) -> str:
    """Run one tool call as `user_email` and return a string for the model.

    Never raises. A tool that fails returns its failure as the tool result so
    the agent can say what went wrong, which is far more useful to the owner
    than a run that dies with nothing.
    """
    fn = (tool_call or {}).get("function") or {}
    name = (fn.get("name") or "").strip()
    raw_args = fn.get("arguments") or "{}"
    try:
        params = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except ValueError:
        params = {}
    if not isinstance(params, dict):
        params = {}

    if not name:
        return "That tool call named no tool, so nothing was run."

    try:
        source = await _load_native_tool_source(name)
        if source:
            return await _run_native(source, name, params, user_email)

        response = await _post_json(
            _proxy_url() + "/meta/call_tool",
            json={"tool_name": name, "arguments": params},
            headers={"X-User-Email": user_email},
            timeout=TOOL_TIMEOUT_SECONDS)
        if response.status_code == 403:
            return ("You do not have access to the service behind the tool "
                    + name + ".")
        if response.status_code == 404:
            return "The tool " + name + " is not available."
        if response.status_code >= 400:
            return "The tool " + name + " could not be run this time."
        payload = response.json()
        return payload if isinstance(payload, str) else json.dumps(payload)
    except Exception:                                       # noqa: BLE001
        # Never surface the exception text: an httpx error carries the URL.
        logger.error("tool call %s failed", name, exc_info=True)
        return "The tool " + name + " could not be run this time."
```

- [ ] **Step 4: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_execute.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Prove the identity test bites**

Change `_run_native` to pass a hardcoded `{"email": "someone@else.com"}` and re-run. `test_a_native_tool_runs_as_the_named_user` must fail. Change `execute_tool_call` to send no `X-User-Email` header and re-run; the proxy test must fail. Restore both.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_tools.py mcp-servers/tasks/tests/test_agent_tools_execute.py
git commit -m "feat(agents): execute one tool call as the calling user

Native tools are loaded from their own source the way Open WebUI runs them,
so the mapping to each service stays in one place. Proxy tools go through
/meta/call_tool, which does its own per-user access check."
```

---

### Task 3: Store the per-schedule tool mode

**Files:**
- Create: `mcp-servers/tasks/migrations/042_schedule_tool_mode.sql`
- Modify: `mcp-servers/tasks/models.py:146` (beside `agent_id`)
- Modify: `mcp-servers/tasks/routes_schedules.py:77` (`CreateScheduleIn`), `:264` (the insert), `:442` (`_serialize`)
- Test: `mcp-servers/tasks/tests/test_schedule_tool_mode.py`

**Interfaces:**
- Produces: `Schedule.tool_mode` (nullable `Text`), request field `tool_mode`, and `tool_mode` in the serialized schedule.

Context that matters: on this same feature, `agent_id` was accepted by the API and silently thrown away because the insert never carried it, and separately was dropped from `_serialize` without a single test failing. Both are covered below on purpose. `db.py` re-runs every migration on every startup, so it must be idempotent.

- [ ] **Step 1: Write the failing test**

```python
"""tool_mode has to survive the whole round trip.

Every assertion here exists because the neighbouring column, agent_id, was
lost twice on this feature: once in the insert and once in the serializer,
each time with a full green suite.
"""
import pytest

from routes_schedules import CreateScheduleIn, _serialize


def test_the_request_model_accepts_a_tool_mode():
    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p", tool_mode="full")
    assert body.tool_mode == "full"


def test_tool_mode_defaults_to_none_so_existing_callers_are_unchanged():
    body = CreateScheduleIn(
        user_email="owner@example.com", name="n", cron_expr="0 9 * * *",
        tz="Asia/Manila", prompt="p")
    assert body.tool_mode is None


def test_serialize_returns_the_tool_mode():
    """Deleting this line must fail a test. Last time the equivalent line
    for agent_id was removed, all 31 tests still passed."""
    class _Sched:
        id = "11111111-1111-1111-1111-111111111111"
        user_email = "owner@example.com"
        name = "n"
        cron_expr = "0 9 * * *"
        tz = "Asia/Manila"
        persona = None
        prompt = "p"
        enabled = True
        run_once = False
        delivery_channel_id = None
        delivery_platform = None
        kind = "agent"
        video_config = None
        agent_id = "agent-x-0001"
        tool_mode = "full"
        last_run_at = None
        last_run_status = None
        last_result = None
        last_result_at = None
        created_at = None

    out = _serialize(_Sched())
    assert out["tool_mode"] == "full"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_schedule_tool_mode.py -q`
Expected: FAIL, pydantic rejects the unexpected `tool_mode` argument.

- [ ] **Step 3: Write the migration**

Create `mcp-servers/tasks/migrations/042_schedule_tool_mode.sql`:

```sql
-- 042: how much a scheduled agent is allowed to do.
--
-- 'read_only' lets the agent call tools that only read. 'full' lets it call
-- everything, including sending mail. NULL means read_only: every row that
-- exists today predates the tool loop and none of their owners has been
-- asked yet, so the quiet default has to be the safe one.
--
-- Deliberately not NOT NULL with a default. Backfilling would write a
-- decision nobody made onto every existing schedule, and NULL carries the
-- useful distinction between "chose read_only" and "was never asked".
--
-- 'ask' is intentionally absent. It needs a run that can suspend and resume
-- and a person to answer, which is Phase 2. A value the code cannot honour
-- would be worse than one that is not offered yet.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS tool_mode TEXT;
```

- [ ] **Step 4: Add the column to the model**

In `mcp-servers/tasks/models.py`, directly after the `agent_id` line:

```python
    # NULL means read_only. See migration 042: absent is not the same as
    # chosen, and every row that predates the tool loop is absent.
    tool_mode = Column(Text, nullable=True)
```

- [ ] **Step 5: Carry it through the route**

In `mcp-servers/tasks/routes_schedules.py`, in `CreateScheduleIn` beside `agent_id`:

```python
    tool_mode: str | None = None
```

In the insert, beside `agent_id=body.agent_id`:

```python
            # None means read_only, the safe default for an unattended run.
            tool_mode=body.tool_mode,
```

In `_serialize`, beside `"agent_id": sch.agent_id`:

```python
        "tool_mode": sch.tool_mode,
```

- [ ] **Step 6: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_schedule_tool_mode.py tests/test_routes_schedules.py -q`
Expected: PASS, 3 passed plus the existing routes tests still green.

- [ ] **Step 7: Prove the serializer test bites**

Delete the `"tool_mode": sch.tool_mode,` line and re-run. `test_serialize_returns_the_tool_mode` must fail. Restore it.

- [ ] **Step 8: Commit**

```bash
git add mcp-servers/tasks/migrations/042_schedule_tool_mode.sql mcp-servers/tasks/models.py mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_schedule_tool_mode.py
git commit -m "feat(schedules): store how much a scheduled agent may do

NULL means read only. Absent is not the same as chosen, so existing rows
are not backfilled with a decision nobody made."
```

---

### Task 4: The tool loop

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py:95-123` (`_chat`), `:190-214` (the call site)
- Test: `mcp-servers/tasks/tests/test_agent_tool_loop.py`

**Interfaces:**
- Consumes: `agent_tools.is_write_tool(method_name) -> bool`, `agent_tools.execute_tool_call(tool_call, user_email) -> str`.
- Produces: `_chat(token, model, messages, tool_ids, user_email, tool_mode) -> tuple[str, list[str]]`, returning the answer and a list of human-readable notes about anything refused.

Context: `_chat` today raises `_ToolCallRequested` and `run_agent` turns that into "scheduled runs cannot do that yet". Both go away. Verified on production: posting the conversation back with the assistant's `tool_calls` message and one `role: "tool"` message per result returns `finish_reason: stop` and a real answer.

- [ ] **Step 1: Write the failing test**

```python
"""The loop that finally lets an agent do something.

Every test drives agent_runner._chat with a fake Open WebUI, because the
real one needs a model. What matters is the bookkeeping: that a result gets
handed back, that a refusal is explained rather than silently dropped, and
that the loop always ends.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import agent_runner


def _tool_call(name, cid="call_1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": "{}"}}


def _reply(content=None, calls=None):
    msg = {"content": content or "", "tool_calls": calls or None}
    return {"choices": [{"message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}]}


async def test_a_read_tool_is_executed_and_its_result_fed_back():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("list_unread_emails")])
        return _reply(content="You have 4 unread emails.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert answer == "You have 4 unread emails."
    assert notes == []
    ex.assert_awaited_once()
    assert ex.await_args.args[1] == "owner@example.com", "ran as the wrong user"
    # The second request must carry the tool result back.
    second = posts[1]["messages"]
    assert any(m.get("role") == "tool" and "4 unread" in m.get("content", "")
               for m in second)


async def test_a_write_tool_is_refused_in_read_only_and_explained():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="I could not send it.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    ex.assert_not_awaited(), "read_only must not execute a write tool"
    assert notes and "send_email" in notes[0]
    assert answer == "I could not send it."


async def test_a_write_tool_runs_in_full_mode():
    posts = []

    async def fake_post(payload, token):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="Sent.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="sent")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="full")

    ex.assert_awaited_once()
    assert answer == "Sent."


async def test_a_missing_mode_is_treated_as_read_only():
    """Every schedule that predates this feature has no mode at all."""
    async def fake_post(payload, token):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()) as ex:
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com", tool_mode=None)

    ex.assert_not_awaited()


async def test_every_call_in_one_turn_is_executed():
    async def fake_post(payload, token):
        if not getattr(fake_post, "seen", False):
            fake_post.seen = True
            return _reply(calls=[_tool_call("list_unread_emails", "a"),
                                 _tool_call("search_emails", "b")])
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="r")) as ex:
        await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert ex.await_count == 2


async def test_the_loop_stops_at_the_cap_and_says_so():
    """A model that keeps asking must not spin forever."""
    async def fake_post(payload, token):
        return _reply(calls=[_tool_call("list_unread_emails")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="r")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1", messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only")

    assert ex.await_count <= agent_runner.MAX_TOOL_ITERATIONS
    assert any("stopped" in n.lower() for n in notes)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tool_loop.py -q`
Expected: FAIL, `AttributeError: module 'agent_runner' has no attribute '_post_chat'`

- [ ] **Step 3: Split the HTTP call out of `_chat`**

Replace `_chat` in `mcp-servers/tasks/agent_runner.py` with these two functions, and delete the `_ToolCallRequested` class:

```python
#: How many times the model may ask for tools before we stop. Each iteration
#: is a full completion, so this bounds the run's wall clock as well as its
#: appetite.
MAX_TOOL_ITERATIONS = 5


async def _post_chat(payload: dict, token: str) -> dict:
    """One completion. Split out so the loop above it can be tested without
    a model, and so there is one place that knows the wire format."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        r = await client.post(
            f"{_base_url()}/api/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload)
        r.raise_for_status()
        return r.json()


async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None, user_email: str,
                tool_mode: str | None) -> tuple[str, list[str]]:
    """Talk to the agent, running any tools it asks for, until it answers.

    Open WebUI injects the tool specs and returns the model's tool_calls, but
    it never runs them for an API caller: its execution loop lives on the
    socket path used by its own UI. So the execution and the feeding back
    happen here. Verified on production that handing a tool result back
    returns finish_reason "stop" and a real answer.

    Returns the answer and any notes about what was refused, which the caller
    shows the owner. A refusal is not an error: the run completes and says
    what it would not do.
    """
    convo = list(messages)
    notes: list[str] = []
    write_allowed = (tool_mode or "read_only") == "full"

    for _ in range(MAX_TOOL_ITERATIONS):
        payload: dict = {"model": model, "messages": convo, "stream": False}
        if tool_ids:
            payload["tool_ids"] = tool_ids
        data = await _post_chat(payload, token)

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("the model returned no answer")
        message = choices[0].get("message") or {}
        calls = message.get("tool_calls") or []
        content = (message.get("content") or "").strip()

        if not calls:
            return content, notes

        convo.append({"role": "assistant", "content": content,
                      "tool_calls": calls})
        for call in calls:
            name = ((call.get("function") or {}).get("name") or "").strip()
            if is_write_tool(name) and not write_allowed:
                notes.append(
                    "Declined to run " + name + ", because this schedule is "
                    "set to read only.")
                result = ("Refused: this scheduled run is read only, so "
                          + name + " was not run.")
            else:
                result = await execute_tool_call(call, user_email)
            convo.append({"role": "tool", "tool_call_id": call.get("id"),
                          "name": name, "content": result})

    notes.append("Stopped after " + str(MAX_TOOL_ITERATIONS)
                 + " rounds of tool use, so this answer may be incomplete.")
    return content, notes
```

Add the import near the top, beside the existing ones:

```python
from agent_tools import execute_tool_call, is_write_tool
```

- [ ] **Step 4: Update the call site**

In `run_agent`, replace the `try/except _ToolCallRequested` block with:

```python
        try:
            answer, notes = await _chat(
                token=chat_token, model=sched.agent_id,
                messages=_messages_for(sched), tool_ids=tools or None,
                user_email=sched.user_email,
                tool_mode=getattr(sched, "tool_mode", None))
        except Exception:
            raise
        if not answer:
            return ("failed", "The agent returned an empty answer.", {})
        if notes:
            # Say what was refused. A run that quietly skipped half its job
            # and reported success would be worse than one that failed.
            answer = answer + "\n\n" + "\n".join(notes)
        return ("completed", answer, {})
```

- [ ] **Step 5: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tool_loop.py tests/test_agent_runner.py -q`
Expected: PASS. `test_agent_runner.py` has tests referencing `_ToolCallRequested` and the old `_chat` signature; update those to the new shape rather than deleting them, keeping the identity assertion added by the previous review.

- [ ] **Step 6: Prove the refusal test bites**

Change `if is_write_tool(name) and not write_allowed:` to `if False:` and re-run. `test_a_write_tool_is_refused_in_read_only_and_explained` and `test_a_missing_mode_is_treated_as_read_only` must both fail. Restore.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_tool_loop.py mcp-servers/tasks/tests/test_agent_runner.py
git commit -m "feat(agents): run the tools an agent asks for

Open WebUI returns the tool calls but never runs them for an API caller, so
the execution and the feeding back happen here. A schedule that may only
read says what it declined instead of skipping it silently."
```

---

### Task 5: Choose the mode on the Cron page

**Files:**
- Modify: `mcp-servers/tasks/static/cron.html:672-680` (beside the Run as field), `:1517` (the submit body), and the card rendering near `:1262`
- Test: `mcp-servers/tasks/tests/browser/test_cron_tool_mode.py`

**Interfaces:**
- Consumes: `tool_mode` on the created schedule and on each listed schedule, from Task 3.

Context: the control belongs directly under "Run as", because it is meaningless without an agent. Follow the existing markup exactly: a `div.field`, a `label.form-label`, a `select.form-input`, and a `span.form-hint`. The card already renders small badges for the timezone, the destination and the agent; the mode joins those, and only when the schedule has an agent.

- [ ] **Step 1: Write the failing test**

```python
"""The Tool access control, and what the card says about it.

Follows the existing browser tests in this directory: parse the served page
and assert on structure, rather than driving a browser.
"""
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "static" / "cron.html"


@pytest.fixture(scope="module")
def html():
    return PAGE.read_text(encoding="utf-8")


def test_there_is_a_tool_access_select(html):
    assert 'id="tool-mode"' in html


def test_it_offers_read_only_and_full_but_not_ask(html):
    block = html.split('id="tool-mode"', 1)[1].split("</select>", 1)[0]
    assert 'value="read_only"' in block
    assert 'value="full"' in block
    assert 'value="ask"' not in block, "ask is Phase 2 and cannot be honoured yet"


def test_read_only_is_the_default_selection(html):
    block = html.split('id="tool-mode"', 1)[1].split("</select>", 1)[0]
    first = re.search(r'<option[^>]*value="([^"]*)"', block)
    assert first and first.group(1) == "read_only"


def test_the_submit_body_sends_the_tool_mode(html):
    assert "body.tool_mode" in html


def test_the_control_sits_with_the_run_as_field(html):
    """It is meaningless without an agent, so it must not drift elsewhere."""
    assert html.index('id="run-as"') < html.index('id="tool-mode"')
    between = html[html.index('id="run-as"'):html.index('id="tool-mode"')]
    assert between.count('class="field"') <= 1
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/test_cron_tool_mode.py -q`
Expected: FAIL, `assert 'id="tool-mode"' in html`

- [ ] **Step 3: Add the control**

Immediately after the closing `</div>` of the Run as field in `mcp-servers/tasks/static/cron.html`:

```html
            <div class="field">
              <label class="form-label" for="tool-mode">Tool access</label>
              <select class="form-input" id="tool-mode" name="tool-mode">
                <option value="read_only">Read only</option>
                <option value="full">Full access</option>
              </select>
              <span class="form-hint">A scheduled run happens with nobody
                watching. Read only lets the agent look things up but not send,
                reply, create or delete. Full access lets it do everything you
                could, including sending email on your behalf.</span>
            </div>
```

- [ ] **Step 4: Send it on submit**

Beside the existing `if (runAs) body.agent_id = runAs;`:

```javascript
      // Only meaningful with an agent, and the server treats a missing value
      // as read only anyway.
      const toolMode = (document.getElementById("tool-mode") || {}).value || "";
      if (runAs && toolMode) body.tool_mode = toolMode;
```

- [ ] **Step 5: Show it on the card**

Where the agent badge is rendered, add beside it:

```javascript
      // Only when the schedule runs as an agent: without one there are no
      // tools and the mode would be noise.
      if (s.agent_id && s.tool_mode === "full") {
        badges.push('<span class="chip">Full tool access</span>');
      } else if (s.agent_id) {
        badges.push('<span class="chip">Read only</span>');
      }
```

Match the surrounding code's existing badge helper and class names rather than copying `chip` blindly if that is not what the file uses.

- [ ] **Step 6: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/ -q`
Expected: PASS. The browser suite was 199 passed before this task; expect 204.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/static/cron.html mcp-servers/tasks/tests/browser/test_cron_tool_mode.py
git commit -m "feat(cron): choose how much a scheduled agent may do

Read only is the default and the first option, because a scheduled run
happens with nobody watching."
```

---

### Task 6: Verify it end to end on production

**Files:**
- None. This task changes no code.

Context, and why this task exists: on this feature, a page was verified against a stubbed API and shipped broken through a whole deploy, and the automated tests all stub the model. Nothing in Tasks 1 to 5 proves a real agent runs a real tool. Only this does.

- [ ] **Step 1: Deploy `tasks` following the repo's documented process**

Hash-sweep the server against the repo first, CRLF-normalized, then copy the changed files, run `sed -i 's/\r$//'` on each, and rebuild. Confirm migration 042 applied.

- [ ] **Step 2: Prove a read tool actually runs**

Create a schedule naming the Triage agent with `tool_mode` unset, prompt "How many unread emails do I have right now?", fire it with run-now, and read `last_result`. Expected: a real count, not "tried to use one of its tools". This is the exact case that fails today.

- [ ] **Step 3: Prove a write tool is refused**

Same schedule, prompt "Send a test email to me saying hello". Expected: the run completes, no mail is sent, and the result says it declined to run `send_email` because the schedule is read only. Confirm in the mailbox that nothing was sent.

- [ ] **Step 4: Prove full access works**

Set that schedule's `tool_mode` to `full` and repeat step 3. Expected: the mail arrives. Delete it afterwards.

- [ ] **Step 5: Prove existing schedules are untouched**

Confirm the four production schedules still have `agent_id` null and `tool_mode` null, and that one of them still runs green.

- [ ] **Step 6: Clean up**

Delete every schedule created for this verification and confirm the count returns to four.

---

## Self-Review

**Spec coverage.** The loop, Task 4. Executing both tool families, Task 2. The read/write classifier including unknown-is-write, Task 1. Per-schedule mode with read_only default, Task 3. The Cron control, Task 5. Reporting what was refused, Task 4 step 4 and Task 5 step 5. `ask` absent from the UI, Task 5's test asserts it. Production verification, Task 6. The security note about exec'ing tool source is carried in Task 2's docstring.

**Placeholders.** None. Every code step carries its code, every test step its assertions, and every run step its command and expected output.

**Type consistency.** `is_write_tool(str) -> bool` and `execute_tool_call(dict, str) -> str` are defined in Tasks 1 and 2 and consumed with those signatures in Task 4. `_chat` returns `tuple[str, list[str]]` in Task 4 and is unpacked as two values at its only call site. `tool_mode` is a nullable string everywhere: column, request field, serialized field, and loop parameter.

**One deviation from the spec, recorded here.** The spec described the native tool table and the verb rule as two mechanisms. In practice the verb rule already classifies all seven native tools correctly, so `READ_METHODS` is kept as a pin against renames rather than as the primary mechanism. This is a narrowing of implementation, not of behaviour.
