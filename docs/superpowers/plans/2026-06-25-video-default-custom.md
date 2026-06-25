# Default vs Custom Video Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a video source is ready, let the user pick Default ("Generate now", the AI directs a kinetic animated video) or Custom ("Add direction", free-text). webhook-handler only; the brain (live) handles the empty-prompt Default.

**Architecture:** A new Discord choice card replaces the "Add description" card at all four sites that post it. A "Generate now" button (new `aiuivid:gennow:` id) routes through `_handle_video_route` to a new runner that sets render_mode=animated then generates. "Add direction" reuses the existing details button. On Slack, the single modal's description becomes optional and the mode default flips to animated.

**Tech Stack:** Python, discord.py-style raw components, Slack Block Kit, pytest.

**Spec:** `docs/superpowers/specs/2026-06-25-video-default-custom-design.md`

**Conventions:** run tests from `webhook-handler/`: `cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest ...`. NO em-dashes in code/comments OR user-facing strings. Commits plain, no AI attribution. Windows + Git Bash; `python` (fallback `py`). Async tests: match the file's convention.

---

## File Structure
- Modify: `webhook-handler/handlers/video_panel.py` — `build_choice_components` + `aiuivid:gennow:` id/predicate/extractor.
- Modify: `webhook-handler/handlers/commands.py` — `run_video_gennow` runner; swap the 2 runner posters (capture, first-add) to the choice card.
- Modify: `webhook-handler/handlers/discord_commands.py` — gennow handler via `_handle_video_route`; swap `_post_video_describe` + the `/video new` pre-attached poster to the choice card.
- Modify: `webhook-handler/handlers/slack_video_panel.py` — description optional + `DEFAULT_MODE="animated"`.
- Tests: `tests/test_video_panel.py`, `tests/test_video_runners.py`, `tests/test_video_routing.py`, `tests/test_slack_video_panel.py`.

---

## Task DC1: Choice-card builder + gennow id

**Files:** Modify `handlers/video_panel.py`; modify `tests/test_video_panel.py`.

