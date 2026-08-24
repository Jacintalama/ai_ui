# Agents in channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A direct message to the bot is answered by whichever of the user's agents fits, with that agent's instructions and tools, acting as that user.

**Architecture:** An agent is an Open WebUI model row, so routing to one means sending a different model id to the existing `chat_completion` call. A new module loads the caller's own agents, asks a cheap model which one fits, and validates the answer against that list. The pipeline calls it after commands and before the answer.

**Tech Stack:** Python 3, httpx, pytest (asyncio auto mode), FastAPI service `webhook-handler`.

Spec: `docs/superpowers/specs/2026-08-24-agents-in-channels-design.md`

## Global Constraints

- **Commit attribution is Ralph Benitez only.** Never add `Co-Authored-By: Claude`, "Generated with Claude Code", or any AI attribution to a commit message, PR, or file.
- **No em-dashes or en-dashes** anywhere a person reads: commit messages, comments, user-facing copy.
- **Direct messages only.** Never modify or move the `src.chat_type != "dm"` check in `pipeline.py`. The Brain is injected into every model call, so a group answer leaks private memory.
- **Every failure still answers the user.** `pipeline.py`'s docstring states the rule: nothing here may fail silently, because somebody is waiting. Any new failure path falls back to the normal model and still replies.
- **The router's answer is untrusted.** It must be validated against the caller's own candidate list before it is used as a model id.
- **The router call uses the caller's own token**, so the router model must be one every user can see. `gpt-4o-mini` has a row and a wildcard read grant, so it qualifies.
- **New code gets type hints.** Use `async`/`await` for I/O and `httpx` for HTTP, matching the existing modules.
- Tests live in `webhook-handler/tests/` and run with `cd webhook-handler && py -m pytest tests/ -q`. Python is `py` on this machine, not `python3`.
- **`webhook-handler` is NOT covered by `deploy_orchestrator.sh`.** It deploys by one `scp` per changed file, never `scp -r`, then a rebuild.

---

## Task 1: The gateway can list the caller's models

**Files:**
- Modify: `webhook-handler/gateway/owui.py`
- Test: `webhook-handler/tests/test_gateway_owui_models.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `OWUIUserClient.list_models() -> list[dict]`, returning raw rows from `/api/v1/models/list`, each with at least `id`, `name`, `meta`. Tasks 2 and 3 use it.

- [ ] **Step 1: Write the failing test**

Create `webhook-handler/tests/test_gateway_owui_models.py`:

```python
"""Listing the models the caller can see.

/api/v1/models/list is the only endpoint that keeps user_id and meta on the
row. /api/models nests the row under `info` and deletes params server side,
which is what made the Agents page show an empty list for a whole deploy. It
also pages at 30, so a user with more than 30 agents silently loses the rest
unless this pages through.
"""
import json

import httpx
import pytest

from gateway.owui import OWUIUserClient


def _client(handler) -> OWUIUserClient:
    """An OWUIUserClient whose HTTP is served by `handler`, no socket."""
    client = OWUIUserClient("https://example.test", "tok")
    transport = httpx.MockTransport(handler)

    async def _request(method, path, **kwargs):
        async with httpx.AsyncClient(transport=transport) as http:
            resp = await http.request(method, f"https://example.test{path}",
                                      **kwargs)
        if resp.status_code >= 400:
            from gateway.owui import OWUIError
            raise OWUIError(resp.status_code, resp.text[:400])
        return resp

    client._request = _request
    return client


def _row(mid: str) -> dict:
    return {"id": mid, "name": mid, "meta": {"description": "d"},
            "base_model_id": "gpt-4o-mini"}


async def test_it_returns_the_rows():
    def handler(request):
        return httpx.Response(200, json={"items": [_row("agent-a-0001")],
                                         "total": 1})

    got = await _client(handler).list_models()

    assert [m["id"] for m in got] == ["agent-a-0001"]


async def test_it_pages_until_it_has_everything():
    seen = []

    def handler(request):
        page = int(dict(request.url.params).get("page", "1"))
        seen.append(page)
        rows = [_row("agent-%02d" % i) for i in range((page - 1) * 30, page * 30)]
        rows = rows[:30] if page == 1 else rows[:5]
        return httpx.Response(200, json={"items": rows, "total": 35})

    got = await _client(handler).list_models()

    assert seen == [1, 2], "it did not ask for the second page"
    assert len(got) == 35


