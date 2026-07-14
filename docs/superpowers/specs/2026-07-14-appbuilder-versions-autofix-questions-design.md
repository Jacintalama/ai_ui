# App Builder: versions + AutoFix + pre-build questions

Date: 2026-07-14
Status: Approved direction (Ralph: "build the 1 and 2 and 3" from
docs/app-builder-feature-research-2026-07-14.md); design grounded in code.

## F1. App version timeline + restore

Every successful build, enhance, or restore snapshots the app so users can
always go back. Restore is never destructive (Lovable model): restoring v2
creates v5 whose content equals v2.

- **Snapshot hook:** in `routes_execution._run_execution`, when an app task
  reaches `completed` and has a `slug`, copy `APPS_DIR/<slug>/` into
  `APPS_DIR/<slug>/.versions/v<N>/` (excluding `.versions`, `.video`,
  `node_modules`, attachments dirs). Manifest at
  `.versions/manifest.json`: list of `{no, created_at, kind:
  build|enhance|restore, label}` where label is the first 80 chars of the
  triggering description. Keep the newest 10 snapshots; prune older.
- **API (routes_aiuibuilder, owner-scoped like publish):**
  - `GET /{slug}/versions` -> `{versions: [{no, created_at, kind, label}]}`
    (newest first).
  - `POST /{slug}/restore` body `{version_no}` -> snapshots the CURRENT
    state first (kind=restore label "before restore to vN"), then copies
    `v<N>` over the live app dir, appends a new manifest entry, returns the
    updated list. 409 while a build/enhance for the slug is live.
- **Surfaces:**
  - Web `preview.html`: a Versions side panel (list + Restore button each,
    confirm dialog, preview iframe reload after restore).
  - Discord My-apps project menu: new "Versions" button
    (`aiuibuild:versions:<slug>`) -> ephemeral list with per-version restore
    buttons (`aiuibuild:restore:<slug>:<no>`, confirm card first).
  - Slack app row: "Versions" button -> DM list with restore buttons
    (native confirm dialogs).
- **Client:** `TasksClient.list_app_versions(email, slug)`,
  `restore_app_version(email, slug, version_no)`.

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
