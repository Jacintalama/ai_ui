# New video → straight into the upload thread — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking **New video** drops the user straight into their private thread (no upfront form), where they drag screenshots in, click **Add title & description**, pick style/voice, and Generate — no slash commands shown.

**Architecture:** The New-video button creates an *empty* draft and opens the thread (reusing `_open_video_studio`). The thread's controls include an **Add title & description** button that opens a popup whose submit patches the draft via an extended `/draft-set`. `Generate` (queue) refuses with a clear message if the description is blank. Backend draft endpoints gain optional title/prompt; only the Discord draft path is touched.

**Tech Stack:** Python 3.13, FastAPI (tasks backend), discord interactions over HTTP, pytest. Worktree `C:/Users/alama/Desktop/Lukas Work/IO-integrate`, branch `fix/video-thread-image-intake`. Bot tests run from `webhook-handler/`; backend tests from `mcp-servers/tasks/` (DB tests skip offline, run at deploy/CI).

---

## File Structure

- **Modify** `mcp-servers/tasks/routes_video.py` — `DraftRequest` (optional title/prompt), `DraftPatch` (+title/prompt), `update_draft` (apply them), `queue_job` (blank-prompt guard).
- **Modify** `mcp-servers/tasks/tests/test_routes_video_draft.py` + `test_routes_video_queue.py` — new cases.
- **Modify** `webhook-handler/clients/tasks.py` — `set_video_draft_fields` gains title/prompt.
- **Modify** `webhook-handler/handlers/video_panel.py` — details modal/button/prefixes, studio components, embed copy; remove `build_video_modal`/`NEW_MODAL_ID`/`is_vid_new_modal`.
- **Modify** `webhook-handler/handlers/discord_commands.py` — `is_vid_new`→studio, `is_vid_details`→modal, details-modal submit; remove `_handle_video_new_modal`; studio message copy.
- **Modify** `webhook-handler/handlers/commands.py` — `run_video_set_details`.
- **Modify** `webhook-handler/tests/test_video_panel.py`, `test_video_routing.py`, `test_video_new.py` — update for the new flow.

---

## Task 1: Backend — empty draft, draft-set title/prompt, queue blank-prompt guard

**Files:**
- Modify: `mcp-servers/tasks/routes_video.py` (`DraftRequest` 128-132, `queue_job` 794-830, `DraftPatch` 789-791, `update_draft` 833-859)
- Test: `mcp-servers/tasks/tests/test_routes_video_draft.py`, `mcp-servers/tasks/tests/test_routes_video_queue.py`

- [ ] **Step 1: Write the failing offline test (request-model change)**

Append to `mcp-servers/tasks/tests/test_routes_video_draft.py`:

```python
async def test_create_draft_allows_empty_body_no_422():
    """With optional title/prompt, POST /draft with an empty body passes
    validation (no 422). Offline it then hits the dummy DB and 500s; the point is
    only that it is NOT a 422 validation error anymore."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", json={}, headers=HEAD)
    assert r.status_code != 422
```

And the DB-gated cases:

```python
@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_create_empty_draft_defaults_title_and_blank_prompt(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", json={}, headers=HEAD)
    assert r.status_code == 201
    job = (await db_session.execute(
        select(VideoJob).where(VideoJob.id == uuid.UUID(r.json()["id"])))).scalar_one()
    assert job.title == "Untitled video"
    assert job.prompt == ""
    assert job.status == "collecting"


@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_draft_set_updates_title_and_prompt(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", json={}, headers=HEAD)
    job_id = r.json()["id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/draft-set",
                         json={"title": "Real Title", "prompt": "narrate the dashboard"},
                         headers=HEAD)
    assert r.status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/video-jobs/current-draft", headers=HEAD)
    assert r.json()["title"] == "Real Title"
```

Append to `mcp-servers/tasks/tests/test_routes_video_queue.py` (mirror its existing imports/fixtures — it already builds drafts + screenshots for queue tests):

```python
@pytest.mark.skipif(not _HAVE_DB, reason="needs Postgres (runs at deploy/CI)")
async def test_queue_blocks_blank_description(db_session, tmp_path, monkeypatch):
    """A draft with a screenshot but a blank description cannot be queued."""
    monkeypatch.setenv("APPS_DIR", str(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/video-jobs/draft", json={"title": "T", "prompt": ""}, headers=HEAD)
    job_id = r.json()["id"]; slug = r.json()["slug"]
    shots = tmp_path / slug / ".video" / job_id / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    (shots / "screenshot-1.png").write_bytes(b"x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/video-jobs/{job_id}/queue", headers=HEAD)
    assert r.status_code == 400
    assert "description" in r.json()["detail"].lower()
```

