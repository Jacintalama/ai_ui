# Lukas standup 2026-11-10 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the five things Lukas asked for on 2026-11-10: a lighter mcp-proxy, ClickUp create/move/assign that works, a video progress panel, a sturdier app preview with a desktop side view, and new agents that pick their own skills.

**Architecture:** Four PRs, each independently deployable. (A) `mcp-proxy/tool_embeddings.py` embeds only changed tools, in batches. (B) a ClickUp resolver in the tasks service sits between the model's arguments and ClickUp's API. (C) `integrations-ui.js` gets a video step panel, a reply-wait guard on the build panel, a loading state on app panels and a scaled desktop side view. (D) a Jev-backed skill picker used by both agent-creation paths, with the agents page pre-ticking its picks.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, fastembed/onnxruntime (proxy); vanilla JS served as a static asset (page); pytest, node for running the real JS sections.

Design: `docs/plans/2026-11-10-lukas-standup-design.md`.

---

## PR A: mcp-proxy embeds only what changed, in batches

### Task A1: pure helpers, tested first

**Files:**
- Modify: `mcp-proxy/tool_embeddings.py`
- Test: `mcp-proxy/tests/test_the_index_embeds_only_what_changed.py`

**Step 1: failing tests**

```python
from tool_embeddings import tool_text, text_hash, needing_embedding, EMBED_BATCH

def test_the_text_is_what_was_always_embedded():
    info = {"original_name": "create_task", "description": "Create a task",
            "tenant_name": "ClickUp (your account)"}
    assert tool_text("my-clickup_create_task", info) == \
        "create_task - Create a task (server: ClickUp (your account))"

def test_an_unchanged_tool_is_not_embedded_again():
    texts = {"a": "a - x (server: s)", "b": "b - y (server: s)"}
    stored = {"a": text_hash(texts["a"]), "b": text_hash(texts["b"])}
    assert needing_embedding(texts, stored) == []

def test_a_new_or_changed_or_unhashed_tool_is_embedded():
    texts = {"a": "a - x", "b": "b - changed", "c": "c - new", "d": "d - old row"}
    stored = {"a": text_hash("a - x"), "b": text_hash("b - before"), "d": None}
    assert needing_embedding(texts, stored) == ["b", "c", "d"]

def test_batches_are_small():
    assert EMBED_BATCH <= 32
```

**Step 2:** `cd mcp-proxy && python -m pytest tests/test_the_index_embeds_only_what_changed.py -q` → FAIL (ImportError).

**Step 3:** add `tool_text`, `text_hash` (sha256 hex of the text), `needing_embedding(texts, stored)` (sorted names whose stored hash is missing, None or different), `EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))`, and pass `batch_size=EMBED_BATCH` in `generate_embeddings_batch`.

**Step 4:** tests pass.

### Task A2: store_tool_embeddings uses them

**Files:** `mcp-proxy/tool_embeddings.py`, same test file.

**Step 1: failing test** with a fake asyncpg pool (records `execute`/`fetch` calls; `fetch` returns rows `{"tool_name", "text_hash"}`) and a monkeypatched `generate_embeddings_batch` that records what it was asked to embed:
- all hashes match → `generate_embeddings_batch` never called, and `get_embedding_model` never called;
- one changed → called with exactly that one text; its row is written with its hash.

**Step 2:** run → FAIL.

**Step 3:** in `ensure_embeddings_table`, `ALTER TABLE mcp_proxy.tool_embeddings ADD COLUMN IF NOT EXISTS text_hash TEXT`. In `store_tool_embeddings`: build `texts` with `tool_text`; `SELECT tool_name, text_hash FROM mcp_proxy.tool_embeddings WHERE embedding IS NOT NULL`; embed only `needing_embedding(...)`; write `text_hash` with each row; still upsert metadata for every tool so descriptions stay current; log `Embedded N of M tools (the rest unchanged)`.

**Step 4:** all proxy tests pass: `cd mcp-proxy && python -m pytest tests -q`.

**Step 5:** commit, PR, merge, deploy. Verify on the server: process RSS of `uvicorn main:app` after the deploy boot and after one more restart; boot log line; `free -m`.

---

## PR B: ClickUp people and columns

### Task B1: the resolver, pure

**Files:**
- Create: `mcp-servers/tasks/clickup_people.py`
- Test: `mcp-servers/tasks/tests/test_clickup_understands_people_and_columns.py`

Fixtures are copied from ClickUp's v2 reference (`GET /v2/team`, `GET /v2/list/{id}`, `GET /v2/task/{id}`), with an `email` on each member as `GET /v2/user` defines it.

Functions:
- `members_of(team_payload) -> list[dict]` — `{id, username, email}` from every workspace, deduped by id.
- `resolve_person(value, members) -> (id | None, problem | None)` — int or digit string as is; else exact email, exact username, then a unique first-word match, case-insensitive; ambiguous or unknown → a sentence naming the people there (at most 10).
- `resolve_assignees(value, members, for_update)` — create: list (or one value) → list of ints. update: list → `{"add": ids, "rem": []}`; dict → both keys resolved, missing key `[]`.
- `resolve_status(value, statuses) -> (status | None, problem | None)` — case and space insensitive exact match; "done", "complete", "completed", "finished", "closed" → the single status of type `closed`/`done`; otherwise a sentence listing the columns.

