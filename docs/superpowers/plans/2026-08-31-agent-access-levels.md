# Agent Access Levels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every agent a three-level access setting (read / ask / all) and let agents actually run their tools in channels, obeying it.

**Architecture:** The tool loop already exists in `mcp-servers/tasks/agent_runner.py::_chat` and stays there; a new internal endpoint in the tasks service exposes it, and `webhook-handler` calls that endpoint instead of talking to Open WebUI directly when a message is for an agent. A new `agent_access` module owns the one decision that matters (what may this agent do, here, right now) so that decision lives in exactly one function. The "ask first" level ends the turn early and resumes on the next inbound message, using the state store the gateway already uses for agent pins.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, httpx, pytest (`asyncio_mode = auto`), vanilla JS in `static/agents.html`, Docker Compose on Hetzner.

**Spec:** `docs/superpowers/specs/2026-08-31-agent-access-levels-design.md`

## Global Constraints

- **Commit messages carry no AI attribution.** No `Co-Authored-By`, no "Generated with". Author is Ralph Benitez only. This is non-negotiable per the user's global rule.
- **No em-dashes or en-dashes in any user-visible copy** (refusal sentences, prompts, hints, labels). Use a period, comma, or "and"/"so".
- **Nothing on the gateway path may fail silently.** `pipeline.py`'s module docstring is explicit: somebody is staring at a chat window, so every exit delivers a sentence a person can read.
- **Bookkeeping must never fail a run.** `agent_activity` swallows its own errors; keep it that way.
- **Never log or store a minted Open WebUI token.** This project has already leaked a bot token through an HTTP client logging a request URL.
- **Unknown tools count as writes.** `is_write_tool` returns True by default and that failure direction is deliberate. Do not "fix" it.
- **Expect ~130 local test errors** at setup from `db_session` (no local Postgres). That is pre-existing. Confirm failures say `ERROR at setup`.
- Repo checks out CRLF on Windows. Preserve each file's existing line endings when editing.

---

### Task 1: The access decision, in one place

**Files:**
- Create: `mcp-servers/tasks/agent_access.py`
- Test: `mcp-servers/tasks/tests/test_agent_access.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LEVEL_READ`, `LEVEL_ASK`, `LEVEL_ALL`, `LEVELS`, `MODE_READ_ONLY`, `MODE_ASK`, `MODE_FULL`, `SURFACE_CHANNEL`, `SURFACE_SCHEDULE`, `level_of(meta: dict | None) -> str | None`, `effective_mode(level: str | None, tool_mode: str | None, surface: str) -> str`, `refusal_reason(level: str | None, tool_mode: str | None, surface: str) -> str`, `ApprovalRequired(conversation: list[dict], calls: list[dict])`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_access.py`:

```python
"""What may this agent do, here, right now.

The whole point of this module is that there is ONE answer to that, in one
function. This codebase has twice had access logic living in two places where
fixing one left the other open, so the table below is exhaustive on purpose.
"""
import pytest

import agent_access as aa


# --- reading the level off the agent row ----------------------------------

@pytest.mark.parametrize("meta,expected", [
    ({"access": "read"}, "read"),
    ({"access": "ask"}, "ask"),
    ({"access": "all"}, "all"),
    ({"access": "ALL"}, "all"),
    ({"access": "  ask  "}, "ask"),
])
def test_a_level_is_read_off_the_agent_row(meta, expected):
    assert aa.level_of(meta) == expected


@pytest.mark.parametrize("meta", [
    None, {}, {"access": None}, {"access": 3}, {"access": ""},
    {"access": "banana"}, {"access": ["all"]}, "not a dict",
])
def test_anything_unrecognised_is_no_opinion_not_a_default(meta):
    """Absent means "behave exactly as today". Reading a junk value as a
    level would hand an agent a permission nobody chose."""
    assert aa.level_of(meta) is None


# --- the ceiling ----------------------------------------------------------

@pytest.mark.parametrize("level,tool_mode,expected", [
    # The agent's level is a ceiling. A schedule may narrow it, never widen it.
    ("read", "full", aa.MODE_READ_ONLY),
    ("all", "read_only", aa.MODE_READ_ONLY),
    ("all", "full", aa.MODE_FULL),
    ("ask", "full", aa.MODE_READ_ONLY),
    ("ask", "read_only", aa.MODE_READ_ONLY),
    ("read", "read_only", aa.MODE_READ_ONLY),
    # No opinion reproduces today's behaviour exactly.
    (None, "full", aa.MODE_FULL),
    (None, "read_only", aa.MODE_READ_ONLY),
    (None, None, aa.MODE_READ_ONLY),
])
def test_the_schedule_ceiling(level, tool_mode, expected):
    assert aa.effective_mode(level, tool_mode, aa.SURFACE_SCHEDULE) == expected


@pytest.mark.parametrize("level,expected", [
    ("read", aa.MODE_READ_ONLY),
    ("ask", aa.MODE_ASK),
    ("all", aa.MODE_FULL),
    # Today a channel refuses every tool, so read-only cannot regress anything.
    (None, aa.MODE_READ_ONLY),
])
def test_a_channel_follows_the_agent_alone(level, expected):
    assert aa.effective_mode(level, None, aa.SURFACE_CHANNEL) == expected


def test_a_schedule_never_asks():
    """A schedule fires whether or not anybody is online. Asking would hang
    the run at 3am waiting for an answer nobody is there to give."""
    assert aa.effective_mode("ask", "full", aa.SURFACE_SCHEDULE) != aa.MODE_ASK


def test_a_channel_tool_mode_is_ignored_entirely():
    """There is no schedule behind a Discord message, so nothing may sneak a
    tool_mode in and widen a read-only agent."""
    assert aa.effective_mode("read", "full", aa.SURFACE_CHANNEL) == aa.MODE_READ_ONLY


# --- what the person is told ----------------------------------------------

def test_a_schedule_keeps_the_sentence_it_has_today():
    assert (aa.refusal_reason(None, "read_only", aa.SURFACE_SCHEDULE)
            == "this schedule is set to read only")


def test_an_asking_agent_on_a_schedule_says_why_it_could_not_ask():
    reason = aa.refusal_reason("ask", "full", aa.SURFACE_SCHEDULE)
    assert reason == "a scheduled run has nobody to ask"


def test_a_channel_never_talks_about_schedules():
    """The sentence "this schedule is set to read only" is simply false in a
    Discord DM, and it is what the loop says today."""
    reason = aa.refusal_reason("read", None, aa.SURFACE_CHANNEL)
    assert "schedule" not in reason
    assert reason == "this agent is set to read only"


@pytest.mark.parametrize("surface", [aa.SURFACE_CHANNEL, aa.SURFACE_SCHEDULE])
@pytest.mark.parametrize("level", [None, "read", "ask", "all"])
def test_every_reason_reads_as_a_clause(surface, level):
    """These get interpolated into two sentences, so a trailing full stop or
    a leading capital would produce garbage in one of them."""
    reason = aa.refusal_reason(level, "full", surface)
    assert reason and not reason.endswith(".") and reason[0].islower()
    assert "\u2014" not in reason and "\u2013" not in reason


# --- the approval signal --------------------------------------------------

def test_approval_required_carries_what_is_needed_to_resume():
    convo = [{"role": "user", "content": "send it"}]
    calls = [{"id": "call_1", "function": {"name": "send_email"}}]
    err = aa.ApprovalRequired(convo, calls)
    assert err.conversation == convo
    assert err.calls == calls
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_access.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_access'`

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/agent_access.py`:

```python
"""What an agent may do, here, right now.

There is one answer to that and it lives in this file. The alternative is
what this codebase has done twice before: the same decision written in two
functions, where fixing one leaves the other open.

An agent's level is a CEILING. A schedule may narrow it and may never widen
it. Two controls that can each widen the other is how permission systems get
holes.

An absent level is not a default. It means the agent predates this feature
and has no opinion, so each caller falls back to what it did before, and
nothing that works today starts behaving differently.

None of this protects one user from another. The owner writes their own
agent row, so they can set their own agent to `all` whenever they like, and
that is intended: it is their agent acting on their own connected accounts.
Per-user scoping is done by X-User-Email and the per-user minted token, and
none of it changes here. What this protects against is an agent doing
something its owner did not intend, including at the prompting of text the
agent read somewhere else.
"""

#: What the owner picked, stored as meta.access on the agent's model row.
LEVEL_READ = "read"
LEVEL_ASK = "ask"
LEVEL_ALL = "all"
LEVELS = frozenset({LEVEL_READ, LEVEL_ASK, LEVEL_ALL})

#: What the tool loop is told. read_only and full are the values the
#: per-schedule tool_mode column has always used; ask is new.
MODE_READ_ONLY = "read_only"
MODE_ASK = "ask"
MODE_FULL = "full"

#: Where the agent is running. A channel has somebody watching who can be
#: asked; a schedule does not.
SURFACE_CHANNEL = "channel"
SURFACE_SCHEDULE = "schedule"


class ApprovalRequired(Exception):
    """The agent wants to do something it must ask about first.

    Raised out of the middle of the tool loop, carrying enough to pick the
    turn back up once an answer arrives. An exception rather than a third
    return value on purpose: this is an exceptional exit from a loop whose
    ordinary contract is "run until the model answers", and every existing
    caller of that loop unpacks two values.
    """

    def __init__(self, conversation: list[dict], calls: list[dict]):
        self.conversation = conversation
        self.calls = calls
        super().__init__("the agent needs approval before it can continue")


def level_of(meta) -> str | None:
    """The agent's own access level, or None when it has no opinion.

    Anything unrecognised reads as None rather than as a default. A junk
    value is not evidence of a choice, and treating it as one would hand an
    agent a permission nobody picked.
    """
    if not isinstance(meta, dict):
        return None
    value = meta.get("access")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in LEVELS else None


def effective_mode(level: str | None, tool_mode: str | None,
                   surface: str) -> str:
    """What the tool loop is allowed to do for this run."""
    if surface == SURFACE_CHANNEL:
        # No schedule behind a channel message, so tool_mode is ignored
        # entirely rather than defaulted. Reading it here would give a caller
        # a way to widen a read-only agent.
        if level == LEVEL_ALL:
            return MODE_FULL
        if level == LEVEL_ASK:
            return MODE_ASK
        # LEVEL_READ, and None. Channels refuse every tool today, so
        # read-only for an agent with no opinion cannot regress anything.
        return MODE_READ_ONLY

    schedule_full = (tool_mode or MODE_READ_ONLY) == MODE_FULL
    if level is None:
        # Exactly today's behaviour, so an existing schedule set to full
        # keeps working.
        return MODE_FULL if schedule_full else MODE_READ_ONLY
    if level == LEVEL_ALL and schedule_full:
        return MODE_FULL
    # Everything else narrows, including ask: see the module docstring.
    return MODE_READ_ONLY


def refusal_reason(level: str | None, tool_mode: str | None,
                   surface: str) -> str:
    """Why a write was not run, as a lower-case clause with no full stop.

    It is interpolated into two different sentences, so it has to read as a
    fragment in both. Kept beside effective_mode so the two cannot drift:
    a refusal that explains the wrong rule is worse than no explanation.
    """
    if surface == SURFACE_CHANNEL:
        return "this agent is set to read only"
    if level == LEVEL_ASK:
        return "a scheduled run has nobody to ask"
    if level == LEVEL_READ:
        return "this agent is set to read only"
    return "this schedule is set to read only"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_access.py -q`
Expected: PASS, 30+ tests

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_access.py mcp-servers/tasks/tests/test_agent_access.py
git commit -m "feat(agents): one place that decides what an agent may do"
```

