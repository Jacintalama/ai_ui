# App Builder — faithful initial prompt + resume-from-previous-point (all surfaces)

Date: 2026-07-13
Status: approved (scope confirmed by Jacint)
Branch: `feat/build-prompt-resume-fixes`

## Problem

Two reported bugs in the App Builder ("build") feature, confirmed by a full read of the
webhook-handler bot flow, the tasks build engine, and the browser UI.

### Bug 1 — the initial build prompt is not shown faithfully

The user's prompt is captured on every surface, but it is stored *wrapped* inside
`TaskItem.description`:

```
{slug directive}{template rules}\n\nUSER REQUEST:\n{what the user typed}
```

There is no clean copy of the prompt anywhere, so each surface re-derives it and three get
it wrong:

- **Editor / preview page never shows it.** The build overlay has no element bound to the
  prompt, and the transcript rebuilder filters the original build task out
  (`static/preview.html:7075-7076`). `loadChatHistory` only replays `ChatMessage` rows,
  which never contain the build prompt.
- **After the first enhancement the gallery card leaks internal text.** Enhance tasks reuse
  the slug and are created as `description="Enhance apps/<slug>/: <text>"`. The gallery
  dedupes by slug keeping the newest task, and the enhance description has no
  `USER REQUEST:` marker, so `lastIndexOf("USER REQUEST:")` returns -1 and the card renders
  the raw `Enhance apps/<slug>/: ...` string (`static/projects.html:1270`, `1300-1303`).
- **Bots echo a mangled fragment.** Discord/Slack/Voice show only
  `friendly_name(description)`, which truncates at the first comma and drops a leading
  article (`handlers/commands.py:67-88`) — "A CRM, a dashboard, and booking for my clinic"
  is echoed as "CRM". The verbatim prompt is echoed nowhere.

### Bug 2 — resuming to a previous point

Web reopen/answer plumbing mostly works (`preview.html?task=<id>`, NEEDS_INPUT answer panel,
DB-backed transcript). The breakages:

- Resume drifts to the newest task (an enhancement) and never re-surfaces the original
  request (same root cause as Bug 1).
- A one-shot build that pauses for input loses earlier context on resume — the one-shot
  branch replays only the last answer, not the conversation, and never tells the agent a
  partial app already exists (`routes_tasks.py:687-701`).
- A `pending` build that already has an execution can hang on "building…" forever — the
  overlay auto-starts only when there are zero executions (`static/preview.html:3183-3204`).
- A template picked from the standalone gallery is silently dropped — `projects.html` never
  reads `#template=<key>` from the URL.
- **On Discord / Slack / Voice, a build that asks a question is a hard dead-end** — there is
  no answer-and-continue path at all (`routes_aiuibuilder.py:144-160`; no `answer_build`
  client method).

## Scope (confirmed)

- Resume: **all surfaces including Voice** — fix the web resume bugs AND wire an
  answer-and-resume path for Discord, Slack, and Voice, with persisted last-build state.
- OWUI nuggets: **defer + document** — the v0.10.2 build-relevant features (native tool /
  Model, Artifacts inline preview, Knowledge-Base RAG, native automations) are separate
  architectural projects. Capture as a ranked doc; do not build now.

## Design

### A. One canonical clean prompt (server)

- New helper `clean_user_prompt(description)` (new module `mcp-servers/tasks/prompt_utils.py`):
  - if `"USER REQUEST:\n"` present → text after the **last** marker, stripped;
  - elif `startswith("Enhance apps/")` → text after the first `": "`, stripped;
  - else → `description.strip()`.
- Add computed `user_prompt` to `TaskOut` (set in the TaskItem→TaskOut serializer so
  `GET /api/tasks/{id}`, list, and history all carry it).
- Add `user_prompt` to `BuildStatusResponse` (`routes_aiuibuilder.py`) so bots/voice can show it.
- Persist the initial prompt as the first `ChatMessage(role="user")` at build-create time
  (`create_task` for web; `_create_and_spawn_build` for Discord/Slack/Voice), guarded to
  BUILD + known slug + user_email, idempotent (skip if a user-role message already exists).

