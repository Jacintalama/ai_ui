# Agents on a schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A schedule can name one of the user's AI agents, and when it fires that agent runs with its own instructions and its own tools, acting as the schedule's owner.

**Architecture:** One nullable `agent_id` column on `tasks.schedules`. `scheduler._run_scheduled_task` already branches to `_run_video_schedule`; this adds a second branch calling `agent_runner.run_agent`, which returns the same `(status, result, extras)` triple, so storing and delivering the result is untouched. The agent runs through Open WebUI's chat API using a short-lived token minted for the schedule's owner.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, asyncpg, httpx, pytest (asyncio auto mode), plain HTML/JS for the Cron page.

Spec: `docs/superpowers/specs/2026-08-26-agents-on-a-schedule-design.md`

## Global Constraints

- **Commit attribution is Ralph Benitez only.** Never add `Co-Authored-By: Claude`, "Generated with Claude Code", or any AI attribution to a commit message, PR, or file.
- **No em-dashes or en-dashes** anywhere a person reads: commit messages, comments, user-facing copy.
- **Never log or store a minted token.** `owui_token.py` says so in its own docstring. This project has already leaked a bot token once through an HTTP client that logged the request URL.
- **Do not add a new `kind`.** `schedules.kind` is already `'agent'` or `'video'`, where `'agent'` means the CLI executor. The new column is `agent_id`, and a null there means today's behaviour, unchanged.
- **A null `agent_id` must change nothing.** Every existing schedule has one.
- **Fail to a delivered message.** A schedule nobody is watching that silently produces nothing is worse than one that says it broke.
- **Compose only injects what a service DECLARES.** Adding an env var to `.env` alone reaches no container. This has bitten this project three times.
- **Never touch `.env`.** The server's copy holds the only production secrets.
- Python is `py` on this machine, not `python3`. Tests: `cd mcp-servers/tasks && py -m pytest tests/ -q`. Expect roughly 130 pre-existing DB-tier errors locally with no Postgres; they say `ERROR at setup` and are not yours. Scope runs to the named files.
- **`mcp-servers/tasks/templates.py` must never be deployed.** The server's copy is ahead. This plan does not touch it.

---

## Task 1: The column, the model and the API field

**Files:**
- Create: `mcp-servers/tasks/migrations/041_schedule_agent_id.sql`
- Modify: `mcp-servers/tasks/models.py` (the `Schedule` class)
- Modify: `mcp-servers/tasks/routes_schedules.py` (`CreateScheduleIn`)
- Test: `mcp-servers/tasks/tests/test_schedule_agent_id.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Schedule.agent_id: str | None` and `CreateScheduleIn.agent_id: str | None`. Tasks 2 and 3 both read it.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_schedule_agent_id.py`:

```python
"""A schedule can name one of the user's agents.

The column is nullable and null means today's behaviour, because every row
that already exists has one. `kind` is deliberately untouched: it is already
'agent' or 'video', where 'agent' means the CLI executor, and overloading that
word further would make the collision worse.
"""
import pathlib

from models import Schedule
from routes_schedules import CreateScheduleIn

MIGRATION = (pathlib.Path(__file__).resolve().parents[1]
             / "migrations" / "041_schedule_agent_id.sql")


def test_the_model_carries_an_agent_id():
    assert hasattr(Schedule, "agent_id")


def test_a_schedule_can_be_created_without_naming_an_agent():
    """Null is the normal case and must stay the default, or every existing
    caller would suddenly be required to pick one."""
    payload = CreateScheduleIn(name="n", cron_expr="0 9 * * *", prompt="p")
    assert payload.agent_id is None


def test_a_schedule_can_name_an_agent():
    payload = CreateScheduleIn(name="n", cron_expr="0 9 * * *", prompt="p",
                               agent_id="agent-triage-0002")
    assert payload.agent_id == "agent-triage-0002"


def test_the_migration_is_additive_and_idempotent():
    """db.py re-runs every migration on every startup, so a migration that is
    not idempotent takes the service down on the second boot."""
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists agent_id" in sql
    assert "drop" not in sql, "a migration on a live table must not drop anything"
    assert "not null" not in sql, "existing rows have no agent, so it must be nullable"