async def test_an_empty_page_stops_the_loop():
    """A total that never matches must not spin forever."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"items": [], "total": 999})

    got = await _client(handler).list_models()

    assert got == []
    assert len(calls) == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_owui_models.py -q`
Expected: FAIL with `AttributeError: 'OWUIUserClient' object has no attribute 'list_models'`

- [ ] **Step 3: Add the method**

In `webhook-handler/gateway/owui.py`, add to `OWUIUserClient` directly after `chat_completion`:

```python
    async def list_models(self) -> list[dict]:
        """Every derived model this user can see, which is where agents live.

        /api/v1/models/list rather than /api/models: the latter nests the row
        under `info` and deletes params server side, so the owner and the
        instructions both vanish. This one also returns ONLY models with a
        base_model_id, so the 130 base models are excluded and the list stays
        small.

        It pages at 30 on a one-indexed `page`. The guard stops a wrong `total`
        from spinning forever.
        """
        items: list[dict] = []
        page = 1
        for _ in range(25):
            resp = await self._request(
                "GET", f"/api/v1/models/list?page={page}")
            data = self._json(resp)
            batch = data.get("items") or []
            items.extend(batch)
            total = data.get("total")
            if not batch or not isinstance(total, int) or len(items) >= total:
                break
            page += 1
        return items
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_owui_models.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/owui.py webhook-handler/tests/test_gateway_owui_models.py
git commit -m "feat(gateway): list the models the caller can see

Reads /api/v1/models/list rather than /api/models, because the latter nests the
row under info and deletes params, so neither the owner nor the instructions
survive. It also returns only derived models, so agents come back without the
130 base models.

Pages through, since it returns 30 at a time. Without that, a user with more
than 30 agents would silently lose the rest."
```

---

## Task 2: Choosing an agent

**Files:**
- Create: `webhook-handler/gateway/agent_router.py`
- Test: `webhook-handler/tests/test_gateway_agent_router.py` (create)

**Interfaces:**
- Consumes: `OWUIUserClient.chat_completion(messages, model)` from Task 1's module.
- Produces, all used by Task 3 and Task 4:
  - `candidates(models: list[dict]) -> list[dict]` returning dicts with keys `id`, `name`, `description`
  - `build_messages(text: str, cands: list[dict]) -> list[dict]`
  - `validate(answer: str | None, cands: list[dict]) -> dict | None`
  - `async pick(owui, text: str, cands: list[dict], router_model: str) -> dict | None`
  - `match_pin_request(text: str, cands: list[dict]) -> dict | None`
  - `is_unpin_request(text: str) -> bool`
  - `pin_key(platform: str, chat_id: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_agent_router.py`:

```python
"""Which agent answers, and the guard rails around that choice.

The router is a model reading a short message, so it can be wrong and it can
invent an id. Everything it returns is checked against the caller's own
candidates before it becomes a model id, because an id it made up must never be
able to route a real request.
"""
from unittest.mock import AsyncMock

import pytest

from gateway import agent_router


def _model(mid, name, desc="", base="gpt-4o-mini"):
    return {"id": mid, "name": name, "base_model_id": base,
            "meta": {"description": desc, "toolIds": []}}


MODELS = [
    _model("gpt-4o-mini", "gpt-4o-mini", base=None),
    _model("agent-inbox-triage-0002", "Inbox Triage",
           "You read the user's unread email and say what needs them."),
    _model("agent-research-assistant-0001", "Research Assistant",
           "You research questions and answer with what you found."),
]
CANDS = agent_router.candidates(MODELS)


@pytest.mark.parametrize("bad", [None, "", 0, {"items": []}, object()])
def test_a_non_list_yields_no_candidates(bad):
    """The models endpoint can return something that is not a list, and a stub
    certainly can. Raising here would surface as an unexplained failure two
    layers up."""
    assert agent_router.candidates(bad) == []


def test_only_agents_are_candidates():
    """A base model is not an agent, and neither is a preset the user made in
    Open WebUI's own workspace."""
    ids = [c["id"] for c in CANDS]
    assert ids == ["agent-inbox-triage-0002", "agent-research-assistant-0001"]


def test_a_candidate_carries_its_name_and_one_line():
    c = CANDS[0]
    assert c["name"] == "Inbox Triage"
    assert "unread email" in c["description"]


def test_the_prompt_never_carries_full_instructions():
    """Instructions run to 4000 characters and this call happens on every
    message, so the prompt is names and one-liners on purpose."""
    long_agent = _model("agent-long-0003", "Long", "x" * 400)
    cands = agent_router.candidates([long_agent])
    text = "".join(m["content"] for m in agent_router.build_messages("hi", cands))
    assert len(text) < 1200
    assert "agent-long-0003" in text


def test_a_valid_answer_is_accepted():
    got = agent_router.validate("agent-inbox-triage-0002", CANDS)
    assert got["id"] == "agent-inbox-triage-0002"


@pytest.mark.parametrize("answer", [
    "agent-not-mine-9999",          # an id it invented
    "agent-inbox-triage-0002-x",    # close but not real
    "NONE",
    "",
    None,
    "I think you want Inbox Triage",
])
def test_anything_not_in_the_candidates_is_refused(answer):
    assert agent_router.validate(answer, CANDS) is None


def test_a_quoted_or_padded_id_is_still_accepted():
    """Models like to wrap an answer in quotes or a newline."""
    got = agent_router.validate('  "agent-inbox-triage-0002"  \n', CANDS)
    assert got["id"] == "agent-inbox-triage-0002"