- [ ] **Step 1: Append failing tests** to tests/test_video_panel.py (use the file's `vp` alias / import style):

```python
def test_build_choice_components_two_buttons():
    rows = vp.build_choice_components("job1")
    ids = [c["custom_id"] for r in rows for c in r["components"]]
    assert ids == ["aiuivid:gennow:job1", "aiuivid:details:job1"]


def test_gennow_predicate_round_trips():
    assert vp.is_vid_gennow("aiuivid:gennow:j") and vp.job_from_gennow("aiuivid:gennow:j") == "j"


def test_gennow_disjoint_from_generate_and_details():
    assert vp.is_vid_gennow("aiuivid:generate:x") is False
    assert vp.is_vid_gennow("aiuivid:details:x") is False
    # and generate/details predicates do not match gennow
    assert vp.is_vid_generate("aiuivid:gennow:x") is False
    assert vp.is_vid_details("aiuivid:gennow:x") is False
```

- [ ] **Step 2: Run, confirm FAIL:** `cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_panel.py -k "choice or gennow" -v`

- [ ] **Step 3: Implement** in video_panel.py.
(a) Add the constant near the other prefixes (DETAILS_PREFIX, GENERATE_PREFIX, ~lines 13-31): `GENNOW_PREFIX = "aiuivid:gennow:"`.
(b) Add the builder (DETAILS_PREFIX and GENERATE_PREFIX already exist; reuse `_button`, ACTION_ROW, STYLE_SUCCESS, STYLE_SECONDARY as the other builders do):
```python
def build_choice_components(job_id: str) -> list[dict]:
    return [{"type": ACTION_ROW, "components": [
        _button("Generate now", f"{GENNOW_PREFIX}{job_id}", STYLE_SUCCESS),
        _button("Add direction", f"{DETAILS_PREFIX}{job_id}", STYLE_SECONDARY)]}]
```
(c) Add predicate + extractor with the others:
```python
def is_vid_gennow(c: str) -> bool: return c.startswith(GENNOW_PREFIX)
def job_from_gennow(c: str) -> str: return _suffix_after(c, GENNOW_PREFIX)
```
Keep `build_describe_components` exported (other tests import it).

- [ ] **Step 4: Run, confirm PASS** (full file): `cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_panel.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add webhook-handler/handlers/video_panel.py webhook-handler/tests/test_video_panel.py && git commit -m "feat(video): choice-card builder (Generate now / Add direction) + gennow id"
```

---

## Task DC2: run_video_gennow + swap the two runner posters

**Files:** Modify `handlers/commands.py`; modify `tests/test_video_runners.py`.

- [ ] **Step 1: Append failing tests** to tests/test_video_runners.py (mirror its fixtures/mocks; read the file head). Cover (a) capture posts the choice card, (b) first-add posts the choice card, (c) run_video_gennow sets render_mode=animated then generates:

```python
async def test_run_video_capture_posts_choice_card(monkeypatch):
    # adapt to the file's existing run_video_capture test harness:
    # assert the posted components == build_choice_components(job_id)
    # (contains custom_ids aiuivid:gennow:<job> and aiuivid:details:<job>)
    ...


async def test_run_video_gennow_sets_animated_then_generates(monkeypatch):
    # mock the tasks client + run_video_generate; assert
    # set_video_draft_fields was awaited with render_mode="animated" BEFORE
    # queue_video / run_video_generate was awaited.
    ...
```
NOTES (verified against the real harness):
- test_video_runners.py uses `_router()` (CommandRouter.__new__, real methods) + `_ctx()` + a MagicMock tasks client. run_video_gennow calls the REAL run_video_set_field -> `tc.set_video_draft_fields` and REAL run_video_generate -> `tc.queue_video`. So assert on those two AsyncMocks; do NOT mock run_video_generate. Assert ordering (set_video_draft_fields with render_mode="animated" BEFORE queue_video) via the parent mock's `mock_calls`. Default `notify_channel=None` means no watcher spawns -> test stays hermetic.
- `run_video_set_field(self, ctx, job_id, *, style=None, voice=None, render_mode=None)` takes explicit keyword-only kwargs (confirmed) — `run_video_set_field(ctx, job_id, render_mode="animated")` is valid.
- The EXISTING tests at test_video_runners.py:35 and :286 assert the details button id is present; since build_choice_components STILL contains the details button, they keep passing unchanged (they will NOT fail at Step 2). The NEW tests asserting the gennow id are what drive the change. Optionally rename the two old tests for clarity.

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in commands.py.
(a) `run_video_capture` (~line 2416-2417): change the success post from `build_describe_components(draft["id"])` to `build_choice_components(draft["id"])` (update the import accordingly). Keep the progress message.
(b) `run_video_add` (~line 2375-2381, the `prior_count == 0` branch): change `build_describe_components(draft["id"])` to `build_choice_components(draft["id"])`. The subsequent-add echo (~:2384) is unchanged.
(c) Add a new runner mirroring `run_video_set_field` (:2421-2430) + `run_video_generate` (:2453-2470):
```python
async def run_video_gennow(self, ctx, job_id: str) -> None:
    """Default path: force kinetic animated, then queue + watch + deliver. The
    brain scripts the whole video from an empty prompt."""
    await self.run_video_set_field(ctx, job_id, render_mode="animated")
    await self.run_video_generate(ctx, job_id)
```
(Match the real method signatures — `run_video_set_field(self, ctx, job_id, **fields)` and `run_video_generate(self, ctx, job_id)`. If run_video_set_field takes explicit kwargs, pass render_mode accordingly. Read :2421 to confirm.)

- [ ] **Step 4: Run, confirm PASS** + the existing runner tests:
`cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_video_runners.py -v`
(test_video_runners.py:36 asserted first-add posts build_describe_components — update it to build_choice_components.)

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add webhook-handler/handlers/commands.py webhook-handler/tests/test_video_runners.py && git commit -m "feat(video): run_video_gennow (animated + generate) + post choice card after capture/add"
```

---

## Task DC3: gennow handler + remaining two poster sites

**Files:** Modify `handlers/discord_commands.py`; modify `tests/test_video_routing.py`.

- [ ] **Step 1: Append failing tests** to tests/test_video_routing.py (mirror its dispatch-assertion style):

```python
# Mirror test_generate_dispatches_and_binds_notify_channel (test_video_routing.py:199).
# CRITICAL: _router() does NOT define run_video_gennow -> it auto-creates a NON-async
# MagicMock, and _spawn(create_task(...)) would raise. So in the test, set
# r.run_video_gennow = AsyncMock() on the router (mirror how run_video_generate is set).
async def test_gennow_dispatches_to_gennow_runner(...):
    # block_actions payload, custom_id aiuivid:gennow:<job>; assert the gennow
    # runner is scheduled and notify_channel is bound (same as the generate test).
    ...
```
Read test_generate_dispatches_and_binds_notify_channel (:199-217) and mirror it exactly, including the `r.run_video_gennow = AsyncMock()` setup.

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in discord_commands.py.
(a) Add a routing branch next to the generate handler (`is_vid_generate` at :433-440). The REAL generate branch wraps the id-extract in `try/except ValueError: return {"type": DEFERRED_UPDATE_MESSAGE}` and passes a `raw_text=...` to `_handle_video_route`. COPY THAT EXACT SHAPE, substituting gennow:
```python
        if vid.is_vid_gennow(custom_id):
            try:
                job_id = vid.job_from_gennow(custom_id)
            except ValueError:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_video_route(
                payload, lambda ctx, j=job_id: self.router.run_video_gennow(ctx, j),
                raw_text="video gennow")
```
(Read the real is_vid_generate branch and match its exact arg names; the ack type DEFERRED_CHANNEL_MESSAGE+flags:64 is inherited from _handle_video_route.)
(b) `_post_video_describe` (~:939-949): change the posted components from `build_describe_components(job_id)` to `build_choice_components(job_id)`, and update the message text (~:948) from the "Add a short description..." wording to choice wording, e.g. "Screenshots ready. Generate now (I will direct it) or add your own direction.".
(c) `/video new` pre-attached block (~:1085-1089): change its `build_describe_components(job_id)` post to `build_choice_components(job_id)`. Do NOT change that block's surrounding text (test_video_new.py:43-44 asserts "description" appears in the studio text; leave the text, swap only the components).
(d) NO import edit needed: discord_commands.py uses the module alias `from handlers import video_panel as vid` (:84), so `vid.build_choice_components` works as soon as the function exists. (The import note applies only to commands.py, which uses named local imports.)

- [ ] **Step 4: Run, confirm PASS** + the routing + new suites + import check:
`cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -c "import handlers.discord_commands; print('import ok')" && python -m pytest tests/test_video_routing.py tests/test_video_new.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_video_routing.py && git commit -m "feat(video): gennow handler via _handle_video_route + choice card on screenshot + /video new paths"
```

---

## Task DC4: Slack optional description + animated default

**Files:** Modify `handlers/slack_video_panel.py`; modify `tests/test_slack_video_panel.py`.

- [ ] **Step 1: Append failing tests** to tests/test_slack_video_panel.py:

```python
def test_video_modal_description_is_optional():
    view = build_video_modal("C123")   # file uses NAMED imports, no `svp` alias
    prompt_block = next(b for b in view["blocks"] if b.get("block_id") == "prompt")
    assert prompt_block.get("optional") is True


def test_default_mode_is_animated():
    assert DEFAULT_MODE == "animated"   # DEFAULT_MODE already imported at test top (:24)
```
NOTE: test_slack_video_panel.py uses NAMED imports (`from handlers.slack_video_panel import build_video_modal, DEFAULT_MODE, ...` at :5/:24) - do NOT add `svp.` or a bare `from slack_video_panel import`. The prompt block_id is "prompt" (confirmed); adapt if the builder differs.

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** in slack_video_panel.py.
(a) Flip the module constant (~:38): `DEFAULT_MODE = "animated"` (drives both the mode select initial_option and the parse fallback `_sel(..., DEFAULT_MODE)`).
(b) In `build_video_modal`, make the Description input optional: pass `optional=True` to its `_plain_input(...)` call (~:188-193) and add a hint to its label or placeholder: "Leave blank to let the AI direct it." Confirm `_plain_input` supports an `optional` flag (it should set `"optional": True` on the input block); if not, add the flag to the block dict directly.

- [ ] **Step 4: Run, confirm PASS** (full file): `cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/test_slack_video_panel.py -v`

- [ ] **Step 5: Commit:**
```bash
cd "C:/All/Work - Code/ai_ui" && git add webhook-handler/handlers/slack_video_panel.py webhook-handler/tests/test_slack_video_panel.py && git commit -m "feat(video): Slack description optional (blank = AI directs) + default animated"
```

---

## Task DC5: Verification + deploy

- [ ] **Step 1: Full video suite:** `cd "C:/All/Work - Code/ai_ui/webhook-handler" && python -m pytest tests/ -k video -q` -> no new failures.
- [ ] **Step 2: import + em-dash scan:**
`python -c "import handlers.discord_commands, handlers.video_panel, handlers.commands, handlers.slack_video_panel; print('ok')"`
`grep -nP "[\x{2013}\x{2014}]" handlers/video_panel.py handlers/commands.py handlers/discord_commands.py handlers/slack_video_panel.py | grep -iE "generate now|add direction|gennow|direct it" || echo clean`
- [ ] **Step 3: Deploy (webhook-handler only; follow CLAUDE.md).**
Changed files: handlers/video_panel.py, handlers/commands.py, handlers/discord_commands.py, handlers/slack_video_panel.py. Drift-check each against the running container (normalized), upload LF via `git show HEAD:path | ssh -i ~/.ssh/aiui_vps ... "cat > /root/proxy-server/<path>"`, then `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`, verify the container is Up + gateway connected.
- [ ] **Step 4: Manual verify:** New video -> From a website -> paste URL -> on the choice card click "Generate now" -> a kinetic video renders with no description. Then "Add direction" (Custom) still works. Slack: submit the modal with a blank description -> generates.

---

## Out of scope
- Sub-project 2: kinetic renderer polish (separate).
- Any tasks-service change (the brain already handles empty prompts).
