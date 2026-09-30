# Live Agent Office Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** The Agent Office draws a run, a tool call and a handoff within about a second of it happening, instead of on a five second poll.

**Architecture:** An in-process asyncio fan-out (`agent_events.py`) that the existing write sites publish to, one SSE endpoint (`GET /agents/stream`, scoped to the caller), and an `EventSource` in `office.html` that applies events to the floor it already draws. The poll stays as a 30 second fallback and resync. Spec: `docs/superpowers/specs/2026-09-29-live-agent-office-design.md` (approved by Ralph).

**Tech Stack:** FastAPI, `sse_starlette.EventSourceResponse` (3.0.3, already used by `routes_agent_chat.py:904`), asyncio queues, vanilla JS `EventSource`, pytest (`asyncio_mode = auto`), Playwright 1.52 for browser tests.

**Ground rules for whoever runs this:**
- All paths below are relative to `mcp-servers/tasks/` unless they start with `docs/`.
- Run tests from `mcp-servers/tasks/`. About 130 `ERROR at setup` from `db_session` is normal locally; nothing in this plan touches the DB tier.
- `tests/conftest.py` mutes `agent_activity.record_step` for every test (fixture `_no_agent_step_recording`). A test that exercises `record_step` must override that fixture by defining one with the same name in its own file, as `tests/test_agent_step_record.py` does.
- Commit with `git -c core.safecrlf=false commit`. Push only to `fork`, after `gh auth switch -u Jacintalama` and `git fetch fork`.
- No emoji or icons anywhere in UI text.

---

### Task 1: The bus (`agent_events.py`)

**Files:**
- Create: `agent_events.py`
- Test: `tests/test_agent_events.py`

**Step 1: Write the failing tests**

```python
"""The live office's fan-out: right person, no prose, never costs a turn."""
import asyncio
import json

import pytest

import agent_events

ALLOWED = {"event", "agent_id", "tool", "target_agent_id", "status", "at"}


@pytest.fixture(autouse=True)
def _empty_bus():
    agent_events._SUBS.clear()
    yield
    agent_events._SUBS.clear()


def test_an_event_reaches_every_page_of_its_owner_and_nobody_else():
    mine_1 = agent_events.subscribe("me@example.com")
    mine_2 = agent_events.subscribe("me@example.com")
    theirs = agent_events.subscribe("them@example.com")

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")

    assert mine_1.queue.qsize() == 1
    assert mine_2.queue.qsize() == 1
    assert theirs.queue.qsize() == 0


def test_a_subscriber_that_raises_does_not_reach_the_publisher():
    class Broken:
        def put_nowait(self, _):
            raise RuntimeError("boom")
    bad = agent_events.subscribe("me@example.com")
    bad.queue = Broken()
    good = agent_events.subscribe("me@example.com")

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")        # must not raise

    assert good.queue.qsize() == 1


def test_a_full_page_is_dropped_and_the_others_keep_receiving(monkeypatch):
    monkeypatch.setattr(agent_events, "MAX_QUEUE", 2)
    slow = agent_events.subscribe("me@example.com")
    monkeypatch.setattr(agent_events, "MAX_QUEUE", 100)
    fast = agent_events.subscribe("me@example.com")

    for _ in range(3):
        agent_events.publish("tool_started", agent_id="agent-a",
                             user_email="me@example.com", tool="search_drive")

    assert slow.dropped is True
    assert slow not in agent_events._SUBS.get("me@example.com", set())
    assert fast.queue.qsize() == 3


@pytest.mark.parametrize("event", sorted(agent_events.EVENTS))
def test_each_event_carries_only_names_and_never_the_owner(event):
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish(event, agent_id="agent-a", user_email="me@example.com",
                         tool="ask_colleague", target_agent_id="agent-b",
                         status="ok")
    payload = sub.queue.get_nowait()
    assert payload["event"] == event
    assert set(payload) <= ALLOWED
    assert "me@example.com" not in json.dumps(payload)


def test_an_unknown_event_is_not_sent():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("question_asked", agent_id="agent-a",
                         user_email="me@example.com")
    assert sub.queue.qsize() == 0


async def test_the_stream_says_hello_then_delivers_then_ends_when_dropped():
    gen = agent_events.stream("me@example.com", poll_seconds=0.05)
    first = await gen.__anext__()
    assert first["event"] == "hello"

    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com")
    nxt = await asyncio.wait_for(gen.__anext__(), 1)
    assert nxt["event"] == "run_started"
    assert json.loads(nxt["data"])["agent_id"] == "agent-a"

    (sub,) = agent_events._SUBS["me@example.com"]
    sub.dropped = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 1)
    assert "me@example.com" not in agent_events._SUBS
```

**Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_agent_events.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'agent_events'`.

**Step 3: Write `agent_events.py`**

```python
"""The office's live feed: what an agent is doing, the moment it does it.

An in-process fan-out. tasks runs ONE uvicorn process (Dockerfile:46, no
--workers) and every agent turn runs inside it, so a dict of asyncio queues
reaches every open office. No Redis, nothing else to keep alive.

A fan-out, not a log: a page that was not connected misses what happened,
which is why every stream opens with `hello` and the page re-reads
/agents/activity on it. Spec:
docs/superpowers/specs/2026-09-29-live-agent-office-design.md
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: Five moments, each one a thing that really happened. Nothing else is sent.
EVENTS = frozenset({"run_started", "tool_started", "tool_finished",
                    "handoff", "run_finished"})

#: Per open page. One that falls this far behind is dropped, not buffered:
#: the box has 3.8GB, and the browser reconnects and re-reads anyway.
MAX_QUEUE = 100


class Subscriber:
    __slots__ = ("user_email", "queue", "dropped")

    def __init__(self, user_email: str):
        self.user_email = user_email
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.dropped = False


_SUBS: dict[str, set[Subscriber]] = {}


def subscribe(user_email: str) -> Subscriber:
    sub = Subscriber(user_email)
    _SUBS.setdefault(user_email, set()).add(sub)
    return sub


def unsubscribe(sub: Subscriber) -> None:
    subs = _SUBS.get(sub.user_email)
    if subs is None:
        return
    subs.discard(sub)
    if not subs:
        _SUBS.pop(sub.user_email, None)


def publish(event: str, *, agent_id: str | None, user_email: str | None,
            tool: str | None = None, target_agent_id: str | None = None,
            status: str | None = None) -> None:
    """Send one event to every open office of `user_email`. Never raises.

    No prose, by construction: there is no parameter for a question, an
    answer or a tool's arguments, the same rule agent_step follows. The
    owner routes the event and is never put in it.
    """
    try:
        if event not in EVENTS or not agent_id or not user_email:
            return
        payload = {"event": event, "agent_id": agent_id,
                   "at": datetime.now(timezone.utc).isoformat()}
        if tool:
            payload["tool"] = tool
        if target_agent_id:
            payload["target_agent_id"] = target_agent_id
        if status:
            payload["status"] = status
        for sub in list(_SUBS.get(user_email, ())):
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                sub.dropped = True
                unsubscribe(sub)
            except Exception:                               # noqa: BLE001
                logger.warning("live office: a page refused an event",
                               exc_info=True)
    except Exception:                                       # noqa: BLE001
        logger.warning("live office: publish failed", exc_info=True)


async def stream(user_email: str, poll_seconds: float = 5.0):
    """Server-sent events for one open page, until it goes or is dropped.

    Subscribes on first iteration rather than at request time, so a request
    whose body is never iterated cannot leave a subscriber behind. The
    finally runs on a client disconnect too: EventSourceResponse cancels
    this generator when the connection closes.
    """
    sub = subscribe(user_email)
    try:
        yield {"event": "hello", "data": "{}"}
        while not sub.dropped:
            try:
                payload = await asyncio.wait_for(sub.queue.get(),
                                                 timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue
            if sub.dropped:
                break
            yield {"event": payload["event"], "data": json.dumps(payload)}
    finally:
        unsubscribe(sub)
```

**Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_agent_events.py -q`
Expected: 10 passed (5 parametrized plus 5).

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_events.py mcp-servers/tasks/tests/test_agent_events.py
git -c core.safecrlf=false commit -m "The office's live feed: one fan-out, scoped to its owner, no prose"
```

---

### Task 2: `agent_handoff.current_run()`

**Files:**
- Modify: `agent_handoff.py` (after `parent_run()`, near line 104)
- Test: `tests/test_agent_handoff.py` (append)

**Step 1: Write the failing test** (append to `tests/test_agent_handoff.py`)

```python
async def test_current_run_is_the_run_in_flight_nested_included():
    assert agent_handoff.current_run() is None
    async with agent_handoff.began("run-1"):
        assert agent_handoff.current_run() == "run-1"
        async with agent_handoff.began("run-2"):
            assert agent_handoff.current_run() == "run-2"
        assert agent_handoff.current_run() == "run-1"
    assert agent_handoff.current_run() is None
```

**Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_agent_handoff.py -q -k current_run`
Expected: FAIL, `AttributeError: module 'agent_handoff' has no attribute 'current_run'`.

**Step 3: Implement** (after `parent_run`)

```python
def current_run() -> str | None:
    """The run in flight right now, nested included, or None outside a turn.

    The same value parent_run() reads, asked a different question: this is
    "is a run open for this tool call", not "who asked". Nothing outside
    this module may read _RUN directly.
    """
    return _RUN.get()
```

**Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_agent_handoff.py -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_handoff.py mcp-servers/tasks/tests/test_agent_handoff.py
git -c core.safecrlf=false commit -m "A public way to ask which run is in flight"
```

---

### Task 3: Publish beside the writes in `agent_activity.py`

Publish only AFTER a successful commit, so an event can never disagree with the row. `finish_run` knows only the run id, so its UPDATE gains `RETURNING agent_id, user_email`: same statement, no extra round trip.

**Files:**
- Modify: `agent_activity.py` (`start_run` ~117, `finish_run` ~150, `record_step` ~193; add `import agent_events`)
- Test: `tests/test_agent_activity_events.py` (new)

**Step 1: Write the failing tests**

```python
"""Every event the floor draws is a row that was really written."""
import pytest

import agent_activity


@pytest.fixture(autouse=True)
def _no_agent_step_recording():
    """Overrides conftest's mute: these tests exercise record_step itself."""
    yield


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(agent_activity.agent_events, "publish",
                        lambda event, **kw: got.append((event, kw)))
    return got


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, row=None):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **kw):
        return _Result(self.row)

    async def commit(self):
        pass


