# Agent subconscious and free models, design

Date: 2026-09-15. Approved by the owner in conversation the same day.

## What is wrong today, measured

1. An agent carries nothing of its own between conversations. The chat
   panel keeps a per conversation summary (migration 048), the bots send
   the last 20 turns of one chat, a schedule gets 1,200 characters of its
   own previous result. Nothing crosses from one chat to the next or from
   Discord to the panel.
2. The `remember` tool writes to Open WebUI's `public.memory` table. That
   table has 0 rows. Nothing on the agent path reads it back, so the tool
   is write only in practice.
3. The global `knowledge_graph_memory` filter injects about 950 characters
   of graph context per completion (125 injections in the last 24 hours).
   It ranks by similarity to the latest message, so a decision that is not
   mentioned right now is not recalled, and it is per person, not per agent.
4. Eleven agents run on paid models: 2 on gpt-4, 2 on gpt-4o-mini, 7 on
   openai/gpt-5-mini through OpenRouter. The OpenRouter key has 25 credits
   purchased and 24.99 used, so the paid ids on it will start failing.
5. An agent cannot sit on Auto (Free): it is a callback pipe and loops
   (409 since a3dd9e9f3). So a free model has to be a real base model.

## Decisions taken by the owner

1. Memory scope: both. Each agent keeps its own notes; facts about the
   person are shared by all of that person's agents.
2. Capture: automatic after a chat turn, plus the existing remember tool.
3. Free model failure: retry the turn on other free models. Never a paid
   model, never silent.
4. Which agents: all 11 move, and new agents default to the free model.
5. Allowlist: add the two working nex ids and remove the five free ids that
   never answer.

## Approaches rejected

1. Extending the knowledge graph filter: similarity ranking misses settled
   decisions, per person only, runs inside Open WebUI where nothing here
   tests it, and its 6 second timeout fails open silently.
2. Bigger conversation windows: nothing survives a new chat.
3. A new Open WebUI pipe that retries free models: pipes do not forward
   tools (measured by Ralph on 2026-09-10), so agents on it lose theirs.

## Evidence behind the model choice (live, 2026-09-15)

| model | tool call | latency | note |
|---|---|---|---|
| nvidia/nemotron-3-super-120b-a12b:free | yes | 1.3s | in the allowlist already |
| nex-agi/nex-n2.5-pro:free | yes | 3.0s | needs adding to the allowlist |
| nex-agi/nex-n2.5-mini:free | yes | 7.2s | needs adding to the allowlist |
| google/gemma-4-26b-a4b-it:free | no | 429 | rate limited on every call |
| cohere/north-mini-code:free | no | 2.8s | asked a question instead of calling |
| inclusionai/ling-3.0-flash-fin:free | no | 1.9s | spent all tokens reasoning |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | no | 0.6s | 502 worker limit |
| nvidia/nemotron-3.5-lightning:free | yes | 10.8s | too slow to wait on |

Through Open WebUI, `reasoning_effort: none` on nemotron gave a clean
answer with 0 reasoning tokens; without it, a truncated reply leaked the
model's reasoning into the content. A direct base model call with
`tool_ids` still received the tool specs and returned a tool call, which is
what makes a fallback possible at all.

Failure shapes an API caller sees, all measured: HTTP 400 with the body
`{"detail": "Provider returned error"}` for an upstream 429; HTTP 200 whose
body carries an `error` object and no `choices` for an upstream 502; and
a body with no choices at all.

## Design

### 1. Data

Migration `049_agent_memory.sql` creates `tasks.agent_memory`:
id uuid primary key, agent_id text, user_email text, content text,
key text (normalised: lower case, whitespace collapsed, punctuation
stripped, first 120 characters), source text (`reflection` or `tool`),
created_at, last_seen_at. Unique on (agent_id, user_email, key). Index on
(user_email, agent_id, last_seen_at desc). Idempotent like every other
migration; the runner re-runs them all at boot.

Shared facts stay in `public.memory`, inserted the way the remember
endpoint already does it, plus the same key based dedup before insert.

Caps: notes are pruned to 60 per agent, dropping the oldest by
last_seen_at, and a note the person asked for by name (source `tool`)
outlives one a reflection wrote by itself. Facts are never pruned: they
are read newest first, up to 100. `public.memory` is Open WebUI's own
table and holds memories the person typed in Settings as well as ones the
remember tool wrote, with no column that tells those from a reflection's,
so an automatic writer must never delete there. Capping the read is all
the recall budget needs.

### 2. Recall

`agent_memory.recall_block(user_email, agent_id)` returns at most 2,400
characters: the agent's notes newest first (up to 1,400), then the facts
known about the person (up to 1,000). It is appended to the identity line
in `routes_agent_turn._identity_line`, which every chat, panel and bot turn
goes through, and sent as the leading system message from
`agent_runner.run_agent` for schedules. Empty when nothing is stored, so a
turn for an agent with no memory is byte identical to today.