def test_the_migration_does_not_touch_kind():
    """kind already means the CLI executor, so this feature must not move it.

    Comments are stripped first: the migration explains at length WHY it is not
    a new kind, and a naive search would match that explanation and pass while
    the statements did something else entirely.
    """
    statements = "\n".join(
        line.split("--")[0]
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
    ).lower()
    assert "kind" not in statements, statements
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_schedule_agent_id.py -q`
Expected: FAIL. `test_the_model_carries_an_agent_id` fails on the missing attribute, and the migration tests fail with `FileNotFoundError`.

- [ ] **Step 3: Write the migration**

Create `mcp-servers/tasks/migrations/041_schedule_agent_id.sql`:

```sql
-- 041: let a schedule name one of the user's AI agents.
--
-- Null means what schedules have always done: the Claude Code CLI executor,
-- with the persona prefix and MEMORY.md. Every row that exists today is in
-- that state, so the column has to be nullable and nothing is backfilled.
--
-- Deliberately NOT a new `kind`. schedules.kind is already 'agent' or 'video',
-- where 'agent' means the CLI executor, so a scheduled task is already called
-- an agent and it is not the same thing as an AI Agent. Adding a third value
-- there would deepen a collision instead of avoiding it.
--
-- No foreign key to the model table. Open WebUI owns public.model, an agent
-- can be deleted from the web at any time, and a cascade or a restrict would
-- either destroy the user's schedule or block their delete. The scheduler
-- checks at run time and falls back instead.
--
-- Idempotent: db.py re-runs every migration on every startup.

ALTER TABLE tasks.schedules
    ADD COLUMN IF NOT EXISTS agent_id TEXT;
```

- [ ] **Step 4: Add the model attribute**

In `mcp-servers/tasks/models.py`, in the `Schedule` class, directly after the `run_once` column:

```python
    # The AI Agent this schedule runs as, or NULL for the CLI executor that
    # schedules have always used. Not a foreign key: Open WebUI owns the model
    # table and an agent can be deleted from the web at any time, so the
    # scheduler checks at run time and falls back rather than letting a delete
    # cascade into somebody's schedule.
    agent_id = Column(Text, nullable=True)
```

- [ ] **Step 5: Add the API field**

In `mcp-servers/tasks/routes_schedules.py`, in `CreateScheduleIn`, directly after `kind`:

```python
    # Which AI Agent runs this, or None for the executor schedules have always
    # used. Not validated against the model table here: the agent has to be
    # visible to the OWNER at run time, and that is a different question from
    # whether it exists right now.
    agent_id: str | None = None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_schedule_agent_id.py -q`
Expected: `5 passed`

- [ ] **Step 7: Check nothing else broke**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_routes_schedules.py tests/test_schedule_kind.py tests/test_schedule_limits.py tests/test_schedule_result.py -q`
Expected: all pass. If a test asserts an exact set of `CreateScheduleIn` fields, update the test to include `agent_id` rather than removing the field.

- [ ] **Step 8: Commit**

```bash
git add mcp-servers/tasks/migrations/041_schedule_agent_id.sql mcp-servers/tasks/models.py mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_schedule_agent_id.py
git commit -m "feat(schedules): a schedule can name an agent

One nullable column. Null means what schedules have always done, which is
every row that exists today, so nothing is backfilled and no existing caller
has to change.

Deliberately not a new kind. schedules.kind is already 'agent' or 'video',
where 'agent' means the CLI executor, so a scheduled task is already called an
agent and it is not the same thing as an AI Agent. A third value there would
deepen that collision rather than avoid it.

No foreign key either. Open WebUI owns the model table and an agent can be
deleted from the web at any time, so a cascade would destroy somebody's
schedule and a restrict would block their delete. The scheduler checks at run
time instead."
```

---

## Task 2: Running the agent

**Files:**
- Create: `mcp-servers/tasks/agent_runner.py`
- Modify: `mcp-servers/tasks/scheduler.py`
- Modify: `docker-compose.unified.yml` (the `tasks` service environment block, one line)
- Test: `mcp-servers/tasks/tests/test_agent_runner.py` (create)

