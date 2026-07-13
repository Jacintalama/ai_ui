# App Builder Prompt + Resume Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the user's real build prompt faithfully on every surface, and make a paused build resumable from Discord, Slack, Voice, and the web.

**Architecture:** One server-side helper recovers the clean prompt from the wrapped `description`; it feeds a new `user_prompt` API field and a first persisted chat message. A single resume-prompt builder replays conversation context for one-shot builds. A new user-scoped `answer` endpoint plus a `TasksClient.answer_build` method turns the bot/voice NEEDS_INPUT dead-end into an answer-and-continue loop.

**Tech Stack:** FastAPI + SQLAlchemy async (tasks service), pytest, vanilla JS/HTML (App Builder UI), Discord/Slack/ElevenLabs handlers (webhook-handler), httpx.

**Spec:** `docs/superpowers/specs/2026-07-13-build-prompt-resume-fixes-design.md`

**Test tiers (from CLAUDE.md / memory):**
- webhook-handler: `cd webhook-handler && python -m pytest tests/ -q`
- tasks local (non-DB): `cd mcp-servers/tasks && AIUI_FERNET_KEY=<any> python -m pytest tests/ -q`
- tasks in-container vs `aiui_test`: on the box, `docker exec -e AIUI_TEST_DB=1 -e DATABASE_URL="$TEST_DSN" -w /app tasks python -m pytest tests/ -q` (DSN = container DATABASE_URL with `s|/openwebui$|/aiui_test|` anchored)
- video-remotion: unaffected; run once at the end to confirm still green.

**Rule:** never edit local `mcp-servers/tasks/templates.py` for deploy (server copy is ahead). Reading is fine.

---

## Phase 1 — Server: one canonical clean prompt

### Task 1.1: `clean_user_prompt` helper

**Files:**
- Create: `mcp-servers/tasks/prompt_utils.py`
- Test: `mcp-servers/tasks/tests/test_prompt_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_prompt_utils.py
from prompt_utils import clean_user_prompt


def test_unwraps_user_request_block():
    d = 'PROJECT NAME: "x".\n<rules text>\n\nUSER REQUEST:\nA CRM, a dashboard, and booking'
    assert clean_user_prompt(d) == "A CRM, a dashboard, and booking"


def test_uses_first_marker_so_user_text_may_contain_it():
    d = "<rules>\n\nUSER REQUEST:\nmake a page titled USER REQUEST: history"
    assert clean_user_prompt(d) == "make a page titled USER REQUEST: history"


def test_enhance_prefix_stripped():
    assert clean_user_prompt("Enhance apps/shop-a1/: add a gallery") == "add a gallery"


def test_plain_description_untouched():
    assert clean_user_prompt("just build a todo list") == "just build a todo list"


def test_empty_and_none():
    assert clean_user_prompt("") == ""
    assert clean_user_prompt(None) == ""
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: prompt_utils`)

Run: `cd mcp-servers/tasks && AIUI_FERNET_KEY=t python -m pytest tests/test_prompt_utils.py -q`

- [ ] **Step 3: Implement**

```python
# mcp-servers/tasks/prompt_utils.py
"""Recover the user's original prompt from a stored task description.

`create_task` wraps a build prompt as "<rules>\n\nUSER REQUEST:\n<prompt>";
`enhance` stores "Enhance apps/<slug>/: <prompt>". Anything else is already clean.
The structural marker is the FIRST occurrence (the rules block, which is
server-controlled, never contains it), so a user whose own text contains
"USER REQUEST:" is preserved.
"""
from __future__ import annotations

_MARKER = "\n\nUSER REQUEST:\n"


def clean_user_prompt(description: str | None) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    idx = text.find(_MARKER)
    if idx != -1:
        return text[idx + len(_MARKER):].strip()
    if text.startswith("Enhance apps/"):
        _, sep, rest = text.partition(": ")
        if sep:
            return rest.strip() or text
    return text
```

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat(tasks): clean_user_prompt helper recovers the user's real prompt"`

---

### Task 1.2: `user_prompt` on `TaskOut`

**Files:**
- Modify: `mcp-servers/tasks/schemas.py` (add `user_prompt: str = ""` to `TaskOut`)
- Modify: the TaskItem→TaskOut serializer (find it: grep `TaskOut(` / `TaskOut.model_validate` / `_task_out` in `mcp-servers/tasks/routes_tasks.py`)
- Test: `mcp-servers/tasks/tests/test_task_out_user_prompt.py`

