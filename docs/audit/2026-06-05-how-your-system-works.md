# How Your System Works

A plain-language guide to your AIUI platform — the no-code chatbot that lets people build websites and schedule automated tasks by chatting in Slack or Discord.

---

## 1. The big picture

Your product lets everyday people build a working website and set up automated recurring tasks (like "summarize my emails every morning") without writing any code — they just chat with a bot inside Slack or Discord. Behind the scenes, an AI does the actual website-building work, and the bot walks the user through it with friendly buttons and fill-in-the-blank forms instead of asking them to type commands. Think of it like a vending machine for websites and automations: the user picks what they want from buttons and menus, describes it in a sentence or two, and a few minutes later the finished product pops out with a shareable link. The whole experience is designed so nobody ever sees code, server settings, or technical jargon — at least, that's the goal.

---

## 2. The journey of a user

Here is what actually happens, step by step, from a brand-new person to a live website.

**Step 1 — They find the panel.** In a Slack or Discord channel, there's a pinned message (like a permanent welcome card) titled "AIUI App Builder" with two buttons: **Build an app** and **My apps**. There's a second pinned card for **Scheduled tasks**. This panel is the front door — there is no separate website to visit and no app to install.

> **Important reality check:** A new person who simply *types a sentence* ("hey, can you build me a website?") into the channel gets **no response at all**. The bot only reacts to button clicks, pop-up forms, and one specific typed command. A first-timer has no way to know this, so the bot can feel broken or offline until they happen to click a button.

**Step 2 — They prove who they are ("linking").** Before the bot will build or publish anything tied to *their* account, it needs to know who they are. On Slack, it tries to read their email automatically from their Slack profile. On Discord, the person must type in their work email and then **wait for a human administrator to approve them** by clicking a button in a private admin channel. This is the biggest stumbling block today (more on that in Section 4).

**Step 3 — They start a build.** They click **Build an app**. The bot opens a **private space just for them** — a private thread on Discord, or a direct message (DM) on Slack — so their work isn't visible to the whole channel. Inside that private space, the bot shows a dropdown of ready-made **templates** (a landing page, an online store, a booking site, a blank canvas, etc.).

**Step 4 — They describe what they want.** After picking a template, a small pop-up form appears: *"Describe your app"* with an example like *"a portfolio site for Maya, a UX designer."* They type a sentence or two in plain English and hit submit.

**Step 5 — The AI builds it (the waiting room).** The bot replies *"Building… I'll post the link here when it's ready (usually a few minutes)."* Behind the scenes, an AI coding agent is actually writing all the website files, checking its own work, and sometimes redoing parts to get it right. This can genuinely take several minutes to much longer. During this whole time the chat shows **nothing new** — no progress bar, no "still working" heartbeat. To the user it can look frozen.

**Step 6 — The app is ready.** When it's done, the bot posts a **"Build ready"** card with a green **Publish** button, an **Open preview** link (to see it privately first), and a **Visual Editor** link (a separate web page where they can tweak the design).

**Step 7 — They publish.** They click **Publish**, and the bot posts a **"Published!"** card with the **live, shareable web address**. The site is now real and public. They also get an **Unpublish** button if they want to take it down later.

**Step 8 (optional) — They schedule a task.** Separately, from the Scheduled Tasks panel, they can set up something recurring — for example, *"summarize my unread emails every morning."* They fill in *what to do* and *when*, and if the task needs access to their Gmail or Google Drive, the bot gives them a **Connect** link to grant permission. From then on, the task runs automatically and results are delivered to their private message.

**Step 9 — They manage everything.** The **My apps** button lists everything they've built, each with buttons to preview, publish/unpublish, edit, check status, or delete. The schedules dashboard similarly lets them run-now, pause, resume, edit, or delete each automated task.

---

## 3. The main parts and what each does

**The Discord bot.** This is one of the two "storefronts" where users interact with your product. It works entirely through Discord's slash command (`/aiui`), buttons, and pop-up forms — *not* free typing. It opens private threads for each user's build, shows template pickers, runs the build/preview/publish flow, and handles scheduling through a button-driven "pick how often / pick a day / pick an hour" approach. It's the more developer-flavored of the two surfaces: some of its wording still leaks technical terms (it even calls the scheduler "Cron Jobs"), and it relies on an admin manually approving each new user.

**The Slack bot.** The second storefront, mirroring the Discord experience but using Slack's style. Most of the action happens in **direct messages** with the bot — when a user clicks a button in a channel, the real work quietly moves to their DMs, and the channel just shows a tiny "Sent to your DM" note. Unlike Discord, the Slack bot *does* reply when you @-mention it or DM it directly (it answers as a general AI chatbot), and it tries to identify users automatically from their Slack email rather than requiring admin approval.

