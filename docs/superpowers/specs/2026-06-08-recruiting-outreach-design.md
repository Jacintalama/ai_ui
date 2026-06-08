# Recruiting Outreach Automation — Design Spec

**Date:** 2026-06-08
**Status:** Approved (high-level), pending spec review
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

Reuses the **build watcher** delivery model (`commands.py:_start_build` →
`_watch_build`), NOT the scheduler callback — because this is a one-off,
button-triggered action where the webhook-handler already holds the thread id.

```
Discord/Slack: click button → modal submit
   │  (webhook-handler: handle_interaction → ACK type-5 deferred)
   ▼
CommandRouter.run_panel_outreach(ctx, role, location, jobdesc, count)
   │  resolve caller email (→ _respond_not_linked if unlinked)
   ▼
TasksClient.start_outreach(email, {role, location, jobdesc, count})  ──HTTP──▶ tasks service
   │                                                                            │
   │  ACK "🔎 Searching GitHub… results in your thread"                         │  create TaskItem(prompt=outreach prompt)
   │                                                                            ▼
   │                                                          routes_execution._run_execution (agent)
   │                                                            1. GitHub API search (GITHUB_TOKEN)
   │                                                            2. fetch public emails; web-search to fill gaps
   │                                                            3. draft a personalized email per candidate
   │                                                            4. emit a fenced ```json block, then COMPLETED
   ▼
_watch_outreach watcher  (polls TasksClient until task completes)
   │  extract the JSON block from the agent result
   │  validate (pydantic) · enforce cap (≤count, ≤25) · within-batch dedupe by email
   ▼
N8NClient.trigger_workflow("recruiting-outreach", {job_title, sheet_id, candidates:[…]})  ──HTTP──▶ n8n
   │                                                                            │  Webhook → Read Sheet (cross-run dedupe)
   │                                                                            │        → for each NEW: Gmail send (sender = n8n Gmail cred)
   │                                                                            │        → append row (status sent | no_email) to Sheet
   │  ◀──────────────── { sent, saved, sheet_url } ────────────────────────────┘  Respond node
   ▼
post summary to the user's private thread (ctx.notify_channel)
```

**Why agent → JSON → webhook-handler → n8n (not agent → n8n directly):** the
money/email-sending step must be deterministic, not subject to LLM tool-call
reliability. The agent's job ends at producing a validated candidate list; the
webhook-handler enforces the cap + dedupe and calls the existing, error-handled
`N8NClient`. The agent emits a single fenced ` ```json ` block (robust to extract)
rather than free-form text.

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
to 1..25, default 10). Add `__all__`.

### 4.2 Routing — `discord_commands.py` + `slack_interactions.py`
Mirror the `is_sched_*` dispatch: `is_out_find` → return the modal (type 9);
`is_out_modal` → parse fields → `asyncio.create_task(router.run_panel_outreach(...))`
→ deferred ACK. Slack: the equivalent block-action + `views_open` modal path.

### 4.3 `commands.py` — `CommandRouter.run_panel_outreach`
Mirror `_start_build`/`_watch_build`:
- resolve email (`_resolve_email_for_ctx`; `_respond_not_linked` if none),
- validate `jobdesc` non-empty,
- `start_outreach` → ACK, then spawn `_watch_outreach(ctx, email, task_id)`.

`_watch_outreach`: poll the task (reuse the build-poll helper); on success
extract+validate JSON, enforce cap/dedupe, call `n8n_client.trigger_workflow`,
post the summary; on failure post a friendly error + 🔁 Retry.

### 4.4 `clients/tasks.py` — `start_outreach(email, payload) -> {task_id}`
Mirror `start_build`. Calls a new tasks endpoint.

### 4.5 `mcp-servers/tasks` — outreach task type
- New route `POST /outreach` (capability/admin auth like the build route) that
  creates a `TaskItem` whose `prompt` is the outreach prompt and kicks
  `_run_execution`. Reuses the existing execution pipeline + `parse_outcome`.