class _Boom:
    async def __aenter__(self):
        raise RuntimeError("the database is not there")

    async def __aexit__(self, *a):
        return False


async def test_start_run_announces_the_run_it_wrote(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    run_id = await agent_activity.start_run("agent-a", "me@example.com",
                                            agent_activity.SOURCE_CHANNEL)
    assert run_id
    assert sent == [("run_started", {"agent_id": "agent-a",
                                     "user_email": "me@example.com"})]


async def test_a_run_that_was_not_written_is_not_announced(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    assert await agent_activity.start_run(
        "agent-a", "me@example.com", agent_activity.SOURCE_CHANNEL) is None
    assert sent == []


async def test_finish_run_announces_whose_run_ended_and_how(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session",
                        lambda: _Session(row=("agent-a", "me@example.com")))
    await agent_activity.finish_run("run-1", "ok")
    assert sent == [("run_finished", {"agent_id": "agent-a",
                                      "user_email": "me@example.com",
                                      "status": "ok"})]


async def test_finishing_an_unknown_run_announces_nothing(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session(row=None))
    await agent_activity.finish_run("run-nobody-wrote", "ok")
    assert sent == []


async def test_a_step_announces_the_tool_that_finished(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "search_drive", "ok")
    assert sent == [("tool_finished", {"agent_id": "agent-a",
                                       "user_email": "me@example.com",
                                       "tool": "search_drive",
                                       "status": "ok"})]


async def test_a_step_with_a_colleague_is_also_a_handoff(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Session())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "ask_colleague", "ok",
                                     target_agent_id="agent-b")
    assert [e for e, _ in sent] == ["tool_finished", "handoff"]
    assert sent[1][1]["target_agent_id"] == "agent-b"


async def test_a_step_that_was_not_written_is_not_announced(monkeypatch, sent):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    await agent_activity.record_step("run-1", "agent-a", "me@example.com",
                                     "search_drive", "ok")
    assert sent == []
```

**Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_agent_activity_events.py -q`
Expected: FAIL, `AttributeError: module 'agent_activity' has no attribute 'agent_events'`.

**Step 3: Implement**

Add `import agent_events` to the imports.

In `start_run`, after `await s.commit()` and before `return run_id`:
```python
        agent_events.publish("run_started", agent_id=agent_id,
                             user_email=user_email)
```

In `finish_run`, append ` RETURNING agent_id, user_email` to BOTH `UPDATE` statements, keep the result, and publish after the commit:
```python
            result = await s.execute(sql_text("UPDATE ... WHERE id = :id "
                                              "RETURNING agent_id, user_email"), {...})
            row = result.first()
            await s.commit()
        if row is not None:
            agent_events.publish("run_finished", agent_id=row[0],
                                 user_email=row[1], status=status)
```
(Initialise `row = None` before the `if usage is None` branch so both branches assign it. The publish stays inside the `try`.)

In `record_step`, after `await s.commit()`:
```python
        agent_events.publish("tool_finished", agent_id=agent_id,
                             user_email=user_email, tool=tool, status=status)
        if target_agent_id and target_agent_id != agent_id:
            agent_events.publish("handoff", agent_id=agent_id,
                                 user_email=user_email, tool=tool,
                                 target_agent_id=target_agent_id,
                                 status=status)
```

**Step 4: Run to verify they pass, and nothing nearby broke**

Run: `python -m pytest tests/test_agent_activity_events.py tests/test_agent_step_record.py tests/test_agent_activity.py tests/test_handoff_activity.py -q`
Expected: all pass except `test_each_cut_off_clears_the_worst_case_of_its_own_path`, which already fails on main (see "Known failure" at the end). It must fail with the same numbers as before, not new ones.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_activity.py mcp-servers/tasks/tests/test_agent_activity_events.py
git -c core.safecrlf=false commit -m "A run, a finished tool call and a handoff are announced as they are written"
```

---

### Task 4: `tool_started` from `execute_tool_call`

The one choke point both tool paths go through (`agent_runner.py:925`, `routes_agent_turn.py:433`). Published only while a run is open, so the floor never sees a tool start for a run it was never told about. Event only, no row: see the spec's "A start row for every step".

**Files:**
- Modify: `agent_tools.py` (in `execute_tool_call`, right after the `if not name: return outcome.failed(...)` check, before `if name == HANDOFF_TOOL:`; add `import agent_events`)
- Test: `tests/test_tool_started_event.py` (new)

**Step 1: Write the failing tests**

```python
"""The floor learns a tool started the moment it starts."""
import pytest

import agent_handoff
import agent_tools


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(agent_tools.agent_events, "publish",
                        lambda event, **kw: got.append((event, kw)))
    return got


def _call(name):
    return {"function": {"name": name, "arguments": "{}"}}


async def test_a_tool_call_inside_a_run_is_announced(sent):
    # HANDOFF_TOOL with allowed_native_tools=None is refused before any
    # lookup, so this runs with no network and no database.
    async with agent_handoff.began("run-1"):
        await agent_tools.execute_tool_call(
            _call(agent_tools.HANDOFF_TOOL), "me@example.com",
            allowed_native_tools=None, agent_id="agent-a")
    assert sent == [("tool_started", {"agent_id": "agent-a",
                                      "user_email": "me@example.com",
                                      "tool": agent_tools.HANDOFF_TOOL})]


async def test_a_tool_call_outside_any_run_is_not_announced(sent):
    await agent_tools.execute_tool_call(
        _call(agent_tools.HANDOFF_TOOL), "me@example.com",
        allowed_native_tools=None, agent_id="agent-a")
    assert sent == []


async def test_a_call_that_names_no_tool_is_not_announced(sent):
    async with agent_handoff.began("run-1"):
        await agent_tools.execute_tool_call(
            _call("  "), "me@example.com", agent_id="agent-a")
    assert sent == []
```

**Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tool_started_event.py -q`
Expected: FAIL, `AttributeError: module 'agent_tools' has no attribute 'agent_events'`.

**Step 3: Implement**

```python
    if agent_handoff.current_run():
        agent_events.publish("tool_started", agent_id=agent_id,
                             user_email=user_email, tool=name)
```

**Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_tool_started_event.py tests/test_ask_colleague.py tests/test_tool_step_recording.py -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_tools.py mcp-servers/tasks/tests/test_tool_started_event.py
git -c core.safecrlf=false commit -m "The floor hears a tool start, from the one place every tool call passes"
```

---

### Task 5: `GET /agents/stream`

**Files:**
- Modify: `routes_agents.py` (next to `@router.get("/activity")`, ~line 412; add `import agent_events` and `from sse_starlette.sse import EventSourceResponse`)
- Test: `tests/test_agents_stream_route.py` (new)

The web reaches it as `/api/tasks/agents/stream` (main.py mounts this router at `/api/tasks`). The gateway already streams `text/event-stream` through (`api-gateway/main.py:315-363`) and accepts the JWT from the `token` cookie (`:486-493`), which is how `EventSource` authenticates.

**Step 1: Write the failing test**

```python
"""The live stream is served, and only to the person it belongs to."""
import agent_events
import routes_agents


def test_the_stream_route_exists_and_is_a_get():
    paths = {(r.path, tuple(sorted(r.methods)))
             for r in routes_agents.router.routes}
    assert ("/agents/stream", ("GET",)) in paths


async def test_the_route_streams_the_callers_own_events(monkeypatch):
    class User:
        email = "me@example.com"
    agent_events._SUBS.clear()
    resp = await routes_agents.stream(user=User())
    assert resp.media_type == "text/event-stream"
    agent_events._SUBS.clear()
```

**Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_agents_stream_route.py -q`
Expected: FAIL, the route is not in the set / `AttributeError: ... has no attribute 'stream'`.

**Step 3: Implement**

```python
@router.get("/stream")
async def stream(user: CurrentUser = Depends(current_user)) -> EventSourceResponse:
    """The office's live feed: the caller's own agents, as it happens.

    Scoped exactly like /activity. One person's agent working is not
    another person's, and an admin watching must not see anyone else's
    floor. A comment every 20 seconds keeps Cloudflare and Caddy from
    reaping a connection that is merely idle, which on this floor is most
    of the day.
    """
    return EventSourceResponse(agent_events.stream(user.email), ping=20)
```

**Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_agents_stream_route.py tests/test_agent_events.py -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agents_stream_route.py
git -c core.safecrlf=false commit -m "GET /agents/stream: the caller's own agents, live"
```

---

### Task 6: The office listens

**Files:**
- Modify: `static/office.html`
- Test: `tests/browser/test_office_live.py` (new; harness copied from `tests/browser/test_office_page.py`)

**Step 1: Write the failing browser tests**

Copy `AGENTS`, the `browser` fixture and `_serve` from `tests/browser/test_office_page.py`. The page fixture differs in three ways: the served activity is a mutable dict read at request time, `/agents/stream` is answered with an SSE body the test chooses, and requests are counted.

```python
STREAM = {"body": "retry: 60000\n\nevent: hello\ndata: {}\n\n"}
SERVED = {"activity": {}}
HITS = {"activity": 0}


def _sse(*events):
    out = "retry: 60000\n\nevent: hello\ndata: {}\n\n"
    for e in events:
        out += "event: %s\ndata: %s\n\n" % (e["event"], json.dumps(e))
    return out


@pytest.fixture
def page(browser, request):
    SERVED["activity"] = {}
    HITS["activity"] = 0
    opts = getattr(request, "param", {})
    srv = _serve((STATIC / "office.html").read_bytes())
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    pg.set_default_timeout(6000)
    if opts.get("no_event_source"):
        pg.add_init_script("delete window.EventSource;")
    if opts.get("clock"):
        pg.clock.install()

    def route(r):
        url = r.request.url
        if "/agents/stream" in url:
            r.fulfill(status=200, content_type="text/event-stream",
                      body=STREAM["body"])
            return
        if "/models/list" in url:
            body = {"items": AGENTS, "total": len(AGENTS)}
        elif "/agents/activity" in url:
            HITS["activity"] += 1
            body = {"activity": SERVED["activity"], "handoffs": []}
        else:
            body = {"stats": {}} if "/agents/stats" in url else {"skills": []}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", route)
    pg.goto("http://127.0.0.1:%d/office.html" % srv.server_address[1])
    pg.wait_for_selector(".who", state="visible")
    yield pg
    pg.close()
    srv.shutdown()
```

Tests (set `STREAM["body"]` BEFORE the `page` fixture runs by using a small fixture that runs first, or parametrize through `request.param`; the simplest is a module-level setter fixture listed before `page` in the test signature):

```python
IRIS = "agent-iris-a103"


@pytest.fixture
def iris_starts_a_tool():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS, "at": "2026-09-30T10:00:00+00:00"},
        {"event": "tool_started", "agent_id": IRIS, "tool": "search_drive",
         "at": "2026-09-30T10:00:01+00:00"})
    yield
    STREAM["body"] = _sse()


