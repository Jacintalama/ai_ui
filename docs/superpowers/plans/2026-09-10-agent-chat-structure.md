# Agent Chat Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent chat panel a structure that can express state, so a
failure, a status and a conversation stop having to be dressed up as chat
bubbles.

**Architecture:** Five separable steps against the existing panel. The agent
state mapping is fixed first because it is smallest and independent. Then a
turn becomes one DOM block instead of loose bubbles, which everything after
it sits inside: failures render as failures, and a running agent says which
tool it is using. Conversations come last because they are the only step with
unknowns, three store functions that have never been called.

**Tech Stack:** Python 3.11, FastAPI, htmx 2.0.4 with the SSE extension,
server-rendered HTML fragments, Playwright for browser tests, pytest with
`asyncio_mode = auto`.

**Spec:** `docs/superpowers/specs/2026-09-10-agent-chat-structure-design.md`

## Global Constraints

- Run tests from `mcp-servers/tasks/`. Expect ~130 pre-existing errors from
  the `db_session` fixture with no local Postgres; confirm they say
  `ERROR at setup` and are not your change.
- One round at a time. Nothing in this plan may allow two rounds against one
  conversation.
- Every agent hears every message inside a conversation. Naming an agent
  means only they answer.
- No em-dashes or en-dashes in any string a person reads.
- Fragments are server-rendered HTML strings; every value that came from a
  person or a model goes through `esc()`.
- A missing or unrecognised value keeps today's behaviour. This panel is live
  for real users and nothing here may change an existing conversation.
- The status line is decoration. If a status event is lost the turn must
  still render.
- Deploy is not part of any task. Ralph deploys.

---

### Task 1: Agent state that answers a question somebody asks

Replaces Awake/Idle with Ready/Needs you. `AWAKE_FOR` and the ten minute
window go: they were invented to answer "is this agent alive", and an agent is
always alive and only sometimes busy.

**Files:**
- Modify: `mcp-servers/tasks/agent_activity.py`
- Modify: `mcp-servers/tasks/static/agents.html`
- Test: `mcp-servers/tasks/tests/test_agent_activity.py`
- Test: `mcp-servers/tasks/tests/browser/test_agents_page.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_shape(row, now)` returns `state` in
  `{"working", "ready", "waiting", "failed"}`. `AWAKE_FOR` and the
  `"awake"` and `"idle"` states no longer exist.

- [ ] **Step 1: Write the failing tests**

Replace the awake tests in `tests/test_agent_activity.py`. Delete
`test_a_finished_run_reads_as_awake_with_how_long_it_took`,
`test_an_agent_left_alone_long_enough_goes_idle`,
`test_talking_again_puts_it_back_to_awake`,
`test_awake_is_the_ten_minutes_ralph_asked_for`, and
`test_the_clock_runs_from_the_END_of_the_run_not_the_start`. Add:

```python
def test_a_finished_run_reads_as_ready():
    """Ralph: "fix the idle and active, it seems not accurate". It was
    accurate and it answered the wrong question. Ready is true whether it ran
    a second ago or last week, which is why it will stop feeling wrong."""
    out = _shape(_row(NOW - timedelta(seconds=30),
                      finished=NOW - timedelta(seconds=22),
                      status="completed"), NOW)
    assert out["state"] == "ready"
    assert out["last_duration_seconds"] == 8


def test_ready_does_not_go_stale():
    """The specific thing that felt wrong: an agent that worked perfectly an
    hour ago was reported as Idle, which reads as switched off."""
    old = _shape(_row(NOW - timedelta(days=3),
                      finished=NOW - timedelta(days=3), status="completed"), NOW)
    assert old["state"] == "ready"


def test_a_run_that_stopped_to_ask_needs_you():
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status="waiting"), NOW)
    assert out["state"] == "waiting"


def test_a_failed_run_reads_as_failed():
    out = _shape(_row(NOW - timedelta(seconds=30), finished=NOW,
                      status="failed"), NOW)
    assert out["state"] == "failed"


def test_a_run_in_flight_still_reads_as_working():
    assert _shape(_row(NOW - timedelta(seconds=5)), NOW)["state"] == "working"


def test_awake_is_gone():
    """Left behind, it would be two names for one thing and the page would
    have to handle both."""
    assert not hasattr(agent_activity, "AWAKE_FOR")
    for status in ("completed", "failed", "waiting"):
        out = _shape(_row(NOW - timedelta(seconds=9), finished=NOW,
                          status=status), NOW)
        assert out["state"] in ("ready", "failed", "waiting"), out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agent_activity.py -q -p no:randomly`
Expected: FAIL, `AttributeError` on the import of `AWAKE_FOR` at the top of
the file, plus `assert 'awake' == 'ready'`.

- [ ] **Step 3: Fix the import line in the test file**

```python
from agent_activity import (STALE_AFTER_CHANNEL, STALE_AFTER_SCHEDULE,
                            _shape)
```

- [ ] **Step 4: Replace the state mapping**

In `agent_activity.py`, delete the `AWAKE_FOR` constant and its comment
block, then replace the final return of `_shape` with:

```python
    # What somebody actually wants to know: is it doing something for me
    # right now, and did the last thing I asked for work. "Awake for ten
    # minutes" answered neither, which is why it felt wrong while being
    # perfectly accurate.
    status = row["status"]
    state = ("waiting" if status == "waiting"
             else "failed" if status == "failed"
             else "ready")
    return {"state": state,
            "last_status": status,
            "last_run_at": started.isoformat(),
            "last_duration_seconds": max(
                0, int((finished - started).total_seconds())),
            "source": row["source"]}
```

Also update the module docstring: it currently describes three live states
including AWAKE.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agent_activity.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Write the failing browser tests**

Replace the awake tests in `tests/browser/test_agents_page.py`. Delete
`test_a_recently_used_agent_reads_as_awake`,
`test_the_dot_is_green_when_the_agent_is_awake`,
`test_awake_is_still_green_but_does_not_pulse`,
`test_the_dot_is_amber_when_the_agent_is_resting`, and
`test_an_agent_stopped_for_approval_reads_as_blocked_not_idle`. Add:

```python
def test_a_finished_agent_reads_as_ready(page):
    _activity(page, {"agent-mine-a1b2": {
        "state": "ready", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    text = page.locator('[data-activity-for="agent-mine-a1b2"]').inner_text()
    assert "Ready" in text
    assert "Idle" not in text and "Awake" not in text
    assert "took 2s" in text


def test_ready_is_green_and_does_not_pulse(page):
    """Green because the agent is fine. No pulse: that is reserved for a run
    in flight, and spending it on every resting agent makes it mean nothing."""
    _activity(page, {"agent-mine-a1b2": {
        "state": "ready", "last_status": "completed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    dot = page.locator('[data-activity-for="agent-mine-a1b2"] .dot')
    assert dot.evaluate("el => getComputedStyle(el).backgroundColor") \
        == "rgb(74, 222, 128)"
    assert dot.evaluate("el => getComputedStyle(el).animationName") == "none"


def test_an_agent_waiting_on_you_says_so(page):
    _activity(page, {"agent-mine-a1b2": {
        "state": "waiting", "last_status": "waiting",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 2, "source": "channel"}})
    line = page.locator('[data-activity-for="agent-mine-a1b2"]')
    assert "Needs you" in line.inner_text()
    assert "waiting" in line.get_attribute("class")


def test_a_failed_agent_says_failed(page):
    _activity(page, {"agent-mine-a1b2": {
        "state": "failed", "last_status": "failed",
        "last_run_at": "2026-08-28T12:00:00+00:00",
        "last_duration_seconds": 3, "source": "channel"}})
    line = page.locator('[data-activity-for="agent-mine-a1b2"]')
    assert "Failed" in line.inner_text()
    assert "failed" in line.get_attribute("class")
```

- [ ] **Step 7: Run them to verify they fail**

Run: `python -m pytest tests/browser/test_agents_page.py -q -p no:randomly -k "ready or waiting or failed"`
Expected: FAIL, the line still says Idle.

- [ ] **Step 8: Rewrite paintActivity**

In `static/agents.html`, replace the block from
`var blocked = a.last_status === "failed"` down to the `el.innerHTML` that
follows it, with:

```javascript
        // One state, one word, one colour. The server decides; the page does
        // not re-derive it from last_status, which is how the old code ended
        // up with two sources of truth for the same fact.
        var STATE_WORD = { ready: "Ready", waiting: "Needs you",
                           failed: "Failed" };
        var state = STATE_WORD[a.state] ? a.state : "ready";
        el.classList.add(state);
        var bits = [];
        if (a.last_run_at) bits.push("used " + ago(a.last_run_at));
        if (a.last_duration_seconds !== null
            && a.last_duration_seconds !== undefined) {
          bits.push("took " + secs(a.last_duration_seconds));
        }
        el.innerHTML = '<span class="dot"></span><span>' + STATE_WORD[state]
          + (bits.length ? " · " + esc(bits.join(", ")) : "") + "</span>";
```

Replace the CSS rules `.card-activity.awake`, `.card-activity.awake .dot`,
`.card-activity.idle .dot` and `.card-activity.blocked .dot` with:

```css
  /* Green because the agent is fine, and NOT pulsing: the pulse is reserved
     for a run in flight, and spending it on every resting agent would make
     it mean nothing. */
  .card-activity.ready { color: #4ade80; }
  .card-activity.ready .dot { background: #4ade80; }
  .card-activity.waiting { color: #fbbf24; }
  .card-activity.waiting .dot { background: #fbbf24; }
  .card-activity.failed { color: #f87171; }
  .card-activity.failed .dot { background: #f87171; }
```

- [ ] **Step 9: Run the browser tests to verify they pass**

Run: `python -m pytest tests/browser/test_agents_page.py -q -p no:randomly`
Expected: PASS, all of them.

- [ ] **Step 10: Commit**

```bash
git add mcp-servers/tasks/agent_activity.py mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/test_agent_activity.py mcp-servers/tasks/tests/browser/test_agents_page.py
git commit -m "Agent states that answer a question somebody asks

Awake and Idle were accurate and answered the wrong question: nobody wants
to know whether an agent was used in the last ten minutes. Working, Ready,
Needs you and Failed answer what they do want. Ready is Ready whether it ran
a second ago or last week, which is the specific thing that felt wrong."
```

---

### Task 2: A turn is one block

Everything after this sits inside it. A turn is the person's message plus
every answer to it, in one DOM element with a header for status.

**Files:**
- Modify: `mcp-servers/tasks/agent_chat_render.py`
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Modify: `mcp-servers/tasks/static/agent-chat.css`
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py`

**Interfaces:**
- Consumes: `_shape` state names from Task 1 (not used here).
- Produces:
  - `render.turn_open(text: str) -> str` opens a turn block containing the
    person's message and an empty status row.
  - `render.turn_close() -> str` closes it.
  - `TURN_BODY_TARGET = "#agent-thread .aturn:last-child .aturn-body"`
  - `TURN_STATUS_TARGET = "#agent-thread .aturn:last-child .aturn-status"`
  - Task 3 and Task 4 swap into those two selectors.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_chat_render.py`:

```python
def test_a_turn_carries_the_message_and_a_place_for_answers():
    from agent_chat_render import turn_open
    html = turn_open("what is in my inbox?")
    assert "what is in my inbox?" in html
    assert "aturn-body" in html
    assert "aturn-status" in html


def test_a_turn_escapes_what_the_person_typed():
    from agent_chat_render import turn_open
    html = turn_open('<img src=x onerror="alert(1)">')
    assert "<img" not in html
    assert "&lt;img" in html


def test_the_turn_targets_point_inside_a_turn():
    """Two other files swap into these. A selector that stops matching does
    not error; the answers simply stop appearing."""
    from agent_chat_render import (TURN_BODY_TARGET, TURN_STATUS_TARGET,
                                   turn_open)
    html = turn_open("x")
    for target in (TURN_BODY_TARGET, TURN_STATUS_TARGET):
        leaf = target.rsplit(" ", 1)[-1].lstrip(".")
        assert leaf in html, (target, leaf)


def test_the_turn_targets_name_the_thread_on_the_page():
    import pathlib
    from agent_chat_render import TURN_BODY_TARGET
    page = (pathlib.Path(__file__).resolve().parents[1]
            / "static" / "agents.html").read_text(encoding="utf-8")
    assert 'id="%s"' % TURN_BODY_TARGET.split()[0].lstrip("#") in page
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k turn`
Expected: FAIL, `ImportError: cannot import name 'turn_open'`.

