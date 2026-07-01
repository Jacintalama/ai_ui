# Intelligent clarify-then-confirm ("high-IQ assistant") — design

Date: 2026-07-01
Branch: `feat/just-chat-intent-router`
Status: approved (design), pending implementation

## Problem

The just-chat intent router already understands plain English and can build apps,
schedule tasks, and set up a daily briefing from a sentence. But it acts too
eagerly and too bluntly:

- On a build it either fires a yes/no confirm card immediately or, only for a
  *vague build on Discord*, asks a single canned "what kind of site?" question.
- Slack has no clarify step at all.
- It never restates what it understood before running, so a misread runs anyway.

Lukas's ask: make the bot read as a *high-IQ assistant that knows what the user
wants* — it should **ask before it proceeds**, on **both Discord and Slack**, and
in general channels it should feel present and intelligent.

## Decision (from brainstorming)

- **Always ask one clarifying question first** for an executable request, even if
  the request already looks complete. The question is written by the model from
  the user's own words each time (not a fixed template).
- **After the user answers, recap what will happen and confirm with a button**
  ("Here's what I've got: … Want me to go ahead?"). One extra tap, but it catches
  a misread before anything runs.

## Scope

Applies to the two intents the bot actually executes end-to-end from chat:

- `build_app` — always clarify, then recap+confirm, then build.
- `schedule_task` — always clarify, then recap+confirm (recap shows the parsed
  time/recurrence), then create the schedule.

Unchanged:

- `daily_briefing` — one-tap confirm (fixed content, nothing to clarify).
- `make_video`, `find_jobs`, `find_engineers`, `summarize_email`, `web_research`
  — the existing "suggest, tap the tool" message (not run end-to-end from chat).
- `question` / small talk / low confidence — a smart answer via the existing
  gpt-5 ask path. No interrogation.

Surfaces (all get the same loop):

- Discord gateway plain text in any channel (`handle_chat_message`).
- Discord `/aiui <free text>` slash (`_handle_natural`).
- Discord private app thread (`handle_builder_thread_message`, shares state).
- Slack DM and channel/mention free text (`slack.py::_try_intent`).
- Confirm buttons already route to `run_confirmed_intent` on both platforms.

## Behavior (the loop)

1. User types plain English.
2. Bot classifies.
3. `question` / chatter -> smart answer, no clarify.
4. `build_app` / `schedule_task` -> ONE clarifying question, written from the
   user's words (e.g. "A portfolio for a photographer, nice. Roughly how many
   projects, and any color or vibe you want?"). The pending request is remembered
   for that user.
5. User replies.
   - If the reply is itself a question (they asked instead of answering) -> answer
     it and **keep** the pending request (do not force a confirm).
   - Otherwise -> merge original + reply, re-read it, and post a **recap + confirm
     card** ("Yes, do it" / "No, just answer"). Clear the pending request.
6. `daily_briefing` -> straight to a one-tap confirm (no clarify).
7. Yes -> run it for real and deliver the result (private thread on Discord, DM or
   channel on Slack). No -> drop it and answer normally.

The clarify prompt tells the model: ask for the single most important missing
detail; if nothing important is missing, ask a brief "anything you'd like to add
before I start?" So a fully specified request still gets one light touch, then the
recap, honoring "always ask first" without a real interrogation.

## Architecture

Small additions; reuses the existing card + confirm-token machinery.

### `handlers/intent_router.py` (pure + one thin async wrapper)

- `EXECUTABLE = ("build_app", "schedule_task")` — the intents that clarify.
- `build_clarify_messages(intent, text) -> list[dict]` — the clarify prompt
  (pure). One short, friendly, specific question; output the question only.
- `parse_clarify(raw, intent) -> str` — strip the model reply to a single
  question line; empty/garbled -> the fallback for that intent.
- `_CLARIFY_FALLBACK: dict[str, str]` — deterministic per-intent question used
  when the model call fails (network/empty), e.g. build_app -> "What kind of site
  is it, and who's it for?", schedule_task -> "What should I do, and how often or
  when?".
- `async def clarify_question(intent, text, openwebui, model) -> str` — thin
  wrapper (build -> model -> parse), never raises, falls back on failure.

### `handlers/intent_cards.py` (pure)

- `recap_line(intent, detail, when="", task="") -> str` — "Here's what I've got:
  <detail>. Want me to go ahead?"; for `schedule_task` include the time phrase
  ("… every weekday at 8am"). Reuses the existing confirm buttons/blocks.

### `handlers/commands.py` (CommandRouter)

- Rename `self._pending_build_clarify` -> `self._pending_clarify` and store
  `{intent, text}` (covers build_app + schedule_task). The private-thread handler
  keeps working on the shared store.
- New small result type `ChatStep(kind, text, token="")` where kind is one of
  `"clarify" | "confirm" | "answer" | "suggest"`.
