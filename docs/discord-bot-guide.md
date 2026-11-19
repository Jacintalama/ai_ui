# IO Platform — Discord Bot Guide

This is the complete, plain-English guide to the AIUI Discord bot: every channel, every
feature, and how it all works under the hood. It's written so a brand-new team member can
read it top to bottom and understand the whole thing.

> The **same bot brain** powers Slack too. This guide is Discord-focused; where Slack
> behaves differently, it's called out.

---

## At a glance

| Feature | What it does | Channel | How you start it |
|---|---|---|---|
| **Link your account** | Connects your Discord user to your work email so everything you make is yours | any panel | 🔗 **Link my account** |
| **App Builder** | Build, preview, publish & edit web apps with AI — no code | `#app-builder` | 🚀 **Build an app** |
| **Scheduler** | Run any AI task on a repeat or one-time schedule, results to a private thread | `#app-builder` (schedules panel) / `#cron-jobs` | ⏰ **Open my schedules** |
| **Recruiting Outreach** | Find engineers on GitHub, review the list, edit drafts, then *you* send the emails | `#recruiting` | 🔍 **Find Engineers** |

**Table of contents**
1. [Start here — Link your account](#1-start-here--link-your-account)
2. [Channels & panels](#2-channels--panels)
3. [App Builder](#3-app-builder)
4. [Scheduler (recurring & one-time tasks)](#4-scheduler-recurring--one-time-tasks)
5. [Recruiting Outreach](#5-recruiting-outreach)
6. [How it works (under the hood)](#6-how-it-works-under-the-hood)

Every button/menu in Discord carries a hidden `custom_id` (e.g. `aiuibuild:publish:<app>`).
You never see these, but they're listed per-feature so an engineer can trace any click to its
handler.

---

## 1. Start here — Link your account

### Why it's required

Every feature acts on behalf of **your identity**, not a shared bot account. When the bot
builds an app, runs a schedule, or sends outreach, it passes **your work email** to the
backend, and everything you create is stored as *yours* (your apps, your schedules, your
outreach). Until you link, the bot can't act for you — clicking any feature just shows a
friendly "link first" prompt.

### The flow

1. **🔗 Link my account** (`aiuilink:start`) — on the schedules and recruiting panels, and on any "not linked yet" message.
2. **Enter your work email** in the popup (`aiuilink:modal`). The email format is validated; a typo gets a gentle retry.
3. **An admin approves it.** Your request is posted to a private admin channel with **✅ Approve** / **✖ Reject** buttons (`aiuilink:approve:<id>` / `aiuilink:reject:<id>`). You get an ephemeral "Request sent — an admin will review it shortly."
4. **You're in.** On approval you get a DM — *"🎉 You're in! Tap 🚀 Build an app to create your first one."* From then on every feature resolves to your real email and just works.

> **Schedules & App Builder** are usable even before a formal link (they fall back to a stable
> per-Discord-user identity), but anything that needs **Gmail/Drive access** (like sending
> email) will prompt you to connect that account first.

| custom_id | Trigger |
|---|---|
| `aiuilink:start` | "Link my account" → opens the email popup |
| `aiuilink:modal` | Email popup submit → posts an approval card to admins |
| `aiuilink:approve:<discord_id>` | Admin approves |
| `aiuilink:reject:<discord_id>` | Admin rejects |

---

## 2. Channels & panels

Each channel has a **pinned panel** (buttons that never expire). Most real work happens in a
**private per-user thread** the bot opens for you — only you and the bot can see it.

### `#app-builder`
The hub for building apps **and** managing schedules. It has **two** pinned panels:

| Panel | Buttons |
|---|---|
| App Builder | 🚀 **Build an app** · 📂 **My apps** |
| Scheduled tasks | ⏰ **Open my schedules** · 🔗 **Link my account** |

### `#cron-jobs`
A dedicated scheduling channel (older-style panel). Default name `cron-jobs` (configurable):

| Buttons |
|---|
| ⏰ **Schedule a task** · 📋 **My schedules** |

### `#recruiting`
Find engineers and run outreach. Pinned panel:

| Buttons |
|---|
| 🔍 **Find Engineers** · 🔗 **Link my account** |

### Admin / alerts channel
An internal channel (set by the `DISCORD_ALERT_CHANNEL_ID` setting; its display name isn't
hard-coded). The bot posts **account-link approval cards** and system alerts here. No pinned
panel — cards appear as needed.

> **Private threads:** Build an app → `aiui-apps-<you>`; Open my schedules → `schedules-<you>`.
> They keep your work, previews, and results out of the public channel.

---

## 3. App Builder

Build, preview, publish, and iterate on **web apps** entirely from Discord — no code. The bot
is the interface; an AI agent does the actual building.

### Build a new app
1. **🚀 Build an app** (`aiuibuild:new`) → the bot opens your private `aiui-apps-<you>` thread.
2. **Pick a template** from the *"Pick a template…"* dropdown (`aiuibuild:tplselect`), or hit **⬜ Blank** (`aiuibuild:tpl:`) for an empty project.
3. **Describe your app** in the popup (`aiuibuild:build:<template>`) — e.g. *"a portfolio site for Maya, a UX designer"* (up to 4,000 characters).
4. **The agent builds it.** The bot says *"Building <name>… I'll post the link here when it's ready (usually a few minutes)"* and watches in the background.
5. **"✅ Build ready"** appears with:
   - 🟢 **Publish** (`aiuibuild:publish:<app>`)
   - 🔗 **Open preview** (when a preview URL exists)
   - 🎨 **Visual Editor** (a signed web deep-link — see below)

   *(If the agent needs clarification it asks; if it failed it tells you to retry.)*

### Publish / Unpublish
- **🟢 Publish** flips the app live and rewrites the message into a **"🎉 Published!"** state with **🔗 Open live** and a red **🔌 Unpublish** (`aiuibuild:unpublish:<app>`).
- **🔌 Unpublish** takes it offline again.

### Enhance (edit with AI)
An **Enhance** button (`aiuibuild:enhance:<app>`) opens a popup — *"What do you want to change?"*
(e.g. *"make the header green and add an About section"*). The agent edits the app and posts a
fresh "Build ready" with a new Publish button.

### Visual Editor
The **🎨 Visual Editor** button opens a browser deep-link into the web editor for that app,
signed with a short-lived, app-bound token (`/tasks/edit/<app>?token=…`). It only appears when
the bot can confirm you own the app.

### My apps
**📂 My apps** (`aiuibuild:myapps`) → a dropdown of your apps (`aiuibuild:appselect`). Pick one
to get a state-aware card: 🎨 Visual Editor · 🟢 Publish *or* 🔌 Unpublish · 🔗 Open preview/live ·
ℹ️ **Status** (`aiuibuild:status:<app>`, shows name/published/URL/last-change) · 🗑 **Delete**
(`aiuibuild:del:<app>` → confirm card with **🗑 Delete it** / **✖ Cancel**).

| custom_id family | Purpose |
|---|---|
| `aiuibuild:new` / `:myapps` | Build / manage entry buttons |
| `aiuibuild:tplselect` / `:tpl:<key>` | Template dropdown / Blank |
| `aiuibuild:build:<key>` | "Describe your app" popup |
| `aiuibuild:publish:<app>` / `:unpublish:<app>` | Go live / take down |
| `aiuibuild:enhance:<app>` / `:enhancemodal:<app>` | AI edit |
| `aiuibuild:appselect` / `:status:<app>` / `:del:<app>` / `:del-confirm:<app>` / `:del-cancel:<app>` | Manage / status / delete |

---

## 4. Scheduler (recurring & one-time tasks)

Automate any task the AI agent can do — *summarise my unread emails*, *post a Friday digest* —
on a **repeat** or as a **single future run**. No cron syntax: it's all buttons and dropdowns,
and results land in your private thread.

### Open & create
1. **⏰ Open my schedules** (`aiuisched:open`) → your private `schedules-<you>` thread with a **➕ New schedule** button (and a dropdown of existing ones).
2. **➕ New schedule** (`aiuisched:new`) asks **"When should this run?"** → **🔁 Repeating** or **1️⃣ Just once**.

**Repeating** → friendly dropdowns:
| Dropdown | Options |
|---|---|
| How often? | Every day · Weekdays · Every week · Every hour · Every 30 min |
| What time? (Manila) | whole hours, 12 AM–11 PM |
| Which day? (weekly only) | Sunday–Saturday |

**Just once** → quick-picks **Today / Tomorrow / Next Monday**, or a 14-day date dropdown (e.g.
*"Mon, Jun 15"*) + a time. If you pick a time that's already passed, it tells you to choose a
future time.

Either way, hit **✅ Set the task** to open *"What should it do?"* (up to 2,000 chars). Prefer
typing? **⌨️ Type it instead** lets you write the *what* and the *when* in plain English
(*"every Monday 9am"*, *"every 30 minutes"*).

### Confirm (and connect if needed)
The bot shows a plain-English summary — *"📅 every Monday at 9:00 AM — {your task}. Look right?"*
with **✅ Confirm** / **✖ Cancel**. If the task needs Gmail/Drive and you haven't connected it,
you first get a **🔌 Connect …** link + an **✅ I've connected — create it** button.

> All times are **Manila / GMT+8** (no daylight saving) — *9:00 AM* always means 9 AM Manila.

### Manage existing schedules
Pick a schedule from the dropdown to get a colour-coded card (🟢 active · ⏸ paused · ⚠️ last run
failed · ⏳ running) with:
**▶️ Run now** · **⏸ Pause** / **▶️ Resume** · **✏️ Edit** (re-opens a pre-filled popup) · **🗑 Delete**.
A failed run's result comes with a **🔁 Retry** button.

| custom_id | Action |
|---|---|
| `aiuisched:open` / `:new` | Open dashboard / start the picker |
| `aiuisched:pick:<field>:<token>` | Picker navigation (frequency/time/day/date) |
| `aiuisched:confirm:<token>` / `:cancel:<token>` | Confirm / cancel creation |
| `aiuisched:connected:<token>` | "I've connected" resume after OAuth |
| `aiuisched:run:<id>` / `:pause:<id>` / `:resume:<id>` / `:edit:<id>` / `:del:<id>` | Per-schedule controls |

---

## 5. Recruiting Outreach

Find software engineers on GitHub, **review the list, edit the drafts**, and only then send the
emails. (On **Discord** you're in control; on **Slack** the old behaviour stays — it finds and
auto-sends in one step.)

### 1) Find
**🔍 Find Engineers** (`aiuiout:find`) opens a popup (`aiuiout:modal`): **Skill / language**
(required), **Location** (optional), **Job description** (required), **How many to find**
(default 10, max 25).

### 2) The agent searches + drafts — *nothing is sent yet*
The AI agent searches the **GitHub API** (authenticated with a GitHub token) for matching users,
reads their public profiles for an email (and uses web search to find one when GitHub doesn't
expose it — it never fabricates an address), and **drafts a short personalised email per
engineer**. The results are stored for your review; **no email goes out at this stage.**

### 3) Review, select, edit
The bot posts an **overview message**:
- A **list** of everyone found (✅ selected · ⬜ not selected · ⚠️ no email).
- **Select who to email** (multi-pick) — only people *with* an email are selectable.
- **Edit / add-email for one…** — opens a popup to rewrite the **subject/body**, or **add an
  email** to a no-email find (which then makes them selectable).
- **📧 Send to selected (N)** · **♻ Refresh**.

Only the person who ran **Find** can drive this (the backend checks ownership).

### 4) Send (your trigger)
Press **Send** and *only the selected engineers* are emailed via the **n8n** workflow (using a
Gmail account), and everyone is logged to a **Google Sheet**. Anyone already in the sheet is
**deduplicated** (not emailed twice). The message then locks to a sent summary with the sheet
link.

**The n8n workflow** (`recruiting-outreach`): `Webhook → read the sheet → dedupe by email →
has-email? → (Gmail Send + append row) / (append row only) → respond {sent, saved, sheet_url}`.

| custom_id | Component |
|---|---|
| `aiuiout:find` / `aiuiout:modal` | Find button / the role popup |
| `aiuiout:sel:<task>` | "Select who to email" multi-pick |
| `aiuiout:edit:<task>` / `aiuiout:editmodal:<task>:<cid>` | Edit dropdown / the edit popup |
| `aiuiout:send:<task>` / `aiuiout:refresh:<task>` | Send / refresh |

---

## 6. How it works (under the hood)

### The stack
Everything runs in **Docker containers on one Hetzner VPS**: `caddy`, `api-gateway`,
**`webhook-handler`** (the bot), **`tasks`** (the AI/job backend), `n8n`, `postgres`, `redis`,
`open-webui`, an `mcp-proxy` + per-tool MCP servers (GitHub, Gmail, Drive, Calendar…), and
Grafana/Loki for logs. Only Caddy faces the internet; the rest talk over a private Docker
network.

### The request path
```
You click a button in Discord
  → Discord SIGNS the request and POSTs it
  → Cloudflare (CDN/DDoS) → Caddy (TLS) → API Gateway (auth/rate-limit)
  → webhook-handler (the bot):
        1. verifies Discord's Ed25519 signature (drops anything unsigned)
        2. routes by the button/menu's custom_id
        3. replies within Discord's ~3-second deadline — usually "working…"
           (a "deferred" response), then finishes in the background
  → calls the tasks service (FastAPI)
        → which runs the AI agent (Claude) on a SEPARATE, network-sandboxed VM over SSH
              → which talks to GitHub / Google / n8n through allowed paths only
  → result is sent back and the bot edits its "working…" message into the answer
```

### A few key details
- **Signed requests.** Discord signs every interaction with the app's private key; the bot
  verifies it with the matching public key (PyNaCl). Unsigned/forged requests get a `401`.
- **The 3-second rule.** Discord fails an interaction if the bot doesn't reply in ~3 s. So for
  real work the bot immediately returns a "thinking…" (deferred) response, does the work in an
  `asyncio` background task, then edits the message with the result. For long jobs (app builds)
  that outlive the 15-minute interaction window, it posts a fresh message with the bot token
  instead.
- **One brain, two chat apps.** Discord and Slack both translate their clicks into the same
  internal `CommandContext` and run through the **same** command router — so a feature behaves
  identically on both (Discord verifies an Ed25519 signature; Slack verifies an HMAC secret).
- **The agent is sandboxed.** The AI agent doesn't run on the main server — the tasks service
  SSHes into a dedicated agent VM, syncs the workspace over, runs Claude there, streams the
  output back (scrubbing any secrets), and syncs results back. That VM has a **network egress
  allowlist** — it can only reach approved destinations (e.g. Anthropic, GitHub, package
  registries), which is why enabling GitHub for the recruiting feature required explicitly
  allowing `api.github.com`.
- **Integrations.** GitHub (search), Gmail/Drive/Calendar (per-user OAuth, tokens stored
  encrypted), and **n8n** (the email-sending workflow engine) are all reached over the private
  network, never directly by the agent VM.

---

### Where the code lives (for engineers)
| Area | Files |
|---|---|
| Discord routing | `webhook-handler/handlers/discord_commands.py` |
| Shared command logic | `webhook-handler/handlers/commands.py` |
| UI builders (buttons/modals) | `webhook-handler/handlers/app_builder_panel.py`, `recruiting_panel.py`, `recruiting_review.py`, `schedule_picker.py` |
| Backend (apps/schedules/outreach + agent) | `mcp-servers/tasks/` (`routes_outreach.py`, `outreach.py`, `remote_executor.py`, …) |
| Email workflow | `n8n-workflows/recruiting-outreach.json` |
| Deploy/infra notes | `CLAUDE.md`, `docker-compose.unified.yml` |

*Generated from the live codebase. If a flow changes, update this guide alongside the code.*