---

### Task 2: Teach the tool loop the three modes

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py` (imports, new constants, `_post_chat`, `_chat`)
- Modify: `mcp-servers/tasks/tests/test_agent_tool_loop.py` (fakes gain a third parameter)
- Test: `mcp-servers/tasks/tests/test_agent_tool_loop.py` (new cases)

**Interfaces:**
- Consumes: `agent_access.MODE_ASK`, `agent_access.MODE_FULL`, `agent_access.ApprovalRequired`.
- Produces: `_chat(token, model, messages, tool_ids, user_email, tool_mode, refusal_reason=..., max_iterations=MAX_TOOL_ITERATIONS, timeout=HTTP_TIMEOUT_SECONDS) -> tuple[str, list[str]]`, raising `ApprovalRequired`. Also `CHANNEL_MAX_TOOL_ITERATIONS = 3` and `CHANNEL_HTTP_TIMEOUT_SECONDS = 60`. `_post_chat(payload, token, timeout)`.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_agent_tool_loop.py`:

```python
# --- the three access modes ------------------------------------------------

async def test_a_write_under_ask_stops_and_asks_instead_of_running():
    """The whole point of "With access". Running it and then mentioning it
    would be the bug, not the feature."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("send_email")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="sent")) as ex:
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "send it"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    ex.assert_not_awaited(), "the write ran anyway"
    assert caught.value.calls[0]["function"]["name"] == "send_email"


async def test_reads_in_the_same_batch_still_run_before_it_asks():
    """Otherwise a turn that looks something up and then acts on it would
    throw away the lookup and have to redo it after approval."""
    import agent_access

    async def fake_post(payload, token, timeout=None):
        return _reply(calls=[_tool_call("list_unread_emails", "c1"),
                             _tool_call("send_email", "c2")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")) as ex:
        with pytest.raises(agent_access.ApprovalRequired) as caught:
            await agent_runner._chat(
                token="t", model="agent-1",
                messages=[{"role": "user", "content": "q"}],
                tool_ids=["gmail"], user_email="owner@example.com",
                tool_mode=agent_access.MODE_ASK)

    assert ex.await_count == 1, "the read should have run, the write should not"
    assert [c["id"] for c in caught.value.calls] == ["c2"]
    # The conversation handed back has to carry the read's result, or the
    # resumed turn loses it.
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
               for m in caught.value.conversation)


async def test_a_write_under_all_access_just_runs():
    import agent_access
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="Sent.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="ok")) as ex:
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "send it"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode=agent_access.MODE_FULL)

    ex.assert_awaited_once()
    assert answer == "Sent."
    assert notes == []


async def test_the_refusal_says_why_in_the_callers_words():
    """The loop used to say "this schedule is set to read only" everywhere,
    which is simply false in a Discord DM."""
    import agent_access
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        if len(posts) == 1:
            return _reply(calls=[_tool_call("send_email")])
        return _reply(content="I could not send that.")

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call", new=AsyncMock()):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "send it"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode=agent_access.MODE_READ_ONLY,
            refusal_reason="this agent is set to read only")

    assert "this agent is set to read only" in notes[0]
    assert "schedule" not in notes[0]
    fed_back = posts[1]["messages"][-1]["content"]
    assert "this agent is set to read only" in fed_back


async def test_a_channel_can_be_given_a_shorter_leash():
    """A person waiting in Discord will not sit through the schedule path's
    five rounds of tool use."""
    posts = []

    async def fake_post(payload, token, timeout=None):
        posts.append(payload)
        return _reply(calls=[_tool_call("list_unread_emails")])

    with patch.object(agent_runner, "_post_chat", new=fake_post), \
         patch("agent_runner.execute_tool_call",
               new=AsyncMock(return_value="4 unread")):
        answer, notes = await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=["gmail"], user_email="owner@example.com",
            tool_mode="read_only",
            max_iterations=agent_runner.CHANNEL_MAX_TOOL_ITERATIONS)

    assert len(posts) == agent_runner.CHANNEL_MAX_TOOL_ITERATIONS
    assert "3 rounds" in notes[-1], "the note must report the real cap"


async def test_the_per_call_timeout_reaches_the_request():
    seen = {}

    async def fake_post(payload, token, timeout=None):
        seen["timeout"] = timeout
        return _reply(content="done")

    with patch.object(agent_runner, "_post_chat", new=fake_post):
        await agent_runner._chat(
            token="t", model="agent-1",
            messages=[{"role": "user", "content": "q"}],
            tool_ids=None, user_email="owner@example.com",
            tool_mode="read_only",
            timeout=agent_runner.CHANNEL_HTTP_TIMEOUT_SECONDS)

    assert seen["timeout"] == agent_runner.CHANNEL_HTTP_TIMEOUT_SECONDS
```

- [ ] **Step 2: Update the existing fakes in the same file**

Every existing `async def fake_post(payload, token):` in
`tests/test_agent_tool_loop.py` becomes
`async def fake_post(payload, token, timeout=None):`. `_chat` now passes the
timeout positionally, so a two-parameter fake raises `TypeError`.

Run: `cd mcp-servers/tasks && grep -c "async def fake_post(payload, token)" tests/test_agent_tool_loop.py`
Expected: 0 after the edit.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_tool_loop.py -q`
Expected: FAIL. The new cases fail on the unknown `refusal_reason` /
`max_iterations` / `timeout` keyword arguments and on `ApprovalRequired`
never being raised.

- [ ] **Step 4: Implement**

In `mcp-servers/tasks/agent_runner.py`, add to the imports beside the others:

```python
import agent_access
```

Add beneath `MAX_TOOL_ITERATIONS`:

```python
#: A channel is somebody waiting at a keyboard, not a cron entry. The
#: schedule path's five rounds at 240 seconds each is a 20 minute worst
#: case, which is fine at 3am and absurd in a Discord window. These bring it
#: to about 3 minutes.
CHANNEL_MAX_TOOL_ITERATIONS = 3
CHANNEL_HTTP_TIMEOUT_SECONDS = 60
```

Change `_post_chat` to take the timeout:

```python
async def _post_chat(payload: dict, token: str,
                     timeout: float = HTTP_TIMEOUT_SECONDS) -> dict:
    """One completion. Split out so the loop above it can be tested without
    a model, and so there is one place that knows the wire format."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{_base_url()}/api/chat/completions",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload)
        r.raise_for_status()
        return r.json()
```

Replace the `_chat` signature and body down to the end of the function:

```python
async def _chat(token: str, model: str, messages: list[dict],
                tool_ids: list[str] | None, user_email: str,
                tool_mode: str | None,
                refusal_reason: str = "this schedule is set to read only",
                max_iterations: int = MAX_TOOL_ITERATIONS,
                timeout: float = HTTP_TIMEOUT_SECONDS) -> tuple[str, list[str]]:
    """Talk to the agent, running any tools it asks for, until it answers.

    Open WebUI injects the tool specs and returns the model's tool_calls, but
    it never runs them for an API caller: its execution loop lives on the
    socket path used by its own UI. So the execution and the feeding back
    happen here. Verified on production that handing a tool result back
    returns finish_reason "stop" and a real answer.

    Returns the answer and any notes about what was refused, which the caller
    shows the owner. A refusal is not an error: the run completes and says
    what it would not do.

    Raises ApprovalRequired when tool_mode is "ask" and the model asked for a
    write. Reads in the same batch have already run by then and their results
    are in the carried conversation, so resuming does not redo them.

    refusal_reason is the caller's words for why a write was blocked. It is
    a parameter rather than a constant because this loop serves both a
    schedule and a chat window, and "this schedule is set to read only" is
    false in a Discord DM.
    """
    convo = list(messages)
    notes: list[str] = []
    mode = tool_mode or agent_access.MODE_READ_ONLY
    write_allowed = mode == agent_access.MODE_FULL
    # Set before the loop so a tuned-down max_iterations of 0 still has
    # something defined to return, instead of an UnboundLocalError.
    content = ""

    for _ in range(max_iterations):
        payload: dict = {"model": model, "messages": convo, "stream": False}
        if tool_ids:
            payload["tool_ids"] = tool_ids
        data = await _post_chat(payload, token, timeout)

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
        pending: list[dict] = []
        for call in calls:
            # A tool call comes straight from a model, so its shape cannot be
            # trusted: `call` itself, its "function" object, or "name" inside
            # that can each be something other than what they should be. The
            # same nine shapes are already guarded one layer down in
            # execute_tool_call; guard them here too, before .strip() or
            # .get() can raise and take the whole run down with it. A call
            # that cannot be named degrades to a refused/unnamed call rather
            # than a fatal error.
            call = call if isinstance(call, dict) else {}
            fn = call.get("function")
            fn = fn if isinstance(fn, dict) else {}
            raw_name = fn.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            label = name or "an unnamed tool call"
            if is_write_tool(name) and not write_allowed:
                if mode == agent_access.MODE_ASK:
                    # Held back, not refused. The turn ends below and picks
                    # up again once the owner answers.
                    pending.append(call)
                    continue
                notes.append(
                    "Declined to run " + label + ", because "
                    + refusal_reason + ".")
                result = ("Refused: " + refusal_reason + ", so "
                          + label + " was not run.")
            else:
                # tool_ids scopes which native tools this agent is even
                # allowed to run, not only which ones the model was told
                # about -- see execute_tool_call.
                result = await execute_tool_call(call, user_email, tool_ids)
            if isinstance(result, str) and len(result) > TOOL_RESULT_EXCERPT_CHARS:
                result = (
                    result[:TOOL_RESULT_EXCERPT_CHARS]
                    + "\n\n[This tool result was shortened. It was longer "
                    "than " + str(TOOL_RESULT_EXCERPT_CHARS) + " characters.]")
            convo.append({"role": "tool", "tool_call_id": call.get("id"),
                          "name": name, "content": result})

        if pending:
            # Raised after the whole batch so the reads above are already
            # done and carried. Every held call still needs a tool message
            # before the next completion, which is what the resume writes.
            raise agent_access.ApprovalRequired(convo, pending)

    notes.append("Stopped after " + str(max_iterations)
                 + " rounds of tool use, so this answer may be incomplete.")
    return content, notes
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_tool_loop.py tests/test_agent_runner.py tests/test_agent_access.py -q`
Expected: PASS, no failures.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_tool_loop.py
git commit -m "feat(agents): the tool loop understands read, ask and full"
```

---

### Task 3: Apply the ceiling on the schedule side

**Files:**
- Modify: `mcp-servers/tasks/agent_runner.py::run_agent`
- Test: `mcp-servers/tasks/tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `agent_access.level_of`, `agent_access.effective_mode`, `agent_access.refusal_reason`, `agent_access.ApprovalRequired` from Task 1; `_chat`'s new keyword arguments from Task 2.
- Produces: nothing new. `run_agent(sched) -> tuple[str, str, dict]` is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_agent_runner.py`:

```python
# --- the agent's level is a ceiling over the schedule's tool_mode ----------

def _sched(agent_id="agent-1", tool_mode="full", email="owner@example.com"):
    class S:
        pass
    s = S()
    s.agent_id = agent_id
    s.user_email = email
    s.prompt = "do the thing"
    s.tool_mode = tool_mode
    s.last_result = ""
    s.last_run_status = "completed"
    return s


def _agent_row(access=None):
    meta = {"toolIds": ["gmail"]}
    if access is not None:
        meta["access"] = access
    return {"id": "agent-1", "name": "Scout", "meta": meta}


@pytest.mark.parametrize("access,expected_mode", [
    ("read", "read_only"),   # the agent narrows a full schedule
    ("ask", "read_only"),    # nobody is there to ask at 3am
    ("all", "full"),         # both agree
    (None, "full"),          # no opinion: exactly today's behaviour
])
async def test_the_agent_level_caps_a_full_schedule(access, expected_mode,
                                                    monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row(access)], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    status, _result, _extras = await agent_runner.run_agent(
        _sched(tool_mode="full"))

    assert status == "completed"
    assert seen["tool_mode"] == expected_mode


async def test_a_read_only_schedule_still_caps_an_all_access_agent(monkeypatch):
    """The ceiling runs one way. A schedule may narrow, never widen."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("all")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    await agent_runner.run_agent(_sched(tool_mode="read_only"))
    assert seen["tool_mode"] == "read_only"