**Interfaces:**
- Consumes: `Schedule.agent_id` from Task 1; `owui_token.mint_owui_token(user_id: str, ttl_seconds: int = 60) -> str`.
- Produces: `agent_runner.run_agent(sched) -> tuple[str, str, dict]` returning `(status, result, extras)`, the same triple `_run_video_schedule` returns.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agent_runner.py`:

```python
"""Running a schedule as one of the user's AI agents.

The agent has to act as the schedule's OWNER, with the owner's own tools, and
it has to survive the agent being deleted from the web after the schedule was
made. Every path ends in a delivered message: a schedule nobody is watching
that silently produces nothing is worse than one that says it broke.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import agent_runner


def _sched(**over):
    base = dict(id="sched-1", user_email="owner@example.com",
                agent_id="agent-triage-0002", name="Morning triage",
                prompt="Sort my unread mail.", last_result=None)
    base.update(over)
    return SimpleNamespace(**base)


AGENT_ROW = {"id": "agent-triage-0002", "name": "Triage",
             "meta": {"toolIds": ["gmail"]}}


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    """Replace every network seam. Nothing here touches a socket."""
    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="owui-owner-1"))
    monkeypatch.setattr(agent_runner, "mint_owui_token",
                        lambda user_id, ttl_seconds=60: "minted-token")
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=[AGENT_ROW]))
    chat = AsyncMock(return_value="Two need a reply today.")
    monkeypatch.setattr(agent_runner, "_chat", chat)
    return SimpleNamespace(chat=chat)


async def test_it_runs_the_named_agent(wired):
    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "completed"
    assert "reply today" in result
    assert wired.chat.await_args.kwargs["model"] == "agent-triage-0002"


async def test_it_sends_the_agents_own_tools(wired):
    """Open WebUI attaches a model's tools only for its own UI. An API caller
    that does not ask gets none, and the agent arrives unable to do anything."""
    await agent_runner.run_agent(_sched())

    assert wired.chat.await_args.kwargs["tool_ids"] == ["gmail"]


async def test_an_agent_with_no_tools_sends_none(wired, monkeypatch):
    """None is not the same as an empty list, which reads as an explicit
    request for no tools."""
    monkeypatch.setattr(agent_runner, "_list_agents", AsyncMock(
        return_value=[{"id": "agent-triage-0002", "name": "Triage",
                       "meta": {"toolIds": []}}]))

    await agent_runner.run_agent(_sched())

    assert wired.chat.await_args.kwargs["tool_ids"] is None


async def test_it_runs_as_the_owner_not_anyone_else(wired, monkeypatch):
    """A schedule belongs to one person, reads their mail, and runs whether or
    not they are online. Running as the wrong identity would read somebody
    else's mailbox and look completely correct."""
    seen = {}

    def spy_mint(user_id, ttl_seconds=60):
        seen["user_id"] = user_id
        seen["ttl"] = ttl_seconds
        return "minted-token"

    monkeypatch.setattr(agent_runner, "mint_owui_token", spy_mint)

    await agent_runner.run_agent(_sched())

    assert seen["user_id"] == "owui-owner-1"


async def test_the_token_outlives_a_slow_tool_call(wired, monkeypatch):
    """The default is 60 seconds, which is right for pairing and wrong here: a
    tool using run can take longer, and an expired token mid run fails in a way
    that looks like the agent refusing."""
    seen = {}

    def spy_mint(user_id, ttl_seconds=60):
        seen["ttl"] = ttl_seconds
        return "minted-token"

    monkeypatch.setattr(agent_runner, "mint_owui_token", spy_mint)

    await agent_runner.run_agent(_sched())

    assert seen["ttl"] >= agent_runner.HTTP_TIMEOUT_SECONDS


async def test_the_previous_result_is_carried_forward(wired):
    """A daily digest that repeats itself is useless, and the CLI path this
    replaces kept a memory between runs."""
    await agent_runner.run_agent(_sched(last_result="Yesterday: 3 invoices."))

    sent = "".join(m["content"] for m in wired.chat.await_args.kwargs["messages"])
    assert "3 invoices" in sent


async def test_a_huge_previous_result_is_trimmed(wired):
    await agent_runner.run_agent(_sched(last_result="x" * 9000))

    sent = "".join(m["content"] for m in wired.chat.await_args.kwargs["messages"])
    assert len(sent) < 4000, "the whole of last_result was pasted in"


async def test_the_first_run_carries_nothing(wired):
    await agent_runner.run_agent(_sched(last_result=None))

    msgs = wired.chat.await_args.kwargs["messages"]
    assert len(msgs) == 1, msgs


async def test_a_deleted_agent_still_delivers_something(wired, monkeypatch):
    """The agent was removed from the web after the schedule was made. The run
    must still produce a message that says so."""
    monkeypatch.setattr(agent_runner, "_list_agents", AsyncMock(return_value=[]))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert "no longer" in result.lower() or "gone" in result.lower()
    wired.chat.assert_not_called()


