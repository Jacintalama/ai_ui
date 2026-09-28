# Agent Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent that hits the edge of its own job can ask a colleague, get the answer back as a tool result, and finish its own turn with it.

**Architecture:** The handoff is a tool call. `ask_colleague` is visible to models through an Open WebUI tool row (a spec is what makes a tool visible at all), but tasks intercepts it **by name inside `execute_tool_call`** and never exec's that row's body. That keeps the depth, cycle and permission guards in trusted code rather than in a row anybody can edit in the web UI. Everything runs in-process in the tasks container, so a `ContextVar` carries the handoff stack without threading a parameter through Open WebUI's plumbing.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy `text()` over asyncpg, pytest with `asyncio_mode = auto`, Postgres.

**Spec:** `docs/superpowers/specs/2026-09-28-agent-handoff-design.md`

## Global Constraints

- **Never raises into a turn.** Every refusal is returned as a tool-result sentence. `execute_tool_call`'s contract is that it never raises.
- **Recording fails open.** A failed `agent_step` insert must never cost somebody their turn. Log and continue, exactly like `agent_activity.start_run` returning `None`.
- **No prose is stored.** Never the question, never the answer. Tool name, agent ids and status only.
- **Owner scoping everywhere.** The colleague is resolved from the caller's own roster. An agent id from a model argument is never trusted.
- **A level is a ceiling.** A surface may narrow it and may never widen it (`agent_access.py` module docstring).
- **Depth cap is 2. At most 2 handoffs per turn.**
- **Migrations are additive and idempotent.** `db.py` re-runs every migration on each startup.
- **Local test reality:** ~130 tests error at setup with `asyncpg.connect(...)` because there is no local Postgres. That is pre-existing. Confirm any failure you see says `ERROR at setup` before blaming your change.
- **Do not kill processes named `chrome.exe`.** Filter on `ms-playwright` in the executable path; the owner's own browser has the same image name.

## Review Focus

Five things the spec implies that no single task's happy path exercises. Each has a test added to the task that owns the code.

1. **A model naming an agent that is not the owner's** — must refuse in a sentence, not raise, and must not run a turn. Task 5.
2. **A model naming itself** — self-handoff is a cycle of length one and must refuse. Task 2.
3. **`ask_colleague` called when the agent was never granted it** — must not execute; the existing `tool_ids` scoping must still apply. Task 5.
4. **A colleague whose own turn raises `ApprovalRequired`** — impossible by construction once `ask` narrows, so a test must pin that `effective_mode` never returns `MODE_ASK` for the colleague surface. Task 1.
5. **A step row written for a call that was refused** — the refusal is a fact worth recording, and `finished_at` must still be set. Task 4.

---

### Task 1: The colleague surface in `agent_access`

**Files:**
- Modify: `mcp-servers/tasks/agent_access.py`
- Test: `mcp-servers/tasks/tests/test_agent_access.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `agent_access.SURFACE_COLLEAGUE` (str `"colleague"`); `effective_mode(level, tool_mode, surface)` and `refusal_reason(level, tool_mode, surface)` both accept it.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_agent_access.py`:

```python
# --- a colleague asked by another agent -------------------------------------
# A handoff has nobody watching the way a channel does: the owner is in a
# conversation with the ASKING agent, so a prompt raised here would ask them
# about a conversation they are not in.

def test_a_colleague_set_to_all_may_act():
    assert agent_access.effective_mode(
        agent_access.LEVEL_ALL, None,
        agent_access.SURFACE_COLLEAGUE) == agent_access.MODE_FULL


def test_a_colleague_set_to_ask_narrows_to_read_only():
    """Narrows rather than prompting. This is what makes ApprovalRequired
    impossible inside a handoff."""
    assert agent_access.effective_mode(
        agent_access.LEVEL_ASK, None,
        agent_access.SURFACE_COLLEAGUE) == agent_access.MODE_READ_ONLY


def test_a_colleague_set_to_read_stays_read_only():
    assert agent_access.effective_mode(
        agent_access.LEVEL_READ, None,
        agent_access.SURFACE_COLLEAGUE) == agent_access.MODE_READ_ONLY


def test_a_colleague_with_no_level_is_read_only():
    """An absent level is not a default. An agent that predates the feature
    has expressed no opinion, and a handoff is the one surface where
    guessing 'full' would let one agent widen another."""
    assert agent_access.effective_mode(
        None, None, agent_access.SURFACE_COLLEAGUE) == agent_access.MODE_READ_ONLY


def test_a_colleague_is_never_asked():
    """Review Focus 4. If this can return ask, ApprovalRequired can be
    raised inside a handoff and the two-level resume problem is back."""
    for level in (None, agent_access.LEVEL_READ, agent_access.LEVEL_ASK,
                  agent_access.LEVEL_ALL):
        assert agent_access.effective_mode(
            level, None, agent_access.SURFACE_COLLEAGUE) != agent_access.MODE_ASK


def test_a_schedules_tool_mode_cannot_widen_a_colleague():
    """A level is a ceiling. Nothing a caller passes may widen it."""
    assert agent_access.effective_mode(
        agent_access.LEVEL_READ, agent_access.MODE_FULL,
        agent_access.SURFACE_COLLEAGUE) == agent_access.MODE_READ_ONLY


def test_the_refusal_says_a_colleague_cannot_be_asked():
    said = agent_access.refusal_reason(
        agent_access.LEVEL_ASK, None, agent_access.SURFACE_COLLEAGUE)
    assert "colleague" in said or "another agent" in said
    assert not said.endswith(".")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_access.py -q -k colleague`
Expected: FAIL with `AttributeError: module 'agent_access' has no attribute 'SURFACE_COLLEAGUE'`

- [ ] **Step 3: Add the surface**

In `agent_access.py`, beside the existing surfaces:

```python
SURFACE_CHANNEL = "channel"
SURFACE_SCHEDULE = "schedule"
#: One agent asked another. Nobody is watching THIS conversation: the owner
#: is talking to the agent that asked, so a prompt raised here would ask them
#: about a conversation they are not in, and answering it would need the
#: colleague's reply written back into a turn that is paused mid-sentence.
#: So `ask` narrows here instead of prompting, which makes ApprovalRequired
#: impossible inside a handoff rather than merely unlikely.
SURFACE_COLLEAGUE = "colleague"
```