def test_an_event_moves_the_floor_without_waiting_for_the_poll(iris_starts_a_tool, page):
    who = page.locator('.who[data-id="%s"]' % IRIS)
    who.and_(page.locator('[data-state="working"]')).wait_for(timeout=3000)
    assert who.locator(".tool-now").inner_text() == "search_drive"


@pytest.fixture
def a_stranger_starts():
    STREAM["body"] = _sse({"event": "run_started", "agent_id": "agent-not-mine",
                           "at": "2026-09-30T10:00:00+00:00"})
    yield
    STREAM["body"] = _sse()


def test_an_event_for_an_agent_not_on_this_floor_draws_nothing(a_stranger_starts, page):
    page.wait_for_timeout(1000)
    assert page.locator('.who[data-id="agent-not-mine"]').count() == 0
    assert page.locator('.who[data-state="working"]').count() == 0


@pytest.fixture
def fast_reconnect():
    STREAM["body"] = "retry: 150\n\nevent: hello\ndata: {}\n\n"
    yield
    STREAM["body"] = _sse()


def test_every_reconnect_rereads_the_floor(fast_reconnect, page):
    page.wait_for_timeout(1500)
    # One read at start, then one per connection's hello; the body ends
    # after hello, so EventSource reconnects every 150ms.
    assert HITS["activity"] >= 4, HITS


