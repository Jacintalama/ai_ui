# Recruiting Outreach Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-button "Find Engineers" flow to the Discord + Slack bots that finds software engineers (GitHub + web), emails them a job description, and logs everyone to a Google Sheet — agent finds+drafts, n8n sends+logs.

**Architecture:** Bot button → modal → `CommandRouter.run_panel_outreach` → tasks service `POST /outreach` creates a `TaskItem` and runs the AI agent (find+draft, emits one ```json block then `COMPLETED`). `_run_outreach` (tasks) extracts the JSON via `extract_final_body`, caps/dedupes, POSTs to the n8n `recruiting-outreach` webhook via raw `httpx` (mirroring `routes_cron.py`), stores a summary. A detached `_watch_outreach` watcher (mirror of `_watch_build`) polls `GET /outreach/{task_id}` and posts the summary to the user's thread.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, httpx, pydantic; Discord HTTP interactions + Block Kit; pytest/pytest-asyncio; n8n (hosted) workflow JSON.

**Spec:** `docs/superpowers/specs/2026-06-08-recruiting-outreach-design.md`

**Sub-skills:** @superpowers:test-driven-development for every task; @superpowers:verification-before-completion before claiming done.

---

## Conventions & guardrails (read once)

- **Test runners:**
  - webhook-handler: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest <path> -v`
  - tasks PURE modules (no DB): `cd mcp-servers/tasks; python -m pytest <path> -v` — only for modules that do NOT import a DB session.
  - **NEVER run the tasks DB-backed tests against production.** `mcp-servers/tasks/tests/conftest.py`'s `db_session` fixture TRUNCATEs prod tables (the 2026-04-27 incident wiped 9 projects). All tasks tests in this plan are pure (no `db_session`) and import the unit under test directly.
- **Line endings:** local files are CRLF; the server is LF. Deploy is out of scope for this plan (a separate deploy step after merge), but keep new files LF-clean where the tooling allows.
- **DRY:** mirror existing patterns exactly; do not invent new abstractions.
- **Commit after every task** (the granularity below).
- Work happens on branch `feat/recruiting-outreach` (already created).

## File Structure

**webhook-handler (the bots):**
- Create `webhook-handler/handlers/recruiting_panel.py` — Discord pure builders (panel, embed, modal, custom_id predicates, `parse_outreach_modal`). Mirrors `app_builder_panel.py`.
- Create `webhook-handler/handlers/slack_recruiting_panel.py` — Slack Block Kit panel + modal view + `outreach_fields_from_view`. Mirrors `slack_schedule_panel.py`.
- Modify `webhook-handler/handlers/discord_commands.py` — route `is_out_find` (→ modal) and `is_out_modal` (→ background `run_panel_outreach`).
- Modify `webhook-handler/handlers/slack_interactions.py` — route the Slack outreach button + view_submission.
- Modify `webhook-handler/clients/tasks.py` — `start_outreach`, `get_outreach_status`.
- Modify `webhook-handler/handlers/commands.py` — `run_panel_outreach` + `_watch_outreach` (+ `OUTREACH_*` poll constants).

**tasks service (the brain):**
- Create `mcp-servers/tasks/outreach.py` — pure logic: `CandidateList` pydantic model, `extract_candidates(raw_log)`, `cap_and_dedupe(candidates, count)`, `build_outreach_prompt(...)`, `post_outreach_to_n8n(...)`, `format_outreach_summary(...)`. No DB imports.
- Create `mcp-servers/tasks/routes_outreach.py` — `POST /outreach`, `GET /outreach/{task_id}`, and the `_run_outreach` background coroutine.
- Modify `mcp-servers/tasks/main.py` — `include_router(routes_outreach.router)`.

**infra / ops:**
- Create `n8n-workflows/recruiting-outreach.json` — the send+log workflow.
- Modify `docker-compose.unified.yml` — add `GITHUB_TOKEN` to the tasks service env.
- Create `docs/recruiting-outreach-setup.md` — one-time operator setup.

---

## Task 1: Discord pure builders (`recruiting_panel.py`)

**Files:**
- Create: `webhook-handler/handlers/recruiting_panel.py`
- Test: `webhook-handler/tests/test_recruiting_panel.py`

Mirror `webhook-handler/handlers/app_builder_panel.py` (component constants, `_button`, `is_*` predicates).

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_recruiting_panel.py
import pytest
from handlers import recruiting_panel as rp


def test_panel_has_find_and_link_buttons():
    payload = rp.build_recruiting_panel()
    ids = [c["custom_id"] for row in payload["components"] for c in row["components"]
           if "custom_id" in c]
    assert rp.OUT_FIND_ID in ids
    # reuses the existing self-service Link button
    from handlers.app_builder_panel import LINK_START_ID
    assert LINK_START_ID in ids


def test_modal_has_four_inputs_in_order():
    modal = rp.build_outreach_modal()
    assert modal["custom_id"] == rp.OUT_MODAL_ID
    input_ids = [row["components"][0]["custom_id"] for row in modal["components"]]
    assert input_ids == [rp.OUT_ROLE_INPUT, rp.OUT_LOCATION_INPUT,
                         rp.OUT_JOBDESC_INPUT, rp.OUT_COUNT_INPUT]
    # jobdesc is a paragraph; role/location/count are short
    styles = {row["components"][0]["custom_id"]: row["components"][0]["style"]
              for row in modal["components"]}
    assert styles[rp.OUT_JOBDESC_INPUT] == 2   # paragraph
    assert styles[rp.OUT_ROLE_INPUT] == 1      # short


def test_is_predicates():
    assert rp.is_out_find(rp.OUT_FIND_ID)
    assert not rp.is_out_find("aiuiout:nope")
    assert rp.is_out_modal(rp.OUT_MODAL_ID)
    assert not rp.is_out_modal("aiuibuild:build:")


@pytest.mark.parametrize("raw,expected", [
    ({"count": "10"}, 10),
    ({"count": ""}, 10),       # default
    ({"count": "0"}, 1),       # clamp low
    ({"count": "99"}, 25),     # clamp high
    ({"count": "abc"}, 10),    # non-numeric -> default
    ({}, 10),                  # missing -> default
])
def test_parse_outreach_modal_count(raw, expected):
    values = {rp.OUT_ROLE_INPUT: "Python", rp.OUT_LOCATION_INPUT: "",
              rp.OUT_JOBDESC_INPUT: "Hiring", **{rp.OUT_COUNT_INPUT: raw.get("count", "")}}
    role, location, jobdesc, count = rp.parse_outreach_modal(values)
    assert count == expected
    assert role == "Python"
    assert jobdesc == "Hiring"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: handlers.recruiting_panel`.

- [ ] **Step 3: Write the implementation**

```python
# webhook-handler/handlers/recruiting_panel.py
"""Pure builders for the #recruiting channel panel + outreach modal.

No I/O. Mirrors handlers/app_builder_panel.py. Imported by the Discord
interaction handler and unit-tested in tests/test_recruiting_panel.py.
"""
from __future__ import annotations

from handlers.app_builder_panel import (
    ACTION_ROW, BUTTON, TEXT_INPUT, STYLE_SUCCESS, STYLE_PRIMARY,
    TEXT_SHORT, TEXT_PARAGRAPH, ROBOTIC_CYAN, LINK_START_ID, _button,
)

__all__ = [
    "OUT_FIND_ID", "OUT_MODAL_ID", "OUT_ROLE_INPUT", "OUT_LOCATION_INPUT",
    "OUT_JOBDESC_INPUT", "OUT_COUNT_INPUT", "build_recruiting_panel",
    "build_recruiting_embed", "build_outreach_modal", "is_out_find",
    "is_out_modal", "parse_outreach_modal",
]

OUT_FIND_ID = "aiuiout:find"      # button (exact match)
OUT_MODAL_ID = "aiuiout:modal"    # modal submit (exact match)
OUT_ROLE_INPUT = "role"
OUT_LOCATION_INPUT = "location"
OUT_JOBDESC_INPUT = "jobdesc"
OUT_COUNT_INPUT = "count"

_DEFAULT_COUNT = 10
_MAX_COUNT = 25

PANEL_CONTENT = (
    "\U0001f3af **Recruiting Outreach**\n"
    "Find software engineers and email them a job in one click. Hit "
    "**\U0001f50d Find Engineers**, describe the role, and I'll search GitHub, "
    "email those I can reach, and save everyone to your shared sheet."
)


def build_recruiting_panel() -> dict:
    """Pinned #recruiting panel: Find Engineers + the self-service Link button."""
    row = {"type": ACTION_ROW, "components": [
        _button("\U0001f50d Find Engineers", OUT_FIND_ID, STYLE_SUCCESS),
        _button("\U0001f517 Link my account", LINK_START_ID, STYLE_PRIMARY),
    ]}
    return {"content": PANEL_CONTENT, "components": [row]}


def build_recruiting_embed() -> dict:
    """Terminal/console-styled embed for the #recruiting channel panel."""
    return {
        "title": "\U0001f3af AIUI · RECRUITING",
        "color": ROBOTIC_CYAN,
        "description": (
            "```\n"
            "> describe the role + paste a job description\n"
            "> source: github + web search\n"
            "> emails sent to those with a public address\n"
            "> everyone saved to your google sheet\n"
            "```"
        ),
        "footer": {"text": "AIUI · outreach unit"},
    }


def build_outreach_modal() -> dict:
    """Type-9 MODAL data: role, location, job description, count."""
    def _ti(cid, label, style, required, maxlen, placeholder):
        return {"type": ACTION_ROW, "components": [{
            "type": TEXT_INPUT, "custom_id": cid, "label": label, "style": style,
            "required": required, "max_length": maxlen, "placeholder": placeholder,
        }]}
    return {
        "title": "Find Engineers"[:45],
        "custom_id": OUT_MODAL_ID,
        "components": [
            _ti(OUT_ROLE_INPUT, "Skill / language", TEXT_SHORT, True, 100,
                "e.g. Python backend"),
            _ti(OUT_LOCATION_INPUT, "Location (optional)", TEXT_SHORT, False, 100,
                "e.g. Berlin"),
            _ti(OUT_JOBDESC_INPUT, "Job description", TEXT_PARAGRAPH, True, 4000,
                "We're hiring a senior backend engineer to ..."),
            _ti(OUT_COUNT_INPUT, "How many to email (max 25)", TEXT_SHORT, False, 3,
                "10"),
        ],
    }


def is_out_find(custom_id: str) -> bool:
    return custom_id == OUT_FIND_ID


def is_out_modal(custom_id: str) -> bool:
    return custom_id == OUT_MODAL_ID


def parse_outreach_modal(values: dict) -> tuple[str, str, str, int]:
    """Flattened {custom_id: value} -> (role, location, jobdesc, count).
    count defaults to 10 and is clamped to 1..25."""
    role = (values.get(OUT_ROLE_INPUT) or "").strip()
    location = (values.get(OUT_LOCATION_INPUT) or "").strip()
    jobdesc = (values.get(OUT_JOBDESC_INPUT) or "").strip()
    raw = (values.get(OUT_COUNT_INPUT) or "").strip()
    try:
        count = int(raw)
    except (TypeError, ValueError):
        count = _DEFAULT_COUNT
    count = max(1, min(_MAX_COUNT, count))
    return role, location, jobdesc, count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_panel.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/recruiting_panel.py webhook-handler/tests/test_recruiting_panel.py
git commit -m "feat(outreach): Discord recruiting panel + outreach modal builders"
```

---

## Task 2: Discord routing (button → modal, submit → background)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (component dispatch ~line 219-332; modal-submit dispatcher — find the `is_panel_modal` / `is_sched_modal` branch)
- Test: `webhook-handler/tests/test_recruiting_routing.py`

Mirror the schedules pattern: `test_schedules_ux_interactions.py` and the `is_sched_new` (→ `{"type": MODAL, ...}`) / `SCHED_MODAL_ID` submit branches.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_recruiting_routing.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers import recruiting_panel as rp


def _handler(router):
    d = MagicMock()
    return DiscordCommandHandler(discord_client=d, command_router=router)


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_find_button_opens_modal():
    handler = _handler(MagicMock())
    payload = {"type": 3, "id": "i", "token": "t",
               "data": {"custom_id": rp.OUT_FIND_ID},
               "member": {"user": {"id": "100", "username": "alice"}}, "channel_id": "c"}
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == rp.OUT_MODAL_ID


@pytest.mark.asyncio
async def test_modal_submit_dispatches_outreach():
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count):
        calls.append((role, location, jobdesc, count))
    router.run_panel_outreach = fake
    handler = _handler(router)
    payload = {
        "type": 5,  # MODAL_SUBMIT
        "id": "i", "token": "t", "channel_id": "c",
        "member": {"user": {"id": "100", "username": "alice"}},
        "data": {"custom_id": rp.OUT_MODAL_ID, "components": [
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_ROLE_INPUT, "value": "Python"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_LOCATION_INPUT, "value": "Berlin"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_JOBDESC_INPUT, "value": "Hiring a dev"}]},
            {"type": 1, "components": [{"type": 4, "custom_id": rp.OUT_COUNT_INPUT, "value": "8"}]},
        ]},
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # DEFERRED_CHANNEL_MESSAGE
    await _drain()
    assert calls == [("Python", "Berlin", "Hiring a dev", 8)]
```

> NOTE: confirm the MODAL_SUBMIT interaction type integer and the deferred ACK
> constant by reading how `SCHED_MODAL_ID` submits are handled in
> `discord_commands.py` (the modal-submit dispatcher). Use the SAME constants.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_routing.py -v`
Expected: FAIL — modal not returned / `run_panel_outreach` never called.

- [ ] **Step 3: Implement the routing**

In `discord_commands.py`:
1. Import: `from handlers import recruiting_panel`.
2. In `_handle_message_component` (the button dispatcher), alongside `is_sched_new`, add:
   ```python
   if recruiting_panel.is_out_find(custom_id):
       return {"type": MODAL, "data": recruiting_panel.build_outreach_modal()}
   ```
   (Place it before the final `is_panel_button` fallthrough; `aiuiout:*` is disjoint from `aiuibuild:*`/`aiuisched:*`.)
3. In the modal-submit dispatcher (mirror the `is_sched_modal` / `is_panel_modal` branch), add a branch that flattens the modal components into `{custom_id: value}`, calls `recruiting_panel.parse_outreach_modal(...)`, spawns the background task, and returns the deferred ACK:
   ```python
   if recruiting_panel.is_out_modal(custom_id):
       values = {c["custom_id"]: c.get("value", "")
                 for row in data.get("components", [])
                 for c in row.get("components", [])}
       role, location, jobdesc, count = recruiting_panel.parse_outreach_modal(values)
       # Build the ctx EXACTLY like the enhance-modal submit branch does
       # (discord_commands.py ~631-647): it wires notify_channel via
       # _channel_notifiers(channel_id), which the watcher needs to post results.
       notify_channel, notify_channel_rich = self._channel_notifiers(channel_id)
       ctx = CommandContext(... , channel_id=channel_id, platform="discord",
                            notify_channel=notify_channel,
                            notify_channel_rich=notify_channel_rich, ...)
       asyncio.create_task(self.router.run_panel_outreach(ctx, role, location, jobdesc, count))
       return {"type": DEFERRED_CHANNEL_MESSAGE}
   ```
   **There is no `_ctx_from_component` helper** — the ctx is built inline in each
   modal-submit branch. Copy the **enhance-modal** branch's ctx setup verbatim
   (it uses `self._channel_notifiers(channel_id)` to set `notify_channel` /
   `notify_channel_rich`; the schedule branch and `_handle_panel_route` do NOT set
   `notify_channel`, so don't copy those). Only swap the field extraction + the
   `run_panel_outreach` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_recruiting_routing.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full webhook-handler suite (no regressions)**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_recruiting_routing.py
git commit -m "feat(outreach): route Discord Find Engineers button + modal submit"
```

---

## Task 3: Tasks client methods (`start_outreach`, `get_outreach_status`)

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (after `get_build_status`, ~line 225)
- Test: `webhook-handler/tests/test_tasks_client_outreach.py`

Mirror `start_build` / `get_build_status` exactly.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_tasks_client_outreach.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clients.tasks import TasksClient


def _client(resp_json):
    tc = TasksClient.__new__(TasksClient)  # bypass __init__ network setup
    resp = MagicMock()
    resp.json.return_value = resp_json
    tc._request = AsyncMock(return_value=resp)
    return tc


@pytest.mark.asyncio
async def test_start_outreach_posts_payload():
    tc = _client({"task_id": "abc"})
    out = await tc.start_outreach("u@x.com",
        {"role": "Python", "location": "Berlin", "jobdesc": "Hiring", "count": 8})
    assert out == {"task_id": "abc"}
    method, path, email = tc._request.call_args.args[:3]
    assert method == "POST" and path == "/outreach" and email == "u@x.com"
    assert tc._request.call_args.kwargs["json"]["role"] == "Python"


@pytest.mark.asyncio
async def test_get_outreach_status_gets():
    tc = _client({"status": "completed", "found": 12, "sent": 8, "saved": 4,
                  "sheet_url": "http://s", "text": "done"})
    out = await tc.get_outreach_status("u@x.com", "abc")
    assert out["sent"] == 8
    method, path, email = tc._request.call_args.args[:3]
    assert method == "GET" and path == "/outreach/abc" and email == "u@x.com"
```

> NOTE: verify `_request`'s positional signature (`method, path, user_email`) by
> reading `start_build`. Adjust the assertion if `_request` uses kwargs.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_tasks_client_outreach.py -v`
Expected: FAIL — `AttributeError: start_outreach`.

- [ ] **Step 3: Implement**

```python
# in webhook-handler/clients/tasks.py, after get_build_status:
    async def start_outreach(
        self, user_email: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        resp = await self._request("POST", "/outreach", user_email, json=payload)
        return resp.json()

    async def get_outreach_status(
        self, user_email: str, task_id: str,
    ) -> dict[str, Any]:
        resp = await self._request("GET", f"/outreach/{task_id}", user_email)
        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes** — same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client_outreach.py
git commit -m "feat(outreach): tasks client start_outreach + get_outreach_status"
```

---

## Task 4: CommandRouter.run_panel_outreach + _watch_outreach

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (add `OUTREACH_*` constants near `BUILD_POLL_SECONDS:30`; add methods near `_start_build`/`_watch_build:2086`)
- Test: `webhook-handler/tests/test_run_panel_outreach.py`

Mirror `_start_build` (resolve email → ack → spawn watcher tracked in `self._background_tasks`) and `_watch_build` (poll loop, defensive notify).

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_run_panel_outreach.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext


def _ctx(notify):
    # channel_id is a REQUIRED CommandContext field (no default) — omitting it
    # raises TypeError, not the intended "method undefined" failure.
    return CommandContext(
        user_id="100", user_name="alice", channel_id="c", raw_text="outreach",
        subcommand="", arguments="", platform="discord", respond=AsyncMock(),
        respond_components=AsyncMock(), notify_channel=notify,
    )


def _router(tasks_client):
    r = CommandRouter.__new__(CommandRouter)
    r._tasks_client = tasks_client
    r._background_tasks = set()
    r._resolve_email_for_ctx = AsyncMock(return_value="u@x.com")
    return r


@pytest.mark.asyncio
async def test_run_panel_outreach_unlinked_prompts_link():
    r = _router(MagicMock())
    r._resolve_email_for_ctx = AsyncMock(return_value=None)
    r._respond_not_linked = AsyncMock()
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "", "Hiring", 10)
    r._respond_not_linked.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_panel_outreach_empty_jobdesc():
    r = _router(MagicMock())
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "", "   ", 10)
    ctx.respond.assert_awaited()  # asks for a description; no task started


