# Design — Onboarding & Linking (Bot UX Sprint, Theme 1)

**Date:** 2026-06-05
**Status:** Approved (design), pending implementation plan
**Source:** `docs/audit/2026-06-05-bot-ux-feature-roadmap.md` (features #1, #3, #8-partial welcome)
**Goal:** Make the Slack + Discord chat bots usable by non-technical first-timers by removing the three biggest onboarding cliffs: the "Ask Lukas" dead-end, the silent approval black hole, and the absence of any welcome/guidance.

---

## Background & constraints

The bot platform ("AIUI") lets non-technical users build and publish small web apps and schedule recurring tasks by clicking buttons and filling short forms in Slack/Discord. A code audit (8-agent, 2026-06-05) found a non-technical user quits within ~2 minutes. The worst onboarding offenders:

1. **"Ask Lukas" dead-end** — the not-linked message hardcodes a person's name across ~12 call sites and never shows the self-service Link button that already exists. On Slack the equivalent is OAuth jargon (`users:read.email scope`).
2. **Approval black hole** — Discord linking waits for a human admin to click Approve; the user is *never told* the outcome.
3. **No welcome** — a brand-new user lands on bare buttons (or, on Slack, a generic AI reply) with no "start here."

**Hard technical constraints (verified in code):**
- The Discord bot uses **HTTP interactions only** (slash commands + buttons + modals). The only Discord gateway connection is `voice_bot.py` (voice-only). **Discord cannot listen to plain typed text messages** without a new gateway connection — explicitly OUT of scope (separate roadmap feature #15).
- **Slack** already has DM + @mention listeners (`webhook-handler/handlers/slack.py`), so plain typing on Slack is a viable welcome trigger.
- Slack identifies users by **auto-reading email** from the profile (`users:read.email`); there is no Slack approval flow and we are NOT adding one this sprint.

**Design principle (from user):** users should not need to know to type `/aiui`. Make **buttons the front door** everywhere; attach an actionable button to every dead-end message so users always *click*, never *type*.

---

## Scope

**In scope (3 pieces):**
1. Unified, friendly, self-service "not linked" card — Discord (with Link button) + Slack (plain-language wording).
2. Approval notification — DM the Discord user when an admin approves/rejects their link request.
3. Welcome / help card — shared component, surfaced button-first (Slack DM/mention + Discord pinned panel & `/aiui help`).

**Out of scope (deferred, with reasons):**
- Discord plain-text message listening (needs gateway — feature #15).
- Auto-approve by email domain (user chose to keep manual approval).
- Slack self-service email-link flow (user chose wording-only; auto-read suffices).
- Persistent first-run tracking (user chose on-demand, no new DB state/migration).

---

## Piece 1 — Unified "not linked" card

### Problem
Two contradictory helpers in `webhook-handler/handlers/commands.py`:
- `_not_linked_text(ctx)` (:1777) → Discord: *"Your Discord account isn't linked. Ask Lukas to add you."*; Slack: the `users:read.email` jargon.
- `_not_linked_msg()` (:1785) → *"…Hit 🔗 Link my account on the Schedules panel…"*

Neither attaches the Link button; advice contradicts depending on which path the user hit.

### Design
Introduce **one** helper that returns a structured result (copy + optional component), replacing both:

```python
# returns {"text": str, "components": list | None}  (Discord)
#      or {"text": str, "blocks": list | None}      (Slack)
def not_linked_card(ctx) -> dict
```

- **Discord:** text = *"👋 You're almost set up — tap **🔗 Link my account** to start building."* + an action row containing the Link button (`LINK_START_ID`, already defined in `app_builder_panel.py:761`). Clicking it opens the existing email modal → existing admin Approve/Reject flow.
- **Slack:** text = *"I can't see your email yet. Ask whoever set up this Slack workspace to turn on email access for the bot (the `users:read.email` permission), then try again."* — plain-language lead, the technical term kept only as a parenthetical the admin can act on. No button (Slack auto-reads; nothing for the end user to click).

### Call sites to migrate (~10)
- `commands.py`: 1366, 1542 (`_not_linked_text`); 1796, 1841 (`_not_linked_msg`)
- `discord_commands.py`: 1024 (`_not_linked_msg`)
- `slack_commands.py`: 81 (`_not_linked_text`)
- `slack_interactions.py`: 365, 464, 636, 716 (`_not_linked_text`)

Each call site currently does `ctx.respond(text)` / `post_message(text=...)`. Update Discord sites to also pass `components`; Slack sites pass the friendlier text (and optionally the welcome buttons as blocks). Keep a thin backward-compatible `_not_linked_text`/`_not_linked_msg` shim returning `.text` so existing mocks/tests don't break, OR update the 6 referencing tests — **decision: update the tests**, since the message shape is changing intentionally (`test_slack_command_build_notify.py`, `test_slack_interactions.py`, `test_slack_schedule_interactions.py`, `test_two_button_entry.py`).

---

## Piece 2 — Approval notification (Discord)

### Problem
`_handle_link_decision` (`discord_commands.py:1153`) updates only the admin's message; the requesting user is never notified. They see *"Request sent — an admin will review it shortly"* (:1141) then silence.

### Design
**a) New Discord client capability** in `webhook-handler/clients/discord.py`:
```python
async def open_dm(self, user_id: str) -> str | None      # POST /users/@me/channels {recipient_id}
async def send_dm(self, user_id: str, content: str = "", components=None) -> bool
```
`send_dm` opens (or reuses) the DM channel then posts via the existing channel-message path. Fail-soft: log and return False on error (a failed DM must never break the admin's Approve action).

**b) Notify on decision** in `_handle_link_decision._do()` (:1166), after the DB update + admin-message edit:
- **Approved:** DM the user — *"🎉 You're in! Tap 🚀 **Build an app** to create your first one."* + an action row with the Build-an-app button (reuse the panel's build entry component from `app_builder_panel.py`).
- **Rejected:** DM — *"Your access request wasn't approved this time. If you think that's a mistake, reach out to your team admin."* (no blame, a path forward). No retry button (avoids approve-spam loops); they can re-submit via the Link button.

The requesting user's `discord_id` is already recovered from the custom_id (:1158). DM delivery is best-effort and logged.

---

## Piece 3 — Welcome / help card (button-first)

### Design
**Shared welcome card** (one builder per platform, same content): *"👋 Hi! I can build you a website or run a task on a schedule — no coding needed."* + buttons **🚀 Build an app** and **⏰ Schedule a task** (reuse existing entry components: `app_builder_panel.py:44` Discord, `slack_app_builder_panel.py` Slack).

**Slack triggers** (`webhook-handler/handlers/slack.py`):
- `SlackWebhookHandler` currently only calls OpenWebUI. Add a lightweight greeting/getting-started heuristic (`_looks_like_getting_started(text)`): matches greetings ("hi", "hello", "hey"), help words ("help", "start", "get started", "how do i", "what can you do"), and very short messages.
- **DM or @mention that looks like getting-started →** post the **full welcome card** (blocks + buttons) instead of the generic AI answer.
- **Otherwise →** answer with the AI as today, but **append a small footer** action row (*Build an app · Schedule a task*) so the buttons are always one tap away. No state, no spam of the full card.
- The handler needs the welcome-card builder injected (import from a shared module) and a `SlackClient.post_message` call that accepts `blocks`.

**Discord triggers:**
- The pinned App Builder panel (`app_builder_panel.py:44`) already needs no typing; reword it to be self-explanatory as the "front door" (clear one-line "what this does" + the two buttons). 
- `/aiui help` (`commands.py` help builder ~:395-420) leads with the welcome card (Build / Schedule / Ask) and moves the 18 developer commands behind `/aiui help advanced` (or admin-only). Bonus path for anyone who does type the slash command.

---

## Data flow (unchanged backends)
- Linking: Discord email modal → `router.request_link` → admin Approve card → `router.approve_link` → **(new)** DM to user. No DB schema change.
- Slack identity: unchanged auto-read; only the failure copy changes.
- Welcome: pure presentation; no persistence.

## Error handling
- DM send is best-effort; failures are logged and never block the admin decision or the user's next action.
- All new detached work (if any) wrapped in try/except (consistent with the existing fail-soft pattern).
- Slack welcome heuristic failure falls through to the normal AI answer.

## Testing
- `not_linked_card`: returns correct copy + component per platform (Discord has Link button; Slack has none, no jargon-only text).
- Discord client `open_dm`/`send_dm`: builds the right API calls (mock httpx); returns False on error without raising.
- `_handle_link_decision`: DMs the user on approve (with Build button) and on reject (polite, no button); admin path still succeeds if DM fails.
- Slack `_looks_like_getting_started`: greetings/help/short → welcome card; real questions → AI answer + buttons footer.
- Update the ~6 existing tests that mock `_not_linked_text`/`_not_linked_msg` to the new shape.

## Success criteria
- No user-facing string contains "Lukas" or a bare "`users:read.email` scope" instruction.
- Every Discord "not linked" response renders a working Link button.
- A Discord user is DM'd within seconds of approval/rejection.
- A Slack user who DMs "hi" / "help" gets the welcome card with buttons; one who asks a real question gets an answer plus an always-present buttons footer.
- No new DB tables/migrations; no Discord gateway connection added.