async def test_an_asking_agent_on_a_schedule_is_told_why(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("ask")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", fake_chat)

    await agent_runner.run_agent(_sched(tool_mode="full"))
    assert seen["refusal_reason"] == "a scheduled run has nobody to ask"


async def test_an_approval_escaping_into_a_schedule_is_reported_not_swallowed(
        monkeypatch):
    """effective_mode never hands a schedule "ask", so this cannot happen
    today. If it ever does, the owner must get a sentence that names the
    cause rather than the generic "could not finish this run"."""
    import agent_access

    async def boom(**kwargs):
        raise agent_access.ApprovalRequired([], [])

    monkeypatch.setattr(agent_runner, "_owui_user_id_for",
                        AsyncMock(return_value="u1"))
    monkeypatch.setattr(agent_runner, "_list_agents",
                        AsyncMock(return_value=([_agent_row("all")], False)))
    monkeypatch.setattr(agent_runner, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(agent_runner, "_chat", boom)

    status, result, _extras = await agent_runner.run_agent(_sched())
    assert status == "failed"
    assert "nobody to ask" in result
```

If `AsyncMock` and `pytest` are not already imported at the top of
`tests/test_agent_runner.py`, add `from unittest.mock import AsyncMock` and
`import pytest`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_runner.py -q -k "ceiling or caps or asking or escaping"`
Expected: FAIL. `seen["tool_mode"]` is the raw `sched.tool_mode`, and
`refusal_reason` is never passed.

- [ ] **Step 3: Implement**

In `mcp-servers/tasks/agent_runner.py::run_agent`, replace the `_chat` call
block (currently the "Keyword arguments on purpose" comment through the call)
with:

```python
        # The agent's own level is a ceiling over the schedule's tool_mode.
        # A schedule may narrow what its agent may do and may never widen it;
        # see agent_access. An agent with no level set falls through to
        # exactly the behaviour this had before the setting existed.
        level = agent_access.level_of(meta)
        mode = agent_access.effective_mode(
            level, getattr(sched, "tool_mode", None),
            agent_access.SURFACE_SCHEDULE)

        # Keyword arguments on purpose: the tests assert on them by name, and
        # a positional call here would silently drift from those assertions.
        answer, notes = await _chat(
            token=chat_token, model=sched.agent_id,
            messages=_messages_for(sched), tool_ids=tools or None,
            user_email=sched.user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, getattr(sched, "tool_mode", None),
                agent_access.SURFACE_SCHEDULE))
```

Add a dedicated handler immediately above the existing `except Exception:` in
the same function:

```python
    except agent_access.ApprovalRequired:
        # Unreachable today: effective_mode never gives a schedule "ask".
        # Kept so that if it ever becomes reachable the owner is told the
        # cause instead of the generic "could not finish this run", which
        # would send somebody hunting for an outage that is not there.
        logger.warning("an agent asked for approval on a schedule, "
                       "which has nobody to ask")
        outcome = "failed"
        return ("failed",
                "This agent is set to ask before it changes anything, and a "
                "scheduled run has nobody to ask. Set it to All access, or "
                "run it from a chat.", {})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_runner.py tests/test_agent_tool_loop.py tests/test_agent_access.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/agent_runner.py mcp-servers/tasks/tests/test_agent_runner.py
git commit -m "feat(agents): an agent's access level caps what a schedule may do"
```

---

### Task 4: The channel turn endpoint

**Files:**
- Create: `mcp-servers/tasks/routes_agent_turn.py`
- Modify: `mcp-servers/tasks/main.py` (import and one `include_router`)
- Test: `mcp-servers/tasks/tests/test_agent_turn_endpoint.py`

**Interfaces:**
- Consumes: `agent_access` (Task 1), `_chat` / `CHANNEL_MAX_TOOL_ITERATIONS` / `CHANNEL_HTTP_TIMEOUT_SECONDS` / `_list_agents` / `_owui_user_id_for` (Task 2), `routes_gateway._require_internal`, `agent_activity`.
- Produces: `POST /agents/turn` returning `{"answer": str, "notes": list[str]}` or `{"pending": {"agent_id": str, "user_email": str, "calls": list, "conversation": list}}`. Module members `_resolve_agent(user_email, agent_id)`, `_trim_for_storage(conversation)`, `PENDING_CONTENT_CHARS`.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agent_turn_endpoint.py`:

```python
"""One agent turn, asked for by the chat gateway.

The gateway says WHICH agent. This service decides what that agent may touch.
That split is the point of the endpoint: tool_ids is the gate on which native
tools may execute, so a caller that could name them would be deciding its own
permissions.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import agent_access
import routes_agent_turn as rt


def _agent(access=None, tools=("gmail",)):
    meta = {"toolIds": list(tools)}
    if access is not None:
        meta["access"] = access
    return {"id": "agent-1", "name": "Scout", "meta": meta}


def _body(**over):
    class B:
        user_email = "owner@example.com"
        agent_id = "agent-1"
        messages = [{"role": "user", "content": "q"}]
    b = B()
    for k, v in over.items():
        setattr(b, k, v)
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-1"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())


async def test_the_endpoint_resolves_the_agents_own_tools(monkeypatch):
    """A caller must not be able to name tool_ids. It is the gate on which
    native tools may execute, so naming it outside this service would move
    the decision to the wrong side of the wall."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all", ["gmail"])], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")

    assert out == {"answer": "done", "notes": []}
    assert seen["tool_ids"] == ["gmail"]
    assert seen["user_email"] == "owner@example.com"


@pytest.mark.parametrize("access,expected", [
    ("read", agent_access.MODE_READ_ONLY),
    ("ask", agent_access.MODE_ASK),
    ("all", agent_access.MODE_FULL),
    (None, agent_access.MODE_READ_ONLY),
])
async def test_the_agents_level_decides_the_mode(access, expected, monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent(access)], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert seen["tool_mode"] == expected


async def test_the_refusal_never_mentions_schedules(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("read")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert "schedule" not in seen["refusal_reason"]


async def test_a_channel_gets_the_shorter_leash(monkeypatch):
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")
    assert seen["max_iterations"] == rt.CHANNEL_MAX_TOOL_ITERATIONS
    assert seen["timeout"] == rt.CHANNEL_HTTP_TIMEOUT_SECONDS


async def test_an_agent_that_wants_approval_comes_back_as_pending(monkeypatch):
    convo = [{"role": "assistant", "content": "", "tool_calls": []}]
    calls = [{"id": "c1", "function": {"name": "send_email"}}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, calls)

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("ask")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")

    assert "answer" not in out
    assert out["pending"]["calls"] == calls
    assert out["pending"]["agent_id"] == "agent-1"
    # Carried so the resume can check that the person answering is the person
    # who was asked. The state key is per chat, not per person.
    assert out["pending"]["user_email"] == "owner@example.com"


async def test_a_stored_conversation_is_trimmed(monkeypatch):
    """It holds every tool result from the turn and lands in a JSON column,
    so an uncapped record grows to whatever the agent happened to read."""
    big = "x" * (rt.PENDING_CONTENT_CHARS * 3)
    convo = [{"role": "tool", "tool_call_id": "c0", "content": big}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, [{"id": "c1"}])

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("ask")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    out = await rt.turn(_body(), x_internal_secret="s")
    stored = out["pending"]["conversation"][0]["content"]
    assert len(stored) <= rt.PENDING_CONTENT_CHARS + 100


async def test_an_unknown_agent_is_a_404_not_a_crash(monkeypatch):
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="s")
    assert caught.value.status_code == 404


async def test_a_truncated_listing_is_not_read_as_a_missing_agent(monkeypatch):
    """"Not in what we fetched" is not "does not exist". Saying the agent is
    gone would send somebody deleting a schedule that was fine."""
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], True)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="s")
    assert caught.value.status_code == 503


async def test_the_run_is_recorded_as_a_channel_run(monkeypatch):
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)

    await rt.turn(_body(), x_internal_secret="s")

    rt.agent_activity.start_run.assert_awaited_once()
    assert (rt.agent_activity.start_run.await_args.args[2]
            == rt.agent_activity.SOURCE_CHANNEL)
    rt.agent_activity.finish_run.assert_awaited_once()


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")

    monkeypatch.setattr(rt, "_require_internal", deny)
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    with pytest.raises(HTTPException) as caught:
        await rt.turn(_body(), x_internal_secret="wrong")
    assert caught.value.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_turn_endpoint.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'routes_agent_turn'`

- [ ] **Step 3: Implement**

Create `mcp-servers/tasks/routes_agent_turn.py`:

```python
"""One agent turn, run for the chat gateway.

The gateway holds the conversation and delivers the words. This holds the
tool loop, because the loop is where is_write_tool lives and that is the one
function deciding whether an agent may delete somebody's data. A second copy
of it in webhook-handler would be a second copy that can drift.

Deliberately internal only, and deliberately NOT part of routes_agents: that
router is mounted twice, bare and under /api/tasks, and the web mount is a
path an ordinary signed-in browser reaches. This one is mounted once.

The caller names the agent. It does not name the tools. tool_ids is the gate
on which native tools may execute (see execute_tool_call), so resolving it
here rather than accepting it is the difference between a permission and a
suggestion.
"""
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import agent_access
import agent_activity
from agent_runner import (CHANNEL_HTTP_TIMEOUT_SECONDS,
                          CHANNEL_MAX_TOOL_ITERATIONS,
                          CHAT_TOKEN_TTL_SECONDS, _chat, _list_agents,
                          _owui_user_id_for)
from agent_tools import execute_tool_call
from owui_token import mint_owui_token
from routes_gateway import _require_internal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents")

#: A held conversation carries every tool result from its turn and lands in a
#: JSON column in the state store, so it is capped before it is handed back
#: for storage. Smaller than the loop's own excerpt cap because this one is
#: written to a row rather than passed along in memory.
PENDING_CONTENT_CHARS = 2000

