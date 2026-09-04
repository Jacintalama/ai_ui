# Each agent's reply is its own message

Date: 2026-09-04
Status: approved, not yet implemented

## The problem

When two agents answer one message, the web chat shows one bubble with both
replies in it. Ralph has asked three times, with screenshots, for each agent
to send its own message, the way people do in a group chat. The attempts so
far, a name row per section and then a cloned message row per agent, are
overlays on one message. They look right in a fresh tab and fall apart in an
old one, and a person can tell they are not real messages.

The constraint is Open WebUI's: a pipe returns one reply and one reply is
one message. Every event a pipe can send acts on the current message; none
creates a new one. Checked in `open_webui/socket/main.py::get_event_emitter`,
where `status`, `message`, `replace`, `embeds` and `files` all key on
`request_info["message_id"]`.

## Two facts that make it possible anyway

Both verified on the live site on 2026-09-04, with throwaway chats deleted
afterwards.

**The chat is a tree, and it renders assistant after assistant.** Every
message carries `parentId` and `childrenIds`, and `history.currentId` names
the tail. A chat whose history is user, then Ada's message, then Mia's
message as a *child* of Ada's, renders as three stacked messages. Each has
its own row and the last has the full action bar. They are real entries in
the chat's own data, so edit, copy and regenerate work on them.

**A real link click reloads the chat without reloading the page.**
SvelteKit intercepts clicks on same-origin links as soft navigations.
Navigating to `/` and back to `/c/<id>` through two synthetic `<a>` clicks
makes the chat component see its id change and load again: 1.2 seconds,
no flash. A synthetic `popstate` does not work, because SvelteKit checks
its own history state key, and a URL that differs only by a query string
does not work either, because the chat component keys on the id.

## What we are building

**The page takes turns.** One agent answers through the normal pipe reply.
Each further agent is asked for by the page, written into the chat as a real
message, and shown by a soft navigation. They arrive one after another, each
in its own time, which is the arrival Ralph chose.

### The flow

1. A person says "hi team" on IO or Auto (Free).
2. The pipe asks the service, as it does now. The service decides who
   answers, say Ada then Mia, in the order `match_agents` already returns.
   It runs **Ada only** and returns her turn, the rendered text, and a
   `queue` of who is still to speak: `["agent-triage-256e"]`.
3. The pipe returns Ada's reply as the message. When the queue is not
   empty it appends a marker the renderer hides and the store keeps:
   `<!-- aiui:next agent-triage-256e -->`. An HTML comment survives
   markdown rendering invisibly and survives the round trip through the
   chat's storage, which is what lets the page find it after a reload too.
4. The page watches the last assistant message. When it settles and carries
   a marker, the page:
   - waits until Open WebUI has **saved** that message, by polling the
     chat's own API until the stored content of the tail contains the
     marker. Writing earlier races the frontend's own save, which
     replaces the whole chat and would erase anything added before it.
   - shows a typing line beneath the last message: "Mia is typing".
   - asks the service to run Mia, through a user-authenticated endpoint,
     with the chat's messages. The service runs her through the same loop
     as every other turn, so her access level applies, her tools run under
     her ceiling, and `tasks.agent_run` records it.
   - writes Mia's reply into the chat: a new assistant message, child of
     the tail, `model` and `modelName` set to Mia, `done: true`, and the
     marker for the next agent if any remain. `currentId` moves to it.
   - soft-navigates away and back. Mia's message appears.
   - repeats while a marker remains.
5. A single agent named, or nobody, leaves the queue empty and nothing in
   step 4 runs. "hi mia" behaves exactly as it does today.

### The first message is claimed for its agent

Mia's message carries her as its model, so Open WebUI shows her name and
her avatar natively. Ada's message, the pipe's reply, is stored with the
pipe as its model and "Ada:" as a label in its text. While the page has the
chat open for writing, it also rewrites that message: strips the label from
the content, sets `model` and `modelName` to Ada. After the soft navigation
the whole thread is consistent, every message owned by the agent that wrote
it, and none of it depends on the header rewrite in the page script.

The header rewrite stays, for the single-agent case where nothing writes to
the chat. It is a display fix, not data, and that is the honest place for
it.

### The marker

`<!-- aiui:next <model-id>[,<model-id>...] -->`, on its own line at the end
of the reply. Model ids, not names, because a name can be renamed and an id
cannot, and the page hands the id straight back to the service. The page
treats a marker naming an agent the person no longer owns as empty: the
service's membership check refuses it and the page stops, rather than
looping.