@pytest.mark.parametrize("page", [{"no_event_source": True, "clock": True}],
                         indirect=True)
def test_without_event_source_the_slow_poll_still_updates(page):
    SERVED["activity"] = {IRIS: {"state": "working", "running_for_seconds": 3,
                                 "last_run_at": "2026-09-30T10:00:00+00:00",
                                 "source": "channel"}}
    page.clock.fast_forward(6000)
    assert page.locator('.who[data-id="%s"][data-state="working"]' % IRIS).count() == 0
    page.clock.fast_forward(25000)
    page.locator('.who[data-id="%s"][data-state="working"]' % IRIS).wait_for(timeout=3000)
```

**Step 2: Run to verify they fail**

Run: `python -m pytest tests/browser/test_office_live.py -q`
Expected: the first three FAIL (no EventSource in the page, no `.tool-now`, one activity hit), the fourth FAILS at the 6 second assertion because the poll is still 5 seconds.

**Step 3: Implement in `static/office.html`**

1. State, next to `var AGENTS = [], ACTIVITY = {}, ...` (~line 506):
```js
  //: Which tool each agent is running right now, from the live feed only.
  var TOOL_NOW = {};
```
2. Live timer without the server: in `loadActivity`, after `ACTIVITY = got.activity || {};`:
```js
      var now = Date.now();
      Object.keys(ACTIVITY).forEach(function (id) {
        var a = ACTIVITY[id];
        if (a.state === "working") a._since = now - (a.running_for_seconds || 0) * 1000;
      });