In `effective_mode`, as the first branch after the channel one:

```python
    if surface == SURFACE_COLLEAGUE:
        # Only a level the owner set to `all` acts. tool_mode is ignored
        # entirely rather than defaulted: reading it here would give a
        # caller a way to widen a read-only agent, which is the hole this
        # module exists to close.
        if level == LEVEL_ALL:
            return MODE_FULL
        return MODE_READ_ONLY
```

In `refusal_reason`, matching position:

```python
    if surface == SURFACE_COLLEAGUE:
        return ("another agent asked this one, and it is not set to act on "
                "its own")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_access.py -q`
Expected: PASS, all of them, including the pre-existing channel and schedule cases.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_access.py mcp-servers/tasks/tests/test_agent_access.py
git commit -m "A colleague asked by another agent acts only if set to all"
```

---

### Task 2: The handoff stack

**Files:**
- Create: `mcp-servers/tasks/agent_handoff.py`
- Test: `mcp-servers/tasks/tests/test_agent_handoff.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `agent_handoff.MAX_DEPTH` (int `2`); `MAX_PER_TURN` (int `2`); `stack()` returning `tuple[str, ...]`; `entered(agent_id)` an async context manager; `began(run_id)` an async context manager; `parent_run()` returning `str | None`; `spent()` returning `int`; `spend()`; `refusal(caller_id, target_id)` returning `str | None` where `None` means allowed.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agent_handoff.py`:

```python
"""How deep a handoff may go, and who may not be asked.

A colleague's turn runs in the same asyncio task as the caller's, so a
ContextVar carries the stack without threading a parameter through Open
WebUI's native-tool plumbing.

Every refusal is a sentence, never an exception: execute_tool_call's whole
contract is that it does not raise, and a caller that is told "no, because"
can write up what it has.
"""
import agent_handoff


async def test_nothing_is_on_the_stack_to_begin_with():
    assert agent_handoff.stack() == ()


async def test_entering_puts_the_agent_on_the_stack():
    async with agent_handoff.entered("agent-nora"):
        assert agent_handoff.stack() == ("agent-nora",)


async def test_leaving_takes_it_off_again():
    async with agent_handoff.entered("agent-nora"):
        pass
    assert agent_handoff.stack() == ()


async def test_an_error_still_takes_it_off():
    try:
        async with agent_handoff.entered("agent-nora"):
            raise RuntimeError("the turn blew up")
    except RuntimeError:
        pass
    assert agent_handoff.stack() == ()


async def test_a_first_handoff_is_allowed():
    assert agent_handoff.refusal("agent-nora", "agent-iris") is None


async def test_asking_yourself_is_refused():
    """Review Focus 2. A self-handoff is a cycle of length one, and it is
    what a confused model reaches for first."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said and "itself" in said


async def test_asking_back_up_the_stack_is_refused():
    async with agent_handoff.entered("agent-nora"):
        async with agent_handoff.entered("agent-iris"):
            said = agent_handoff.refusal("agent-iris", "agent-nora")
            assert said and "already" in said


async def test_past_the_depth_cap_is_refused():
    async with agent_handoff.entered("agent-a"):
        async with agent_handoff.entered("agent-b"):
            said = agent_handoff.refusal("agent-b", "agent-c")
            assert said and "too many" in said


async def test_the_cap_is_two():
    assert agent_handoff.MAX_DEPTH == 2


async def test_a_third_handoff_in_one_turn_is_refused():
    """Depth limits how long a chain is. This limits how MANY an agent
    starts: one agent calling the tool five times is five extra turns on a
    box that runs them one at a time, and no chain was ever two deep."""
    async with agent_handoff.began("run-1"):
        agent_handoff.spend()
        agent_handoff.spend()
        said = agent_handoff.refusal("agent-nora", "agent-iris")
    assert said and "already asked" in said


async def test_the_breadth_cap_is_two():
    assert agent_handoff.MAX_PER_TURN == 2


async def test_a_turn_knows_the_run_that_asked():
    async with agent_handoff.began("run-1"):
        assert agent_handoff.parent_run() == "run-1"


async def test_outside_a_turn_there_is_no_parent():
    assert agent_handoff.parent_run() is None


async def test_a_refusal_reads_as_an_answer_not_an_error():
    """The caller shows this to the owner, so it has to be a sentence they
    can act on rather than a stack trace."""
    said = agent_handoff.refusal("agent-nora", "agent-nora")
    assert said.endswith(".")
    assert said[0].isupper()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_handoff.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_handoff'`

- [ ] **Step 3: Write the module**

Create `mcp-servers/tasks/agent_handoff.py`:

```python
"""How far one agent may follow another.

A colleague's turn runs in the same asyncio task as the caller's, because
execute_tool_call exec's a native tool's source in-process rather than going
back out over HTTP. So a ContextVar carries the stack, and nothing has to be
threaded through Open WebUI's native-tool plumbing.

The guard lives here, in trusted code, and NOT in the tool's own Open WebUI
row: that row is editable from the web UI, and a depth cap somebody can edit
away is not a depth cap.

Every refusal is a sentence rather than an exception. execute_tool_call's
whole contract is that it never raises, and an agent that is told "no,
because" can write up what it has instead of the turn dying.
"""
from __future__ import annotations

import contextlib
import contextvars

#: How many agents deep a chain may go. Two: Nora may ask Iris, and Iris may
#: ask one more, and that is the end of it. Each level is a whole extra turn
#: on a box that runs them one at a time.
MAX_DEPTH = 2

#: How many colleagues ONE turn may ask. Depth limits how long a chain gets;
#: this limits how wide it gets. Without it a single agent could call the
#: tool five times and spend five extra turns without ever going two deep.
MAX_PER_TURN = 2

_STACK: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "agent_handoff_stack", default=())

#: The top-level run everything in this chain hangs off, and how many
#: handoffs it has spent. A one-item list rather than an int because a
#: nested turn must increment the SAME budget its caller is spending, and a
#: ContextVar set in a nested context would not be seen by the outer one.
_TURN: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "agent_handoff_turn", default=None)


def stack() -> tuple:
    """The agents currently waiting on a handoff, outermost first."""
    return _STACK.get()


@contextlib.asynccontextmanager
async def began(run_id: str | None):
    """Open a handoff budget for one top-level turn.

    Only the outermost turn opens one. A colleague's turn runs inside its
    caller's context and must spend the SAME budget, or two agents each
    asking twice would be four turns under a cap of two.
    """
    if _TURN.get() is not None:
        yield
        return
    token = _TURN.set({"run_id": run_id, "spent": 0})
    try:
        yield
    finally:
        _TURN.reset(token)


def parent_run() -> str | None:
    """The run a colleague's run should point at, or None outside a turn."""
    t = _TURN.get()
    return (t or {}).get("run_id")


