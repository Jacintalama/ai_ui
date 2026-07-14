# App Builder: versions + AutoFix + pre-build questions

Date: 2026-07-14
Status: Approved direction (Ralph: "build the 1 and 2 and 3" from
docs/app-builder-feature-research-2026-07-14.md); design grounded in code.

## F1. App version timeline + restore (REUSE the existing git system)

REVISION 2026-07-14: A git-backed version+rollback system ALREADY exists and
is the source of truth - `routes_projects.py` exposes
`GET /api/projects/{slug}/versions` (git log of `apps/<slug>/`) and
`POST /api/projects/{slug}/rollback` (restores a chosen SHA as a NEW commit,
non-destructive), and `preview.html`'s "Version history" tab already renders
this timeline with working rollback. The build agent commits per change, so
the timeline is populated. We do NOT build a second snapshot system.

The real gap: this git system is reachable only by admin/capability auth
(web), not by the bots' owner-scoped `X-User-Email`. So there are NO Discord
or Slack version controls.

Approach: expose the SAME git logic to owner-scoped callers and add bot
surfaces.

- **Shared core:** factor the git list-versions and rollback logic in
  `routes_projects.py` into reusable functions (extract in place, or a small
  `app_git_versions.py`) so both routers call one implementation. No behavior
  change for the existing `/api/projects/*` routes.
- **Owner-scoped API (aiuibuilder router, `current_user` + `_require_owner`,
  the pattern publish uses):**
  - `GET /api/aiuibuilder/{slug}/versions` -> the same version list the
    projects route returns (SHA, message, timestamp, author, current flag).
  - `POST /api/aiuibuilder/{slug}/rollback` body `{sha}` -> same rollback
    core; take the per-slug advisory xact lock (`hashtext("build:<slug>")`,
    as `_create_and_spawn_enhance` does) so a rollback cannot race a live
    build/enhance; 409 while one is live.
- **Web:** already done (`preview.html` version-history tab). No work.
- **Discord My-apps project menu:** new "Versions" button
  (`aiuibuild:versions:<slug>`) -> a select of recent versions
  (`aiuibuild:verpick:<slug>`, value = short SHA) then a confirm card
  (`aiuibuild:rbok:<slug>:<sha>` / `aiuibuild:rbno:`) -> rollback.
- **Slack app row:** "Versions" button -> DM list; each version row a
  Rollback button with a native confirm dialog.
- **Client:** `TasksClient.list_app_versions(email, slug)` (GET the
  aiuibuilder versions route), `rollback_app(email, slug, sha)` (POST the
  aiuibuilder rollback route). Version labels shown to users come from the
  git commit message; the newest/current version has no rollback button.

## F2. AutoFix loop (narrow, real-browser smoke)

After the execute phase completes for an app task, PROVE the app loads
before declaring success, and fix narrowly when it does not.

- **Smoke (`app_smoke.py`, tasks service):** headless Playwright (already
  in the image) loads the app's internal preview URL, waits ~2.5s, and
  collects: non-200 response, `pageerror` exceptions, `console.error`
  messages, and failed resource loads. Returns a compact error report
  (deduped, max ~10 lines) or None when clean.
- **Fix pass:** new `build_autofix_prompt(slug, errors)` in
  claude_executor: "The app fails its load check with EXACTLY these
  errors... fix ONLY these errors with the smallest possible change; do not
  redesign, restyle, or refactor anything else." Run via the existing
  claude subprocess.
- **Loop:** smoke -> if errors, autofix pass -> re-smoke, at most 2 fix
  passes. Wired into `_run_execution` after execute-completed (before the
  existing verify step; applies when the task has a slug). Log sections
  `--- AUTOFIX 1/2 ---` appended to the execution log. If still broken
  after 2 passes, proceed to the existing failure/verify handling but
  include the smoke errors in the user-facing result so the failure is
  concrete.
- Smoke unavailability (Playwright error, preview route down) fails OPEN:
  skip AutoFix, never block a build on the checker itself.

## F3. Pre-build clarifying questions (structured, capped, skippable)

Before scaffolding a NON-template build (blank/custom description), the
agent may ask up to 3 short multiple-choice questions, rendered as buttons
on every surface. One round only.

- **Question pass:** new `build_prebuild_questions_prompt(description)`:
  single non-tool completion instructing: reply `NO_QUESTIONS` when the
  brief is clear; otherwise emit JSON `{questions: [{q, options: [2..4
  short strings]}]}` (max 3). Runs before the plan/execute phases for
  panel-initiated blank builds only (template builds skip it).
- **State:** reuses the existing paused-build seam: task ->
  `awaiting_input`, structured questions stored on the task
  (`questions_json` column, additive migration), `BuildStatusResponse`
  gains `questions: [{q, options}] | null` beside the existing free-text
  `question`.
- **Answering:** existing `POST /build/{task_id}/answer` accepts
  `{answers: [str, ...]}` as well as the current free-text `{answer}`.
  Answers are appended to the build description ("Choices: q -> a; ...")
  and the build resumes through the existing resume path.
- **Surfaces:** web build form shows the questions as option buttons with a
  "Just build it" skip; Discord posts one message per question with option
  buttons (`aiuibuild:qopt:<task_id>:<qi>:<oi>`) plus a Skip-all button;
  Slack DM blocks the same. Skip (or 10 minutes without an answer, enforced
  by a check in the existing scheduler tick) proceeds with the agent's own
  defaults and says so.
- Never re-asks: one round per build; the mid-build stuck-question flow
  from Jul 13 is unchanged and separate.

## Error handling and safety

- Restore refuses (409) while the slug has a live build/enhance; snapshots
  are pruned oldest-first, never the current state.
- AutoFix passes are capped (2) and narrow by prompt; the loop can only
  reduce user-visible failures, never spin unbounded.
- Question JSON that fails to parse -> treated as NO_QUESTIONS (build
  proceeds normally).

## Testing

- versions: manifest round-trip, prune-at-10, restore-creates-new-entry,
  409-while-live, route registration; panel builders for Discord/Slack.
- autofix: prompt content, loop caps (mocked smoke/subprocess: clean run
  skips, 1-error run fixes once, persistent error stops at 2), fail-open.
- questions: prompt pass parsing (NO_QUESTIONS, valid JSON, garbage),
  answer endpoint accepting both shapes, timeout auto-proceed, surface
  builders (buttons/blocks with skip).

Deploy: tasks service (orchestrator or tar+rebuild) + webhook-handler
(tar+rebuild) + web static; verify live with a real blank build (questions
appear, answer, build completes, version listed, restore works) and a
deliberately broken enhance (AutoFix repairs or reports concretely).