@pytest.mark.asyncio
async def test_run_panel_outreach_starts_and_acks():
    tc = MagicMock()
    tc.start_outreach = AsyncMock(return_value={"task_id": "abc"})
    r = _router(tc)
    ctx = _ctx(AsyncMock())
    await r.run_panel_outreach(ctx, "Python", "Berlin", "Hiring", 8)
    tc.start_outreach.assert_awaited_once()
    ctx.respond.assert_awaited()  # the "Searching GitHub…" ack


@pytest.mark.asyncio
async def test_watch_outreach_posts_summary_on_completed():
    tc = MagicMock()
    tc.get_outreach_status = AsyncMock(return_value={
        "status": "completed", "found": 12, "sent": 8, "saved": 4,
        "sheet_url": "http://sheet", "text": "Emailed 8, saved 4"})
    r = _router(tc)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_outreach(ctx, "u@x.com", "abc", poll_seconds=0, max_polls=2)
    assert posted and "8" in posted[0]


@pytest.mark.asyncio
async def test_watch_outreach_posts_error_on_failed():
    tc = MagicMock()
    tc.get_outreach_status = AsyncMock(return_value={"status": "failed", "text": "no candidates"})
    r = _router(tc)
    posted = []
    ctx = _ctx(AsyncMock(side_effect=lambda m: posted.append(m)))
    await r._watch_outreach(ctx, "u@x.com", "abc", poll_seconds=0, max_polls=2)
    assert posted and ("couldn't" in posted[0].lower() or "failed" in posted[0].lower()
                       or "no candidates" in posted[0].lower())