def spent() -> int:
    t = _TURN.get()
    return int((t or {}).get("spent") or 0)


def spend() -> None:
    """Count one handoff against this turn's budget."""
    t = _TURN.get()
    if t is not None:
        t["spent"] = int(t.get("spent") or 0) + 1


@contextlib.asynccontextmanager
async def entered(agent_id: str):
    """Mark an agent as waiting on a colleague for the length of this block.

    Reset by token rather than by popping, so an exception on the way out
    cannot leave an agent stuck on the stack for the rest of the request.
    """
    token = _STACK.set(stack() + (agent_id,))
    try:
        yield
    finally:
        _STACK.reset(token)


def refusal(caller_id: str, target_id: str) -> str | None:
    """Why this handoff may not happen, or None when it may."""
    if caller_id and target_id and caller_id == target_id:
        return ("An agent cannot ask itself, so nothing was asked.")
    if target_id in stack():
        return ("That agent is already waiting on this one, so asking it "
                "back would go round in a circle. Nothing was asked.")
    if len(stack()) >= MAX_DEPTH:
        return ("That would be too many agents deep, so nothing was asked. "
                "Answer with what you have.")
    if spent() >= MAX_PER_TURN:
        return ("This turn has already asked as many colleagues as it may, "
                "so nothing was asked. Answer with what you have.")
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_handoff.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_handoff.py mcp-servers/tasks/tests/test_agent_handoff.py
git commit -m "How far one agent may follow another"
```

---

### Task 3: Migration 052

**Files:**
- Create: `mcp-servers/tasks/migrations/052_agent_step.sql`

**Interfaces:**
- Consumes: nothing.
- Produces: table `tasks.agent_step`; columns `tasks.agent_run.parent_run_id`.

- [ ] **Step 1: Write the migration**

Create `mcp-servers/tasks/migrations/052_agent_step.sql`:

```sql
-- 052: what an agent actually did, and who asked it to.
--
-- agent_run says an agent ran, for how long, on which model and at what
-- cost. It has never said what the agent DID. agent_runner handles
-- tool_calls in memory and persists none of it, so the office can say
-- "working" and nothing more.
--
-- A handoff between agents is a tool call, so one table records both what an
-- agent is doing and who it is collaborating with.
--
-- No prose is stored. Not the question, not the answer. The tool's name is
-- the useful part: search_drive is "searching Drive". Storing what was asked
-- would be a privacy cost with no payoff, and it sits badly beside the
-- private agent conversations added on 2026-09-25.
--
-- Additive and idempotent: db.py re-runs every migration on each startup.

CREATE TABLE IF NOT EXISTS tasks.agent_step (
    id              UUID        PRIMARY KEY,
    run_id          UUID        NOT NULL,
    agent_id        TEXT        NOT NULL,
    user_email      TEXT        NOT NULL,
    tool            TEXT        NOT NULL,
    -- Set only when the tool was a handoff. NULL for every other tool.
    target_agent_id TEXT,
    status          TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- "What did this run do", which is how a run is read back.
CREATE INDEX IF NOT EXISTS agent_step_run_idx
    ON tasks.agent_step (run_id);

-- "What has this person's office been doing lately", which is how the
-- activity surfaces read it.
CREATE INDEX IF NOT EXISTS agent_step_owner_recent_idx
    ON tasks.agent_step (user_email, started_at DESC);

-- Which run asked for this one. NULL for a run nobody asked for, which is
-- every run that exists today.
ALTER TABLE tasks.agent_run
    ADD COLUMN IF NOT EXISTS parent_run_id UUID;

CREATE INDEX IF NOT EXISTS agent_run_parent_idx
    ON tasks.agent_run (parent_run_id)
    WHERE parent_run_id IS NOT NULL;
```

- [ ] **Step 2: Check it parses**

Run: `cd mcp-servers/tasks && python -c "import pathlib; s = pathlib.Path('migrations/052_agent_step.sql').read_text(); assert 'CREATE TABLE IF NOT EXISTS tasks.agent_step' in s; assert s.count('IF NOT EXISTS') == 5; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add mcp-servers/tasks/migrations/052_agent_step.sql
git commit -m "Record what an agent did, and who asked it to"
```

---

### Task 4: Recording a step

**Files:**
- Modify: `mcp-servers/tasks/agent_activity.py`
- Test: `mcp-servers/tasks/tests/test_agent_step_record.py`

**Interfaces:**
- Consumes: `agent_handoff` (not used here), migration 052.
- Produces:
  - `agent_activity.SOURCE_COLLEAGUE` (str `"colleague"`)
  - `async start_step(run_id, agent_id, user_email, tool, target_agent_id=None) -> str | None`
  - `async finish_step(step_id, status) -> None`
  - `start_run(agent_id, user_email, source, parent_run_id=None) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agent_step_record.py`:

```python
"""Recording what an agent did, without ever costing it its turn.

Only the in-memory half runs here. The SQL half needs a real Postgres and is
verified in the container: this repo's destructive DB tests once wiped nine
production projects, so they are not run locally.
"""
import agent_activity


class _Boom:
    """A session that fails the way a database that is down fails."""
    async def __aenter__(self):
        raise RuntimeError("the database is not there")

    async def __aexit__(self, *a):
        return False


async def test_a_step_with_no_run_records_nothing():
    """start_run returns None when its own write failed. A step belonging to
    a run that was never recorded has nothing to hang off."""
    assert await agent_activity.start_step(
        None, "agent-a", "me@example.com", "search_drive") is None


async def test_a_step_with_no_tool_records_nothing():
    assert await agent_activity.start_step(
        "run-1", "agent-a", "me@example.com", "") is None


async def test_a_failing_insert_does_not_raise(monkeypatch):
    """Review Focus 5 support, and the rule the whole module follows: the
    run matters, the bookkeeping does not."""
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    assert await agent_activity.start_step(
        "run-1", "agent-a", "me@example.com", "search_drive") is None


async def test_finishing_a_step_that_was_never_recorded_is_safe():
    await agent_activity.finish_step(None, "ok")


async def test_a_failing_finish_does_not_raise(monkeypatch):
    monkeypatch.setattr(agent_activity, "session", lambda: _Boom())
    await agent_activity.finish_step("step-1", "ok")


async def test_there_is_a_colleague_source():
    """So the office can say 'Iris is helping Nora' as a fact rather than an
    animation."""
    assert agent_activity.SOURCE_COLLEAGUE == "colleague"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_step_record.py -q`
Expected: FAIL with `AttributeError: module 'agent_activity' has no attribute 'start_step'`

- [ ] **Step 3: Write the implementation**

In `agent_activity.py`, beside the existing sources:

```python
SOURCE_SCHEDULE = "schedule"
SOURCE_CHANNEL = "channel"
#: Another agent asked for this run. The office reads it to say who is
#: helping whom, which is a fact about a row rather than an animation.
SOURCE_COLLEAGUE = "colleague"
```

Change `start_run` to carry the run that asked:

```python
async def start_run(agent_id: str, user_email: str, source: str,
                    parent_run_id: str | None = None) -> str | None:
    """Record that an agent has started working. Returns the run id, or None.

    None means the bookkeeping failed, and the caller carries on regardless:
    the run itself matters, this does not.

    `parent_run_id` is the run that asked for this one, for a handoff. None
    for a run nobody asked for, which is every run that existed before
    agents could ask each other.
    """
    if not agent_id or not user_email:
        return None
    run_id = str(uuid.uuid4())
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "INSERT INTO tasks.agent_run "
                    "(id, agent_id, user_email, source, status, parent_run_id) "
                    "VALUES (:id, :agent_id, :user_email, :source, 'running', "
                    ":parent_run_id)"),
                {"id": run_id, "agent_id": agent_id,
                 "user_email": user_email, "source": source,
                 "parent_run_id": parent_run_id})
            await s.commit()
        return run_id
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the start of an agent run",
                       exc_info=True)
        return None
