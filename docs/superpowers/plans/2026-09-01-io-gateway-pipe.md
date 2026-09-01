# IO Gateway Pipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One model in the Open WebUI dropdown, "IO", that answers you itself and wakes one of your agents when you name it, so that saying "hi mia" in the web chat reaches Mia the way it already does in Discord.

**Architecture:** A thin Open WebUI pipe holds no routing logic. It sends the conversation to a new internal endpoint in the `tasks` service, which reads the per-chat pin, matches an agent by name, and either runs that agent through the existing `/agents/turn` machinery or reports that no agent was named. When no agent is named the pipe answers on a base model itself. Keeping the logic in `tasks` means the web chat runs OUR tool loop, so the per-agent access levels apply there for the first time.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, httpx, pytest (`asyncio_mode = auto`), an Open WebUI Pipe function (pydantic `Valves`), Docker Compose on Hetzner.

**Spec:** `docs/superpowers/specs/2026-09-01-io-gateway-and-setup-assistant-design.md` (Phase 1 only; Phase 2, the setup assistant, is a separate plan)

## Global Constraints

- **Commit messages carry no AI attribution.** No `Co-Authored-By`, no "Generated with". Author is Ralph Benitez only. Non-negotiable.
- **No em-dashes or en-dashes in any user-visible copy.** Use a period, comma, or "and"/"so". In tests asserting their absence use `"\u2014"` / `"\u2013"`, never the literal characters.
- **No UTF-8 BOM on any file.** No other Python file in this repo has one.
- **`git add` named paths only. Never `git add -A` or `git add .`** This repo always carries a large untracked `apps/` tree; an implementer once swept 174 unrelated files and 10MB of binaries into a commit.
- **Never log or store a minted Open WebUI token**, and never put one in a response body. This project has already leaked a bot token through a client that logged a request URL.
- **Before appending a module-level helper or fixture to an existing test file, grep for a definition of that name first.** A duplicate silently rebinds it for the whole module and breaks unrelated tests. This cost a wasted round on the previous plan.
- **Expect ~147 errors** when running the full tasks suite locally: every test using `db_session` fails at setup because there is no local Postgres. That is pre-existing. Baseline is 2964 passed / 70 skipped / 147 errors.
- Repo checks out CRLF on Windows. Preserve each file's existing line endings.
- Code runs in containers, not local dev. The box has 3.8GB RAM.

---

### Task 1: Which agent is being spoken to

**Files:**
- Create: `mcp-servers/tasks/agent_routing.py`
- Test: `mcp-servers/tasks/tests/test_agent_routing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `match_agent(text: str, agents: list[dict]) -> dict | None`, `wants_release(text: str) -> bool`, `last_user_text(messages: list[dict]) -> str`, `RELEASE_PHRASES: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_routing.py`:

```python
"""Working out who the person is talking to.

The rule is ported from the channel gateway, which has run in Discord and
Telegram for weeks: a whole-word match on the agent's name anywhere in the
sentence, because people write "hi mia, are you there" rather than an
@mention.

The dangerous half is the false positive. An agent named Ada must not be
summoned by "adapt", or somebody discussing adapters gets an agent every time.
"""
import pytest

import agent_routing as ar

ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
AGENTS = [ADA, MIA]


@pytest.mark.parametrize("text,expected", [
    ("hi mia how can you help me", "Mia"),
    ("MIA, any news?", "Mia"),
    ("  ada: what is up", "Ada"),
    ("could you ask Ada about the invoice", "Ada"),
    ("gisingin mo si Mia", "Mia"),
    ("hey ada!", "Ada"),
])
def test_a_name_spoken_in_a_sentence_picks_that_agent(text, expected):
    assert ar.match_agent(text, AGENTS)["name"] == expected


@pytest.mark.parametrize("text", [
    "can you adapt this for me",
    "the adapter is broken",
    "miami is far away",
    "nomiadic patterns",
    "readapt the layout",
    "",
    "   ",
])
def test_a_name_inside_another_word_is_not_a_mention(text):
    """The whole reason boundaries are hand rolled. A false wake is worse than
    a missed one: it hijacks an unrelated conversation."""
    assert ar.match_agent(text, AGENTS) is None


def test_the_first_name_said_wins():
    """Two names in one sentence means the first is being addressed."""
    assert ar.match_agent("mia and ada are both here", AGENTS)["name"] == "Mia"
    assert ar.match_agent("ada and mia are both here", AGENTS)["name"] == "Ada"


def test_an_unknown_name_matches_nothing():
    assert ar.match_agent("hi scout", AGENTS) is None


@pytest.mark.parametrize("agents", [
    [], None, ["not a dict"], [{"id": "x"}], [{"name": ""}], [{"name": "   "}],
])
def test_a_malformed_agent_list_never_raises(agents):
    """This list comes from a model listing over HTTP, so the shape cannot be
    trusted. A crash here takes down every message in the chat."""
    assert ar.match_agent("hi mia", agents) is None


# --- sending the agent back to sleep --------------------------------------

@pytest.mark.parametrize("text", [
    "stop", "Stop", "  STOP  ", "stop using that", "never mind", "nevermind",
    "back to normal", "no agent",
])
def test_a_release_phrase_is_recognised(text):
    assert ar.wants_release(text) is True