- [ ] **Step 3: Add the fragments**

In `agent_chat_render.py`, after `queued_bubble`:

```python
#: Where a running turn's answers and status land. The turn block is opened
#: by the send response and everything after it swaps into these, so the
#: selectors live here beside the element that creates them. Tests check both
#: halves: the classes come from turn_open, the id from agents.html.
TURN_BODY_TARGET = "#agent-thread .aturn:last-child .aturn-body"
TURN_STATUS_TARGET = "#agent-thread .aturn:last-child .aturn-status"


def turn_open(text: str) -> str:
    """One turn: the person's message, a status row, and room for answers.

    A turn rather than loose bubbles, because the panel had no way to say
    anything that was not an answer. Status, failures and what an agent is
    doing all had to be dressed up as chat messages, and a failure that looks
    like an answer is a failure people re-read as an answer.
    """
    return ('<div class="aturn">'
            '<div class="am user"><div class="ab">'
            f'{esc(text)}</div></div>'
            '<div class="aturn-status"></div>'
            '<div class="aturn-body"></div>')


def turn_close() -> str:
    """Closes the element turn_open left open."""
    return "</div>"
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k turn`
Expected: PASS.

- [ ] **Step 5: Write the failing test for the send route**

Add to `tests/test_agent_chat_queue.py`:

```python
async def test_a_new_message_opens_a_turn():
    s = store.get_session(_User.email)
    out = await _send("what is in my inbox?")
    body = out.body.decode()
    assert "aturn" in body
    assert "what is in my inbox?" in body
    assert "sse" in body.lower(), "the stream block is still needed"


async def test_a_queued_message_opens_its_own_turn():
    """It is a separate question and gets its own block, or its answers land
    inside the previous turn and belong to the wrong message."""
    s = store.get_session(_User.email)
    s.streaming = True
    out = await _send("and my calendar?")
    body = out.body.decode()
    assert "aturn" in body
    assert "hx-swap-oob" in body, "it must not append after the open turn"
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_chat_queue.py -q -p no:randomly -k "opens_a_turn or own_turn"`
Expected: FAIL, `assert 'aturn' in ...`.

- [ ] **Step 7: Open a turn from the send route**

In `routes_agent_chat.py::agent_chat_send`, replace
`return HTMLResponse(render.queued_bubble(body))` with:

```python
        # Its own turn, appended to the thread out of band so it lands after
        # the running turn rather than inside it. Its answers swap into
        # :last-child, which is this one from the moment it exists.
        return HTMLResponse(
            f'<div hx-swap-oob="beforeend:#agent-thread">'
            f'{render.turn_open(body)}{render.turn_close()}</div>')
```

and replace `resp = HTMLResponse(render.user_bubble(body) + render.stream_block())` with:

```python
    resp = HTMLResponse(render.turn_open(body) + render.turn_close()
                        + render.stream_block())
```

- [ ] **Step 8: Run it to verify it passes**

Run: `python -m pytest tests/test_agent_chat_queue.py -q -p no:randomly`
Expected: PASS, all of them.

- [ ] **Step 9: Point the stream at the turn**

In `agent_chat_render.py::stream_block`, replace the body of the returned
string with:

```python
    return ('<div class="astream" hx-ext="sse" '
            'sse-connect="/tasks/agents/chat/stream" sse-close="close">'
            f'<div sse-swap="message" hx-target="{TURN_BODY_TARGET}" '
            'hx-swap="beforeend"></div>'
            f'<div sse-swap="working" hx-target="{TURN_STATUS_TARGET}" '
            'hx-swap="innerHTML"></div>'
            '</div>')
```

- [ ] **Step 10: Replay a saved conversation as turns**

In `agent_chat_render.py::thread`, wrap each user message and the answers
that follow it. Replace the loop with:

```python
    out = []
    open_turn = False
    for m in messages or []:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            if open_turn:
                out.append(turn_close())
            out.append(turn_open(content))
            open_turn = True
            continue
        if role == "note":
            if content:
                out.append(note(content))
        elif role == "assistant":
            name = str(m.get("agent_name") or "Agent")
            if content:
                out.append(agent_bubble(name, content, m.get("replying_to")))
            awaiting = m.get("awaiting")
            if isinstance(awaiting, dict) and awaiting.get("calls"):
                out.append(approval_bubble(name, awaiting.get("ask_id", ""),
                                           awaiting["calls"]))
    if open_turn:
        out.append(turn_close())
    return "".join(out)
```

- [ ] **Step 11: Write the failing test for replay**

Add to `tests/test_agent_chat_render.py`:

```python
def test_a_replayed_conversation_groups_answers_into_turns():
    from agent_chat_render import thread
    html = thread([
        {"role": "user", "content": "one"},
        {"role": "assistant", "agent_name": "Mia", "content": "first"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "agent_name": "Ada", "content": "second"},
    ])
    assert html.count('class="aturn"') == 2
    assert html.count("</div>") >= 2
    assert html.index("first") < html.index("two"), "an answer escaped its turn"


def test_a_replay_with_no_messages_is_empty():
    from agent_chat_render import thread
    assert thread([]) == ""
    assert thread(None) == ""
```

- [ ] **Step 12: Run the render tests**

Run: `python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_queue.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 13: Style the turn**

Add to `static/agent-chat.css`:

```css
/* A turn is the person's message and everything that answered it. Grouping
   them gives status and failures somewhere to live that is not a bubble
   pretending to be a message. */