```

> NOTE: confirm `CommandContext`'s constructor kwargs by reading its definition
> (it has more fields — `metadata`, `notify_channel_rich`, etc.). Provide the
> required ones; the test only needs `respond` + `notify_channel`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_run_panel_outreach.py -v`
Expected: FAIL — `run_panel_outreach` / `_watch_outreach` undefined.

- [ ] **Step 3: Implement**

Add constants near line 30:
```python
OUTREACH_POLL_SECONDS = 12
OUTREACH_MAX_POLLS = 80   # ~16 min, > agent EXECUTION_TIMEOUT_SECONDS (600s) + n8n
OUTREACH_MAX_CONSECUTIVE_ERRORS = 5
```

Add methods (mirror `_start_build`/`_watch_build`):
```python
    async def run_panel_outreach(
        self, ctx: CommandContext, role: str, location: str,
        jobdesc: str, count: int,
    ) -> None:
        email = await self._resolve_email_for_ctx(ctx)
        if not email:
            await self._respond_not_linked(ctx)
            return
        if not (jobdesc or "").strip():
            await ctx.respond("Please paste the job description so I know what to send.")
            return
        try:
            result = await self._tasks_client.start_outreach(email, {
                "role": role, "location": location, "jobdesc": jobdesc, "count": count})
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))  # reuse 401/403 -> not-linked copy
            return
        task_id = result["task_id"]
        where = f"{role}" + (f" · {location}" if location else "")
        await ctx.respond(
            f"\U0001f50e Searching GitHub for **{where}** … I'll post the results "
            "in your thread when it's done (usually a minute or two).")
        if ctx.notify_channel is not None:
            w = asyncio.create_task(self._watch_outreach(ctx, email, task_id))
            self._background_tasks.add(w)
            w.add_done_callback(self._background_tasks.discard)

    async def _watch_outreach(
        self, ctx: CommandContext, email: str, task_id: str,
        *, poll_seconds: int | None = None, max_polls: int | None = None,
    ) -> None:
        if ctx.notify_channel is None:
            return
        async def _notify(msg: str) -> None:
            try:
                await ctx.notify_channel(msg)
            except Exception as exc:  # noqa: BLE001
                logger.error("watch_outreach notify failed task=%s: %s", task_id, exc)
        poll_seconds = OUTREACH_POLL_SECONDS if poll_seconds is None else poll_seconds
        max_polls = OUTREACH_MAX_POLLS if max_polls is None else max_polls
        errors = 0
        for _ in range(max_polls):
            await asyncio.sleep(poll_seconds)
            try:
                st = await self._tasks_client.get_outreach_status(email, task_id)
                errors = 0
            except TasksAPIError as e:
                errors += 1
                if errors >= OUTREACH_MAX_CONSECUTIVE_ERRORS:
                    await _notify("Lost track of the outreach run — try again.")
                    return
                continue
            status = st.get("status")
            if status == "completed":
                text = (st.get("text") or "").strip() or "Outreach complete."
                url = st.get("sheet_url") or ""
                await _notify(f"✅ {text}" + (f"\n\U0001f449 {url}" if url else ""))
                return
            if status == "failed":
                text = (st.get("text") or "").strip()
                await _notify("⚠️ Outreach didn't complete. "
                              + (text or "Try a broader role or remove the location."))
                return
        await _notify("Outreach is still running — check back shortly.")
```