@pytest.mark.parametrize("text", [
    "stop the server please",
    "can you stop it from failing",
    "never mind the details, keep going",
    "what should I stop doing",
    "",
])
def test_an_ordinary_sentence_does_not_release(text):
    """Matched on the WHOLE message. Somebody mid-conversation who writes
    "stop the server" must not lose the agent they are talking to."""
    assert ar.wants_release(text) is False


# --- reading the message ---------------------------------------------------

def test_the_last_user_message_is_what_gets_matched():
    msgs = [
        {"role": "user", "content": "hi ada"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "now hi mia"},
    ]
    assert ar.last_user_text(msgs) == "now hi mia"


@pytest.mark.parametrize("msgs", [
    [], None, [{"role": "assistant", "content": "x"}],
    [{"role": "user"}], [{"role": "user", "content": None}],
    [{"role": "user", "content": ["not", "a", "string"]}], ["not a dict"],
])
def test_reading_the_message_never_raises(msgs):
    assert ar.last_user_text(msgs) == ""


def test_no_dashes_in_the_release_vocabulary():
    for p in ar.RELEASE_PHRASES:
        assert "\u2014" not in p and "\u2013" not in p
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_routing.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_routing'`

- [ ] **Step 3: Write the implementation**

Create `mcp-servers/tasks/agent_routing.py`:

```python
"""Which of a person's agents they are speaking to.

Ported from the channel gateway's agent_router, which has matched names in
Discord and Telegram for weeks. The rule is a whole-word, case-insensitive
match on the agent's name anywhere in the sentence, because people write
"hi mia, are you there" rather than an @mention. That is also why an agent's
name has to be one word: a name with a space in it is not something anybody
says mid sentence and cannot be found in free text reliably.

The failure that matters is the false positive. Waking an agent nobody asked
for hijacks the conversation and costs a model call, and it happens silently.
Missing a wake just means the person says the name again.
"""
import re

#: Said to send the current agent back to sleep. Matched against the WHOLE
#: message, lower-cased and stripped, never as a substring: somebody who
#: writes "stop the server from crashing" is not dismissing their agent.
RELEASE_PHRASES = frozenset({
    "stop", "stop it", "stop using that", "stop using it",
    "never mind", "nevermind", "back to normal", "go back to normal",
    "no agent", "plain chat", "release", "dismiss",
})


def wants_release(text: str) -> bool:
    """True when the whole message is a request to release the agent."""
    return (text or "").strip().lower().rstrip(".!") in RELEASE_PHRASES


def match_agent(text: str, agents) -> dict | None:
    """The agent whose name is spoken, or None.

    Word boundaries are hand rolled rather than \\b so that an agent called
    "Ada" is not summoned by "adapt" and one called "Mia" is not summoned by
    "Miami". When two names appear, the one said first wins, because that is
    the one being addressed.

    Never raises. The agent list arrives from a model listing over HTTP, so a
    wrong shape is expected rather than exceptional, and an exception here
    would take down every message in the chat.
    """
    hay = text or ""
    best = None
    for a in agents or []:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            continue
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])",
                      hay, re.IGNORECASE)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), a)
    return best[1] if best else None


def last_user_text(messages) -> str:
    """The most recent thing the person actually typed.

    Reads backwards rather than taking messages[-1], because a tool result or
    an assistant turn can be last.
    """
    for m in reversed(messages or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
    return ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_routing.py -q -p no:cacheprovider`
Expected: PASS, 35+ tests

- [ ] **Step 5: Prove the boundary test bites**

The false-positive guard is the whole point of this module. Temporarily replace the `re.search(...)` pattern with a plain `name.lower() in hay.lower()`, run the suite, and confirm `test_a_name_inside_another_word_is_not_a_mention` FAILS. Restore it and confirm green. Paste both outputs in your report. A boundary test that passes against substring matching is worthless.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_routing.py mcp-servers/tasks/tests/test_agent_routing.py
git commit -m "feat(agents): work out which agent is being spoken to"
```

---

### Task 2: The chat endpoint that wakes an agent

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_endpoint.py`

**Interfaces:**
- Consumes: `agent_routing.match_agent`, `agent_routing.wants_release`, `agent_routing.last_user_text` (Task 1); `_resolve_agent`, `_pending_payload`, `_run_turn` (below); `agent_runner._list_agents`, `_owui_user_id_for`, `CHAT_TOKEN_TTL_SECONDS`; `owui_token.mint_owui_token`; `models.BotState`; `db.session`.
- Produces: `POST /agents/chat` returning `{"agent": {"id","name"} | None, "answer": str | None, "notes": list[str]}` or `{"agent": {...}, "pending": {...}}`. Module members `PIN_TTL_SECONDS`, `_pin_key(chat_id)`, `_read_pin`, `_write_pin`, `_clear_pin`, `_run_turn`, `ChatIn`.

- [ ] **Step 1: Extract the turn runner so two endpoints can share it**

`turn()` currently inlines the activity recording and the `_chat` call. Pull that body into a helper, leaving `turn()` a thin wrapper. In `mcp-servers/tasks/routes_agent_turn.py`, add above `@router.post("/turn")`:

```python
async def _run_turn(user_email: str, agent_id: str,
                    messages: list[dict]) -> dict:
    """Run one turn as this user's agent, tools and all.

    Split out of the endpoint so /agents/chat can reuse it without going back
    out over HTTP to ourselves. Returns the same two shapes the endpoint does.
    """
    token, tools, level = await _resolve_agent(user_email, agent_id)
    mode = agent_access.effective_mode(level, None, agent_access.SURFACE_CHANNEL)

    run_id = await agent_activity.start_run(
        agent_id, user_email, agent_activity.SOURCE_CHANNEL)
    outcome = "failed"
    try:
        answer, notes = await _chat(
            token=token, model=agent_id, messages=messages,
            tool_ids=tools or None, user_email=user_email,
            tool_mode=mode,
            refusal_reason=agent_access.refusal_reason(
                level, None, agent_access.SURFACE_CHANNEL),
            max_iterations=CHANNEL_MAX_TOOL_ITERATIONS,
            timeout=CHANNEL_HTTP_TIMEOUT_SECONDS)
        outcome = "completed"
        return {"answer": answer, "notes": notes}
    except agent_access.ApprovalRequired as err:
        outcome = STATUS_WAITING
        return _pending_payload(user_email, agent_id, err)
    finally:
        await agent_activity.finish_run(run_id, outcome)
```

and replace the body of `turn()` with:

```python
@router.post("/turn")
async def turn(body: TurnIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Run one turn as this user's agent, tools and all."""
    _require_internal(x_internal_secret)
    return await _run_turn(body.user_email, body.agent_id, body.messages)
```

Run `cd mcp-servers/tasks && python -m pytest tests/test_agent_turn_endpoint.py tests/test_agent_turn_resume.py -q -p no:cacheprovider` and confirm the existing tests still pass unchanged. They must, because the behaviour is identical; if any fails you have changed something you should not have.

- [ ] **Step 2: Write the failing test**

Create `mcp-servers/tasks/tests/test_agent_chat_endpoint.py`:

```python
"""The web chat asking who should answer.

The pipe holds no routing logic; it sends the conversation here and this
decides. That keeps one implementation serving Discord, Telegram and the web
chat, and it means the web chat runs OUR tool loop, so the per-agent access
levels apply there.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import routes_agent_turn as rt

ADA = {"id": "agent-a", "name": "Ada", "meta": {"toolIds": ["gmail"]}}
MIA = {"id": "agent-m", "name": "Mia", "meta": {"toolIds": []}}


def _body(text, chat_id="chat-1", email="owner@example.com"):
    class B:
        user_email = email
        messages = [{"role": "user", "content": text}]
    b = B()
    b.chat_id = chat_id
    return b


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(rt, "_require_internal", lambda s: None)
    monkeypatch.setattr(rt, "_owui_user_id_for", AsyncMock(return_value="u1"))
    monkeypatch.setattr(rt, "mint_owui_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rt, "_list_agents",
                        AsyncMock(return_value=([ADA, MIA], False)))
    monkeypatch.setattr(rt, "_run_turn",
                        AsyncMock(return_value={"answer": "hi", "notes": []}))
    pins = {}
    monkeypatch.setattr(rt, "_read_pin", AsyncMock(side_effect=lambda k: pins.get(k)))
    monkeypatch.setattr(rt, "_write_pin",
                        AsyncMock(side_effect=lambda k, v: pins.__setitem__(k, v)))
    monkeypatch.setattr(rt, "_clear_pin", AsyncMock(side_effect=lambda k: pins.pop(k, None)))
    return pins


async def test_naming_an_agent_wakes_it(_wire):
    out = await rt.chat(_body("hi mia how are you"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia"
    assert out["answer"] == "hi"
    rt._run_turn.assert_awaited_once()
    assert rt._run_turn.await_args.args[1] == "agent-m"


async def test_naming_nobody_leaves_it_to_the_gateway(_wire):
    """IO answers for itself. The pipe needs to know that, so agent is None
    and no turn is run."""
    out = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert out["agent"] is None
    assert out["answer"] is None
    rt._run_turn.assert_not_awaited()


async def test_a_woken_agent_stays_awake_for_the_next_message(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("and what about tomorrow"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia", "the pin did not hold"
    assert rt._run_turn.await_count == 2


async def test_naming_a_different_agent_switches_rather_than_stacking(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("actually ada, you take this"), x_internal_secret="s")
    assert out["agent"]["name"] == "Ada"
    again = await rt.chat(_body("carry on"), x_internal_secret="s")
    assert again["agent"]["name"] == "Ada", "the switch did not stick"


async def test_a_release_phrase_sends_the_agent_back_to_sleep(_wire):
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    out = await rt.chat(_body("stop"), x_internal_secret="s")
    assert out["agent"] is None
    after = await rt.chat(_body("what is the weather"), x_internal_secret="s")
    assert after["agent"] is None, "the agent woke back up on its own"


async def test_the_pin_is_per_chat(_wire):
    """Two conversations must not share an agent."""
    await rt.chat(_body("hi mia", chat_id="chat-1"), x_internal_secret="s")
    out = await rt.chat(_body("carry on", chat_id="chat-2"), x_internal_secret="s")
    assert out["agent"] is None


async def test_a_pinned_agent_that_was_deleted_does_not_wedge_the_chat(_wire,
                                                                      monkeypatch):
    """The agent can be deleted between messages. Failing closed to "no agent"
    keeps the person chatting instead of erroring on every message."""
    await rt.chat(_body("hi mia"), x_internal_secret="s")
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([ADA], False)))
    out = await rt.chat(_body("carry on"), x_internal_secret="s")
    assert out["agent"] is None
    assert out["answer"] is None


async def test_a_truncated_listing_does_not_wake_the_wrong_agent(_wire,
                                                                 monkeypatch):
    """"Not in what we fetched" is not "does not exist". Matching against a
    partial list could pick a different agent with a similar name."""
    monkeypatch.setattr(rt, "_list_agents", AsyncMock(return_value=([], True)))
    out = await rt.chat(_body("hi mia"), x_internal_secret="s")
    assert out["agent"] is None


async def test_a_pending_approval_is_passed_through(_wire, monkeypatch):
    monkeypatch.setattr(rt, "_run_turn", AsyncMock(
        return_value={"pending": {"calls": [{"id": "c1"}]}}))
    out = await rt.chat(_body("mia send that email"), x_internal_secret="s")
    assert out["agent"]["name"] == "Mia"
    assert out["pending"]["calls"][0]["id"] == "c1"


async def test_the_internal_secret_is_required(monkeypatch):
    def deny(secret):
        raise HTTPException(status_code=403, detail="invalid internal secret")

    monkeypatch.setattr(rt, "_require_internal", deny)
    with pytest.raises(HTTPException) as caught:
        await rt.chat(_body("hi mia"), x_internal_secret="wrong")
    assert caught.value.status_code == 403
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_chat_endpoint.py -q -p no:cacheprovider`
Expected: FAIL with `AttributeError: module 'routes_agent_turn' has no attribute 'chat'`