async def test_an_owner_with_no_account_fails_readably(wired, monkeypatch):
    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value=None))

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert result.strip() != ""
    wired.chat.assert_not_called()


async def test_a_model_failure_is_reported_not_raised(wired):
    """_finalize_run dispatches this detached, so a raise would vanish and
    leave the schedule stuck on running."""
    wired.chat.side_effect = RuntimeError("model down")

    status, result, _ = await agent_runner.run_agent(_sched())

    assert status == "failed"
    assert result.strip() != ""


async def test_the_minted_token_is_never_returned_in_the_result(wired):
    """This project has already logged a bot token once."""
    status, result, extras = await agent_runner.run_agent(_sched())

    assert "minted-token" not in result
    assert "minted-token" not in repr(extras)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_runner'`

- [ ] **Step 3: Write the runner**

Create `mcp-servers/tasks/agent_runner.py`:

```python
"""Run a schedule as one of the user's AI agents.

An agent is an Open WebUI model row, so running one means calling Open WebUI's
chat API with that model id. Two things make it more than that.

It has to act as the schedule's OWNER. A schedule belongs to one person, reads
their mail and their files, and fires whether or not they are online, so the
request is made with a token minted for them.

And it has to ASK for the agent's tools. Open WebUI attaches a model's own
tools only when the request comes from its own UI, which it recognises by the
session id; its middleware says API callers must request tools via tool_ids.
Without that field the agent arrives with its instructions and nothing it can
do, and answers that it cannot reach your mail.

Returns the same (status, result, extras) triple as the video path, so
_finalize_run stores and delivers it without knowing which kind of run it was.
"""
import logging
import os

import httpx

from owui_token import mint_owui_token

logger = logging.getLogger(__name__)

#: An agent that uses tools can take a while. The token has to outlive the
#: slowest single call or it expires mid run, which surfaces as the agent
#: refusing rather than as an auth error.
HTTP_TIMEOUT_SECONDS = 240
TOKEN_TTL_SECONDS = HTTP_TIMEOUT_SECONDS + 60

#: Enough of the last run to avoid repeating it, not so much that it crowds
#: out the actual task. last_result is capped at 8000 characters upstream.
MEMORY_EXCERPT_CHARS = 1200

AGENT_PREFIX = "agent-"


def _base_url() -> str:
    return os.environ.get("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")


async def _owui_user_id_for(email: str) -> str | None:
    """The Open WebUI user id behind an email.

    Imported lazily from routes_gateway so this module can be tested without
    pulling in the router and its dependencies.
    """
    from routes_gateway import _owui_user_id_for as resolve
    return await resolve(email)


async def _list_agents(token: str) -> list[dict]:
    """The derived models this token's user can see.

    /api/v1/models/list rather than /api/models: the latter nests the row under
    `info` and deletes params server side. It pages at 30 on a one indexed
    `page`, and a user is capped at 25 agents, so one page is enough here; the
    guard stops a wrong total looping.
    """
    out: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(5):
            r = await client.get(
                f"{_base_url()}/api/v1/models/list?page={page}",
                headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
            batch = data.get("items") or []
            out.extend(batch)
            total = data.get("total")
            if not batch or not isinstance(total, int) or len(out) >= total:
                break
            page += 1
    return out


async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None) -> str:
    """One non streaming completion, as the token's user."""
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if tool_ids:
        payload["tool_ids"] = tool_ids
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        r = await client.post(
            f"{_base_url()}/api/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload)
        r.raise_for_status()
        data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("the model returned no answer")
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _messages_for(sched) -> list[dict]:
    """The task, preceded by a trimmed reminder of the last run when there is
    one. The CLI path this replaces kept a memory between runs, and dropping
    that would make every daily digest say the same thing every day."""
    last = (getattr(sched, "last_result", None) or "").strip()
    msgs: list[dict] = []
    if last:
        msgs.append({
            "role": "user",
            "content": ("For context, this is what you produced on the previous "
                        "run of this schedule. Do not repeat it; say what has "
                        "changed.\n\n" + last[:MEMORY_EXCERPT_CHARS]),
        })
    msgs.append({"role": "user", "content": sched.prompt})
    return msgs


async def run_agent(sched) -> tuple[str, str, dict]:
    """Run one schedule as its agent. Returns (status, result, extras).

    Never raises. _finalize_run dispatches this detached, so an escaping
    exception would vanish into a discarded task and leave the schedule stuck
    reporting that it is still running.
    """
    try:
        owner = await _owui_user_id_for(sched.user_email)
        if not owner:
            return ("failed",
                    "This schedule could not run: its owner has no account on "
                    "this platform any more.", {})

        token = mint_owui_token(owner, ttl_seconds=TOKEN_TTL_SECONDS)

        agents = await _list_agents(token)
        agent = next((a for a in agents
                      if isinstance(a, dict) and a.get("id") == sched.agent_id), None)
        if agent is None:
            return ("failed",
                    "This schedule is set to run as an agent that no longer "
                    "exists. Open the Cron page and pick another one.", {})

        meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
        tools = meta.get("toolIds")
        tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []

        # Keyword arguments on purpose: the tests assert on them by name, and
        # a positional call here would silently drift from those assertions.
        answer = await _chat(token=token, model=sched.agent_id,
                             messages=_messages_for(sched),
                             tool_ids=tools or None)
        if not answer:
            return ("failed", "The agent returned an empty answer.", {})
        return ("completed", answer, {})
    except Exception as exc:                            # noqa: BLE001
        # Never include the exception's own text blindly: an httpx error can
        # carry the request URL, and this project has already leaked a token
        # that way.
        logger.error("agent schedule run failed", exc_info=True)
        return ("failed",
                "The agent could not finish this run. It will try again at the "
                "next scheduled time.", {})
```