```
   and in `stateOf`, compute the seconds from `_since` when present:
```js
      var secs = a._since != null ? Math.max(0, Math.round((Date.now() - a._since) / 1000))
                                  : a.running_for_seconds;
      return { key: "working", label: "Working" + (secs != null ? " " + secs + "s" : "") };
```
   Measured from the browser's own clock both times, so server clock skew cannot make it negative.
3. `applyEvent`, after `loadActivity`:
```js
  //: One event from /agents/stream, applied to what the floor holds. Each is
  //: a row the server just wrote (tool_started: a call it just began), so
  //: this is the poll's truth, sooner.
  function applyEvent(e) {
    if (!e || !e.agent_id) return;
    var a = ACTIVITY[e.agent_id] || {};
    if (e.event === "run_started") {
      ACTIVITY[e.agent_id] = Object.assign({}, a, { state: "working",
        running_for_seconds: 0, _since: Date.now(), last_run_at: e.at });
    } else if (e.event === "tool_started") {
      TOOL_NOW[e.agent_id] = e.tool;
    } else if (e.event === "tool_finished") {
      if (TOOL_NOW[e.agent_id] === e.tool) delete TOOL_NOW[e.agent_id];
    } else if (e.event === "handoff") {
      if (e.target_agent_id && e.target_agent_id !== e.agent_id) {
        HANDOFFS = HANDOFFS.concat([{ from: e.agent_id, to: e.target_agent_id,
                                      status: e.status, at: e.at }]);
      }
    } else if (e.event === "run_finished") {
      delete TOOL_NOW[e.agent_id];
      var next = Object.assign({}, a, { last_status: e.status,
        state: e.status === "waiting" ? "waiting"
             : e.status === "failed" ? "failed" : "ready" });
      delete next.running_for_seconds;
      delete next._since;
      ACTIVITY[e.agent_id] = next;
    }
  }
