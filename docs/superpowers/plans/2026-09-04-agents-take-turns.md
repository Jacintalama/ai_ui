# Agents Take Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When two or more agents answer one message, each agent's reply is a real, separate message in the web chat, arriving one after another.

**Architecture:** The pipe returns only the first agent's reply, tagged with a hidden marker naming every agent that answers. The page waits for Open WebUI to save that reply, asks the service to run the next agent through a user-authenticated route, writes the answer into the chat's own history as a new assistant message, and soft-navigates so Open WebUI renders it. Every agent still runs through the service's own loop.

**Tech Stack:** Python 3.11 / FastAPI (tasks service), Open WebUI pipe functions (httpx + pydantic), vanilla JS in the bind-mounted `integrations-ui.js`, Playwright for the live browser checks.

**Spec:** `docs/superpowers/specs/2026-09-04-agents-take-turns-design.md`

## Global Constraints

- The marker is `<!-- aiui:turns <id>[,<id>...] -->` on its own line at the end of a reply. It lists **every** agent that answers, in speaking order, the first being the author of the message that carries it. This refines the spec's `aiui:next <remaining>`: carrying the author's id too is what lets the page claim the first message without parsing a display name back into an id.
- Model **ids** in the marker, never names.
- The pipe reply contains **one** agent's turn when `first_only` is set. Discord and Telegram never set it and are unchanged.
- The page writes to the chat only through `GET /api/v1/chats/<id>` and `POST /api/v1/chats/<id>`, reading, modifying the tail and the new message, and writing back. Never constructs a chat from scratch.
- The page never writes before the stored tail carries the marker, because Open WebUI's own save after a reply replaces the whole chat.
- The page holds no internal secret. It reaches the service only through a `current_user`-authenticated route.
- `integrations-ui.js` is bind-mounted: deploy with `cat >`, never `scp`.
- Never use an em-dash or en-dash anywhere: code, comments, copy, commit messages.
- Never add AI attribution to a commit. `git add` named paths only, never `-A`.
- Edit files, do not rewrite them. Keep two blank lines between top-level Python definitions.
- Watch escape sequences. Before committing a Python file run `python -W error::SyntaxWarning -c "import pathlib; compile(pathlib.Path('PATH').read_text(encoding='utf-8'),'x','exec')"`. Before committing the JS run `node -e "new Function(require('fs').readFileSync('mcp-servers/gdrive/integrations-ui.js','utf8'))"`.

---

### Task 1: The service runs one agent and names the rest

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_turn.py` (`ChatIn`, the `if named:` branch of `chat()`, every `return` of `chat()`)
- Test: `mcp-servers/tasks/tests/test_agent_chat_endpoint.py`

**Interfaces:**
- Consumes: `ChatIn`, `chat()`, `_turn_for(user_email, agent, messages, names)`, `_write_pin`, `render_turns`, all already in the file.
- Produces: `ChatIn.first_only: bool = False`; every `chat()` response gains `"queue": list[str]` and `"marker": str`; `turns_marker(ids: list[str]) -> str` module function.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_agent_chat_endpoint.py`:

```python


async def test_first_only_runs_one_agent_and_names_the_rest(_wire):
    """The web page takes turns: the pipe shows the first agent, the page
    fetches the rest one at a time. So the service runs one and says who
    is left, in speaking order."""
    b = _body("hi team")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Ada"]
    assert out["queue"] == ["agent-m"]
    rt._run_turn.assert_awaited_once()


async def test_first_only_still_pins_the_last_agent_in_the_full_list(_wire):
    """A follow up with no name goes to whoever spoke last, and that is
    still Mia even though only Ada has spoken so far."""
    b = _body("hi team")
    b.first_only = True
    await rt.chat(b, x_internal_secret="s")
    assert rt._write_pin.await_args.args[1] == "agent-m"


async def test_the_marker_names_every_speaker_with_the_author_first(_wire):
    b = _body("hi team")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["marker"] == "<!-- aiui:turns agent-a,agent-m -->"


async def test_one_agent_named_means_no_queue_and_no_marker(_wire):
    b = _body("hi mia")
    b.first_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["queue"] == []
    assert out["marker"] == ""


async def test_without_first_only_every_agent_still_runs(_wire):
    """Discord and Telegram never set the flag and must not change."""
    out = await rt.chat(_body("hi team"), x_internal_secret="s")
    assert [t["agent"]["name"] for t in out["turns"]] == ["Ada", "Mia"]
    assert out["queue"] == []
    assert out["marker"] == ""


async def test_every_reply_shape_carries_queue_and_marker(_wire, monkeypatch):
    """The pipes read both fields off every reply, so every branch must
    return them, not only the one that fills them."""
    monkeypatch.setattr(rt, "_answer_as_io", AsyncMock(return_value="io"))
    for text in ("what is the weather", "stop"):
        out = await rt.chat(_body(text), x_internal_secret="s")
        assert out["queue"] == [] and out["marker"] == "", text
    b = _body("plain")
    b.route_only = True
    out = await rt.chat(b, x_internal_secret="s")
    assert out["queue"] == [] and out["marker"] == ""


def test_turns_marker_is_one_line_with_ids_only():
    assert rt.turns_marker(["agent-a", "agent-m"]) == "<!-- aiui:turns agent-a,agent-m -->"
    assert rt.turns_marker([]) == ""
    assert rt.turns_marker(["agent-a"]) == ""
```