#: A run that stopped to ask is neither finished nor still working. Recorded
#: as its own status so the card does not claim the agent is awake for the
#: next 45 minutes waiting for a reply that may never come.
STATUS_WAITING = "waiting"


class TurnIn(BaseModel):
    user_email: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    messages: list[dict]


class ResumeIn(BaseModel):
    user_email: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    conversation: list[dict]
    calls: list[dict]
    approved: bool


async def _resolve_agent(user_email: str, agent_id: str) -> tuple[str, list[str], str | None]:
    """(token, the agent's own tool ids, its access level).

    Raises HTTPException rather than returning a sentinel: every caller here
    would have to re-raise anyway, and a sentinel that got ignored once would
    run a turn with no tools and look like a model problem.
    """
    owner = await _owui_user_id_for(user_email)
    if not owner:
        raise HTTPException(status_code=404,
                            detail="no account for that user")
    token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
    agents, truncated = await _list_agents(token)
    agent = next((a for a in agents
                  if isinstance(a, dict) and a.get("id") == agent_id), None)
    if agent is None:
        if truncated:
            # "Not in what we fetched" is not "does not exist". The listing
            # stopped early, so the agent may be on a page never reached.
            raise HTTPException(
                status_code=503,
                detail="could not check that agent just now")
        raise HTTPException(status_code=404, detail="no such agent")
    meta = agent.get("meta") if isinstance(agent.get("meta"), dict) else {}
    tools = meta.get("toolIds")
    tools = [t for t in tools if isinstance(t, str)] if isinstance(tools, list) else []
    return token, tools, agent_access.level_of(meta)


def _trim_for_storage(conversation: list[dict]) -> list[dict]:
    """Cap what goes into the state store, without dropping any message.

    Dropping a message would break the turn: every tool_call in the assistant
    message needs a matching tool message before the next completion. So the
    contents shrink and the shape stays.
    """
    out = []
    for msg in conversation:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and len(content) > PENDING_CONTENT_CHARS:
            msg = dict(msg)
            msg["content"] = (content[:PENDING_CONTENT_CHARS]
                              + "\n\n[shortened]")
        out.append(msg)
    return out


def _pending_payload(user_email: str, agent_id: str,
                     err: agent_access.ApprovalRequired) -> dict:
    return {"pending": {
        "agent_id": agent_id,
        # Carried so the resume can check the person answering is the person
        # who was asked: the gateway's state key is per chat, not per person.
        "user_email": user_email,
        "calls": err.calls,
        "conversation": _trim_for_storage(err.conversation),
    }}


@router.post("/turn")
async def turn(body: TurnIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Run one turn as this user's agent, tools and all."""
    _require_internal(x_internal_secret)
    token, tools, level = await _resolve_agent(body.user_email, body.agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)

    run_id = await agent_activity.start_run(
        body.agent_id, body.user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=body.agent_id, messages=body.messages,
            tool_ids=tools or None, user_email=body.user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(body.user_email, body.agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)
```

In `mcp-servers/tasks/main.py`, add the import beside the other route imports:

```python
from routes_agent_turn import router as agent_turn_router
```

and mount it ONCE, immediately after the existing agents mounts:

```python
app.include_router(agent_turn_router)  # /agents/turn — internal only (X-Internal-Secret)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_turn_endpoint.py -q`
Expected: PASS

- [ ] **Step 5: Prove the router is mounted once, not twice**

The whole reason this lives outside `routes_agents` is that the latter is
mounted on a public prefix. Verify:

Run:
```bash
cd mcp-servers/tasks && python -c "
from main import app
paths = [r.path for r in app.routes if 'turn' in r.path]
print(paths)
assert paths == ['/agents/turn'], paths
print('mounted once, internal path only')
"
```
Expected: `['/agents/turn']` then `mounted once, internal path only`

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_agent_turn_endpoint.py
git commit -m "feat(agents): run an agent turn with its tools for a channel"
```

---

### Task 5: Resuming an approved turn

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py`
- Test: `mcp-servers/tasks/tests/test_agent_turn_resume.py`

**Interfaces:**
- Consumes: `_resolve_agent`, `_pending_payload`, `ResumeIn` (Task 4).
- Produces: `POST /agents/turn/resume` returning the same shapes as `/agents/turn`. Module member `REFUSED_BY_OWNER`.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agent_turn_resume.py`:

```python
"""Picking a held turn back up once the owner has answered.

The dangerous half of the approval flow. Everything here is about the window
between the question and the answer: the agent can be edited, the level can
change, and the same record must never run twice.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import agent_access
import routes_agent_turn as rt


def _agent(access="ask"):
    return {"id": "agent-1", "name": "Scout",
            "meta": {"toolIds": ["gmail"], "access": access}}


def _body(approved=True, **over):
    class B:
        user_email = "owner@example.com"
        agent_id = "agent-1"
        conversation = [
            {"role": "user", "content": "send it"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1",
                             "function": {"name": "send_email",
                                          "arguments": "{}"}}]},
        ]
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "send_email", "arguments": "{}"}}]
    b = B()
    b.approved = approved
    for k, v in over.items():
        setattr(b, k, v)
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt.agent_activity, "start_run",
                        AsyncMock(return_value="run-2"))
    monkeypatch.setattr(rt.agent_activity, "finish_run", AsyncMock())


async def test_an_approved_call_runs_and_the_answer_comes_back(monkeypatch):
    async def fake_chat(**kwargs):
        return "Sent it.", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=True), x_internal_secret="s")

    ex.assert_awaited_once()
    assert out["answer"] == "Sent it."


async def test_the_tool_result_is_fed_back_before_the_model_is_asked_again(
        monkeypatch):
    """Every tool_call in the assistant message needs a matching tool message
    or the next completion is rejected outright."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call",
                        AsyncMock(return_value="sent"))

    await rt.resume(_body(approved=True), x_internal_secret="s")

    tool_msgs = [m for m in seen["messages"] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1"]
    assert tool_msgs[0]["content"] == "sent"


async def test_a_refusal_runs_nothing_but_still_lets_the_agent_explain(
        monkeypatch):
    """Going silent would be worse. The agent gets told it was refused and
    answers in its own words."""
    seen = {}

    async def fake_chat(**kwargs):
        seen.update(kwargs)
        return "Alright, I did not send it.", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=False), x_internal_secret="s")

    ex.assert_not_awaited()
    tool_msgs = [m for m in seen["messages"] if m.get("role") == "tool"]
    assert rt.REFUSED_BY_OWNER in tool_msgs[0]["content"]
    assert out["answer"] == "Alright, I did not send it."


async def test_an_agent_downgraded_to_read_only_does_not_get_its_write(
        monkeypatch):
    """The level is re-read on resume, not trusted from when the question was
    asked. Somebody who has second thoughts and changes the setting has
    changed the setting."""
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("read")], False)))
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    out = await rt.resume(_body(approved=True), x_internal_secret="s")

    ex.assert_not_awaited()
    assert "read only" in out["answer"]


async def test_a_deleted_agent_does_not_get_its_write(monkeypatch):
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], False)))
    ex = AsyncMock()
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    with pytest.raises(HTTPException):
        await rt.resume(_body(approved=True), x_internal_secret="s")
    ex.assert_not_awaited()


async def test_a_resumed_turn_can_ask_again(monkeypatch):
    """A model that wants a second write after the first one landed has to be
    able to ask about that one too."""
    convo = [{"role": "tool", "tool_call_id": "c1", "content": "sent"}]
    calls = [{"id": "c2", "function": {"name": "delete_message"}}]

    async def fake_chat(**kwargs):
        raise agent_access.ApprovalRequired(convo, calls)

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call",
                        AsyncMock(return_value="sent"))

    out = await rt.resume(_body(approved=True), x_internal_secret="s")
    assert out["pending"]["calls"] == calls


async def test_all_access_resumes_too(monkeypatch):
    """An agent moved from ask to all between question and answer should not
    be stuck: it is now MORE permitted, not less."""
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent("all")], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    await rt.resume(_body(approved=True), x_internal_secret="s")
    ex.assert_awaited_once()


async def test_the_tools_are_still_resolved_here_not_taken_from_the_caller(
        monkeypatch):
    """Same rule as the turn endpoint: the caller names the agent, this names
    the tools. execute_tool_call is scoped by them."""
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))

    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_chat", fake_chat)
    ex = AsyncMock(return_value="sent")
    monkeypatch.setattr(rt, "execute_tool_call", ex)

    await rt.resume(_body(approved=True), x_internal_secret="s")
    assert ex.await_args.args[2] == ["gmail"]