The marker is removed from a message's content when the page claims that
message, so it never accumulates and a reloaded chat carries no live
markers once its queue has drained.

### The service

`POST /agents/chat` gains `first_only: bool`. When true, it runs only the
first matched agent and returns `queue`, the remaining agents' ids in
speaking order. When false, behaviour is unchanged, so Discord and Telegram,
which already send one message per turn through their own gateway, are
untouched. The pin is written for the LAST agent in the full list, as now,
so a follow up with no name goes to whoever spoke last.

A new user-authenticated route, `POST /api/tasks/agents/turn`, takes
`{chat_id, agent_id, messages}` and returns `{answer, notes, agent}`. It
uses the existing `current_user` dependency, resolves the agent through
`_agents_for(user.email)` so a person can only ever run their own agents,
and calls the same `_turn_for` the internal endpoint calls. It is the one
new door, and it opens onto code that already has its own gate.

### The page

Lives in `integrations-ui.js`, beside the header rewrite, and reuses
`aiuiAuthHeaders()`. One state machine per chat, keyed on the chat id in
the URL, so switching chats mid-queue abandons the old one: the old chat's
marker is still in its stored content, and the queue resumes the next time
that chat is opened and settles.

The page abandons a queue when the tail message is no longer the one it
found the marker on. The person sent something, or a regenerate replaced
the reply. The marker they left behind in the abandoned message is
harmless: it names an agent that has not spoken, and if the person returns
to that message the queue picks up.

The chat's own API is the only thing the page writes to. `GET
/api/v1/chats/<id>` returns `{chat: {...}}`; `POST /api/v1/chats/<id>`
with the same shape replaces it. The page reads, modifies exactly the tail
and the new message, and writes back. It never constructs a chat from
scratch.

### Errors

Every failure leaves the chat in a state a person can carry on from.

- The service refuses or times out on a queued agent: the typing line
  becomes "Mia did not answer", the marker is left in place so a reload
  can retry, and the queue stops. Nothing is written.
- The chat write fails: the typing line becomes "could not add Mia's
  reply", nothing navigates, and the reply is not lost, because the page
  logs it to the console under a stable prefix. Retried on the next settle.
- The soft navigation fails to land, judged by the row count not growing
  within five seconds: the page reloads the chat the hard way with
  `location.reload()`. The message is already saved, so the only cost is
  the flash this design otherwise avoids.
- A marker names an agent the person cannot run: the service returns 403,
  the page drops that id and continues with the rest of the queue.

### What this does not do

- It does not change Discord or Telegram, which already send one message
  per agent.
- It does not stream an agent's reply token by token. Each agent's message
  appears whole, the way a person's does.
- It does not make Open WebUI's own multi-model feature do this. That
  feature shows answers side by side and bypasses our loop.
- It does not remove the DOM-clone split immediately. It is switched off
  the moment a marker is present, so the two never fight, and removed in
  the same change once the new path is verified live.

## Testing

The rule this project keeps relearning: every real defect here was found by
running code, and every check that missed one was reasoning about code.
Three of this feature's load-bearing facts were found only by driving a real
browser against the live site, and no test that greps a script would have
caught the DOM shape change that silently killed the header rewrite. So the
page half of this is verified in a browser, not by string assertions.

**Service**
- `first_only` runs exactly one agent, returns the rest as `queue` in
  order, and still pins the last agent in the full list.
- `first_only` with one agent named returns an empty queue.
- The user route refuses an agent the caller does not own, and refuses
  without the caller's token.
- The user route's turn is recorded in `tasks.agent_run` like any other.
- The marker is rendered only when the queue is non-empty, and never for a
  single agent.

**Page, in a real browser against the live site**
- "hi team" produces two message rows, Ada's then Mia's, each with its own
  model and its own action bar, and a reload shows the same two rows.
- The first message's stored `model` is Ada's after the claim.
- No marker remains in any stored message once the queue drains.
- Sending a new message mid-queue abandons it, and the abandoned marker
  resumes when the chat is reopened.
- A refused agent produces the failure line and leaves the chat usable.
- Three agents named produce three rows in speaking order.

**Mutation**, because a browser test that passes proves nothing until it
has been seen to fail: with the save-wait removed, the first agent's
message must be lost; with the marker rendering removed, the page must do
nothing; with the membership check removed from the user route, a stranger
must be able to run somebody's agent.

## Deploy

`tasks` changes (new route, `first_only`), both pipes change (the marker),
and `integrations-ui.js` is bind-mounted, written with `cat >`, never
`scp`, or the inode changes and the mount breaks. Order is tasks first, so
the page's new endpoint exists before any page can call it.
