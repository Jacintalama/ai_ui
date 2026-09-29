# The office watches the work happen

2026-09-29

## What this is for

The owner was shown a proposal to rebuild the Agent Office as a game world:
Phaser or PixiJS, sprite sheets per agent, characters that stand up, walk to
desks, sit down and wander. Asked what the office should show when nothing is
running, the owner chose **only what really happened**: every movement maps to
a row the platform recorded. Asked what the office should be worth opening on
a quiet day, the owner chose **watch it happen, live**.

Those two answers together are the whole brief. The office may not invent, and
the office must not be late.

### Success looks like

You have the office open. An agent starts a run. Within about 200ms the robot
lights up, badges the tool it is running, draws its line to a colleague when
it hands over, and settles when the run ends. You watched it, in order, as it
happened.

### What this explicitly does not do

It does not make the agents run more often. On the day this was written the
owner's floor read "7 agents, none working right now", with last runs between
2 and 22 hours old. This work removes the lag. It does not remove the silence,
and anyone expecting a busy office afterwards will be disappointed by physics
rather than by the code.

It also does not adopt a game engine. See "Approaches rejected".

## The problem

`office.html:1464` refreshes on a five second `setInterval`. Everything the
floor knows arrives on that tick, so the most interesting moments of an agent
turn are typically over before they are drawn, and a handoff between two
agents can appear and vanish inside one interval.

## Approach: an in-process event bus and one SSE endpoint

`tasks` runs a **single** uvicorn process (`Dockerfile:46`, `uvicorn main:app`
with no `--workers`), and agent turns execute inside it. So a plain asyncio
fan-out in that process reaches every open page. No Redis, no separate socket
server, no second thing to deploy or keep alive.

```
tasks (one process)
  an agent turn
    |-- start_run ------> bus + DB row
    |-- execute_tool_call> bus            (event only, no row)
    |-- record_step -----> bus + DB row
    '-- finish_run ------> bus + DB row
              |
              v
     GET /agents/stream   (text/event-stream, current_user scoped)
              |
     api-gateway stream_through()          [already exists]
              |
       office.html EventSource
       (slow poll kept as fallback and resync)
```

### Why this shape

- **The transport is already proven through this stack.** The api-gateway has
  `is_event_stream()` and `stream_through()` (`api-gateway/main.py:315-363`),
  added when the agent chat panel was fixed, precisely because the gateway
  used to buffer every response and turn a stream into one delivery at the
  end. SSE from `tasks` reaches the browser untouched today.
- **EventSource can authenticate here.** It cannot set headers, but the
  gateway accepts the Open WebUI JWT from *either* `Authorization: Bearer` or
  the `token` cookie (`api-gateway/main.py:486-493`). The office runs
  same-origin inside Open WebUI, so the cookie is first-party and
  `withCredentials: true` is enough.
- **Three of the four publish sites already exist as single choke points.**
  `agent_activity.start_run`, `finish_run` and `record_step` are the only
  places those facts are written. Publishing beside the write means an event
  cannot disagree with the row.

### Approaches rejected

**Phaser or PixiJS.** The proposal assumed "React remains the application
shell; Phaser becomes the office inside it". There is no React shell: no
`package.json` anywhere in the platform UI, no bundler, no build step.
`agents.html` and `office.html` are hand-written HTML, CSS and vanilla JS
served off disk by FastAPI and deployed by `scp` plus `docker cp`. (React and
npm do exist in `video-remotion`, a separate Node renderer, so a build is not
unthinkable here, only unprecedented for the web pages.) Adopting a canvas
renderer costs a build pipeline plus sprite sheets per agent, where today a
new agent costs nothing because the robot is generated SVG with a colour
palette. It buys smoother motion and a camera. It buys no additional true
fact, which is the thing this floor is short of. The event model designed
here is identical either way, so if the floor still feels flat afterwards,
a renderer swap remains available as a contained piece of work.

**Polling faster.** Changing 5000 to 1000 is half an hour of work and no new
infrastructure. It is still up to a second late and multiplies the database
read load by five, all day, for every open page.

**A start row for every step.** `record_step`'s docstring records that a
start-then-finish pair was removed on 2026-09-29 in `d9b8c26b8`, because "a
row opened as 'running' and immediately overwritten describes no in-flight
window anyone could ever observe". That window is now observable, so the
reasoning has changed, but the conclusion should not: the cost was a second
round trip and a second commit on a hot path, and that cost is still real.
`tool_started` is published as an event with **no row**. The live view needs
the signal; nothing needs it durable.

## The events

Five, each one a moment that actually occurred.

| event | published from | row? |
|---|---|---|
| `run_started` | `agent_activity.start_run` | yes, existing |
| `tool_started` | `agent_tools.execute_tool_call` | **no** |
| `tool_finished` | `agent_activity.record_step` | yes, existing |
| `handoff` | `agent_activity.record_step`, when `target_agent_id` is set | yes, existing |
| `run_finished` | `agent_activity.finish_run` | yes, existing |