```

Add the two step functions after `finish_run`:

```python
async def start_step(run_id: str | None, agent_id: str, user_email: str,
                     tool: str, target_agent_id: str | None = None
                     ) -> str | None:
    """Record that a run has started one tool call. Returns the step id.

    None means it was not recorded, and every caller carries on regardless.
    A run that was never recorded (start_run returned None) has nothing for
    a step to hang off, so that returns None too rather than writing an
    orphan.

    No arguments and no result are stored, only the tool's name. See the
    migration for why.
    """
    if not run_id or not tool:
        return None
    step_id = str(uuid.uuid4())
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "INSERT INTO tasks.agent_step "
                    "(id, run_id, agent_id, user_email, tool, "
                    "target_agent_id, status) "
                    "VALUES (:id, :run_id, :agent_id, :user_email, :tool, "
                    ":target, 'running')"),
                {"id": step_id, "run_id": run_id, "agent_id": agent_id,
                 "user_email": user_email, "tool": tool,
                 "target": target_agent_id})
            await s.commit()
        return step_id
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the start of a tool call",
                       exc_info=True)
        return None


async def finish_step(step_id: str | None, status: str) -> None:
    """Close a step out. Safe to call with None.

    A refused call is finished too: a refusal is a fact worth recording, and
    a row left saying `running` for ever would read as a tool that hung.
    """
    if not step_id:
        return
    try:
        async with session() as s:
            await s.execute(
                sql_text(
                    "UPDATE tasks.agent_step "
                    "SET finished_at = now(), status = :status "
                    "WHERE id = :id"),
                {"id": step_id, "status": status})
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record the end of a tool call",
                       exc_info=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_step_record.py tests/test_agent_activity.py -q`
Expected: PASS. The existing `agent_activity` tests must still pass, because `parent_run_id` defaults to `None` and every existing caller passes three arguments.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_activity.py mcp-servers/tasks/tests/test_agent_step_record.py
git commit -m "Record each tool call, and which run asked for a run"
```

---

### Task 5: `ask_colleague`, intercepted in trusted code

**Files:**
- Modify: `mcp-servers/tasks/agent_tools.py`
- Test: `mcp-servers/tasks/tests/test_ask_colleague.py`

**Interfaces:**
- Consumes: `agent_handoff.refusal`, `agent_handoff.entered`, `agent_access.SURFACE_COLLEAGUE`.
- Produces: `agent_tools.HANDOFF_TOOL` (str `"ask_colleague"`); `async run_handoff(caller_id, user_email, target_name, question) -> str`; module-level seam `agent_tools._run_colleague_turn` for tests.

**Why the interception:** the tool is visible to models through an Open WebUI tool row, because a tool without a generated spec is invisible to every model. But `execute_tool_call` must NOT exec that row's body for this one: the row is editable from the web UI, and a depth cap somebody can edit away is not a depth cap.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_ask_colleague.py`:

```python
"""One agent asking another.

The tool is intercepted by name before the native-source path, so the guards
live here in trusted code rather than in a row that is editable from the web
UI. `_run_colleague_turn` is a module-level seam so these tests never run a
real turn, following the pattern in tests/test_autofix_loop.py.
"""
import agent_handoff
import agent_tools


def _call(name="ask_colleague", **args):
    import json
    return {"id": "call-1", "function": {"name": name,
                                         "arguments": json.dumps(args)}}


def _roster(*names):
    return [{"id": "agent-" + n.lower(), "name": n} for n in names]


async def test_the_colleague_is_asked_and_the_answer_comes_back(monkeypatch):
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        return "The spec is in Drive under Q3."

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "where is the spec")
    assert "Q3" in said
    assert "Iris" in said


async def test_an_agent_that_is_not_yours_is_refused(monkeypatch):
    """Review Focus 1. The id comes off a model, so it is never trusted."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Somebody Else", "hello")
    assert ran == []
    assert "no colleague" in said.lower()


async def test_asking_yourself_never_runs_a_turn(monkeypatch):
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Nora"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Nora", "hello")
    assert ran == []
    assert "itself" in said


async def test_too_deep_never_runs_a_turn(monkeypatch):
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    async with agent_handoff.entered("agent-a"):
        async with agent_handoff.entered("agent-b"):
            said = await agent_tools.run_handoff(
                "agent-b", "me@example.com", "Iris", "hello")
    assert ran == []
    assert "too many" in said


async def test_the_colleague_is_on_the_stack_while_it_answers(monkeypatch):
    """So a colleague that asks back up the chain is refused by Task 2's
    guard rather than looping."""
    seen = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        seen.append(agent_handoff.stack())
        return "done"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "hello")
    assert seen == [("agent-iris",)]


async def test_a_turn_that_blows_up_is_still_an_answer(monkeypatch):
    """execute_tool_call never raises, so neither does this."""
    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        raise RuntimeError("the colleague fell over")

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "hello")
    assert "could not" in said.lower()


async def test_an_empty_question_is_refused(monkeypatch):
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    said = await agent_tools.run_handoff(
        "agent-nora", "me@example.com", "Iris", "   ")
    assert "nothing to ask" in said.lower()


async def test_the_tool_is_named():
    assert agent_tools.HANDOFF_TOOL == "ask_colleague"


async def test_an_agent_without_the_tool_cannot_use_it(monkeypatch):
    """Review Focus 3. tool_ids scoping still applies: interception must not
    become a back door around the grant."""
    ran = []

    async def fake_turn(user_email, agent_id, question, parent_run_id=None):
        ran.append(agent_id)
        return "should not happen"

    monkeypatch.setattr(agent_tools, "_run_colleague_turn", fake_turn)
    monkeypatch.setattr(agent_tools, "_roster_for",
                        lambda email: _roster("Iris"))
    out = await agent_tools.execute_tool_call(
        _call(agent="Iris", question="hello"), "me@example.com",
        ["gdrive"], "agent-nora")
    assert ran == []
    assert "not been given" in out.lower() or "was not run" in out.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_ask_colleague.py -q`
Expected: FAIL with `AttributeError: module 'agent_tools' has no attribute 'HANDOFF_TOOL'`

- [ ] **Step 3: Write the implementation**

At the top of `agent_tools.py`, beside the other imports:

```python
import agent_handoff
```

Add near the other module constants:

```python
#: The one tool this module runs itself rather than exec'ing a native row.
#: The row exists so the model can SEE the tool -- a tool without a
#: generated spec is invisible to every model -- but its body is never run:
#: that row is editable from the web UI, and a depth cap somebody can edit
#: away is not a depth cap.
HANDOFF_TOOL = "ask_colleague"


async def _roster_for(user_email: str) -> list[dict]:
    """This person's own agents. A module-level seam so tests never call
    Open WebUI."""
    import routes_agent_turn
    return await routes_agent_turn._agents_for(user_email)


async def _run_colleague_turn(user_email: str, agent_id: str, question: str,
                              parent_run_id: str | None = None) -> str:
    """Run one turn as the colleague and return its answer.

    A module-level seam, so the tests above drive the handoff without
    running a browser, a model or a database -- the same pattern
    tests/test_autofix_loop.py uses.
    """
    import routes_agent_turn
    out = await routes_agent_turn._run_turn(
        user_email, agent_id, [{"role": "user", "content": question}],
        brief=True, surface=agent_access.SURFACE_COLLEAGUE,
        parent_run_id=parent_run_id)
    answer = (out or {}).get("answer") or ""
    notes = [n for n in ((out or {}).get("notes") or []) if isinstance(n, str)]
    if not answer and notes:
        answer = "\n".join(notes)
    return answer


def _match_colleague(roster: list[dict], wanted: str) -> dict | None:
    """The agent this name means, or None.

    Matched against the OWNER'S OWN roster and never trusted from the
    model's argument: the name arrives in text an agent read somewhere, and
    an id taken at face value would let a prompt-injected document address
    somebody else's agent.
    """
    want = (wanted or "").strip().lower()
    if not want:
        return None
    for a in roster or []:
        name = str(a.get("name") or "").strip().lower()
        if name == want or str(a.get("id") or "").strip().lower() == want:
            return a
    return None


async def run_handoff(caller_id: str, user_email: str, target_name: str,
                      question: str) -> str:
    """One agent asking another, as a tool result.

    Never raises and never returns an empty string: the caller shows this to
    its owner, so every outcome has to be a sentence they can act on.
    """
    asked = (question or "").strip()
    if not asked:
        return "There was nothing to ask, so no colleague was asked."

    roster = await _roster_for(user_email)
    target = _match_colleague(roster, target_name)
    if not target:
        return ("There is no colleague called %r on this account, so nothing "
                "was asked." % (target_name or ""))

    target_id = str(target.get("id") or "")
    refused = agent_handoff.refusal(caller_id, target_id)
    if refused:
        return refused

    name = str(target.get("name") or target_id)
    # Counted BEFORE the turn, not after: a colleague that fails still cost
    # the turn it took, and not counting it would let a failing agent be
    # asked for ever.
    agent_handoff.spend()
    try:
        async with agent_handoff.entered(target_id):
            answer = await _run_colleague_turn(
                user_email, target_id, asked,
                parent_run_id=agent_handoff.parent_run())
    except Exception:                                       # noqa: BLE001
        logger.exception("a colleague's turn failed")
        return ("%s could not answer just now, so carry on with what you "
                "have." % name)
    answer = (answer or "").strip()
    if not answer:
        return "%s had nothing to add." % name
    return "%s says: %s" % (name, answer)
```

In `execute_tool_call`, immediately after `name = name.strip()` and before the native-source lookup:

```python
    if name == HANDOFF_TOOL:
        # Scoped like every other native tool: interception must not become
        # a back door around the grant. An agent that was never given this
        # tool cannot use it just because this branch runs first.
        if allowed_native_tools is not None and \
                HANDOFF_TOOL not in allowed_native_tools:
            return ("This agent has not been given the tool to ask a "
                    "colleague, so nothing was asked.")
        args = arguments_of(tool_call) or {}
        return await run_handoff(
            agent_id or "", user_email,
            str(args.get("agent") or ""), str(args.get("question") or ""))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_ask_colleague.py tests/test_agent_tools.py -q`