.aturn { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.aturn-status:empty { display: none; }
.aturn-body { display: flex; flex-direction: column; gap: 10px; }
```

- [ ] **Step 14: Run every chat test**

Run: `python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_queue.py tests/test_agent_chat_round.py tests/test_agent_chat_room.py tests/test_agent_chat_page.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add mcp-servers/tasks/agent_chat_render.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/static/agent-chat.css mcp-servers/tasks/tests/test_agent_chat_render.py mcp-servers/tasks/tests/test_agent_chat_queue.py
git commit -m "A turn is one block, not loose bubbles

The panel showed a stream of bubbles and had no way to express state, so
anything that was not an answer had to be dressed as one. A turn now holds
the message and every answer to it, with a status row of its own."
```

---

### Task 3: A failure looks like a failure

**Files:**
- Modify: `mcp-servers/tasks/agent_chat_render.py`
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Modify: `mcp-servers/tasks/static/agent-chat.css`
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py`

**Interfaces:**
- Consumes: `TURN_BODY_TARGET` from Task 2.
- Produces: `render.failure(name: str, reason: str, fix: str = "") -> str`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_failure_is_not_a_bubble():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.")
    assert "afail" in html
    assert 'class="am agent"' not in html, "it renders as an answer"
    assert "Ada" in html
    assert "The free models are all busy." in html


def test_a_failure_can_carry_the_fix():
    from agent_chat_render import failure
    html = failure("Ada", "The free models are all busy.",
                   "Ada is set to Auto (Free). Pick a specific model.")
    assert "Pick a specific model." in html


def test_a_failure_escapes_everything():
    from agent_chat_render import failure
    html = failure("<b>x</b>", "<i>y</i>", "<u>z</u>")
    for tag in ("<b>", "<i>", "<u>"):
        assert tag not in html
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k failure`
Expected: FAIL, `ImportError: cannot import name 'failure'`.

- [ ] **Step 3: Add the fragment**

```python
def failure(name: str, reason: str, fix: str = "") -> str:
    """An agent that could not answer, drawn as a failure.

    Deliberately not a bubble. These used to arrive as prose in the thread,
    in the same shape as an answer, and a failure that looks like an answer
    is one people re-read as an answer.
    """
    tail = f'<div class="afail-fix">{esc(fix)}</div>' if fix else ""
    return ('<div class="afail">'
            f'<div class="afail-what">{esc(name)} could not answer. '
            f'{esc(reason)}</div>{tail}</div>')
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k failure`
Expected: PASS.

- [ ] **Step 5: Write the failing test for the round**

Add to `tests/test_agent_chat_queue.py`:

```python
async def test_a_failed_agent_renders_as_a_failure(monkeypatch):
    """_turn_for never raises; it returns the failure sentence as an answer,
    which is exactly how a failure became a bubble."""
    import routes_agent_turn as rt
    s = store.get_session(_User.email)
    await _send("hi")

    async def failing(email, agent, history, names=()):
        return {"answer": rt._turn_failed_sentence("Ada"), "notes": [],
                "agent": {"id": "agent-a", "name": "Ada"}}

    monkeypatch.setattr(chat, "_turn_for", failing)
    monkeypatch.setattr(chat, "_agents_for",
                        lambda e: _agents_stub())
    monkeypatch.setattr(chat, "_keep_within_budget",
                        lambda e, sess, a: _nothing())
    monkeypatch.setattr(store, "save_chat", lambda e, sess: _nothing())
    events = []
    resp = await chat.agent_chat_stream(request=_Req(), user=_User())
    async for event in resp.body_iterator:
        events.append(str(event))
    assert any("afail" in e for e in events), events
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_chat_queue.py -q -p no:randomly -k renders_as_a_failure`
Expected: FAIL, no `afail` in the events.

- [ ] **Step 7: Recognise a failed turn in the round**

In `routes_agent_chat.py::_run_round`, immediately after
`answer = out.get("answer") or ""`, add:

```python
        # _turn_for never raises: one agent blowing up must not cost the
        # others their answer. So a failure arrives here as an ordinary
        # answer string, and this is the only place that can tell.
        import routes_agent_turn as _rt
        if answer == _rt._turn_failed_sentence(name):
            messages.append({"role": "failure", "agent_name": name,
                             "content": answer})
            yield {"event": "message",
                   "data": render.failure(name, "Something went wrong on our "
                                          "side. Nothing was changed.")}
            continue
```

Move the import to the top of the file rather than inside the function if
`routes_agent_turn` is already imported there.

- [ ] **Step 8: Replay a stored failure**

In `agent_chat_render.py::thread`, inside the loop, add before the
`assistant` branch:

```python
        if role == "failure":
            out.append(failure(str(m.get("agent_name") or "That agent"),
                               "Something went wrong on our side. "
                               "Nothing was changed."))
            continue
```

- [ ] **Step 9: Run the tests**

Run: `python -m pytest tests/test_agent_chat_queue.py tests/test_agent_chat_render.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 10: Style it**

```css
/* Not a bubble. A failure that looks like an answer is one people re-read
   as an answer. */
.afail { border-left: 2px solid #f87171; padding: 6px 0 6px 10px;
         font-size: 12.5px; color: var(--muted, #8b8b96); line-height: 1.5; }
.afail-fix { margin-top: 3px; color: var(--text-2, #b8b8c0); }
```

- [ ] **Step 11: Commit**

```bash
git add mcp-servers/tasks/agent_chat_render.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/static/agent-chat.css mcp-servers/tasks/tests/test_agent_chat_render.py mcp-servers/tasks/tests/test_agent_chat_queue.py
git commit -m "A failure looks like a failure

They arrived as prose in the thread, in the same shape as an answer, so
people re-read them as answers."
```

---

### Task 4: An agent says what it is doing

**Files:**
- Modify: `mcp-servers/tasks/agent_chat_render.py`
- Modify: `mcp-servers/tasks/routes_agent_turn.py`
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Test: `mcp-servers/tasks/tests/test_agent_chat_render.py`

**Interfaces:**
- Consumes: `TURN_STATUS_TARGET` from Task 2.
- Produces: `render.working(name: str, doing: str = "") -> str`, one extra
  optional argument on the existing function.
  `rt._turn_for(email, agent, messages, names, on_tool=None)`, where `on_tool`
  is `Callable[[str], None]` called with each tool name before it runs.

- [ ] **Step 1: Write the failing test**

```python
def test_working_can_say_what_it_is_doing():
    from agent_chat_render import working
    assert "reading your mail" in working("Mia", "reading your mail")
    assert "Mia" in working("Mia", "reading your mail")


def test_working_without_a_task_reads_as_before():
    from agent_chat_render import working
    assert "Mia is working" in working("Mia")


def test_a_known_tool_is_named_in_plain_words():
    """A person reading the panel should not have to know that
    list_unread_emails is what reading their mail is called."""
    from agent_chat_render import doing_words
    assert doing_words("list_unread_emails") == "reading your mail"
    assert doing_words("find_skills") == "looking for a skill"
    assert doing_words("create_schedule") == "setting up a schedule"


def test_an_unknown_tool_falls_back_to_something_true():
    from agent_chat_render import doing_words
    assert doing_words("my_clickup_whatever") == "using a tool"
    assert doing_words("") == "using a tool"
    assert doing_words(None) == "using a tool"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k "working or doing"`
Expected: FAIL, `ImportError: cannot import name 'doing_words'`.

- [ ] **Step 3: Add the words and widen working**

```python
#: What a tool is doing, in words a person reading the panel understands.
#: Anything not named here falls back to something true rather than to the
#: method name, which means nothing outside this codebase.
_DOING = {
    "list_unread_emails": "reading your mail",
    "list_important_emails": "reading your mail",
    "list_recent_emails": "reading your mail",
    "search_emails": "searching your mail",
    "read_email": "reading a message",
    "draft_email": "writing a draft",
    "send_email": "sending an email",
    "reply_to_email": "writing a reply",
    "list_calendar_events": "checking your calendar",
    "create_calendar_event": "adding to your calendar",
    "search_drive": "searching your files",
    "list_drive_files": "looking through your files",
    "read_drive_file": "reading a file",
    "create_document": "writing a document",
    "create_excel": "building a spreadsheet",
    "create_simple_excel": "building a spreadsheet",
    "create_dashboard": "building a dashboard",
    "create_simple_dashboard": "building a dashboard",
    "find_skills": "looking for a skill",
    "use_skill": "reading a skill",
    "create_schedule": "setting up a schedule",
    "list_my_schedules": "checking your schedules",
    "remember": "saving that",
    "my_account": "checking your account",
    "list_my_apps": "looking at your apps",
}


def doing_words(tool_name) -> str:
    """Plain words for one tool call."""
    if not isinstance(tool_name, str):
        return "using a tool"
    return _DOING.get(tool_name.strip(), "using a tool")


def working(name: str, doing: str = "") -> str:
    """Which agent is running right now, and what it is doing.

    A round of three agents that each use tools can hold the stream open for
    minutes. Without this line a slow round is indistinguishable from a broken
    one, and without `doing` it is indistinguishable from a stuck one.
    """
    if doing:
        return (f'<div class="aworking">{esc(name)} is '
                f'{esc(doing)}...</div>')
    return f'<div class="aworking">{esc(name)} is working...</div>'
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_agent_chat_render.py -q -p no:randomly -k "working or doing"`
Expected: PASS.

- [ ] **Step 5: Add the seam**

In `routes_agent_turn.py::_run_turn`, add an `on_tool=None` parameter and
pass a wrapper into `_chat` via `agent_runner.execute_tool_call`. Because
`_chat` reaches `execute_tool_call` as a module global, the honest seam is a
parameter on `_chat` itself. In `agent_runner.py::_chat`, add
`on_tool=None` to the signature and, immediately before
`result = await execute_tool_call(...)`, add:

```python
                if on_tool is not None:
                    # Before it runs, not after: the panel is saying what is
                    # happening now, and a tool can take thirty seconds.
                    try:
                        on_tool(name)
                    except Exception:               # noqa: BLE001
                        # Decoration. A broken status callback must never
                        # cost somebody their turn.
                        logger.warning("status callback failed",
                                       exc_info=True)
```

Thread `on_tool` through `_run_turn` and `_turn_for` as a keyword argument
defaulting to `None`.

- [ ] **Step 6: Write the test**

Add to `tests/test_agent_stale_model.py`:

```python
async def test_the_tool_callback_fires_before_the_tool(monkeypatch):
    order = []

    async def two_rounds(payload, token, timeout=None):
        if len(order) == 0:
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "1", "type": "function",
                                "function": {"name": "list_unread_emails",
                                             "arguments": "{}"}}]}}]}
        return {"choices": [{"message": {"content": "done"}}]}

    async def ran(tool_call, user_email, allowed=None, agent_id=None):
        order.append("ran")
        return "ok"

    monkeypatch.setattr(agent_runner, "_post_chat", two_rounds)
    monkeypatch.setattr(agent_runner, "execute_tool_call", ran)
    answer, _n = await agent_runner._chat(
        token="t", model="m", messages=[{"role": "user", "content": "hi"}],
        tool_ids=["gmail"], user_email="who@example.com",
        tool_mode="read_only",
        on_tool=lambda name: order.append("said:" + name))
    assert order == ["said:list_unread_emails", "ran"], order
    assert answer == "done"


async def test_a_broken_callback_does_not_cost_the_turn(monkeypatch):
    """Decoration must never be load-bearing."""
    calls = []

    async def two_rounds(payload, token, timeout=None):
        if not calls:
            calls.append(1)
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "1", "type": "function",
                                "function": {"name": "x", "arguments": "{}"}}]}}]}
        return {"choices": [{"message": {"content": "done"}}]}

    async def ran(tool_call, user_email, allowed=None, agent_id=None):
        return "ok"

    def explode(name):
        raise RuntimeError("no")

    monkeypatch.setattr(agent_runner, "_post_chat", two_rounds)
    monkeypatch.setattr(agent_runner, "execute_tool_call", ran)
    answer, _n = await agent_runner._chat(
        token="t", model="m", messages=[{"role": "user", "content": "hi"}],
        tool_ids=["gmail"], user_email="who@example.com",
        tool_mode="read_only", on_tool=explode)
    assert answer == "done"
```

- [ ] **Step 7: Run them**

Run: `python -m pytest tests/test_agent_stale_model.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 8: Emit the status from the round**

`_turn_for` is awaited as one unit, so a synchronous callback cannot yield
from the generator. Run the turn as a task and report what the callback has
collected while it runs. In `routes_agent_chat.py::_run_round`, replace

```python
        out = await _turn_for(email, agent, turn_history, names)
```

with

```python
        # The turn runs as a task so the status can be reported WHILE it
        # happens. A tool call can take thirty seconds, and a line that only
        # appears afterwards is not a status, it is a receipt.
        said = []
        running = asyncio.create_task(
            _turn_for(email, agent, turn_history, names,
                      on_tool=said.append))
        last = None
        while not running.done():
            await asyncio.sleep(0.25)
            if said and said[-1] != last:
                last = said[-1]
                yield {"event": "working",
                       "data": render.working(name,
                                              render.doing_words(last))}
        out = await running
```

Add `import asyncio` at the top of the file if it is not already there.

- [ ] **Step 9: Run every chat and turn test**

Run: `python -m pytest tests/test_agent_chat_render.py tests/test_agent_chat_queue.py tests/test_agent_stale_model.py tests/test_agent_turn_endpoint.py tests/test_agent_tool_loop.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add mcp-servers/tasks/agent_chat_render.py mcp-servers/tasks/agent_runner.py mcp-servers/tasks/routes_agent_turn.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/tests/
git commit -m "An agent says what it is doing

Working and nothing else could mean waiting on a model, running a tool, or
being stuck. The turn loop already knew; the panel was never told."
```

---

### Task 5: Conversations

The only step with unknowns: `list_chats`, `load_chat` and `delete_chat` are
written, untested and have never been called.

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Modify: `mcp-servers/tasks/agent_chat_render.py`
- Modify: `mcp-servers/tasks/static/agents.html`
- Modify: `mcp-servers/tasks/static/agent-chat.css`
- Test: `mcp-servers/tasks/tests/test_agent_chat_conversations.py`

**Interfaces:**
- Consumes: `store.list_chats(email)`, `store.load_chat(email, chat_id)`,
  `store.delete_chat(email, chat_id)`.
- Produces: `GET /tasks/agents/chat/chats`, `POST /tasks/agents/chat/open`
  (form field `chat_id`), `POST /tasks/agents/chat/new`,
  `POST /tasks/agents/chat/delete` (form field `chat_id`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_chat_conversations.py`:

```python
"""More than one conversation, using the store functions that already exist.

They are written, untested and have never been called from anywhere, so
these are the first time any of them runs.
"""
import pytest

import agent_chat_store as store
import routes_agent_chat as chat


class _User:
    email = "someone@example.com"


@pytest.fixture(autouse=True)
def clean():
    store._SESSIONS.clear()
    yield
    store._SESSIONS.clear()


async def test_switching_loads_the_other_conversation(monkeypatch):
    async def load(email, chat_id):
        return {"id": chat_id, "title": "Invoices",
                "messages": [{"role": "user", "content": "chase them"}],
                "summary": "", "pending": {}}

    monkeypatch.setattr(store, "load_chat", load)
    monkeypatch.setattr(store, "save_chat", lambda e, s: _nothing())
    s = store.get_session(_User.email)
    s.messages = [{"role": "user", "content": "old"}]
    await chat.agent_chat_open(chat_id="abc", user=_User())
    assert s.chat_id == "abc"
    assert s.messages == [{"role": "user", "content": "chase them"}]


async def test_switching_mid_round_does_not_staple_the_answer_on(monkeypatch):
    """The generation guard already exists for New chat. Switching has to bump
    it too, or a round still unwinding writes its answer into the conversation
    somebody just opened."""
    async def load(email, chat_id):
        return {"id": chat_id, "title": "x", "messages": [], "summary": "",
                "pending": {}}

    monkeypatch.setattr(store, "load_chat", load)
    monkeypatch.setattr(store, "save_chat", lambda e, s: _nothing())
    s = store.get_session(_User.email)
    before = s.generation
    await chat.agent_chat_open(chat_id="abc", user=_User())
    assert s.generation > before


async def test_opening_a_conversation_that_is_not_yours_changes_nothing(
        monkeypatch):
    """load_chat filters on user_email, so somebody else's id returns None.
    The session must be left exactly as it was."""
    async def load(email, chat_id):
        return None

    monkeypatch.setattr(store, "load_chat", load)
    s = store.get_session(_User.email)
    s.messages = [{"role": "user", "content": "mine"}]
    await chat.agent_chat_open(chat_id="someone-elses", user=_User())
    assert s.messages == [{"role": "user", "content": "mine"}]


async def test_a_new_conversation_starts_empty(monkeypatch):
    monkeypatch.setattr(store, "save_chat", lambda e, s: _nothing())
    s = store.get_session(_User.email)
    s.messages = [{"role": "user", "content": "old"}]
    s.queued = ["typed into the old one"]
    await chat.agent_chat_new(user=_User())
    assert s.messages == []
    assert s.queued == []
    assert s.chat_id is None


async def test_the_list_says_which_one_is_open(monkeypatch):
    async def listing(email):
        return [{"id": "a", "title": "Inbox"}, {"id": "b", "title": "Invoices"}]

    monkeypatch.setattr(store, "list_chats", listing)
    s = store.get_session(_User.email)
    s.chat_id = "b"
    out = await chat.agent_chat_chats(user=_User())
    body = out.body.decode()
    assert "Inbox" in body and "Invoices" in body
    assert 'aria-current="true"' in body


async def _nothing():
    return None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agent_chat_conversations.py -q -p no:randomly`
Expected: FAIL, `AttributeError: module 'routes_agent_chat' has no attribute
'agent_chat_open'`.

- [ ] **Step 3: Add the routes**

In `routes_agent_chat.py`:

```python
@router.get("/tasks/agents/chat/chats", include_in_schema=False)
async def agent_chat_chats(user: CurrentUser = Depends(current_user)
                           ) -> HTMLResponse:
    """This person's conversations, newest first."""
    s = store.get_session(user.email)
    try:
        rows = await store.list_chats(user.email)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not list the conversations")
        rows = []
    return HTMLResponse(render.chat_list(rows, s.chat_id))


@router.post("/tasks/agents/chat/open", include_in_schema=False)
async def agent_chat_open(chat_id: str = Form(...),
                          user: CurrentUser = Depends(current_user)
                          ) -> HTMLResponse:
    """Switch to another conversation.

    load_chat filters on user_email, so an id belonging to somebody else
    returns None and the session is left exactly as it was.
    """
    s = store.get_session(user.email)
    try:
        row = await store.load_chat(user.email, chat_id)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not open conversation %s", chat_id)
        row = None
    if not row:
        return HTMLResponse(render.thread(s.messages))
    if s.chat_id:
        try:
            await store.save_chat(user.email, s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not save before switching")
    # Replaced, never cleared in place, and the generation bumped: a round
    # still unwinding must not write its answer into the conversation
    # somebody just opened.
    s.messages = list(row.get("messages") or [])
    s.pending = dict(row.get("pending") or {})
    s.summary = str(row.get("summary") or "")
    s.summarised_upto = 0
    s.queued = []
    s.streaming = False
    s.chat_id = str(row["id"])
    s.generation += 1
    return HTMLResponse(render.thread(s.messages))


@router.post("/tasks/agents/chat/new", include_in_schema=False)
async def agent_chat_new(user: CurrentUser = Depends(current_user)
                         ) -> HTMLResponse:
    """Start a conversation, keeping the one that is open."""
    s = store.get_session(user.email)
    if s.chat_id:
        try:
            await store.save_chat(user.email, s)
        except Exception:                                   # noqa: BLE001
            log.exception("agent chat: could not save before starting a new one")
    s.messages = []
    s.pending = {}
    s.summary = ""
    s.summarised_upto = 0
    s.queued = []
    s.streaming = False
    s.chat_id = None
    s.generation += 1
    return HTMLResponse(render.empty_thread())


@router.post("/tasks/agents/chat/delete", include_in_schema=False)
async def agent_chat_delete(chat_id: str = Form(...),
                            user: CurrentUser = Depends(current_user)
                            ) -> HTMLResponse:
    """Remove one conversation. Scoped to the caller by the query itself."""
    s = store.get_session(user.email)
    try:
        await store.delete_chat(user.email, chat_id)
    except Exception:                                       # noqa: BLE001
        log.exception("agent chat: could not delete conversation %s", chat_id)
    if s.chat_id == chat_id:
        s.messages = []
        s.pending = {}
        s.summary = ""
        s.queued = []
        s.chat_id = None
        s.generation += 1
    try:
        rows = await store.list_chats(user.email)
    except Exception:                                       # noqa: BLE001
        rows = []
    return HTMLResponse(render.chat_list(rows, s.chat_id))
```

- [ ] **Step 4: Add the list fragment**

In `agent_chat_render.py`:

```python
def chat_list(rows, open_id) -> str:
    """The conversations, newest first, with the open one marked."""
    if not rows:
        return '<div class="achats-empty">No other conversations yet.</div>'
    out = []
    for row in rows:
        rid = str(row.get("id") or "")
        title = str(row.get("title") or "Untitled")
        current = ' aria-current="true"' if rid == open_id else ""
        out.append(
            f'<button type="button" class="achat" data-chat="{esc(rid)}"'
            f'{current} hx-post="/tasks/agents/chat/open" '
            f'hx-vals=\'{{"chat_id": "{esc(rid)}"}}\' '
            'hx-target="#agent-thread" hx-swap="innerHTML">'
            f'{esc(title)}</button>')
    return "".join(out)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_agent_chat_conversations.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Put the control on the panel**

In `static/agents.html`, replace the `ap-head` block with:

```html
  <div class="ap-head">
    <h2>Chat with your agents</h2>
    <button class="btn" type="button" id="ap-chats"
            aria-expanded="false">Conversations</button>
    <button class="btn" type="button" id="ap-new"
            hx-post="/tasks/agents/chat/new"
            hx-target="#agent-thread" hx-swap="innerHTML">New</button>
    <button class="btn" type="button" id="ap-clear">Clear</button>
  </div>
  <!-- Behind a control rather than a third column: the common case is one
       conversation, and a permanently visible list of one is wasted width in
       a panel that is already narrow. -->
  <div class="achats" id="ap-chat-list" hidden
       hx-get="/tasks/agents/chat/chats" hx-trigger="load"
       hx-swap="innerHTML"></div>
```

- [ ] **Step 7: Wire the control**

In `static/agent-chat.js`, add:

```javascript
  // Behind a control. The list is refreshed on open rather than kept live:
  // it changes only when somebody starts, switches or deletes one.
  var chatsBtn = document.getElementById("ap-chats");
  if (chatsBtn) {
    chatsBtn.addEventListener("click", function () {
      var list = document.getElementById("ap-chat-list");
      var open = list.hidden;
      list.hidden = !open;
      chatsBtn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && window.htmx) window.htmx.trigger(list, "load");
    });
  }
