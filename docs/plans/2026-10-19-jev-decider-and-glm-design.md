# Jev for triage, GLM for every agent, a plain debug view (design)

Date: 2026-10-19. Status: approved the same day (sections 1 and 2 explicitly;
3 and 4 as part of "proceed").

Source: the owner's call on 2026-10-16 (transcript in the session): use Jev,
a fast decision model, for the triage agent; it is "ultra cheap"; the agents'
UI is a troubleshooting view and may be plainer. The same day: run the agents
on the cheapest GLM.

## Facts (checked 2026-10-19)

1. Jev (TypeSafe AI, released 2026-09-15) returns a choice from fixed options
   with probabilities; it writes no text. $0.042 per million input tokens,
   output free. Vendor latency 70 to 500 ms. Independent tests: 78.8% on a
   77-way routing set (GPT-5.6 Terra 84.0%); the advised pattern is Jev first
   and escalate below 0.8 confidence. Access: console.typesafe.ai (early
   access), Vercel AI Gateway, Cloudflare. OpenRouter lists only
   `typesafe/jev-router`, unpriced.
2. Cheapest GLM with tools on OpenRouter: `z-ai/glm-5.3-flash`, $0.035 / M
   in, $0.20 / M out, 1M context. Backup: `z-ai/glm-4.7-flash`, $0.06 / $0.40.
3. Today: 12 agents (11 on nemotron free, 1 on gpt-5.5), free pool of four
   free models, paid escalation to gpt-5.5 capped at 40/day, 62 runs in the
   last 7 days. OpenRouter balance $22.42 of $55.00. The server has
   OPENAI_API_KEY and OPENROUTER_API_KEY; no TypeSafe key.

## Decisions

1. GLM 5.3 Flash replaces everything, including gpt-5.5.
2. The decider is Jev itself (TypeSafe), not OpenAI's Decisions API.
3. Jev decides: a normal answer or a team job, and which agent takes it.
4. A plain debug view comes after Jev and GLM; Ralph's robots stay.
5. Approach: Jev first, the current GLM triage as the fallback below 0.8,
   every decision recorded, any Jev failure is today's path.

## 1. Everything on GLM 5.3 Flash

1. All 12 agent rows (`public.model`, `agent-*`) move their base model to
   `z-ai/glm-5.3-flash`, after a backup of those rows.
2. New agents default to it (`AGENT_DEFAULT_MODEL`); the fallback pool
   (`AGENT_FREE_MODELS`) becomes GLM 5.3 Flash then GLM 4.7 Flash.
3. Paid escalation off with the existing switch (`AGENT_PAID_DAILY_CAP=0`).
4. Triage, the summariser and reflection follow the agent's model.
5. Each run records its cost from GLM's list price in `tasks.agent_run`.
6. Proof first: Open WebUI gets the base model rows and read grants for both
   GLM ids (a missing row makes every turn say Model not found); one test
   agent switches and runs one real tool-using turn live; then all move.

## 2. The Jev decider

1. Runs for messages to the whole team only; named, meeting and approval
   messages keep today's rules.
2. One call, two questions: answer or job; which agent (names and roles).
   Input is the message, the last few lines and the roster, kept short.
3. Answer with confidence >= 0.8: only that agent answers. Job >= 0.8: GLM
   writes the plan and the plan card appears as today. Below 0.8: today's
   triage, on GLM.
4. 2 second limit; any error, timeout or missing key is today's path.
5. Each decision is stored in a new table: choice, confidence, who, time in
   ms, provider, used or fell back and why. No message text.
6. Cost about $0.00001 per message. Off until `TYPESAFE_API_KEY` exists.

## 3. Plain debug view

1. A plain page, no animation: a timeline per conversation of decisions
   (with confidence and the path taken), agent-to-agent asks, job steps, and
   each run's model, time and cost.
2. Reads existing tables (`agent_run`, `agent_step`, `agent_job*`) plus the
   decisions table. Linked from the agents page.

## 4. Testing and rollout

1. Test first for the decider (choices, threshold, timeout, fallback, no
   key), the round wiring, and the view.
2. Live order: GLM rows and one real turn; then all agents; then the decider
   and view deployed (off without a key); Jev switched on when the key is in.
3. Deploy hash-checked; verify the served bytes and one real decision when
   the key exists.