async def test_the_run_is_recorded_as_a_channel_run(monkeypatch):
    async def fake_chat(**kwargs):
        return "done", []

    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([_agent()], False)))
    monkeypatch.setattr(rt, "_chat", fake_chat)
    monkeypatch.setattr(rt, "execute_tool_call", AsyncMock(return_value="ok"))

    await rt.resume(_body(approved=True), x_internal_secret="s")
    assert (rt.agent_activity.start_run.await_args.args[2]
            == rt.agent_activity.SOURCE_CHANNEL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_turn_resume.py -q`
Expected: FAIL with `AttributeError: module 'routes_agent_turn' has no attribute 'resume'`

- [ ] **Step 3: Implement**

Append to `mcp-servers/tasks/routes_agent_turn.py`:

```python
#: Fed back as the tool result when the owner said no, so the agent can say
#: what happened in its own words instead of going quiet.
REFUSED_BY_OWNER = "Refused: the owner did not approve this action"

#: Levels that may still act when a held turn is picked back up. `ask` is
#: here because that is the level the question was asked under; `all` because
#: an agent moved up in the meantime is more permitted, not less.
_RESUMABLE = frozenset({agent_access.MODE_ASK, agent_access.MODE_FULL})


@router.post("/turn/resume")
async def resume(body: ResumeIn,
                 x_internal_secret: str = Header(default="")) -> dict:
    """Continue a turn that stopped to ask.

    The access level is READ AGAIN here rather than trusted from when the
    question was asked. Between the two there is a window in which the agent
    can be edited or deleted, and somebody who has second thoughts and turns
    an agent down to read only has turned it down.
    """
    _require_internal(x_internal_secret)
    token, tools, level = await _resolve_agent(body.user_email, body.agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)
    if mode not in _RESUMABLE:
        return {"answer": "This agent is set to read only now, so I did not "
                          "run that.", "notes": []}

    convo = list(body.conversation)
    for call in body.calls:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        raw_name = fn.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if body.approved:
            # tools, not anything the caller sent: same rule as the turn
            # endpoint, and the reason execute_tool_call takes this argument.
            result = await execute_tool_call(call, body.user_email,
                                             tools or None)
        else:
            result = (REFUSED_BY_OWNER + ", so " + (name or "that tool")
                      + " was not run.")
        # Every tool_call in the held assistant message needs a matching tool
        # message before the next completion, approved or not.
        convo.append({"role": "tool", "tool_call_id": call.get("id"),
                      "name": name, "content": result})

    run_id = await agent_activity.start_run(
        body.agent_id, body.user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=body.agent_id, messages=convo,
            tool_ids=tools or None, user_email=body.user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(body.user_email, body.agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_turn_resume.py tests/test_agent_turn_endpoint.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole tasks suite for regressions**

Run: `cd mcp-servers/tasks && python -m pytest tests/ -q 2>&1 | tail -20`
Expected: the same ~130 `ERROR at setup` failures from `db_session` and no
new failures. Compare against `git stash && python -m pytest tests/ -q | tail -3`
if the count looks off.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_agent_turn_resume.py
git commit -m "feat(agents): pick a held turn back up once the owner answers"
```

---

### Task 6: The gateway's client methods

**Files:**
- Modify: `webhook-handler/clients/tasks.py`
- Test: `webhook-handler/tests/test_gateway_agent_turn_client.py`

**Interfaces:**
- Consumes: `POST /agents/turn` and `POST /agents/turn/resume` (Tasks 4 and 5).
- Produces: `TasksClient.agent_turn(user_email, agent_id, messages) -> dict`, `TasksClient.agent_turn_resume(user_email, agent_id, conversation, calls, approved) -> dict`, `AGENT_TURN_TIMEOUT_SECONDS`.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_agent_turn_client.py`:

```python
"""Asking the tasks service to run an agent turn.

The one thing that is easy to get wrong here is the timeout. TasksClient
defaults to 15 seconds, which is right for reading a row and far too short
for a turn that may run three rounds of tool use.
"""
import httpx
import pytest
import respx

from clients.tasks import AGENT_TURN_TIMEOUT_SECONDS, TasksAPIError, TasksClient

BASE = "http://tasks:8210"


def _client():
    return TasksClient(BASE, internal_secret="sekrit")


@respx.mock
async def test_a_turn_is_asked_for_with_the_internal_secret():
    route = respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(200, json={"answer": "hi", "notes": []}))

    out = await _client().agent_turn(
        user_email="owner@example.com", agent_id="agent-1",
        messages=[{"role": "user", "content": "q"}])

    assert out == {"answer": "hi", "notes": []}
    sent = route.calls[0].request
    assert sent.headers["X-Internal-Secret"] == "sekrit"
    # Never X-User-Email on this call: the body names the user, and the
    # endpoint is internal. See the note on TasksClient._headers.
    assert "X-User-Email" not in sent.headers


@respx.mock
async def test_the_turn_gets_longer_than_the_default_fifteen_seconds():
    """Three rounds of tool use does not fit in the timeout used for reading
    a schedule row, and a timeout here reads to the user as the bot ignoring
    them."""
    seen = {}

    def capture(request):
        seen["timeout"] = request.extensions.get("timeout", {}).get("read")
        return httpx.Response(200, json={"answer": "hi", "notes": []})

    respx.post(f"{BASE}/agents/turn").mock(side_effect=capture)
    await _client().agent_turn(
        user_email="o@e.com", agent_id="a", messages=[])

    assert seen["timeout"] == AGENT_TURN_TIMEOUT_SECONDS
    assert AGENT_TURN_TIMEOUT_SECONDS > 15


@respx.mock
async def test_a_pending_answer_is_passed_straight_through():
    respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(200, json={"pending": {"calls": [1]}}))

    out = await _client().agent_turn(
        user_email="o@e.com", agent_id="a", messages=[])
    assert out["pending"]["calls"] == [1]


@respx.mock
async def test_a_resume_carries_the_verdict():
    route = respx.post(f"{BASE}/agents/turn/resume").mock(
        return_value=httpx.Response(200, json={"answer": "sent", "notes": []}))

    await _client().agent_turn_resume(
        user_email="o@e.com", agent_id="a",
        conversation=[{"role": "user", "content": "x"}],
        calls=[{"id": "c1"}], approved=False)

    body = route.calls[0].request.content.decode()
    assert '"approved": false' in body or '"approved":false' in body


@respx.mock
async def test_a_failure_arrives_as_a_typed_error_the_pipeline_can_catch():
    """pipeline.handle_event turns TasksAPIError into a sentence. An untyped
    exception here would escape as UNEXPECTED instead."""
    respx.post(f"{BASE}/agents/turn").mock(
        return_value=httpx.Response(503, json={"detail": "nope"}))

    with pytest.raises(TasksAPIError):
        await _client().agent_turn(
            user_email="o@e.com", agent_id="a", messages=[])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_agent_turn_client.py -q`
Expected: FAIL with `ImportError: cannot import name 'AGENT_TURN_TIMEOUT_SECONDS'`

- [ ] **Step 3: Implement**

In `webhook-handler/clients/tasks.py`, add near the top beside the other
module constants:

```python
#: An agent turn runs up to CHANNEL_MAX_TOOL_ITERATIONS completions with tool
#: calls in between, so it cannot use the 15 second default that suits
#: reading a row. Sized above the tasks service's own worst case for a
#: channel turn (3 rounds at 60 seconds) with room for the tool calls
#: themselves. A timeout here reads to the user as the bot ignoring them.
AGENT_TURN_TIMEOUT_SECONDS = 240.0
```

Add the two methods to `TasksClient`, beside the other internal-secret
methods:

```python
    async def agent_turn(self, user_email: str, agent_id: str,
                         messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Run one turn as this user's agent, tools and all.

        Deliberately does NOT send tool_ids. The tasks service resolves the
        agent's own tools, because that field is the gate on which native
        tools may execute and naming it from here would move the decision out
        of the service that enforces it.
        """
        resp = await self._internal_request(
            "POST", "/agents/turn",
            json={"user_email": user_email, "agent_id": agent_id,
                  "messages": messages},
            timeout=AGENT_TURN_TIMEOUT_SECONDS)
        return resp.json()

    async def agent_turn_resume(self, user_email: str, agent_id: str,
                                conversation: list[dict[str, Any]],
                                calls: list[dict[str, Any]],
                                approved: bool) -> dict[str, Any]:
        """Continue a turn the agent stopped to ask about."""
        resp = await self._internal_request(
            "POST", "/agents/turn/resume",
            json={"user_email": user_email, "agent_id": agent_id,
                  "conversation": conversation, "calls": calls,
                  "approved": approved},
            timeout=AGENT_TURN_TIMEOUT_SECONDS)
        return resp.json()
```

`_internal_request` currently hardcodes `timeout=self.timeout`. Change its
signature to accept an override:

```python
    async def _internal_request(self, method: str, path: str,
                                timeout: float | None = None,
                                **kwargs) -> httpx.Response:
        """For system endpoints (/discord-links/*) authed with X-Internal-Secret."""
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.request(
                    method, url, headers={"X-Internal-Secret": self._internal_secret}, **kwargs
                )
```

leaving the rest of that method untouched.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_agent_turn_client.py -q`
Expected: PASS

- [ ] **Step 5: Check nothing else called `_internal_request` positionally**

Run: `cd webhook-handler && grep -n "_internal_request(" clients/tasks.py | grep -v "async def"`
Expected: every call passes `method` and `path` positionally and everything
else by keyword. If any call passes a third positional argument, it now lands
on `timeout` and must be converted to a keyword.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_gateway_agent_turn_client.py
git commit -m "feat(gateway): ask tasks to run an agent turn"
```

---

### Task 7: Route agent messages through the tool loop

**Files:**
- Modify: `webhook-handler/gateway/pipeline.py` (`_run`, around lines 296-320)
- Test: `webhook-handler/tests/test_gateway_agent_tools.py`

**Interfaces:**
- Consumes: `TasksClient.agent_turn` (Task 6).
- Produces: `pipeline._deliver_turn(adapter, src, out, agent, notice) -> str | None` returning None when the turn is pending (Task 8 fills that in), and `pipeline.TURN_EMPTY`.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_agent_tools.py`:

```python
"""An agent mentioned in a channel can finally use its tools.

Until now this path caught OWUIToolCallError and answered "It can't do that
here yet". The tool loop lives in the tasks service, so the change is that an
agent message goes there instead of straight to Open WebUI.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource


def _event(text="hi scout, any mail?"):
    return MessageEvent(
        source=SessionSource(platform="discord", chat_id="c1",
                             user_id="u1", user_name="ralph"),
        message_type=MessageType.TEXT, text=text)


@pytest.fixture
def wired(monkeypatch):
    """The whole pipeline stubbed down to the one decision under test."""
    tasks = MagicMock()
    tasks.resolve_gateway_identity = AsyncMock(return_value={
        "linked": True, "email": "owner@example.com",
        "owui_token": "tok", "owui_user_id": "u1"})
    tasks.get_state = AsyncMock(return_value=None)
    tasks.set_state = AsyncMock(return_value=True)
    tasks.delete_state = AsyncMock(return_value=True)
    tasks.agent_turn = AsyncMock(
        return_value={"answer": "You have 4 unread.", "notes": []})
    monkeypatch.setattr(pipeline, "_tasks", tasks)

    owui = MagicMock()
    owui.chat_completion = AsyncMock(return_value="plain answer")
    owui.update_chat = AsyncMock()
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    monkeypatch.setattr(pipeline, "get_or_create_chat",
                        AsyncMock(return_value=("chat-1", {"messages": []})))
    monkeypatch.setattr(pipeline, "history_messages", lambda chat, n: [])

    adapter = MagicMock()
    adapter.send_chunked = AsyncMock()
    adapter.send_typing = AsyncMock()
    adapter.stop_typing = AsyncMock()
    return pipeline, tasks, owui, adapter


AGENT = {"id": "agent-1", "name": "Scout", "tools": ["gmail"]}


async def test_an_agent_message_goes_through_the_tool_loop(wired, monkeypatch):
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)

    tasks.agent_turn.assert_awaited_once()
    assert tasks.agent_turn.await_args.kwargs["agent_id"] == "agent-1"
    assert tasks.agent_turn.await_args.kwargs["user_email"] == "owner@example.com"
    owui.chat_completion.assert_not_awaited(), "the agent bypassed its tools"
    assert "You have 4 unread." in sent


async def test_a_plain_message_still_goes_straight_to_open_webui(wired,
                                                                monkeypatch):
    """No agent means no tools and no reason to pay for a second hop."""
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(None, None, None)))

    sent = await pl.handle_event(_event("what is the weather"), adapter)

    owui.chat_completion.assert_awaited_once()
    tasks.agent_turn.assert_not_awaited()
    assert "plain answer" in sent


async def test_the_agent_answers_in_its_own_name(wired, monkeypatch):
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent.startswith("Scout:")


async def test_notes_are_delivered_not_swallowed(wired, monkeypatch):
    """A refused write that nobody is told about is the worst outcome: the
    person believes it happened."""
    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={
        "answer": "Here is the draft.",
        "notes": ["Declined to run send_email, because this agent is set to "
                  "read only."]})
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert "Declined to run send_email" in sent


async def test_a_turn_with_nothing_in_it_still_says_something(wired,
                                                              monkeypatch):
    """Nothing on this path may fail silently. See the module docstring."""
    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={"answer": "", "notes": []})
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent.strip()


async def test_a_tasks_failure_is_a_sentence_not_silence(wired, monkeypatch):
    from clients.tasks import TasksAPIError

    pl, tasks, owui, adapter = wired
    tasks.agent_turn = AsyncMock(side_effect=TasksAPIError(503, "down"))
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    sent = await pl.handle_event(_event(), adapter)
    assert sent == pl.TASKS_DOWN


async def test_the_transcript_is_still_written(wired, monkeypatch):
    """The turn has to land in the user's sidebar, which is also what feeds
    the Brain."""
    pl, tasks, owui, adapter = wired
    monkeypatch.setattr(pl, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    await pl.handle_event(_event(), adapter)
    owui.update_chat.assert_awaited_once()
```

If `resolve_gateway_identity` is not the real method name on `TasksClient`,
match whatever `_run` calls in `pipeline.py` around line 228.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_agent_tools.py -q`
Expected: FAIL. `agent_turn` is never awaited; `chat_completion` is.

- [ ] **Step 3: Implement**

In `webhook-handler/gateway/pipeline.py`, add beside the other copy constants:

```python
TURN_EMPTY = ("The agent finished without saying anything. Ask it again and "
              "it may have more to say.")
```

Replace the `answer = await owui.chat_completion(...)` block in `_run` with:

```python
    if agent:
        # An agent goes through the tasks service, which owns the tool loop.
        # Open WebUI does not run tools for an API caller, so calling it
        # directly here is what produced "It can't do that here yet".
        out = await _tasks.agent_turn(
            user_email=identity["email"], agent_id=agent["id"],
            messages=messages)
        answer = _answer_from(out)
    else:
        answer = await owui.chat_completion(messages, model, chat_id=chat_id)
```

and add the helper beside `_say`:

```python
def _answer_from(out: dict) -> str:
    """The words to deliver from an agent turn.

    Notes ride along with the answer rather than replacing it: a refused
    write that nobody is told about is the worst outcome, because the person
    believes it happened.
    """
    answer = (out.get("answer") or "").strip()
    notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
    if notes:
        note_text = "\n".join(notes)
        answer = (answer + "\n\n" + note_text) if answer else note_text
    # Nothing on this path may fail silently.
    return answer or TURN_EMPTY
```

The existing transcript write, notice prefix and agent name prefix below this
block all stay exactly as they are.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_agent_tools.py tests/test_gateway_pipeline.py tests/test_gateway_agent_mention.py -q`
Expected: PASS. If `test_gateway_agent_mention.py` asserts that
`chat_completion` receives `tool_ids`, update those assertions to assert on
`agent_turn` instead: that behaviour has moved, it has not been lost.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_agent_tools.py webhook-handler/tests/test_gateway_agent_mention.py
git commit -m "feat(gateway): an agent mentioned in a channel can use its tools"
```

---

### Task 8: Asking before it acts

**Files:**
- Create: `webhook-handler/gateway/approvals.py`
- Modify: `webhook-handler/gateway/pipeline.py` (`_run`, and `_answer_from` becomes `_deliver_turn`)
- Test: `webhook-handler/tests/test_gateway_approvals.py`

**Interfaces:**
- Consumes: `TasksClient.agent_turn_resume`, `get_state` / `set_state` / `delete_state` (already on `TasksClient`).
- Produces: `approvals.pending_key(platform, chat_id) -> str`, `approvals.verdict(text) -> bool | None`, `approvals.prompt(agent_name, calls) -> str`, `approvals.PENDING_TTL_SECONDS`, `approvals.DROPPED`, `approvals.NOT_YOURS`.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_approvals.py`:

```python
"""Stopping to ask before an agent changes anything.

The turn ends and picks up on the next message, so everything here is about
that gap: reading a reply as a verdict, saying what is about to happen
clearly enough to answer, and never letting one record run twice.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway import approvals, pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

CALLS = [{"id": "c1", "type": "function",
          "function": {"name": "send_message",
                       "arguments": '{"to": "ralph@example.com", '
                                    '"subject": "Q3 numbers"}'}}]


# --- reading the reply -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "yes", "Yes", "  YES  ", "y", "ok", "okay", "sure", "go ahead", "do it",
    "approve", "approved",
])
def test_an_approval_is_recognised(text):
    assert approvals.verdict(text) is True


@pytest.mark.parametrize("text", [
    "no", "No", "n", "stop", "cancel", "dont", "don't", "nope",
])
def test_a_refusal_is_recognised(text):
    assert approvals.verdict(text) is False


@pytest.mark.parametrize("text", [
    "what would that email say?", "yesterday I asked you something",
    "no idea what you mean", "", "   ", "nothing to do with it",
])
def test_anything_else_is_not_a_verdict(text):
    """Anything else drops the pending action and is handled as an ordinary
    message. Being trapped in a confirmation loop is the failure mode people
    hate most, so an unrecognised reply must never re-ask."""
    assert approvals.verdict(text) is None


def test_a_word_containing_no_is_not_a_refusal():
    """"nothing", "november", "not sure yet" all contain "no"."""
    assert approvals.verdict("nothing has changed") is None


# --- what the person is shown ---------------------------------------------

def test_the_prompt_names_the_tool_and_its_arguments():
    """No hand-written phrase per tool. A phrasebook covering 300+ proxy
    tools would be wrong somewhere, and where it was wrong is exactly where
    somebody approves the wrong thing."""
    out = approvals.prompt("Scout", CALLS)
    assert "Scout" in out
    assert "send_message" in out
    assert "ralph@example.com" in out
    assert "Q3 numbers" in out
    assert "yes" in out.lower() and "no" in out.lower()


def test_a_long_argument_is_truncated():
    calls = [{"id": "c1", "function": {"name": "send_message",
                                       "arguments": '{"body": "%s"}' % ("x" * 5000)}}]
    out = approvals.prompt("Scout", calls)
    assert len(out) < 1200


def test_a_malformed_call_still_produces_a_readable_question():
    """These come from a model, so the shape cannot be trusted. A crash here
    would leave somebody staring at silence."""
    for bad in ([{"id": "c1"}], [{"function": "not a dict"}],
                [{"function": {"name": None}}], ["not a dict"], []):
        out = approvals.prompt("Scout", bad)
        assert out.strip()


def test_several_writes_are_one_question():
    """Two questions back to back for one intent is worse than one."""
    calls = CALLS + [{"id": "c2", "function": {"name": "delete_draft",
                                               "arguments": "{}"}}]
    out = approvals.prompt("Scout", calls)
    assert out.count("Reply") == 1
    assert "send_message" in out and "delete_draft" in out


def test_the_key_is_per_chat():
    assert approvals.pending_key("discord", "c1") != approvals.pending_key(
        "discord", "c2")
    assert approvals.pending_key("discord", "c1").startswith("agentpending:")


# --- the flow through the pipeline ----------------------------------------

def _event(text):
    return MessageEvent(
        source=SessionSource(platform="discord", chat_id="c1",
                             user_id="u1", user_name="ralph"),
        message_type=MessageType.TEXT, text=text)


AGENT = {"id": "agent-1", "name": "Scout", "tools": ["gmail"]}
PENDING = {"agent_id": "agent-1", "agent_name": "Scout",
           "user_email": "owner@example.com", "calls": CALLS,
           "conversation": [{"role": "user", "content": "send it"}],
           "chat_id": "chat-1", "user_text": "send it"}


@pytest.fixture
def wired(monkeypatch):
    tasks = MagicMock()
    tasks.resolve_gateway_identity = AsyncMock(return_value={
        "linked": True, "email": "owner@example.com",
        "owui_token": "tok", "owui_user_id": "u1"})
    tasks.get_state = AsyncMock(return_value=None)
    tasks.set_state = AsyncMock(return_value=True)
    tasks.delete_state = AsyncMock(return_value=True)
    tasks.agent_turn = AsyncMock(return_value={"answer": "ok", "notes": []})
    tasks.agent_turn_resume = AsyncMock(
        return_value={"answer": "Sent it.", "notes": []})
    monkeypatch.setattr(pipeline, "_tasks", tasks)

    owui = MagicMock()
    owui.chat_completion = AsyncMock(return_value="plain")
    owui.update_chat = AsyncMock()
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    monkeypatch.setattr(pipeline, "get_or_create_chat",
                        AsyncMock(return_value=("chat-1", {"messages": []})))
    monkeypatch.setattr(pipeline, "history_messages", lambda chat, n: [])
    monkeypatch.setattr(pipeline, "_choose_agent",
                        AsyncMock(return_value=(AGENT, None, None)))

    adapter = MagicMock()
    adapter.send_chunked = AsyncMock()
    adapter.send_typing = AsyncMock()
    adapter.stop_typing = AsyncMock()
    return pipeline, tasks, adapter


async def test_a_pending_turn_is_stored_and_the_question_is_asked(wired):
    pl, tasks, adapter = wired
    tasks.agent_turn = AsyncMock(return_value={"pending": {
        "agent_id": "agent-1", "user_email": "owner@example.com",
        "calls": CALLS, "conversation": []}})

    sent = await pl.handle_event(_event("send that email"), adapter)

    tasks.set_state.assert_awaited_once()
    key = tasks.set_state.await_args.args[0]
    assert key == approvals.pending_key("discord", "c1")
    assert tasks.set_state.await_args.kwargs["ttl_seconds"] == approvals.PENDING_TTL_SECONDS
    assert "send_message" in sent


async def test_yes_resumes_and_runs_it(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    sent = await pl.handle_event(_event("yes"), adapter)

    tasks.agent_turn_resume.assert_awaited_once()
    assert tasks.agent_turn_resume.await_args.kwargs["approved"] is True
    assert "Sent it." in sent


async def test_no_resumes_with_a_refusal(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)
    tasks.agent_turn_resume = AsyncMock(
        return_value={"answer": "Alright, I left it.", "notes": []})

    sent = await pl.handle_event(_event("no"), adapter)

    assert tasks.agent_turn_resume.await_args.kwargs["approved"] is False
    assert "Alright, I left it." in sent


async def test_the_record_is_deleted_before_it_is_acted_on(wired):
    """Otherwise a second "yes" arriving while the first is still running
    sends the same email twice."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    order = []
    tasks.delete_state = AsyncMock(side_effect=lambda k: order.append("delete"))
    tasks.agent_turn_resume = AsyncMock(
        side_effect=lambda **k: (order.append("resume"),
                                 {"answer": "done", "notes": []})[1])

    await pl.handle_event(_event("yes"), adapter)
    assert order == ["delete", "resume"]


async def test_somebody_else_cannot_approve_your_agents_write(wired):
    """The state key is per chat. In a group, or after a re-link, the person
    answering is not necessarily the person who was asked."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=dict(PENDING,
                                                  user_email="someone@else.com"))

    sent = await pl.handle_event(_event("yes"), adapter)

    tasks.agent_turn_resume.assert_not_awaited()
    assert sent == approvals.NOT_YOURS