```

- [ ] **Step 8: Style it**

```css
.achats { display: flex; flex-direction: column; gap: 4px; padding: 8px 12px;
          border-bottom: 1px solid var(--border, rgba(255,255,255,.09)); }
.achat { text-align: left; background: none; border: 0; padding: 6px 8px;
         border-radius: 8px; color: var(--text-2, #b8b8c0); font: inherit;
         cursor: pointer; }
.achat:hover { background: var(--surface-2, #212121); color: var(--text, #fff); }
.achat[aria-current="true"] { color: var(--accent, #7c8cff); font-weight: 600; }
.achats-empty { padding: 8px 12px; font-size: 12px;
                color: var(--muted, #8b8b96); }
```

- [ ] **Step 9: Write the browser test**

Create `tests/browser/test_agent_conversations.py` modelled on
`tests/browser/test_graph_view.py`: serve `agents.html` from a temp
directory, stub `**/api/tasks/agents/chat/**` and `**/api/**`, then:

```python
def test_the_list_is_hidden_until_asked_for(page):
    assert not page.locator("#ap-chat-list").is_visible()


def test_the_control_opens_and_closes_it(page):
    page.locator("#ap-chats").click()
    page.wait_for_timeout(150)
    assert page.locator("#ap-chat-list").is_visible()
    page.locator("#ap-chats").click()
    page.wait_for_timeout(150)
    assert not page.locator("#ap-chat-list").is_visible()
```

- [ ] **Step 10: Run everything**

Run: `python -m pytest tests/test_agent_chat_conversations.py tests/browser/test_agent_conversations.py tests/test_agent_chat_queue.py tests/test_agent_chat_render.py tests/test_agent_chat_room.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/agent_chat_render.py mcp-servers/tasks/static/agents.html mcp-servers/tasks/static/agent-chat.js mcp-servers/tasks/static/agent-chat.css mcp-servers/tasks/tests/
git commit -m "More than one conversation

The store has held one row per conversation since the panel shipped, and
list_chats, load_chat and delete_chat were written, untested and never
called. Switching bumps the generation the same way New chat does, or a round
still unwinding writes its answer into the conversation somebody just opened."
```

---

---

### Task 6: Say when a skill was left out

The spec asks for a quiet line of what a turn cost, on demand. Most of it is
optional; one part is not. When too many skills are ticked, `brief_for` cuts
to fit and names what it dropped **to the agent**. The person who ticked the
box is told nothing, and their agent appears to ignore a skill they chose.

**Files:**
- Modify: `mcp-servers/tasks/agent_skills.py`
- Modify: `mcp-servers/tasks/routes_agent_chat.py`
- Test: `mcp-servers/tasks/tests/test_agent_skills.py`

**Interfaces:**
- Consumes: `render.note` (existing), `agent_skills.brief_for` (existing).
- Produces: `agent_skills.dropped_for(meta) -> list[str]`, the skills that
  would not fit, in the order they were chosen.

- [ ] **Step 1: Write the failing test**

```python
def test_the_skills_that_did_not_fit_can_be_named(monkeypatch):
    """brief_for already knows. Only the agent was told, and the person who
    ticked the box saw an agent quietly ignoring their choice."""
    monkeypatch.setattr(agent_skills, "MAX_TOTAL_CHARS", 1500)
    every = [s["name"] for s in agent_skills.catalogue()]
    dropped = agent_skills.dropped_for({"skillIds": every})
    assert dropped
    assert set(dropped) <= set(every)
    assert every[0] not in dropped, "it dropped the first one chosen"


def test_nothing_is_dropped_when_it_all_fits():
    assert agent_skills.dropped_for({"skillIds": ["inbox-triage"]}) == []
    assert agent_skills.dropped_for({}) == []
    assert agent_skills.dropped_for(None) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agent_skills.py -q -p no:randomly -k dropped`
Expected: FAIL, `AttributeError: module 'agent_skills' has no attribute
'dropped_for'`.

- [ ] **Step 3: Extract what brief_for already computes**

In `agent_skills.py`, add:

```python
def dropped_for(meta) -> list:
    """The chosen skills that will not fit in the brief, in chosen order.

    brief_for makes exactly this decision and tells the agent. Nobody tells
    the person who ticked the boxes, so their agent looks like it is ignoring
    a skill they picked on purpose.
    """
    picked = selected(meta)
    if not picked:
        return []
    used = 0
    dropped = []
    for skill in picked:
        block = "

## Skill: %s
%s" % (skill["name"], skill["body"])
        if used + len(block) > MAX_TOTAL_CHARS:
            dropped.append(skill["name"])
            continue
        used += len(block)
    return dropped
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_agent_skills.py -q -p no:randomly -k dropped`
Expected: PASS.

- [ ] **Step 5: Say it once per round**

In `routes_agent_chat.py::_run_round`, immediately after
`speakers, may_pass = _speakers_for(asked, agents)`, add:

```python
    # Said once per round, not once per agent: with three agents holding the
    # same overfull list, three identical notes would be worse than none.
    over = []
    for agent in speakers:
        for name in agent_skills.dropped_for(agent.get("meta")):
            if name not in over:
                over.append(name)
    if over:
        line = ("Some skills did not fit this time: %s. Untick a few on the "
                "agent's card if you need them." % ", ".join(over[:5]))
        messages.append({"role": "note", "content": line})
        yield {"event": "message", "data": render.note(line)}
```

Add `import agent_skills` at the top of the file if it is not already there.

- [ ] **Step 6: Run the chat tests**

Run: `python -m pytest tests/test_agent_chat_queue.py tests/test_agent_chat_round.py tests/test_agent_skills.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/agent_skills.py mcp-servers/tasks/routes_agent_chat.py mcp-servers/tasks/tests/test_agent_skills.py
git commit -m "Say when a skill was left out

brief_for already cuts to fit and names what it dropped, to the agent. The
person who ticked the box was told nothing and saw an agent quietly ignoring
a skill they chose on purpose."
```

## Verification before this is called done

The last two defects in this panel were both the browser half being wrong
while the server half was right, and neither was findable from the test
suite. So, on the real site, signed in, before this is reported complete:

1. Send three messages in a row without waiting. All three appear as separate
   turns, in order, each with its answers inside it.
2. Watch the status line during a turn that uses a tool. It names the tool in
   plain words.
3. Set an agent to Auto (Free), ask it something until it fails, and confirm
   the failure renders as a failure and not as a bubble.
4. Open Conversations, start a new one, switch back, and confirm the thread
   swaps and the agent cards do not.
5. Leave an agent alone for an hour and confirm the card still says Ready.