Also add `first_only = False` to the `_body` helper's class `B` beside `route_only = False`, and to the inline class `B` in `test_an_agent_sees_history_without_the_speaker_labels`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_chat_endpoint.py -q`
Expected: the new tests fail with `KeyError: 'queue'` and `AttributeError: module has no attribute 'turns_marker'`.

- [ ] **Step 3: Add the flag, the marker, and the one-agent branch**

In `mcp-servers/tasks/routes_agent_turn.py`, extend `ChatIn`:

```python
    #: The web page takes turns: the pipe shows the first agent's reply and
    #: the page fetches each further agent itself, so they arrive one after
    #: another as separate messages. With this set, only the first matched
    #: agent runs here and the rest come back as `queue`. Discord and
    #: Telegram send one message per turn already and never set it.
    first_only: bool = False
```

Add, directly under `render_turns`:

```python


def turns_marker(ids) -> str:
    """The hidden line that tells the page who answers and in what order.

    Empty unless at least two agents answer, because a single reply needs
    nothing from the page. Model ids, never names: a name can be renamed
    under a stored message and an id cannot, and the page hands these ids
    straight back to /agents/speak. An HTML comment renders as nothing and
    survives the round trip through the chat's own storage, which is what
    lets the page find it again after a reload.
    """
    ids = [i for i in (ids if isinstance(ids, list) else []) if isinstance(i, str) and i]
    if len(ids) < 2:
        return ""
    return "<!-- aiui:turns %s -->" % ",".join(ids)
```

Replace the `if named:` branch body:

```python
    if named:
        # Naming agents switches rather than stacking: the LAST one named is
        # who a follow up with no name goes to, so "actually ada, you take
        # this" hands over cleanly even when Mia was also named.
        names = [a.get("name") for a in agents if a.get("name")]
        speakers = named[:1] if getattr(body, "first_only", False) else named
        turns = []
        for agent in speakers:
            turns.append(await _turn_for(body.user_email, agent, body.messages, names))
        await _write_pin(key, named[-1]["id"])
        queue = [a["id"] for a in named[1:]] if getattr(body, "first_only", False) else []
        ids = [a["id"] for a in named] if queue else []
        return {"turns": turns, "rendered": render_turns(turns),
                "queue": queue, "marker": turns_marker(ids)}
```

Add `"queue": [], "marker": ""` to every other `return` in `chat()`: the `wants_release` branch, the `route_only` branch, the IO-answers branch, and the pinned follow-up at the end. Four sites. Each becomes, for example:

```python
        return {"turns": turns, "rendered": render_turns(turns), "queue": [], "marker": ""}
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_chat_endpoint.py tests/test_agent_label_echo.py -q`
Expected: all pass.

- [ ] **Step 5: Prove the tests are load bearing**

Change `speakers = named[:1] if ...` to `speakers = named` and confirm `test_first_only_runs_one_agent_and_names_the_rest` goes red. Restore. Change `len(ids) < 2` to `len(ids) < 1` and confirm `test_turns_marker_is_one_line_with_ids_only` goes red. Restore. Do not commit a mutation.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/tests/test_agent_chat_endpoint.py
git commit -m "Run one agent and name the rest, so the page can take turns"
```

---

### Task 2: A door the page can use

**Files:**
- Modify: `mcp-servers/tasks/routes_agents.py` (new route at the end)
- Test: `mcp-servers/tasks/tests/test_agents_speak.py`

**Interfaces:**
- Consumes: `current_user`, `CurrentUser` from `auth`; `_agents_for`, `_turn_for` from `routes_agent_turn`.
- Produces: `POST /agents/speak` (mounted at both `/agents` and `/api/tasks/agents`, like every route in this file), body `{chat_id, agent_id, messages}`, response `{answer, notes, agent: {id, name}}`.

**Why this file:** `routes_agents.py` is already mounted under `/api/tasks` and already uses `current_user`, so the page reaches it with the same `aiuiAuthHeaders()` it uses for everything else. The internal `/agents/turn` lives in `routes_agent_turn.py` and must stay internal; this is a different path name on purpose so the two can never collide.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_agents_speak.py`:

```python
"""The one door the page uses to make a further agent speak.

It opens onto _turn_for, which already has its own gate, so the only thing
this route adds is: prove who is asking, and let them run only their own
agents. A stranger's token, or no token, must reach nothing.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

import routes_agents
from auth import CurrentUser, current_user

ADA = {"id": "agent-a", "name": "Ada"}
MIA = {"id": "agent-m", "name": "Mia"}
OWNER = "speak-owner@example.com"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")
    app.dependency_overrides[current_user] = lambda: CurrentUser(email=OWNER)
    monkeypatch.setattr(routes_agents, "_agents_for",
                        AsyncMock(return_value=[ADA, MIA]))
    monkeypatch.setattr(routes_agents, "_turn_for",
                        AsyncMock(return_value={"answer": "hi from mia", "notes": ["a note"],
                                                "agent": {"id": "agent-m", "name": "Mia"}}))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


BODY = {"chat_id": "chat-1", "agent_id": "agent-m",
        "messages": [{"role": "user", "content": "hi team"},
                     {"role": "assistant", "content": "hello from ada"}]}


async def test_an_owner_can_make_their_own_agent_speak(client):
    r = await client.post("/api/tasks/agents/speak", json=BODY)
    assert r.status_code == 200
    assert r.json() == {"answer": "hi from mia", "notes": ["a note"],
                        "agent": {"id": "agent-m", "name": "Mia"}}


async def test_the_turn_runs_through_the_same_loop_as_every_other(client):
    """_turn_for is what applies the access level, cleans the labels out of
    history and records the run. This route must call it, not _run_turn."""
    await client.post("/api/tasks/agents/speak", json=BODY)
    routes_agents._turn_for.assert_awaited_once()
    args = routes_agents._turn_for.await_args.args
    assert args[0] == OWNER
    assert args[1] == MIA
    assert args[2] == BODY["messages"]
    assert sorted(args[3]) == ["Ada", "Mia"]


async def test_an_agent_the_caller_does_not_own_is_refused(client):
    r = await client.post("/api/tasks/agents/speak",
                          json={**BODY, "agent_id": "agent-somebody-elses"})
    assert r.status_code == 403
    routes_agents._turn_for.assert_not_awaited()


async def test_no_token_reaches_nothing(monkeypatch):
    app = FastAPI()
    app.include_router(routes_agents.router, prefix="/api/tasks")

    def _refuse():
        raise HTTPException(status_code=401, detail="no")
    app.dependency_overrides[current_user] = _refuse
    monkeypatch.setattr(routes_agents, "_turn_for", AsyncMock())
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    r = await c.post("/api/tasks/agents/speak", json=BODY)
    assert r.status_code == 401
    routes_agents._turn_for.assert_not_awaited()


@pytest.mark.parametrize("bad", [
    {"chat_id": "c", "agent_id": "", "messages": []},
    {"chat_id": "", "agent_id": "agent-m", "messages": []},
    {"chat_id": "c", "agent_id": "agent-m"},
])
async def test_a_malformed_request_is_a_422_not_a_500(client, bad):
    r = await client.post("/api/tasks/agents/speak", json=bad)
    assert r.status_code == 422
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agents_speak.py -q`
Expected: 404s, since the route does not exist.

- [ ] **Step 3: Add the route**

At the top of `mcp-servers/tasks/routes_agents.py`, with the other imports:

```python
from routes_agent_turn import _agents_for, _turn_for
```

At the end of the file:

```python


class SpeakIn(BaseModel):
    chat_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    messages: list[dict]


@router.post("/speak")
async def speak(body: SpeakIn, user: CurrentUser = Depends(current_user)) -> dict:
    """Make one of this person's agents answer, for the page that takes
    turns.

    The page cannot hold the internal secret, so this is the one door it
    uses. It opens onto _turn_for, which already applies the agent's access
    level, cleans the speaker labels out of history and records the run;
    all this route adds is proof of who is asking and the rule that they
    may run only their own agents. Not /agents/turn, which is internal and
    must stay so.

    The pin is deliberately not written here. The first_only reply already
    pinned the last agent in the full list, and a turn for an earlier one
    must not move it back.
    """
    agents = await _agents_for(user.email)
    agent = next((a for a in agents if a.get("id") == body.agent_id), None)
    if agent is None:
        raise HTTPException(status_code=403, detail="That is not one of your agents.")
    names = [a.get("name") for a in agents if a.get("name")]
    out = await _turn_for(user.email, agent, body.messages, names)
    return {"answer": out.get("answer") or "",
            "notes": [n for n in (out.get("notes") or []) if isinstance(n, str)],
            "agent": out.get("agent") or {"id": agent["id"], "name": agent.get("name")}}
```

Check that `BaseModel`, `Field`, `Depends` and `HTTPException` are already imported in that file; add any that are not.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agents_speak.py -q`
Expected: all pass.

Then confirm the mount and that it does not collide with the internal route:

```bash
cd mcp-servers/tasks && AIUI_FERNET_KEY=x DATABASE_URL=postgresql://x@y/z python -c "import main; ps=main.app.openapi()['paths']; print(sorted(p for p in ps if 'speak' in p or p.endswith('/agents/turn')))"
```
Expected: `['/agents/speak', '/agents/turn', '/api/tasks/agents/speak']`, and `/api/tasks/agents/turn` absent.

- [ ] **Step 5: Prove the membership check is load bearing**

Change `if agent is None:` to `if False:` and confirm `test_an_agent_the_caller_does_not_own_is_refused` goes red. Restore.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agents_speak.py
git commit -m "A door the page can use to make a further agent speak"
```

---

### Task 3: Both pipes show one agent and carry the marker

**Files:**
- Modify: `open-webui-functions/io_gateway_pipe.py` (`_ask_tasks`, `pipe()`)
- Modify: `open-webui-functions/auto_router_pipe.py` (`_agents_first`)
- Test: `mcp-servers/tasks/tests/test_io_gateway_pipe.py`, `mcp-servers/tasks/tests/test_auto_router_pipe.py`

**Interfaces:**
- Consumes: the service's `{turns, rendered, queue, marker}` shape from Task 1.
- Produces: each pipe's reply text ends with the marker when one is present.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-servers/tasks/tests/test_io_gateway_pipe.py`:

```python


async def test_the_pipe_asks_for_one_agent_at_a_time(mod, monkeypatch):
    """The page takes turns. The pipe must say so, or the service runs
    everybody and the page finds nothing left to fetch."""
    p = mod.Pipe()
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"turns": [], "rendered": "", "queue": [], "marker": ""}

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            seen.update(json or {}); return R()

    monkeypatch.setattr(mod.httpx, "AsyncClient", C)
    await p._ask_tasks("o@example.com", "chat-1", [{"role": "user", "content": "hi team"}])
    assert seen.get("first_only") is True


async def test_the_marker_rides_at_the_end_of_the_reply(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "turns": [{"agent": {"id": "agent-a", "name": "Ada"}, "answer": "Hello.", "notes": []}],
        "rendered": "Ada:\nHello.", "queue": ["agent-m"],
        "marker": "<!-- aiui:turns agent-a,agent-m -->"}))
    out = await p.pipe({"messages": [{"role": "user", "content": "hi team"}], "stream": False},
                       __user__={"email": "o@example.com"})
    assert out.endswith("<!-- aiui:turns agent-a,agent-m -->")
    assert "Hello." in out
    assert out.count("aiui:turns") == 1


async def test_no_marker_means_nothing_is_appended(mod, monkeypatch):
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "turns": [{"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Hi.", "notes": []}],
        "rendered": "Mia:\nHi.", "queue": [], "marker": ""}))
    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}], "stream": False},
                       __user__={"email": "o@example.com"})
    assert "aiui:turns" not in out
    assert not out.endswith("\n")


async def test_a_marker_of_the_wrong_type_is_ignored(mod, monkeypatch):
    """The shape comes over HTTP and is not ours to trust."""
    p = mod.Pipe()
    monkeypatch.setattr(p, "_ask_tasks", AsyncMock(return_value={
        "turns": [{"agent": {"id": "agent-m", "name": "Mia"}, "answer": "Hi.", "notes": []}],
        "marker": ["not", "a", "string"]}))
    out = await p.pipe({"messages": [{"role": "user", "content": "hi mia"}], "stream": False},
                       __user__={"email": "o@example.com"})
    assert "Hi." in out and "not" not in out
```

Look at `tests/test_auto_router_pipe.py` for how it loads the module and drives `_agents_first`, and add the same three shapes there: `first_only` is sent alongside `route_only`; a marker is appended to the rendered text; an absent or non-string marker appends nothing. If that file has no test of `_agents_first` yet, model the loader on `test_io_gateway_pipe.py`'s `_load()` and drive `_agents_first` with the same fake client class as above.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_io_gateway_pipe.py tests/test_auto_router_pipe.py -q`
Expected: the new tests fail; `first_only` is not sent and no marker is appended.

- [ ] **Step 3: Send the flag and append the marker, in both pipes**

In `open-webui-functions/io_gateway_pipe.py`, in `_ask_tasks`, add `"first_only": True` to the JSON body beside `user_email`, `chat_id` and `messages`. In `pipe()`, replace the final render:

```python
        try:
            text = self._render(out)
        except Exception:                               # noqa: BLE001
            # Never let a shape we did not expect turn into a framework error
            # in somebody's chat window.
            return TASKS_DOWN
        # The page takes turns from here: the marker names every agent that
        # answers, and the page fetches the rest one at a time as separate
        # messages. An HTML comment renders as nothing.
        marker = out.get("marker") if isinstance(out, dict) else None
        if isinstance(marker, str) and marker.strip():
            text = text.rstrip() + "\n\n" + marker.strip()
        return text
```

In `open-webui-functions/auto_router_pipe.py`, in `_agents_first`, add `"first_only": True` beside `"route_only": True`, and replace the final return:

```python
        rendered = data.get("rendered")
        if not (isinstance(rendered, str) and rendered.strip()):
            return None
        marker = data.get("marker")
        if isinstance(marker, str) and marker.strip():
            rendered = rendered.rstrip() + "\n\n" + marker.strip()
        return rendered
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_io_gateway_pipe.py tests/test_auto_router_pipe.py -q`
Expected: all pass, including every pre-existing test in both files.

- [ ] **Step 5: Commit**

```bash
git add open-webui-functions/io_gateway_pipe.py open-webui-functions/auto_router_pipe.py mcp-servers/tasks/tests/test_io_gateway_pipe.py mcp-servers/tasks/tests/test_auto_router_pipe.py
git commit -m "Both pipes show one agent and carry the marker for the page"
```

---

### Task 4: The page takes turns

**Files:**
- Modify: `mcp-servers/gdrive/integrations-ui.js` (the agent-header section: `aiuiRefreshAgentNames`, `aiuiRewriteAgentHeader`, and the block from `// ----- One message per agent -----` through `aiuiSplitIntoAgentMessages`)
- Test: `mcp-servers/tasks/tests/test_agent_name_header.py` (structural), `mcp-servers/tasks/tests/browser/test_agents_take_turns_live.py` (real browser, skipped without `AIUI_LIVE=1`)

**Interfaces:**
- Consumes: `POST /api/tasks/agents/speak` from Task 2; the marker from Tasks 1 and 3; `aiuiAuthHeaders()`, `aiuiFirstTextNode`, `aiuiAgentLabelsIn`, `aiuiStripLabel`, `AIUI_AGENT_NAME_LINE_RE` already in the file.
- Produces: `aiuiTakeTurns(chatId)`, `aiuiAgentNameById`.

**What is removed:** the DOM-clone split (`aiuiSplitIntoAgentMessages` and its helpers `aiuiAgentColour`, `aiuiAgentAvatar`, `aiuiSwapAvatar`, `aiuiPathTo`, `aiuiFollowPath`, `aiuiStripLabelFromBlock`, `aiuiMessageContainer`, the `injectAgentSplitStyle` block and `AIUI_AGENT_COLOURS`). With `first_only`, a pipe reply holds exactly one agent, so the multi-agent DOM path can never trigger again and dead code is worse than none.

