# The IO gateway, and the setup assistant

Date: 2026-09-01
Status: approved, not yet implemented

## The problem

Two complaints, one underlying cause: the web chat has none of the machinery the
chat channels have.

**Naming an agent does not reach it.** Open WebUI's `@mention` sets
`atSelectedModel` for exactly one message and then clears it. Observed in
production: `@Triage` was answered by `gpt-5`, the follow-up "hey what are you?"
reached Triage, and "hi triage how can you help me" went back to `gpt-5`. There
is no name routing in the web chat at all, so "hi triage" is just text.

The same feature has worked in Discord and Telegram for weeks.
`gateway/agent_router.py::match_mention` catches an agent's name in an ordinary
sentence, and a pin keeps that agent answering until the person says stop.

**Somebody who does not know how to connect an app gets no help.** There is a
keyword watcher in `integrations-ui.js` that injects a Connect card, but it
covers Google only, it fires on a regex rather than on the model's judgement,
and it never opens the Connections panel. As of today Ralph is the only user on
the platform with any Google connection; everyone else has none.

## What we are building

A **gateway model**, called IO, that behaves like a receptionist: it answers you
itself, it knows what your account has, it can set things up for you with your
say-so, and when you name one of your agents it wakes that agent and hands the
conversation over.

Two phases. Phase 2 depends on nothing in Phase 1, but Phase 1 fixes a live bug
and is the more visible win, so it goes first.

---

## Phase 1: the IO pipe

### Why a pipe and not an inlet filter

An inlet filter would be the obvious way to reroute a message. It does not work.

Verified in `open_webui/utils/middleware.py`: the `model` object is resolved
before inlet filters run (line ~2280), and everything downstream, including tool
resolution and skill loading, reads that already-resolved object rather than
`form_data['model']`. An inlet that rewrote the model id would send the text to a
different model while still applying the **original** model's instructions and
tools. The agent would answer without being itself, which is worse than not
routing at all because it would look like it worked.

A pipe is the proven pattern on this platform. `auto_router`, `auto_smart` and
`fusion_pipe` are all live pipes that pick a model per request.

### What it does

IO appears as one model in the dropdown. For each message:

1. **Is an agent named?** Reuse the matching rule that already works in
   channels: a whole-word match on the agent's name, anywhere in the sentence.
   The names are one word each precisely so this is reliable, and that is why
   the starter agents are called Ada and Mia rather than job titles.
