# Recruiting Outreach Automation — Design Spec

**Date:** 2026-06-08
**Status:** Approved (high-level), spec-review iteration 2
**Author:** brainstormed with Jacint

## 1. Problem & Goal

The employer (boss) wants a **one-button** way, from the Discord/Slack bot, to:

1. **Find** software engineers from public sources (GitHub + web search).
2. **Email** them a job description (only those for whom an email is found).
3. **Collect** every engineer found into a shared Google Sheet (so they're tracked
   even when no email exists).

Constraints from the user (locked decisions):

| Decision | Choice | Source |
|---|---|---|
| Lead source | **GitHub (official API) + web search** to fill missing emails | user |
| Send channel | **Email**, auto-send to those with an email; collect the rest | user |
| Engine | **Hybrid**: AI agent *finds + drafts*; n8n *sends + logs to Sheet* | user |
| Placement | New **`#recruiting` channel** on both Discord and Slack | default (approved) |
| Send mode | **Straight send**, protected by a per-run cap + dedupe | default (approved) |

Non-goals (explicitly out of scope for v1):

- No LinkedIn / job-board scraping (ToS/ban risk, no emails).
- No paid people-data API (Apollo/Hunter) — clean phase-2 add.
- No reply tracking / inbound capture — replies land in the sender's Gmail.
- No recurring schedule in v1 (the existing scheduler makes this a phase-2 add).

## 2. User-facing flow

A pinned card in `#recruiting` (mirrors the App Builder / Schedules panels):

```
🎯 Recruiting Outreach — Find engineers and email them a job in one click.
[ 🔍 Find Engineers ]   [ 🔗 Link my account ]
```