- [ ] **Step 1: Write the failing structural tests**

Append to `mcp-servers/tasks/tests/test_agent_name_header.py`:

```python


def test_the_page_takes_turns_from_the_marker():
    """Every further agent's reply is fetched by the page and written into
    the chat as a real message. That code must read the marker, wait for
    the save, call the speak route, write through the chat API, and
    soft navigate. Missing any one of those is a broken feature."""
    section = _agent_header_section(_js())
    assert "aiui:turns" in section
    assert "function aiuiTakeTurns(" in section
    assert "/api/tasks/agents/speak" in section
    assert "'/api/v1/chats/' + chatId" in section
    assert "aiuiWaitForSavedMarker" in section
    assert "aiuiSoftReload" in section


def test_the_page_never_writes_before_the_reply_is_saved():
    """Open WebUI saves the whole chat after a reply. Writing before that
    save would have the new message erased by it."""
    section = _agent_header_section(_js())
    body = _js_function(section, "aiuiTakeTurns")
    wait = body.find("aiuiWaitForSavedMarker(")
    save = body.find("aiuiSaveChat(")
    assert wait != -1 and save != -1
    assert wait < save, "the chat is written before the wait for the save"


def test_a_new_message_is_a_child_of_the_tail_with_the_agent_as_its_model():
    section = _agent_header_section(_js())
    body = _js_function(section, "aiuiTakeTurns")
    assert "parentId: tail.id" in body
    assert "model: next" in body
    assert "history.currentId = newId" in body


def test_the_dom_clone_split_is_gone():
    """A pipe reply now holds one agent, so the code that cloned rows for
    two can never run. Leaving it would be a second rendering path for a
    case that no longer exists."""
    section = _agent_header_section(_js())
    assert "aiuiSplitIntoAgentMessages" not in section
    assert "data-aiui-agent-clone" not in section
    assert "aiuiSwapAvatar" not in section
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_name_header.py -q`
Expected: the four new tests fail.

- [ ] **Step 3: Remove the clone split and add the turn taking**

In `mcp-servers/gdrive/integrations-ui.js`:

**(a)** Delete everything from the line `  // ----- One message per agent -----` up to but not including `  function aiuiRewriteAgentHeader(span) {`. That removes the style block, `AIUI_AGENT_COLOURS`, `aiuiAgentColour`, `aiuiAgentAvatar`, `aiuiSwapAvatar`, `aiuiPathTo`, `aiuiFollowPath`, `aiuiStripLabelFromBlock`, `aiuiMessageContainer` and `aiuiSplitIntoAgentMessages`.

**(b)** In `aiuiRefreshAgentNames`, keep a name for each id as well. Change the loop to:

```js
        var names = new Set();
        var byId = {};
        for (var i = 0; i < items.length; i++) {
          if (aiuiIsMintedAgent(items[i]) && items[i].name) {
            names.add(String(items[i].name).trim().toLowerCase());
            byId[items[i].id] = String(items[i].name).trim();
          }
        }
        aiuiAgentNames = names;
        aiuiAgentNameById = byId;
```

and declare `var aiuiAgentNameById = {};` beside `var aiuiAgentNames = new Set();`.

**(c)** Insert this block directly before `  function aiuiRewriteAgentHeader(span) {`:

```js
  // ===== Agents take turns =====
  // A pipe returns one reply and Open WebUI shows it as one message, and
  // no event a pipe can send makes a second one. So when two agents
  // answer, the pipe shows the first and hides a marker naming everybody
  // who answers, in order. This code finds that marker on the last reply,
  // waits until Open WebUI has saved it, asks the service to run the next
  // agent, writes the answer into the chat's own history as a new message
  // that is a child of the last one, and navigates away and back so the
  // chat loads again and shows it. Then the new tail carries the marker
  // for whoever is next, and the observer calls back in.
  //
  // Two facts this rests on, both checked on the live site 2026-09-04: the
  // chat renders an assistant message whose parent is another assistant
  // message as its own row; and a real link click is a SvelteKit soft
  // navigation, where a synthetic popstate is not.
  var AIUI_TURNS_RE = /<!--\s*aiui:turns\s+([^\s>]+)\s*-->/;
  var aiuiTurnsBusy = {};

  function aiuiChatIdFromUrl() {
    var m = /\/c\/([0-9a-f-]{36})/.exec(location.pathname);
    return m ? m[1] : null;
  }

  function aiuiParseTurns(content) {
    var m = AIUI_TURNS_RE.exec(content || '');
    if (!m) return null;
    var ids = m[1].split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    return ids.length ? ids : null;
  }

  function aiuiStripTurnsMarker(content) {
    return String(content || '').replace(AIUI_TURNS_RE, '').replace(/\s+$/, '');
  }

  // The label the pipe put at the top, "Ada:" on its own line. Text, not
  // DOM: this runs on the stored content.
  function aiuiStripLeadingLabelText(content) {
    var m = /^\s*[A-Za-z0-9 -]{1,40}:[ \t]*\r?\n/.exec(content || '');
    return m ? content.slice(m[0].length) : content;
  }

  // The messages on the current branch, root first. The history is a tree
  // and currentId names the tail, so walk parents and reverse.
  function aiuiChainFromHistory(history) {
    var msgs = history && history.messages ? history.messages : {};
    var id = history ? history.currentId : null;
    var chain = [];
    for (var guard = 0; id && msgs[id] && guard < 500; guard++) {
      chain.unshift(msgs[id]);
      id = msgs[id].parentId;
    }
    return chain;
  }

  function aiuiUuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 3 | 8)).toString(16);
    });
  }

  function aiuiTypingLine(text) {
    var el = document.getElementById('aiui-typing');
    if (!el) {
      el = document.createElement('div');
      el.id = 'aiui-typing';
      el.style.cssText = 'padding:.25rem 0 .75rem 3.75rem;opacity:.65;font-size:.9rem;';
      var rows = document.querySelectorAll('[id^="message-"]');
      var last = rows.length ? rows[rows.length - 1] : null;
      var slot = last && last.parentElement ? last.parentElement : null;
      if (slot && slot.parentElement) slot.parentElement.insertBefore(el, slot.nextSibling);
      else document.body.appendChild(el);
    }
    el.textContent = text;
  }

  function aiuiClearTypingLine() {
    var el = document.getElementById('aiui-typing');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  // SvelteKit intercepts a same-origin link click as a soft navigation.
  // Away to a fresh chat and back makes the chat component see its id
  // change and load again: about a second, no flash. If the rows have not
  // grown in five seconds the message is still saved, so reload the hard
  // way and accept the flash.
  function aiuiSoftReload(chatId) {
    function go(href) {
      var a = document.createElement('a');
      a.href = href;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    var before = document.querySelectorAll('[id^="message-"]').length;
    go('/');
    setTimeout(function () { go('/c/' + chatId); }, 400);
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      if (document.querySelectorAll('[id^="message-"]').length > before) { clearInterval(timer); return; }
      if (tries >= 20) { clearInterval(timer); location.reload(); }
    }, 250);
  }

  function aiuiFetchChat(chatId) {
    return fetch('/api/v1/chats/' + chatId, { headers: aiuiAuthHeaders() })
      .then(function (r) {
        if (!r.ok) throw new Error('chat fetch ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !data.chat || !data.chat.history) throw new Error('chat shape');
        return data;
      });
  }

  function aiuiSaveChat(chatId, chat) {
    return fetch('/api/v1/chats/' + chatId, {
      method: 'POST', headers: aiuiAuthHeaders(), body: JSON.stringify({ chat: chat })
    }).then(function (r) {
      if (!r.ok) throw new Error('chat save ' + r.status);
    });
  }

  // Open WebUI saves the whole chat after a reply completes. Anything
  // written before that save is replaced by it. So wait until the stored
  // tail is the reply that carries the marker.
  function aiuiWaitForSavedMarker(chatId) {
    var attempt = 0;
    function look() {
      return aiuiFetchChat(chatId).then(function (data) {
        var chain = aiuiChainFromHistory(data.chat.history);
        var tail = chain[chain.length - 1];
        if (tail && tail.role === 'assistant' && aiuiParseTurns(tail.content)) return data;
        if (++attempt >= 12) return null;
        return new Promise(function (r) { setTimeout(r, 500); }).then(look);
      });
    }
    return look();
  }

  function aiuiSpeak(chatId, agentId, chain) {
    var messages = chain.map(function (m) {
      return { role: m.role, content: aiuiStripTurnsMarker(m.content) };
    });
    return fetch('/api/tasks/agents/speak', {
      method: 'POST', headers: aiuiAuthHeaders(),
      body: JSON.stringify({ chat_id: chatId, agent_id: agentId, messages: messages })
    }).then(function (r) {
      if (r.status === 403) return { refused: true };
      if (!r.ok) throw new Error('speak ' + r.status);
      return r.json();
    });
  }

  function aiuiTakeTurns(chatId) {
    if (!chatId || aiuiTurnsBusy[chatId]) return;
    aiuiTurnsBusy[chatId] = true;

    var chat, history, chain, tail, turns, spoke, next, rest, nextName;
    aiuiWaitForSavedMarker(chatId).then(function (data) {
      if (!data) return null;
      chat = data.chat;
      history = chat.history;
      chain = aiuiChainFromHistory(history);
      tail = chain[chain.length - 1];
      turns = aiuiParseTurns(tail.content);

      if (!turns || turns.length < 2) {
        // A marker with nobody left to speak. Clean it off and stop.
        tail.content = aiuiStripTurnsMarker(tail.content);
        return aiuiSaveChat(chatId, chat).then(function () { return null; });
      }
      spoke = turns[0];
      next = turns[1];
      rest = turns.slice(2);
      nextName = aiuiAgentNameById[next] || next;

      // Claim the tail for its author, if the pipe wrote it. A message the
      // page wrote already carries its agent as its model.
      tail.content = aiuiStripTurnsMarker(tail.content);
      if (tail.model !== spoke) {
        tail.model = spoke;
        tail.modelName = aiuiAgentNameById[spoke] || spoke;
        tail.content = aiuiStripLeadingLabelText(tail.content);
      }

      aiuiTypingLine(nextName + ' is typing');
      return aiuiSpeak(chatId, next, chain).then(function (out) {
        return { out: out };
      }, function () {
        // Marker stays on the tail, so a reload can retry.
        aiuiTypingLine(nextName + ' did not answer');
        return null;
      });
    }).then(function (step) {
      if (!step) return;
      var out = step.out;

      if (out.refused) {
        // Not this person's agent any more. Drop it, keep the rest.
        if (rest.length) tail.content += '\n\n<!-- aiui:turns ' + [spoke].concat(rest).join(',') + ' -->';
        aiuiClearTypingLine();
        return aiuiSaveChat(chatId, chat).then(function () {
          if (rest.length) { aiuiTurnsBusy[chatId] = false; aiuiTakeTurns(chatId); }
        });
      }

      var answer = String(out.answer || '').trim();
      var notes = (out.notes || []).filter(function (n) { return typeof n === 'string'; });
      if (notes.length) answer = answer ? answer + '\n\n' + notes.join('\n') : notes.join('\n');
      if (!answer) answer = 'There was nothing to answer.';
      if (rest.length) answer += '\n\n<!-- aiui:turns ' + [next].concat(rest).join(',') + ' -->';

      var newId = aiuiUuid();
      history.messages[newId] = {
        id: newId, parentId: tail.id, childrenIds: [], role: 'assistant',
        content: answer, model: next, modelName: nextName, modelIdx: 0,
        done: true, timestamp: Math.floor(Date.now() / 1000)
      };
      tail.childrenIds = (tail.childrenIds || []).concat([newId]);
      history.currentId = newId;

      return aiuiSaveChat(chatId, chat).then(function () {
        aiuiClearTypingLine();
        aiuiSoftReload(chatId);
      }, function () {
        aiuiTypingLine('could not add ' + nextName + "'s reply");
        console.warn('[AIUI turns] reply not saved for', next, ':', answer);
      });
    }).catch(function (e) {
      console.warn('[AIUI turns]', e && e.message ? e.message : e);
    }).then(function () {
      aiuiTurnsBusy[chatId] = false;
    });
  }

  // Is this header span the last reply on the page? Only the tail can carry
  // a live marker, and a reloaded chat with twenty replies must not fetch
  // the chat twenty times.
  function aiuiIsLastReply(span) {
    var spans = document.querySelectorAll('#response-message-model-name');
    return spans.length > 0 && spans[spans.length - 1] === span;
  }
```