async def test_pick_returns_the_chosen_candidate():
    owui = AsyncMock()
    owui.chat_completion.return_value = "agent-inbox-triage-0002"

    got = await agent_router.pick(owui, "check my mail", CANDS, "gpt-4o-mini")

    assert got["name"] == "Inbox Triage"


async def test_no_candidates_means_no_model_call():
    """This is the cost guard. The router would otherwise run on every message
    from every user, including users who have no agents."""
    owui = AsyncMock()

    got = await agent_router.pick(owui, "hello", [], "gpt-4o-mini")

    assert got is None
    owui.chat_completion.assert_not_called()


async def test_a_router_failure_is_not_an_error():
    """The person is waiting. A router that cannot answer must not stop them
    getting a reply."""
    owui = AsyncMock()
    owui.chat_completion.side_effect = RuntimeError("router down")

    got = await agent_router.pick(owui, "check my mail", CANDS, "gpt-4o-mini")

    assert got is None


@pytest.mark.parametrize("text,expected", [
    ("use Inbox Triage", "agent-inbox-triage-0002"),
    ("Use inbox triage", "agent-inbox-triage-0002"),
    ("switch to Research Assistant", "agent-research-assistant-0001"),
    ("talk to Inbox Triage.", "agent-inbox-triage-0002"),
])
def test_a_pin_phrase_naming_a_real_agent_pins_it(text, expected):
    got = agent_router.match_pin_request(text, CANDS)
    assert got["id"] == expected


@pytest.mark.parametrize("text", [
    "use my email to find the invoice",
    "use the research I sent you",
    "switch to a different tone",
    "can you use Inbox Triage",
    "Inbox Triage",
    "",
])
def test_an_ordinary_message_is_not_a_pin(text):
    """A message silently turning into a setting is worse than a router that
    picks wrong, so the match is deliberately narrow: the rest of the message
    must BE the agent's name."""
    assert agent_router.match_pin_request(text, CANDS) is None


@pytest.mark.parametrize("text,expected", [
    ("stop using that", True),
    ("Stop using it.", True),
    ("back to normal", True),
    ("stop using my email", False),
    ("hello", False),
])
def test_unpin_detection(text, expected):
    assert agent_router.is_unpin_request(text) is expected


def test_the_pin_key_is_per_conversation():
    a = agent_router.pin_key("telegram", "42")
    b = agent_router.pin_key("telegram", "43")
    c = agent_router.pin_key("discord", "42")
    assert a != b and a != c
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_router.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'gateway.agent_router'`

- [ ] **Step 3: Write the module**

Create `webhook-handler/gateway/agent_router.py`:

```python
"""Which of the caller's agents should answer this message.

An agent is an Open WebUI model row, so "routing to an agent" is choosing a
different model id. The hard part is not the routing, it is that the thing
choosing is a model reading a short message: it can be wrong, and it can invent
an id. So everything it returns is checked against the caller's own candidate
list before it is used.

Candidates are always built from a list fetched with the CALLER's token, so an
agent belonging to somebody else is never in scope to begin with.
"""
import logging

log = logging.getLogger(__name__)

AGENT_PREFIX = "agent-"

#: A prompt sent on every message has to stay small, so the list is capped and
#: each line is a name and a one-liner rather than the agent's instructions.
MAX_CANDIDATES = 20
MAX_DESCRIPTION = 120
MAX_TEXT = 500

PIN_VERBS = ("use ", "switch to ", "talk to ")
UNPIN_PHRASES = (
    "stop using that", "stop using it", "stop using this",
    "back to normal", "use normal", "no agent",
)


def candidates(models: list[dict]) -> list[dict]:
    """The agents in a model list, as {id, name, description}.

    Filters on the id prefix, the same test the Agents page uses. Open WebUI's
    own workspace can create derived models that are not agents, and those have
    no business being routed to.
    """
    # Not just a convenience. Callers hand this whatever the models endpoint
    # returned, and a stub or a proxy error page can make that something that
    # is not a list. Iterating it would raise from inside a helper that is
    # supposed to be pure, and surface as an unexplained failure.
    if not isinstance(models, list):
        return []

    out: list[dict] = []
    for m in models:
        mid = m.get("id") or ""
        if not mid.startswith(AGENT_PREFIX):
            continue
        meta = m.get("meta") or {}
        out.append({
            "id": mid,
            "name": (m.get("name") or mid)[:60],
            "description": (meta.get("description") or "")[:MAX_DESCRIPTION],
        })
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def build_messages(text: str, cands: list[dict]) -> list[dict]:
    listing = "\n".join(
        "%s | %s | %s" % (c["id"], c["name"], c["description"]) for c in cands)
    system = (
        "You route a message to the assistant that fits it best.\n"
        "Each line is: id | name | what it does.\n\n"
        + listing
        + "\n\nReply with exactly one id from that list, or the single word "
          "NONE if none of them clearly fits. Reply with nothing else."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": (text or "")[:MAX_TEXT]}]


def validate(answer: str | None, cands: list[dict]) -> dict | None:
    """The candidate the router named, or None.

    Untrusted input. A model can return an id that does not exist, or one
    belonging to another user, and either would route a real request somewhere
    it must not go.
    """
    by_id = {c["id"]: c for c in cands}
    for line in (answer or "").splitlines():
        cleaned = line.strip().strip('"\'`').strip()
        if not cleaned:
            continue
        return by_id.get(cleaned)
    return None


async def pick(owui, text: str, cands: list[dict],
               router_model: str) -> dict | None:
    """Ask which agent fits. Returns the candidate, or None to answer normally.

    Never raises. The person is waiting for an answer, and a router that cannot
    make up its mind must not be able to stop them getting one.
    """
    if not cands:
        return None
    try:
        answer = await owui.chat_completion(
            build_messages(text, cands), router_model)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: agent router did not answer, using the default "
                    "model", exc_info=True)
        return None
    return validate(answer, cands)