Click **🔍 Find Engineers** → a modal (4 inputs, fits Discord's 5-row limit):

| Input id | Label | Style | Required | Example |
|---|---|---|---|---|
| `role` | Skill / language | short | yes | `Python backend` |
| `location` | Location (optional) | short | no | `Berlin` |
| `jobdesc` | Job description | paragraph | yes | `We're hiring a senior...` |
| `count` | How many to email (max 25) | short | no (default 10) | `10` |

On submit: bot ACKs (deferred), runs in background, and posts the result to the
user's private thread (same thread model as Schedules):

```
✅ Outreach complete for "Python backend · Berlin"
• Emailed 8 engineers
• Saved 4 more (no public email) to the list
👉 https://docs.google.com/spreadsheets/d/…
```

## 3. Architecture & data flow

The **tasks service owns the whole backend pipeline** (agent run → JSON extract →
validate → cap/dedupe → n8n call → summary). The bot just kicks it off and polls a
summary — it never parses agent output. This keeps the hybrid intact (agent =
smart find+draft; n8n = bulk send+log) while putting the deterministic,
money-sending glue in testable Python rather than the bot or the LLM.

Delivery reuses the **build watcher** model (`commands.py:_start_build` →
`_watch_build`): a detached task polls the tasks service and posts via
`ctx.notify_channel` when done. The bot already holds the thread id, so no
scheduler callback is involved.

```
Discord/Slack: click button → modal submit
   │  webhook-handler: handle_interaction → ACK type-5 deferred
   ▼
CommandRouter.run_panel_outreach(ctx, role, location, jobdesc, count)
   │  resolve caller email (→ _respond_not_linked if unlinked); validate jobdesc
   ▼
TasksClient.start_outreach(email, {role, location, jobdesc, count})  ──HTTP──▶ tasks: POST /outreach
   │   ACK "🔎 Searching GitHub… results in your thread"                        │  create TaskItem(prompt=outreach prompt)
   │                                                                            ▼
   │                                          _run_outreach (background, sibling of _run_execution)
   │                                            1. agent run: GitHub API via Bash curl ($GITHUB_TOKEN),
   │                                               native WebSearch/WebFetch to fill missing emails,
   │                                               draft a personalized email per candidate
   │                                            2. agent emits ONE fenced ```json block, then bare COMPLETED
   │                                            3. parse_outcome → branch completed/failed
   │                                            4. extract_final_body(log) → the text BEFORE the sentinel
   │                                            5. pull the fenced json, validate (pydantic CandidateList)
   │                                            6. cap (≤count, ≤25) + within-batch dedupe by email
   │                                            7. httpx POST to {n8n base}/webhook/recruiting-outreach
   │                                                  {job_title, candidates:[…]}   ──HTTP──▶ n8n
   │                                                  Webhook → Read Sheet (cross-run dedupe)
   │                                                        → Gmail send (has-email) → append all rows
   │                                                        → Respond {sent, saved, sheet_url}
   │                                            8. store summary {found, sent, saved, sheet_url, text}
   │                                               on the TaskItem (result JSON)
   ▼
_watch_outreach watcher  ──poll──▶  tasks: GET /outreach/{task_id} → {status, found, sent, saved, sheet_url, text}
   │
   ▼
post the summary to the user's private thread (ctx.notify_channel)
```

**Why the tasks service calls n8n (not the agent, not the bot):** the agent
*inherits the tasks container env* and has full tools, so it could call n8n — but
the send step must be deterministic, not subject to LLM tool-call reliability. The
agent's job ends at producing a validated candidate list; tasks-service Python
enforces cap/dedupe and POSTs to n8n via the **same raw-`httpx` webhook pattern
`routes_cron.py:298-302` already uses** for the weekly recap. The bot stays dumb
(poll a summary), avoiding any JSON parsing in the interaction layer.

## 4. Components to build

### 4.1 `webhook-handler/handlers/recruiting_panel.py` (NEW — pure builders)
Mirrors `app_builder_panel.py` exactly (no I/O, unit-tested). New `aiuiout:*`
namespace:

```
OUT_FIND_ID  = "aiuiout:find"    # button (exact match)
OUT_MODAL_ID = "aiuiout:modal"   # modal submit (exact match)
OUT_ROLE_INPUT, OUT_LOCATION_INPUT, OUT_JOBDESC_INPUT, OUT_COUNT_INPUT
```
Functions: `build_recruiting_panel()`, `build_recruiting_embed()`,
`build_outreach_modal()`, `is_out_find()`, `is_out_modal()`,
`parse_outreach_modal(values) -> (role, location, jobdesc, count)` (clamps count
to 1..25, default 10 on missing/non-numeric). Add `__all__`.

### 4.2 Routing — `discord_commands.py` + `slack_interactions.py`
Mirror the `is_sched_*` dispatch: `is_out_find` → return the modal (type 9);
`is_out_modal` → parse fields → `asyncio.create_task(router.run_panel_outreach(...))`
→ deferred ACK. Slack: the equivalent block-action + `views_open` modal path.

### 4.3 `commands.py` — `CommandRouter.run_panel_outreach`
Mirror `_start_build`/`_watch_build`:
- resolve email (`_resolve_email_for_ctx`; `_respond_not_linked` if none),
- validate `jobdesc` non-empty,
- `start_outreach` → ACK, then spawn `_watch_outreach(ctx, email, task_id)` tracked
  in `self._background_tasks` (same pattern as `_start_build`).

`_watch_outreach`: poll `TasksClient.get_outreach_status(task_id)` until terminal;
on `completed` post the summary text + Sheet link; on `failed` post a friendly
error + a 🔁 Retry button. No JSON parsing here — the tasks service already did it.
Size the poll budget (max polls × interval) to comfortably exceed the agent's
`EXECUTION_TIMEOUT_SECONDS` (600s) **plus** the n8n send, so the watcher never
gives up before `_run_outreach` finishes — same concern as `_watch_build`'s
`BUILD_MAX_POLLS`/`BUILD_POLL_SECONDS`.

### 4.4 `clients/tasks.py` — two methods (mirror `start_build`/`get_build_status`)
- `start_outreach(email, payload) -> {task_id}` → `POST /outreach`.
- `get_outreach_status(task_id) -> {status, found, sent, saved, sheet_url, text}`
  → `GET /outreach/{task_id}`.

### 4.5 `mcp-servers/tasks` — outreach task type + status endpoint
- `POST /outreach` (`current_user` / X-User-Email auth — the build route uses
  `Depends(current_user)`, NOT admin): create a `TaskItem` whose `prompt` is the
  outreach prompt, then kick `_run_outreach`. Returns `{task_id}`.
- `_run_outreach` (NEW background coroutine, sibling to `_run_execution`):
  1. stream the agent; `parse_outcome` to branch `completed`/`failed`.
  2. on `failed`: store the failure reason; done.
  3. on `completed`: `extract_final_body(log)` → text **before** the sentinel
     (NOT `parse_outcome`, whose after-sentinel payload is empty for a bare
     trailing `COMPLETED` — this is the bug fixed in commit `41754d918`).
  4. extract the single fenced ` ```json ` block; validate with a pydantic model
     `CandidateList{candidates:[{name, github_url, email|null, subject, body}]}`.
     If absent/invalid → store a failure summary ("couldn't parse candidates").
  5. cap to `min(count, 25)`; drop within-batch duplicate emails.
  6. POST to n8n via raw `httpx` (mirror `routes_cron.py:298-302`, the tasks
     service's existing n8n-webhook call) to `{n8n base}/webhook/recruiting-outreach`
     with `{job_title, candidates}`. The base URL is read from env with the hosted
     default `https://n8n.srv1041674.hstgr.cloud` — the same default
     `routes_cron.py:18-20` already uses, so **no new n8n secret is required**
     (webhook-path triggers don't use an API key). **There is no `N8NClient` in the
     tasks service** (it lives only in `webhook-handler`); do not assume one. On
     non-2xx / timeout, store a partial summary ("found N, sending failed — saved
     to list, will retry"). Use a generous client timeout (e.g. 90s) for the send
     loop; `routes_cron.py` uses 30s for its single POST.
  7. store a result JSON on the `TaskItem` (`{found, sent, saved, sheet_url,
     text}`) where `text` is the human one-liner the bot will post.
- `GET /outreach/{task_id}` → `OutreachStatusResponse{status, found, sent, saved,
  sheet_url, text}`, reading the stored result JSON. This is the dedicated result
  channel the bot polls (the build-status endpoint deliberately does NOT return
  `result` on success, so it cannot be reused).
- New prompt builder `build_outreach_prompt(role, location, jobdesc, count)`:
  instructs the agent to (1) translate role+location into a GitHub user-search
  query and call `https://api.github.com/search/users` via Bash `curl` with
  `Authorization: token $GITHUB_TOKEN` (token inherited from the container env);
  (2) for each login `GET /users/{login}` for a public email, and use the native
  WebSearch/WebFetch tools to fill gaps; (3) draft a short personalized email per
  candidate referencing their profile + the job description; (4) output **exactly
  one** fenced ` ```json ` block of `CandidateList` shape, then a bare `COMPLETED`.

### 4.6 `n8n-workflows/recruiting-outreach.json` (NEW)
Clone `sheets-report.json`'s skeleton (Webhook `responseMode:responseNode` →
Code → Google Sheets → Respond) and add Gmail:
`Webhook(path=recruiting-outreach)` → `Google Sheets (read — for cross-run
dedupe)` → `Code (drop emails already in sheet; split has-email vs no-email)` →
`Gmail (send, loop over has-email)` → `Google Sheets (append every candidate,
status sent|no_email)` → `Respond ({sent, saved, sheet_url})`.
- The target Google Sheet is **configured once in the workflow's Google Sheets
  nodes in the n8n UI** (like `sheets-report.json`'s baked-in `documentId`); the
  payload does NOT carry a sheet id, removing a moving part. `Respond` returns the
  Sheet's URL so the bot can link it.
- Gmail + Sheets use n8n-UI-configured OAuth credentials (the one recruiting
  sender + sheet-writer account). The JSON file ships with `id:"CONFIGURE_IN_UI"`
  placeholders that the operator binds on import (same convention as the existing
  workflows).

### 4.7 Google Sheet (collected-info store)
Columns: `date | name | github_url | email | status | job_title`. The boss
creates it, shares it with the n8n Google account, and selects it in the n8n
workflow's Sheets nodes (4.6). Not referenced by any service env.

## 5. Configuration / secrets

All new config lives on the **tasks** container (which now runs the agent *and*
calls n8n). The webhook-handler needs **no new secret**.

| Var | Where | Notes |
|---|---|---|
| `GITHUB_TOKEN` | tasks container env (server `.env`) | **the only new required secret.** Free PAT, raises GitHub rate limit 60→5000/hr. Inherited by the agent subprocess (`env={**os.environ}`). Boss/operator adds it; **we never touch `.env`**. |
| n8n webhook base URL | hosted default in code | the tasks service POSTs to `https://n8n.srv1041674.hstgr.cloud/webhook/recruiting-outreach` — same hosted default `routes_cron.py` already uses. No api key needed for webhook triggers. Optionally override via an env var (e.g. `N8N_WEBHOOK_BASE`) if the host ever changes. |
| n8n Gmail + Sheets OAuth + sheet selection | n8n UI | the consistent sender + the target Sheet |

`docker-compose.unified.yml` tasks service gains a `GITHUB_TOKEN=${GITHUB_TOKEN:-}`
line (parameterized, no secret in the repo). The tasks service does **not**
currently have `N8N_*` env (those lines 123-125 belong to the webhook-handler);
none are needed because the n8n base falls back to the hosted default in code.

## 6. Safety guardrails (built in)

- **Per-run cap:** clamp `count` to 1..25 in the modal parser; `_run_outreach`
  re-caps to `min(count, 25)`; the n8n Code node hard-caps sends too.
- **Default 10 keeps under the tasks-side n8n call timeout:** `_run_outreach`'s
  `httpx` POST uses a ~90s timeout; a Sheets-read + per-send Gmail loop is ~1–2s/
  send, so 10 is comfortable and 25 fits. The hard max of 25 is the documented
  ceiling; if a future phase raises it, the n8n workflow must switch to
  respond-early + async send (noted, not built in v1).
- **Cross-run dedupe:** the n8n workflow reads the Sheet and skips any email
  already present — never email the same person twice.
- **Within-batch dedupe:** `_run_outreach` drops duplicate emails before n8n.
- **Only real emails are mailed:** candidates with `email=null` are appended to the
  Sheet (`status=no_email`) and never sent.
- **Single sender:** all mail goes from one n8n-connected Gmail (professional +
  avoids per-user-token complexity).

## 7. Error handling

- Caller not linked → `_respond_not_linked(ctx)` (existing self-service Link card).
- Agent `FAILED` / no JSON block / invalid JSON → `_run_outreach` stores a failure
  summary; `GET /outreach` returns `status=failed`; the watcher posts a friendly
  message + 🔁 Retry. Never 500 the interaction.
- No candidates found → "I couldn't find engineers matching that — try a broader
  role or remove the location."
- `N8NClient.trigger_workflow` returns `None`/`{"status":"error"}` (timeout / empty
  body / n8n error — already logged by the client) → store a partial summary
  ("Found N engineers but sending failed — they're saved; I'll retry sends") and
  surface the found count.
- GitHub rate-limit / 403 → the agent reports it via the `FAILED:` path.

## 8. Testing strategy

All unit-level, **no production DB** (conftest TRUNCATEs — never run pytest against
prod; the 2026-04-27 incident wiped 9 projects):

- `recruiting_panel` pure builders: panel/modal shape, custom_ids, count clamping,
  `parse_outreach_modal` (default 10; clamp 0→1, 99→25; non-numeric→10).
- Routing: `is_out_find` returns a modal; `is_out_modal` dispatches a background
  task + deferred ACK (mirror `test_schedules_ux_interactions.py`).
- `_run_outreach` (tasks): JSON extraction via `extract_final_body` from a sample
  that is a **real stream-json `result` line** (e.g.
  `{"type":"result","result":"…```json…```\nCOMPLETED"}`), since the executor runs
  `--output-format stream-json` and `extract_final_body` reads the final `result`
  event — not plain text; then cap + within-batch dedupe; the n8n-error branch
  stores the partial summary; agent-`FAILED` branch stores the failure.
- `GET /outreach/{task_id}`: returns the stored summary shape; 404 for unknown id.
- `_watch_outreach` + `get_outreach_status` client: correct URL/headers; posts
  summary on completed, error+Retry on failed.
- n8n workflow JSON: well-formed + has the expected Webhook→Sheets→Code→Gmail→
  Sheets→Respond node chain.

## 9. Scope & phasing

- **v1 (this spec):** one button → find + email + collect, one run at a time.
  Roughly: 1 panel file + routing on both bots + 1 router method + 2 client methods
  + 1 tasks route + `_run_outreach` + 1 status endpoint + 1 prompt builder + 1 n8n
  workflow + 1 Sheet. Reuses the bots, the agent engine (full-tool `claude` with
  native WebSearch/WebFetch + Bash), the build-watcher delivery, the
  `routes_cron.py` n8n-webhook httpx pattern, and `extract_final_body`.
- **Phase 2 (easy adds):** "run every Monday" via the existing scheduler;
  swap GitHub for a paid people-data API behind the same agent prompt; reply
  tracking; an optional "Confirm send" review card before bulk send.

## 10. Open setup tasks for the operator (one-time, no code)

1. Create a GitHub PAT; add `GITHUB_TOKEN` to the server `.env` (operator-only).
2. In n8n: connect the recruiting Gmail + Google Sheets accounts; import &
   activate the `recruiting-outreach` workflow; select the target Sheet in its
   Sheets nodes.
3. Create the Google Sheet with the header row; share it with the n8n account.