- [ ] **Step 4: Implement**

Add to the imports at the top of `mcp-servers/tasks/routes_agent_turn.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import agent_routing
from db import session
from models import BotState
```

Append to the module:

```python
#: A woken agent stays awake for a week of chatting unless released. Long
#: because a pin is a preference, not a lock: the cost of it lasting too long
#: is one "stop", and the cost of it expiring mid-conversation is somebody
#: wondering why their agent stopped answering.
PIN_TTL_SECONDS = 60 * 60 * 24 * 7


class ChatIn(BaseModel):
    user_email: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    messages: list[dict]


def _pin_key(chat_id: str) -> str:
    return "agentpin:web:%s" % chat_id


async def _read_pin(key: str) -> str | None:
    """The pinned agent id for this chat, or None. Never raises.

    Fails open the way the channel pin does: a state outage must not stop
    somebody chatting, and the cost of a missed pin is that they say the name
    again.
    """
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
            return None
        value = row.value
        return value.get("agent_id") if isinstance(value, dict) else None
    except Exception:                                       # noqa: BLE001
        logger.warning("could not read the agent pin", exc_info=True)
        return None


async def _write_pin(key: str, agent_id: str) -> None:
    """Remember which agent is awake. Never raises."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=PIN_TTL_SECONDS)
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                row.value = {"agent_id": agent_id}
                row.updated_at = datetime.now(timezone.utc)
                row.expires_at = expires
            else:
                s.add(BotState(state_key=key, value={"agent_id": agent_id},
                               updated_at=datetime.now(timezone.utc),
                               expires_at=expires))
            await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not write the agent pin", exc_info=True)


async def _clear_pin(key: str) -> None:
    """Send the agent back to sleep. Never raises."""
    try:
        async with session() as s:
            row = (await s.execute(
                select(BotState).where(BotState.state_key == key)
            )).scalar_one_or_none()
            if row:
                await s.delete(row)
                await s.commit()
    except Exception:                                       # noqa: BLE001
        logger.warning("could not clear the agent pin", exc_info=True)


async def _agents_for(user_email: str) -> list[dict]:
    """This person's own agents, or an empty list.

    Empty on ANY doubt, including a listing that was cut short: matching a
    name against a partial list could wake a different agent whose name
    happens to be similar, and waking the wrong agent is worse than waking
    none.
    """
    try:
        owner = await _owui_user_id_for(user_email)
        if not owner:
            return []
        token = mint_owui_token(owner, ttl_seconds=CHAT_TOKEN_TTL_SECONDS)
        agents, truncated = await _list_agents(token)
        if truncated:
            return []
        return [a for a in agents if isinstance(a, dict) and a.get("id")]
    except Exception:                                       # noqa: BLE001
        logger.warning("could not list agents for routing", exc_info=True)
        return []


@router.post("/chat")
async def chat(body: ChatIn,
               x_internal_secret: str = Header(default="")) -> dict:
    """Who should answer this message, and their answer if it is an agent.

    Returns agent=None when nobody was named and nobody is pinned, which is
    the caller's cue to answer as itself. The caller holds no routing logic so
    that Discord, Telegram and the web chat all decide this the same way.
    """
    _require_internal(x_internal_secret)
    key = _pin_key(body.chat_id)
    text = agent_routing.last_user_text(body.messages)

    if agent_routing.wants_release(text):
        await _clear_pin(key)
        return {"agent": None, "answer": None, "notes": []}

    agents = await _agents_for(body.user_email)
    named = agent_routing.match_agent(text, agents)

    if named:
        # Naming a different agent switches rather than stacking: one agent is
        # awake at a time, so "actually ada, you take this" hands over cleanly.
        await _write_pin(key, named["id"])
        agent = named
    else:
        pinned_id = await _read_pin(key)
        agent = next((a for a in agents if a.get("id") == pinned_id), None)
        if pinned_id and agent is None:
            # Deleted, or renamed out from under the pin. Fail closed to no
            # agent rather than erroring on every message from here on.
            await _clear_pin(key)

    if agent is None:
        return {"agent": None, "answer": None, "notes": []}

    out = await _run_turn(body.user_email, agent["id"], body.messages)
    out["agent"] = {"id": agent["id"], "name": agent.get("name") or agent["id"]}
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_chat_endpoint.py tests/test_agent_turn_endpoint.py tests/test_agent_turn_resume.py tests/test_agent_routing.py -q -p no:cacheprovider`
Expected: PASS, no failures.