```
4. `connectLive`, next to it:
```js
  //: "hello" opens every connection, each automatic reconnect included, and
  //: the floor re-reads on it: the stream is a fan-out, not a log, so what
  //: happened while disconnected is only in the database.
  var LIVE_EVENTS = ["run_started", "tool_started", "tool_finished",
                     "handoff", "run_finished"];
  function connectLive() {
    if (typeof window.EventSource !== "function") return;
    var es;
    try {
      es = new EventSource("/api/tasks/agents/stream", { withCredentials: true });
    } catch (x) { console.warn("[office] live feed unavailable", x); return; }
    es.addEventListener("hello", function () { loadActivity().then(draw); });
    LIVE_EVENTS.forEach(function (name) {
      es.addEventListener(name, function (ev) {
        var e;
        try { e = JSON.parse(ev.data); } catch (x) { return; }
        applyEvent(e);
        draw();
      });
    });
  }
```
5. The badge, in the robot slot markup (~line 806), right after the dot `<i class="dot ...">`:
```js
      (st.key === "working" && TOOL_NOW[m.id]
        ? '<span class="tool-now">' + esc(TOOL_NOW[m.id]) + '</span>' : "") +
```
   and CSS next to `.who .dot`:
```css
  .who .tool-now {
    position: absolute; top: -4px; left: 50%; transform: translateX(-50%);
    z-index: 3; max-width: 100%; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; padding: 1px 6px; border-radius: 8px;
    font: 600 10px/1.4 var(--font-ui); color: var(--text);
    background: var(--surface); border: 1px solid var(--border);
  }