- [ ] **Step 4: Branch in the scheduler**

In `mcp-servers/tasks/scheduler.py`, find this line in `_run_scheduled_task`:

```python
    if getattr(sched, "kind", "agent") == "video":
        return await _run_video_schedule(sched)
```

and add the agent branch directly after it:

```python
    if getattr(sched, "kind", "agent") == "video":
        return await _run_video_schedule(sched)
    # A schedule that names an AI Agent runs through the chat path as its
    # owner, with that agent's own tools. Null means the CLI executor below,
    # which is what every schedule did before this existed.
    #
    # Checked AFTER kind: a video schedule renders a walkthrough and has no
    # agent, so the order here decides which wins if a row somehow has both.
    if getattr(sched, "agent_id", None):
        from agent_runner import run_agent
        async with _RUN_SEMAPHORE:
            return await run_agent(sched)
```

- [ ] **Step 5: Declare the Open WebUI URL for the tasks service**

The tasks service signs tokens with `WEBUI_SECRET_KEY` but has never needed to CALL Open WebUI, so it has no URL for it. Compose injects only what a service declares, so without this the runner would fall back to its default and any future override would silently do nothing.

In `docker-compose.unified.yml`, in the `tasks` service `environment:` block, directly after the `WEBUI_SECRET_KEY` line:

```yaml
      # tasks now CALLS Open WebUI as well as signing tokens for it: a schedule
      # that names an agent runs that agent through the chat API. Declared
      # rather than left to the code default, because compose injects only what
      # a service declares and an override in .env alone would reach nothing.
      - OPENWEBUI_URL=${OPENWEBUI_URL:-http://open-webui:8080}
```

- [ ] **Step 6: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_runner.py -q`
Expected: `12 passed`

- [ ] **Step 7: Check the scheduler still passes**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_scheduler.py tests/test_schedule_kind.py tests/test_scheduler_delivery.py tests/test_schedule_result.py -q`
Expected: all pass. The video branch and the CLI branch are both untouched.

- [ ] **Step 8: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/scheduler.py mcp-servers/tasks/tests/test_agent_runner.py docker-compose.unified.yml
git commit -m "feat(schedules): run a schedule as one of your agents

A schedule that names an agent now runs that agent through the chat API, with
its own instructions and its own tools, acting as the schedule's owner. It
returns the same triple as the video path, so storing and delivering the result
is untouched.

Two things make it more than a model id. It runs as the OWNER, because a
schedule reads that person's mail and fires whether or not they are online, and
running as the wrong identity would read somebody else's mailbox while looking
completely correct. And it asks for the agent's tools explicitly: Open WebUI
attaches a model's own tools only for requests from its own UI, so an API
caller that does not ask gets none.

The token is minted to outlive the slowest call rather than the default sixty
seconds, because expiring mid run surfaces as the agent refusing rather than as
an auth error.

The previous run's result is carried forward, trimmed. The CLI path this
replaces kept a memory between runs, and dropping it would make every daily
digest say the same thing every day.

Nothing raises. _finalize_run dispatches this detached, so an escaping
exception would vanish and leave the schedule stuck reporting that it is still
running. Every failure returns a sentence the owner can read.