- [ ] **Step 6: Confirm the route is mounted once, internal only**

The router this lives on is deliberately mounted a single time, unlike `agents_router` which is also mounted under the public `/api/tasks` prefix.

Run:
```bash
cd mcp-servers/tasks && python -c "
from main import app
paths = sorted({r.path for r in app.routes if getattr(r,'path','') and 'turn' in getattr(r,'path','') or getattr(r,'path','') == '/agents/chat'})
print(paths)
assert '/agents/chat' in paths and '/api/tasks/agents/chat' not in paths
print('mounted once, internal path only')
"
```
Expected: `mounted once, internal path only`

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_agent_chat_endpoint.py
git commit -m "feat(agents): decide who answers a web chat message"
```

---

### Task 3: The IO pipe

**Files:**
- Create: `open-webui-functions/io_gateway_pipe.py`
- Test: `mcp-servers/tasks/tests/test_io_gateway_pipe.py`

**Interfaces:**
- Consumes: `POST /agents/chat` (Task 2).
- Produces: an Open WebUI Pipe class exposing one model, id `io`, name `IO`. Module members `Pipe`, `Pipe.Valves`, `Pipe.pipes()`, `Pipe.pipe(body, __user__, __event_emitter__)`.

The test file lives under `mcp-servers/tasks/tests/` because that is where this repo's pytest configuration lives; the pipe file itself is installed into Open WebUI, not imported by the tasks service.

- [ ] **Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_io_gateway_pipe.py`:

```python
"""The one model in the dropdown that decides who answers.

The pipe holds no routing logic. Everything here is about the seam: it must
ask the tasks service, deliver whatever comes back, and never leave somebody
staring at silence when that call fails.
"""
import importlib.util
import os
from unittest.mock import AsyncMock

import pytest

PIPE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "open-webui-functions", "io_gateway_pipe.py")


def _load():
    spec = importlib.util.spec_from_file_location("io_gateway_pipe", PIPE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def test_it_offers_exactly_one_model_called_io(mod):
    pipes = mod.Pipe().pipes()
    assert len(pipes) == 1
    assert pipes[0]["id"] == "io"
    assert pipes[0]["name"] == "IO"


async def test_an_agents_answer_is_delivered_with_its_name(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "agent-m", "name": "Mia"},
        "answer": "Four unread.", "notes": []}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}],
                        "stream": False},
                       __user__={"email": "owner@example.com"})

    assert "Four unread." in out
    assert "Mia" in out, "the person cannot tell who answered"


async def test_notes_ride_along_with_the_answer(mod, monkeypatch):
    """A refused write that nobody is told about is the worst outcome: the
    person believes it happened."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "a", "name": "Mia"}, "answer": "Here is the draft.",
        "notes": ["Declined to run send_email, because this agent is set to read only."]}))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert "Declined to run send_email" in out


async def test_a_pending_approval_is_shown_as_a_question(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": {"id": "a", "name": "Mia"},
        "pending": {"calls": [{"id": "c1", "function": {
            "name": "send_message",
            "arguments": '{"to": "ralph@example.com"}'}}]}}))

    out = await p.pipe({"messages": [{"role": "user", "content": "mia send it"}]},
                       __user__={"email": "o@e.com"})
    assert "send_message" in out
    assert "ralph@example.com" in out
    assert "yes" in out.lower()


async def test_no_agent_named_falls_through_to_the_base_model(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "agent": None, "answer": None, "notes": []}))
    monkeypatch.setattr(p, "_answer_as_io", AsyncMock(return_value="I can help."))

    out = await p.pipe({"messages": [{"role": "user", "content": "what is the weather"}]},
                       __user__={"email": "o@e.com"})

    assert out == "I can help."
    p._answer_as_io.assert_awaited_once()


async def test_a_tasks_failure_still_says_something(mod, monkeypatch):
    """Somebody is watching this chat. Silence is the one unacceptable
    outcome."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(side_effect=RuntimeError("down")))

    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}]},
                       __user__={"email": "o@e.com"})
    assert isinstance(out, str) and out.strip()


async def test_a_missing_user_is_reported_not_guessed(mod):
    """Acting without knowing whose account it is would run an agent as the
    wrong person."""
    p = mod.Pipe()
    out = await p.pipe({"messages": [{"role": "user", "content": "hi"}]},
                       __user__=None)
    assert isinstance(out, str) and out.strip()


async def test_an_empty_conversation_is_answered_not_crashed(mod):
    p = mod.Pipe()
    out = await p.pipe({"messages": []}, __user__={"email": "o@e.com"})
    assert isinstance(out, str) and out.strip()


def test_the_secret_is_never_put_in_a_reply(mod):
    """This project has already leaked a token through a client that logged a
    request URL."""
    src = open(PIPE_PATH, encoding="utf-8").read()
    assert "INTERNAL_CALLBACK_SECRET" in src
    for bad in ["print(", "logger.info(secret", "f\"{secret}"]:
        assert bad not in src, bad


def test_no_dashes_in_the_pipe_copy(mod):
    src = open(PIPE_PATH, encoding="utf-8").read()
    assert "\u2014" not in src and "\u2013" not in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_io_gateway_pipe.py -q -p no:cacheprovider`