- [ ] **Step 1: Read** `schemas.py` around `class TaskOut` and the serializer(s) that build `TaskOut` from a `TaskItem` in `routes_tasks.py` (`GET /api/tasks/{id}`, list, history). Note whether TaskOut is built via `from_attributes`/`model_validate` or field-by-field.

- [ ] **Step 2: Write the failing test**

```python
# mcp-servers/tasks/tests/test_task_out_user_prompt.py
from schemas import TaskOut
from prompt_utils import clean_user_prompt


def test_taskout_exposes_clean_user_prompt():
    # TaskOut must carry a user_prompt derived from the wrapped description
    raw = "<rules>\n\nUSER REQUEST:\nbuild a booking site"
    out = TaskOut(
        id=1, description=raw, status="pending", action_type="BUILD",
        user_prompt=clean_user_prompt(raw),
    )  # fill remaining required fields per the real schema when writing
    assert out.user_prompt == "build a booking site"
```

Adjust the constructor to the real required fields after reading schemas.py.

- [ ] **Step 3: Run — expect FAIL** (unknown field `user_prompt`)
- [ ] **Step 4: Implement** — add `user_prompt: str = ""` to `TaskOut`; in every serializer that returns a `TaskOut`, set `user_prompt=clean_user_prompt(item.description)`. If TaskOut uses `model_validate(item)`, add a wrapper that injects it, or add a `@model_validator(mode="after")`-free approach: build the dict then set the field. Prefer a single helper `def _task_out(item) -> TaskOut` if one exists; otherwise add it and route all three endpoints through it.
- [ ] **Step 5: Run — expect PASS**; also run the full local tasks suite to catch serializer regressions: `AIUI_FERNET_KEY=t python -m pytest tests/ -q`
- [ ] **Step 6: Commit** — `git commit -m "feat(tasks): TaskOut.user_prompt exposes the clean prompt to every UI"`

---

### Task 1.3: `user_prompt` + `question` on `BuildStatusResponse`

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py` (`BuildStatusResponse`, `_public_build_status`, `GET /build/{task_id}`)
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder.py` (extend)

- [ ] **Step 1: Read** `routes_aiuibuilder.py:130-180, 440-470` (`_public_build_status`, `BuildStatusResponse`, the GET handler).

- [ ] **Step 2: Write failing tests** (extend the file)

```python
def test_build_status_includes_user_prompt_and_question(monkeypatch):
    # a build awaiting input surfaces the clean prompt and the pending question
    # Build a fake TaskItem-like object with description wrapped + result=question,
    # call the status serializer, assert response.user_prompt == "<clean>" and
    # response.question == "<the question>" and status == "needs_input".
    ...
```

- [ ] **Step 3: Run — expect FAIL**
- [ ] **Step 4: Implement** — add `user_prompt: str = ""` and `question: str | None = None` to `BuildStatusResponse`; when `task_status == "awaiting_input"`, set `question = item.result`; set `user_prompt = clean_user_prompt(item.description)`. Keep the public status string `needs_input` (still what non-answering callers see) — resumability is added in Task 2.3, not by changing this string.
- [ ] **Step 5: Run — expect PASS**
- [ ] **Step 6: Commit** — `git commit -m "feat(tasks): build status returns user_prompt and pending question"`

---

### Task 1.4: persist the initial prompt as the first chat message

**Files:**
- Modify: `mcp-servers/tasks/routes_tasks.py` (`create_task`, BUILD branch) and `mcp-servers/tasks/routes_aiuibuilder.py` (`_create_and_spawn_build`)
- Reference: `mcp-servers/tasks/routes_chat_history.py` / `models.py` `ChatMessage` for the write shape
- Test: `mcp-servers/tasks/tests/test_initial_prompt_chat_message.py` (in-container/DB tier)

- [ ] **Step 1: Read** `models.py` `ChatMessage` and `routes_chat_history.py` to learn the exact insert (columns: slug/app_slug, user_email, role, content, created_at) and whether a helper exists.

- [ ] **Step 2: Write failing test (DB tier)** — create a BUILD task via `create_task` with a slug + user_email, then assert a `ChatMessage(role="user")` with the clean prompt exists for (slug, user_email); creating again does not duplicate it.