OPENWEBUI_URL is now declared for the tasks service. It signs tokens for Open
WebUI but had never called it, and compose injects only what a service
declares."
```

---

## Task 3: Choosing an agent on the Cron page

**Files:**
- Modify: `mcp-servers/tasks/static/cron.html`
- Test: `mcp-servers/tasks/tests/browser/test_cron_run_as.py` (create)

**Interfaces:**
- Consumes: `CreateScheduleIn.agent_id` from Task 1.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/browser/test_cron_run_as.py`:

```python
"""Picking which agent a schedule runs as.

The default has to stay the assistant schedules have always used: somebody who
never touches this field must get exactly what they got before.
"""
import http.server
import json
import pathlib
import threading

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

STATIC = pathlib.Path(__file__).resolve().parents[2] / "static"

AGENTS = [
    {"id": "agent-triage-0002", "name": "Triage", "base_model_id": "gpt-4o-mini",
     "meta": {"description": "sorts mail", "toolIds": ["gmail"]},
     "params": {"system": "sort mail"}, "user_id": "me",
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 1, "updated_at": 1},
    {"id": "agent-scout-0001", "name": "Scout", "base_model_id": "gpt-4o-mini",
     "meta": {"description": "researches", "toolIds": []},
     "params": {"system": "research"}, "user_id": "me",
     "access_grants": [], "is_active": True, "write_access": True,
     "created_at": 2, "updated_at": 2},
]


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    html = (STATIC / "cron.html").read_bytes()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    sent = []

    def route(r):
        url = r.request.url
        if "/api/v1/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif r.request.method == "POST":
            sent.append(json.loads(r.request.post_data or "{}"))
            body = {"id": "new"}
        else:
            body = []
        r.fulfill(status=201 if r.request.method == "POST" else 200,
                  content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.route("**/tasks/**", route)
    pg.goto("http://127.0.0.1:%d/cron.html" % srv.server_address[1])
    pg.wait_for_selector("#run-as", state="attached")
    pg.wait_for_timeout(400)
    pg.sent = sent
    yield pg
    pg.close()
    srv.shutdown()


def _fill(page):
    page.fill("#name", "Morning digest")
    page.fill("#prompt", "Sort my unread mail.")


def test_the_field_defaults_to_the_usual_assistant(page):
    """Somebody who never touches this must get exactly what they got before."""
    assert page.input_value("#run-as") == ""


def test_it_lists_the_agents_you_can_see(page):
    labels = page.locator("#run-as option").all_inner_texts()
    assert any("Triage" in t for t in labels), labels
    assert any("Scout" in t for t in labels), labels


def test_leaving_it_alone_sends_no_agent(page):
    _fill(page)
    page.locator("#create-btn").click()
    page.wait_for_timeout(400)
    assert page.sent, "nothing was posted"
    assert page.sent[-1].get("agent_id") in (None, ""), page.sent[-1]


def test_picking_an_agent_sends_its_id(page):
    _fill(page)
    page.select_option("#run-as", "agent-triage-0002")
    page.locator("#create-btn").click()
    page.wait_for_timeout(400)
    assert page.sent[-1]["agent_id"] == "agent-triage-0002"


def test_a_failure_to_list_agents_still_lets_you_create_a_schedule(page):
    """The agent list is a convenience. Losing it must not take the form with
    it, because the form works perfectly well without an agent."""
    page.route("**/api/v1/models/list*", lambda r: r.abort())
    page.reload()
    page.wait_for_selector("#name", state="visible")
    _fill(page)
    page.locator("#create-btn").click()
    page.wait_for_timeout(500)
    assert page.sent, "the form stopped working when the agent list failed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/test_cron_run_as.py -q`
Expected: FAIL, timing out on `#run-as`.

- [ ] **Step 3: Add the field**

In `mcp-servers/tasks/static/cron.html`, directly after the Prompt field block (the `<div class="field">` containing `id="prompt"`), insert:

```html
            <div class="field">
              <label class="form-label" for="run-as">Run as</label>
              <select class="form-input" id="run-as" name="run-as">
                <option value="">Default assistant</option>
              </select>
              <span class="form-hint">Pick one of your agents to run this, with
                its own instructions and tools. Leave it as it is and schedules
                behave exactly as they always have.</span>
            </div>
```

- [ ] **Step 4: Populate it and send it**