Expected: PASS, including the existing `agent_tools` tests.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_tools.py mcp-servers/tasks/tests/test_ask_colleague.py
git commit -m "One agent can ask another, guarded in trusted code"
```

---

### Task 6: `_run_turn` accepts a surface and a parent

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py:281-344`
- Test: `mcp-servers/tasks/tests/test_run_turn_surface.py`

**Interfaces:**
- Consumes: `agent_access.SURFACE_COLLEAGUE`, `agent_activity.SOURCE_COLLEAGUE`, `agent_activity.start_run(..., parent_run_id=...)`.
- Produces: `_run_turn(user_email, agent_id, messages, brief=False, surface=agent_access.SURFACE_CHANNEL, parent_run_id=None) -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_run_turn_surface.py`:

```python
"""A turn knows which surface it is running on.

A handoff is a turn like any other, except that its permissions are
narrower, its run points at the run that asked for it, and the office can
tell it apart from a run the person started.
"""
import agent_access
import agent_activity
import routes_agent_turn as rt


def _stub(monkeypatch, seen):
    async def resolve(user_email, agent_id):
        return ("tok", [], agent_access.LEVEL_ALL,
                {"id": agent_id, "name": "Iris"}, [])

    async def chat(**kw):
        seen["mode"] = kw.get("tool_mode")
        return ("answered", [])

    async def start_run(agent_id, user_email, source, parent_run_id=None):
        seen["source"] = source
        seen["parent"] = parent_run_id
        return "run-1"

    async def finish_run(run_id, status, usage=None):
        return None

    async def brief_for(user_email, agent, roster, messages):
        return {"role": "system", "content": "brief"}

    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt, "_brief_for", brief_for)
    monkeypatch.setattr(rt.agent_activity, "start_run", start_run)
    monkeypatch.setattr(rt.agent_activity, "finish_run", finish_run)
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection",
                        lambda *a, **k: None)


async def test_a_channel_turn_is_unchanged(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}])
    assert seen["source"] == agent_activity.SOURCE_CHANNEL
    assert seen["parent"] is None


async def test_a_colleague_turn_says_so(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE,
                       parent_run_id="run-0")
    assert seen["source"] == agent_activity.SOURCE_COLLEAGUE
    assert seen["parent"] == "run-0"


async def test_a_colleague_turn_uses_the_colleague_permissions(monkeypatch):
    """LEVEL_ALL is what the stub returns, so a colleague turn may act. The
    point of this test is that the SURFACE reaches effective_mode at all."""
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE)
    assert seen["mode"] == agent_access.MODE_FULL
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_run_turn_surface.py -q`
Expected: FAIL with `TypeError: _run_turn() got an unexpected keyword argument 'surface'`

- [ ] **Step 3: Write the implementation**

Change the signature at `routes_agent_turn.py:281`:

```python
async def _run_turn(user_email: str, agent_id: str, messages: list[dict],
                    brief: bool = False,
                    surface: str = agent_access.SURFACE_CHANNEL,
                    parent_run_id: str | None = None) -> dict:
```

Add to its docstring:

```
    `surface` is where this turn is running, which decides what its tools
    may do. A handoff passes SURFACE_COLLEAGUE, which narrows `ask` to read
    only: the owner is in a conversation with the agent that ASKED, so a
    prompt raised here would ask them about a conversation they are not in.

    `parent_run_id` is the run that asked for this one, so the office can
    say who is helping whom as a fact rather than an animation.
```

Replace the three uses of `SURFACE_CHANNEL` in the body with `surface`:

```python
    mode = agent_access.effective_mode(level, None, surface)

    run_id = await agent_activity.start_run(
        agent_id, user_email,
        (agent_activity.SOURCE_COLLEAGUE
         if surface == agent_access.SURFACE_COLLEAGUE
         else agent_activity.SOURCE_CHANNEL),
        parent_run_id=parent_run_id)
```

and in the `_chat(...)` call:

```python
            refusal_reason=agent_access.refusal_reason(level, None, surface),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_run_turn_surface.py tests/test_agent_turn.py -q`
Expected: PASS, including the existing turn tests, because both new parameters default to today's behaviour.

- [ ] **Step 5: Open the handoff budget, and shorten a colleague's turn**

Still in `_run_turn`, wrap the body so the outermost turn opens the budget the handoffs spend, and so a colleague's turn does not wait as long as a top-level one. Add near the other constants in `routes_agent_turn.py`:

```python
#: A colleague's turn is shorter than a top-level one because somebody is
#: waiting mid-sentence for it, and agents run one at a time on this box.
COLLEAGUE_HTTP_TIMEOUT_SECONDS = max(30, CHANNEL_HTTP_TIMEOUT_SECONDS // 2)
COLLEAGUE_MAX_TOOL_ITERATIONS = max(1, CHANNEL_MAX_TOOL_ITERATIONS // 2)
```

and in the `_chat(...)` call use them for the colleague surface:

```python
            max_iterations=(COLLEAGUE_MAX_TOOL_ITERATIONS
                            if surface == agent_access.SURFACE_COLLEAGUE
                            else CHANNEL_MAX_TOOL_ITERATIONS),
            timeout=(COLLEAGUE_HTTP_TIMEOUT_SECONDS
                     if surface == agent_access.SURFACE_COLLEAGUE
                     else CHANNEL_HTTP_TIMEOUT_SECONDS),
```

and wrap the whole `try:` body in the budget:

```python
    async with agent_handoff.began(run_id):
        try:
            ...
```

Add `import agent_handoff` at the top of `routes_agent_turn.py`.

Add this test to `tests/test_run_turn_surface.py`:

```python
async def test_a_colleague_turn_does_not_wait_as_long(monkeypatch):
    """Somebody is waiting mid-sentence for it, and agents run one at a
    time on a 3.8GB box."""
    seen = {}

    async def chat(**kw):
        seen["timeout"] = kw.get("timeout")
        seen["iterations"] = kw.get("max_iterations")
        return ("answered", [])

    _stub(monkeypatch, seen)
    monkeypatch.setattr(rt, "_chat", chat)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE)
    assert seen["timeout"] < rt.CHANNEL_HTTP_TIMEOUT_SECONDS
    assert seen["iterations"] < rt.CHANNEL_MAX_TOOL_ITERATIONS


async def test_the_outermost_turn_opens_the_handoff_budget(monkeypatch):
    seen = {}
    opened = []

    async def chat(**kw):
        opened.append(agent_handoff.parent_run())
        return ("answered", [])

    _stub(monkeypatch, seen)
    monkeypatch.setattr(rt, "_chat", chat)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}])
    assert opened == ["run-1"]
```

