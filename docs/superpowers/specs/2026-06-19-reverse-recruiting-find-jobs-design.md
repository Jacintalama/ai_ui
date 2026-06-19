# Reverse Recruiting: "Find Jobs" (Discord + Slack)

- **Date:** 2026-06-19
- **Status:** Approved design (pending spec review)
- **Scope:** A second button on the `#recruiting` panel that runs the *reverse* of today's Find-Engineers flow — find **companies/roles** for a job-seeker and email a tailored application to each, on their behalf. Discord **and** Slack, both with full review-before-send.

## 1. Problem / Goal

Today the recruiting feature is **one-directional**: a company describes a role and the bot finds **engineers** on GitHub and emails them a pitch (company → engineer). The team's standup direction is the *reverse*: **reverse recruiting** — the bot works **for a job-seeker**, finding companies that are hiring and pitching them on the seeker's behalf (seeker → company).

We want this as a **new button next to "Find Engineers"**, reusing as much of the existing machinery as possible, with the same find → review → edit → send → Google-Sheet flow.

## 2. The key architectural fact (why this is small past the entry point)

The existing review/edit/send pipeline is **direction-agnostic** — every handler keys off `task_id` and renders whatever candidates the backend stored (`commands.py:2463-2549`, `routes_outreach.py:148-220`). The `Candidate` model and all pure helpers (`extract_candidates`, `cap_and_dedupe`, `build_review_candidates`, `apply_candidate_edit`, `set_selection`, `sendable_candidates`) are equally direction-agnostic (`outreach.py:20-175`). The n8n `recruiting-outreach` webhook is generic "dedupe-by-email → Gmail each → log to sheet" (`outreach.py:94-105`).

So reverse recruiting needs: **a `direction` flag on the backend request + a reverse prompt branch + a new entry button/modal/router method per platform.** The review→send *logic* (selection, edit, send-to-n8n, sheet logging) is reused as-is. Two seams are NOT free, though, and the spec treats them as first-class work: (1) the re-render handlers must become **platform- and direction-aware** so labels/builder are correct on every interaction, not just the first post (§5–§6), and (2) the **Slack review layer** is genuinely new — Slack lacks it today (§7).

## 3. Decisions (locked with user)