```
6. The tail (~line 1485): the poll slows and the live feed starts. Also tick the working labels once a second so the timer moves between events:
```js
    // The live feed drives the floor now. The poll stays as the fallback
    // (no EventSource, no cookie, a gap the heartbeat missed), at 30s.
    connectLive();
    setInterval(function () { loadActivity().then(draw); }, 30000);
    setInterval(function () {
      document.querySelectorAll('.who[data-state="working"]').forEach(function (el) {
        var small = el.querySelector(".who-label small");
        if (small) small.textContent = stateOf(el.getAttribute("data-id")).label;
      });
    }, 1000);
```
   Update the comment on `window.aiuiRefreshOffice` ("The five second poll is what normally drives this") to say the live feed does, with the 30 second poll as fallback. Leave the function itself exactly as it is.

**Step 4: Run to verify they pass, and the old office tests still do**

Run: `python -m pytest tests/browser/test_office_live.py tests/browser/test_office_page.py tests/browser/test_office_inline.py -q`
Expected: all pass.

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/office.html mcp-servers/tasks/tests/browser/test_office_live.py
git -c core.safecrlf=false commit -m "The office listens: a run, a tool and a handoff drawn as they happen"
```

---

### Task 7: Verify on the server, through the real gateway

`python -c "import ..."` does not catch a NameError inside a function body (CLAUDE.md), and a fixture page cannot prove the gateway streams. This task is the proof.

**Step 1: Sweep, then deploy.** Hash-sweep the six changed runtime files on the host and in the container against the commit before Task 1 (CR stripped). Any mismatch means someone changed the server: stop and reconcile. Then scp each file to `/root/proxy-server/mcp-servers/tasks/...`, `sed -i 's/\r$//'`, `docker cp` each into `tasks:/app/...` (static into `/app/static/`), and check nothing is running before a restart:
```bash
docker exec postgres psql -U openwebui -d openwebui -Atc "select count(*) from tasks.items where status in ('running','planning')"
docker exec postgres psql -U openwebui -d openwebui -Atc "select count(*) from tasks.agent_run where finished_at is null and started_at > now() - interval '65 minutes'"
docker restart tasks && curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
```

**Step 2: The stream through the gateway, both auth paths.** Sign in through Open WebUI with the test account to get a JWT (password from an env var, never printed; token never printed). Then:
```bash
curl -sN -m 5 -H "Authorization: Bearer $T" https://ai-ui.coolestdomain.win/api/tasks/agents/stream   # first lines: event: hello
curl -sN -m 5 -b "token=$T"                  https://ai-ui.coolestdomain.win/api/tasks/agents/stream   # same, via the cookie
curl -s -o /dev/null -w "%{http_code}\n" -m 5 https://ai-ui.coolestdomain.win/api/tasks/agents/stream # no auth: 401
```

**Step 3: A real turn, timed.** Keep a timestamped stream open (`curl -sN ... | while IFS= read -r l; do echo "$(date +%s.%N) $l"; done > live.log`), and inside the container open a second stream for a different email (`X-User-Email` on `localhost:8210/agents/stream`). Send one plain question to one of the test account's agents on a free model (no build, no code, so no paid escalation: $0). Then check:
1. `live.log` has `run_started`, any `tool_started`/`tool_finished`, then `run_finished`, in that order.
2. `run_started` arrived within 1 second of that run's `started_at` in `tasks.agent_run`.
3. The other email's stream received `hello` and pings only.

**Step 4: Look at it in a browser.** Open the office as the test account, send the same kind of question from the agents page, and screenshot the robot working with its badge before the answer lands.

**Step 5: Stamp and push.** Update `.deploy-state` (JSON) to the new HEAD, push `main` to `fork`, and mark 2.1 done in `docs/HANDOFF-2026-09-30-agent-office.md`.

---

### Known failure, not caused by this plan

`tests/test_agent_activity.py::test_each_cut_off_clears_the_worst_case_of_its_own_path` fails on `main` and on the code production runs (checked in the container 2026-09-30): `3900s > 3840s + 240s` is false. `6182406aa` put the free pool back to four models, which lengthened a scheduled agent's worst case past `STALE_AFTER_SCHEDULE` (65 minutes), so a healthy long schedule can be marked failed. Fixing it is a separate decision about that window. It must not be "fixed" by editing the test.