**(d)** In `aiuiRewriteAgentHeader`, replace the final strip/split block with:

```js
    // One agent per reply now, so the label below always repeats the
    // header and goes. If this is the last reply, the page also checks
    // the stored chat for a marker and takes the remaining turns.
    if (span.getAttribute('data-aiui-agent-stripped') === '1') return;
    span.setAttribute('data-aiui-agent-stripped', '1');
    aiuiStripLabel(body, scan.labels[0]);
    if (aiuiIsLastReply(span)) aiuiTakeTurns(aiuiChatIdFromUrl());
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_agent_name_header.py tests/test_connect_button.py -q`
Expected: all pass. Then `node -e "new Function(require('fs').readFileSync('mcp-servers/gdrive/integrations-ui.js','utf8')); console.log('parses')"` from the repo root.

- [ ] **Step 5: Write the live browser test, skipped without `AIUI_LIVE=1`**

Create `mcp-servers/tasks/tests/browser/test_agents_take_turns_live.py`. It runs only inside the tasks container against the live site, because that is the only place the whole path exists:

```python
"""Two agents, two real messages, one after the other. Live only.

Runs against the real site from inside the tasks container with AIUI_LIVE=1.
Nothing here is stubbed: the pipe, the service, the chat API and Open
WebUI's renderer are all the real ones, because three of this feature's
load-bearing facts were found only that way and no stub would have shown
them.
"""
import asyncio
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AIUI_LIVE") != "1",
                                reason="live site only; set AIUI_LIVE=1 in the tasks container")

HOST = "https://ai-ui.coolestdomain.win"
EMAIL = "ralphbenitez32@gmail.com"


async def _page(pw, token):
    browser = await pw.chromium.launch()
    ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
    await ctx.add_cookies([{"name": "token", "value": token,
                            "domain": "ai-ui.coolestdomain.win", "path": "/"}])
    page = await ctx.new_page()
    await page.goto(HOST + "/", wait_until="domcontentloaded")
    await page.evaluate("t => localStorage.setItem('token', t)", token)
    return browser, page


async def _rows(page):
    return await page.evaluate("""() => [...document.querySelectorAll('[id^="message-"]')].map(r => {
        const s = r.querySelector('#response-message-model-name');
        return { header: s ? s.textContent.trim() : null,
                 text: r.textContent.replace(/\\s+/g, ' ').trim().slice(0, 60) };
    })""")


async def test_hi_team_becomes_two_messages_one_after_another():
    import httpx
    from playwright.async_api import async_playwright
    from owui_token import mint_owui_token
    from routes_gateway import _owui_user_id_for

    uid = await _owui_user_id_for(EMAIL)
    token = mint_owui_token(uid, ttl_seconds=900)
    async with async_playwright() as pw:
        browser, page = await _page(pw, token)
        await page.goto(HOST + "/?models=auto_router.auto", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        box = page.locator("#chat-input, textarea, [contenteditable='true']").first
        await box.click()
        await box.fill("hi team, one short sentence each")
        await page.keyboard.press("Enter")

        # Ada first, alone.
        for _ in range(60):
            await page.wait_for_timeout(1000)
            rows = await _rows(page)
            heads = [r["header"] for r in rows if r["header"]]
            if len(heads) >= 1 and heads[0] not in ("Auto (Free)", "IO"):
                break
        first_seen = time.time()

        # Then Mia, as her own row.
        for _ in range(60):
            await page.wait_for_timeout(1000)
            rows = await _rows(page)
            heads = [r["header"] for r in rows if r["header"]]
            if len(heads) >= 2:
                break
        assert heads[:2] == ["Ada", "Mia"], rows
        assert time.time() - first_seen >= 1, "the second arrived with the first, not after it"

        chat_id = await page.evaluate("location.pathname.split('/c/')[1]")

        # A reload shows the same two rows, from stored data alone.
        await page.goto(HOST + "/c/" + chat_id, wait_until="networkidle")
        await page.wait_for_timeout(4000)
        rows = await _rows(page)
        assert [r["header"] for r in rows if r["header"]][:2] == ["Ada", "Mia"], rows

        # The stored chat: first message claimed for Ada, no marker anywhere.
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get("http://open-webui:8080/api/v1/chats/" + chat_id,
                            headers={"Authorization": "Bearer " + token})
            msgs = r.json()["chat"]["history"]["messages"].values()
        assistants = [m for m in msgs if m["role"] == "assistant"]
        assert [m["model"] for m in assistants][:2] == ["agent-scout-7d88", "agent-triage-256e"]
        assert not any("aiui:turns" in (m.get("content") or "") for m in msgs)
        assert not any((m.get("content") or "").startswith("Ada:") for m in assistants)

        await browser.close()
        async with httpx.AsyncClient(timeout=60) as c:
            await c.delete("http://open-webui:8080/api/v1/chats/" + chat_id,
                           headers={"Authorization": "Bearer " + token})
```