Expected: FAIL, the pipe file does not exist.

- [ ] **Step 3: Write the pipe**

Create `open-webui-functions/io_gateway_pipe.py`:

```python
"""
title: IO
id: io
description: Talks to you, and wakes one of your agents when you name it.
author: Ralph Benitez
version: 1.0.0
requirements: httpx
"""
# The gateway model. Say "hi mia" and Mia answers; say nothing in particular
# and IO answers.
#
# It holds NO routing logic on purpose. The tasks service decides who should
# answer, which keeps one implementation serving Discord, Telegram and this
# chat, and means an agent used here runs through the same tool loop as
# everywhere else. That is what makes the per-agent access levels apply in the
# web chat: Open WebUI's own loop never reaches our code, so without this an
# agent set to Read only would still write.
import json
import os
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, Field

TASKS_URL = os.environ.get("TASKS_URL", "http://tasks:8210")
INTERNAL_SECRET = os.environ.get("INTERNAL_CALLBACK_SECRET", "")
OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://open-webui:8080")

#: Long enough for three rounds of tool use plus the tool calls themselves,
#: matching the channel budget in agent_runner. A timeout here reads to the
#: person as the model ignoring them.
TIMEOUT_SECONDS = 420.0

NO_USER = ("I could not tell whose account this is, so I did not run anything. "
           "Sign out and back in, and try again.")
TASKS_DOWN = ("I could not reach my memory just now, so I could not check your "
              "agents. Try again in a moment.")
EMPTY = "There was nothing to answer."

#: One argument value in an approval question. Enough to recognise a
#: recipient or a subject, not enough for a message body to bury the question.
MAX_ARG_CHARS = 120
MAX_ARGS_SHOWN = 5


class Pipe:
    class Valves(BaseModel):
        TASKS_URL: str = Field(
            default=TASKS_URL, description="Base URL of the tasks service.")
        INTERNAL_SECRET: str = Field(
            default=INTERNAL_SECRET,
            description="Shared secret for the tasks service. Read from env.")
        BASE_MODEL: str = Field(
            default="gpt-4o-mini",
            description="The model IO answers with when no agent was named.")
        SHOW_AGENT_NAME: bool = Field(
            default=True,
            description="Prefix an agent's answer with its name.")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "io", "name": "IO"}]

    # --- talking to the tasks service -------------------------------------

    async def _ask_tasks(self, user_email: str, chat_id: str,
                         messages: list) -> dict:
        """Who should answer, and their answer if it is an agent."""
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            r = await client.post(
                self.valves.TASKS_URL.rstrip("/") + "/agents/chat",
                headers={"X-Internal-Secret": self.valves.INTERNAL_SECRET},
                json={"user_email": user_email, "chat_id": chat_id,
                      "messages": messages})
            r.raise_for_status()
            return r.json()

    async def _answer_as_io(self, body: dict, user_email: str) -> str:
        """IO speaking for itself, on the base model."""
        payload = {"model": self.valves.BASE_MODEL,
                   "messages": body.get("messages") or [], "stream": False}
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            r = await client.post(
                OPENWEBUI_URL.rstrip("/") + "/api/chat/completions",
                headers={"X-Internal-Secret": self.valves.INTERNAL_SECRET},
                json=payload)
            r.raise_for_status()
            data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return EMPTY
        return (choices[0].get("message") or {}).get("content") or EMPTY

    # --- rendering ---------------------------------------------------------

    def _approval_question(self, agent_name: str, calls: list) -> str:
        """What the agent wants to do, in its own terms.

        The tool's own name and arguments, not a hand written phrase per tool.
        A phrasebook covering 300+ tools would be wrong somewhere, and where it
        was wrong is exactly where somebody would approve the wrong thing.
        """
        lines = ["%s wants to run:" % (agent_name or "This agent")]
        for call in calls or []:
            call = call if isinstance(call, dict) else {}
            fn = call.get("function")
            fn = fn if isinstance(fn, dict) else {}
            name = fn.get("name")
            name = name.strip() if isinstance(name, str) and name.strip() else "an unnamed tool"
            lines.append("  " + name)
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except (ValueError, TypeError):
                args = {}
            if isinstance(args, dict):
                for k, v in list(args.items())[:MAX_ARGS_SHOWN]:
                    lines.append("     %s: %s" % (k, str(v)[:MAX_ARG_CHARS]))
        if len(lines) == 1:
            lines.append("  something it did not name")
        lines.append("")
        lines.append("Reply yes to let it, or no to skip.")
        return "\n".join(lines)

    def _render(self, out: dict) -> str:
        agent = out.get("agent") or {}
        name = agent.get("name") or agent.get("id") or "Agent"

        pending = out.get("pending")
        if isinstance(pending, dict) and pending.get("calls"):
            return self._approval_question(name, pending["calls"])

        answer = (out.get("answer") or "").strip()
        notes = [n for n in (out.get("notes") or []) if isinstance(n, str)]
        if notes:
            note_text = "\n".join(notes)
            answer = (answer + "\n\n" + note_text) if answer else note_text
        answer = answer or EMPTY
        if self.valves.SHOW_AGENT_NAME:
            return "%s:\n%s" % (name, answer)
        return answer

    # --- the entry point ---------------------------------------------------

    async def pipe(self, body: dict, __user__: dict = None,
                   __event_emitter__: Optional[Callable[[dict], Any]] = None):
        """One message in, one answer out.

        Every exit returns a sentence. Somebody is watching this chat, so a
        silent failure is the one outcome that is never acceptable.
        """
        user_email = (__user__ or {}).get("email") or ""
        if not user_email:
            return NO_USER
        if not (body.get("messages") or []):
            return EMPTY

        chat_id = (body.get("chat_id")
                   or (body.get("metadata") or {}).get("chat_id")
                   or "web")

        try:
            out = await self._ask_tasks(user_email, chat_id,
                                        body.get("messages") or [])
        except Exception:                                   # noqa: BLE001
            # Never include the exception text: an httpx error can carry the
            # request URL, and this project has already leaked a token that way.
            return TASKS_DOWN

        if not out.get("agent"):
            try:
                return await self._answer_as_io(body, user_email)
            except Exception:                               # noqa: BLE001
                return TASKS_DOWN

        return self._render(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_io_gateway_pipe.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Run the whole agent test set for regressions**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_routing.py tests/test_agent_chat_endpoint.py tests/test_agent_turn_endpoint.py tests/test_agent_turn_resume.py tests/test_agent_access.py tests/test_agent_tool_loop.py tests/test_agent_runner.py tests/test_io_gateway_pipe.py -q -p no:cacheprovider`