(If `test_routes_video_queue.py` lacks the `json={"title":..., "prompt":""}` create + screenshot setup helpers, write them inline as above; check the file's existing pattern first and match it.)

- [ ] **Step 2: Run the offline test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_draft.py::test_create_draft_allows_empty_body_no_422 -q`
Expected: FAIL — currently returns 422 (title/prompt required), so `assert r.status_code != 422` fails.

- [ ] **Step 3: Make title/prompt optional + extend DraftPatch + apply + queue guard**

In `mcp-servers/tasks/routes_video.py`:

(a) `DraftRequest` — replace:

```python
class DraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: str = Field("clean_product_demo", max_length=50)
    voice: str = Field(DEFAULT_VOICE_ID, max_length=50)
```

with:

```python
class DraftRequest(BaseModel):
    title: str = Field("Untitled video", max_length=200)
    prompt: str = Field("", max_length=2000)
    style: str = Field("clean_product_demo", max_length=50)
    voice: str = Field(DEFAULT_VOICE_ID, max_length=50)
```

(b) `DraftPatch` — replace:

```python
class DraftPatch(BaseModel):
    style: str | None = Field(None, max_length=50)
    voice: str | None = Field(None, max_length=50)
```

with:

```python
class DraftPatch(BaseModel):
    style: str | None = Field(None, max_length=50)
    voice: str | None = Field(None, max_length=50)
    title: str | None = Field(None, max_length=200)
    prompt: str | None = Field(None, max_length=2000)
```

(c) `update_draft` — after the `if body.voice is not None:` block (which ends with `vals["voice"] = body.voice`), and BEFORE `if vals:`, add:

```python
        if body.title is not None:
            vals["title"] = body.title
        if body.prompt is not None:
            vals["prompt"] = body.prompt
```

(d) `queue_job` — right after the screenshot check (`if not _list_screenshots(job.slug, str(jid)): raise HTTPException(400, "Add at least one screenshot first")`), add:

```python
        if not (job.prompt or "").strip():
            raise HTTPException(400, "Add a description first")
```

- [ ] **Step 4: Run the offline test + the tasks offline suite**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_video_draft.py -q`
Expected: PASS (the empty-body test now passes; DB tests SKIP offline). Then `python -m pytest -q` in `mcp-servers/tasks` to confirm no offline regressions.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add mcp-servers/tasks/routes_video.py mcp-servers/tasks/tests/test_routes_video_draft.py mcp-servers/tasks/tests/test_routes_video_queue.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): empty draft + draft-set title/prompt + queue blank-prompt guard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: TasksClient.set_video_draft_fields accepts title/prompt

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (`set_video_draft_fields` 268-276)
- Test: `webhook-handler/tests/test_video_new.py`

- [ ] **Step 1: Write the failing test**

Append to `webhook-handler/tests/test_video_new.py`:

```python
@pytest.mark.asyncio
async def test_set_video_draft_fields_includes_title_and_prompt():
    from clients.tasks import TasksClient
    tc = TasksClient(base_url="http://t")
    captured = {}

    async def fake_request(method, path, user_email, json=None):
        captured["json"] = json

        class R:
            def json(self_inner):
                return {"status": "ok"}
        return R()

    tc._request = fake_request
    await tc.set_video_draft_fields("u@x.com", "job1", title="T", prompt="P")
    assert captured["json"] == {"title": "T", "prompt": "P"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py::test_set_video_draft_fields_includes_title_and_prompt -q`
Expected: FAIL — `set_video_draft_fields` has no `title`/`prompt` kwargs (TypeError).

- [ ] **Step 3: Extend `set_video_draft_fields`**

In `webhook-handler/clients/tasks.py`, replace:

```python
    async def set_video_draft_fields(self, user_email: str, job_id: str, *,
                                     style: str | None = None, voice: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if style is not None:
            body["style"] = style
        if voice is not None:
            body["voice"] = voice
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/draft-set", user_email, json=body)
        return resp.json()
```

with:

```python
    async def set_video_draft_fields(self, user_email: str, job_id: str, *,
                                     style: str | None = None, voice: str | None = None,
                                     title: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if style is not None:
            body["style"] = style
        if voice is not None:
            body["voice"] = voice
        if title is not None:
            body["title"] = title
        if prompt is not None:
            body["prompt"] = prompt
        resp = await self._request("POST", f"/api/video-jobs/{job_id}/draft-set", user_email, json=body)
        return resp.json()
```

- [ ] **Step 4: Run it to verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_video_new.py::test_set_video_draft_fields_includes_title_and_prompt -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/clients/tasks.py webhook-handler/tests/test_video_new.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): set_video_draft_fields accepts title/prompt

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: video_panel — details modal/button, prefixes, studio components, embed; drop the create-modal

**Files:**
- Modify: `webhook-handler/handlers/video_panel.py`
- Test: `webhook-handler/tests/test_video_panel.py`

- [ ] **Step 1: Update the test file (imports + new/changed tests)**

In `webhook-handler/tests/test_video_panel.py`:

(a) In the import block, remove `build_video_modal`, `NEW_MODAL_ID`, `is_vid_new_modal`; add `build_details_modal`, `DETAILS_PREFIX`, `DETAILS_MODAL_PREFIX`, `is_vid_details`, `is_vid_details_modal`, `job_from_details`, `job_from_details_modal`, `STYLE_SECONDARY` is not needed. The builders line and constants/predicates/extractors lines become:

```python
from handlers.video_panel import (
    # builders
    build_video_panel, build_details_modal, build_refine_modal,
    build_style_select, build_voice_select, build_studio_components,
    build_generate_row, build_done_components, build_proposal_components,
    build_video_embed,
    # constants
    NEW_ID, LIST_ID,
    STYLE_PREFIX, VOICE_PREFIX, GENERATE_PREFIX, DETAILS_PREFIX, DETAILS_MODAL_PREFIX,
    REFINE_PREFIX, REFINE_MODAL_PREFIX, APPLY_PREFIX, VERSION_PREFIX,
    TITLE_INPUT, PROMPT_INPUT, REFINE_INPUT,
    STYLES,
    # predicates
    is_vid_new, is_vid_list, is_vid_details, is_vid_details_modal,
    is_vid_style, is_vid_voice, is_vid_generate,
    is_vid_refine, is_vid_refine_modal, is_vid_apply, is_vid_version,
    # extractors
    job_from_style, job_from_voice, job_from_generate, job_from_details, job_from_details_modal,
    job_from_refine, job_from_refine_modal, job_from_apply, job_from_version,
)
```

(b) Replace `test_modal_field_custom_ids` and `test_modal_fields_required` (the two `build_video_modal()` tests) with:

```python
def test_details_modal_custom_id_and_inputs():
    modal = build_details_modal("job-d1")
    assert modal["custom_id"] == f"{DETAILS_MODAL_PREFIX}job-d1"
    inputs = [c for row in modal["components"] for c in row["components"]
              if c.get("type") == TEXT_INPUT]
    input_ids = [inp["custom_id"] for inp in inputs]
    assert input_ids == [TITLE_INPUT, PROMPT_INPUT]
    by_id = {inp["custom_id"]: inp for inp in inputs}
    assert by_id[TITLE_INPUT].get("required") is False
    assert by_id[PROMPT_INPUT].get("required") is True


def test_details_prefix_predicates_disjoint():
    assert is_vid_details(f"{DETAILS_PREFIX}j1") is True
    assert is_vid_details(f"{DETAILS_MODAL_PREFIX}j1") is False
    assert is_vid_details_modal(f"{DETAILS_MODAL_PREFIX}j1") is True
    assert is_vid_details_modal(f"{DETAILS_PREFIX}j1") is False
    assert job_from_details(f"{DETAILS_PREFIX}j1") == "j1"
    assert job_from_details_modal(f"{DETAILS_MODAL_PREFIX}j1") == "j1"
```

(c) In `test_studio_components_has_style_voice_generate_rows`, after the row-2 generate assertion, add a details-button assertion (rows stay 3; the last row holds both buttons):

```python
    # row 2 also has the Add-title-&-description button
    assert any(c.get("custom_id") == f"{DETAILS_PREFIX}job-s1" for c in rows[2]["components"])
```

(d) Replace `test_video_embed_mentions_video_new_command` with:

```python
def test_video_embed_is_slash_free_and_mentions_drop():
    embed = build_video_embed()
    assert "/video" not in embed["description"]
    assert "drop" in embed["description"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: FAIL — ImportError (new names not defined yet).

- [ ] **Step 3: Edit `video_panel.py`**

(a) Constants — replace the line `NEW_MODAL_ID = "aiuivid:newmodal"` with:

```python
DETAILS_PREFIX = "aiuivid:details:"
DETAILS_MODAL_PREFIX = "aiuivid:detailsmodal:"
```

(b) Replace the whole `build_video_modal` function with `build_details_modal`:

```python
def build_details_modal(job_id: str) -> dict:
    return {
        "title": "Title & description"[:45],
        "custom_id": f"{DETAILS_MODAL_PREFIX}{job_id}",
        "components": [
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": TITLE_INPUT,
                "label": "Title (optional)", "style": TEXT_SHORT, "required": False,
                "max_length": 200, "placeholder": "e.g. Dashboard walkthrough",
            }]},
            {"type": ACTION_ROW, "components": [{
                "type": TEXT_INPUT, "custom_id": PROMPT_INPUT,
                "label": "Describe the narrated walkthrough",
                "style": TEXT_PARAGRAPH, "required": True, "max_length": 2000,
                "placeholder": "Walk the dashboard, highlight the charts, end on export.",
            }]},
        ],
    }
```

(c) Replace `build_studio_components` with (Add-details + Generate share the last row, so it stays 3 rows):

```python
def build_studio_components(job_id: str, voices: list[dict]) -> list[dict]:
    return [
        {"type": ACTION_ROW, "components": [build_style_select(job_id)]},
        {"type": ACTION_ROW, "components": [build_voice_select(job_id, voices)]},
        {"type": ACTION_ROW, "components": [
            _button("Add title & description", f"{DETAILS_PREFIX}{job_id}", STYLE_SECONDARY),
            _button("Generate video", f"{GENERATE_PREFIX}{job_id}", STYLE_SUCCESS)]},
    ]
```

(d) Replace the `build_video_embed` description block with the slash-free click flow:

```python
        "description": (
            "```\n"
            "> turn screenshots into a narrated walkthrough\n"
            "> 1. click New video below\n"
            "> 2. drag-and-drop your screenshots into the thread that opens\n"
            "> 3. add a description, pick style + voice, hit Generate\n"
            "```"
        ),
```

(e) Replace `def is_vid_new_modal(c: str) -> bool: return c == NEW_MODAL_ID` with:

```python
def is_vid_details(c: str) -> bool: return c.startswith(DETAILS_PREFIX)
def is_vid_details_modal(c: str) -> bool: return c.startswith(DETAILS_MODAL_PREFIX)
```

(f) In the extractors block (next to `job_from_style` etc.), add:

```python
def job_from_details(c: str) -> str: return _suffix_after(c, DETAILS_PREFIX)
def job_from_details_modal(c: str) -> str: return _suffix_after(c, DETAILS_MODAL_PREFIX)
```

- [ ] **Step 4: Run the panel tests**

Run: `cd webhook-handler && python -m pytest tests/test_video_panel.py -q`
Expected: PASS. (NOTE: `discord_commands.py` still imports/uses the removed symbols — the full suite will fail until Task 4; that is expected. This task's gate is `test_video_panel.py` passing.)

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/video_panel.py webhook-handler/tests/test_video_panel.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): details modal/button + slash-free panel; drop create-modal

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Bot routing — New→studio, details modal+submit, studio copy

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (`is_vid_new` 392-393; modal route 1163-1164; remove `_handle_video_new_modal` ~1005; `_open_video_studio` else-message)
- Modify: `webhook-handler/handlers/commands.py` (`run_video_set_field` ~2380 — add `run_video_set_details` after it)
- Test: `webhook-handler/tests/test_video_routing.py`, `webhook-handler/tests/test_video_new.py`

- [ ] **Step 1: Update `test_video_routing.py` (the two New-flow tests)**

(a) Replace `test_new_button_opens_new_modal` with a studio-open test:

```python
@pytest.mark.asyncio
async def test_new_button_opens_studio_deferred():
    """Clicking New video ACKs ephemeral-deferred and opens the studio with an
    EMPTY draft (title 'Untitled video', blank prompt) in the background."""
    router = _router()
    router._resolve_email = AsyncMock(return_value="u@x.com")
    tc = MagicMock()
    tc.create_video_draft = AsyncMock(return_value={"id": "jobN"})
    tc.get_video_voices = AsyncMock(return_value={"voices": []})
    tc.fetch_bytes = AsyncMock(return_value=b"mp3")
    router._tasks_client = tc
    handler = _handler(router)
    discord = handler.discord
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    discord.post_channel_file = AsyncMock(return_value=True)
    handler._get_or_make_thread = AsyncMock(return_value="thread-n")
    payload = {"type": 3, "id": "i", "token": "t", "channel_id": "c",
               "member": {"user": {"id": "100", "username": "alice"}},
               "data": {"custom_id": vid.NEW_ID}}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    tc.create_video_draft.assert_awaited_once_with(
        "u@x.com", "Untitled video", "", "clean_product_demo", "amy")
    assert discord.post_channel_message.await_args.args[0] == "thread-n"