> Reuse `_format_build_error` only if its 401/403 branch returns the not-linked
> copy (it does — `commands.py:2080`). Otherwise add a tiny `_format_outreach_error`.

- [ ] **Step 4: Run test to verify it passes** — same command. Expected: PASS.

- [ ] **Step 5: Full suite** — `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest -q`. Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_run_panel_outreach.py
git commit -m "feat(outreach): run_panel_outreach + _watch_outreach (mirror build watcher)"
```

---

## Task 5: Tasks pure logic (`outreach.py`) — prompt, JSON extract, cap/dedupe, summary

**Files:**
- Create: `mcp-servers/tasks/outreach.py`
- Test: `mcp-servers/tasks/tests/test_outreach_logic.py`

Pure module, **no DB imports**. `extract_candidates` uses `extract_final_body`
from `claude_executor` (text BEFORE the sentinel — NOT `parse_outcome`).

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_outreach_logic.py
import json
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import outreach


def _stream_json(body: str) -> str:
    # mirror local_executor's --output-format stream-json final event
    return json.dumps({"type": "result", "is_error": False, "result": body}) + "\n"


def test_extract_candidates_from_real_stream_json():
    cand_json = json.dumps({"candidates": [
        {"name": "A", "github_url": "https://github.com/a", "email": "a@x.com",
         "subject": "Hi A", "body": "..."},
        {"name": "B", "github_url": "https://github.com/b", "email": None,
         "subject": "Hi B", "body": "..."},
    ]})
    body = f"Here are the candidates:\n```json\n{cand_json}\n```\nCOMPLETED"
    out = outreach.extract_candidates(_stream_json(body))
    assert len(out.candidates) == 2
    assert out.candidates[0].email == "a@x.com"
    assert out.candidates[1].email is None


def test_extract_candidates_missing_block_returns_empty():
    out = outreach.extract_candidates(_stream_json("no json here\nCOMPLETED"))
    assert out.candidates == []


def test_cap_and_dedupe():
    from outreach import Candidate
    cands = [
        Candidate(name="A", github_url="g/a", email="a@x.com", subject="s", body="b"),
        Candidate(name="A2", github_url="g/a2", email="A@x.com", subject="s", body="b"),  # dup (case-insensitive)
        Candidate(name="C", github_url="g/c", email=None, subject="s", body="b"),
        Candidate(name="D", github_url="g/d", email="d@x.com", subject="s", body="b"),
    ]
    out = outreach.cap_and_dedupe(cands, count=2)
    # cap=2 applies to the whole list AFTER dedupe; no-email kept (collected)
    emails = [c.email for c in out if c.email]
    assert "a@x.com" in [e.lower() for e in emails]
    assert len([e for e in emails]) <= 2
    assert len(out) <= 3  # 2 emailed-cap + at most the kept no-email ones


def test_build_outreach_prompt_contains_contract():
    p = outreach.build_outreach_prompt("Python", "Berlin", "Hiring a dev", 8)
    assert "api.github.com/search/users" in p
    assert "GITHUB_TOKEN" in p
    assert "```json" in p
    assert "COMPLETED" in p
    assert "8" in p