with `import agent_handoff` at the top of that test file.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_run_turn_surface.py tests/test_agent_turn.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_run_turn_surface.py
git commit -m "A turn knows which surface it is running on"
```

---

### Task 7: Record every tool call in the loop

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (the tool loop, around lines 838-889)
- Test: `mcp-servers/tasks/tests/test_tool_step_recording.py`

**Interfaces:**
- Consumes: `agent_activity.start_step`, `agent_activity.finish_step`, `HANDOFF_TOOL` imported by name from `agent_tools`.
- Produces: nothing new; the loop now writes a step per call.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_tool_step_recording.py`:

```python
"""Every tool call leaves a row, and a failed row never costs a turn."""
import agent_runner


def _started(monkeypatch):
    calls = []

    async def start_step(run_id, agent_id, user_email, tool,
                         target_agent_id=None):
        calls.append({"run": run_id, "agent": agent_id, "tool": tool,
                      "target": target_agent_id})
        return "step-%d" % len(calls)

    async def finish_step(step_id, status):
        calls.append({"finished": step_id, "status": status})

    monkeypatch.setattr(agent_runner.agent_activity, "start_step", start_step)
    monkeypatch.setattr(agent_runner.agent_activity, "finish_step", finish_step)
    return calls


async def test_a_tool_call_is_recorded(monkeypatch):
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}},
        "ok")
    assert calls[0]["tool"] == "search_drive"
    assert calls[0]["target"] is None
    assert calls[1]["status"] == "ok"


async def test_a_handoff_records_who_was_asked(monkeypatch):
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "ask_colleague",
                      "arguments": '{"agent": "Iris", "question": "hi"}'}},
        "ok")
    assert calls[0]["tool"] == "ask_colleague"
    assert calls[0]["target"] == "Iris"


async def test_a_refused_call_is_still_recorded(monkeypatch):
    """Review Focus 5. A refusal is a fact worth having, and a row left
    saying running for ever would read as a tool that hung."""
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "send_email", "arguments": "{}"}},
        "refused")
    assert calls[1]["status"] == "refused"


async def test_recording_that_fails_does_not_raise(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("the database is not there")

    monkeypatch.setattr(agent_runner.agent_activity, "start_step", boom)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com",
        {"function": {"name": "search_drive", "arguments": "{}"}}, "ok")


async def test_a_call_with_no_name_records_nothing(monkeypatch):
    calls = _started(monkeypatch)
    await agent_runner._record_step(
        "run-1", "agent-nora", "me@example.com", {"function": {}}, "ok")
    assert calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_tool_step_recording.py -q`
Expected: FAIL with `AttributeError: module 'agent_runner' has no attribute '_record_step'`

- [ ] **Step 3: Write the helper**

`agent_runner.py` imports names FROM `agent_tools` (`from agent_tools import (arguments_of, execute_tool_call, ...)`), not the module, so `agent_tools.HANDOFF_TOOL` would raise `NameError`. Add `HANDOFF_TOOL` to that existing import list:

```python
from agent_tools import (HANDOFF_TOOL, arguments_of, execute_tool_call,
```

Then, above the tool loop:

```python
async def _record_step(run_id, agent_id, user_email, call, status) -> None:
    """Write one tool call down, and never let that cost a turn.

    Open and closed in one go rather than around the call itself: the
    interesting facts are which tool, on whose behalf, and how it ended, and
    a step that opens before a tool runs would need a second write on every
    path out of a loop that has several.

    A handoff carries who was asked, which is what turns this one table into
    the record of both what an agent is doing and who it is working with.
    """
    try:
        fn = (call or {}).get("function")
        fn = fn if isinstance(fn, dict) else {}
        name = fn.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            return
        target = None
        if name == HANDOFF_TOOL:
            args = arguments_of(call) or {}
            target = str(args.get("agent") or "") or None
        step_id = await agent_activity.start_step(
            run_id, agent_id, user_email, name, target)
        await agent_activity.finish_step(step_id, status)
    except Exception:                                       # noqa: BLE001
        logger.warning("could not record a tool call", exc_info=True)
```

In the tool loop, after `result` is decided and before the `convo.append` of the tool message, add:

```python
                await _record_step(
                    usage.run_id if usage else None, model, user_email,
                    call, _step_status(result))
```

and beside `_record_step`:

```python
def _step_status(result) -> str:
    """How a call ended, read off the result the model will see.

    The loop has only the string it is about to hand back, so that is what
    decides this: a refusal already says so in words, because the owner has
    to be able to read it too.
    """
    text = result if isinstance(result, str) else ""
    if text.startswith("Refused:"):
        return "refused"
    return "ok"
```

For the held case, inside the `pending.append(call)` branch, add:

```python
                    await _record_step(
                        usage.run_id if usage else None, model, user_email,
                        call, "held")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_tool_step_recording.py tests/test_agent_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_tool_step_recording.py
git commit -m "Every tool call leaves a row"
```

---

### Task 8: The Open WebUI tool row

**Files:**
- Create: `open-webui-functions/colleague_tool.py`
- Create: `scripts/install_colleague_tool.py`

**Interfaces:**
- Consumes: `agent_tools.HANDOFF_TOOL` (the name must match exactly).
- Produces: a `public.tool` row with id `colleague`, whose spec makes `ask_colleague` visible to models.

- [ ] **Step 1: Write the tool source**

Create `open-webui-functions/colleague_tool.py`:

```python
"""Ask a colleague.

This body is never executed. The tasks service intercepts `ask_colleague`
by name inside execute_tool_call and runs the handoff itself, because this
row is editable from the web UI and a depth cap somebody can edit away is
not a depth cap.

The row exists because a tool without a generated spec is invisible to every
model. What matters here is the signature and the docstring: that is what
becomes the spec the model reads.
"""


class Tools:
    def __init__(self):
        pass

    async def ask_colleague(self, agent: str, question: str) -> str:
        """
        Ask one of your colleagues something you cannot answer yourself.

        Use this when the job in front of you needs something that is
        plainly somebody else's: a file you cannot see, a calendar you do
        not keep, an app you did not build. Ask them for that one thing,
        then carry on and finish your own answer with what they say.

        Do not use it to pass the whole question on, and do not use it to
        chat. If you can answer, answer.

        :param agent: The colleague's name, exactly as it appears in your
            roster, for example "Iris".
        :param question: The one thing you need from them, in a sentence.
        """
        return ("This tool is handled by the platform and was not run here.")
```

- [ ] **Step 2: Write the installer**

Create `scripts/install_colleague_tool.py`, following the shape of the existing installers in `scripts/`:

```python
"""Install the ask_colleague tool row in Open WebUI.

Run on the server:
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py         # show
  OPENWEBUI_API_KEY=... python3 scripts/install_colleague_tool.py --apply # write

A tool needs BOTH a public.tool row AND generated `specs`, or it is invisible
to every model. Open WebUI generates the specs from the source when the row
is created through its own endpoint, which is why this posts rather than
writing the table directly.
"""
import os
import pathlib
import sys

import requests

BASE = os.environ.get("OPENWEBUI_URL", "http://localhost:3000")
KEY = os.environ.get("OPENWEBUI_API_KEY", "")
if not KEY:
    sys.exit("OPENWEBUI_API_KEY is required")

TOOL_ID = "colleague"
SOURCE = (pathlib.Path(__file__).resolve().parents[1]
          / "open-webui-functions" / "colleague_tool.py").read_text()

body = {
    "id": TOOL_ID,
    "name": "Colleague",
    "content": SOURCE,
    "meta": {"description": "Ask one of your colleagues something you "
                            "cannot answer yourself."},
}

head = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
existing = requests.get("%s/api/v1/tools/id/%s" % (BASE, TOOL_ID),
                        headers=head, timeout=30)
print("exists:", existing.status_code == 200)

if "--apply" not in sys.argv:
    print("dry run; pass --apply to write")
    sys.exit(0)

url = ("%s/api/v1/tools/id/%s/update" % (BASE, TOOL_ID)
       if existing.status_code == 200
       else "%s/api/v1/tools/create" % BASE)
r = requests.post(url, headers=head, json=body, timeout=30)
print("wrote:", r.status_code)
r.raise_for_status()

check = requests.get("%s/api/v1/tools/id/%s" % (BASE, TOOL_ID),
                     headers=head, timeout=30).json()
specs = (check.get("specs") or [])
names = [s.get("name") for s in specs]
print("specs:", names)
if "ask_colleague" not in names:
    sys.exit("the row was written but no ask_colleague spec was generated, "
             "so no model can see it")
print("ok")
```

- [ ] **Step 3: Check both parse**

Run: `cd "C:/All/Work - Code/ai_ui" && python -m py_compile open-webui-functions/colleague_tool.py scripts/install_colleague_tool.py && echo ok`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add open-webui-functions/colleague_tool.py scripts/install_colleague_tool.py
git commit -m "The tool row that makes ask_colleague visible to a model"
```

---

### Task 9: Verify on the server

**Files:** none changed. This task is evidence.

CLAUDE.md is explicit: `python -c "import routes_execution"` will not catch a `NameError` inside a function body, and wiring has to be proved by a real run.

- [ ] **Step 1: Deploy**

Hash-sweep every changed file against the previous commit in the same command as the deploy, then copy, strip CRLF, and rebuild:

```bash
cd "C:/All/Work - Code/ai_ui"
for f in mcp-servers/tasks/agent_access.py mcp-servers/tasks/agent_handoff.py \
         mcp-servers/tasks/agent_activity.py mcp-servers/tasks/agent_tools.py \
         mcp-servers/tasks/agent_runner.py mcp-servers/tasks/routes_agent_turn.py \
         mcp-servers/tasks/migrations/052_agent_step.sql; do
  S=$(ssh root@46.224.193.25 "md5sum /root/proxy-server/$f 2>/dev/null | cut -d' ' -f1")
  P=$(git show HEAD~1:$f 2>/dev/null | tr -d '\r' | md5sum | cut -d' ' -f1)
  echo "$f $([ "$S" = "$P" ] && echo SWEEP-OK || echo DRIFT)"
done
```

Any `DRIFT` means somebody edited that file on the box. Stop and reconcile before deploying.

- [ ] **Step 2: Confirm the migration applied**

```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \"SELECT count(*) FROM information_schema.tables WHERE table_schema='tasks' AND table_name='agent_step';\""
```
Expected: `1`

- [ ] **Step 3: Install the tool row and grant it**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && export OPENWEBUI_API_KEY=\$(grep -m1 '^OPENWEBUI_API_KEY=' .env | cut -d= -f2-) && python3 scripts/install_colleague_tool.py --apply"
```
Expected: `specs: ['ask_colleague']` then `ok`.

Then add `colleague` to one agent's `meta.toolIds` so it can actually reach it.

- [ ] **Step 4: Prove one real handoff**

Ask the granted agent something that is plainly another agent's job, through the agents chat panel, and then read the rows back:

```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \"SELECT s.agent_id, s.tool, s.target_agent_id, s.status FROM tasks.agent_step s ORDER BY s.started_at DESC LIMIT 5;\""
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -tAc \"SELECT id, agent_id, source, parent_run_id FROM tasks.agent_run WHERE source='colleague' ORDER BY started_at DESC LIMIT 3;\""
```

Expected: a step row naming `ask_colleague` with a `target_agent_id`, and a run row with `source = colleague` and a non-null `parent_run_id`.

**Do not mark this plan complete without those two rows.** A handoff that cannot be seen in the database did not happen.

- [ ] **Step 5: Stamp and record**

```bash
cd "C:/All/Work - Code/ai_ui" && FULL=$(git rev-parse HEAD)
ssh root@46.224.193.25 "printf '{\"sha\": \"$FULL\", \"deployed_at\": \"%s\", \"deployed_by\": \"manual@dev\"}' \"\$(date -u +%Y-%m-%dT%H:%M:%S+00:00)\" > /root/proxy-server/.deploy-state"
```
