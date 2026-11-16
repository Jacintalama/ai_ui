# The triage connects, then carries on, and sees the whole platform (2026-11-17)

## Why

Lukas, call of 2026-11-16, about the triage agent:

> "Imagine the triage agent to do that, to say we have automation, so we
> should connect n8n and pop up the connect field and then they connect it
> and then it starts using it."

> "If it sees all the skills and sees all the integrations ... you demoed
> last time that you said automation and it recommended Zapier and n8n.
> That's what I would like for the other parts, like the app builder ...
> things like that."

Two gaps, measured against the code on 2026-11-17:

1. **The chat stops at the Connect button.** The callback pages already
   tell the tab that opened them (Google: `aiui-<app>-connected`; every
   other OAuth app: `{aiuiOauth: true, ok}`), but nothing in the chat
   listens, and the inline button keeps no handle, no listener, no poll
   (`integrations-ui.js` `wireAiuiConnectLink`). Also, only Notion's button
   opens its login; GitHub, ClickUp, Airtable, HubSpot, Jira, LinkedIn,
   Dropbox and Outlook can all do OAuth on the server but their button
   opens the Connections panel, one click further away.
2. **The triage knows two platform features** (`app_triage.PLATFORM`:
   Publish, Deploy to Vercel). The App Builder, Cron Jobs, AI Agents,
   Automations, Video Generation and Channels are tools the assistant can
   use, but never a recommendation with a button to the place.

## Goals

- Connect from the chat opens the app's own login straight away when the
  app has one (the "connect field").
- When that connect finishes, the button says so, and the chat carries on
  with what the person asked, using the app.
- The triage recommends the platform's own parts the way it recommends
  apps, each with a button that opens that part in place.

## Non-goals

- No change to how any vendor's login works, to the callback pages or to
  the Connections panel (Ralph's lane).
- No new tools. What the assistant can DO in the chat is unchanged.
- Not a cron-job chain across apps (Ralph's lane).

## Anti-goals

- Never send a message the person did not set going. The continue is sent
  only after a connect THEY started from THAT reply, only while they are
  still on that chat, and only when the box is empty; otherwise a
  Continue button waits for their click.
- Never continue on a signal alone: "connected" is confirmed by the
  service before anything is sent.
- No recommendation the platform cannot back: every how-line is checked
  against the page or tool it names.

## Approaches

**Continue after connect.**
- *A. Browser only (chosen).* The chat page notices the connect finished
  (the callback's message, confirmed by `GET /api/tasks/connections` or
  the Google status route, or a poll for apps connected by pasting a key),
  then types "I've connected X. Please go ahead with what I asked." into
  the chat and sends it. The conversation already holds the request, and
  Jev's tool pick reads the turns before it, so the next turn uses the app
  with no server change. Checked live 2026-11-17: a script can type into
  `#chat-input` (TipTap) and `#send-message-button` sends it.
- *B. Server resumes the turn.* The service would remember the request and
  answer it when the token lands. It cannot write into an Open WebUI chat
  the person is looking at, so the answer would land somewhere else.
  Rejected.
- *C. Prefill only.* Put the text in the box and let them press Enter.
  Safer, but it is not "it starts using it". Kept only as the fallback
  (the Continue button) when auto-continue would be wrong.

**More of the platform in the triage.**
- *A. Catalogue entries (chosen).* Six more `Platform` entries, asked in
  the same Jev call as the apps and cut on their own (`platform_pick`),
  re-measured with `scripts/jev_checks_calibrate.py apps 2`.
- *B. Read it off the tool pick.* No new questions, but the tool pick only
  fires when the assistant will act, so "what's the best way to automate
  my leads" would never show IO's own Automations beside n8n and Zapier.
  Rejected.

## The design

### Platform entries (`app_triage.py`)

| id | button | opens |
|---|---|---|
| app_builder | Open App Builder | app-builder |
| cron_jobs | Open Cron Jobs | cronjobs |
| ai_agents | Open AI Agents | ai-agents |
| automations | Set up in AI Agents | ai-agents |
| video | Open Video Generation | video-generation |
| channels | Open Channels | channel |

`OPEN_PLACES` becomes those five places; the page's list matches.
`Platform.rule` carries an entry's own "do not suggest X" line (hosting
for Publish and Vercel, other site builders for the App Builder), so the
hosting line stops appearing under a cron job. One button per place.

### Connect, then carry on (`integrations-ui.js`)

- Wiring a Connect button loads `GET /api/tasks/connections` once (which
  apps can do OAuth here, and which are connected).
- Click: Google as today; an app with `oauth: true` opens a tab and goes
  to its `/oauth/start` (the Notion path, for all of them); otherwise the
  panel.
- While waiting: listen for the callback's message (same origin only) and
  poll every 3 s for up to 10 minutes.
- Done (confirmed connected): the button turns into "✓ X connected", then
  the continue line is sent if the person is still on that chat and the
  box is empty, otherwise a "Continue" button appears beside it.
- Once per button.

## Measured (2026-11-17)

`scripts/jev_checks_calibrate.py apps 2`, 39 cases, about $0.01 a pair of
runs. First pass: AI Agents scored 0.88 on "put a meeting with Ana on my
calendar" and 0.67 on a poem; App Builder 0.82 on "when someone fills in
the contact form on my site"; Channels only 0.60 on "talk to my agents from
Telegram". Each note now says what the part is NOT. Second pass: no wrong
platform pick from 0.60 up in either run, so `platform_pick` is 0.70 by the
rule (lowest clean cut plus one step). What it gives up: Cron Jobs 0.69 on
"remind me every Monday at 9am" (the tool pick still makes the job) and
Publish 0.60 on "my bakery site live on my own domain".

## After review (2026-11-17)

An independent review found these, all fixed:

- Several parts open one page, so the page alone made App Builder count
  as Publish already offered; a part is offered by its own words or its
  own button only.
- "Connect a task tracker" was `#aiui-connect:trello`, which with each
  app's own login would have sent everybody to Trello; it is `tracker`,
  opens the panel, and carries on when any tracker is connected.
- Calendar does have a status route the page can call (by address); it is
  confirmed like the others. A message counts only from the window this
  button opened (`e.source`).
- Auto-send also requires that the reply is still the last one, nothing
  was sent since the click, no dialog is open and no other field has the
  cursor; when Send never appears our text is taken back out; apps that
  finish together are one message; a reply drawn again finds its button
  by message id; a watch that ran out can be started again.
- The Cron Jobs page cannot edit a job, so its line says pause, run or
  delete there and change it here. When the matching tool already did the
  job, the button stays and the how-line goes.

## Left to the builder

Wording of the how-lines (true to the pages), the calibration cases, and
the poll interval.