Confirm it is collected and skipped locally: `cd mcp-servers/tasks && python -m pytest tests/browser/test_agents_take_turns_live.py -q` prints `1 skipped`. It is run for real in Task 5.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/gdrive/integrations-ui.js mcp-servers/tasks/tests/test_agent_name_header.py mcp-servers/tasks/tests/browser/test_agents_take_turns_live.py
git commit -m "The page takes turns: each further agent is its own real message"
```

---

### Task 5: Deploy and verify on the live site

Not dispatched to a subagent; deploys to production. Presented to Ralph.

- [ ] **Step 1: Deploy tasks first**, so the page's endpoint exists before any page can call it. One `scp` of a gzipped tarball, `sed -i 's/\r$//'` after, rebuild with `docker compose -f docker-compose.unified.yml up -d --build tasks`, then `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`. Confirm `/api/tasks/agents/speak` answers 401 without a token and 403 for a foreign `agent_id` with one.

- [ ] **Step 2: Update both pipe rows** in Open WebUI with the existing `update_function.py` pattern (`io` and `auto_router`), then restart open-webui **once** and wait for 200 outside any retry loop. A retry loop that contains the restart has restarted it three times before.

- [ ] **Step 3: Deploy the page script** with `gunzip -c > /root/proxy-server/mcp-servers/gdrive/integrations-ui.js`, confirm the inode is unchanged and the hash matches inside the open-webui container.

- [ ] **Step 4: Run the live test** from inside the tasks container: `docker exec -e PYTHONPATH=/app -e AIUI_LIVE=1 -w /app tasks python -m pytest tests/browser/test_agents_take_turns_live.py -q -s`. It types "hi team" into the real page and asserts two rows in order, a second arrival after the first, the same two rows after a reload, and a stored chat with the first message claimed for Ada and no marker left.

- [ ] **Step 5: The three mutation checks the spec names**, each against the deployed page, restoring after each: with `aiuiWaitForSavedMarker` returning immediately, the first agent's message must be lost after the frontend's save; with the marker rendering removed from the pipe, the page must do nothing; with the membership check removed from `/agents/speak`, a stranger's token must be able to run somebody's agent.

- [ ] **Step 6: Ralph's browser.** Hard refresh, fresh chat on Auto (Free), "hi team". Ada, then Mia a few seconds later, each their own message.

- [ ] **Step 7: Stamp `.deploy-state`** (JSON with `sha`, `deployed_at`, `deployed_by`) and record in memory.

---

## Self-Review

**Spec coverage.** The flow, steps 1 to 5: Tasks 1, 3, 4. First message claimed for its agent: Task 4 (c) in `aiuiTakeTurns`. The marker, ids not names: Task 1 `turns_marker`, with the refinement to carry the author noted in Global Constraints. The service, `first_only` and the user route: Tasks 1 and 2. The page: Task 4. Every listed error: Task 4, the refused branch, the did-not-answer branch, the could-not-save branch, and the five-second hard-reload fallback in `aiuiSoftReload`. Removal of the DOM clone: Task 4 (a) and its structural test. Testing checklist: service items in Tasks 1 and 2, page items in the live test, the three mutations in Task 5. Deploy order tasks-first: Task 5.

**Placeholder scan.** No TBD, no "handle errors", every code step carries the code.

**Type consistency.** `chat()` returns `queue: list[str]` and `marker: str` (Task 1); both pipes read `marker` as a string and ignore anything else (Task 3); the page parses `aiui:turns` into ids and hands `agent_id` to `/api/tasks/agents/speak` (Task 4), whose body is `{chat_id, agent_id, messages}` and whose response is `{answer, notes, agent}` (Task 2), which the page reads as `out.answer`, `out.notes`. `_turn_for(user_email, agent, messages, names)` is called with the same four positional arguments in Tasks 1 and 2.

**One judgement recorded.** The spec says the marker names the remaining agents; this plan has it name every speaker with the author first, so the page can claim the first message by id without mapping a display name back to an id. Same information, one less lookup, one fewer way to be wrong.