Expected: PASS, no failures.

- [ ] **Step 6: Commit**

```bash
git add open-webui-functions/io_gateway_pipe.py mcp-servers/tasks/tests/test_io_gateway_pipe.py
git commit -m "feat(chat): one model that answers you and wakes your agents"
```

---

### Task 4: Install, deploy, and prove it on the server

**Files:**
- No source changes. This task is deployment and verification.

**Interfaces:**
- Consumes: everything above.

`CLAUDE.md` is explicit that wiring inside a function body is not caught by an import or a unit test, and this pipeline has been bitten by exactly that twice. Nothing here is optional.

- [ ] **Step 1: Confirm the tree is clean and the suites pass**

```bash
cd "C:/All/Work - Code/ai_ui"
git status --short | grep -v "^?? apps/" | grep -v "^?? _aiui_demo" | grep -v "^?? .superpowers"
cd mcp-servers/tasks && python -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -3
```
Expected: no unexpected modified files; the suite at or above **2964 passed, 70 skipped, 147 errors** (the 147 are the known `db_session` setup failures from having no local Postgres). Do not proceed if the error count exceeds 147.

- [ ] **Step 2: Deploy the tasks service**

`rsync` is absent from Git Bash on Windows, so the orchestrator will not run. Copy one file per `scp` (`scp -r` silently skips files), then normalise line endings, then verify by hash before rebuilding:

```bash
cd "C:/All/Work - Code/ai_ui"
for f in mcp-servers/tasks/agent_routing.py mcp-servers/tasks/routes_agent_turn.py; do
  scp -o ConnectTimeout=25 "$f" "root@46.224.193.25:/root/proxy-server/$f"
done
ssh root@46.224.193.25 "cd /root/proxy-server/mcp-servers/tasks && sed -i 's/\r\$//' agent_routing.py routes_agent_turn.py"
```

Then compare `sed 's/\r$//' <file> | md5sum` locally against `md5sum <file>` on the server for both files. They must match before you rebuild. If `scp` fails while `ssh` works (this happened for 30 minutes on 2026-08-28), base64 the file and echo it over ssh, verifying the byte count.

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 3: Verify tasks came back up with the new endpoint**

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "docker exec tasks python -c \"import agent_routing, routes_agent_turn; print('modules OK')\""
```
Expected: `{"status":"ok"}` and `modules OK`.

- [ ] **Step 4: Prove the new endpoint is not reachable from the internet**

```bash
for p in "/tasks/agents/chat" "/api/tasks/agents/chat" "/agents/chat"; do
  printf "%s -> " "$p"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 20 -X POST "https://ai-ui.coolestdomain.win$p" \
    -H "Content-Type: application/json" \
    -d '{"user_email":"x@y.com","chat_id":"c","messages":[]}'