def test_format_outreach_summary():
    s = outreach.format_outreach_summary(found=12, sent=8, saved=4, sheet_url="http://s")
    assert "8" in s and "4" in s
```

> NOTE on cap semantics: cap applies to the count of engineers **emailed**
> (those with an email). Engineers without an email are collected regardless.
> Implement so `count` limits the has-email subset; keep no-email ones for the
> sheet. Adjust the test above if you choose to cap the whole batch — but the
> spec says "How many to **email**", so cap the emailable subset.

- [ ] **Step 2: Run to verify it fails**

Run: `cd mcp-servers/tasks; python -m pytest tests/test_outreach_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: outreach`.

- [ ] **Step 3: Implement**

```python
# mcp-servers/tasks/outreach.py
"""Pure outreach logic: prompt, JSON candidate extraction, cap/dedupe,
n8n POST, summary text. No DB. Tested in tests/test_outreach_logic.py."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx
from pydantic import BaseModel

from claude_executor import extract_final_body

N8N_BASE = os.environ.get("N8N_WEBHOOK_BASE", "https://n8n.srv1041674.hstgr.cloud")
OUTREACH_WEBHOOK_PATH = "recruiting-outreach"
_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class Candidate(BaseModel):
    name: str
    github_url: str = ""
    email: Optional[str] = None
    subject: str = ""
    body: str = ""


class CandidateList(BaseModel):
    candidates: list[Candidate] = []


def extract_candidates(raw_log: str) -> CandidateList:
    """Pull the fenced ```json block out of the agent's pre-sentinel body."""
    body = extract_final_body(raw_log) if raw_log else ""
    if not body:
        return CandidateList()
    m = _FENCE.search(body)
    if not m:
        return CandidateList()
    try:
        data = json.loads(m.group(1))
        return CandidateList(**data)
    except (ValueError, TypeError):
        return CandidateList()


def cap_and_dedupe(candidates: list[Candidate], count: int) -> list[Candidate]:
    """Drop duplicate emails (case-insensitive); cap the *emailable* subset to
    `count`. No-email candidates are always kept (collected, not emailed)."""
    seen: set[str] = set()
    emailable: list[Candidate] = []
    no_email: list[Candidate] = []
    for c in candidates:
        if c.email:
            key = c.email.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            emailable.append(c)
        else:
            no_email.append(c)
    return emailable[:max(0, count)] + no_email


def build_outreach_prompt(role: str, location: str, jobdesc: str, count: int) -> str:
    loc = f" located in {location}" if location.strip() else ""
    return f"""You are a recruiting research assistant. Find up to {count} software \
engineers matching: {role}{loc}.

STEPS:
1. Build a GitHub user-search query from the role and location and call the GitHub \
API with Bash, e.g.:
   curl -s -H "Authorization: token $GITHUB_TOKEN" \
   "https://api.github.com/search/users?q={role}+{location}+type:user&per_page={count*2}"
   (URL-encode the query; $GITHUB_TOKEN is in your environment.)
2. For each login, GET https://api.github.com/users/<login> to read the public \
email and name. Where the email is missing, use the WebSearch / WebFetch tools to \
try to find a public professional email. Never guess or fabricate emails — use null \
if you cannot find a real one.
3. Draft a SHORT, personalized recruiting email for each engineer referencing \
their work and this job description:
---
{jobdesc}
---
4. Output EXACTLY ONE fenced json block (no prose after it) of this shape, then a \
new line with the single word COMPLETED:
```json
{{"candidates":[{{"name":"...","github_url":"...","email":"... or null","subject":"...","body":"..."}}]}}
```
If you cannot find anyone, output a candidates list of [] then COMPLETED. \
On a hard error, output a line starting with FAILED: and the reason."""


async def post_outreach_to_n8n(job_title: str, candidates: list[Candidate],
                               *, timeout: float = 90.0) -> dict:
    """POST the batch to the n8n recruiting-outreach webhook (mirror routes_cron).
    Returns the parsed JSON ({sent, saved, sheet_url}) or raises on non-2xx."""
    url = f"{N8N_BASE.rstrip('/')}/webhook/{OUTREACH_WEBHOOK_PATH}"
    payload = {"job_title": job_title,
               "candidates": [c.model_dump() for c in candidates]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        text = resp.text.strip()
        return json.loads(text) if text else {}


def format_outreach_summary(found: int, sent: int, saved: int, sheet_url: str = "") -> str:
    parts = [f"Outreach complete — found {found} engineer(s).",
             f"Emailed {sent}.",
             f"Saved {saved} more (no public email) to the list."]
    return " ".join(parts)
```

- [ ] **Step 4: Run to verify it passes** — same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/outreach.py mcp-servers/tasks/tests/test_outreach_logic.py
git commit -m "feat(outreach): tasks pure logic — prompt, JSON extract, cap/dedupe, n8n POST"
```

---

## Task 6: Tasks n8n POST — verify the httpx call shape

**Files:**
- Test: `mcp-servers/tasks/tests/test_outreach_n8n.py`

Covers `post_outreach_to_n8n` against a mocked httpx so we lock the URL + payload + error behavior without hitting the network.

- [ ] **Step 1: Write the failing test**

```python
# mcp-servers/tasks/tests/test_outreach_n8n.py
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import outreach
from outreach import Candidate


class _Resp:
    def __init__(self, code=200, text='{"sent":2,"saved":1,"sheet_url":"http://s"}'):
        self.status_code = code; self.text = text
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)
    def json(self):
        import json; return json.loads(self.text)


class _Client:
    last = {}
    def __init__(self, timeout): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json):
        _Client.last = {"url": url, "json": json}; return _Resp()


@pytest.mark.asyncio
async def test_post_outreach_url_and_payload(monkeypatch):
    monkeypatch.setattr(outreach.httpx, "AsyncClient", _Client)
    out = await outreach.post_outreach_to_n8n("Python role", [
        Candidate(name="A", email="a@x.com", subject="s", body="b")])
    assert out["sent"] == 2
    assert _Client.last["url"].endswith("/webhook/recruiting-outreach")
    assert _Client.last["json"]["job_title"] == "Python role"
    assert _Client.last["json"]["candidates"][0]["email"] == "a@x.com"
```

- [ ] **Step 2: Run to verify it fails** → `cd mcp-servers/tasks; python -m pytest tests/test_outreach_n8n.py -v` (FAIL: AsyncClient real call / assertion).

- [ ] **Step 3:** Already implemented in Task 5 (`post_outreach_to_n8n`). If the test reveals a shape mismatch, fix `outreach.py`.

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/tests/test_outreach_n8n.py
git commit -m "test(outreach): lock n8n POST url + payload shape"
```

---