In `mcp-servers/tasks/static/cron.html`, add this near the other startup code, after `authHeaders` is defined:

```js
    // The agents this person can see, for the Run as field. An agent is a
    // model row whose id we minted, which is the same test the Agents page
    // uses. Deliberately quiet on failure: this list is a convenience and the
    // form works perfectly well without an agent, so losing it must not take
    // the form down with it.
    async function loadAgentsForRunAs() {
      const sel = document.getElementById("run-as");
      if (!sel) return;
      try {
        const r = await fetch("/api/v1/models/list?page=1",
                              { headers: authHeaders(), credentials: "include" });
        if (!r.ok) return;
        const body = await r.json();
        const items = Array.isArray(body.items) ? body.items : [];
        items
          .filter((m) => String(m.id || "").startsWith("agent-"))
          .forEach((m) => {
            const o = document.createElement("option");
            o.value = m.id;
            o.textContent = m.name || m.id;
            sel.appendChild(o);
          });
      } catch (e) {
        console.warn("[cron] could not load agents for Run as", e);
      }
    }
    loadAgentsForRunAs();
```

Then in the submit handler, directly after `if (BROWSER_TZ) body.tz = BROWSER_TZ;`:

```js
      // Only sent when one was chosen. An empty string is not the same as
      // absent: the API treats null as "the assistant schedules have always
      // used", and that is what an untouched field means.
      const runAs = (document.getElementById("run-as") || {}).value || "";
      if (runAs) body.agent_id = runAs;
```

- [ ] **Step 5: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/test_cron_run_as.py -q`
Expected: `5 passed`

- [ ] **Step 6: Run the whole browser suite for regressions**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/ -q`
Expected: all pass. It was 190 passed before this task.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/static/cron.html mcp-servers/tasks/tests/browser/test_cron_run_as.py
git commit -m "feat(cron): choose which agent a schedule runs as

One field on the form. It defaults to the assistant schedules have always used,
so somebody who never touches it gets exactly what they got before, and an
untouched field sends no agent_id at all rather than an empty string.

The agent list fails quietly on purpose. It is a convenience, and the form
works perfectly well without an agent, so losing the list must not take the
form down with it. There is a test for that specifically."
```

---

## Task 4: Deploy and verify on a real schedule

**Files:**
- No new files. Deploys Tasks 1 to 3.

**Interfaces:**
- Consumes: everything above.
- Produces: the feature, live.

The tasks service IS covered by the orchestrator script, but this also changes `docker-compose.unified.yml`, and the compose file on the server has diverged from the repo before. Both are handled below.

- [ ] **Step 1: Confirm the tree is clean and the suites pass**

```bash
cd "C:/All/Work - Code/ai_ui"
git status --short -- mcp-servers docker-compose.unified.yml
cd mcp-servers/tasks && py -m pytest tests/browser/ -q
cd "C:/All/Work - Code/ai_ui/mcp-servers/tasks" && py -m pytest tests/test_agent_runner.py tests/test_schedule_agent_id.py tests/test_scheduler.py tests/test_schedule_kind.py -q
```

Expected: no output from `git status` for those paths, and passing suites.

- [ ] **Step 2: Compare the server's compose against the repo by DECLARED VARIABLES, not text**

A text diff on this file has produced a false alarm before, reporting a missing block that was only an alignment artefact.

```bash
cd "C:/All/Work - Code/ai_ui"
scp -q -o ConnectTimeout=20 root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml /tmp/server-compose.yml
py - <<'PY'
import re, io
def declared(path):
    out, svc = {}, None
    for raw in io.open(path, encoding="utf-8", errors="replace"):
        l = raw.rstrip("\n")
        m = re.match(r"^  ([a-zA-Z0-9_.-]+):\s*$", l)
        if m:
            svc = m.group(1); out.setdefault(svc, set()); continue
        s = l.strip()
        if s.startswith("#") or not s:
            continue
        m2 = re.match(r"^- ([A-Z0-9_]+)=", s)
        if m2 and svc:
            out[svc].add(m2.group(1))
    return out
a = declared(r"docker-compose.unified.yml")
b = declared(r"/tmp/server-compose.yml")
for s in sorted(set(a) | set(b)):
    x, y = a.get(s, set()), b.get(s, set())
    if x != y:
        print("SERVICE", s, "| only in repo:", sorted(x - y), "| only on server:", sorted(y - x))