```

(b) Replace `test_new_video_modal_submit_acks_ephemeral_deferred` with a details-modal submit test:

```python
@pytest.mark.asyncio
async def test_details_modal_submit_sets_title_and_prompt():
    """Add-title-&-description modal submit ACKs ephemeral-deferred and patches
    the draft's title/prompt via set_video_draft_fields."""
    router = _router()
    router._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    tc = MagicMock()
    tc.set_video_draft_fields = AsyncMock(return_value={"status": "ok"})
    router._tasks_client = tc
    handler = _handler(router)
    handler.discord.edit_original = AsyncMock(return_value=True)
    payload = {
        "type": 5, "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": f"{vid.DETAILS_MODAL_PREFIX}job7", "components": [
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.TITLE_INPUT, "value": "Dash"}]},
            {"type": 1, "components": [
                {"type": 4, "custom_id": vid.PROMPT_INPUT, "value": "walk it"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()
    tc.set_video_draft_fields.assert_awaited_once_with(
        "u@x.com", "job7", title="Dash", prompt="walk it")
```

(If `_router()` in this file doesn't set `run_video_set_details`/`run_video_set_field` as real methods, note that `_router()` builds a real `CommandRouter` (see top of file) so the runners exist; only the tasks client + email resolver are mocked.)

- [ ] **Step 2: Update the studio-open test in `test_video_new.py`**

In `webhook-handler/tests/test_video_new.py`, in `test_open_video_studio_without_screenshots_skips_add`, change the final assertion from `"drop your screenshots here"` to the new copy:

```python
    assert "drag your screenshots" in content.lower()
```

- [ ] **Step 3: Run the routing + studio tests to verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_video_routing.py tests/test_video_new.py -q`
Expected: FAIL — `is_vid_new` still returns MODAL / `DETAILS_MODAL_PREFIX` route not wired / studio copy unchanged.

- [ ] **Step 4: Edit `discord_commands.py`**

(a) Replace the `is_vid_new` branch:

```python
        if vid.is_vid_new(custom_id):
            return {"type": MODAL, "data": vid.build_video_modal()}
```

with (open the studio with an empty draft) + add the details-button branch right after:

```python
        if vid.is_vid_new(custom_id):
            member = payload.get("member", {})
            user = member.get("user", payload.get("user", {}))
            self._spawn(self._open_video_studio(
                interaction_token=payload.get("token", ""),
                user_id=user.get("id", ""),
                user_name=user.get("username", "unknown"),
                channel_id=payload.get("channel_id", ""),
                title="Untitled video", prompt="", screenshot_urls=None))
            return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
        if vid.is_vid_details(custom_id):
            try:
                job_id = vid.job_from_details(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return {"type": MODAL, "data": vid.build_details_modal(job_id)}
```

(b) Replace the modal-submit route:

```python
        if vid.is_vid_new_modal(custom_id):
            return await self._handle_video_new_modal(payload)
```

with:

```python
        if vid.is_vid_details_modal(custom_id):
            return await self._handle_video_details_modal(payload)
```

(c) Remove the entire `_handle_video_new_modal` method (the thin caller added earlier — `async def _handle_video_new_modal(...)` through its `return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}`) and replace it with `_handle_video_details_modal`:

```python
    async def _handle_video_details_modal(self, payload: dict[str, Any]) -> dict[str, Any]:
        """'Add title & description' modal submit → patch the draft's title/prompt.
        ACK ephemeral-deferred within 3s."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        try:
            job_id = vid.job_from_details_modal(custom_id)
        except ValueError:
            return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
        title = self._extract_modal_value(data, vid.TITLE_INPUT) or None
        prompt = self._extract_modal_value(data, vid.PROMPT_INPUT)
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="video details",
            subcommand="video", arguments="", platform="discord", respond=respond)
        self._spawn(self.router.run_video_set_details(ctx, job_id, title=title, prompt=prompt))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

(d) In `_open_video_studio`, replace the no-screenshots `studio_msg` else-branch:

```python
            else:
                studio_msg = (
                    "Pick a style + voice, then **drop your screenshots here** "
                    "(or use `/video add`), then hit **Generate video**."
                )
```

with:

```python
            else:
                studio_msg = (
                    "Drag your screenshots into this thread (up to 12). Then click "
                    "**Add title & description**, pick a style + voice, and hit "
                    "**Generate video**."
                )
```

- [ ] **Step 5: Add `run_video_set_details` in `commands.py`**

In `webhook-handler/handlers/commands.py`, immediately AFTER the `run_video_set_field` method (it ends with the `except TasksAPIError as e: logger.warning(...)` block), add:

```python
    async def run_video_set_details(self, ctx: CommandContext, job_id: str, *,
                                    title: str | None = None, prompt: str | None = None) -> None:
        """Add-title-&-description submit: patch the draft's title/prompt."""
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        try:
            await self._tasks_client.set_video_draft_fields(
                email, job_id, title=title, prompt=prompt)
        except TasksAPIError as e:
            await ctx.respond(f"Couldn't save: {e.message}")
            return
        await ctx.respond(
            "Saved. Drag your screenshots in, pick a style + voice, then hit Generate video.")
```

- [ ] **Step 6: Run routing + studio tests, then the full bot suite**

Run: `cd webhook-handler && python -m pytest tests/test_video_routing.py tests/test_video_new.py -q && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" add webhook-handler/handlers/discord_commands.py webhook-handler/handlers/commands.py webhook-handler/tests/test_video_routing.py webhook-handler/tests/test_video_new.py
git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" commit -m "feat(video): New video opens the upload thread; Add title & description button

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification

- [ ] **Step 1: Bot suite**

Run: `cd webhook-handler && python -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Tasks offline suite**

Run: `cd mcp-servers/tasks && python -m pytest -q`
Expected: all pass (DB tests skip offline).

- [ ] **Step 3: Review diff + clean tree**

Run: `git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" status --short && git -C "C:/Users/alama/Desktop/Lukas Work/IO-integrate" log --oneline 115776242..HEAD`

---

## Task 6: Deploy to production (GATED — confirm with the user first)

**Do not run until the user confirms.** Two services change: `tasks` (backend) and `webhook-handler` (bot). Per-file scp (never `scp -r`).

- [ ] **Step 1: SSH + drift-check the 4 files to overwrite** (`mcp-servers/tasks/routes_video.py`, `webhook-handler/{clients/tasks.py,handlers/video_panel.py,handlers/discord_commands.py}`): CRLF-normalized hash server-vs-`git show <last-deployed-sha>:<path>`. If unexpected drift, STOP.

- [ ] **Step 2: Deploy backend (tasks)**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
scp mcp-servers/tasks/routes_video.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/routes_video.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
```

- [ ] **Step 3: Run the backend DB tests on the server** (real Postgres `aiui_test`), per the established runner pattern (docker cp the two test files into the tasks container, `docker exec` with `AIUI_TEST_DB=1` + a `DATABASE_URL` containing `test`). Expected: the new draft/queue DB tests PASS.

- [ ] **Step 4: Deploy bot (webhook-handler)**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate/webhook-handler"
scp clients/tasks.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
scp handlers/video_panel.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/video_panel.py
scp handlers/discord_commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/discord_commands.py
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler && docker compose -f docker-compose.unified.yml logs --tail 30 webhook-handler"
```
Expected: `Up (healthy)`, `Conversational voice bot ready`, no traceback. (`commands.py` is also changed — scp it too: `scp handlers/commands.py root@…/webhook-handler/handlers/commands.py` BEFORE the rebuild.)

- [ ] **Step 5: Refresh the channel panel** so the card shows the slash-free click flow (edit the existing panel message in place if possible, else re-post). No command re-registration needed.

- [ ] **Step 6: Live e2e** (in-container against the live backend): click-equivalent — create empty draft via `POST /draft {}` → draft-set title/prompt → add a screenshot by URL → `POST /queue` with blank prompt returns 400 "Add a description first"; with prompt set returns queued. Plus a manual New video click in Discord: lands in thread, drag a screenshot, Add title & description, Generate.
