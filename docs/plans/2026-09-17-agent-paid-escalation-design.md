# Agents move to the paid model on their own, design

Date: 2026-09-17. Approved by the owner in conversation the same day.

## What the owner asked for

A programmer agent on a free model answers ordinary questions fine. On a
long conversation or real work (building an app, a larger code change,
debugging) it stops answering properly. Today the only fix is to open the
agent's card, press Edit and change its model, then change it back. The ask:

1. Simple questions and requests stay on the free model.
2. Complex work moves to a stronger paid model (GPT-5.5) automatically.
3. The agent notices when the free model is not enough.
4. Seamless: nobody has to know which model answered.
5. Back to the free model once the work is simple again.

## What the investigation found first, measured

1. The one real stuck session (Ralph's room, 2026-09-16 13:39 UTC) was a
   server bug, not the model: opening App Builder closed the chat stream,
   the stream's cleanup was cancelled, and the room stayed marked busy, so
   every later message was queued and never answered. It stayed stuck after
   Ralph moved Rex to gpt-5.5 by hand. Fixed separately on branch
   `fix/logout-and-stuck-agent-room` (commit cd561e2c0), together with the
   dropped approval in the everybody-passed fallback (410cc0d00) and the
   PASS bubble with a routing footer (48ec5dfd9).
2. The free models behaved as designed on 2026-09-16: nemotron failed 3
   times, each in about 1 second, and nex-n2.5-pro answered every time. A
   repro with a 38.6k and a 50.9k character history plus tools and a build
   request answered twice (1.9 s and 5.7 s, one tool call each, 0 reasoning
   tokens) and was overloaded once (HTTP 200 with a 503 body and no choices).
3. Ralph's Auto (Smart) pipe cannot do this job as an agent's base model. It
   drops the tool specs Open WebUI hands it, so the agent has no tools, and
   it routes on the last user message only. In the room that message is
   PASS_INSTRUCTION (668 characters), over its 400 character threshold, so
   every unnamed agent went to gpt-5.5 whatever the person asked. That is
   the PASS plus footer in the owner's 2026-09-17 screenshot (stored rows
   from 2026-09-14).
4. Nothing records which model answered an agent turn or what it cost:
   `tasks.agent_run` has no model or cost column, API completions write no
   chat rows, Langfuse holds 0 traces, and the OpenAI key lacks the
   `api.usage.read` scope.
5. gpt-5.5 is reachable: it has an active `public.model` row and a
   `user:*:read` grant, and the OpenAI key answers GET /v1/models/gpt-5.5.
   No completion was sent during the investigation.
6. Prices, read 2026-09-17 from developers.openai.com/api/docs/pricing:
   gpt-5.5 $5.00 input, $0.50 cached input, $30.00 output per million
   tokens ($10 / $45 above 272K context). About $0.05 for one completion at
   7,000 input and 500 output tokens; a turn can make several.
7. Rex (agent-rex-a101) was moved to gpt-5.5 by hand on 2026-09-16 13:41 UTC.
   The other 10 agents are on nemotron-3-super free.

## Decisions taken by the owner

1. Trigger: rules on the person's own words, plus a move when the free model
   fails. No extra classifier call, no self-assessment by the free model.
2. Paid model: GPT-5.5.
3. Spend guard: record the model, tokens and cost of every run, and cap paid
   turns per person per day (40).
4. Stickiness: until the task is done. Follow-ups within 15 minutes stay
   paid; a plain question about something else goes back to free.

## The design

### When a turn moves

1. Up front, from what the person typed (never from an instruction this
   service added, such as PASS_INSTRUCTION, the identity line or the recall
   block):
   1. asks to build or create an app, site, dashboard, bot, extension or
      game, or a web page: a kind only a site has (landing, signup, contact,
      pricing) or a page in an app or site. A page in a notebook or a doc is
      not one, and neither is an application that does not say web or
      mobile (`build`)
   2. asks to write, change, refactor, implement or debug code, or mentions
      App Builder, or pastes a code block (`code`)
   3. pastes an error, exception or stack trace (`error`)
   4. a single message over 2,000 characters (`long_message`)
2. Partway through a turn:
   1. the free model asks for `propose_app_change` or `apply_app_change`
      (`heavy_tool`); the batch is discarded unrun and asked again on paid
   2. the free model answers with nothing, or with reasoning and no text
      (`empty_answer`)
   3. the carried conversation passes 60,000 characters
      (`long_conversation`). Grounded in the repro: 38.6k and 50.9k character
      histories answered. The room's own budget keeps its history under
      about 35k, so in practice this fires when tool results pile up.
3. On failure, in the same turn, with the carried conversation so no tool
   runs twice:
   1. every id in the free pool failed (`pool_spent`)
   2. the free rounds ran out (`rounds_cap`); the paid model gets 3 more
      rounds, then the write-up