**The App Builder backend (the "engine room").** This is the powerhouse that nobody sees. When someone submits a build request, this service reserves a unique web address, writes a detailed instruction sheet for the AI, and launches the AI coding agent to actually create the website files. It also powers the "Enhance/edit an existing app" feature. One important limitation: **only one app on the entire platform can be built at a time** — if two people try to build simultaneously, the second person is told to wait. The bot then quietly checks on the build every 12 seconds for up to about 30 minutes and speaks up only when it's finished, needs more detail, or failed.

**The scheduler.** This is the part that runs tasks automatically on a repeating basis. The user describes a task in plain English ("every morning") or, on Discord, clicks frequency buttons (Daily, Weekly, etc.). The system translates that into a time-code that computers understand, so the user (ideally) never sees the technical syntax. It runs each task on schedule and sends the results back as a message, and lets users pause, resume, run-now, or delete their tasks.

**The connectors (Gmail / Google Drive).** These let a scheduled task actually reach into a user's Google account — for example, to read their email so it can summarize it. When the bot detects a task needs this access, it shows a **Connect** button that sends the user through Google's permission screen. (Note: this connection step currently appears to be unreliable in the code — see Section 4 — so users may get stuck in a "still not connected" loop even after they grant access.) Despite occasional mentions of other tools like Supabase, the only connectors that actually exist are Gmail and Drive.

**The front door (behind everything).** Every message from Slack and Discord first lands at a single entry point that verifies the request is genuine (not a forgery) before passing it to the right handler. This is plumbing the user never sees, but it's the security checkpoint that keeps impostors out.

---

## 4. Where Slack and Discord differ today

The two storefronts are *supposed* to feel like the same product, but in practice they've drifted apart. Here are the differences that matter most for a business owner to know:

**How users get identified.**
- **Slack** reads the user's email automatically from their profile. If it can't, the user sees a message asking an admin to grant a permission called "users:read.email" — pure jargon a normal person can't act on.
- **Discord** makes users type their email and then **wait for a human to approve them** — and crucially, **the user is never told when approval happens**. They submit their request, see "an admin will review it shortly," and then... silence. They have to keep guessing and retrying to find out if they're in.

**Setting up a schedule.**
- **Slack** lets users type the timing in plain English ("every morning") — but its form **leads with developer cron syntax** (`0 9 * * *`) in the hint, which can scare off non-technical users. Slack's form also labels the field "When?" (which sounds like a one-time event, not a repeating one).
- **Discord** is button-driven (Daily/Weekly/Hourly), which is friendlier — *except* its "Custom" option drops users straight into a raw **cron expression** box with no plain-English alternative. Discord also brands the whole feature "Cron Jobs," which is engineer-speak.

**Timezone confusion.** Discord's time picker at least says "(Asia/Manila)." Slack's schedule form **never mentions a timezone at all** — so a user outside the Philippines who schedules "every morning" may have it fire at the wrong local time and never understand why.

**Editing an existing app.** On **Slack, the "Enhance" (edit my app) button is effectively missing** from the menus where it's supposed to appear — so a Slack user who wants to change an app they already built may have no obvious way to do it, even though the feature exists under the hood. Discord has historically exposed this button.

**Color coding is reversed.** The cards that signal "is my app live yet?" use **opposite colors** on the two platforms (one uses green for "ready but not yet live," the other uses green for "published"). A user who learns one platform will misread the status on the other.

**The "not linked" error messages contradict each other and name a specific person.** Across both platforms, when a user isn't recognized, they often get a message saying **"Ask Lukas to add you."** A new customer has no idea who Lukas is. Worse, *other* messages tell the same user to just click a "Link my account" button themselves — so the advice is inconsistent, and the self-service path (the one that actually works) is often hidden.

---

### Two themes worth your attention

Reading across both platforms, two issues come up again and again and are worth flagging to whoever maintains the product:

1. **Silence during waits and failures.** Whether it's a build in progress, a pending approval, or a background task that quietly crashed, the system very often leaves users staring at a screen with no feedback. Much of the time, the only place a problem is recorded is in the server logs — invisible to the user, who just assumes the bot is broken.

2. **Jargon and dead ends leaking through.** Despite the "no-code, no-jargon" promise, users still run into machine-style app names (slugs like `maya-portfolio-3a1f`), raw cron codes, error messages meant for engineers, and a hardcoded "Ask Lukas" instruction. These are the rough edges most likely to make a non-technical first-timer give up.

Both of these are fixable, and addressing them would make the product feel as smooth as it's pitched to be.