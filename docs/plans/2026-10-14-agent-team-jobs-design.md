# Agent team jobs: triage, plan, assign, run in the background (design)

Date: 2026-10-14. Status: approved the same day.

Covers the requested items: decision engine / triage (3), agent task planning
and assignment (4), status and movement in the UI (5, with the Office timing
work already under way), main context for sub-agents (6), background execution
and progress (7).

## What exists today (measured 2026-10-14)

1. **Triage:** three unrelated deciders, none of which turns a request into
   work for the team:
   - the meeting decision engine (`mcp-servers/meetings/decision_engine.py`)
     sorts meeting action items for people;
   - `agent_routing.choose_speakers` picks who answers a chat message;
   - `agent_escalation.decide` picks free or paid model.
2. **Planning and assignment:** none for agents. `tasks.items` assigns to
   people only; `ask_colleague` (`agent_tools.py`) is a one-shot question.
3. **Sub-agent context:** `run_handoff` passes only the question text plus the
   colleague's own brief (`agent_tools.py:325-328`); not even who is asking,
   although the handoff spec said it should.
4. **Background:** only schedules (`scheduler.py`, semaphore 3) and App Builder
   builds. A chat round runs inside its SSE generator and is cancelled when
   the browser leaves (`routes_agent_chat.py`).
5. **Progress:** "is working..." in the thread and the Office live feed. No
   step count, no Stop, no finished notice for agent turns.

## Decisions

1. First job: a request typed to the team in the chat.
2. The plan is shown and runs only after the person presses Start.
3. The lead agent triages every team message.
4. The lead is one of the person's agents, marked with a Team lead switch.
5. A step sees the request, the plan (its own step marked) and the results of
   earlier steps, not the whole chat transcript.
6. A finished job is announced in the chat plus a Done badge; nothing outside.
7. Approach: job and step records plus a background worker. Rejected: reusing
   `tasks.items` (built for people and builds), and one long lead turn (60 s
   and 7-step limits, not durable).

## 1. Records and life cycle

1. `tasks.agent_job`: id, owner email, chat id, lead agent id, request text,
   status, created/started/finished times, final result.
2. `tasks.agent_job_step`: job id, position, agent id, what to do, status,
   result (capped), `run_id` linking to `tasks.agent_run`.
3. Job status: proposed, running, needs_you, done, failed, cancelled.
   Step status: waiting, running, done, failed, skipped.
4. Limits: one running job per person; 2 to 6 steps; a proposed plan expires
   after 24 hours.
5. Lead: a Team lead switch stored on the agent. If none is marked, the first
   agent whose role reads as a manager, else the first agent.

## 2. Triage and planning

1. Runs only for messages to the whole team. Named, private and approval
   messages keep today's path.
2. One extra call by the lead before the round: free model, tools off, one
   iteration (the summariser's settings). Strict output: `answer`, or `job`
   with 2 to 6 steps, each naming one of the person's agents and what it does.
3. A plan that names an unknown agent, has the wrong number of steps or an
   empty step is discarded and the round runs as normal.
4. Fails open: any error, timeout or busy model means a normal round.
5. The plan card is posted by the lead in the team chat with Start and Cancel
   and saved with the conversation, so a reload shows it and its status.
6. Cost: one free call per team message. The paid model is reachable only
   inside a step, under the existing daily cap.
7. The fake model gains `scene:job`, which returns a fixed plan.

## 3. Running

1. A worker loop in the tasks service, started like the scheduler, runs the
   steps of started jobs one at a time; at most 2 steps across all users at
   once (3.8 GB box).
2. A step is a normal agent turn (the agent's own tools and access), recorded
   with source `job`. Its brief: the request, the plan with its step marked,
   and earlier step results capped at about 2,000 characters each.
3. Each finished step posts the agent's answer in the team chat, labelled
   "Step N of M".
4. A step that wants to change something raises the existing Yes/No question
   in the chat; the job is `needs_you` until it is answered, then continues.
5. A failed step is retried once; a second failure fails the job, skips the
   rest, and the lead says which step failed and why.
6. Stop cancels the job: the running step is cancelled, the rest skipped.
7. Results are saved after every step; after a service restart the worker
   resumes at the step that was running and re-runs it once.
8. Each step has the normal turn limits plus a 5 minute hard cap.
9. After the last step the lead writes a short final answer from the results;
   it is posted and the job is done.

## 4. What the person sees

1. New events on `/agents/stream`, ids and numbers only: `job_started` (lead,
   step count, agents in order), `step_started` (agent, step N of M),
   `step_finished` (agent, step, status), `job_finished` (lead, status).
2. Chat: the plan card shows live status ("Running: step 2 of 4, Ada is
   working") and a Stop button; step results arrive as agent messages; the
   lead's final answer closes the job.
3. Agents list: the working agent pulses; the Everyone row shows "Job: 2 of 4"
   while running and a Done badge after a job finishes while away, until the
   conversation is opened.
4. Office: on `step_started` the lead walks to the assignee's desk and hands
   it over (Ralph's handoff walk and line, from the event, not guessed); the
   assignee types while working and speaks when its result posts; the to-do
   panel lists the job's steps with their status.
5. Plain text labels only.

## 5. Testing and rollout

1. Test first: plan checks, step brief, worker (start, retry, Stop, resume,
   needs_you), triage fallback; browser tests for the card, progress, Stop,
   list states and the Office hand-over.
2. Local first: `scene:job`; an end-to-end script that starts a job, closes
   the page mid-job, reopens and checks the result and the badge; a second run
   that restarts tasks mid-job and checks the resume.
3. One real free-model job on the local stack before going live.
4. Rollout, each part local first, reviewed, then deployed hash-checked:
   - Part A, engine: records, triage, plan card, worker, results in the chat;
   - Part B, views: agents list progress and badge, Office hand-over, to-do
     panel;
   - Part C: the `ask_colleague` brief also says who is asking (item 6 for
     plain chats).
5. Off switch: `AGENT_JOBS_ENABLED=false` keeps every message on today's path.
   Start refuses while it is off, and no worker runs. A job already running
   or waiting on its owner when it goes off is stranded: it holds their one
   running slot until the switch is back on or they press Stop, which
   works either way.