4. At most once a turn. If the paid call fails (any HTTP failure except 401
   or 403, or a timeout), the turn goes back to the free model it left and
   does not try paid again. A 401 or 403 is still raised.
5. Never paid: the room summariser (no intent is passed) and the memory
   reflection (it never calls the tool loop).
6. Only agents whose base model is a `:free` id move. An agent somebody put
   on a paid model (Rex) is untouched. Auto (Smart) is untouched.

### The room: decide on free first

An agent in the room that was not named may answer PASS. Moving every agent
to paid up front on "build me an app" would pay seven times to hear six
PASSes. So an unnamed agent gets one free completion first: PASS ends its
turn on free; anything else (an answer or a tool call, which has not run
yet) is discarded and asked again on paid. A named agent moves at once.

### Staying on paid

1. A paid completion opens or refreshes a 15 minute window for that person
   and that agent (in memory in the tasks process; the service runs one
   worker).
2. Inside the window: approvals, "yes, go ahead", short instructions like
   "make it blue", and anything that matches a rule stay paid (`sticky`).
3. A plain question with no build or code words ("what is on my calendar
   tomorrow?") goes back to free even inside the window. Modal requests
   ("can you make it blue?") are requests, not questions, and questions
   about the work ("why did the build fail?") stay paid.

### Spend guard and records

1. Migration 050 adds `model`, `escalation`, `prompt_tokens`,
   `completion_tokens` and `cost_usd` to `tasks.agent_run`, with a rollback
   in `migrations/rollbacks/`.
2. `escalation` is written the moment a run moves, so the cap sees moves
   still in flight; the rest is written with the finish.
3. Tokens are summed from the `usage` field of every completion that
   answered. Cost uses `AGENT_PAID_PRICES` (default `gpt-5.5=5:30`, dollars
   per million tokens). Free ids cost 0. A model with no price, or a paid
   reply without usage, records NULL cost, never 0. Cached input is charged
   at the full input price (conservative; whether Open WebUI passes the
   cached count through is not verified).
4. Cap: `AGENT_PAID_DAILY_CAP=40` runs that moved, per person, per UTC day
   (resets 08:00 in the owner's UTC+8). If the count cannot be read the turn
   stays free. Past the cap the agent stays free and, once that day, adds a
   plain sentence to its answer saying the daily limit for the stronger
   model is used up. In the answer, not in notes, because the room draws
   answers and drops notes. Never added to a PASS.
5. Two ways to turn the feature off without a code change:
   `AGENT_PAID_DAILY_CAP=0`, or `AGENT_PAID_MODEL=` set blank in `.env`.
   Blank works only because compose declares that one as
   `${AGENT_PAID_MODEL-gpt-5.5}`, with no colon: `${VAR:-default}` replaces
   a blank value with the default, so a blank line in `.env` would still
   run gpt-5.5. Deleting the line from `.env` gives the default, gpt-5.5.
6. No footer or label in replies.

### Timing

A paid completion gets at least `AGENT_PAID_TIMEOUT_SECONDS` (90). The worst
turn grows, so the windows that call a run dead and the token lifetime grow
with it. `agent_runner.worst_turn_seconds` counts the worst turn. The token
lifetime is computed from it when the service starts, so it follows
`AGENT_FREE_MODELS`, `AGENT_PAID_TIMEOUT_SECONDS` and
`AGENT_PAID_EXTRA_ROUNDS`. The two windows are fixed numbers in
`agent_activity`, checked against it by a test (the cut-off test in
`test_agent_activity.py`) with the settings of wherever the test runs. A
longer free pool or a larger paid timeout or extra round count set by env
raises the token but not the windows; the windows then have to be raised in
code, and that test says by how much. The numbers with the default settings:

1. Chat: 1,170 seconds. Moving at the start is one free answer at 60 and
   seven paid rounds at 90; moving at the round cap is seven free rounds at
   60 and three paid rounds at 90. Either can end with a paid write-up that
   times out at 120 and a free write-up that spends all three free ids at
   120 each. `STALE_AFTER_CHANNEL` 12 to 21 minutes.
2. Schedule: 3,600 seconds (eight free rounds, three paid rounds, the
   failed paid write-up and three free write-ups, all at 240).
   `STALE_AFTER_SCHEDULE` 50 to 65 minutes. `CHAT_TOKEN_TTL_SECONDS` 2,700
   to 3,660.
3. Corrected after review on 2026-09-17, and not yet confirmed by the
   owner. The approved figures were 930 seconds, 17 minutes and a 3,420
   second token. They left out a paid write-up that fails, and priced the
   fallback ids spent in the write-up at the round timeout. The new figures
   were checked on a scratch copy with the plan's Task 7 loop, by searching
   its paths with every post at its full timeout. The free loop before this change was already 780
   seconds for a chat turn, not the 660 its comments said.

### Settings (compose, tasks service)

`AGENT_PAID_MODEL=gpt-5.5`, `AGENT_PAID_REASONING=none` (was `low`; see
Not verified item 1 for the measured 400),
`AGENT_PAID_TIMEOUT_SECONDS=90`, `AGENT_PAID_DAILY_CAP=40`,
`AGENT_PAID_PRICES=gpt-5.5=5:30`. `AGENT_PAID_MODEL` and
`AGENT_PAID_REASONING` are declared `${VAR-default}` (no colon), so a value
set blank in `.env` reaches the container blank; the other three are
`${VAR:-default}`, so blank gives the default (`AGENT_PAID_DAILY_CAP=0`,
not blank, is the off switch). Code defaults only, overridable by env:
`AGENT_PAID_STICKY_SECONDS=900`, `AGENT_PAID_EXTRA_ROUNDS=3`,
`AGENT_PAID_CONVERSATION_CHARS=60000`, `AGENT_PAID_MESSAGE_CHARS=2000`.

## Changes the code forced on the approved design

1. Unnamed agents in the room decide on free first (above). Without it one
   message costs up to one paid call per agent in the room.
2. The move is opt in per caller. A caller that passes no intent never
   moves, so the summariser and any future caller stay free unless someone
   decides otherwise. The reflection needed no change: it never calls the
   tool loop.
3. The heavy tools are only `propose_app_change` and `apply_app_change`. No
   agent tool builds a new app today (open-webui-functions/*_tool.py).
4. The room passes the person's words through a context variable
   (`agent_escalation.asking`), not a new argument, because about fifteen
   test doubles of `_turn_for` have fixed positional signatures.
5. The at-cap move gives the paid model 3 extra rounds rather than only the
   write-up, so it can finish work the free model started.
6. The stale windows and the token lifetime grow (above).

## Not verified before building, checked in the live task

1. That gpt-5.5 through Open WebUI accepts `reasoning_effort: low`.
   **Measured 2026-09-17 17:13 UTC: it does not.** The first live paid turn
   got HTTP 400 from api.openai.com: "Function tools with reasoning_effort
   are not supported for gpt-5.5 in /v1/chat/completions. To use function
   tools, use /v1/responses or set reasoning_effort to 'none'." The turn
   went back to free as designed and cost nothing. The default is now
   `none`, the value the error names.
2. That Open WebUI passes `usage` through for a gpt-5.5 non-stream reply.
3. That gpt-5.5 answers an agent turn with tool specs inside 90 seconds.
4. That tool calling works when the base id gpt-5.5 is posted with
   `tool_ids`. Inferred from production: the free fallback posts base ids
   with `tool_ids` and Rex ran 6 tools that way on nex-n2.5-pro on
   2026-09-16. Before 2026-09-15 agents on OpenAI models ran tools, but
   through their derived agent ids, not a posted base id.

## Non-goals

1. No change to agents on a paid base model.
2. No footer, label or UI change.
3. The summariser and the reflection stay free only.
4. No change to Auto (Smart) or Auto (Free).
5. No allowlist on the OpenAI direct connection, although every plain user
   can pick gpt-5.5-pro ($30 / $180) there today. Worth a separate decision.
6. No fix here for the reflection reading PASS_INSTRUCTION as the person's
   words in room rounds (pre-existing, seen while tracing this).

## Known risks

1. The Discord, Slack and Telegram gateway waits 420 seconds for
   `/agents/turn` (webhook-handler `AGENT_TURN_TIMEOUT_SECONDS`). A worst
   case paid turn is 1,170 seconds. The free worst case was already 780.
   Three other callers give up sooner, and all three reach a turn that can
   move (added after review, 2026-09-18):
   1. `open-webui-functions/auto_router_pipe.py` posts `/agents/chat` with
      `TIMEOUT_SECONDS` 120 (its valve default).
   2. `open-webui-functions/agents_tool.py` posts `/agents/chat` with
      `timeout_seconds` 60, less than one paid completion's own 90.
   3. The browser's `aiuiSpeak` in `mcp-servers/gdrive/integrations-ui.js`
      posts `/api/tasks/agents/speak` with no timeout of its own, so the
      limit is probably Cloudflare's 100 seconds on a proxied request
      (inferred, not measured). One paid completion alone may take its
      full 90 seconds, and every free round before a move adds up to 60.
   What the tasks service does with a turn whose caller has gone is not
   checked here. Task 11 records the measured gpt-5.5 latency of its paid
   turns next to these four numbers (60, 100, 120, 420), which says whether
   any of them is hit in practice.
2. The window and the once a day note live in process memory, so a restart
   forgets them. The cap does not: it is counted from the table.
3. The rules are keyword rules. They will miss some real work and catch
   some chat; the move on failure is the backstop, and the cap bounds cost.
