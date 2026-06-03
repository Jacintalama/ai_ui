# Apps List: Preview + Delete, and a Separate Builder Thread — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) Give the Discord App Builder its OWN private thread, separate from the cron "schedules" thread. (2) Add **Preview** (open) and **Delete** (with confirm) to the "My apps" list on both Slack and Discord.

**Architecture:** Tasks service gets a new `builder_thread_id` column + GET/POST endpoint (mirrors the existing `schedules_thread_id` ones) and a user-scoped owner-checked delete endpoint (refactors the existing admin cascade into a shared core). The webhook-handler adds client methods and wires the bot handlers: App Builder uses the builder thread; apps lists gain a Preview link button and a Delete button (Slack uses Block Kit's native `confirm` dialog; Discord uses the existing token confirm-card pattern).

**Tech Stack:** Python, FastAPI + SQLAlchemy + asyncpg (tasks service), pytest, Discord interactions, Slack Block Kit.

**Approved decisions (brainstorm):** separate builder thread; Preview + Delete on BOTH platforms; Delete requires confirm.

---

## File Structure

| File | Change |
|---|---|
| `mcp-servers/tasks/migrations/017_discord_link_builder_thread.sql` (new) | `ALTER TABLE tasks.discord_links ADD COLUMN IF NOT EXISTS builder_thread_id text;` |
| `mcp-servers/tasks/models.py` (DiscordLink ~141-155) | add `builder_thread_id = Column(Text, nullable=True)` |
| `mcp-servers/tasks/routes_discord_links.py` (~110-131) | add GET/POST `/{discord_id}/builder-thread` mirroring the schedules-thread endpoints |
| `mcp-servers/tasks/routes_projects.py` (~1217, ~1244) | extract a shared `_delete_slug(s, slug, email, *, is_admin)` core from the admin `delete_project`; keep admin route using it |
| `mcp-servers/tasks/routes_aiuibuilder.py` (~451) | add user-scoped owner-checked `DELETE /{slug}/app` reusing `_delete_slug(..., is_admin=False)` |
| `webhook-handler/clients/tasks.py` (~167-214) | add `get_user_builder_thread`/`set_user_builder_thread` + `delete_app(email, slug)` |
| `webhook-handler/handlers/app_builder_panel.py` | Discord: Preview link + Delete button (+ delete-confirm card) ids/builders for the apps menu |
| `webhook-handler/handlers/discord_commands.py` | use builder thread for `_handle_build_new`/`_handle_my_apps`; delete-confirm/cancel + do-delete handlers |
| `webhook-handler/handlers/slack_app_builder_panel.py` | `build_apps_list_blocks`: add Preview (url) + Delete (native `confirm`) per row |
| `webhook-handler/handlers/slack_interactions.py` | delete action handler |
| Tests | tasks-service endpoint tests; webhook-handler builder-thread + delete + preview tests |

**Patterns to mirror (from investigation):**
- Migration: raw idempotent SQL, auto-run at startup (`db.py:_run_migrations`). Use `ADD COLUMN IF NOT EXISTS`.
- Builder-thread endpoints: copy `routes_discord_links.py` `get_thread`/`set_thread` (~113-131), swap `schedules_thread_id`→`builder_thread_id`.
- Delete core: admin `delete_project` (`routes_projects.py:1244-1272`) already cascades DB + `shutil.rmtree(apps/<slug>)`. Refactor into `_delete_slug(s, slug, email, *, is_admin)` with the `_require_role(..., "owner", is_admin=...)` ownership check (like `_unpublish_slug` at :1217).
- Discord confirm: `build_confirm_components(token)` + `SCHED_CONFIRM_PREFIX`/`SCHED_CANCEL_PREFIX` (app_builder_panel.py ~491). Add an analogous `aiuibuild:del-confirm:`/`aiuibuild:del-cancel:` pair.
- Slack confirm: native `confirm` object on the button element (no handler needed for the dialog).
- Preview URL: draft → `https://{tasks_public_url-or-domain}/tasks/preview-app/{slug}/`; published → `public_url` (already in `list_projects` output) i.e. `https://{slug}.{domain}/`.

---

## Task 1: Tasks service — `builder_thread_id` column + endpoints

**Files:** new `migrations/017_discord_link_builder_thread.sql`; modify `models.py`; modify `routes_discord_links.py`; test `mcp-servers/tasks/tests/` (mirror existing discord-links thread test if present).

- [ ] **Step 1: Write failing test** for the new endpoints (mirror the existing schedules-thread test; GET returns None initially, POST sets it, GET returns it). Run from the tasks service test dir. If no test harness exists for these routes, add a minimal one mirroring the closest existing route test.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - Add `migrations/017_discord_link_builder_thread.sql`:
    ```sql
    ALTER TABLE tasks.discord_links ADD COLUMN IF NOT EXISTS builder_thread_id text;
    ```
  - `models.py` DiscordLink: add `builder_thread_id = Column(Text, nullable=True)`.
  - `routes_discord_links.py`: add (mirroring `get_thread`/`set_thread`):
    ```python
    @router.get("/{discord_id}/builder-thread")
    async def get_builder_thread(discord_id: str, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
        _require_internal(x_internal_secret)
        async with session() as s:
            link = (await s.execute(select(DiscordLink).where(DiscordLink.discord_id == discord_id))).scalar_one_or_none()
        return {"thread_id": link.builder_thread_id if link else None}

    @router.post("/{discord_id}/builder-thread")
    async def set_builder_thread(discord_id: str, body: ThreadIn, x_internal_secret: str = Header(default="")) -> dict[str, Any]:
        _require_internal(x_internal_secret)
        async with session() as s:
            link = (await s.execute(select(DiscordLink).where(DiscordLink.discord_id == discord_id))).scalar_one_or_none()
            if link is None:
                raise HTTPException(status_code=404, detail="link not found")
            link.builder_thread_id = body.thread_id
            await s.commit()
        return {"ok": True}
    ```
    (match the exact param/model names the existing endpoints use — `ThreadIn`, `_require_internal`.)
- [ ] **Step 4: Run tests, verify pass.** Confirm the migration file is idempotent.
- [ ] **Step 5: Commit** `feat(tasks): builder_thread_id column + /discord-links builder-thread endpoints`

---

## Task 2: Tasks service — user-scoped owner delete endpoint

**Files:** modify `routes_projects.py` (extract `_delete_slug`), `routes_aiuibuilder.py` (add user route); test in `mcp-servers/tasks/tests/`.

- [ ] **Step 1: Write failing test** — owner can delete their built app (DB rows + dir gone); non-owner/member gets 403; unknown slug behaves like the existing delete. Mirror the existing publish/unpublish access-gate test (`test_publish_access_gate.py`).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - In `routes_projects.py`, extract the body of admin `delete_project` (lines ~1244-1272) into:
    ```python
    async def _delete_slug(s, slug: str, email: str, *, is_admin: bool) -> None:
        _validate_slug(slug)
        if not is_admin:
            if not await _user_can_see_project(s, slug, email):
                raise HTTPException(status_code=403, detail="Not a member of this project")
            await _require_role(s, slug, email, "owner", is_admin=False)
        # ... existing cascade deletes (TaskItem, ChatMessage, ProjectSupabase, PublishedApp, ProjectMember) + commit + shutil.rmtree(apps/<slug>) ...
    ```
    Keep `delete_project` (admin route) calling `_delete_slug(s, slug, user.email, is_admin=True)`.
  - In `routes_aiuibuilder.py`, add (mirror `unpublish_built_app`):
    ```python
    @router.delete("/{slug}/app", status_code=204)
    async def delete_built_app(slug: str, user: CurrentUser = Depends(current_user)):
        """User-scoped owner-only hard delete of a Discord/Slack-built app."""
        _validate_slug(slug)
        async with session() as s:
            await _delete_slug(s, slug, user.email, is_admin=False)
        return None
    ```
    (import `_delete_slug` alongside the existing `_unpublish_slug` import.)
- [ ] **Step 4: Run tests, verify pass** (incl. existing publish/unpublish tests unaffected).
- [ ] **Step 5: Commit** `feat(tasks): user-scoped owner delete endpoint for built apps`

---

## Task 3: webhook-handler client — builder-thread + delete methods

**Files:** modify `webhook-handler/clients/tasks.py`; test `webhook-handler/tests/` (mirror existing tasks-client tests with respx).

- [ ] **Step 1: Write failing tests** (respx): `get_user_builder_thread` GETs `/discord-links/{id}/builder-thread`; `set_user_builder_thread` POSTs it; `delete_app(email, slug)` issues `DELETE /{slug}/app` with the user-email header and returns True on 204.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (mirror `get_user_thread`/`set_user_thread` at :167 and `unpublish_app` at :214):
    ```python
    async def get_user_builder_thread(self, discord_id: str) -> str | None:
        resp = await self._internal_request("GET", f"/discord-links/{discord_id}/builder-thread")
        return resp.json().get("thread_id")

    async def set_user_builder_thread(self, discord_id: str, thread_id: str) -> bool:
        await self._internal_request("POST", f"/discord-links/{discord_id}/builder-thread", json={"thread_id": thread_id})
        return True

    async def delete_app(self, user_email: str, slug: str) -> bool:
        # mirror unpublish_app: user-scoped DELETE with X-User-Email
        ...
    ```
    Match how `unpublish_app` builds its request (path, headers/user-email, success check).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(webhook): tasks client builder-thread + delete_app methods`

---

## Task 4: webhook-handler router — builder-thread accessors

**Files:** modify `webhook-handler/handlers/commands.py` (add `get_user_builder_thread`/`set_user_builder_thread` passthroughs next to the existing `get_user_thread`/`set_user_thread` at ~1840); test in `webhook-handler/tests/`.

- [ ] **Step 1: Write failing test** that `CommandRouter.get_user_builder_thread`/`set_user_builder_thread` delegate to `_tasks_client`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the two thin passthroughs (mirror existing).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(webhook): router builder-thread accessors`

---

## Task 5: Discord — App Builder uses the builder thread (not schedules)

**Files:** modify `webhook-handler/handlers/discord_commands.py` (`_get_or_make_thread` + the two app-builder handlers); test `tests/test_two_button_entry.py`.

- [ ] **Step 1: Write failing test** — clicking "Build an app" / "My apps" uses `router.get_user_builder_thread`/`set_user_builder_thread` (NOT `get_user_thread`), and `_handle_sched_open` STILL uses `get_user_thread` (the schedules one). Assert the two flows resolve different thread accessors.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — parametrize `_get_or_make_thread(user_id, channel_id, user_name, *, kind)` where `kind="builder"` uses `get_user_builder_thread`/`set_user_builder_thread` and names new threads `aiui-apps-{user_name}`, while `kind="schedules"` keeps the existing `get_user_thread`/`set_user_thread` + `schedules-{user_name}` name. `_handle_build_new`/`_handle_my_apps` pass `kind="builder"`; `_handle_sched_open` passes `kind="schedules"`. (This also reverts the earlier cosmetic rename so schedules threads are `schedules-` again.)
- [ ] **Step 4: Run, verify pass** (full suite — schedules tests must stay green).
- [ ] **Step 5: Commit** `fix(discord): App Builder uses its own thread, separate from cron schedules`

---

## Task 6: Discord — Preview + Delete (with confirm) in the apps menu

**Files:** modify `app_builder_panel.py` (Preview link + Delete button + `build_delete_confirm_components`; ids `aiuibuild:del:`, `aiuibuild:del-confirm:`, `aiuibuild:del-cancel:` + predicates), `discord_commands.py` (delete / confirm / cancel handlers); tests.

- [ ] **Step 1: Write failing tests** — the per-app actions include a Preview link button (url = published `public_url` or draft preview url) and a Delete button (`aiuibuild:del:<slug>`); clicking Delete renders a confirm card (`build_delete_confirm_components(slug)`); confirm → `router.delete_app(email, slug)` called; cancel → no delete.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — add the Preview link + Delete button to the app-action components (find where a selected app's actions are rendered — `build_project_menu_components` ~338, used by the app-select handler). Add confirm-card builder + `is_app_delete`/`is_del_confirm`/`is_del_cancel` predicates + `slug_from_*`. Wire handlers: delete→show confirm; del-confirm→`_resolve_email`+`delete_app`+success msg; del-cancel→dismiss. Preview is a link button (no handler). Owner-only: rely on the endpoint's 403 + show a friendly message.
- [ ] **Step 4: Run, verify pass** (full suite).
- [ ] **Step 5: Commit** `feat(discord): Preview + Delete (confirm) in My apps`

---

## Task 7: Slack — Preview + Delete (native confirm) in apps list

**Files:** modify `slack_app_builder_panel.py` (`build_apps_list_blocks` rows), `slack_interactions.py` (delete handler); tests `tests/test_slack_panel.py` + `tests/test_two_button_entry.py`.

- [ ] **Step 1: Write failing tests** — each row in `build_apps_list_blocks` includes a Preview link button (`"url"` = published public_url or draft preview url) and a Delete button carrying `DELETE_PREFIX+slug` with a Block Kit `confirm` object; `_handle_block_actions` routes the delete action → `_tasks_client.delete_app(email, slug)` and reports back in the DM.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
  - `build_apps_list_blocks`: for each app compute `open_url = app.get("public_url") if app.get("published") else f"{settings.tasks_public_url.rstrip('/')}/tasks/preview-app/{slug}/"`; add a link button `{"type":"button","text":{...,"text":"Preview"},"url":open_url}` and a Delete button with a `confirm` object (title "Delete app?", text "This permanently deletes <name>. No undo.", confirm "Delete", deny "Cancel"), action_id `f"{DELETE_PREFIX}{slug}"`. Add a `DELETE_PREFIX = "aiuibuild:del:"` constant.
  - `slack_interactions.py`: in `_handle_block_actions`, add a `DELETE_PREFIX` branch (mirror the existing `_do_publish`/`_do_unpublish` action dispatch loop): resolve email via `_email_for`, `await self.router._tasks_client.delete_app(email, slug)`, then post a confirmation (and ideally re-render the list). Background-task tracked.
- [ ] **Step 4: Run, verify pass** (full suite).
- [ ] **Step 5: Commit** `feat(slack): Preview + Delete (confirm) in My apps`

---

## Task 8: Full-suite regression + manual deploy notes

- [ ] Run full suites: `cd webhook-handler && python -m pytest -q` AND the tasks-service tests (`cd mcp-servers/tasks && python -m pytest -q` if a harness exists).
- [ ] Final code review across the whole diff.
- [ ] **Deploy (after approval):** deploy `tasks` (migration auto-runs at startup → adds `builder_thread_id`; restart applies the new endpoints + delete route) AND `webhook-handler` (4+ handler files + clients/tasks.py). Re-pin not needed (button payloads change only inside the My-apps list, which is posted per-click). Merge to `main` so redeploys keep it.

---

## Risks / notes
- **Delete is destructive and irreversible** (cascades DB + removes `apps/<slug>` dir). The confirm step is mandatory; owner-only enforced server-side (403 otherwise).
- Migration runs on EVERY tasks-service startup and is idempotent (`ADD COLUMN IF NOT EXISTS`) — safe to deploy by restart.
- Task 5 reverts the earlier cosmetic thread rename so cron schedules threads are `schedules-<user>` again and App Builder gets `aiui-apps-<user>`.