## Task 7: Tasks routes + `_run_outreach` (`routes_outreach.py`)

**Files:**
- Create: `mcp-servers/tasks/migrations/019_outreach_action_type.sql`
- Create: `mcp-servers/tasks/routes_outreach.py`
- Modify: `mcp-servers/tasks/main.py` (register router)
- Test: `mcp-servers/tasks/tests/test_routes_outreach.py` (pure-ish: mock the DB session + agent stream; do NOT use `db_session`)

> **BLOCKER fixed here first.** `migrations/001_init.sql` defines
> `action_type TEXT NOT NULL CHECK (action_type IN ('RESEARCH','BUILD','INTEGRATE','ASK_USER'))`.
> Inserting `action_type="OUTREACH"` (the route below) would raise an
> IntegrityError at runtime — and the pure unit tests would NOT catch it. The
> migration below widens the constraint. Migrations are applied automatically on
> every tasks-service boot by `db.py:_run_migrations()` (sorted `*.sql`), so they
> MUST be idempotent — the DO-block below is name-agnostic and safe to re-run.

- [ ] **Step 0a: Write the migration** (`migrations/019_outreach_action_type.sql`)

```sql
-- 019: allow the OUTREACH action_type (idempotent, name-agnostic)
DO $$
DECLARE c text;
BEGIN
  SELECT conname INTO c FROM pg_constraint
   WHERE conrelid = 'tasks.items'::regclass AND contype = 'c'
     AND pg_get_constraintdef(oid) ILIKE '%action_type%';
  IF c IS NOT NULL THEN
    EXECUTE format('ALTER TABLE tasks.items DROP CONSTRAINT %I', c);
  END IF;
  ALTER TABLE tasks.items
    ADD CONSTRAINT items_action_type_check
    CHECK (action_type IN ('RESEARCH','BUILD','INTEGRATE','ASK_USER','OUTREACH'));
END $$;
```

> Confirm `019` is the next free number (`ls migrations/`); bump if 019 already
> exists. Confirm the schema-qualified table name (`tasks.items`) matches
> `001_init.sql` (it uses the `tasks` schema).

- [ ] **Step 0b: Commit the migration**

```bash
git add mcp-servers/tasks/migrations/019_outreach_action_type.sql
git commit -m "feat(outreach): migration — allow OUTREACH action_type"
```

Then continue with the routes below. Mirror `routes_aiuibuilder._create_and_spawn_build` for task creation and
`routes_execution._run_execution` for the agent run + `parse_outcome` branching.
`_run_outreach` does: stream agent → `parse_outcome` (failed?) → on completed,
`extract_candidates` → `cap_and_dedupe` → `post_outreach_to_n8n` → store summary
JSON on `TaskItem.result`.

- [ ] **Step 1: Write the failing test** (logic-level, dependency-injected)

```python
# mcp-servers/tasks/tests/test_routes_outreach.py
import json, os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import routes_outreach


@pytest.mark.asyncio
async def test_process_completed_calls_n8n_and_summarizes(monkeypatch):
    cand = json.dumps({"candidates": [
        {"name": "A", "github_url": "g/a", "email": "a@x.com", "subject": "s", "body": "b"},
        {"name": "B", "github_url": "g/b", "email": None, "subject": "s", "body": "b"}]})
    log = json.dumps({"type": "result", "result":
        f"```json\n{cand}\n```\nCOMPLETED"}) + "\n"

    async def fake_post(job_title, candidates, **kw):
        return {"sent": 1, "saved": 1, "sheet_url": "http://sheet"}
    monkeypatch.setattr(routes_outreach.outreach, "post_outreach_to_n8n", fake_post)

    summary = await routes_outreach._process_outreach_result(
        log, job_title="Python", count=10)
    assert summary["status"] == "completed"
    assert summary["sent"] == 1 and summary["saved"] == 1
    assert summary["sheet_url"] == "http://sheet"
    assert summary["found"] == 2


@pytest.mark.asyncio
async def test_process_failed_agent():
    log = json.dumps({"type": "result", "result": "FAILED: github rate limit"}) + "\n"
    summary = await routes_outreach._process_outreach_result(log, job_title="x", count=10)
    assert summary["status"] == "failed"


@pytest.mark.asyncio
async def test_process_no_candidates():
    log = json.dumps({"type": "result", "result": "```json\n{\"candidates\":[]}\n```\nCOMPLETED"}) + "\n"
    summary = await routes_outreach._process_outreach_result(log, job_title="x", count=10)
    assert summary["status"] == "failed"  # nothing found -> surfaced as a soft failure
    assert summary["found"] == 0
```

- [ ] **Step 2: Run to verify it fails** → `cd mcp-servers/tasks; python -m pytest tests/test_routes_outreach.py -v`.

- [ ] **Step 3: Implement** — factor the testable core into `_process_outreach_result` (pure: takes the raw log, returns the summary dict), and keep DB/agent wiring in `_run_outreach` + the routes.

```python
# mcp-servers/tasks/routes_outreach.py
"""POST /outreach + GET /outreach/{task_id} + the _run_outreach coroutine."""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

import outreach
from auth import current_user, CurrentUser
from claude_executor import parse_outcome
from db import session
from models import TaskItem, TaskExecution

logger = logging.getLogger("tasks.outreach")
router = APIRouter()


class OutreachRequest(BaseModel):
    role: str = ""
    location: str = ""
    jobdesc: str
    count: int = 10


class OutreachResponse(BaseModel):
    task_id: uuid.UUID


class OutreachStatusResponse(BaseModel):
    status: str
    found: int = 0
    sent: int = 0
    saved: int = 0
    sheet_url: str = ""
    text: str = ""


async def _process_outreach_result(raw_log: str, *, job_title: str, count: int) -> dict:
    """Pure: agent log -> summary dict. Branches on parse_outcome, extracts the
    JSON via outreach.extract_candidates, caps/dedupes, calls n8n."""
    outcome = parse_outcome(raw_log)
    if outcome.kind == "failed":
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0,
                "sheet_url": "", "text": (outcome.payload or "The search failed.").strip()[:500]}
    cand = outreach.extract_candidates(raw_log)
    found = len(cand.candidates)
    if found == 0:
        return {"status": "failed", "found": 0, "sent": 0, "saved": 0, "sheet_url": "",
                "text": "I couldn't find engineers matching that — try a broader role or remove the location."}
    batch = outreach.cap_and_dedupe(cand.candidates, count)
    try:
        res = await outreach.post_outreach_to_n8n(job_title, batch)
    except Exception as exc:  # noqa: BLE001
        logger.error("outreach n8n POST failed: %s", exc)
        emailable = sum(1 for c in batch if c.email)
        return {"status": "completed", "found": found, "sent": 0, "saved": len(batch),
                "sheet_url": "",
                "text": f"Found {found} engineer(s) but sending failed — they're saved; I'll retry sends."}
    sent = int(res.get("sent", 0)); saved = int(res.get("saved", len(batch)))
    sheet_url = res.get("sheet_url", "")
    return {"status": "completed", "found": found, "sent": sent, "saved": saved,
            "sheet_url": sheet_url,
            "text": outreach.format_outreach_summary(found, sent, saved, sheet_url)}