def _normalise(text: str) -> str:
    return (text or "").strip().rstrip(".!").strip().lower()


def match_pin_request(text: str, cands: list[dict]) -> dict | None:
    """The agent this message asks to switch to, or None.

    Deliberately narrow: the message must start with one of a few verbs and the
    REST of it must be exactly an agent's name. A looser match would swallow
    real requests that happen to begin with "use", and a message silently
    turning into a setting is worse than a router that picks wrong.
    """
    t = _normalise(text)
    for verb in PIN_VERBS:
        if t.startswith(verb):
            rest = t[len(verb):].strip()
            for c in cands:
                if rest == c["name"].strip().lower():
                    return c
    return None


def is_unpin_request(text: str) -> bool:
    return _normalise(text) in UNPIN_PHRASES


def pin_key(platform: str, chat_id: str) -> str:
    return "gateway:agent-pin:%s:%s" % (platform, chat_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_router.py -q`
Expected: `30 passed`

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/gateway/agent_router.py webhook-handler/tests/test_gateway_agent_router.py
git commit -m "feat(gateway): choose which agent answers a message

An agent is a model row, so routing to one is choosing a different id. The hard
part is that the thing choosing is a model reading a short message: it can be
wrong and it can invent an id. Every answer is checked against the caller's own
candidates before it becomes a model id.

Candidates are capped and carry a one-line description rather than the agent's
instructions, because this prompt is built on every message and instructions run
to 4000 characters.

The pin matcher is narrow on purpose. The message must start with one of three
verbs and the rest of it must BE an agent's name, so \"use my email to find the
invoice\" stays an ordinary request. A message silently turning into a setting
is worse than a router that picks wrong."
```

---

## Task 3: The pipeline routes to the chosen agent

**Files:**
- Modify: `webhook-handler/config.py:107`
- Modify: `webhook-handler/gateway/pipeline.py`
- Test: `webhook-handler/tests/test_gateway_agent_routing.py` (create)

**Interfaces:**
- Consumes: `agent_router.candidates`, `agent_router.pick` from Task 2; `OWUIUserClient.list_models` from Task 1.
- Produces: `pipeline._choose_agent(owui, text) -> dict | None`. Task 4 extends the same call site.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_agent_routing.py`:

```python
"""The pipeline sending a message to an agent instead of the default model.

The load-bearing assertions are that the id the router returns is what reaches
chat_completion, and that every way the routing can fail still answers the
person. The group refusal is re-tested here because this change sits directly
after it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from gateway import pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

AGENT = {"id": "agent-inbox-triage-0002", "name": "Inbox Triage",
         "base_model_id": "gpt-4o-mini",
         "meta": {"description": "You read unread email.", "toolIds": []}}


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.list_models.return_value = [AGENT]
    # First call is the router, second is the real answer.
    client.chat_completion.side_effect = ["agent-inbox-triage-0002", "the answer"]
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok-for-user-1"}
    tasks.gateway_get_session.return_value = None
    tasks.get_state.return_value = None

    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _event(text="check my mail", chat_type="dm"):
    return MessageEvent(
        text=text, message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type=chat_type, user_id="111",
                             user_name="Ralph"))


def _answer_call(owui):
    """The chat_completion call that produced the reply, not the router one."""
    return owui.chat_completion.await_args_list[-1]


async def test_the_agent_id_is_what_answers(adapter, owui):
    await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == "agent-inbox-triage-0002"


async def test_the_reply_says_which_agent_answered(adapter):
    out = await pipeline.handle_event(_event(), adapter)

    assert out.rstrip().endswith("via Inbox Triage")
    assert "the answer" in out


async def test_no_agents_means_the_default_model_and_no_tag(adapter, owui):
    owui.list_models.return_value = []
    owui.chat_completion.side_effect = ["the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == settings.gateway_model
    assert "via" not in out
    assert owui.chat_completion.await_count == 1, "the router ran with no candidates"


async def test_an_invented_id_falls_back_to_the_default_model(adapter, owui):
    owui.chat_completion.side_effect = ["agent-not-yours-9999", "the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert _answer_call(owui).args[1] == settings.gateway_model
    assert "via" not in out


async def test_a_failure_to_list_models_still_answers(adapter, owui):
    owui.list_models.side_effect = RuntimeError("models endpoint down")
    owui.chat_completion.side_effect = ["the answer"]

    out = await pipeline.handle_event(_event(), adapter)

    assert "the answer" in out
    assert _answer_call(owui).args[1] == settings.gateway_model


async def test_the_transcript_records_the_agent_that_answered(adapter, owui):
    await pipeline.handle_event(_event(), adapter)

    owui.update_chat.assert_awaited()
    written = owui.update_chat.await_args.args[1]
    assert "agent-inbox-triage-0002" in str(written)


async def test_a_group_message_is_still_refused(adapter, wired, owui):
    """Regression. This change sits immediately after that check."""
    out = await pipeline.handle_event(_event(chat_type="group"), adapter)

    assert out == pipeline.GROUP_REFUSAL
    wired.tasks.gateway_resolve.assert_not_called()
    owui.list_models.assert_not_called()


async def test_a_command_never_reaches_the_router(adapter, owui):
    await pipeline.handle_event(_event(text="/help"), adapter)

    owui.list_models.assert_not_called()
    owui.chat_completion.assert_not_called()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_routing.py -q`
Expected: FAIL. `test_the_agent_id_is_what_answers` fails because the default model is sent, and `test_no_agents_means_the_default_model_and_no_tag` fails on the await count.

- [ ] **Step 3: Add the router model setting**

In `webhook-handler/config.py`, directly below the `gateway_model` field on line 107:

```python
    # The model that decides WHICH agent answers. Called with the user's own
    # token, so it has to be one every user can see: gpt-4o-mini has a row and
    # a wildcard read grant, so it qualifies. Kept separate from gateway_model
    # so the routing decision can run on something cheap.
    gateway_router_model: str = Field(default="gpt-4o-mini",
                                      alias="GATEWAY_ROUTER_MODEL")
```

- [ ] **Step 4: Wire the choice into the pipeline**

In `webhook-handler/gateway/pipeline.py`, add to the imports:

```python
from gateway import agent_router
```

Add this function directly above `async def _run(`:

```python
async def _choose_agent(owui: OWUIUserClient, text: str) -> dict | None:
    """The agent that should answer, or None for the default model.

    Never raises. Listing models or routing can both fail, and neither is a
    reason to leave somebody staring at silence, so both fall back to the
    normal model.
    """
    try:
        models = await owui.list_models()
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not list the caller's models, using the "
                    "default model", exc_info=True)
        return None
    cands = agent_router.candidates(models)
    return await agent_router.pick(
        owui, text, cands, settings.gateway_router_model)
```

Then in `_run`, replace this block:

```python
    await adapter.send_typing(src.chat_id)
    chat_id, chat = await get_or_create_chat(
        _tasks, owui, src.platform, src.chat_id,
        owui_user_id, text, settings.gateway_model)

    messages = history_messages(chat, settings.gateway_history_turns)
    messages.append({"role": "user", "content": text})
    answer = await owui.chat_completion(
        messages, settings.gateway_model, chat_id=chat_id)
```

with:

```python
    await adapter.send_typing(src.chat_id)

    agent = await _choose_agent(owui, text)
    model = agent["id"] if agent else settings.gateway_model

    chat_id, chat = await get_or_create_chat(
        _tasks, owui, src.platform, src.chat_id,
        owui_user_id, text, model)

    messages = history_messages(chat, settings.gateway_history_turns)
    messages.append({"role": "user", "content": text})
    answer = await owui.chat_completion(messages, model, chat_id=chat_id)
```

And replace the persist-and-deliver block at the end of `_run`:

```python
    try:
        await owui.update_chat(
            chat_id, append_turn(chat, text, answer, settings.gateway_model))
    except Exception:                              # noqa: BLE001
        log.exception("gateway: could not write the transcript to chat %s; "
                      "delivering the answer anyway", chat_id)

    return await _say(adapter, src.chat_id, answer)
```

with:

```python
    try:
        await owui.update_chat(
            chat_id, append_turn(chat, text, answer, model))
    except Exception:                              # noqa: BLE001
        log.exception("gateway: could not write the transcript to chat %s; "
                      "delivering the answer anyway", chat_id)

    # Tagged on delivery, not in the transcript. The stored turn already
    # records the model that produced it, and the web UI shows that, so
    # writing the tag into the text too would duplicate it there.
    if agent:
        answer = "%s\n\nvia %s" % (answer, agent["name"])

    return await _say(adapter, src.chat_id, answer)
```

- [ ] **Step 5: Run the new tests**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_routing.py -q`
Expected: `8 passed`

- [ ] **Step 6: Run the whole suite for regressions**

Run: `cd webhook-handler && py -m pytest tests/ -q`
Expected: everything passes. `tests/test_gateway_pipeline.py` is the one to watch, because it asserts on `chat_completion` calls and a router call now comes first whenever there are candidates.

Those tests keep passing for a specific reason, not by luck. Their `owui` fixture is an `AsyncMock`, so `list_models()` returns a `MagicMock` rather than a list. The `isinstance(models, list)` guard in `candidates()` turns that into no candidates, so no router call happens. Without that guard the `for` loop would raise `TypeError`, `handle_event` would catch it, and every one of those tests would fail with an unexplained `UNEXPECTED` reply.

If any do fail, make the test explicit about what `list_models` returns rather than changing the pipeline to suit the test.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/config.py webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_agent_routing.py
git commit -m "feat(gateway): answer as the agent that fits the message

A direct message now goes to whichever of your agents suits it, with that
agent's instructions and tools, acting as you. Because an agent is a model row,
this is one different id reaching the call that was already there.

The reply ends with a line naming the agent, so a wrong choice is visible rather
than silent, and the transcript records the agent as the model so the web UI
agrees with what happened.

Listing the models and routing can both fail and neither stops a reply: both
fall back to the default model. Somebody is waiting on the other end.

The group refusal is re-tested here rather than trusted, because this change
sits immediately after it."
```

---

## Task 4: Pinning an agent for the conversation

**Files:**
- Modify: `webhook-handler/gateway/pipeline.py`
- Test: `webhook-handler/tests/test_gateway_agent_pin.py` (create)

**Interfaces:**
- Consumes: `agent_router.match_pin_request`, `is_unpin_request`, `pin_key`, `candidates` from Task 2; `_tasks.get_state/set_state/delete_state`.
- Produces: nothing further.

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_gateway_agent_pin.py`:

```python
"""Pinning an agent, which is how a wrong pick costs one sentence.

Without a pin, a message the router misreads once it misreads every time you
rephrase it.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from gateway import agent_router, pipeline
from gateway.events import MessageEvent, MessageType, SessionSource

AGENT = {"id": "agent-inbox-triage-0002", "name": "Inbox Triage",
         "base_model_id": "gpt-4o-mini",
         "meta": {"description": "You read unread email.", "toolIds": []}}
KEY = agent_router.pin_key("telegram", "42")


@pytest.fixture
def adapter():
    a = AsyncMock()
    a.name = "telegram"
    a.max_message_length = 4096
    return a


@pytest.fixture
def owui():
    client = AsyncMock()
    client.get_chat.return_value = {"title": "t", "messages": [],
                                    "history": {"messages": {}, "currentId": None}}
    client.create_chat.return_value = "chat-1"
    client.list_models.return_value = [AGENT]
    client.chat_completion.return_value = "the answer"
    return client


@pytest.fixture(autouse=True)
def wired(monkeypatch, owui):
    tasks = AsyncMock()
    tasks.gateway_resolve.return_value = {
        "linked": True, "email": "user@example.com",
        "owui_user_id": "owui-1", "owui_token": "tok-for-user-1"}
    tasks.gateway_get_session.return_value = None
    tasks.get_state.return_value = None
    monkeypatch.setattr(pipeline, "_tasks", tasks)
    monkeypatch.setattr(pipeline, "_owui_factory", lambda token: owui)
    return MagicMock(tasks=tasks, owui=owui)


def _event(text):
    return MessageEvent(
        text=text, message_type=MessageType.TEXT,
        source=SessionSource(platform="telegram", chat_id="42",
                             chat_type="dm", user_id="111", user_name="Ralph"))


async def test_a_pin_phrase_saves_the_choice_and_answers_without_a_model(
        adapter, wired, owui):
    out = await pipeline.handle_event(_event("use Inbox Triage"), adapter)

    wired.tasks.set_state.assert_awaited_once()
    assert wired.tasks.set_state.await_args.args[0] == KEY
    assert "Inbox Triage" in out
    owui.chat_completion.assert_not_called()


async def test_a_pinned_agent_answers_without_asking_the_router(
        adapter, wired, owui):
    wired.tasks.get_state.return_value = {"id": AGENT["id"],
                                          "name": AGENT["name"]}

    out = await pipeline.handle_event(_event("what is new"), adapter)

    assert owui.chat_completion.await_count == 1, "the router ran anyway"
    assert owui.chat_completion.await_args.args[1] == AGENT["id"]
    assert out.rstrip().endswith("via Inbox Triage")


async def test_unpinning_clears_it(adapter, wired, owui):
    wired.tasks.get_state.return_value = {"id": AGENT["id"],
                                          "name": AGENT["name"]}

    out = await pipeline.handle_event(_event("stop using that"), adapter)

    wired.tasks.delete_state.assert_awaited_once_with(KEY)
    assert "normal" in out.lower() or "back" in out.lower()
    owui.chat_completion.assert_not_called()


async def test_a_pin_naming_a_deleted_agent_clears_itself(adapter, wired, owui):
    """The agent was deleted on the web after being pinned here."""
    wired.tasks.get_state.return_value = {"id": "agent-gone-0000",
                                          "name": "Gone"}

    out = await pipeline.handle_event(_event("what is new"), adapter)

    wired.tasks.delete_state.assert_awaited_once_with(KEY)
    assert owui.chat_completion.await_args.args[1] == settings.gateway_model
    assert "Gone" in out


async def test_a_state_failure_does_not_stop_the_answer(adapter, wired, owui):
    wired.tasks.get_state.side_effect = RuntimeError("state store down")

    out = await pipeline.handle_event(_event("what is new"), adapter)

    assert "the answer" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_pin.py -q`
Expected: FAIL, `set_state` never called and the pin never read.

- [ ] **Step 3: Implement the pin**

In `webhook-handler/gateway/pipeline.py`, add these sentences beside the other
copy at the top of the file:

```python
PINNED = ("Right, I'll use %s for this conversation. Say \"stop using that\" "
          "to go back.")
UNPINNED = "Back to normal. I'll pick whichever agent fits each message."
PIN_GONE = ("%s is gone, so I answered normally. Ask me again if you want a "
            "different one.")
```

Replace the whole `_choose_agent` function from Task 3 with the two functions
below. The return type changes from `dict | None` to a triple, because a stale
pin has to say something AND still answer the question, which a single sentence
could not express.

```python
async def _read_pin(key: str) -> dict | None:
    """The pinned agent for this conversation, or None. Never raises."""
    try:
        pin = await _tasks.get_state(key)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not read the agent pin", exc_info=True)
        return None
    return pin if isinstance(pin, dict) and pin.get("id") else None


async def _choose_agent(owui: OWUIUserClient, text: str,
                        src) -> tuple[dict | None, str | None, str | None]:
    """Returns (agent, reply, notice).

    reply  means the message was a setting: answer with this and call no model.
    notice means say this alongside the model's answer.

    Never raises. Listing models, routing, and the state store can all fail,
    and none of them is a reason to leave somebody staring at silence.
    """
    key = agent_router.pin_key(src.platform, src.chat_id)

    try:
        models = await owui.list_models()
        cands = agent_router.candidates(models)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not list the caller's models, using the "
                    "default model", exc_info=True)
        return None, None, None

    if agent_router.is_unpin_request(text):
        await _forget_pin(key)
        return None, UNPINNED, None

    asked = agent_router.match_pin_request(text, cands)
    if asked:
        try:
            await _tasks.set_state(key, {"id": asked["id"],
                                         "name": asked["name"]})
        except Exception:                              # noqa: BLE001
            log.warning("gateway: could not save the agent pin", exc_info=True)
        return asked, PINNED % asked["name"], None

    pin = await _read_pin(key)
    if pin:
        # It may have been deleted on the web since it was pinned here.
        if any(c["id"] == pin["id"] for c in cands):
            return pin, None, None
        await _forget_pin(key)
        return None, None, PIN_GONE % pin.get("name", "That agent")

    chosen = await agent_router.pick(
        owui, text, cands, settings.gateway_router_model)
    return chosen, None, None