- [ ] **Step 3: Run — expect FAIL** (`AIUI_TEST_DB=1`, DSN with "test"; this is a DB test — takes `db_session` fixture)
- [ ] **Step 4: Implement** — a small idempotent helper `async def _seed_prompt_message(session, slug, user_email, prompt)` that inserts a `role="user"` ChatMessage iff none exists yet for (slug, user_email). Call it from both build-create paths, guarded to BUILD + slug + user_email present, using `clean_user_prompt`.
- [ ] **Step 5: Run — expect PASS**
- [ ] **Step 6: Commit** — `git commit -m "feat(tasks): seed the build thread with the user's original prompt"`

---

## Phase 2 — Server: resume correctness + answer endpoint

### Task 2.1: shared `build_resume_prompt` (fixes one-shot context loss)

**Files:**
- Modify: `mcp-servers/tasks/claude_executor.py` (add `build_resume_prompt`)
- Modify: `mcp-servers/tasks/routes_tasks.py` (`/answer` one-shot `else` branch, ~`:687-701`)
- Test: `mcp-servers/tasks/tests/test_resume_prompt.py`

- [ ] **Step 1: Read** `claude_executor.py` `build_prompt` + `build_enhance_prompt` signatures and the enhance "CONVERSATION WITH ADMIN" block; read `routes_tasks.py:614-706`.

- [ ] **Step 2: Write failing tests**

```python
# mcp-servers/tasks/tests/test_resume_prompt.py
from claude_executor import build_resume_prompt


def test_resume_replays_full_history_and_says_continue():
    history = [
        {"role": "ai", "content": "What colour scheme?"},
        {"role": "admin", "content": "dark, teal accents"},
        {"role": "ai", "content": "How many pages?"},
        {"role": "admin", "content": "three"},
    ]
    p = build_resume_prompt(
        description="<rules>\n\nUSER REQUEST:\nbuild a portfolio",
        slug="portfolio-a1", user_email="u@x.com",
        conversation_history=history, latest_answer="three",
    )
    assert "dark, teal accents" in p          # earlier round retained
    assert "three" in p
    assert "apps/portfolio-a1/" in p          # continue-existing-app instruction
    assert "do not" in p.lower() and "restart" in p.lower()
```

- [ ] **Step 3: Run — expect FAIL**
- [ ] **Step 4: Implement** `build_resume_prompt(...)` = `build_prompt(description, ..., slug, user_email)` + a rendered conversation block (reuse the enhance block format) + an explicit "A partial app already exists at apps/<slug>/ — continue it, do not restart from scratch." Then in `routes_tasks.py` `/answer`, replace the one-shot `else` branch to call `build_resume_prompt(... conversation_history=history, latest_answer=body.answer)`.
- [ ] **Step 5: Write + run the missing integration test** — `test_answer_resumes_one_shot_build_with_context` in `test_routes_tasks.py`: task in `awaiting_input`, `max_attempts=1`, POST `/answer`, assert status→`running`, a new `TaskExecution` row, and the prompt handed to the (faked) executor contains the earlier round + the continue instruction. (This closes the coverage gap flagged in the scan.)
- [ ] **Step 6: Run — expect PASS**
- [ ] **Step 7: Commit** — `git commit -m "fix(tasks): one-shot resume replays full context and continues the existing app"`

---

### Task 2.2: `/execute` from `awaiting_input` must not drop the answer

**Files:**
- Modify: `mcp-servers/tasks/routes_execution.py` (`_build_execute_prompt` ~`:365`, `execute` guard ~`:437`)
- Test: `mcp-servers/tasks/tests/test_routes_execution.py` (extend)

- [ ] **Step 1: Read** `_build_execute_prompt` and `execute`.
- [ ] **Step 2: Write failing test** — `test_execute_from_awaiting_input_preserves_conversation`: task `awaiting_input` with a `conversation_history`, POST `/execute`, assert the prompt handed to the faked executor includes the prior admin answer (not a bare `build_prompt`).
- [ ] **Step 3: Run — expect FAIL** (current code drops it)
- [ ] **Step 4: Implement** — in `_build_execute_prompt`, when `item.status == "awaiting_input"` (or `item.conversation_history` non-empty and last entry is an admin answer) and it is the one-shot path, route through `build_resume_prompt(...)` instead of `build_prompt(...)`. Loop/plan path already replays history — leave it.
- [ ] **Step 5: Run — expect PASS**
- [ ] **Step 6: Commit** — `git commit -m "fix(tasks): resuming via execute no longer discards the user's answer"`

---

### Task 2.3: user-scoped `POST /api/aiuibuilder/build/{task_id}/answer`