@router.post("/outreach", response_model=OutreachResponse, status_code=201)
async def start_outreach(body: OutreachRequest, user: CurrentUser = Depends(current_user)):
    import asyncio
    prompt = outreach.build_outreach_prompt(body.role, body.location, body.jobdesc, body.count)
    async with session() as s:
        item = TaskItem(
            meeting_id=uuid.uuid4(), action_type="OUTREACH",
            assignee_name=user.email.split("@")[0], assignee_email=user.email,
            description=f"Outreach: {body.role} {body.location}".strip(),
            priority="NICE_TO_HAVE", status="running", mode="ai", max_attempts=1)
        s.add(item); await s.flush()
        execution = TaskExecution(task_id=item.id, status="running", log="")
        s.add(execution); await s.commit()
        await s.refresh(item); await s.refresh(execution)
        task_id, exec_id = item.id, execution.id
    asyncio.create_task(_run_outreach(task_id, exec_id, prompt,
                                      job_title=body.role, count=body.count))
    return OutreachResponse(task_id=task_id)


@router.get("/outreach/{task_id}", response_model=OutreachStatusResponse)
async def get_outreach_status(task_id: uuid.UUID, user: CurrentUser = Depends(current_user)):
    async with session() as s:
        item = (await s.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one_or_none()
    if item is None or item.assignee_email != user.email:
        raise HTTPException(status_code=404, detail="not found")
    if item.status == "running":
        return OutreachStatusResponse(status="running")
    try:
        data = json.loads(item.result or "{}")
    except ValueError:
        data = {}
    return OutreachStatusResponse(
        status=data.get("status", "failed"), found=data.get("found", 0),
        sent=data.get("sent", 0), saved=data.get("saved", 0),
        sheet_url=data.get("sheet_url", ""), text=data.get("text", ""))


async def _run_outreach(task_id, execution_id, prompt, *, job_title: str, count: int):
    from routes_execution import _stream_claude  # reuse the existing streamer
    try:
        raw_log = await _stream_claude(prompt, execution_id, task_id)
        summary = await _process_outreach_result(raw_log, job_title=job_title, count=count)
        final_status = "completed" if summary["status"] == "completed" else "failed"
        async with session() as s:
            await s.execute(update(TaskExecution).where(TaskExecution.id == execution_id)
                            .values(status="succeeded" if final_status == "completed" else "failed"))
            await s.execute(update(TaskItem).where(TaskItem.id == task_id)
                            .values(status=final_status, result=json.dumps(summary)))
            await s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("outreach run failed: %s", exc)
        async with session() as s:
            await s.execute(update(TaskItem).where(TaskItem.id == task_id).values(
                status="failed",
                result=json.dumps({"status": "failed", "text": f"Run error: {exc}"[:300]})))
            await s.commit()
```

> VERIFY before writing: (a) `_stream_claude`'s exact signature/return in
> `routes_execution.py:108-129` (it returns the joined log string); call it the
> same way `_run_execution` does. (b) `TaskItem` columns (`action_type`,
> `assignee_email`, `result`, `status`, `mode`, `max_attempts`, `meeting_id`) —
> read `models.py`; drop any kwarg that doesn't exist. (c) `parse_outcome`'s
> `Outcome.kind` values include `"failed"`/`"completed"` (`claude_executor.py`).

- [ ] **Step 4: Register the router** in `mcp-servers/tasks/main.py`:
```python
import routes_outreach
app.include_router(routes_outreach.router)
```
(Match how `routes_aiuibuilder` is included — same prefix conventions. If builder
routes are mounted under `/api/aiuibuilder`, decide the outreach prefix: the bot
client calls `/outreach` and `/outreach/{id}` with no `/api` prefix, matching the
schedule/internal style. Keep the client + server prefixes identical.)

- [ ] **Step 5: Run to verify the logic tests pass** → `cd mcp-servers/tasks; python -m pytest tests/test_routes_outreach.py -v`. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_outreach.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_routes_outreach.py
git commit -m "feat(outreach): POST/GET /outreach routes + _run_outreach pipeline"
```

---

## Task 8: Slack panel + routing

**Files:**
- Create: `webhook-handler/handlers/slack_recruiting_panel.py`
- Modify: `webhook-handler/handlers/slack_interactions.py`
- Test: `webhook-handler/tests/test_slack_recruiting.py`

Mirror `slack_schedule_panel.py` (Block Kit blocks + `views_open` modal +
`*_from_view` extractor) and `slack_interactions.py`'s block_actions/view_submission.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_slack_recruiting.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack_interactions import SlackInteractionsHandler
from handlers import slack_recruiting_panel as srp


def _handler(router):
    slack = MagicMock(); slack.open_modal = AsyncMock(return_value=True)
    return SlackInteractionsHandler(slack_client=slack, command_router=router)


@pytest.mark.asyncio
async def test_find_button_opens_modal():
    h = _handler(MagicMock())
    payload = {"type": "block_actions", "trigger_id": "tg",
               "channel": {"id": "c"}, "user": {"id": "u"},
               "actions": [{"action_id": srp.OUT_FIND_ACTION_ID}]}
    await h.handle_interaction(payload)
    h.slack.open_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_view_submission_dispatches(monkeypatch):
    calls = []
    router = MagicMock()
    async def fake(ctx, role, location, jobdesc, count): calls.append((role, count))
    router.run_panel_outreach = fake
    h = _handler(router)
    view = {"callback_id": srp.OUT_MODAL_CALLBACK,
            "private_metadata": "c",
            "state": {"values": srp.sample_state("Python", "Berlin", "Hiring", "8")}}
    payload = {"type": "view_submission", "user": {"id": "u"}, "view": view}
    resp = await h.handle_interaction(payload)
    # view_submission ACKs with empty dict / clear
    for _ in range(6):
        import asyncio; await asyncio.sleep(0)
    assert calls and calls[0][0] == "Python"
```

> `srp.sample_state(...)` is a tiny test helper you add to the panel module to
> build a Block Kit `state.values` dict (mirrors `slack_schedule_panel`'s input
> block ids). Or inline the dict in the test.

- [ ] **Step 2: Run to verify it fails** → `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_slack_recruiting.py -v`.

- [ ] **Step 3: Implement** the Slack panel (blocks + modal `view` with 4 input blocks + `outreach_fields_from_view(view) -> (role, location, jobdesc, count)` reusing `recruiting_panel.parse_outreach_modal` for the count clamp) and wire two branches into `slack_interactions.py`:
  - in `_handle_block_actions`: `if action_id == srp.OUT_FIND_ACTION_ID: await self.slack.open_modal(trigger_id, srp.build_outreach_view(channel_id)); return {}`
  - in `_handle_view_submission`: `if view.get("callback_id") == srp.OUT_MODAL_CALLBACK:` extract fields, then build the ctx. **The Slack `SCHED_MODAL_ID` submit branch does NOT build a `notify_channel` ctx** (it posts to a DM directly via `self.slack.post_message`). So construct the ctx manually: start from `_slack_ctx(user_id)` for identity + the not-linked path, resolve email via `_email_for`, and set `notify_channel` to a closure that wraps `self.slack.post_message(target, msg)` where `target` is the channel/DM id from `view["private_metadata"]` (the panel stashes `channel_id` there, mirroring the App Builder Slack flow). Track the watcher in `self.router._background_tasks`. Then `asyncio.create_task(self.router.run_panel_outreach(...))` and return the same empty-dict/clear ACK the schedule submit returns. All primitives needed already exist: `_slack_ctx` / `_email_for` in `slack_interactions.py`; `post_message` / `open_dm` / `open_modal` on the slack client (`self.slack.*`).

- [ ] **Step 4: Run to verify it passes.** Then full suite: `./.venv/Scripts/python.exe -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/slack_recruiting_panel.py webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_recruiting.py
git commit -m "feat(outreach): Slack recruiting panel + button/modal routing"
```

---

## Task 9: n8n workflow (`recruiting-outreach.json`)

**Files:**
- Create: `n8n-workflows/recruiting-outreach.json`
- Test: `webhook-handler/tests/test_recruiting_workflow_json.py` (or a tasks test) — validates the JSON is well-formed and has the node chain.

Clone `n8n-workflows/sheets-report.json`'s skeleton; node chain:
`Webhook(path=recruiting-outreach, responseMode=responseNode)` →
`Google Sheets (read, for dedupe)` → `Code (drop emails already in sheet; split
has-email vs no-email)` → `Gmail (send, loop over has-email)` →
`Google Sheets (append every candidate, status sent|no_email)` →
`Respond ({sent, saved, sheet_url})`. Gmail/Sheets credentials `CONFIGURE_IN_UI`;
the target sheet is selected in the UI on import.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_recruiting_workflow_json.py
import json, pathlib

WF = pathlib.Path(__file__).resolve().parents[2] / "n8n-workflows" / "recruiting-outreach.json"


def test_workflow_is_valid_and_has_chain():
    data = json.loads(WF.read_text(encoding="utf-8"))
    names = [n["name"] for n in data["nodes"]]
    types = [n["type"] for n in data["nodes"]]
    assert "n8n-nodes-base.webhook" in types
    assert "n8n-nodes-base.gmail" in types
    assert types.count("n8n-nodes-base.googleSheets") >= 2  # read + append
    assert "n8n-nodes-base.respondToWebhook" in types
    # webhook path matches what the tasks service POSTs to
    wh = next(n for n in data["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert wh["parameters"]["path"] == "recruiting-outreach"
    assert data["connections"]  # has wiring
```

- [ ] **Step 2: Run to verify it fails** → file missing.

- [ ] **Step 3: Author the JSON** following `sheets-report.json`'s structure (Webhook → Code → Sheets → Respond) plus the Gmail node and the dedupe read. The `Code` node receives `$json.body.candidates` and `$json.body.job_title`; it reads existing emails from the Sheets-read output, filters, and emits one item per candidate with fields `{date,name,github_url,email,status,job_title}`.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add n8n-workflows/recruiting-outreach.json webhook-handler/tests/test_recruiting_workflow_json.py
git commit -m "feat(outreach): n8n recruiting-outreach workflow (send + sheet log)"
```

---

## Task 10: Compose env + operator setup doc

**Files:**
- Modify: `docker-compose.unified.yml` (tasks service env block — add `GITHUB_TOKEN`)
- Create: `docs/recruiting-outreach-setup.md`

- [ ] **Step 1: Add the env line** to the **tasks** service environment (NOT webhook-handler), parameterized:
```yaml
      - GITHUB_TOKEN=${GITHUB_TOKEN:-}
```
(Confirm you're editing the tasks service block, not webhook-handler's line 115.)

- [ ] **Step 2: Write `docs/recruiting-outreach-setup.md`** — the 3 one-time steps: create a GitHub PAT and add `GITHUB_TOKEN` to the server `.env`; in n8n connect Gmail + Google Sheets, import & activate `recruiting-outreach.json`, select the target Sheet; create the Sheet with header row `date | name | github_url | email | status | job_title` and share it with the n8n account. Note the optional `N8N_WEBHOOK_BASE` override (defaults to the hosted instance in code).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.unified.yml docs/recruiting-outreach-setup.md
git commit -m "chore(outreach): GITHUB_TOKEN on tasks service + operator setup doc"
```

---

## Task 11: Channel setup script (post the #recruiting panel)

**Files:**
- Create: `webhook-handler/scripts/setup_recruiting_channel.py` (mirror `scripts/setup_app_builder_channel.py`)

- [ ] **Step 1:** Read `scripts/setup_app_builder_channel.py`; create the sibling that posts `recruiting_panel.build_recruiting_embed()` + `build_recruiting_panel()` to a configured `RECRUITING_CHANNEL_ID`. Idempotent (pin one panel).
- [ ] **Step 2:** Smoke it locally with a dry-run/print mode if the original supports it; otherwise just import-check it: `cd webhook-handler; ./.venv/Scripts/python.exe -c "import scripts.setup_recruiting_channel"`.
- [ ] **Step 3: Commit**

```bash
git add webhook-handler/scripts/setup_recruiting_channel.py
git commit -m "feat(outreach): one-shot script to post the #recruiting panel"
```

---

## Final verification (before merge/deploy — separate step)

- [ ] Full webhook-handler suite green: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest -q`
- [ ] Tasks pure suite green (no DB): `cd mcp-servers/tasks; python -m pytest tests/test_outreach_logic.py tests/test_outreach_n8n.py tests/test_routes_outreach.py -v`
- [ ] @superpowers:verification-before-completion: state evidence (counts, command output) before claiming done.
- [ ] Deploy is a SEPARATE, explicit step (per CLAUDE.md): webhook-handler via manual `scp` per changed file + rebuild; tasks via the orchestrator (or manual scp). Add `GITHUB_TOKEN` to the server `.env` (operator). Verify `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz`. **Do not deploy `templates.py`; never touch `.env`.**
- [ ] DB-backed integration test of `POST /outreach` (creates a real TaskItem) runs ONLY in the container against a test DB — never the prod DB.

---

## Notes for the implementer

- The riskiest, least-deterministic part is the agent's GitHub search + email discovery (Task 5/7). The contract (one fenced ```json block, then `COMPLETED`) is what makes the rest deterministic — keep that prompt strict.
- `extract_final_body` reads the FINAL stream-json `result` event; tests must feed a real stream-json line, not plain text (Task 5).
- Cap applies to the *emailable* subset (people are "emailed", per the modal label); no-email candidates are always collected.
- Everything new is additive: no existing route, table, or workflow is modified, so blast radius is small.