async def _forget_pin(key: str) -> None:
    """Clear a pin, never raising. A pin we cannot clear is not worth a
    failed reply."""
    try:
        await _tasks.delete_state(key)
    except Exception:                                  # noqa: BLE001
        log.warning("gateway: could not clear the agent pin", exc_info=True)
```

- [ ] **Step 4: Use the triple in `_run`**

Replace the two lines added in Task 3:

```python
    agent = await _choose_agent(owui, text)
    model = agent["id"] if agent else settings.gateway_model
```

with:

```python
    agent, reply, notice = await _choose_agent(owui, text, src)

    # A pin request is a setting, not a question. Answering it with a model
    # would spend a call and a turn of history saying "ok".
    if reply:
        return await _say(adapter, src.chat_id, reply)

    model = agent["id"] if agent else settings.gateway_model
```

and replace the tag block from Task 3:

```python
    if agent:
        answer = "%s\n\nvia %s" % (answer, agent["name"])

    return await _say(adapter, src.chat_id, answer)
```

with:

```python
    # A notice rides along with the answer rather than replacing it: the person
    # asked a real question and still deserves it answered.
    if notice:
        answer = "%s\n\n%s" % (notice, answer)
    if agent:
        answer = "%s\n\nvia %s" % (answer, agent["name"])

    return await _say(adapter, src.chat_id, answer)