**Files:**
- Modify: `mcp-servers/tasks/routes_aiuibuilder.py` (new endpoint + make `awaiting_input` resumable for bot origin)
- Reference: reuse the resume logic from `routes_tasks.py /answer` — extract it into a shared `async def resume_with_answer(session, item, answer) -> None` in a module both import (e.g. a new `mcp-servers/tasks/resume.py`, or a function in `routes_execution.py`) to avoid duplication.
- Test: `mcp-servers/tasks/tests/test_routes_aiuibuilder_answer.py`

- [ ] **Step 1: Read** how build start authorizes the caller (`start_build` / `_create_and_spawn_build` auth dependency) so the answer endpoint uses the SAME auth (user-scoped, not admin-only).
- [ ] **Step 2: Write failing tests** — (a) POST answer to an `awaiting_input` build flips it to `running`, appends the admin answer to `conversation_history`, spawns an execution; (b) answering a build not in `awaiting_input` returns 409; (c) auth: a caller without the build-scope is rejected.
- [ ] **Step 3: Run — expect FAIL**
- [ ] **Step 4: Implement** — extract the answer/resume core into `resume_with_answer(...)` (append answer → history, status→running, new TaskExecution, `build_resume_prompt`, spawn `_run_execution`); call it from both the web `/answer` and the new aiuibuilder endpoint. Add `_LIVE_BUILD_STATES`-aware handling so an `awaiting_input` build is answerable.
- [ ] **Step 5: Run — expect PASS**
- [ ] **Step 6: Commit** — `git commit -m "feat(tasks): user-scoped answer endpoint resumes a paused build"`

---

## Phase 3 — Web App Builder UI

> JS/HTML edits; verified by the backend tests above + the live e2e. Read each region before editing.

### Task 3.1: gallery card shows the original prompt, not the enhance prefix

**Files:** Modify `mcp-servers/tasks/static/projects.html` (dedupe `:1262-1272`; render `:1296-1304`, `:1334`)

- [ ] **Step 1: Read** `projects.html:1255-1340`.
- [ ] **Step 2: Implement** — (a) render `t.user_prompt` (server field) instead of the `lastIndexOf("USER REQUEST:")` strip; (b) when deduping by slug, keep the newest task for status/preview/link but carry `displayPrompt` = the `user_prompt` of the earliest task for the slug whose `description` does NOT start with `Enhance apps/` (fallback: newest `user_prompt`). Render `displayPrompt`.
- [ ] **Step 3: Verify** — covered by the live e2e (create → enhance → card still shows the original request). Note in commit that JS is e2e-verified.
- [ ] **Step 4: Commit** — `git commit -m "fix(appbuilder-ui): gallery card keeps the original prompt after enhancement"`

### Task 3.2: pre-select a template passed via URL hash

**Files:** Modify `mcp-servers/tasks/static/projects.html` (load-time init)

