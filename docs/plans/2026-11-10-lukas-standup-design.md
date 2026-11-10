# Lukas standup 2026-11-10: design

What Lukas asked for at the end of the 2026-11-10 call, and how each is built.
The user approved the recommended approach for every item up front ("start all
of it complete").

## 1. mcp-proxy memory

**Measured.** The proxy container holds about 1,060 MB against a 1,200 MB limit.
987 MB of that is the heap of the FastAPI process (`uvicorn main:app`). The
FastMCP process beside it, which never loads the search model, is 56 MB. On
every start `store_tool_embeddings` re-embeds all 336 tool texts in one
`model.embed(texts)` call (fastembed's default batch, 256). Reproduced with the
server's library versions and the 336 stored texts: 617 MB peak with the
default batch, 243 MB in batches of 32, 207 MB in batches of 8, and the memory
is kept afterwards.

**Approaches.**
1. Batches of 32, and embed only tools whose text changed (recommended).
2. Batches only. Simple, still embeds 336 texts on every start.
3. Drop semantic search for keyword search. Loses a working feature.

**Design.** `tool_embeddings.py` gains a `text_hash` column (added with
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`). At startup it reads the stored
hashes, embeds only the tools whose text is new or changed, in batches of
`EMBED_BATCH` (32), and writes their hash. When nothing changed, the model is
not loaded at boot at all; the first semantic search loads it, as it is lazy
already. The first start after deploy still embeds all 336, once, in batches.

**Check.** Process memory after two restarts on the server, and the log line
saying how many were embedded.

## 2. ClickUp from the chat: create, move, assign

**Measured.** Only one account has ClickUp connected (Ralph). His held calls
show the failure: the model passed `assignees: ["ralphbenitez32@gmail.com"]`
and once `assignees: "ralphbenitez32@gmail.com"`, while ClickUp takes numeric
user ids; on 2026-11-10 it dropped the assignee altogether. `update_task` takes
`assignees` as `{"add": [...], "rem": [...]}` with both keys required. Any 400
reaches the model as "ClickUp returned an error (400)." with ClickUp's reason
thrown away. "Move between columns" is `update_task.status`, which must be one
of that list's statuses exactly.

**Approaches.**
1. Resolve people and columns in the tool layer (recommended). The model may
   say "ralph", an email or an id, and "done" or "In Progress"; the service
   looks them up and either sends the right value or says exactly what is
   valid.
2. Add a "list members" tool and tell the model to call it first. Costs tool
   rounds, which the chat is already short of, and still trusts the model.
3. Docstring changes only. A prompt is not a guarantee.

**Design.** In `mytools.py`, ClickUp `create_task` and `update_task` pass
through `clickup_people.py` before the call:
- Assignees: each value is an id, an email, a username or a first name,
  matched against the members of the person's workspaces
  (`GET /team`). An unknown or ambiguous name returns an error naming the
  people who are there. `update_task` accepts a plain list as "add" and fills
  a missing `add` or `rem` with `[]`.
- Status: matched without case against the list's statuses
  (`GET /list/{id}`; for `update_task`, the list comes from `GET /task/{id}`).
  "done", "complete" and "finished" map to the list's closed status when it
  has exactly one. No match returns the list's columns.
- A ClickUp 400 or 422 passes ClickUp's own reason through `_vendor_said`,
  which already refuses to repeat anything containing the credential.
- `update_task`'s summary says it moves a task to another column and assigns
  people, so tool search finds it for "move" and "assign".

**Check.** Unit tests on response shapes taken from ClickUp's own API
reference. A live check needs a connected ClickUp account; the only one is a
teammate's, so that waits for permission.

## 3. Video loading in the chat

**Now.** One grey line: "Waiting to start rendering, 1 min so far."

**Design.** The same panel a build already shows (`aiuiStepPanel`), for a
video: In the queue, Writing the script, Recording and rendering, with the
current step marked, a moving bar on the step in progress, and the minutes.
While queued it says how many are ahead, or that it is waiting for room on
the server. Motion is a CSS animation that stops under
`prefers-reduced-motion`. No icons.

## 4. App preview polish

1. **The panel waits for a reply.** The build step panel had the race the
   video player had on 2026-11-09: drawn before any reply is on screen, it
   lands at the end of the page and stays there. It now waits for a reply.
2. **Loading state.** An app panel shows "Loading the app" over a dark frame
   until the app's page has loaded, instead of a blank white box. Lukas: "it
   needs an embed, which takes time".
3. **Side view shows the desktop layout.** The side panel is half the window,
   about 700 px on a laptop, so an app drops to its phone layout. The frame is
   laid out at 1280 px and scaled to fit the panel, so the app shows its
   desktop layout. Pointing at something to change it still works, because
   the browser maps clicks through the scale.

## 5. New agents pick their skills

**Measured.** The main chat already suggests skills for a new agent from its
role and instructions, by keyword. The agents page has none: a new agent's
skills are picked by hand from 68. The keyword match is weak: for "keep our
ClickUp tasks up to date, move tasks between columns" it offers only
`meeting-to-tasks`.

**Approaches.**
1. Jev (the decisions API) judges every skill against the description in one
   call, with the keyword match as the fallback, and the agents page pre-ticks
   what it picked for a new agent (recommended).
2. Keyword match only, shown on the agents page. Cheap, weak.
3. Pick at save on the server. The agents page saves through Open WebUI's own
   API, so there is no server step to hook.

**Design.** `agent_skills.pick_for(email, text, pool)` asks Jev one yes/no
question per skill in a single call and keeps those it is sure of, best first,
at most five; Jev unavailable means the keyword suggestion. Both the main
chat's agent creation and a new route, `GET /agents/skills/for`, use it, and
the route also returns which picks need an app connected. On the agents page,
for a NEW agent, leaving the instructions box pre-ticks the picks (only while
the person has not ticked anything themselves) and says "Suggested from the
description", with a link to suggest again.

## Not in this round

- Triage agent from Trello: needs a working Trello connection to test.
- Rotating the webhook token on the Trello test rule: a teammate's setup.