```

- [ ] **Step 5: Run the new tests**

Run: `cd webhook-handler && py -m pytest tests/test_gateway_agent_pin.py -q`
Expected: `5 passed`

- [ ] **Step 6: Run the whole suite**

Run: `cd webhook-handler && py -m pytest tests/ -q`
Expected: everything passes, including `tests/test_gateway_agent_routing.py` and `tests/test_gateway_pipeline.py`.

- [ ] **Step 7: Commit**

```bash
git add webhook-handler/gateway/pipeline.py webhook-handler/tests/test_gateway_agent_pin.py
git commit -m "feat(gateway): pin an agent for the conversation

Saying \"use Inbox Triage\" points the conversation at that agent until you say
\"stop using that\". This is what makes a wrong automatic pick cost one sentence
instead of a fight: without it, a message the router misreads once it misreads
every time you rephrase it.

A pin request is a setting rather than a question, so it is answered directly
without spending a model call or a turn of history.

A pin whose agent has since been deleted clears itself, says so, and still
answers the question that was asked. Reading or writing the pin can fail and
neither stops a reply."
```

---

## Task 5: Deploy and verify on a real conversation

**Files:**
- No new files. Deploys Tasks 1 to 4.

**Interfaces:**
- Consumes: everything above.
- Produces: the feature, live.

**`webhook-handler` is not covered by `scripts/deploy_orchestrator.sh`.** It is deployed by hand, one `scp` per changed file. `scp -r` silently skips files, so never use it.

- [ ] **Step 1: Confirm the working tree is clean and tests pass**

```bash
cd "C:/All/Work - Code/ai_ui"
git status --short -- webhook-handler
cd webhook-handler && py -m pytest tests/ -q
```

Expected: no output from `git status` for that path, and a passing suite.

- [ ] **Step 2: Hash sweep before overwriting anything**

Teammates edit files directly on the box. Check the server's copies match the branch point before a repo-wins deploy, or their work is silently reverted.

```bash
cd "C:/All/Work - Code/ai_ui"
for f in gateway/pipeline.py gateway/owui.py config.py; do
  local_base=$(git show bbe2ed84d:webhook-handler/$f 2>/dev/null | tr -d '\r' | sha256sum | cut -c1-16)
  remote=$(ssh -o ConnectTimeout=20 root@46.224.193.25 \
    "tr -d '\r' < /root/proxy-server/webhook-handler/$f 2>/dev/null | sha256sum | cut -c1-16")
  echo "$f  branch-point=$local_base  server=$remote"