2. **Is one pinned?** A previously woken agent stays awake for follow-ups. The
   pin is stored per chat, in the same state store the channel pin already
   uses, and is released when the person says so ("stop using that", "never
   mind", naming a different agent). Naming a different agent switches rather
   than stacking: one agent is awake at a time.
3. **If an agent is awake**, call `POST /agents/turn` with that agent and the
   conversation, and stream back its answer, prefixed with its name so it is
   obvious who is speaking.
4. **Otherwise IO answers**, as itself, on a base model named in a pipe valve
   so it can be changed without a redeploy. It defaults to the same model the
   channel gateway uses (`settings.gateway_model`) so the two surfaces answer
   with the same voice.

### What this closes

Yesterday's access levels carry a stated limitation: they do not govern the web
chat, because Open WebUI runs its own tool loop there and never reaches our
code. Through the pipe, **our** loop runs, so Read only / With access / All
access mean the same thing on every surface.

The Agents form currently says "Web chat here always has full access." Once this
ships, that sentence comes out, and the modal stops having to admit an edge.

Channel runs are already recorded in `tasks.agent_run`; web chat runs through
the pipe will be too, so the awake/idle line on the agent cards finally reflects
every surface.

### Waking, in the user's words

"Gisingin mo si Mia" and "hi mia" and "@Mia" all mean the same thing. The
matcher works on the name, not on an English verb, so it needs no language
list. What it must not do is match a name inside another word: the channel
matcher already rejects "hijack" for Jack and "analyse" for Ana, and those cases
are already tested.

---

## Phase 2: the setup assistant

### What it can see

One read-only native tool, `my_account`, returning the caller's state: apps
connected, agents with their tools and access levels, schedules, apps built. For
anything not connected, it also returns **how** it connects and the exact link.

This is what lets the assistant say "you have no ClickUp" instead of guessing,
and every other action depends on it for good advice. Read-only, so there is
nothing it can break.

### What it can do

Connect apps, create agents, create schedules. **It cannot delete or disconnect
anything.** Deleting is rare, it is already one click in the UI, and a wrong
deletion is unrecoverable work. `scheduler` is already flagged in this repo as
unsafe to default-grant because it can delete anyone's cron, and there is a real
incident in this project's history where a bad delete path wiped 9 production
projects and all chat history. When asked to clean something up, the assistant
lists what it found and hands over a button per item.

### It asks before it changes anything, and enforces that itself

Every write is two-phase: `setup_propose` returns a plain-language summary and a
token, `setup_confirm(token)` executes it. The model proposes, the person says
yes, it confirms.

Deliberately not built on the per-agent access levels. Those are enforced in our
tool loop, and in the web chat Open WebUI runs its own. Two-phase enforces
itself wherever it runs, with no dependency on machinery that cannot reach one
of the surfaces. Once Phase 1 ships and the web chat goes through our loop, the
access levels apply there too, and the two mechanisms agree rather than one
covering for the other.

### The connect flow

**Nine services work today, and they split into two kinds.**

OAuth, which can show a real vendor login: **Google** (Gmail, Calendar, Drive)
and **Notion**. Those are the only two with a registered OAuth app.

API key paste, which cannot: **ClickUp, Trello, Airtable, HubSpot, GitHub, n8n,
Zapier**. Giving these a login tab is not a coding task; it means registering a
developer app with each vendor, storing a client id and secret, and in some
cases passing review.

The assistant handles both and they feel the same to the user. One button
either way.

**Opening it: popup first, with a one-time nudge.**

Chrome blocks `window.open()` when no click triggered it. That block is
per-site and the user can lift it, after which the system can open the login tab
by itself with no clicks at all. Chrome does the asking for us, so nobody has to
find a settings page:

1. The assistant calls `window.open`. A blocked call returns `null`, so we can
   tell it failed.
2. If blocked, Chrome shows its blocked-popup icon in the address bar, and the
   assistant says so in the chat: click that icon, choose Always allow, and I
   will be able to open these for you. That is a one-time action per browser.
3. Once allowed, every later connect opens the tab directly.
4. **If the person never allows it**, fall back to opening the Connections
   panel, scrolled to the right app and highlighted, and they click Connect
   there. Nobody is ever stuck.

For an API-key service there is no login to open, so it always uses the panel
path, with the right app preselected and a pointer to where that vendor keeps
its keys.

The permission is per browser and per device. Allowing it on a laptop does not
carry to a phone. That is true of every site and is not something we can change.

**The login itself stays the user's.** We do not automate it and will not.
Completing OAuth on someone's behalf would mean holding their actual password
and second factor, which is the exact thing OAuth exists to avoid: a scoped,
revocable token instead of a credential that opens everything. If this box were
ever compromised, the difference is between an attacker holding a token the
owner can kill from one settings page and holding their Google account.

### Retiring the keyword watcher

`detectConnectService` in `integrations-ui.js` fires on `/(gmail|e-?mail|inbox|
...)/ ` appearing anywhere in a message. It is the same shape as the auto-send
watcher already disabled in that same file for popping a modal whenever a
message mentioned sending. Once the model decides deliberately, keyword guessing
is a liability rather than a fallback, and it goes.

---

## What this does not cover

- **No companion app.** A program that clicks on the user's behalf, driven by a
  remote server, is structurally indistinguishable from remote-access malware,
  and it would not help anyway: it cannot type a password or a 2FA code either.
  It would trade an installer, code signing and three OS builds for one click we
  can already remove.
- **No new vendor OAuth registrations.** Worth doing, but it is per-vendor
  paperwork and not a code change.
- **No deletes.**
- **App Builder and video generation are not surfaces in v1.** The mechanism is
  the hard part; adding a surface afterwards is small.

## Testing

The rule this project keeps relearning: every real defect here has been found by
running code, and every check that missed one was reasoning about code.

**Phase 1**

- A named agent is woken; the answer comes back as that agent, not the base model.
- A pinned agent keeps answering follow-ups until it is released.
- A name inside another word does not match.
- A message naming no agent is answered by IO itself and never calls
  `/agents/turn`.
- An agent set to Read only refuses a write **in the web chat**, which is the
  behaviour that does not exist today and is the whole point of routing through
  our loop.
- A `/agents/turn` failure produces a readable sentence, not silence.

**Phase 2**

- `my_account` returns only the caller's own data. An admin calling it must not
  receive anyone else's.
- A write refuses to execute without a matching confirm token.
- A confirm token is single use.
- A blocked popup is detected and produces the nudge rather than silent nothing.
- The panel fallback opens on the correct app.
- Nothing in the tool surface can delete.

**On the server**, per level and per surface, with a real browser and a real
Discord message. Wiring inside a function body is not caught by an import or a
unit test, and this pipeline has been bitten by exactly that twice.

## Deploy

`tasks` and `open-webui` both change; the pipe is installed as an Open WebUI
function, and `integrations-ui.js` is bind-mounted so it must be written in
place with `cat >`, never `scp`, or the inode changes and the mount breaks.

Order is tasks first. The pipe has nothing to call until `/agents/turn` exists,
which as of 2026-09-01 it does.