done
```
Expected: 403, 404 or 405 for every one. Anything that routes an agent is a hole; stop and fix it before continuing.

Then confirm it rejects an unauthenticated internal call:
```bash
ssh root@46.224.193.25 "docker exec api-gateway sh -lc 'curl -s -o /dev/null -w \"%{http_code}\n\" --max-time 10 -X POST http://tasks:8210/agents/chat -H \"Content-Type: application/json\" -d \"{}\"'"
```
Expected: `403`.

- [ ] **Step 5: Exercise the endpoint with the real secret**

Run inside the container so the secret never leaves it:
```bash
ssh root@46.224.193.25 "docker exec tasks python -c \"
import os, httpx
sec = os.environ.get('INTERNAL_CALLBACK_SECRET','')
def ask(text, chat='verify-1'):
    r = httpx.post('http://localhost:8210/agents/chat',
        json={'user_email':'ralphbenitez32@gmail.com','chat_id':chat,
              'messages':[{'role':'user','content':text}]},
        headers={'X-Internal-Secret': sec}, timeout=300)
    d = r.json()
    a = d.get('agent')
    print(repr(text), '->', r.status_code, '| agent:', a and a.get('name'))
    return d
ask('what is the weather today')
ask('hi ada, reply with exactly PONG')
ask('and what about tomorrow')
ask('stop')
ask('carry on then')
\""
```
Expected, in order: `agent: None`; `agent: Ada`; `agent: Ada` (the pin held); `agent: None` (released); `agent: None` (it stayed asleep).

- [ ] **Step 6: Install the pipe in Open WebUI**

The pipe is a function, not a file the container reads from disk. Install it through the admin UI:

1. Open `https://ai-ui.coolestdomain.win/admin/functions`
2. Click **+**, paste the contents of `open-webui-functions/io_gateway_pipe.py`, save.
3. Confirm it appears **enabled**, and that a model called **IO** now shows in the chat model dropdown.

Then verify it registered:
```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui -t -c \"SELECT id, name, is_active FROM public.function WHERE id LIKE '%io%';\""
```
Expected: a row with `is_active = t`.

- [ ] **Step 7: Use it in a real browser**

Select **IO** in the model dropdown and check each of these:

1. "what is the weather" answers as IO, no agent name prefix.
2. "hi ada" wakes Ada, and the answer is prefixed with her name.
3. A follow-up with no name still comes from Ada.
4. "actually mia, you take this" switches to Mia and stays there.
5. "stop" releases, and the next message is answered by IO.
6. "can you adapt this design" does **not** wake Ada. This is the false positive that would make the feature intolerable, and it is the one thing a unit test cannot prove about the real name set.

- [ ] **Step 8: Confirm the access levels now apply in the web chat**

This is the gap this task closes, so prove it rather than assume it.

1. On the Agents page set Ada to **Read only**.
2. In the web chat with IO: "ada, send a test email to me". Expected: a refusal that names the agent and does **not** contain the word "schedule".
3. Set Ada to **With access** and ask again. Expected: the approval question naming the tool and its arguments.
4. Check the Agents page: Ada's card should show a recent run, because a web chat turn is now recorded like a channel one.

- [ ] **Step 9: Remove the line the modal no longer needs**

`agents.html` currently says "Web chat here always has full access." Once step 8 passes, that sentence is false. Update both hint states to say the setting applies everywhere, redeploy `agents.html` with one `scp` and a `sed -i 's/\r$//'`, rebuild tasks, and confirm the page serves the new wording. Update `tests/test_agents_page_access.py`, which asserts the old sentence.

- [ ] **Step 10: Stamp the deploy state and commit**

`.deploy-state` is JSON and the orchestrator parses `['sha']`; a bare SHA breaks the next deploy.

```bash
cd "C:/All/Work - Code/ai_ui" && SHA=$(git rev-parse HEAD)
ssh root@46.224.193.25 "cd /root/proxy-server && printf '%s' '{\"sha\": \"'$SHA'\", \"deployed_at\": \"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'\", \"deployed_by\": \"Ralph Benitez\"}' > .deploy-state && python3 -c \"import json;print(json.load(open('/root/proxy-server/.deploy-state'))['sha'][:9])\""
```

Note in your report that another session has deployed to this box concurrently before; check `.deploy-state` against what is actually running rather than assuming your own stamp is still current.

---

## Self-Review

**Spec coverage.** Every Phase 1 requirement maps to a task: the pipe rather than an inlet filter, with the reason (Task 3); name matching including "gisingin mo si Mia" and the boundary guard (Task 1); the pin, its release, and switching rather than stacking (Tasks 1 and 2); routing through `/agents/turn` so our tool loop runs (Task 2); recording web runs in `agent_run` (inherited from `_run_turn`, verified in Task 4 step 8); the base model in a valve defaulting so IO has one voice (Task 3); closing the access-level gap and removing the modal's admission (Task 4 steps 8 and 9).

**Naming consistency.** `_run_turn(user_email, agent_id, messages)` is defined in Task 2 step 1 and called in Task 2 step 4 and asserted in the Task 2 tests by `await_args.args[1] == "agent-m"`, which matches its second positional parameter. `_ask_tasks` and `_answer_as_io` are the two seams the Task 3 tests monkeypatch, and both are methods on `Pipe` so `monkeypatch.setattr(p, ...)` binds correctly. `agent_routing` exports exactly the three functions Task 2 imports.

**Known gap carried forward, not fixed here.** `webhook-handler/gateway/agent_router.py` keeps its own copy of the name matcher. Two copies of a behaviour-critical function can drift, and the honest fix is for the channel gateway to call `/agents/chat` too. That is a follow-up, deliberately not bundled into a plan whose job is to make the web chat work, and it is why Task 1's tests mirror the channel matcher's own cases.
