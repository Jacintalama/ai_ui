# Just-Chat Intent Router — design

**Date:** 2026-06-30
**Sub-project 1 of 3** (router → reliability basics → proactive daily assistant)
**Status:** design, pending implementation plan

## Problem

AIUI is pitched as "just chat, no coding," but plain English does nothing useful.
The 2026-06-05 UX audit named this blocker #1 ("Build doesn't build"), and it is
still live in code:

- `webhook-handler/handlers/commands.py:163-194` (`parse_command`) matches only the
  first word against a fixed `known_commands` set. "build me a feedback form" →
  first word `build` is not a command (the real one is `aiuibuilder`) → the whole
  sentence falls through to generic Q&A, which lectures instead of building.
- `webhook-handler/handlers/slack.py:90-121` (`_handle_mention`) and `:123-169`
  (`_handle_direct_message`): a freshly typed Slack message, after the greeting
  check, is sent straight to `openwebui.chat_completion` — a generic answer. There
  is no understanding of "what does this person want me to do."

The onboarding wording was already fixed (welcome card, "Link my account" button,
approval DM in `handlers/onboarding.py`), but the core promise is unmet.

## Goal

When a user types a normal sentence, understand the intent and either do the thing
(after one tap to confirm) or just answer. No commands to memorize.

In scope for v1 (decided with the user):
- **Slack:** full plain-typing support (mentions + DMs).
- **Discord:** plain English via the existing slash command, i.e. `/aiui build me a
  form` routes correctly. No new always-on Discord message listener in v1.

Out of scope for v1 (named follow-ups):
- Discord no-slash typing (needs the privileged Message Content gateway connection;
  deferred for cost/privacy on the 4GB box).
- Multi-turn "needs more detail" clarify-and-resume (audit #16).
- Moving the pending-intent store into the DB (audit #18); in-memory is fine for v1.

## Approach

One shared brain, two wiring points, per-platform rendering — mirroring how
`onboarding.py` already shares logic and renders Discord vs Slack cards separately.

### Shared core — `webhook-handler/handlers/intent_router.py`

Two functions, kept small and testable:

```
INTENTS = build_app | schedule_task | make_video | find_jobs | find_engineers
        | summarize_email | web_research | question   # question = safe default

@dataclass
class IntentResult: intent: str; confidence: float; detail: str
                    # detail = the cleaned request to prefill (e.g. the app description)

async def classify(text, llm) -> IntentResult
    # one cheap LLM call, strict JSON out, safe-parse.
    # the prompt instructs the model to return intent="question" when it is not
    # reasonably sure, so "unsure" is expressed two ways: as the question intent
    # AND as a low confidence. ANY error or unparseable output ->
    # IntentResult("question", 0.0, text).

def decide(result, threshold=0.6) -> Action   # PURE, no I/O
    # Action(kind, intent, detail), kind in {"confirm", "answer"}
    # intent == "question"  -> answer
    # confidence < threshold -> answer
    # otherwise              -> confirm
```

`classify` is the only part that does I/O (the model call) and is injected, so tests
pass a fake. `decide` is pure and gets the bulk of the unit tests.

### Wiring point A — Slack messages (`handlers/slack.py`)

In both `_handle_mention` and `_handle_direct_message`, right **after** the existing
`onboarding.looks_like_getting_started(...)` greeting check and **before** the
generic `openwebui.chat_completion` call:

1. `result = await classify(text, llm)`
2. `action = decide(result)`
3. `action.kind == "confirm"` → post a confirm card (new `confirm_blocks_slack`)
   and return. `action.kind == "answer"` → fall through to today's generic answer
   (unchanged), which already carries the buttons footer.

### Wiring point B — Discord `/aiui <free text>` (`handlers/commands.py`)

The natural-language case is exactly the `("ask", text)` fallthrough where the first
token was not a known command and not the literal word `ask`. At that seam:

1. classify + decide (same core).
2. `confirm` → respond with Discord confirm components (new `confirm_components_discord`).
   `answer` → existing `_handle_ask` (unchanged).

Explicit `/aiui ask <q>`, every known subcommand, and all buttons keep their current
path. No regression to anything that already works.

### Confirm card → run

The confirm card shows one line ("Sounds like you want to build a website. Start
now?") and two buttons: **[Do it]** and **[Just answer]**.

- The user's sentence (`detail`) is stored server-side under a short token, mirroring
  the existing pending-schedule pattern; the **Do it** button carries only the token
  (Discord custom_id is length-limited).
- **Do it** routes into the capability's existing, tested entry point, prefilled with
  `detail` where that entry takes free text:
  - `build_app` → start a build with `detail` as the description (reuses the
    `aiuibuilder build` path).
  - `schedule_task` → open the schedule flow with `detail` fed to the plain-English
    parser.
  - `make_video` / `find_jobs` / `find_engineers` / `summarize_email` / `web_research`
    → open that capability's existing panel/flow (prefill where the entry accepts it).
- **Just answer** → the generic answer path (today's behavior).

### Rollout safety

- Feature flag `INTENT_ROUTER` (compose env on webhook-handler, not `.env`), default
  off until tested, mirroring the `AI_VIDEO_CODEGEN` pattern. Off → today's behavior
  exactly.
- Confirm-first means no expensive/irreversible action (build, video) ever fires on a
  guess; it only fires on an explicit tap.
- `classify` is read-only and always degrades to "answer" on any failure, so the bot
  can never feel more broken than it is today.
- Cost: one small model call per natural message, reusing the configured `ai_model`.

## Components

| Unit | Responsibility | Depends on |
|------|----------------|-----------|
| `intent_router.py` | `classify` (LLM) + `decide` (pure) | the model client only |
| `onboarding.py` (extend) | `confirm_blocks_slack`, `confirm_components_discord` | existing button helpers |
| `slack.py` (edit) | call router in mention + DM handlers | intent_router, onboarding |
| `commands.py` (edit) | call router at the ask fallthrough | intent_router, onboarding |
| pending-intent store | token → detail, short-lived (in-memory v1) | mirrors pending schedules |
| confirm-button handlers | `discord_commands.py` + `slack_interactions.py` | existing entry flows |

## Testing (TDD, run later per user)

- `decide()` table tests: question→answer; each actionable intent high-conf→confirm;
  low-conf→answer; threshold boundary.
- `classify()` with a fake LLM: clean JSON→correct IntentResult; malformed/empty/raised
  → fallback `question`.
- Slack wiring: a natural "build me X" DM with a mocked LLM produces a confirm card,
  not a generic answer; a greeting still shows the welcome card (regression).
- Discord wiring: `/aiui build me X` produces a confirm card; `/aiui ask X` and known
  subcommands dispatch unchanged (regression).
- Confirm action: tapping **Do it** for a stored token starts the right entry flow
  with the prefilled detail; an expired/unknown token degrades gracefully.

## Done when

- A plain sentence in Slack (mention or DM) and a `/aiui <plain sentence>` in Discord
  both produce a correct one-tap confirm for actionable intents and a normal answer
  otherwise.
- All existing commands, buttons, greetings, and the generic-answer path are unchanged
  when the flag is off, and unchanged for non-actionable text when on.
- Unit tests above are green. (Full live e2e is deferred to the end, per the user.)