print("compared", len(set(a) | set(b)), "services")
PY
```

Expected: the only difference is `OPENWEBUI_URL` under `tasks`, which is the line this plan adds. Anything else means somebody edited the server's copy. STOP and reconcile before deploying.

- [ ] **Step 3: Back up the server's compose, then copy the changed files**

```bash
cd "C:/All/Work - Code/ai_ui"
ssh root@46.224.193.25 "cp -a /root/proxy-server/docker-compose.unified.yml /root/compose-backup-agents-on-schedule.yml"

for f in docker-compose.unified.yml \
         mcp-servers/tasks/agent_runner.py \
         mcp-servers/tasks/scheduler.py \
         mcp-servers/tasks/models.py \
         mcp-servers/tasks/routes_schedules.py \
         mcp-servers/tasks/migrations/041_schedule_agent_id.sql \
         mcp-servers/tasks/static/cron.html; do
  want=$(tr -d '\r' < "$f" | sha256sum | cut -c1-16)
  for try in 1 2 3 4; do
    scp -q -o ConnectTimeout=20 "$f" "root@46.224.193.25:/root/proxy-server/$f" 2>/dev/null
    got=$(ssh -o ConnectTimeout=20 root@46.224.193.25 \
      "sed -i 's/\r$//' /root/proxy-server/$f 2>/dev/null; tr -d '\r' < /root/proxy-server/$f 2>/dev/null | sha256sum | cut -c1-16")
    [ "$want" = "$got" ] && { echo "OK $f"; break; }
    echo "  retry $try for $f"; sleep 5
  done
done
```

Expected: `OK` for all seven. Do not proceed on a mismatch: this link truncated a 90KB file to 77KB on 2026-08-20.

- [ ] **Step 4: Rebuild and confirm the migration ran**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && \
  docker compose -f docker-compose.unified.yml up -d --build tasks"

ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \
  \"select column_name from information_schema.columns \
    where table_schema='tasks' and table_name='schedules' and column_name='agent_id';\""
```

Expected: `tasks Started`, then `agent_id`. `db.py` runs every migration on startup, so the column appears without a manual step.

- [ ] **Step 5: Confirm the URL actually reaches the container**

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc 'printenv OPENWEBUI_URL || echo NOT_INJECTED'"
```

Expected: `http://open-webui:8080`. `NOT_INJECTED` means the compose edit did not take, and the runner would fall back to its default while any override silently did nothing.

- [ ] **Step 6: The check no test can do**

On the Cron page, create a schedule that runs a minute or two ahead, set **Run as** to one of the ready-made agents, and give it a prompt only that agent could answer well, for example "list anything urgent in my unread mail" with Triage.

Then wait for it to fire and check the card:

```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \
  \"select name, agent_id, last_run_status, left(coalesce(last_result,''), 200) \
    from tasks.schedules where agent_id is not null order by updated_at desc limit 3;\""
```

Expected: `last_run_status` is `completed` and `last_result` is an answer that shows the agent's tools ran, not an apology about being unable to reach the mailbox. This is the first proof that a scheduled agent has the same abilities as the one in a DM, and no stubbed test can show it.

- [ ] **Step 7: Confirm an ordinary schedule is untouched**

```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \
  \"select count(*) from tasks.schedules where agent_id is null;\""
```

Then run one of those from the Cron page with **Run now** and confirm it still completes.

Expected: the existing schedules still run the way they always have. This is the regression that matters most, because every schedule that exists today is in that state.

- [ ] **Step 8: Record it**

```bash
git commit --allow-empty -m "chore(schedules): agents on a schedule deployed

Migration 041 applied on startup, OPENWEBUI_URL confirmed reaching the tasks
container, and a real schedule run as an agent delivered an answer its tools
had to produce.

Also confirmed the case that matters most: a schedule with no agent still runs
the way it always has. Every schedule that existed before this change is in
that state."
```

---

## Rollback

| If | Then |
|---|---|
| Agent runs misbehave | `UPDATE tasks.schedules SET agent_id = NULL;` Every schedule returns to the CLI executor immediately, with no deploy. |
| The runner is broken | `git revert` the Task 2 commit and rebuild tasks. The column and the form are inert without the branch. |
| The whole thing needs undoing | Revert Tasks 1 to 3 and rebuild. The column can stay: a nullable unused column costs nothing, and dropping it on a live table is the riskier move. |
| The compose edit broke something | `cp /root/compose-backup-agents-on-schedule.yml /root/proxy-server/docker-compose.unified.yml` and rebuild. |