async def test_an_unrelated_reply_drops_it_and_is_answered_normally(wired):
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    sent = await pl.handle_event(_event("actually what is the weather"), adapter)

    tasks.delete_state.assert_awaited_once()
    tasks.agent_turn_resume.assert_not_awaited()
    tasks.agent_turn.assert_awaited_once(), "the new question went unanswered"
    assert approvals.DROPPED in sent


async def test_a_pending_check_survives_a_state_store_failure(wired):
    """Reading the pin already fails open here for the same reason: a state
    outage must not make the bot stop answering."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(side_effect=RuntimeError("state down"))

    sent = await pl.handle_event(_event("hello"), adapter)
    assert sent and sent != pl.UNEXPECTED


async def test_a_pending_reply_is_checked_before_commands(wired):
    """"/help" during a pending approval must not vanish. It is not a
    verdict, so it drops the action and runs as the command it is."""
    pl, tasks, adapter = wired
    tasks.get_state = AsyncMock(return_value=PENDING)

    await pl.handle_event(_event("/help"), adapter)
    tasks.delete_state.assert_awaited_once()
    tasks.agent_turn_resume.assert_not_awaited()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_approvals.py -q`
Expected: FAIL with `ImportError: cannot import name 'approvals'`

- [ ] **Step 3: Write the approvals module**

Create `webhook-handler/gateway/approvals.py`:

```python
"""Stopping to ask the owner before an agent changes anything.

