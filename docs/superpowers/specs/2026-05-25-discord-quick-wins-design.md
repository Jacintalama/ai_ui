# Discord Bot Quick Wins — Design Spec

**Date:** 2026-05-25
**Status:** Approved (brainstorm) → implementing
**Builds on:** the Schedules feature (`feat/discord-schedules`)

Three code features + one no-code setting. Goal: remove the linking bottleneck and polish Schedules. All webhook-handler code is TDD'd green; tasks-service code is compile-checked (runs on deploy).

---

## #2 (no code) — Bot "Manage Messages" permission

Documented only. In Discord: Server Settings → Roles → bot role → enable **Manage Messages** (or per-channel on #app-builder). Then the bot can pin its panels. No implementation.

---

## #1 — Self-service linking (admin-approve)

The webhook-handler stays **DB-free**; the link store lives in the **tasks DB**.

### Data — `tasks.discord_links` (migration 015)
`discord_id text PRIMARY KEY, discord_username text, email text, status text ('pending'|'approved'|'rejected'), requested_at timestamptz, decided_at timestamptz, decided_by text`. One row per Discord user (re-request upserts to pending). The approve/reject buttons key off `discord_id`.

### tasks endpoints — `routes_discord_links.py` (auth: `X-Internal-Secret == INTERNAL_CALLBACK_SECRET`)
- `POST /discord-links/request` `{discord_id, discord_username, email}` → upsert pending → `{status:"pending"}`
- `POST /discord-links/{discord_id}/approve` `{decided_by}` → approved → `{email}`
- `POST /discord-links/{discord_id}/reject` `{decided_by}` → rejected → `{status:"rejected"}`
- `GET /discord-links/resolve/{discord_id}` → `{email: <str|null>}` (email only when approved)

These are **system** calls (not user-scoped), so they use the internal secret, NOT `X-User-Email`.

### TasksClient (internal-secret path, separate from the `X-User-Email`-only path)
`request_link`, `approve_link`, `reject_link`, `resolve_link` — send `X-Internal-Secret` (from `settings.internal_callback_secret`). Documented as the system-call exception to the "only X-User-Email" rule (different endpoints; doesn't touch `/schedules` operator-mode).

### Router resolution
`async def _resolve_email(self, discord_id) -> str | None`: env map first (`self._discord_user_email_map.get`), else `TasksClient.resolve_link`. Replaces all 11 inline `_discord_user_email_map.get(ctx.user_id)` sites in `commands.py`. Env-mapped users short-circuit (no HTTP).

### Discord UI (`aiuilink:*` family)
- **🔗 Link my account** button on the Schedules panel → `aiuilink:start`.
- Click → modal (`aiuilink:modal`, field `email`).
- Submit → validate email → `router.request_link(...)` → bot posts to the **admin channel** (`DISCORD_ALERT_CHANNEL_ID`): *"🔗 @user → alice@x.com [✅ Approve] [✖ Reject]"* (`aiuilink:approve:<discord_id>` / `aiuilink:reject:<discord_id>`) → ephemeral *"Request sent."*
- Admin **Approve** → `router.approve_link` → edit admin msg "✅ Approved". **Reject** → "✖ Rejected". (Trust: the admin channel is access-restricted; whoever can click is an admin.)

---

## #3 — Schedule failure alert + retry

- `tasks/scheduler._deliver_to_discord(...)` gains a `schedule_id` arg.
- `POST /internal/schedule-result`: `ScheduleResultIn` gains `schedule_id: str = ""`. When status ∉ {completed, skipped}, attach a **🔁 Retry** button via a new pure builder `build_retry_components(schedule_id)` → custom_id `aiuisched:run:<id>` (reuses the existing run handler — no new routing).
- `_format_schedule_result` already shows ⚠️ for non-completed.

---

## #4 — Edit a schedule

- **My schedules** rows gain an **✏️ Edit** button (`aiuisched:edit:<id>`) → row buttons become Run / Pause-or-Resume / Edit / Delete (≤5, ok).
- Edit click → handler fetches the schedule (via `list_schedules` + find by id), splits its `name` (`"<when-English>: <what>"`) on the first `": "`, opens a modal (`aiuisched:editmodal:<id>`) **pre-filled** with current `what` + `when`. The English the parser emits round-trips back through `parse_when`, so pre-fill works.
- Editmodal submit → `parse_when` → `router.run_schedule_edit(ctx, id, what, when)` → `TasksClient.update_schedule(id, name, cron, prompt)` → ephemeral ack.
- tasks: `PATCH /schedules/{id}` `{name?, cron_expr?, prompt?}` (ownership-scoped, validates cron). `TasksClient.update_schedule`.

---

## Testing

webhook-handler (TDD, all green): `_resolve_email` (env hit / DB hit / none); link builders + modal + approve/reject routing; the link request/approve/reject router methods; retry-button builder + delivery endpoint attaching it on failure; edit button in the list + editmodal prefill split + `run_schedule_edit`; TasksClient internal-secret methods + `update_schedule` (respx, assert correct headers). tasks side: compile-checked.

## Honest scope

webhook-handler fully TDD'd; tasks migration 015 + endpoints + PATCH written + compile-checked, verified on deploy. Live Discord smoke (clicking Link → admin Approve → use a feature; Edit; failed-run Retry) needs a deploy.
