# Agent animations in step with the chat (Parts 2 to 4) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or
> superpowers:subagent-driven-development in this session) to implement this
> plan task by task.

**Goal:** A robot moves its mouth while its answer is on screen, not while it
is still thinking; a meeting gathers everybody at once, takes turns in the
order the chat answers, and breaks up when the round ends; the agents list
shows the same moments in miniature.

**Architecture:** The tasks service already pushes five events to every open
office on `/agents/stream` (`agent_events.publish`). The chat round
(`routes_agent_chat._run_round`) adds three more at the exact moments it
already knows: `meeting_started` (with the participants in turn order),
`speaking_started` (at the moment a bubble is sent, with its length), and
`meeting_ended`. `run_started` gains the run's `source`. The office
(`static/office/js/office.js`, Ralph's file) and the agents page
(`static/agents.html`) read them. Everything fails open.

**Tech stack:** FastAPI, SSE (sse-starlette), plain JS, Playwright (Python)
browser tests, the local Docker stack (`bash scripts/dev_up.sh up`).

**Design:** `docs/plans/2026-10-12-local-docker-and-synced-animations-design.md`.

---

## What changed since the design (read first)

Ralph's PR #30 (`5482b9bdf`, merged to fork/main `a3611f3fe` on 2026-10-12)
already ships most of the design's Part 3: one clock for walks, rooms moved
rather than rebuilt, slots patched in place, a speaking mouth with typing
dots, a travelling handoff bubble, lit rooms and an activity log. This plan
builds only what is still missing. Do not rewrite his animation code.

Measured in the code on 2026-10-13, the remaining gaps are:

1. **The mouth is inverted.** `office.js` `speaking(id)` is true while the
   run is `working`. Agent turns are non-streaming
   (`routes_agent_chat._run_round` yields the bubble in one piece AFTER
   `_turn_for` returns, and `finish_run` publishes `run_finished` inside that
   call). So the mouth moves while the model is thinking and stops at the
   moment the answer appears in the chat.
2. **A meeting trickles in.** `inMeeting(id)` needs `a.source === "meeting"`,
   but the `run_started` event carries no source, so a robot's source is only
   learned from the 30 second poll or a reconnect. Agents whose turn has not
   started yet stay at their desks.
3. **A meeting ends on a guess.** `MEETING_SECONDS = 90` after the last
   meeting run, instead of when the round ends.
4. **The agents page has no live feed.** It polls `/agents/activity` every
   5 s and never opens `/agents/stream`.

Deviations from the design, on purpose:

1. **No server `speaking_finished`.** Turns are non-streaming, so the server
   has no moment at which speaking ends. The client holds the mouth for a
   time based on the answer's length (`chars`, a number, never prose).
2. **No separate `turn_started`.** `run_started` with `source: "meeting"`,
   plus the order in `meeting_started.participants`, already says whose turn
   it is.

## Gates (stop and ask the user at each)

1. **Before Task 5:** the office files are Ralph's. The user must confirm
   that Ralph has been told.
2. **Before Task 9 (deploy):** Ralph's PR #30 is merged but NOT deployed
   (on 2026-10-13, `walking.css` returned 404 on prod). Deploying
   `office.js` ships his PR #30 as well. The user must confirm that his PR
   may go live with this work.

## Commands used throughout

- Unit tests (from `mcp-servers/tasks/`): `python -m pytest tests/<file> -q`
- Browser tests: `python -m pytest tests/browser/<file> -q`
- Local stack: `bash scripts/dev_up.sh up` (never a bare `docker compose`;
  on 2026-10-13 a bare `up -d --build tasks` dropped caddy and api-gateway).
- After any change under `mcp-servers/tasks/`, rebuild the local copy with
  `bash scripts/dev_up.sh up` (static files are baked into the image).

---

### Task 1: A timing probe, run before anything changes

**Files:**
- Create: `scripts/dev_sync_timing.py`

The baseline has to be measured on today's code, or "after" means nothing.

**Step 1: Write the probe.** Reuse the helpers in `scripts/dev_e2e.py`
(sign-in, `agents_frame`, `office_frame`, `send`). Read that file first.
Inside the office frame, install a recorder before sending anything:

```js
window.__t = [];
new MutationObserver(function (list) {
  list.forEach(function (m) {
    var n = m.target;
    if (m.type === "attributes" && m.attributeName === "data-speaking") {
      window.__t.push({k: n.getAttribute("data-speaking") ? "mouth_on" : "mouth_off",
                       id: n.getAttribute("data-id"), t: performance.now()});
    }
    if (m.type === "childList") m.addedNodes.forEach(function (a) {
      if (a.nodeType === 1 && (a.matches(".am.agent") || a.querySelector && a.querySelector(".am.agent")))
        window.__t.push({k: "bubble", t: performance.now()});
    });
  });
}).observe(document.body, {subtree: true, childList: true, attributes: true,
                           attributeFilter: ["data-speaking"]});
```

Note: the bubble is observed in the thread the message was sent from. If the
office frame has its own `#agent-thread` (office.html line 169), send from
there so the bubble and the robot are in one document and share one clock.

Scenes:
1. `"Ada, hello"`: report `mouth_on - bubble` and `mouth_off - bubble` in ms.
2. `"everyone answer: hello"`: report how many robots are inside the meeting
   room (`#rooms [data-room="meeting"]`; confirm the selector in office.js)
   at the moment the FIRST bubble lands, and the order of `mouth_on` ids
   against the order of bubbles.

Print plain numbered lines, no secrets. Exit 0 on a completed run (the
numbers are the result; the asserts come later).

**Step 2: Run it on today's code.**
Run: `bash scripts/dev_up.sh up && python scripts/dev_sync_timing.py`
Expected (from reading the code): `mouth_on` about 1500 ms BEFORE the bubble,
`mouth_off` within about 100 ms of it; one robot in the meeting room when the
first bubble lands. Write the real numbers into this plan under "Baseline".

**Step 3: Commit.**
```bash
git add scripts/dev_sync_timing.py docs/plans/2026-10-13-synced-animations-parts-2-4.md
git commit -m "Local dev: measure the robots against the chat"
```

---

### Task 2: Three new events and three new fields on the bus

**Files:**
- Modify: `mcp-servers/tasks/agent_events.py` (`EVENTS`, `publish`)
- Test: `mcp-servers/tasks/tests/test_agent_events.py`

**Step 1: Failing tests.** Append:

```python
def test_the_chat_moments_are_events():
    for name in ("speaking_started", "meeting_started", "meeting_ended"):
        assert name in agent_events.EVENTS


def test_speaking_carries_a_length_and_never_the_words():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("speaking_started", agent_id="agent-a",
                         user_email="me@example.com", chars=42)
    payload = sub.queue.get_nowait()
    assert payload["chars"] == 42
    assert set(payload) <= ALLOWED


def test_a_meeting_names_its_people_in_turn_order():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("meeting_started", agent_id="agent-a",
                         user_email="me@example.com",
                         participants=["agent-a", "agent-m", "agent-d"])
    assert sub.queue.get_nowait()["participants"] == ["agent-a", "agent-m", "agent-d"]


def test_a_run_says_where_it_came_from():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("run_started", agent_id="agent-a",
                         user_email="me@example.com", source="meeting")
    assert sub.queue.get_nowait()["source"] == "meeting"


def test_a_bad_length_does_not_raise():
    sub = agent_events.subscribe("me@example.com")
    agent_events.publish("speaking_started", agent_id="agent-a",
                         user_email="me@example.com", chars="many")
    assert "chars" not in sub.queue.get_nowait()
```

And widen the module constant:
`ALLOWED = {"event", "agent_id", "tool", "target_agent_id", "status", "at", "source", "participants", "chars"}`

**Step 2:** `python -m pytest tests/test_agent_events.py -q`. Expected: the
5 new tests FAIL (unknown event, unexpected keyword).

**Step 3: Implement.** In `agent_events.py`:

```python
#: The run's own moments, plus the chat's: a bubble going out, and a meeting
#: opening and closing. Each is a thing that really happened. Nothing else
#: is sent.
EVENTS = frozenset({"run_started", "tool_started", "tool_finished",
                    "handoff", "run_finished",
                    "speaking_started", "meeting_started", "meeting_ended"})

#: A meeting is the person's own agents; this only stops a bad caller from
#: putting an unbounded list on every open page.
MAX_PARTICIPANTS = 20
```

`publish` gains `source: str | None = None, participants: list | None = None,
chars: int | None = None`, and inside the existing `try`, after `status`:

```python
        if source:
            payload["source"] = str(source)
        if participants:
            payload["participants"] = [str(p) for p in participants
                                       if p][:MAX_PARTICIPANTS]
        if chars is not None:
            try:
                payload["chars"] = max(0, int(chars))
            except (TypeError, ValueError):
                pass
```

Update the docstring's "Five moments" wording to match.

**Step 4:** Run the same command. Expected: all pass.

**Step 5: Commit.** `git commit -m "Office feed: speaking and meeting events"`

---

### Task 3: `run_started` says where the run came from

**Files:**
- Modify: `mcp-servers/tasks/agent_activity.py` (`start_run`, the
  `agent_events.publish("run_started", ...)` call, about line 194)
- Test: `mcp-servers/tasks/tests/test_agent_events.py` or the existing
  `start_run` tests (find them with `grep -rn "start_run" tests/`)

**Step 1: Failing test.** `start_run` needs the DB, so monkeypatch
`agent_activity.session` with a fake async context manager whose `execute`
and `commit` are no-ops (follow any existing fake-session pattern in
`tests/`), and `agent_events.publish` with a recorder. Assert the recorded
call has `source="meeting"` when `start_run(..., source="meeting")`.

**Step 2:** Run it. Expected: FAIL (no `source` keyword passed).

**Step 3:** Pass `source=source` in that one publish call.

**Step 4:** Run it. Expected: PASS.

**Step 5: Commit.** `git commit -m "Office feed: a started run carries its source"`

---

### Task 4: The chat round announces bubbles and meetings

**Files:**
- Modify: `mcp-servers/tasks/routes_agent_chat.py` (`_run_round`, lines
  408-669; add `import agent_events` with the other module imports)
- Test: `mcp-servers/tasks/tests/test_agent_chat_round.py`

**Step 1: Failing tests.** Use the file's own `_app` harness. Record the
order of turns and events in one list:

```python
def _record(monkeypatch, mod):
    log = []
    async def turn(email, agent, messages, names=(), **kw):
        log.append(("turn", agent["id"]))
        return {"answer": f'{agent["name"]} here', "notes": [],
                "agent": {"id": agent["id"], "name": agent["name"]}}
    def publish(event, **kw):
        log.append((event, kw.get("agent_id"), kw.get("participants"),
                    kw.get("chars")))
    monkeypatch.setattr(mod, "_turn_for", turn)
    monkeypatch.setattr(mod.agent_events, "publish", publish)
    return log


def test_a_meeting_opens_with_everybody_then_takes_turns_then_closes(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    log = _record(monkeypatch, mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "hi team"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    kinds = [e[:2] for e in log]
    assert kinds == [("meeting_started", "agent-a"), ("turn", "agent-a"),
                     ("speaking_started", "agent-a"), ("turn", "agent-m"),
                     ("speaking_started", "agent-m"),
                     ("meeting_ended", "agent-m")]
    assert log[0][2] == ["agent-a", "agent-m"]
    assert log[2][3] == len("Ada here")


def test_one_agent_speaks_without_a_meeting(monkeypatch):
    app, mod, _ = _app(monkeypatch)
    log = _record(monkeypatch, mod)
    c = TestClient(app)
    c.post("/tasks/agents/chat/send", data={"message": "Ada, hi"}, headers=_hdr())
    c.get("/tasks/agents/chat/stream", headers=_hdr())
    assert [e[0] for e in log] == ["turn", "speaking_started"]


def test_a_failed_turn_does_not_speak(monkeypatch):
    # Use the failure answer the existing
    # test_a_failed_agent_does_not_take_the_round_down uses.
    ...
    assert ("speaking_started", "agent-a") not in [e[:2] for e in log]


def test_a_meeting_still_closes_when_a_turn_raises(monkeypatch):
    # _turn_for raises for Mia. The round may end however it ends today,
    # but meeting_ended must still be published.
    ...
    assert log[-1][0] == "meeting_ended"
```

Check how `"hi team"` and `"Ada, hi"` route before trusting the expected
lists: run them against `agent_routing.choose_speakers` in a REPL first. If
"hi team" does not reach both agents, use the wording the existing
`test_every_agent_in_the_room_gets_its_own_bubble_in_order` uses.

**Step 2:** `python -m pytest tests/test_agent_chat_round.py -q`. Expected:
the new tests FAIL; the old ones still pass.

**Step 3: Implement** in `_run_round`:

1. After `speakers, may_pass, why` are final (after the `private` block,
   before the approval branch returns), compute:
   ```python
   # Who is in this meeting, in the order they will speak. The office
   # walks them all in at once from this, instead of one at a time as each
   # turn starts.
   met = ([str(a.get("id") or "") for a in speakers]
          if _is_a_meeting(speakers) and why != agent_routing.ROUTE_APPROVAL
          else [])
   ```
2. Just before `for agent in list(speakers):`, publish `meeting_started`
   (`agent_id=met[0]`, `participants=met`) when `met`, then wrap from the
   `for` loop to the end of the everybody-passed fallback in
   `try: ... finally:` that publishes `meeting_ended` (`agent_id=met[-1]`)
   when `met`. The `finally` also runs when the browser disconnects and the
   generator is closed.
3. Immediately before each `yield` of an agent's bubble (the main loop's
   `render.agent_bubble` and the fallback's), publish
   `speaking_started` with `agent_id` and `chars=len(answer)`. Before the
   yield, so the event and the bubble leave the server together.
4. Also before yielding a question (`question is not None` in both places):
   an agent asking for approval is speaking too.
5. Not for a failure fragment, a pass, or a note.

`agent_events.publish` never raises, so no new try/except is needed.

**Step 4:** Run the file. Expected: all pass. Then the whole suite:
`python -m pytest tests/ -q` (expect only the known `ERROR at setup` DB
errors).

**Step 5: Commit.** `git commit -m "Agent chat: say when a bubble goes out and when a meeting opens and closes"`

---

### GATE 1: confirm Ralph has been told before Task 5.

---

### Task 5: The office speaks with the bubble, not the thinking

**Files:**
- Modify: `mcp-servers/tasks/static/office/js/office.js` (`speaking`,
  `slotInner`, `patchSlot`, `applyEvent`, `LIVE_EVENTS`; find where `S` is
  initialised and add the new fields there)
- Modify: `mcp-servers/tasks/static/office/animations/speaking.css`
- Test: `mcp-servers/tasks/tests/browser/test_office_live.py` (its `_sse`
  harness)

Behaviour:
1. **Typing dots** (`.talk-dots`) keep today's rule: shown while a run from a
   conversation is working. That IS the thinking, and it matches "is
   working..." in the thread. Drive them from a new `data-typing="1"`.
2. **The mouth** (`data-speaking="1"`) is on only from `speaking_started`
   for `speakFor(chars)` ms:
   `Math.max(1500, Math.min(5000, chars * 40))`, then off by a timer that
   calls `draw()`.
3. **Walk first.** If the robot is walking when `speaking_started` lands,
   the speaking time starts on arrival. Read `watchArrival` and the
   `walking` signal that Ralph's tests use; hook the arrival rather than
   adding a second clock.
4. `run_started` keeps `e.source` on `S.ACTIVITY[id].source` when present.

**Step 1: Failing tests** (new fixtures in the file's style):

```python
@pytest.fixture
def iris_answers():
    STREAM["body"] = _sse(
        {"event": "run_started", "agent_id": IRIS, "source": "channel",
         "at": "2026-09-30T10:00:00+00:00"},
        {"event": "run_finished", "agent_id": IRIS, "status": "ok",
         "at": "2026-09-30T10:00:01+00:00"},
        {"event": "speaking_started", "agent_id": IRIS, "chars": 40,
         "at": "2026-09-30T10:00:01+00:00"})
    yield
    STREAM["body"] = _sse()


def test_the_mouth_moves_with_the_answer_and_then_stops(iris_answers, page):
    who = page.locator('.who[data-id="%s"]' % IRIS)
    page.locator('.who[data-id="%s"][data-speaking="1"]' % IRIS).wait_for(timeout=3000)
    # 40 chars = 1600 ms; gone by 2500 ms.
    page.wait_for_timeout(2500)
    assert who.get_attribute("data-speaking") is None


@pytest.fixture
def iris_thinks():
    STREAM["body"] = _sse({"event": "run_started", "agent_id": IRIS,
                           "source": "channel", "at": "2026-09-30T10:00:00+00:00"})
    yield
    STREAM["body"] = _sse()


def test_thinking_shows_dots_but_no_mouth(iris_thinks, page):
    page.locator('.who[data-id="%s"][data-typing="1"]' % IRIS).wait_for(timeout=3000)
    assert page.locator('.who[data-id="%s"] .talk-dots' % IRIS).count() == 1
    assert page.locator('.who[data-id="%s"]' % IRIS).get_attribute("data-speaking") is None
```

Also: a source carried on `run_started` is used without the poll (serve
`SERVED["activity"] = {}` and assert the robot is typing, which needs the
source).

**Step 2:** `python -m pytest tests/browser/test_office_live.py -q`.
Expected: the new tests FAIL. Also run `test_office_page.py` and
`test_office_inline.py` and note any test that pins the old "mouth while
working" rule; it is updated in Step 3, in the same commit, with the reason
in a comment.

**Step 3: Implement.** In speaking.css, keep the mouth rule on
`[data-speaking="1"]` and update the comment above it to say the mouth is
driven by `speaking_started`. In office.js:

```js
  //: Speaking is the BUBBLE, not the thinking. Agent turns are not
  //: streamed: the whole answer lands in the chat at once, after the run
  //: has finished, and the server says so with speaking_started. The mouth
  //: runs for a time that grows with the answer; the dots are the thinking.
  var SPEAK_MIN_MS = 1500, SPEAK_MAX_MS = 5000, SPEAK_MS_PER_CHAR = 40;
  function speakFor(chars) {
    return Math.max(SPEAK_MIN_MS, Math.min(SPEAK_MAX_MS, (chars || 0) * SPEAK_MS_PER_CHAR));
  }
  function typing(id) {          // was speaking(): the run is working
    var a = S.ACTIVITY[id];
    return !!(a && a.state === "working" && SPEAKING_SOURCES[a.source]);
  }
  function speaking(id) {
    var until = S.SPEAKING[id];
    return !!until && until > Date.now();
  }
```

and in `applyEvent`:

```js
    } else if (e.event === "speaking_started") {
      var ms = speakFor(e.chars);
      S.SPEAKING[e.agent_id] = Date.now() + ms;
      setTimeout(draw, ms + 30);
    }
```

(plus the arrival rule from Behaviour 3). `slotInner` and `patchSlot` set
`data-typing` and the dots from `typing()`, and `data-speaking` from
`speaking()`, each independently.

**Step 4:** Run all three office browser files. Expected: all pass.

**Step 5: Commit.** `git commit -m "Agent office: the mouth moves with the answer, the dots with the thinking"`

---

### Task 6: A meeting gathers, takes turns, and breaks up on the round

**Files:**
- Modify: `mcp-servers/tasks/static/office/js/office.js` (`inMeeting`,
  `meetingIsOn`, `applyEvent`, `LIVE_EVENTS`)
- Test: `mcp-servers/tasks/tests/browser/test_office_live.py`

Behaviour:
1. On `meeting_started`, every participant walks to the meeting room at once.
2. They stay while the round runs, each speaking on their own
   `speaking_started` (Task 5).
3. On `meeting_ended`, they stay `MEETING_LINGER_MS = 4000` (so the last
   answer finishes), then walk back together.
4. Once the stream has said anything about a meeting, the stream wins.
   `MEETING_SECONDS` and the source rule stay only for a page that was
   opened mid-meeting and has heard no `meeting_started`.

```js
  var MEETING_LINGER_MS = 4000;
  // in applyEvent:
    } else if (e.event === "meeting_started") {
      S.MEETING = { ids: (e.participants || []).slice(), ended: null };
    } else if (e.event === "meeting_ended") {
      if (S.MEETING) {
        S.MEETING.ended = Date.now();
        setTimeout(draw, MEETING_LINGER_MS + 30);
      }
    }

  function inMeeting(id) {
    var m = S.MEETING;
    if (m) {
      if (m.ended && Date.now() - m.ended > MEETING_LINGER_MS) return false;
      return m.ids.indexOf(id) !== -1;
    }
    // ... the existing source-based rule, unchanged, for a page that
    // opened mid-meeting.
  }
```

Add the three new names to `LIVE_EVENTS`.

**Step 1: Failing tests:**
1. `meeting_started` with `[ADA_ID, IRIS]` and no runs: both robots end up
   in the meeting room (wait on Ralph's `walking` signal, not a fixed sleep).
2. Then `meeting_ended`: both are still there at 2 s and back at their
   desks by 6 s (use `pg.clock` if the file's `clock` option suits).
3. An agent not in `participants` never enters the room.

**Step 2:** Run. Expected: FAIL.

**Step 3:** Implement as above.

**Step 4:** All three office browser files pass.

**Step 5: Commit.** `git commit -m "Agent office: a meeting gathers together and breaks up when the round ends"`

---

### Task 7: The agents list in miniature

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html` (the roster IIFE near
  line 3570, `row()` and `drawStatus()`; styles next to `.roster-av`)
- Test: a new `mcp-servers/tasks/tests/browser/test_agents_live_roster.py`,
  modelled on `tests/browser/test_agents_hidden_pane.py` (which already
  routes `/agents/stream`)

Behaviour:
1. Open one `EventSource("/api/tasks/agents/stream", {withCredentials: true})`
   while the page is on screen. Close it when the pane is hidden (the page
   already has `onScreen()`).
2. On `.roster-av` of that agent's row:
   - `data-live="working"` from `run_started` to `run_finished`, drawn as a
     slow opacity pulse (2 s, ease-in-out);
   - `data-live="speaking"` for `speakFor(chars)` after `speaking_started`,
     drawn as a 2px ring in the avatar's own colour.
   - Only `opacity` and `box-shadow`/`outline` animate. Under
     `prefers-reduced-motion: reduce`, no animation: a static ring only.
3. In the open thread (`#agent-thread`), one plain line per real event:
   - `meeting_started`: "Meeting: Mia, Ada, Dev" (names from the roster, in
     `participants` order; ids with no name are skipped);
   - `handoff`: "Dev asked Mia".
   These are `<div class="am sys">` lines appended live and never stored, so
   a reload shows only the stored conversation. Text through `textContent`,
   never `innerHTML`.
4. Plain text only. No icons.

**Step 1: Failing tests:** one per behaviour above, driven by an SSE body as
in `test_office_live.py`.

**Step 2:** Run. Expected: FAIL.

**Step 3:** Implement.

**Step 4:** The new file passes, plus `test_agents_hidden_pane.py` and the
other `tests/browser/test_agents*.py`.

**Step 5: Commit.** `git commit -m "Agents list: a working pulse, a speaking ring and meeting lines from the live feed"`

---

### Task 8: Prove it locally

1. `bash scripts/dev_up.sh up` (rebuilds tasks with the new files).
2. `python scripts/dev_check.py`: 6 PASS.
3. `python scripts/dev_e2e.py`: passes.
4. `python scripts/dev_sync_timing.py`: write the numbers under "After".
   Pass bar:
   - `mouth_on - bubble` between 0 and 200 ms;
   - `mouth_off` after the bubble, at about `speakFor(chars)`;
   - every meeting participant is in the room when the first bubble lands;
   - `mouth_on` order equals bubble order.
5. Turn the probe's numbers into asserts, so the script exits 1 on a miss.
6. Look at it in a real browser at http://localhost:8090: one agent, then
   "everyone answer: hello". Save before and after screenshots to `dev/out/`.
7. `python -m pytest tests/ -q` and every `tests/browser/test_office*.py` and
   `tests/browser/test_agents*.py`: report the counts.
8. Code review (superpowers:requesting-code-review), fix, re-run.
9. `git fetch fork`, rebase, push to `fork/main` (`gh auth switch -u Jacintalama`).

### GATE 2: confirm PR #30 may go live with this work.

### Task 9: Deploy, hash-checked

1. `git fetch fork`; `git branch -r --contains HEAD` shows `fork/main`.
2. Find the live commit (`.deploy-state` may be stale), and hash-sweep the
   server against it, CRLF-normalised, for every file about to be copied.
   A file that differs from both the live commit and HEAD is someone's
   unpushed work: stop.
3. `git archive HEAD` with exactly the changed files under
   `mcp-servers/tasks/`; scp the tar; back up the targets; unpack with
   `--no-same-owner`; `stat -c %u /root/proxy-server` prints `0`.
4. `docker compose -f docker-compose.unified.yml up -d --build tasks`
   (static is baked into the image).
5. Verify: container md5 == repo for each file; the HTTPS served bytes of
   `office.js`, `speaking.css`, `walking.css` and `agents.html` == repo;
   `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`.
6. Write `.deploy-state` as JSON (`sha`, `deployed_at`, `deployed_by`).
7. One real chat turn on prod in a browser: the mouth starts with the bubble.
8. Deploy notes say what was checked locally (Task 8).

## Baseline (Task 1, filled in when measured)

Measured 2026-10-13 on the local stack, `python scripts/dev_sync_timing.py`,
headless Chromium, fake model (1.5 s per answer). Two runs, numbers in ms.

Code under test: the `aiui-dev-tasks-1` container (started 08:39:04 UTC,
not restarted across the runs). Its `agent_events.py`, `agent_activity.py`,
`routes_agent_chat.py`, `routes_agent_turn.py`, `agent_chat_render.py`,
`static/office/js/office.js`, `static/office.html` and `static/agents.html`
hash-match `e603d348d` (CRLF-normalised md5), and the served
`/tasks/static/office/js/office.js` matches too. So this is the code before
`9500be6ab` and `aac2258e5`, which landed in the repo while this was measured
but were not in the running image.

Where it was measured:
- The office's own chat (`#deskchat` in `office.html`) cannot be used:
  `office.html` loads `htmx.min.js` (2.0.4) without `vendor/sse.js`, so a
  send there draws the question and the `.astream` block but never opens
  `/tasks/agents/chat/stream`. Measured: 0 chat EventSources after a send, no
  answer in 8 s, and the room session was left `streaming` until the stream
  was opened by hand. That is a bug in its own right.
- So: the conversation on the AI Agents page (`/ai-agents` -> frame
  `/tasks/agents`), and the office it docks (`#office-body iframe`,
  name `aiui-office`, `/tasks/office?embed=1`), a same-origin child of that
  frame. One MutationObserver callback installed in the agents frame watches
  both documents, and every timestamp is the agents frame's
  `performance.now()`: one clock, no cross-frame offset.

Selectors (verified against `agent_chat_render.agent_bubble`, office.js
`slotInner`/`patchSlot`/`syncRooms`, and the live DOM):
- bubble: an added `.am.agent` inside `#agent-thread`, name from `.awho`.
  htmx lands one out-of-band answer in two mutation records, so each element
  is counted once.
- mouth: `.who[data-speaking]` in the office document (`data-id` = agent id,
  name from the slot's `.card-name`), by a scan after every mutation batch,
  which also catches a rebuilt node; the attribute changes were also logged
  and matched (one on, one off per run).
- meeting room: `.zone[data-room="meeting"]`; a robot is "in" it when the
  centre of its `.who` box is inside the zone's box (robots are in
  `#agents-layer`, not inside the zone). Also logged: `#rooms[data-meeting]`.
- run events: a second EventSource on `/api/tasks/agents/stream` from the
  probe, same clock.

Scene a, "Ada, hello" (in the room):

| | run 1 | run 2 |
|---|---|---|
| send to bubble | 1765 | 1821 |
| send to mouth_on | 234 | 276 |
| mouth_on - bubble | -1530 | -1545 |
| mouth_off - bubble | +6 | +7 |
| in the meeting room at the bubble | Ada, Mia, Dev (`data-meeting=3`) | Ada, Mia, Dev (`data-meeting=3`) |

Scene b, "everyone answer: hello":

| | run 1 | run 2 |
|---|---|---|
| first bubble (Ada) after send | 1885 | 1910 |
| robots in the meeting room at the first bubble | 0 (`data-meeting=""`) | 0 (`data-meeting=""`) |
| most in the meeting room at any bubble | 2 (Mia, Dev) | 2 (Mia, Dev) |
| mouth_on order | Ada 328, Mia 1957, Dev 3576 | Ada 363, Mia 2018, Dev 3682 |
| bubble order | Ada 1885, Mia 3499, Dev 5118 | Ada 1910, Mia 3579, Dev 5293 |
| mouth_on order == bubble order | yes | yes |
| mouth_on - bubble (Ada, Mia, Dev) | -1556, -1542, -1542 | -1547, -1561, -1611 |
| mouth_off - bubble (Ada, Mia, Dev) | +5, +5, +5 | +5, +8, +7 |

A third run, after a cosmetic change to the probe's log, gave the same
shape: a -1550/+6; b -1563/-1545/-1540 and +5/+7/+7, 0 then 2 in the room.

What this shows:
1. The mouth opens about 1.55 s before the bubble (the whole model call)
   and closes within 10 ms after it, as expected.
2. The meeting room is driven by a STALE source, not by the meeting.
   Baseline `run_started` carries no `source` (the probe's feed read
   `source=None` on every event), and office.js `applyEvent` keeps
   `a.source` from the last `/agents/activity` read. So:
   - a one-to-one "Ada, hello" put all three robots in the meeting room
     ("3 AGENTS IN A MEETING", screenshot `dev/out/sync-one-first-bubble.png`),
     because their last recorded runs were meetings;
   - in the real meeting, Ada (last read as `channel`) never went to the room,
     and Mia and Dev walked in when Mia started, as soon as any `meeting` row
     was working. Not "one robot at a time": zero, then two.
3. Answers in a meeting are strictly sequential (about 1.6 s each), and each
   mouth starts only when that agent's run starts, so the order matches.

## After (Task 8, filled in when measured)