Reading has a 3 second cap and fails open to an empty block.

### 3. Capture, the subconscious part

After `_run_turn` completes with a real answer, when the person's last
message is at least 40 characters and the answer is not PASS or one of the
service's own failure sentences, a detached task runs one completion on
`AGENT_REFLECT_MODEL` (default: the free primary, with the same pool
fallback, `reasoning_effort` off, no tools). The prompt carries the
existing notes and facts, the last user message and the answer, and asks
for JSON `{"notes": [...], "facts": [...]}`: up to 3 of each, 200
characters each, settled things only, written so they still make sense in
a month. The parser is lenient (first `{` to last `}`), drops questions,
PASS, anything shorter than 12 characters and anything whose key already
exists, then stores the rest.

Limits: one reflection per agent per 90 seconds, two in flight per
process. Never on schedules, never on the resume path, never raises, one
log line per outcome.

### 4. Visibility

The Agents page card shows "Memory: N notes" and a Show control that lists
them with a Forget button per note and a Forget all. Endpoints:
GET `/agents/{id}/memory`, DELETE `/agents/{id}/memory/{note_id}`,
DELETE `/agents/{id}/memory`, owner only through `_agents_for`. Shared
facts are already editable in Settings, Personalization, Memories.

### 5. Free model wiring

Environment on the tasks service, set in compose with defaults and nothing
in `.env`:

- `AGENT_DEFAULT_MODEL=nvidia/nemotron-3-super-120b-a12b:free`
- `AGENT_FREE_MODELS=nvidia/nemotron-3-super-120b-a12b:free,nex-agi/nex-n2.5-pro:free,nex-agi/nex-n2.5-mini:free`
- `AGENT_FREE_REASONING=none`
- `AGENT_REFLECT_MODEL` defaults to the first pool entry.

In `agent_runner._chat`: when the agent's base model ends in `:free`, the
payload carries `reasoning_effort`. When a completion fails with one of the
three provider failure shapes, the loop retries the same request on the
next pool id, posting the base model directly with the agent's own
instructions as the first system message and the same `tool_ids`, and
stays on that id for the rest of the turn. Each pool id is tried once per
turn. When the pool is spent the turn answers with the busy sentence that
exists today. Pool ids are checked against OpenRouter's catalogue with a
15 minute cache, the way the Auto (Free) pipe already does, so a withdrawn
id is skipped rather than tried.

Open WebUI's OpenRouter connection allowlist (persisted config key
`openai.api_configs`, connection index 2) gains the two nex ids and loses
`nvidia/nemotron-3-nano-30b-a3b:free`, `nvidia/nemotron-nano-12b-v2-vl:free`,
`nvidia/nemotron-nano-9b-v2:free`, `openai/gpt-oss-20b:free`,
`poolside/laguna-m.1:free` (withdrawn) and `google/gemma-4-26b-a4b-it:free`
(429 on every call). The compose line changes the same way. A backup row is
written first, the way `openai.api_configs.bak_20260805` was.

`scripts/move_agents_to_free_model.py` lists every `agent-*` model through
the admin API, prints a before and after table, and with `--apply` updates
`base_model_id` through `/api/v1/models/id/{id}/update` (admins may update
any user's model in Open WebUI 0.11) and then calls `/api/models` so the
cache is rebuilt. `--only <id>` limits it to one agent.

### 6. Error handling

Every memory operation fails open around the turn. A reflection that fails
loses one reflection. A recall that fails sends the turn without memory. A
fallback never reaches a paid model. The busy sentence is the only thing
the person sees when every free model is down.

### 7. Testing

1. Unit, written first: key normalisation, recall block budget and order,
   reflection prompt and parser, skip rules, the loop's fallback with fake
   completions (model switch, system injection, reasoning flag, one try per
   id, busy sentence at the end), identity line unchanged when memory is
   empty, schedule messages carry the block, owner only endpoints, the
   migration is picked up by the runner.
2. Container DB tier against `aiui_test`: migration applies, insert,
   dedup, prune, list and delete against real Postgres.
3. Live on production with Ada (the owner's agent): move her, one tool
   turn, one turn stating a decision, one fresh chat asking for it back,
   one forced fallback with a dead primary through a container harness,
   the served page bytes. Then the other 10 agents, one plain turn each.

## Risks accepted

1. OpenRouter free quota: 1,000 requests per day platform wide on this key
   (25 credits purchased), 20 per minute. Reflection adds at most one
   request per qualifying turn. On a bad hour agents say they are busy.
2. Free ids rotate. The catalogue check skips withdrawn ids; the pool env
   var is the place to add a new one.
3. A wrong memory is visible and deletable on the card; a reflection that
   misreads a turn is corrected there, not by code.