The tool loop runs inside one request and cannot sit and wait, so an agent on
"With access" ends its turn early and picks it back up on the next inbound
message. This module holds the three small decisions that go with that: what
counts as an answer, what the question looks like, and where the held turn is
kept.

Nothing here talks to a service. That keeps it testable without a pipeline,
which matters because the verdict matcher is the piece most likely to be
wrong in a way that only shows up on somebody's real sentence.
"""
import json

#: Long enough to walk away and come back, short enough that an approval
#: cannot be answered days later against a conversation nobody remembers.
PENDING_TTL_SECONDS = 600

#: One argument value, in the question. Enough to recognise an email address
#: or a subject line, not enough for a message body to bury the question.
MAX_ARG_CHARS = 120

#: How many arguments of one call are shown. Beyond this the question stops
#: being readable, which is the same as not asking.
MAX_ARGS_SHOWN = 5

DROPPED = "I dropped the action I was waiting on."
NOT_YOURS = ("That was not your agent's question to answer, so I left it "
             "alone.")
EXPIRED = ("I am not waiting on anything now. Ask again and I will run it "
           "from the top.")

_YES = frozenset({"yes", "y", "ok", "okay", "sure", "go ahead", "do it",
                  "approve", "approved", "yep", "yeah", "please do"})
_NO = frozenset({"no", "n", "stop", "cancel", "dont", "don't", "nope",
                 "no thanks", "leave it"})


def pending_key(platform: str, chat_id: str) -> str:
    return "agentpending:%s:%s" % (platform, chat_id)


def verdict(text: str) -> bool | None:
    """True for yes, False for no, None for anything else.

    Matched on the WHOLE message, not on words inside it. "nothing has
    changed" contains "no" and is not a refusal, and reading it as one would
    silently cancel something the person never mentioned.

    None is not a failure. Anything that is not a verdict drops the held
    action and is handled as an ordinary message, because being trapped in a
    confirmation loop is the failure mode people hate most.
    """
    cleaned = (text or "").strip().lower().rstrip(".!")
    if not cleaned:
        return None
    if cleaned in _YES:
        return True
    if cleaned in _NO:
        return False
    return None


def _arguments(fn: dict) -> dict:
    raw = fn.get("arguments")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (ValueError, TypeError):
        # Comes from a model, so the wrong type is exactly what to expect.
        return {}
    return parsed if isinstance(parsed, dict) else {}


def prompt(agent_name: str, calls: list) -> str:
    """The question, in the agent's own terms.

    The tool's own name and its arguments, not a hand-written phrase per
    tool. A phrasebook covering the 300+ proxy tools would be wrong
    somewhere, and where it was wrong is exactly where somebody would approve
    the wrong thing.
    """
    lines = ["%s wants to run:" % (agent_name or "This agent")]
    for call in calls or []:
        call = call if isinstance(call, dict) else {}
        fn = call.get("function")
        fn = fn if isinstance(fn, dict) else {}
        name = fn.get("name")
        name = name.strip() if isinstance(name, str) and name.strip() else "an unnamed tool"
        lines.append("  " + name)
        for key, value in list(_arguments(fn).items())[:MAX_ARGS_SHOWN]:
            lines.append("     %s: %s" % (key, str(value)[:MAX_ARG_CHARS]))
    if len(lines) == 1:
        # Every call was unreadable. Still ask: acting without asking is the
        # one thing this level exists to prevent.
        lines.append("  something it did not name")
    lines.append("")
    lines.append("Reply yes to let it, or no to skip.")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire it into the pipeline**

In `webhook-handler/gateway/pipeline.py`, add to the imports:

```python
from gateway import approvals
```

Add this block in `_run` immediately AFTER the empty-text check
(`if not text.strip(): return ""`) and BEFORE the
`if gateway_commands.is_command(text):` block:

```python
    # Checked before commands so that "/help" during a pending approval is
    # not swallowed: it is not a verdict, so it drops the held action and
    # then runs as the command it is.
    held = await _read_pending(src)
    drop_notice = None
    if held:
        answer_given = approvals.verdict(text)
        if answer_given is None:
            await _clear_pending(src)
            drop_notice = approvals.DROPPED
        else:
            return await _resume_pending(
                adapter, src, held, answer_given, identity["email"])
```

Then, where the notice is folded into the answer near the end of `_run`,
combine `drop_notice` with the existing `notice`:

```python
    notice = "\n\n".join(n for n in (drop_notice, notice) if n) or None
```

Add these helpers beside `_read_pin`:

```python
async def _read_pending(src: SessionSource) -> dict | None:
    """The held approval for this conversation, or None. Never raises.

    Fails open exactly like _read_pin: a state store outage must not stop the
    bot answering, and the cost of missing a held turn is that the person
    repeats themselves.
    """
    try:
        held = await _tasks.get_state(approvals.pending_key(
            src.platform, src.chat_id))
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not read a held approval", exc_info=True)
        return None
    return held if isinstance(held, dict) and held.get("calls") else None


async def _clear_pending(src: SessionSource) -> None:
    try:
        await _tasks.delete_state(approvals.pending_key(
            src.platform, src.chat_id))
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not clear a held approval", exc_info=True)


async def _store_pending(src: SessionSource, pending: dict, agent: dict,
                         chat_id: str, text: str) -> bool:
    """Keep the held turn. Returns whether it was actually kept."""
    try:
        await _tasks.set_state(
            approvals.pending_key(src.platform, src.chat_id),
            {"agent_id": pending.get("agent_id") or agent["id"],
             "agent_name": agent.get("name") or agent["id"],
             "user_email": pending.get("user_email"),
             "calls": pending.get("calls") or [],
             "conversation": pending.get("conversation") or [],
             # Carried so the transcript still gets written when the turn
             # finishes, or an approved turn vanishes from the sidebar.
             "chat_id": chat_id, "user_text": text},
            ttl_seconds=approvals.PENDING_TTL_SECONDS)
        return True
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not hold an approval", exc_info=True)
        return False


async def _resume_pending(adapter: BasePlatformAdapter, src: SessionSource,
                          held: dict, approved: bool, user_email: str) -> str:
    """Pick a held turn back up. Deletes the record first, always."""
    # Deleted BEFORE anything runs. A second "yes" arriving while this one is
    # in flight would otherwise send the same email twice.
    await _clear_pending(src)
    if held.get("user_email") != user_email:
        # The key is per chat, so in a group, or after a re-link, the person
        # answering is not necessarily the person who was asked.
        return await _say(adapter, src.chat_id, approvals.NOT_YOURS)

    await adapter.send_typing(src.chat_id)
    out = await _tasks.agent_turn_resume(
        user_email=user_email, agent_id=held["agent_id"],
        conversation=held.get("conversation") or [],
        calls=held.get("calls") or [], approved=approved)

    agent = {"id": held["agent_id"], "name": held.get("agent_name")}
    return await _deliver_turn(adapter, src, out, agent,
                               held.get("chat_id"), held.get("user_text") or "",
                               None, None)
```

Replace the `_answer_from` helper from Task 7 with `_deliver_turn`, which
handles the pending case as well, and call it from `_run` in place of the
delivery block:

```python
async def _deliver_turn(adapter: BasePlatformAdapter, src: SessionSource,
                        out: dict, agent: dict, chat_id: str | None,
                        text: str, owui, chat) -> str:
    """Say what came back from an agent turn, held or finished.

    Notes ride along with the answer rather than replacing it: a refused
    write that nobody is told about is the worst outcome, because the person
    believes it happened.
    """
    pending = out.get("pending")
    if isinstance(pending, dict) and pending.get("calls"):
        kept = await _store_pending(src, pending, agent, chat_id or "", text)
        question = approvals.prompt(agent.get("name") or agent["id"],
                                    pending["calls"])
        if not kept:
            # Never ask a question that cannot be answered.
            question = (question + "\n\n" + "I could not hold this, so the "
                        "answer may not reach me. Ask again if nothing "
                        "happens.")
        return await _say(adapter, src.chat_id, question)

    answer = (out.get("answer") or "").strip()
    notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
    if notes:
        note_text = "\n".join(notes)
        answer = (answer + "\n\n" + note_text) if answer else note_text
    # Nothing on this path may fail silently.
    answer = answer or TURN_EMPTY

    if owui is not None and chat is not None and chat_id:
        # Persist before delivering, but never let a persist failure swallow
        # a good answer: the person is waiting and the answer already exists.
        try:
            await owui.update_chat(
                chat_id, append_turn(chat, text, answer, agent["id"]))
        except Exception:                              # noqa: BLE001
            log.exception("gateway: could not write the transcript to chat "
                          "%s; delivering the answer anyway", chat_id)

    name = agent.get("name") or agent["id"]
    return await _say(adapter, src.chat_id, "%s:\n%s" % (name, answer))
```

In `_run`, the agent branch becomes:

```python
    if agent:
        out = await _tasks.agent_turn(
            user_email=identity["email"], agent_id=agent["id"],
            messages=messages)
        if notice:
            await _say(adapter, src.chat_id, notice)
        return await _deliver_turn(adapter, src, out, agent, chat_id, text,
                                   owui, chat)
```

The non-agent path below it keeps its existing `chat_completion`, transcript
write and delivery exactly as they are.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd webhook-handler && python -m pytest tests/test_gateway_approvals.py tests/test_gateway_agent_tools.py -q`
Expected: PASS

- [ ] **Step 6: Run the whole webhook-handler suite**

Run: `cd webhook-handler && python -m pytest tests/ -q 2>&1 | tail -15`
Expected: no new failures against the pre-change baseline.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/gateway/approvals.py webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_approvals.py
git commit -m "feat(gateway): an agent asks before it changes anything"
```

---

### Task 9: The control on the Edit agent form

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` (markup near line 538, `openForm`, `buildAgentBody`, `save`, `fillFormFromTemplate`)
- Test: `mcp-servers/tasks/tests/test_agents_page_access.py`

**Interfaces:**
- Consumes: `meta.access` as read by `agent_access.level_of` (Task 1).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agents_page_access.py`:

```python
"""The Access control on the agent form.

