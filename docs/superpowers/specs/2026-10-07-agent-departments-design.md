# Departments you own, and agents you can move

2026-10-07

## What this is for

> "please visualized the room for every department the user can create
> department and can asign agent to that rooms and if user realized that isnt
> hes room he will be the one move"

Rooms on the office floor are **derived**, not owned. `office.html:709` holds
a `ZONES` array mapping a tool to a department, and `zoneFor` puts an agent in
the first room whose tool list it matches. Iris stands in Knowledge because
she holds `gdrive`. Nothing stores a room, nothing creates one, and nobody can
move anybody.

Asked what should happen to those derived rooms, the owner chose: **his rooms
replace them entirely.** One source of truth. Today's six are seeded once as
real rooms he owns, so nothing looks different until he changes something.

Asked how an agent moves, the owner chose: **drag the robot across the floor.**

### Success looks like

You open the office, drag Rex out of Development and into a department you
made called Sales, and he is there when you come back. You can rename it,
reorder it, and delete it.

## What this costs, stated plainly

A room stops telling you what an agent can do. Today "Iris is in Knowledge"
and "Iris holds gdrive" are the same fact, because one is computed from the
other. After this they are independent: Iris can sit in Sales holding only
`gdrive`. That is the point of the feature, and it is a real loss. The agent
card already lists an agent's tools, so the answer stays one click away, and
the floor stops pretending a filing decision is a capability.

## Data

Two tables, both scoped by `user_email` like every other per-user table here.

### `tasks.agent_room` (new)

| column | notes |
|---|---|
| `id` | UUID |
| `user_email` | owner scoping |
| `name` | what it is called |
| `glow` | the room's colour, as `ZONES` carries today |
| `position` | integer, left to right on the floor |
| `is_open_floor` | exactly one per owner, and it cannot be deleted |
| `created_at` | |

### `tasks.agent_placement` (new)

| column | notes |
|---|---|
| `agent_id` | the `public.model` id, primary key with `user_email` |
| `user_email` | owner scoping |
| `room_id` | the room it stands in |
| `position` | integer, order within the room |
| `updated_at` | |

Migration `054_agent_rooms.sql`, additive and idempotent, because `db.py`
re-runs every migration on each startup.

### Seeding, which is what makes this invisible on day one

An owner with no rooms gets the current six plus Open floor, created once,
with each agent placed by exactly the rule `zoneFor` uses now. Seeding happens
on the first read, not on a migration, because the placements depend on each
agent's tools and the migration cannot see them.

**This is the step most likely to go wrong, and it has gone wrong here
before.** On 2026-08-27 a seed endpoint was deployed ahead of the script that
marked existing owners as seeded, and the owner got duplicate agents. So
seeding is guarded by the existence of any room for that owner, in one
statement, and is safe to run concurrently from two open pages.

## Rules

- **Deleting a room moves its agents to Open floor.** It is never a cascade
  that deletes an agent, and Open floor cannot itself be deleted, which is
  what guarantees there is always somewhere to land.
- **An agent with no placement stands in Open floor.** A new agent created
  after seeding has no row, and the floor must not drop it. This is the same
  disk-truth rule the office already follows: draw what is there.
- **A placement for an agent the owner no longer has is ignored**, not an
  error. Agents are deleted outside this feature.
- **Rooms are per owner.** One person's Sales is not another's, the same
  scoping `activity_for` and `handoffs_for` already use.

## The floor

`ZONES` stops being layout logic and becomes seed data. `zoneFor` is deleted:
`drawRooms` reads rooms and placements from the server instead of deriving
them. Everything else about the layout survives unchanged, including the part
rebuilt on 2026-09-29: an agent is one slot in normal flow, a room is however
big its slots make it, the canvas is however big its rooms make it, and
`bestLayout` picks the shape that fits the dock.

### Dragging

Pointer events, not HTML5 drag-and-drop, because the floor is inside a
transformed and scaled canvas and `dragover` coordinates do not survive that
cleanly. On pointer down on a robot, on move it follows the pointer, on up the
room under the pointer is the drop target. The write is one `PUT`, and the
floor shows the agent in its new room before the server answers, reverting if
the write fails.

**The accessibility gap, flagged rather than hidden.** The owner chose drag
alone over drag plus a menu. Drag with a pointer excludes keyboard users and
is awkward on touch, and the office already opens as a pane on phones. This
spec therefore includes the minimum that stops it being a dead end: a
long-press starts a drag on touch, and each robot is focusable with a
"Move to…" action on it reachable from the keyboard. That is not the card
picker that was declined; it is the same drop written a second way, and
leaving it out would make the floor unusable for an input the product already
supports.

## Endpoints

All in `routes_agents.py`, all `current_user` scoped exactly like `/activity`.

- `GET /agents/rooms`: rooms and placements for the caller, seeding on first
  call. One response, because the floor needs both to draw one frame and two
  requests would let them disagree about the same moment, which is the reason
  `/activity` already carries handoffs.
- `POST /agents/rooms`: create.
- `PATCH /agents/rooms/{id}`: rename, recolour, reorder.
- `DELETE /agents/rooms/{id}`: refuses Open floor, moves its agents to it.
- `PUT /agents/placement`: one agent into one room.

## Live updates

The office already streams: `agent_events` fans out to every open page of a
user. A room change is a change to what the floor draws, so it publishes like
anything else, and a second tab redraws without a poll. This adds one event,
`rooms_changed`, carrying no payload: the floor re-reads, the same thing it
already does on `hello` and on reconnect, because the stream is a fan-out and
not a log.

## Testing

**Unit, no network**, following the module-seam pattern used here:

- seeding is idempotent, produces Open floor exactly once, and two concurrent
  callers create one set of rooms
- deleting a room moves its agents to Open floor; deleting Open floor is
  refused
- an agent with no placement reads as Open floor
- a placement naming an agent the owner does not have is ignored
- every read and write is scoped: one owner's rooms never appear for another

**Browser**, against the real floor in the dock, where the 2026-09-29 layout
bugs were only ever measurable:

- a dragged robot lands in the room under the pointer and survives a reload
- a room with no agents still draws, since an empty department is now a thing
  you can make on purpose
- every agent is still wholly inside a room after a move, which is the
  invariant `test_every_agent_stands_fully_inside_a_room` already pins

**On the server.** Seeding against the owner's real seven agents, because the
seed path depends on live tool lists and CLAUDE.md is explicit that an import
check will not catch a `NameError` in a function body.

## Files expected to change

- `migrations/054_agent_rooms.sql` (new): both tables.
- `agent_rooms.py` (new): seeding, reads, writes, the Open floor rule.
- `routes_agents.py`: the five endpoints.
- `agent_events.py`: the `rooms_changed` event.
- `static/office.html`: read rooms instead of deriving them, delete `zoneFor`,
  add dragging.
- tests as above.

## Explicitly out of scope

The collaboration choreography, which is the next piece: agents walking to the
colleague they are asking, talking there, and walking back. It is listed third
in the owner's order and wants rooms to be real first, so that an agent walks
to where it was actually put.