| Topic | Decision |
|---|---|
| Meaning of "reverse" | **Reverse recruiting** — bot works for the job-seeker: find companies/roles, email applications on their behalf (seeker → company). NOT inbound applicant triage. |
| Send behavior | **Find + email companies (full mirror)** — search, draft a tailored application per company, review/edit, then Send via the existing n8n webhook + log to the sheet. |
| Email identity | **Shared Gmail sender** (no per-user OAuth), with the seeker's name/email in the application signature and `Reply-To = seeker` so company replies route to the job-seeker. |
| Platforms | **Discord + Slack.** |
| Slack behavior | **Build the Slack review layer too** — both platforms review applications before any email goes out (closes the existing Slack parity gap). |
| Data / DB | **No migration.** Reuse the OUTREACH `TaskItem.result` JSON; add a `direction` key. |
| n8n | **Reuse** the `recruiting-outreach` workflow; add `reply_to` to the payload and surface it on the Gmail node. This is **not** a Gmail-node-only edit — `reply_to` must reach the Gmail node (via the Dedupe Code node's per-item output or a `$('Webhook')` reference; see §9), and the change is made in the **live Hostinger instance via the UI** (the repo JSON is a template / docs only). |

## 4. User flow (both platforms)

1. **Find Jobs** button on the `#recruiting` panel → a modal (relabeled from the engineer modal):
   - *Target role* (required) — the role the seeker wants (e.g. "Senior Python backend")
   - *Location (optional)*
   - *Your background / skills* (required, multiline) — the seeker's experience, used to tailor each application
   - *How many companies (max 25)*
2. Agent uses web search to find companies plausibly hiring for that role, a real careers/contact email per company, and drafts a **first-person application email** (subject + body) signed as the seeker. **Nothing is sent yet.**
3. Bot posts the **review message** (company list + pick-who-to-email multi-select + edit/add-email dropdown→modal + Send/Refresh) — the same UX as Find-Engineers, with company-oriented labels.
4. User selects which companies to apply to, edits any application, fixes/adds emails, then **Send** → only selected emailable companies get the application via n8n → all are logged to the sheet → message locks to a sent-summary.

## 5. Backend (`mcp-servers/tasks`)

- **`OutreachRequest.direction: str = "hire"`** (`routes_outreach.py:22-27`). `"hire"` = today's behavior unchanged; `"reverse"` = the new flow. Stored into the `result` JSON so the UI and find-phase text can label correctly.
- **`outreach.build_outreach_prompt(role, location, jobdesc, count, *, direction="hire")`** (`outreach.py:65-91`) gains a `reverse` branch:
  - Frames the agent as a job-search assistant acting **on behalf of** the seeker (whose background = `jobdesc`).
  - Step 1: use **WebSearch/WebFetch** to find companies hiring for `role`(+location) and a **real** careers/jobs/hiring-contact email each (`careers@`, `jobs@`, a named contact). Never fabricate — `null` if not found (mirrors the existing no-fabrication rule).
  - Step 2: draft a SHORT, tailored, **first-person application** per company (subject + body), grounded in the background, signed as the seeker.
  - Step 3: same single fenced-`json` `{candidates:[{name, github_url, email, subject, body}]}` + `COMPLETED` contract, so `extract_candidates`/`cap_and_dedupe`/`build_review_candidates` are reused verbatim. For reverse, `name` = company, `github_url` = company/careers URL (**field intentionally repurposed**; the review embed and edit modal don't surface it, n8n only logs it), `email` = contact email, `subject`/`body` = the application.
- **Persisting `direction`/`role`/`location` into `result` JSON** (so every later re-render can resolve labels and restore the title — today only `job_title`=role is stored). This is **not** done in `start_outreach` (which only creates the task); the `result` is written by `_run_outreach` → `_process_outreach_find` (manual) / `_process_outreach_result` (auto) and by the send handler. So: `start_outreach` passes `direction` **and `location`** into `_run_outreach` (today `_run_outreach` receives only `job_title`=role, `count`, `mode` — `location` must be newly threaded), and `_process_outreach_find`/`_process_outreach_result` include `direction`/`role`/`location` in the stored summary dict.
- **`OutreachStatusResponse` gains `direction: str = "hire"`, and `role`/`location`** (`routes_outreach.py:30-43`), **populated by the status, `/candidates`, the PATCH `/candidates/{cid}`, AND `/send` endpoints.** The PATCH endpoint is the critical one: `run_outreach_select` (selection) and `run_outreach_edit_submit` re-render directly from the PATCH response (`commands.py:2478, 2513`), so adding the fields to the shared model is necessary but not sufficient — the PATCH handler (`routes_outreach.py:179-180`, today returns only `status/candidates/found/job_title`) must also populate them, or the two most common interactions still fall back to hire copy. This is the **load-bearing change** that lets the re-render methods (§6) resolve the right builder copy from backend state rather than the (empty) args they're called with today.
- **Direction-aware backend copy — template _every_ user-facing "engineer" string, not just the embed:**
  - `format_outreach_summary(found, sent, saved, sheet_url, *, direction="hire")` → "found N **companies**" vs "engineers" (`outreach.py:108-114`). This summary is generated by the backend and merely echoed into `build_sent_message`, so a UI-side `kind` arg cannot fix it — it must be fixed here.
  - `_process_outreach_find` / `_process_outreach_result` not-found copy (`routes_outreach.py:55, 80`) and the 0-selected text "Pick at least one engineer with an email first." (`routes_outreach.py:190`) become direction-aware.
- **Send** (`POST /outreach/{id}/send`, `routes_outreach.py:183-220`) passes `reply_to` (the task's `assignee_email`) and `job_title` (= the target role) to `post_outreach_to_n8n`. For reverse this is the seeker; for hire it's the recruiter who ran the search (harmless/beneficial — replies route back to them). Confirmed available at send time via the stored task.
- **`post_outreach_to_n8n(job_title, candidates, *, reply_to="")`** (`outreach.py:94-105`) adds `reply_to` to the payload. Backward-compatible (empty default).

## 6. Discord (additive — reuses the entire review layer)

- **`recruiting_panel.py`:** add `REV_FIND_ID = "aiuiout:revfind"`, `REV_MODAL_ID = "aiuiout:revmodal"`, `is_rev_find`/`is_rev_modal`, and `build_reverse_modal()` (the relabeled modal from §4). Reuse `parse_outreach_modal` (returns `role, location, jobdesc, count` — `jobdesc` carries the seeker's background). Add the **"Find Jobs"** button to `build_recruiting_panel` (`recruiting_panel.py:38-44`).
- **`discord_commands.py`:** add a branch in the component router (`:369-383`) — `is_rev_find` → return the reverse modal — and in the modal-submit router (`:782`) — `is_rev_modal` → parse + spawn `router.run_panel_reverse(...)`.
- **`commands.py`:** add `run_panel_reverse(ctx, role, location, jobdesc, count)` — identical to `run_panel_outreach` (`:2336-2370`) except it sends `direction="reverse"` and always `mode="manual"`.
- **`commands.py` — the re-render handlers are CHANGED, not reused unchanged** (this is the gap both reviews flagged). `run_outreach_select` / `run_outreach_edit_submit` / `run_outreach_send` (`:2463-2549`) today hardcode `from handlers import recruiting_review as rr` and call `build_review_message(..., role="", location="")`. They must become **platform- and direction-aware**:
  - pick the builder by `ctx.platform` (`recruiting_review` for Discord vs `slack_recruiting_review` for Slack — §7);
  - read `direction`, `role`, `location` from the backend status/candidates response (now returned, §5) and pass them to the builder, so reverse company-copy and the title survive every re-render (today's hire flow also loses the title after the first click — this fixes that too);
  - template the hardcoded fallbacks: "Pick at least one engineer first." (`:2546, 2549`) and the watcher degrade text "Engineers ready to review." / "No engineers found." (`_watch_outreach_review`, `:2440, 2459`).
- **`recruiting_review.py`:** `build_review_message` / `build_sent_message` take a `kind` (derived from `direction`) so the embed title/footer, the select **placeholder** "Select who to email…" (`:47`), and the button label read company-oriented copy for reverse ("Found N companies for {role}", "Pick who to apply to", "Send applications (n)") while staying identical for hire. Pure, unit-tested.

## 7. Slack review layer (the one substantial new build)

Slack today auto-sends (`commands.py:2347` sets `mode="manual"` only for Discord) and its `CommandContext` has only `notify_channel` + `respond` (`slack_interactions.py:773-784`) — no rich-post, no edit. To review on Slack we add:

- **`webhook-handler/handlers/slack_recruiting_review.py`** (new, pure, mirrors `recruiting_review.py`): Block Kit builders for the review message (section list + a multi-select of emailable companies + an "edit one" select → modal + Send/Refresh buttons) and the edit modal `view`, using the **same** `aiuiout:sel|edit|send|refresh|editmodal:{task_id}` id scheme. Unit-tested in `tests/test_slack_recruiting_review.py`.
- **Slack client + context:** give the Slack `CommandContext` a `notify_channel_msg` (posts Block Kit via the existing `SlackClient.post_message(..., blocks=...)`, `clients/slack.py:91-92`) and an `edit_message` that **replaces the review message in place**. `SlackClient` has `post_to_response_url(replace_original=True, blocks=...)` already (`clients/slack.py:232-275`) but **no `chat.update`** — so the edit mechanism is response-url-based, with one wrinkle the spec must get right:
  - **Block actions** (`aiuiout:sel|send|refresh:*`) **do** carry `response_url` (used today at `slack_interactions.py:303, 338`); their `edit_message` calls `post_to_response_url(replace_original=True)` on the watcher's posted message. Works.
  - **The edit-modal submit is a `view_submission`, which carries NO `response_url`.** So we cannot edit via response_url on the modal path. Mechanism: when the `aiuiout:edit:*` block action opens the edit modal (via `views.open` with the block action's `trigger_id`), **stash that block action's `response_url` in the modal's `private_metadata`** (alongside the task_id/cid); on `view_submission`, read it back and `post_to_response_url(replace_original=True)` to re-render. (Accept the response_url ~30-min / 5-use limit — fine for a review session; if it expires, fall back to posting a fresh review message.)
- **`slack_interactions.py`:** route the new block actions — `aiuiout:sel:*` → `run_outreach_select`, `aiuiout:edit:*` → `views.open` the edit modal (trigger_id is present on block actions), `aiuiout:send:*` → `run_outreach_send`, `aiuiout:refresh:*` → refresh — and the `aiuiout:editmodal:*` `view_submission` → `run_outreach_edit_submit`, building a review-capable Slack `ctx` whose `edit_message` uses the response_url per the rule above. These call the **same** (now platform/direction-aware, §6) router methods Discord uses (`commands.py:2463-2549`).
- **`run_panel_reverse` (and `run_panel_outreach`) become `mode="manual"` on Slack too.** `_watch_outreach_review` (`commands.py:2413`) selects the builder by `ctx.platform` (Discord `recruiting_review` vs Slack `slack_recruiting_review`) and posts via `ctx.notify_channel_msg` (now present on both).
- **Entry button/modal:** `slack_recruiting_panel.py` gains `OUT_REV_ACTION_ID`/`OUT_REV_CALLBACK`, a "Find Jobs" button in `build_recruiting_blocks` (`:41-64`), and `build_reverse_view()` + `reverse_fields_from_view()` (reusing the shared `parse_outreach_modal`). Routed at `slack_interactions.py:346` (button) and `:760` (modal submit).

> Note: making Slack `run_panel_outreach` manual changes today's Slack **hire** behavior (auto-send → review). That's an intended improvement and is consistent with Discord; called out so it's not a surprise.

## 8. Edge cases & errors

- No companies found / no usable email found → direction-aware "couldn't find companies hiring for that — try a broader role or drop the location."
- Send with 0 selected → "Pick at least one company first." (reuses existing 0-selected handling, `routes_outreach.py:188-191`).
- No-email company is excluded from the multi-select until an email is added (existing behavior).
- n8n/send failure → candidates stay `draft` (re-sendable); summary reports sent vs saved (existing behavior).
- Invalid email in the edit modal → bounced without mutating the candidate (existing `_valid_email` guard, `commands.py:2499-2511`).
- Initiator-only / ownership is enforced by the existing owner check (`assignee_email`, `routes_outreach.py:91`).
- **Account-link gate (by design):** a seeker who hasn't linked an account is stopped at `run_panel_reverse` → `_resolve_email_for_ctx` → `_respond_not_linked` (mirrors `commands.py:2340-2343`). This is intended — `Reply-To` needs the seeker's email — but it means reverse requires a linked account, not just channel access.

## 9. New / changed units

- `mcp-servers/tasks/routes_outreach.py` — `OutreachRequest.direction`; **`OutreachStatusResponse.direction`/`role`/`location`** populated by status, `/candidates`, **PATCH `/candidates/{cid}`**, and `/send` (the PATCH one is required for select/edit re-render); thread `direction` **and `location`** through `start_outreach` → `_run_outreach` → `_process_outreach_find`/`_process_outreach_result`; persist `direction`/`role`/`location` in `result`; direction-aware not-found + 0-selected text; pass `reply_to` on send.
- `mcp-servers/tasks/outreach.py` — `build_outreach_prompt(..., direction)` reverse branch; `format_outreach_summary(..., direction)` direction-aware; `post_outreach_to_n8n(..., reply_to)`. (Candidate model + all selection/edit/send helpers unchanged.)
- `webhook-handler/handlers/recruiting_panel.py` — reverse button + modal builders + parsers (reuse `parse_outreach_modal`; reverse modal MUST reuse the exact `role`/`location`/`jobdesc`/`count` input ids).
- `webhook-handler/handlers/recruiting_review.py` — `kind`-aware copy (title/footer/**placeholder**/button) for company-oriented text.
- `webhook-handler/handlers/discord_commands.py` — route `aiuiout:revfind`/`aiuiout:revmodal`.
- `webhook-handler/handlers/commands.py` — `run_panel_reverse`; `_watch_outreach_review` builder-by-platform; **`run_outreach_select`/`edit_submit`/`send` changed → platform- + direction-aware (resolve builder + labels from the status response)**; Slack → `mode="manual"`.
- `webhook-handler/handlers/slack_recruiting_panel.py` — reverse button + modal + field extraction.
- `webhook-handler/handlers/slack_recruiting_review.py` — **new** Block Kit review builders (mirror `recruiting_review.py`).
- `webhook-handler/handlers/slack_interactions.py` — route reverse entry + the review block actions + edit `view_submission`; build a review-capable Slack `ctx` (`notify_channel_msg` + response-url `edit_message`, with the edit-modal `response_url` stashed in `private_metadata`).
- `webhook-handler/clients/tasks.py` — pass `direction` on `start_outreach` (candidate/patch/send client methods already exist).
- `webhook-handler/clients/slack.py` — **no new method needed**: `post_message(blocks=...)` and `post_to_response_url(replace_original=True, blocks=...)` already exist (`:91-92`, `:232-275`).
- **n8n (live Hostinger instance, via the UI — NOT the repo JSON):** add `Reply-To` to the Gmail node sourced from `reply_to`, and propagate `reply_to` through the "Dedupe and Prepare" Code node's per-item output (today it maps only `date,name,github_url,email,subject,body,status,job_title`) **or** reference `$('Webhook').first().json.body.reply_to`. The repo `n8n-workflows/recruiting-outreach.json` is a `CONFIGURE_IN_UI` template and is **documentation only** — editing it does not change production.
- DB: **no new column, no migration** — `direction`/`role`/`location` live in the existing `TaskItem.result` JSON.

## 10. Testing

- **webhook-handler pure builders:** `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py tests/test_recruiting_review.py tests/test_slack_recruiting.py tests/test_slack_recruiting_review.py`.
- **tasks pure logic** (prompt branch, direction-aware summary/not-found/0-selected text): run via the **webhook venv** (`"../../webhook-handler/.venv/Scripts/python.exe" -m pytest <file>`). **Never** run the full tasks suite (its conftest TRUNCATEs the prod DB).
- **Re-render regression (the gap the review caught):** assert that a reverse-direction `/candidates` (and `/send`) response drives **company-oriented** labels through `run_outreach_select` / `run_outreach_edit_submit` / `run_outreach_send` on BOTH a Discord ctx and a Slack ctx (right builder + right copy on re-render, not just the initial watcher post).
- **Manual e2e:** one live Discord run and one live Slack run in `#recruiting` (Find Jobs → review → edit one → send 1), verified against the n8n execution + the Google Sheet, with `Reply-To` confirmed on the received email.

## 11. Suggested build order

1. **Backend** — `direction` flag + reverse prompt + `reply_to` (+ unit tests). Independently testable.
2. **Discord** — button/modal/`run_panel_reverse`, reusing the review layer. Ships a working vertical slice on its own.
3. **Slack review layer** — the new Block Kit review module + review-capable Slack ctx + routing. Largest chunk; benefits hire as well as reverse.

## 12. Risks (eyes-open, not blockers)

- **Discovery reliability:** finding *which* companies are hiring + a *real* contact email via web search is materially less reliable than GitHub-sourcing engineers. The review step is the mitigation — the user vets every application and recipient before sending.
- **Deliverability / reputation:** cold applications to generic `careers@` inboxes from a shared Gmail can be low-yield and risk the sender's reputation. Keeping the human review gate (both platforms) and `Reply-To = seeker` reduces, not eliminates, this.
- **Slack hire behavior change:** routing Slack through manual review (§7) changes today's Slack auto-send; intended, but worth confirming nobody depends on Slack auto-send.
- **Shared sheet + dedupe set:** hire and reverse both POST to the same `recruiting-outreach` webhook, which dedupes by email against one shared "Outreach" sheet tab. A reverse run reuses the `github_url` column for a careers URL (cosmetic mislabel) and shares the email-dedupe set with hire — collision is unlikely (company contact emails vs engineer emails) but noted. A future split (separate tab / `direction` column) is out of scope for v1.

## 13. Out of scope (YAGNI)

- Per-user Gmail OAuth (send literally *from* the seeker's mailbox).
- LinkedIn / job-board API integrations (web search only for v1).
- A separate reverse channel/panel (it's a second button on the existing panel).
- Tracking replies / interview scheduling.