Structural, because the page is vanilla JS with no test harness. These check
the things that would silently change somebody's permissions if they were
wrong, which is why they are worth having even in this crude form.
"""
import os
import re

PAGE = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")


def _page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def test_all_three_levels_are_offered():
    page = _page()
    for value in ('value="read"', 'value="ask"', 'value="all"'):
        assert value in page, value


def test_the_labels_are_the_owners_words():
    page = _page()
    assert "Read only" in page
    assert "With access" in page
    assert "All access" in page


def test_the_scope_is_stated_on_the_form():
    """The web chat runs Open WebUI's own tool loop and ignores this setting.
    A permission control that silently does nothing where somebody first
    tests it is worse than one that admits its edges."""
    page = _page()
    assert "Web chat" in page
    assert re.search(r"always has full access", page)


def test_a_new_agent_defaults_to_asking():
    page = _page()
    assert re.search(r'value="ask"[^>]*checked', page), (
        "the middle level is the default for a new agent")


def test_the_level_is_written_into_meta():
    page = _page()
    assert re.search(r"access:\s*\w+", page), (
        "buildAgentBody must put the level on meta.access")


def test_an_agent_with_no_level_set_is_not_given_one_on_save():
    """Absent means "behave exactly as today". Preselecting a level and
    writing it on an unrelated edit would silently drop a schedule from full
    to read only."""
    page = _page()
    assert "chosenAccess" in page
    assert re.search(r"if\s*\(\s*access\s*\)", page) or \
           re.search(r"access\s*!==?\s*null", page), (
        "the level must be omitted from the body when nothing is selected")


def test_no_em_dashes_in_the_new_copy():
    page = _page()
    assert "\u2014" not in page and "\u2013" not in page
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agents_page_access.py -q`
Expected: FAIL on every assertion about `value="read"` and friends.

- [ ] **Step 3: Add the markup**

In `mcp-servers/tasks/static/agents.html`, insert immediately after the
`<select id="agent-base"></select>` line and before the
`<label class="switch">` block:

```html
        <label>Access</label>
        <div class="access" id="agent-access">
          <label class="radio">
            <input type="radio" name="agent-access" value="read">
            <span>Read only</span>
          </label>
          <label class="radio">
            <input type="radio" name="agent-access" value="ask" checked>
            <span>With access <em>asks before it changes anything</em></span>
          </label>
          <label class="radio">
            <input type="radio" name="agent-access" value="all">
            <span>All access</span>
          </label>
        </div>
        <div class="hint" id="access-hint">Applies in Discord, Telegram and
          scheduled runs. Web chat here always has full access.</div>
```

Add the styling beside the existing `.switch` rules in the page's `<style>`
block:

```css
  .access { display: flex; flex-direction: column; gap: 8px; margin: 6px 0 2px; }
  .access .radio { display: flex; align-items: center; gap: 9px;
                   font-size: 13.5px; cursor: pointer; }
  .access .radio em { color: var(--muted); font-style: normal;
                      font-size: 12.5px; }
```

- [ ] **Step 4: Read and write the level in the JS**

Add these two helpers beside `chosenTools`:

```js
    // Null when nothing is selected, which is how an agent that predates
    // this setting keeps its "no opinion" state. Returning a default here
    // would write a level onto every agent the first time somebody edited
    // its name, and silently drop a full schedule to read only.
    function chosenAccess() {
      var picked = document.querySelector(
        'input[name="agent-access"]:checked');
      return picked ? picked.value : null;
    }

    function setAccess(value) {
      var all = document.querySelectorAll('input[name="agent-access"]');
      for (var i = 0; i < all.length; i++) all[i].checked = false;
      if (!value) return;
      var one = document.querySelector(
        'input[name="agent-access"][value="' + value + '"]');
      if (one) one.checked = true;
    }
```

In `buildAgentBody`, change the `meta` object so the level is written only
when there is one:

```js
    function buildAgentBody(f) {
      var meta = { description: f.instructions.slice(0, 120),
                   toolIds: f.toolIds,
                   agent_instructions: f.instructions };
      // Only when a level is actually selected. See chosenAccess: an agent
      // with no level behaves exactly as it did before this setting existed,
      // and an unrelated edit must not quietly give it one.
      if (f.access) meta.access = f.access;
      return {
        id: f.id, name: f.name, base_model_id: f.baseModel,
        meta: meta,
        params: { system: f.instructions },
```

leaving the rest of that function, including the `access_grants` handling,
exactly as it is.

In `save`, pass it through:

```js
      var body = buildAgentBody({
        id: editingId || newAgentId(name), name: name,
        baseModel: baseModel,
        instructions: instructions, toolIds: chosenTools(),
        access: chosenAccess(),
        accessGrants: (existing && existing.access_grants) || []
      });
```

In `openForm`, set the control from the agent, defaulting only for a new one:

```js
      // A new agent starts on "ask": capable, and it checks with you first.
      // An existing agent with no level shows nothing selected, because it
      // genuinely has no level and pretending otherwise would write one.
      setAccess(agent ? ((agent.meta && agent.meta.access) || "")
                      : "ask");
      document.getElementById("access-hint").textContent =
        (agent && !(agent.meta && agent.meta.access))
          ? ("Not set yet, so this agent works as it always has. Pick one to "
             + "control what it may do. Web chat here always has full access.")
          : ("Applies in Discord, Telegram and scheduled runs. Web chat here "
             + "always has full access.");
```

In the duplicate-from-template path (the function around line 1540 that fills
the form from an existing agent), add the same carry-across beside the tools:

```js
      setAccess((agent.meta && agent.meta.access) || "ask");
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agents_page_access.py -q`
Expected: PASS

- [ ] **Step 6: Check the page still parses and the browser suite passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/ -q -k "agents or browser" 2>&1 | tail -10`
Expected: no new failures. The browser suite has a known tail flake of socket
errors when run straight after the full suite; run it standalone to confirm.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/test_agents_page_access.py
git commit -m "feat(agents): choose what an agent is allowed to do"
```

---

### Task 10: Deploy and prove it on the server

**Files:**
- No source changes. This task is verification.

**Interfaces:**
- Consumes: everything above.
- Produces: a deployed, exercised feature.

`CLAUDE.md` is explicit that wiring inside a function body is not caught by an
import or a unit test, and this pipeline has been bitten by exactly that
twice. Nothing here is optional.

- [ ] **Step 1: Confirm the tree is clean and the suites pass**

Run:
```bash
cd "C:/All/Work - Code/ai_ui" && git status --short | grep -v "^?? apps/" | grep -v "^?? _aiui_demo"
cd mcp-servers/tasks && python -m pytest tests/ -q 2>&1 | tail -3
cd ../../webhook-handler && python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: no unexpected modified files; the tasks suite showing only the
known `db_session` setup errors; the webhook-handler suite clean.

- [ ] **Step 2: Deploy the tasks service**

Run: `ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh`

If `rsync` is missing (Git Bash on Windows), fall back to one `scp` per
changed file, then rebuild, then update `.deploy-state` by hand. It is
**JSON** (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`) and the
script parses `['sha']`; a bare SHA breaks the next deploy.

If `scp` fails while `ssh` works (this happened for 30 minutes on 2026-08-28),
base64 the file and echo it over ssh; for a large file, gzip then split into
7KB chunks and append, **verifying the byte count after each chunk**. A chunk
has silently failed before and produced a truncated file.

After any `scp`, run `sed -i 's/\r$//'` on the server: this repo checks out
CRLF and a trailing `\r` silently reads as false in a compose value.

- [ ] **Step 3: Deploy the webhook-handler by hand**

The orchestrator does not watch `webhook-handler/`. One `scp` per changed
file; `scp -r` silently skips files.

```bash
scp webhook-handler/gateway/approvals.py root@46.224.193.25:/root/proxy-server/webhook-handler/gateway/approvals.py
scp webhook-handler/gateway/pipeline.py root@46.224.193.25:/root/proxy-server/webhook-handler/gateway/pipeline.py
scp webhook-handler/clients/tasks.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
ssh root@46.224.193.25 "cd /root/proxy-server && sed -i 's/\r$//' webhook-handler/gateway/approvals.py webhook-handler/gateway/pipeline.py webhook-handler/clients/tasks.py && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

Before overwriting anything, hash-sweep the server's copy against the repo's
(CRLF-normalized). Teammates edit files directly on the box, and a repo-wins
deploy silently reverts their work.

- [ ] **Step 4: Verify both services came up**

Run:
```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler tasks"
```
Expected: a healthy body from `/healthz`, and both containers `Up`.

- [ ] **Step 5: Prove the endpoint is internal only**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  https://ai-ui.coolestdomain.win/tasks/agents/turn \
  -H "Content-Type: application/json" \
  -d '{"user_email":"x@y.com","agent_id":"a","messages":[]}'
```
Expected: `403` or `404`. Anything that runs a turn is a hole; stop and fix it
before going further.

- [ ] **Step 6: Exercise all three levels in a real Discord DM**

For each, set Scout's Access on the Agents page, then message the bot:

1. **Read only.** "scout, how many unread emails do I have?" Expected: a real
   count, so a read genuinely ran. Then "scout, send a test email to
   yourself." Expected: a refusal naming the agent, and **not** using the word
   "schedule".
2. **With access.** "scout, send a test email to <your address> saying hello."
   Expected: the question, naming `send_message` and showing the recipient.
   Reply **no**. Expected: the agent says it did not send. Ask again, reply
   **yes**. Expected: the mail arrives.
3. **All access.** Same request. Expected: it sends with no question.

Then two edge cases that only a real run can show:

4. Ask for a write, then reply **"what would it say?"** instead of yes or no.
   Expected: the dropped-action line, and the new question answered.
5. Ask for a write, wait 11 minutes, reply **yes**. Expected: a plain sentence
   saying nothing is being waited on, not silence.

- [ ] **Step 7: Confirm the schedule side did not regress**

Run one existing schedule with `tool_mode=full` whose agent has no level set,
using Run now on the Cron page. Expected: it still runs its tools, unchanged.
This is the row of the ceiling table that protects everything already in
production.

- [ ] **Step 8: Confirm channel runs show on the agent cards**

Open the Agents page after step 6. Expected: Scout's card shows a recent run.
The endpoint records with `SOURCE_CHANNEL`, which closes the "channel runs are
not recorded" gap.

- [ ] **Step 9: Stamp the deploy state and push**

```bash
git push origin main
```

Confirm `.deploy-state` on the server carries the new SHA as JSON.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the three levels
and `meta.access` (Tasks 1, 9); absent meaning today's behaviour (Tasks 1, 3,
9); the ceiling (Tasks 1, 3); `ask` as `read` on a schedule (Tasks 1, 3); the
turn endpoint and its refusal to accept `tool_ids` (Task 4); the channel
budget (Tasks 2, 4); the gateway swap (Tasks 6, 7); the approval flow
including delete-before-act, the user re-check, the level re-read and expiry
(Tasks 5, 8); the corrected refusal wording (Tasks 1, 2); the modal and its
honest scope line (Task 9); `SOURCE_CHANNEL` recording (Tasks 4, 5, 10);
deploy (Task 10).

**Naming consistency.** `refusal_reason` is a function in `agent_access` and a
keyword argument on `_chat`; that shadowing is deliberate and the call sites
pass `refusal_reason=agent_access.refusal_reason(...)`. `tool_mode` stays the
parameter name on `_chat` even though it now carries three values, because
`run_agent` and the existing tests already use it. `MODE_*` values match the
strings the `tasks.schedules.tool_mode` column already stores (`read_only`,
`full`), so no migration is implied.

**Known gap carried forward, not fixed here.** Native tools still ignore
`public.tool.valves`, so `create_document` works in chat and fails on a
schedule. It is unrelated to access levels and stays on the backlog.