`execute_tool_call` is the right site for `tool_started` because it is the one
choke point both tool paths go through: `agent_runner.py:925` and
`routes_agent_turn.py:433` both call it. It already receives `agent_id` and
`user_email` as arguments. Publishing at the two call sites instead would
invite a third that forgets.

It needs the run in flight, which `agent_handoff` already tracks: `_RUN` is
set by every turn, nested included, and all three turn paths enter
`agent_handoff.began(run_id)` (`agent_runner.py:1031`,
`routes_agent_turn.py:335` and `:456`). But `_RUN` has no public accessor
today; the module exposes `parent_run()`, which answers a different question
("the run that asked this one"). So `agent_handoff` gains one function,
`current_run()`, returning `_RUN.get()`. Nothing outside the module may read
`_RUN` directly, which is the existing convention there.

### Payload

Each event carries: the event name, `agent_id`, `user_email` (used for
routing and stripped before it reaches the browser), the tool name where one
applies, `target_agent_id` for a handoff, `status` where one applies, and an
ISO timestamp.

**No prose.** Not the question, not the answer, not a tool's arguments or
results. This is the same rule `agent_step` already follows and for the same
reason: it would be a privacy cost with no payoff, and it sits badly beside
the private agent conversations shipped on 2026-09-25.

## Scoping

Subscribers are filtered by `user_email`, exactly as `activity_for` and
`handoffs_for` already scope their reads. One person's agent working is not
another person's agent working, and an admin watching the stream must not see
anyone else's floor.

This is the single most important thing to get wrong quietly, so it gets a
test of its own: an event published for one user must draw nothing on another
user's floor.

## Failure behaviour

**Publishing fails open.** A failed publish must never cost somebody their
turn, exactly like every other post-processing step in this codebase. Every
publish is wrapped, and a raise inside the bus is swallowed and logged.

**Slow consumers are dropped, not buffered.** This box has 3.8GB of RAM. Each
subscriber gets a bounded queue; when it is full the subscriber is
disconnected rather than allowed to grow. The browser reconnects and resyncs,
which is strictly better than an unbounded queue per open tab.

**The bus is a fan-out, not a log.** Anything published while a page was
disconnected is gone. Therefore, on every connect and reconnect, the office
does one full `loadActivity()` before applying further events. Only a re-read
can be trusted after a gap.

**The poll survives as the fallback.** `setInterval` stays but slows from 5s
to 30s. It covers three cases: `EventSource` unsupported or blocked, a user
who has the localStorage token but no cookie, and a silent gap the heartbeat
did not catch.

**Heartbeat.** An SSE comment every 20 seconds, so Cloudflare and Caddy do not
reap a connection that is merely idle, which on this floor is most of the day.

## The office side

`office.html` opens the `EventSource` and applies events to the floor it
already draws. The floor's existing vocabulary covers most of it: a robot
already has a `working` state with a halo and a live timer, and a handoff
already draws a line, a speech bubble and a walk (`talkHtml`, `walkThem`).
What is new is that these fire on an event instead of on a tick, plus a badge
naming the tool an agent is running right now.

`window.aiuiRefreshOffice` stays exactly as it is. It is the seam the browser
tests already use to prove what the floor does with a given set of rows, and
it is how the event tests will feed events without a server.

The existing `HANDOFF_WINDOW_MINUTES = 5` and `TALK_SECONDS = 90` are
unchanged: a resync after a reconnect still needs to render a handoff that is
recent but not instantaneous.

## Testing

**Unit, no network**, following the module-seam pattern already used here:

- the bus fans out to every subscriber for the right user and to nobody else
- a raise inside a subscriber does not propagate to the publisher
- a full queue drops that subscriber and leaves the others receiving
- each of the five events is shaped correctly, and none carries prose

**Browser**, through the existing refresh seam:

- an event moves the floor without waiting for the poll
- an event for another user's agent draws nothing
- on reconnect the floor re-reads rather than trusting what it has
- with `EventSource` unavailable, the floor still updates on the slow poll

**On the server.** The endpoint itself needs a real request through the real
gateway. CLAUDE.md is explicit that `python -c "import ..."` will not catch a
`NameError` inside a function body, and that wiring of this kind is verified
by driving it on the box. Specifically: connect, run a real agent turn, and
confirm the events arrive in order and within a second.

## Files expected to change

- `agent_events.py` (new): the bus, the subscriber registry, the payloads.
- `agent_activity.py`: publish from `start_run`, `finish_run`, `record_step`.
- `agent_tools.py`: publish `tool_started` from `execute_tool_call`.
- `agent_handoff.py`: add `current_run()`, the public accessor for `_RUN`.
- `routes_agents.py`: `GET /agents/stream`, scoped by `current_user`.
- `static/office.html`: `EventSource`, resync on connect, tool badge, and
  the poll slowed to 30s as fallback.
- tests as above.

No migration. Nothing new is stored.