- New `async def plan_chat_step(ctx, text, *, threshold) -> ChatStep` — the
  platform-agnostic state machine:
  - Pending clarify for this user?
    - reply classifies as `question` -> `ChatStep("answer", "")`, keep pending.
    - else -> merge original + reply, re-classify only to extract
      detail/when/task, but **park the pending intent** (not the reply's
      classification), clear pending, `ChatStep("confirm", recap_line(...),
      token)`.
  - Fresh message -> `classify` + `decide(threshold)`:
    - `answer` -> `ChatStep("answer", "")`.
    - executable intent -> `clarify_question(...)`, store pending,
      `ChatStep("clarify", question)`.
    - `daily_briefing` -> `park_intent`, `ChatStep("confirm", confirm_line, token)`.
    - suggest -> `ChatStep("suggest", suggest_line(intent))`.
- `handle_chat_message` (Discord gateway, threshold 0.75), `_handle_natural`
  (Discord slash, threshold 0.6) call `plan_chat_step` and render:
  - clarify -> `ctx.respond(text)`.
  - confirm -> `ctx.respond_components(text, confirm_components_discord(token))`
    (fallback to `ctx.respond(text)` if no components).
  - answer -> `_handle_ask(ctx)`.
  - suggest -> `ctx.respond(text)`.
- `run_confirmed_intent` unchanged for execution; its old vague re-ask stays as a
  rarely-hit safety net (detail is already rich after clarify).
- `handle_builder_thread_message` keeps its richer thread behavior (complete a
  pending clarify -> build; refine the current app via `run_panel_enhance`;
  otherwise answer), now on the shared `_pending_clarify`.
- Minor: enrich `_build_ask_system_prompt` so plain answers know the bot can
  build sites, schedule tasks, and send a briefing, and offer it when the user
  clearly wants one. Keeps general-channel chat feeling like it "knows what the
  user wants."

### `handlers/slack.py` (parity)

- `_try_intent(text, channel, thread_ts)` calls `plan_chat_step` (via a light
  Slack `CommandContext` carrying `user_id` so pending state keys correctly) and
  renders:
  - clarify -> post the question; return True.
  - confirm -> post `confirm_blocks_slack(token, recap_line)`; return True.
  - answer -> return False (the caller's existing generic answer replies).
  - suggest -> post the suggest line; return True.
- The clarify *continuation* arrives as the user's next Slack message, so
  `_try_intent` naturally re-enters and produces the recap+confirm.
- Slack buttons already run `run_confirmed_intent` via
  `slack_interactions.py::_spawn_intent_action`.

## State

`_pending_clarify` and `_pending_intents` are in-memory, lost on a container
restart. Acceptable for v1; persistence is a noted follow-up (same as today's
`_user_app_slug`).

## Testing

Unit (pure-first, matches the repo's style):

- `intent_router`: `build_clarify_messages` shape; `parse_clarify` strips fences /
  picks the question / falls back; `clarify_question` returns the fallback on a
  model failure.
- `intent_cards`: `recap_line` for build (detail) and schedule (detail + when).
- `commands.plan_chat_step` across every state: fresh executable -> clarify +
  pending stored; pending reply (statement) -> confirm + token + recap; pending
  reply (question) -> answer + pending kept; fresh question -> answer; fresh
  suggest -> suggest; daily_briefing -> confirm (no clarify).
- Discord `handle_chat_message`: clarify then continue -> confirm card.
- Slack `_try_intent`: clarify then continue -> recap+confirm blocks; question ->
  returns False.
- Keep the existing router / cards / gateway / presence tests green.

End-to-end (live, in the running webhook-handler container, against real gpt-5 and
the real tasks scheduler), for both a Discord context and a Slack context:

- "build me a website" -> a clarify question; a reply -> a recap+confirm; Yes ->
  a real build that delivers.
- "summarize my emails every weekday at 8am" -> clarify -> recap (with cron 0 8 *
  * 1-5) -> Yes -> a real schedule created, then deleted.
- A plain question -> a smart answer (no clarify).

The final tap inside the actual Discord/Slack apps stays a human step (the bot
cannot post as the user; forged webhooks are signature-blocked). Every behavior
behind that tap is verified in-container.

## Deploy

- Commit on `feat/just-chat-intent-router`; push to `fork` (after
  `gh auth switch -u Jacintalama`, `git fetch fork` + rebase, never force-push).
- Deploy webhook-handler to Hetzner per-file (never `scp -r`); drift-check
  CRLF-normalized hashes server-vs-repo for each changed file before overwriting,
  merge onto the server copy if it is ahead. Never touch `.env`.
- Verify: `docker compose ... ps webhook-handler` Up (healthy), gateway
  reconnects, and the in-container e2e above passes.