done
```

Expected: they match for every file. If one differs, STOP and diff it: somebody changed it on the server and deploying would revert them.

- [ ] **Step 3: Copy each changed file, hash-verified**

```bash
cd "C:/All/Work - Code/ai_ui"
for f in gateway/owui.py gateway/agent_router.py gateway/pipeline.py config.py; do
  want=$(tr -d '\r' < "webhook-handler/$f" | sha256sum | cut -c1-16)
  for try in 1 2 3 4; do
    scp -q -o ConnectTimeout=20 "webhook-handler/$f" \
      "root@46.224.193.25:/root/proxy-server/webhook-handler/$f" 2>/dev/null
    got=$(ssh -o ConnectTimeout=20 root@46.224.193.25 \
      "sed -i 's/\r$//' /root/proxy-server/webhook-handler/$f 2>/dev/null; \
       tr -d '\r' < /root/proxy-server/webhook-handler/$f 2>/dev/null | sha256sum | cut -c1-16")
    [ "$want" = "$got" ] && { echo "OK $f"; break; }
    echo "  retry $try for $f"; sleep 5
  done
done
```

Expected: `OK` for all four. Do not proceed on a mismatch. This link truncated a 90KB file to 77KB on 2026-08-20.

- [ ] **Step 4: Rebuild**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && \
  docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

Expected: `webhook-handler  Started`.

- [ ] **Step 5: Confirm it came up**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && \
  docker compose -f docker-compose.unified.yml ps webhook-handler"
```