Tests (each written first, seen failing):
1. email → id; username → id; "ralph" → id when one member's first word is Ralph.
2. two Johns → problem naming both; unknown → problem naming who is there.
3. an id passes untouched; a digit string becomes an int.
4. update with a list → `{"add": [...], "rem": []}`; update with `{"add": ["x@y"]}` → rem filled.
5. "In Progress" → "in progress"; "done" → "complete" (type closed); "doing" → problem listing "to do, complete".

### Task B2: wired into the ClickUp calls

**Files:** `mcp-servers/tasks/mytools.py`, same test file.

- A per-provider hook: before `_call` sends a ClickUp `create_task` or `update_task`, `clickup_people.prepare(tool_name, args, get)` fetches what it needs through the same authenticated client (`GET /team` only when assignees are given, `GET /list/{list_id}` or `GET /task/{id}` then `GET /list/{id}` only when status is given) and returns `(args, problem)`. A problem returns `_err(problem)` without calling ClickUp.
- ClickUp 400/422: append `_vendor_said(r, creds)` (ClickUp's `err` field) to the error.
- `update_task` summary: "Update a task: move it to another column (status), assign or unassign people, rename it, or change its due date or priority."; assignees descriptions say a name, email or id is fine.

Tests: drive `_call` with a fake transport (`httpx.MockTransport`) and fake creds: create with `assignees=["ralph@x.com"]` sends `[123]`; update with status "Done" sends "complete"; unknown person sends nothing to ClickUp and returns the problem; a 400 with `{"err": "Status not found"}` returns that reason.

Then commit, PR, merge, deploy; verify the served openapi shows the new summary; live write test only with the account owner's permission.

---

## PR C: the chat page

**Files:** `mcp-servers/gdrive/integrations-ui.js`; tests in `mcp-servers/tasks/tests/test_the_page_reads_the_saved_message.py` and a new `test_the_chat_shows_work_in_progress.py`, running the real section under node.

### Task C1: video step panel
- `aiuiVideoSteps(job)` → three rows (In the queue, Writing the script, Recording and rendering) with done/working/waiting from `job.status` (`queued`, `scripting`, `voicing`, `rendering`).
- `aiuiVideoPanel(chatId, job, mins)` draws `#aiui-video-steps` in the last reply (returns false when no reply is on screen), with the queue sentence ("2 ahead of it" or "Waiting for room on the server"), a moving bar on the working row, and minutes.
- `aiuiPollVideo` uses it instead of `aiuiBuildLine`, and removes it when the video settles.
- Tests: states for each status; the panel waits for a reply; the queue sentence; removal on done.

### Task C2: build step panel waits for a reply
- `aiuiStepPanel` returns false without drawing when `aiuiLastReplyBody()` is null. Test under node.

### Task C3: app panel loading state
- `aiuiShowAppInline`: a "Loading the app" overlay over the frame, removed on the frame's `load`. Frame background dark while loading. Test: overlay present at draw, gone after a `load` event.

### Task C4: desktop side view
- `aiuiSplitOpen`: the frame is laid out at `AIUI_DESKTOP_W = 1280` px wide and scaled with `transform: scale(holderWidth / 1280)` (height divided by the same factor), recomputed on window resize; `aiuiSplitClose` restores the frame's style. When the holder is already 1280 or wider, no scale.
- Test: the computed width and scale for a 700 px holder; restore on close.

Shared: one `<style id="aiui-motion">` with the bar animation and `@media (prefers-reduced-motion: reduce)` turning it off.

Then commit, PR, merge, deploy; check on the live site in a browser: side view inner width 1280 and screenshot; video panel with a queued test job (deleted after); app loading overlay on a real app.

---

## PR D: new agents pick their skills

### Task D1: Jev picks skills
**Files:** `mcp-servers/tasks/agent_jev.py`, `mcp-servers/tasks/agent_skills.py`; test `mcp-servers/tasks/tests/test_new_agents_pick_their_skills.py`.
- `agent_jev.skills_request(text, skills)` → one `noul` question per skill ("Would an agent described like this use the skill X: <description>?").
- `agent_jev.pick_skills(email, text, skills) -> list | None` via `ask_many`, keeping answers at or above `cut(PURPOSE_SKILLS)` (0.8), best first.
- `agent_skills.pick_for(email, text, pool)` → Jev's picks (at most `PICK_LIMIT` = 5) or, when Jev returns None, `suggest(text)`.
- Tests: the question names each skill and its description; picks are ordered by confidence and capped; None falls back to keywords.

### Task D2: both creation paths use it
- `routes_agents._skills_for` takes the ranked list from `pick_for` when nothing is named (made async-safe by ranking before calling it).
- New `GET /agents/skills/for?role=&instructions=` → `{"skills": [...], "needs_connect": [...], "said": "Suggested from the description"}`.
- Tests: route returns picks and gaps with Jev stubbed.

### Task D3: agents page pre-ticks
- `agents.html`: for a new agent, on `blur` of the instructions box with non-empty text and no skill ticked by the person, fetch `/api/tasks/agents/skills/for`, tick the picks, show "Suggested from the description: a, b" under the skills row with "Suggest again"; any manual tick stops further auto-ticking.
- Test: a structural test that the handler exists and only runs for a new agent and untouched skills; then a live browser check on the agents page without saving.

Then commit, PR, merge, deploy, verify live.