- [ ] **Step 1: Implement** — on load, read `location.hash`/`location.search` for `template=<key>`; if present and valid, pre-select it (drive the same code path as the in-page picker's select), and clear the "pick a template" block on submit.
- [ ] **Step 2: Commit** — `git commit -m "fix(appbuilder-ui): honor ?template=/#template= from the standalone gallery"`

### Task 3.3: preview page shows the original prompt (overlay + transcript, race fixed)

**Files:** Modify `mcp-servers/tasks/static/preview.html` (overlay `:2230-2255`; `_bovCheck` `:3116-3226`; `loadEnhanceHistory`/`loadChatHistory` `:7030-7090`, called `:3628-3629`)

- [ ] **Step 1: Read** those regions.
- [ ] **Step 2: Implement** — (a) add a "Your request" element in the build overlay bound to `task.user_prompt`; (b) render the original prompt as the first transcript bubble (from `task.user_prompt`, independent of the enhance/chat filters); (c) fix the clobber race: `loadEnhanceHistory` and `loadChatHistory` must not each blindly `innerHTML=""` the shared `#enhance-log` back-to-back — await them in sequence and render the prompt bubble first, or merge into one render function. Do not double-call `loadEnhanceHistory` on the completed path.
- [ ] **Step 3: Verify** via live e2e (watch a build → original request visible; reload → still visible).
- [ ] **Step 4: Commit** — `git commit -m "fix(appbuilder-ui): preview shows the original request and stops losing history to a race"`

### Task 3.4: unstick a pending build that already has an execution

**Files:** Modify `mcp-servers/tasks/static/preview.html` (`_bovCheck` pending branch `:3183-3204`)

- [ ] **Step 1: Implement** — when status is `pending` and executions.length > 0, reveal the manual `#build-start` button (and/or auto-`POST /execute`) instead of showing "building…" forever.
- [ ] **Step 2: Commit** — `git commit -m "fix(appbuilder-ui): a stalled pending build can be started again"`

---

## Phase 4 — webhook-handler bots (echo + answer path)

### Task 4.1: `_start_build` ACK echoes the verbatim prompt

**Files:** Modify `webhook-handler/handlers/commands.py` (`_start_build` `:2052-2090`); Test: `webhook-handler/tests/test_aiuibuilder_build.py` + `test_panel_build.py`

- [ ] **Step 1: Write failing test** — extend `test_build_happy_path_starts_and_acks` (or add `test_build_ack_echoes_user_request`): assert the ACK text contains the full user description string (e.g. `"A CRM, a dashboard, and booking for my clinic"`), not just `"Building"` + slug.
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — in `_start_build`, include the verbatim `description` in the ACK (Discord/Slack), e.g. a quoted "your request" line; keep `friendly_name` for the short bold title. Truncate the echo to a safe length (< platform limit) with an ellipsis but keep the whole ask when it fits.
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "fix(appbuilder): bot echoes the user's real request, not a one-word fragment"`

### Task 4.2: `TasksClient.answer_build`

**Files:** Modify `webhook-handler/clients/tasks.py`; Test: `webhook-handler/tests/test_tasks_client_builder_thread.py` (or new)

- [ ] **Step 1: Write failing test** — `answer_build(task_id, answer)` POSTs to `/api/aiuibuilder/build/{id}/answer` with `{answer}` and returns the parsed status (fake httpx).
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** the method mirroring `start_build`/`get_build_status` error handling.
- [ ] **Step 4: Run — expect PASS**; **Commit** — `git commit -m "feat(appbuilder): tasks client can answer a paused build"`

### Task 4.3: Discord — answer a paused build from the build thread

**Files:** Modify `webhook-handler/handlers/commands.py` (`_watch_build` needs_input branch `:2859-2867`; `handle_builder_thread_message` `:648-684`; StateStore dicts `:282-293`); Test: `webhook-handler/tests/test_aiuibuilder_build.py`

- [ ] **Step 1: Write failing test** — `test_watch_build_needs_input_arms_answer_then_thread_reply_resumes`: watcher hits `needs_input`, posts the question and arms `_pending_build_answer[uid]=task_id` (StateStore-backed); a subsequent `handle_builder_thread_message` reply calls `answer_build` and re-spawns the watcher.
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — on `needs_input`: post the question into the thread (no more "continue in the web builder" dead-end), set `_pending_build_answer` (persisted). In `handle_builder_thread_message`, check `_pending_build_answer` BEFORE the current-app refine branch: if armed, call `answer_build`, clear the flag, re-spawn `_watch_build`. Hydrate-on-miss like the other StateStore dicts.
- [ ] **Step 4: Run — expect PASS**; **Commit** — `git commit -m "feat(appbuilder): Discord can answer and resume a paused build in-thread"`

### Task 4.4: Slack — answer a paused build via a modal

**Files:** Modify `webhook-handler/handlers/slack_commands.py` / `slack_interactions.py` / `slack_app_builder_panel.py`; the Slack build watcher notifier; Test: `webhook-handler/tests/test_slack_interactions.py`

- [ ] **Step 1: Read** how the Slack build watcher posts to DM and how `_handle_view_submission` dispatches (`slack_interactions.py:909`).
- [ ] **Step 2: Write failing test** — needs_input posts a block with an "Answer" button carrying `task_id`; clicking opens a modal; view submission calls `answer_build` and re-spawns the watcher.
- [ ] **Step 3: Run — expect FAIL**
- [ ] **Step 4: Implement** — an "Answer" button (`action_id=appbuild:answer:<task_id>`) → `open_modal(answer_view(task_id))` → view submission branch calls `answer_build`, posts an ack, re-arms the watcher.
- [ ] **Step 5: Run — expect PASS**; **Commit** — `git commit -m "feat(appbuilder): Slack can answer and resume a paused build via modal"`

### Task 4.5: Voice — echo prompt, speak the question, persist last-build

**Files:** Modify `webhook-handler/main.py` (`voice_webhook` `:638-699`, `_last_voice_build` `:568`) and `webhook-handler/handlers/commands.py` (`run_voice_build` `:2131`, `run_voice_build_status` `:2195`); Test: `webhook-handler/tests/test_voice_app_builder.py`

- [ ] **Step 1: Write failing tests** — (a) `run_voice_build` ACK speaks a trimmed echo of the request; (b) `run_voice_build_status` on `needs_input` speaks the question and invites an answer; (c) last-build state round-trips through StateStore (survives a fresh handler instance).
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — echo the request in `run_voice_build`; speak `question` in status; replace the in-memory `_last_voice_build` with StateStore-backed get/set keyed by the voice identity.
- [ ] **Step 4: Run — expect PASS**; **Commit** — `git commit -m "feat(appbuilder): voice echoes the request and can resume a paused build"`

---

## Phase 5 — Voice agent tool registration

### Task 5.1: `answer_build` voice tool + dispatch

**Files:** Modify `webhook-handler/scripts/setup_voice_agent.py` (add `answer_build` tool) and `webhook-handler/main.py` (`voice_webhook` dispatch); Test: `webhook-handler/tests/test_voice_app_builder.py`

- [ ] **Step 1: Write failing test** — a `voice_webhook` POST with command `answer_build` + `{answer}` calls `answer_build` and returns a spoken confirmation.
- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — add the `answer_build` tool definition (mirrors `start_build`/`build_status`, param `answer`); dispatch it in `voice_webhook` to the handler.
- [ ] **Step 4: Run — expect PASS**; **Commit** — `git commit -m "feat(voice): answer_build tool resumes a paused build by voice"`

> Deploy note: the ElevenLabs agent must be re-provisioned by running `setup_voice_agent.py` against prod so the new tool registers (Phase 7).

---

## Phase 6 — OWUI nuggets doc (defer + document)

### Task 6.1: write the ranked nuggets doc

**Files:** Create `docs/owui-v0.10-build-nuggets.md`

- [ ] **Step 1: Write** the ranked opportunities (native tool/Model, Artifacts inline preview, Knowledge-Base RAG, native automations, Channels, Notes) with the current-integration context and a one-line "why it helps the build feature" each, plus a top-5 recommendation. (Source: the OWUI research already done.)
- [ ] **Step 2: Commit** — `git commit -m "docs: OWUI v0.10 build-feature opportunities (deferred)"`

---

## Phase 7 — Green, e2e, deploy

- [ ] **Task 7.1** — webhook-handler suite green: `cd webhook-handler && python -m pytest tests/ -q` (read output; never trust piped exit codes).
- [ ] **Task 7.2** — tasks local suite green: `cd mcp-servers/tasks && AIUI_FERNET_KEY=t python -m pytest tests/ -q`.
- [ ] **Task 7.3** — deploy tasks + webhook-handler to the box per CLAUDE.md (per-file scp + `docker compose up -d --build`), strip CRLF on shipped files.
- [ ] **Task 7.4** — tasks in-container suite green vs `aiui_test` (anchored DSN, `AIUI_TEST_DB=1`).
- [ ] **Task 7.5** — live e2e: create a build via `/api/tasks` (web) and `/api/aiuibuilder/build` (bot), confirm `user_prompt` returned and shown; drive a NEEDS_INPUT → answer → resume end to end (web + the new aiuibuilder answer endpoint).
- [ ] **Task 7.6** — re-run `setup_voice_agent.py` against prod to register `answer_build`.
- [ ] **Task 7.7** — video-remotion suite still green (`cd video-remotion && npm test`), confirming no collateral.
- [ ] **Task 7.8** — bump `.deploy-state`, merge `feat/build-prompt-resume-fixes` → main, push fork (`gh auth switch -u Jacintalama` first; fetch+rebase; never force-push).

---

## Self-review notes

- Spec coverage: Bug 1 → Tasks 1.1–1.4, 3.1, 3.3, 4.1, 4.5. Bug 2 → Tasks 2.1–2.3, 3.2, 3.4, 4.2–4.5, 5.1. OWUI → Task 6.1. Green/e2e → Phase 7. All spec sections mapped.
- Naming consistency: `clean_user_prompt`, `build_resume_prompt`, `resume_with_answer`, `answer_build`, `_pending_build_answer`, `user_prompt`, `question` used consistently across tasks.
- Placeholder honesty: JS/HTML tasks say "Read region, then <precise change>" because the exact edit depends on current markup; each is pinned by a backend test or the live e2e, not left vague.