### B. Show the prompt where it is missing

- `projects.html`: render `t.user_prompt`; when deduping by slug keep the newest task for
  status/preview but source the card's prompt from the **original build** task's
  `user_prompt` (earliest BUILD for the slug that is not an "Enhance apps/" task).
- `preview.html`: add a "Your request" line in the build overlay bound to `task.user_prompt`;
  render the initial prompt as the first transcript bubble; make the completed-build path
  render the prompt deterministically (fix the loadEnhanceHistory/loadChatHistory clobber
  race so the prompt is not lost).
- webhook-handler `_start_build`: echo the **verbatim** user description in the ACK (the bot
  already has it locally), alongside the short friendly title; truncate for the platform
  message limit but show the full ask. Voice ACK speaks a speech-friendly echo.

### C. Web resume correctness

- `routes_tasks.py /answer` one-shot branch and `routes_execution.py /execute` from
  `awaiting_input` share a single resume-prompt builder that replays the full
  `conversation_history` and injects a "a partial app already exists at apps/<slug>/,
  continue it, do not restart" instruction. Neither path may drop the answer/context.
- `preview.html`: when status is `pending` with existing executions, reveal a working Start
  (or auto-kick) instead of hanging.
- `projects.html`: read `#template=<key>` / `?template=<key>` on load and pre-select it.

### D. Answer-and-resume for Discord, Slack, Voice (new)

- Tasks side: `BuildStatusResponse` gains `question` (the pending ask) when the build is
  awaiting input. New user-scoped endpoint `POST /api/aiuibuilder/build/{task_id}/answer`
  `{answer}` that calls the same resume logic as the web `/answer` (authorized the same way
  as build start, not admin-only). A build in `awaiting_input` is resumable, not terminal.
- webhook-handler: `clients/tasks.py.answer_build(task_id, answer, ...)`.
  - Discord: on `needs_input`, post the question into the user's private build thread and arm
    `_pending_build_answer[uid]=task_id` (StateStore-backed); the next thread reply calls
    `answer_build` and re-spawns the watcher. No more dead-end.
  - Slack: on `needs_input`, post the question with an "Answer" button → modal → `answer_build`
    → re-spawn watcher (Slack builds run in DM; a modal is the reliable affordance).
  - Voice: `build_status` speaks the question; a new voice tool `answer_build` (added in
    `scripts/setup_voice_agent.py`) accepts a spoken answer and resumes; `_last_voice_build`
    moves from an in-memory dict to StateStore so it survives a restart.

## Non-goals / known limitations (documented, not fixed here)

- OWUI native features (deferred; see `docs/owui-v0.10-build-nuggets.md`).
- Invited project members see an empty chat thread (chat is per-(slug, user_email)).
- Remote executor does not rsync partial work back on NEEDS_INPUT (prod uses the local
  executor; verify and note).

## Testing

- tasks unit: `clean_user_prompt` (all three shapes + user text that itself contains
  "USER REQUEST:"), `TaskOut.user_prompt` present, initial `ChatMessage` persisted on create,
  one-shot answer replays history + continue-existing-app instruction, `/execute` from
  `awaiting_input` carries context, new `POST /build/{id}/answer`, `BuildStatusResponse.question`.
- webhook-handler: ACK echoes verbatim prompt (Discord/Slack/Voice), `needs_input` arms the
  answer path, thread reply → `answer_build` + watcher re-spawn, Slack answer modal, voice
  `answer_build` tool, StateStore-backed voice last-build.
- Web UI endpoints covered by backend tests; JS behaviours verified by live e2e.
- All four suites green (webhook-handler, tasks local, tasks in-container vs `aiui_test`,
  video-remotion) + a live e2e on the box: create a build, confirm `user_prompt` is returned
  and shown, drive a NEEDS_INPUT answer-resume end to end.

## Rollout

Commit on `feat/build-prompt-resume-fixes`; make all suites green locally + in-container;
deploy tasks + webhook-handler to Hetzner per CLAUDE.md (scp per-file + rebuild), run the live
e2e, bump `.deploy-state`. Re-run the ElevenLabs voice agent setup script to register the new
`answer_build` tool.
