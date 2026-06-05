# Bot UX Feature Roadmap — making AIUI usable for non-technical people

**Date:** 2026-06-05
**Method:** 8 parallel code-reader agents mapped every user-facing touchpoint across the Slack + Discord bots and the App Builder backend, then flagged where a non-technical first-timer gets confused, stuck, or scared. 32 friction points (6 blocker-level), 70 errors/gaps, and 21 prioritized features.

Companion docs:
- `2026-06-05-how-your-system-works.md` — plain-language explainer of the whole platform
- `2026-06-05-maria-first-15-minutes.md` — a first-time-user (flower-shop owner) walkthrough

---

## The core problem in one sentence

The product is pitched as *"just chat with a bot, no coding"* — but in reality plain typing is ignored, the real commands are developer jargon (`/aiui aiuibuilder`), new users hit a brick wall that says "Ask Lukas," and successes drop into silence. A non-technical person quits within ~2 minutes without help.

## The 6 blocker-level findings (a non-tech user cannot get past these)

1. **No real conversation.** Typing a normal sentence to the Discord bot does nothing — it only reacts to `/aiui`, buttons, and forms. No listener for ordinary messages. `webhook-handler/clients/discord.py:43`
2. **"Build" doesn't build.** Intent is keyword-prefix matched; `/aiui build me a tracker` is sent to generic Q&A and lectures the user instead of building (the real command is the typo-looking `aiuibuilder`). `webhook-handler/handlers/commands.py:157`
3. **"Ask Lukas" brick wall.** The not-linked message hardcodes a person's name across ~12 call sites, with no self-service fix shown. `webhook-handler/handlers/commands.py:1782`
4. **OAuth-jargon wall on Slack.** The Slack not-linked message tells a florist to "grant the bot the `users:read.email` scope." `webhook-handler/handlers/commands.py:1779-1781`
5. **Approval black hole.** Discord account linking waits for a human admin to click Approve — and the user is *never told* if/when it happened. `webhook-handler/handlers/discord_commands.py:1166-1176`
6. **(Same as #3 on the onboarding path)** — the dead-end appears on build, publish, enhance, unpublish, delete, schedule, and menu paths.

---

## Prioritized feature roadmap

Priority: **P0** = blocks non-tech users today · **P1** = major friction · **P2** = polish/consistency
Effort: **S** ≈ hours · **M** ≈ 1–2 days · **L** ≈ multi-day

### P0 — Get a non-technical user through the front door

| # | Feature | Surface | Effort | What it fixes |
|---|---------|---------|--------|---------------|
| 1 | **First-run welcome + guided setup card** | both | M | New user is dropped onto bare buttons with no instructions. Greet them on first DM/@mention with one card: "Build a website / Schedule a task" + buttons. |
| 2 | **Unified self-service "not linked" message (kill "Ask Lukas")** | both | S | Collapse the 2 contradictory messages into one friendly line + an inline **🔗 Link my account** button. Removes the #1 quit point. |
| 3 | **Notify users when their link request is approved/rejected** | discord | S | After admin approves, DM the user "You're in! Tap Build an app." Today they hear nothing forever. |
| 4 | **Live build progress heartbeat** | both | M | Replace the silent "few minutes" gap with a rotating, edit-in-place status: "Setting things up… Writing your pages… Double-checking it…" |
| 5 | **Guarantee a build result is always delivered** | backend | L | Multiple silent-failure paths (empty channel_id, un-wrapped background tasks, restart kills the watcher). Make completion survive restarts via the result-callback endpoint; wrap every detached task in try/except that always posts a friendly outcome. |
| 6 | **Plain-English schedule parser** | backend | M | The parser rejects its own example ("every Monday 9am" needs "at"). Accept "every weekday at 9am", "noon every day", "twice a day", optional "at", etc. Pure logic, unit-tested. |
| 7 | **Fix the broken Gmail/Drive connect loop** | backend | M | The connect URL and status check point at mismatched endpoints/identities, so users get "still not connected" forever even after granting access. Align the contract + add a round-trip test. |

### P1 — Remove the next layer of friction

| # | Feature | Surface | Effort | What it fixes |
|---|---------|---------|--------|---------------|
| 8 | **Show apps by friendly name, not slug** | both | M | Everywhere shows `maya-portfolio-3a1f` in code font. Capture a display name at build time; show "Maya's portfolio" in all messages. |
| 9 | **Make timezone explicit & consistent** | both | M | Slack never shows a timezone; "every morning" is hardcoded to 8am Manila. Always show "(Asia/Manila)"; ideally store per-user TZ. |
| 10 | **Friendly, actionable error messages** | both | M | Stop dumping raw `{e}` / "Tasks API error (500)" to users. One mapper → plain message + Retry button; log raw detail server-side only. |
| 11 | **Helpful schedule-time error with examples** | both | S | On a parse miss, show 4–6 known-good phrasings instead of a generic retry; preserve the user's typed task. |
| 12 | **Remove cron jargon from Discord; add plain-English typing** | discord | S | The "Custom…" option opens a raw cron box ("min hour dom mon dow"). Relabel to "When? (plain English)" and route through the parser. Rename "Cron Jobs" → "Scheduled tasks". |
| 13 | **Gate the build behind linking up front** | discord | S | Today an unlinked user fills the whole "Describe your app" form, then gets bounced. Check link status at the Build entry and show the Link card first. |
| 14 | **Rewrite `/aiui help` around the two things users want** | both | S | Help is 18 dev commands (pr-review, mcp, OWASP…). Default view: Build / Schedule / Ask as buttons; hide advanced behind `/aiui help advanced`. |

### P2 — Smarter understanding, consistency, and polish

| # | Feature | Surface | Effort | What it fixes |
|---|---------|---------|--------|---------------|
| 15 | **Treat a typed sentence (and unknown commands) as a real request** | both | L | Add an intent classifier before the keyword switch; register a Discord message handler so plain typing at least gets nudged to the right flow. |
| 16 | **Surface "needs more detail" as an in-chat answer, not a dead end** | both | L | When a build needs clarification, ask the question in chat with an Answer button that resumes the same build — instead of "start over". |
| 17 | **Make the connector prompt predictable; warn on misses** | both | M | Broaden keyword coverage; when ambiguous, ask "Does this need your email?" instead of silently creating a task that returns nothing. |
| 18 | **Persist in-flight schedules & pending connects across restarts** | backend | M | Move `_pending_schedules` out of in-memory dicts into the DB/Redis so a redeploy doesn't wipe a half-finished schedule. |
| 19 | **Status button: plain-language app health** | both | S | Replace "Role: editor / Last commit: 2026-06-05T…" with "Live ✅ · your link · updated 2 hours ago". |
| 20 | **Restore the reachable Enhance/edit button on Slack** | slack | S | The handler exists but no Slack panel emits the button. Wire it onto build-ready, published, and My-apps cards. |
| 21 | **Cross-platform consistency pass** | both | S | Inverted status colors, "When?" vs "How often?", cron-first vs plain-first. Adopt one shared copy/label convention. |

---

## Suggested first sprint (highest impact, ~1 week)

The cheapest path to "a non-technical person can actually succeed":

1. **#2** Unified "not linked" + Link button (S) — kills the worst quit point
2. **#3** Approval notification (S) — closes the black hole
3. **#1** First-run welcome card (M) — gives people a starting point
4. **#11 + #6** Schedule examples error + parser fix (S+M) — stops the "rejected my own example" rage
5. **#4** Build progress heartbeat (M) — keeps people from thinking it crashed

That sequence directly removes 4 of Maria's 5 "almost quit" moments. #5 (guaranteed delivery) and #7 (connect loop) are the backend reliability follow-ups.
