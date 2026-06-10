# Outreach: Find → Review → Edit → Send (Discord)

- **Date:** 2026-06-10
- **Status:** Approved design (pending spec review)
- **Scope:** Discord `#recruiting` only. Slack and the n8n workflow are unchanged.

## 1. Problem

Today, clicking **🔍 Find Engineers** runs the agent and **immediately emails** everyone it
finds with a public address (one-shot find+send in `tasks` → n8n). The user wants a
**human-in-the-loop** flow: find first, show the list, let the user **select** who to email,
**edit** each drafted message, **add an email** to no-email finds, and only send when the
user presses Send.

## 2. Decisions (locked with user)

| Topic | Decision |
|---|---|
| Review depth | **Pick + edit** — preview and rewrite each email's subject/body before sending |
| Platform | **Discord only** for now; Slack keeps the existing auto-send until asked |
| Layout | **Overview + dropdowns** — one message: embed list + multi-select recipients + edit/add-email dropdown→popup + Send button |
| Permissions | **Initiator-only** — only the person who ran Find can select/edit/send; others get a quiet ephemeral decline |
| n8n workflow | **Unchanged** — receives the selected batch only at Send time |

## 3. User flow

1. **🔍 Find Engineers** → existing modal; the count field is relabeled **"How many to find"** (max 25, to fit one Discord select menu).
2. Agent searches GitHub + drafts a personalized email per engineer. **Nothing is sent or saved yet.**
3. Bot posts the **overview message** (see §5).
4. User: selects recipients (multi-pick) · **✏️ Edit** any draft · **✚ Add email** to a no-email find (both via popups).
5. **📧 Send to selected (n)** → only selected engineers are emailed + logged to the sheet via n8n → message updates to a sent-summary and the controls lock.

## 4. Backend (tasks service)

- **Mode flag:** `OutreachRequest.mode: "auto" | "manual"` (default `auto`). Slack/legacy callers omit it (auto). Discord sends `manual`.
  - `auto` → unchanged: `_run_outreach` finds, caps/dedupes, posts to n8n, stores summary.
  - `manual` → `_run_outreach` finds + drafts, **stores candidates**, does **not** post to n8n.
- **Candidate storage:** reuse the existing OUTREACH `TaskItem.result` JSON (no new column, **no migration**). Manual-mode shape: `{ phase: "review"|"sent", role, location, candidates: [...], summary? }`. Each candidate:
  `{ id, name, github_url, email, subject, body, selected: bool, status: "draft"|"sent"|"no_email" }`.
  `id` is a stable per-candidate slug (e.g. `c0`, `c1`, …) so component `custom_id`s and PATCH targets are stable. Auto mode keeps storing its summary in `result` as today (distinguished by the absence of `phase`/`candidates`).
- **Endpoints (new, all auth = current_user, owner-checked):**
  - `GET /outreach/{id}/candidates` → `{ status, role, location, candidates[] }` for rendering. `status` is `running` until the find finishes, then `ready`.
  - `PATCH /outreach/{id}/candidates/{cid}` → body any of `{ email?, subject?, body?, selected? }`; updates the stored candidate; returns it.
  - `POST /outreach/{id}/send` → gathers `selected == true && email` candidates → `post_outreach_to_n8n(job_title, selected)` → marks them `sent`, returns the summary `{found, sent, saved, sheet_url}`.
- `GET /outreach/{id}` (status) stays for the find-phase poll; in manual mode it returns `status: "ready"` once candidates exist.
- **Pure logic** (unit-tested, no DB): selection/edit application + "which candidates are sendable" + summary building live in `outreach.py` (extend the existing pure module).

## 5. Discord components (one message)

- **Embed:** numbered list, status icon per row (✅ selected · ⬜ not selected · ⚠ no email), name + email/`(no email)`.
- **Row 1** — string **multi-select** `Select who to email`: options = candidates that have an email (≤25); `values` = candidate ids; updating it PATCHes `selected` for each and re-renders.
- **Row 2** — string select `Edit / add-email for one…`: options = all candidates; choosing one responds with a **modal** (fields: Email, Subject, Body — prefilled). Submit PATCHes the candidate and re-renders.
- **Row 3** — buttons `📧 Send to selected (n)` and `♻ Refresh`.
- All `custom_id`s carry the task id (e.g. `aiuiout:sel:{task_id}`, `aiuiout:edit:{task_id}`, `aiuiout:send:{task_id}`, `aiuiout:editmodal:{task_id}:{cid}`).

## 6. Edge cases & errors

- Found nobody → message "No engineers matched — try a broader role or drop the location."
- Send with 0 selected → ephemeral "Pick at least one engineer first."
- No-email candidate is **not** in the multi-select until an email is added; if never added, it's simply not emailed (and, in v1, not saved).
- n8n/send partial failure → summary reports sent vs failed; candidates that failed stay `draft` (re-sendable).
- Non-initiator interaction → ephemeral "This isn't your outreach session."
- Invalid email in the add/edit modal → ephemeral re-prompt; candidate unchanged.
- Session is identified by the task id; the message stays usable as long as the task row exists.

## 7. New / changed units (small, isolated, testable)

- `webhook-handler/handlers/recruiting_review.py` — **pure** builders: overview embed+components, edit/add-email modal, re-render after a state change. Unit-tested in `tests/test_recruiting_review.py` (mirrors `test_recruiting_panel.py`).
- `webhook-handler/handlers/discord_commands.py` — route the new `aiuiout:sel|edit|send|editmodal` interactions to the router; modal handling.
- `webhook-handler/handlers/commands.py` — `run_panel_outreach` switches to `mode="manual"`; new `_render_outreach_review` (posts/edits the overview) and handlers for select/edit/send calling the new tasks-client methods. Replaces the auto-send `_watch_outreach` summary for Discord (keep `_watch_outreach` for Slack/auto).
- `webhook-handler/clients/tasks.py` — `get_outreach_candidates`, `patch_outreach_candidate`, `send_outreach`.
- `mcp-servers/tasks/routes_outreach.py` + `outreach.py` — the `mode` flag, candidate storage, the 3 new endpoints, pure selection/edit/summary helpers.
- DB: candidates stored as JSON in the existing `TaskItem.result` column — **no new column, no migration, no new table**.

## 8. Testing

- **webhook-handler:** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_review.py` for the pure builders; extend interaction tests.
- **tasks pure modules:** run the new pure helpers via the **webhook venv** (`"../../webhook-handler/.venv/Scripts/python.exe" -m pytest <file>`). **Never** run the full tasks suite (its conftest TRUNCATEs the prod DB).
- Manual: a live Discord run in `#recruiting` (find → select 1 → edit → send) verified against the n8n execution, same as the audit.

## 9. Out of scope (future)

- Slack parity for the review flow.
- A "Save all found to sheet (without emailing)" action for collected/no-email engineers.
- Persisting drafts across bot restarts beyond the task row (already covered by DB storage).