Expected: `Up`. If not, read the logs before touching anything else.

- [ ] **Step 6: The check no test can do, on a real conversation**

In a Telegram or Discord **direct message** with the bot, as a paired non-admin account:

1. Send `what is the capital of France`. Expected: a normal answer, **no** `via` line, because no agent fits.
2. Send `check my unread email`. Expected: an answer ending `via Inbox Triage`.
3. Send `use Research Assistant`. Expected: the confirmation sentence, and no model answer.
4. Send `what is new`. Expected: an answer ending `via Research Assistant`.
5. Send `stop using that`. Expected: the back-to-normal sentence.

Step 2 is the one that matters most, and it is the whole reason this step exists: it is the first proof that an agent's **tools** reach the model through a channel. Every test above stubs the model. If the answer shows it actually read the mailbox rather than apologising, that also settles the open question from the AI Agents plan, which its Step 5b could not.

- [ ] **Step 7: Record the result**

```bash
git commit --allow-empty -m "chore(gateway): agents in channels verified on a real conversation

A database and container change with no file of its own, recorded here so the
branch carries the record. Verified in a real direct message: a message with no
matching agent answers untagged, a mail request answers as Inbox Triage, a pin
sentence switches and sticks, and unpinning returns to normal.

Step 2 of that check is the first proof that an agent's tools reach the model
through a channel. Every automated test here stubs the model, so nothing before
this could show it."
```

---

## Rollback

| If | Then |
|---|---|
| The router picks badly and annoys people | Set `GATEWAY_ROUTER_MODEL` to a better model and rebuild, or revert Task 3's pipeline change; Tasks 1, 2 and 4 are inert without it. |
| Channel answers break entirely | `git revert` the Task 3 and Task 4 commits and rebuild `webhook-handler`. Tasks 1 and 2 add a method and a module that nothing calls. |
| The extra model call costs too much | Point `GATEWAY_ROUTER_MODEL` at a free model, or revert Task 3. |
| A pin is stuck for one person | `delete_state` on `gateway:agent-pin:<platform>:<chat id>`. |