- New prompt builder `build_outreach_prompt(role, location, jobdesc, count)`:
  instructs the agent to (1) build a GitHub user-search query from role+location
  and call `https://api.github.com/search/users` with `Authorization: token
  $GITHUB_TOKEN`; (2) for each login, `GET /users/{login}` for a public email,
  and use web-search to fill gaps; (3) draft a short personalized email per
  candidate referencing their profile + the job description; (4) output **exactly
  one** fenced ` ```json ` block of shape:
  ```json
  {"candidates":[{"name":"…","github_url":"…","email":"… or null",
                  "subject":"…","body":"…"}]}
  ```
  then the bare `COMPLETED` sentinel.

### 4.6 `n8n-workflows/recruiting-outreach.json` (NEW)
Clone `sheets-report.json` structure (Webhook `responseMode:responseNode` →
Code → Google Sheets → Respond) and add Gmail:
`Webhook(path=recruiting-outreach)` → `Google Sheets (read, for dedupe)` →
`Code (filter out emails already in sheet; split has-email vs no-email; cap)` →
`Gmail (send, loop over has-email)` → `Google Sheets (append every candidate,
status sent|no_email)` → `Respond ({sent, saved, sheet_url})`. Gmail + Sheets
use n8n-UI-configured OAuth credentials (the recruiting sender account).

### 4.7 Google Sheet (collected-info store)
Columns: `date | name | github_url | email | status | job_title`. The boss
creates it, shares it with the n8n Google account; its id goes in config.

## 5. Configuration / secrets

| Var | Where | Notes |
|---|---|---|
| `GITHUB_TOKEN` | tasks container env (server `.env`) | free PAT, raises GitHub rate limit 60→5000/hr. Boss creates; **we never touch `.env`** — boss/operator adds it. |
| `N8N_API_URL`, `N8N_API_KEY` | already set (tasks + webhook-handler) | reused as-is |
| `OUTREACH_SHEET_ID` | webhook-handler env (passed to n8n payload) | the Google Sheet id |
| n8n Gmail + Sheets OAuth | n8n UI | the consistent sender + sheet writer |

## 6. Safety guardrails (built in)

- **Per-run cap:** clamp `count` to 1..25; the n8n Code node hard-caps sends too.
- **Cross-run dedupe:** n8n reads the Sheet and skips any email already present —
  never email the same person twice.
- **Within-batch dedupe:** webhook-handler drops duplicate emails before n8n.
- **Only real emails are mailed:** candidates with `email=null` are appended to
  the Sheet (`status=no_email`) and never sent.
- **Single sender:** all mail goes from one n8n-connected Gmail (professional +
  avoids per-user-token complexity). Small batches stay under n8n's 120s timeout.

## 7. Error handling

- Caller not linked → `_respond_not_linked(ctx)` (existing self-service Link card).
- Agent failed / no JSON block / invalid JSON → post a friendly failure + 🔁 Retry;
  log the raw result. Never 500 the interaction.
- No candidates found → "I couldn't find engineers matching that — try a broader
  role or remove the location."
- `N8NClient.trigger_workflow` returns `None` (timeout/empty body = n8n error) →
  post "Found N engineers but sending failed — they're saved, I'll retry sends."
  and still surface the candidate count. (N8NClient already logs + returns None.)
- GitHub rate-limit / 403 → agent reports it in the JSON-less failure path.

## 8. Testing strategy

All unit-level, **no production DB** (conftest TRUNCATEs — never run pytest against
prod; the 2026-04-27 incident wiped 9 projects):

- `recruiting_panel` pure builders: panel/modal shape, custom_ids, count clamping,
  `parse_outreach_modal` (default 10, clamp 0→1 and 99→25).
- Routing: `is_out_find` returns a modal; `is_out_modal` dispatches a background
  task + deferred ACK (mirror `test_schedules_ux_interactions.py`).
- `_watch_outreach`: JSON extraction from a sample agent transcript; cap + dedupe;
  n8n payload shape; the "n8n returned None" branch posts the fallback message.
- `start_outreach` client: correct URL/headers/body (mirror build client tests).
- n8n workflow JSON: validated as well-formed + has the expected node chain.

## 9. Scope & phasing

- **v1 (this spec):** one button → find + email + collect, one run at a time.
  Roughly: 1 panel file + routing on both bots + 1 router method + 1 client method
  + 1 tasks route/prompt + 1 n8n workflow + 1 Sheet. Reuses bots, agent engine,
  build-watcher delivery, N8NClient, web-search.
- **Phase 2 (easy adds):** "run every Monday" via the existing scheduler;
  swap GitHub source for a paid people-data API behind the same agent prompt;
  reply tracking; an optional "Confirm send" review card before bulk send.

## 10. Open setup tasks for the operator (one-time, no code)

1. Create a GitHub PAT, add `GITHUB_TOKEN` to the server `.env` (operator-only).
2. In n8n: connect the recruiting Gmail + Google Sheets accounts; import &
   activate the `recruiting-outreach` workflow.
3. Create the Google Sheet with the column header row; share with the n8n account;
   put its id in `OUTREACH_SHEET_ID`.
