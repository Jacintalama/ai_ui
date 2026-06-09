# Schedule Date/Time Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text *"How often?"* schedule field with a click-driven date/time picker (Discord dropdowns/buttons, Slack native pickers) and add a **one-time ("run once")** schedule capability.

**Architecture:** A pure `picks_to_cron` converter turns UI selections into `(cron_expr, run_once, human_label)` — the exact inputs the existing schedule-create path already consumes. One-time runs are a normal cron matching a single minute (`MIN HR DAY MON *`) plus a `run_once` flag the scheduler flips `enabled=false` on after firing. The Discord text-modal path stays as a fallback; Slack's create modal becomes picker-only.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, croniter; Discord HTTP interactions (buttons/select menus/modals) + Slack Block Kit (`datepicker`/`timepicker`/`static_select`); pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-06-09-schedule-datetime-picker-design.md`

**Sub-skills:** @superpowers:test-driven-development each task; @superpowers:verification-before-completion before claiming done.

---

## Conventions & guardrails (read once)
- **Test runners:**
  - webhook-handler: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest <path> -v`
  - tasks PURE modules (no DB): `cd mcp-servers/tasks; "../../webhook-handler/.venv/Scripts/python.exe" -m pytest <file> -v` — the webhook venv has croniter/sqlalchemy/pydantic installed. **Run ONLY specific files; NEVER the whole tasks suite; NEVER set a real DATABASE_URL** (the `db_session` fixture TRUNCATEs prod — a past run wiped 9 projects). The tests here don't use `db_session`.
- **Time granularity:** v1 Discord time dropdown is **hourly** (minute always `0`). Exact minutes go through the kept text fallback.
- **Timezone:** all schedules are `Asia/Manila` (existing default). The one-time past-check uses Manila local time.
- **DRY:** reuse `schedule_parse` (cron grammar, `_fmt_time`, `_DAY_NUM`/`_DAY_NAME`) and the existing `_pending_schedules`/confirm/create flow.
- Work on branch `feat/schedule-datetime-picker` (already created). Commit after every task.

## File Structure
**webhook-handler:**
- Create `webhook-handler/handlers/schedule_picker.py` — pure: `picks_to_cron`, option lists, the `aiuisched:pick:*` custom_id constants, Discord card/modal builders.
- Modify `webhook-handler/handlers/discord_commands.py` — picker routing + a `_pending_picks` accumulator; wire the final task-modal into the existing confirm/create path with `run_once`.
- Modify `webhook-handler/handlers/slack_schedule_panel.py` — picker blocks in the create modal.
- Modify `webhook-handler/handlers/slack_interactions.py` — read the picker values in `view_submission`.
- Modify `webhook-handler/handlers/commands.py` — `run_schedule_create` gains `run_once`.
- Modify `webhook-handler/clients/tasks.py` — `create_schedule` gains `run_once`.

**tasks service:**
- Create `mcp-servers/tasks/migrations/0NN_schedule_run_once.sql` — `run_once` column.
- Modify `mcp-servers/tasks/models.py` — `Schedule.run_once`.
- Modify `mcp-servers/tasks/routes_schedules.py` — `CreateScheduleIn.run_once` + pass to `Schedule(...)`.
- Modify `mcp-servers/tasks/scheduler.py` — `_tick_once`: set `enabled=False` when firing a `run_once` row.

---

## Task 1: Pure converter + codec (`schedule_picker.py` core)

**Files:**
- Create: `webhook-handler/handlers/schedule_picker.py`
- Test: `webhook-handler/tests/test_schedule_picker.py`

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_schedule_picker.py
from datetime import datetime
import pytest
from handlers import schedule_picker as sp


# Fixed "now" in Manila for deterministic one-time past/future checks.
NOW = datetime(2026, 6, 9, 10, 0)  # naive local-Manila wall clock is fine for v1


@pytest.mark.parametrize("picks,expected_cron,expected_once", [
    ({"kind": "rep", "freq": "daily", "hour": "9"}, "0 9 * * *", False),
    ({"kind": "rep", "freq": "weekdays", "hour": "8"}, "0 8 * * 1-5", False),
    ({"kind": "rep", "freq": "weekly", "hour": "9", "weekday": "monday"}, "0 9 * * 1", False),
    ({"kind": "rep", "freq": "hourly"}, "0 * * * *", False),
    ({"kind": "rep", "freq": "every30"}, "*/30 * * * *", False),
    ({"kind": "once", "date": "2026-06-15", "hour": "9"}, "0 9 15 6 *", True),
])
def test_picks_to_cron_ok(picks, expected_cron, expected_once):
    cron, run_once, label = sp.picks_to_cron(picks, now=NOW)
    assert cron == expected_cron
    assert run_once is expected_once
    assert label  # non-empty human label


def test_one_time_past_rejected():
    with pytest.raises(sp.PastTimeError):
        sp.picks_to_cron({"kind": "once", "date": "2026-06-09", "hour": "9"}, now=NOW)
    # 09:00 today is before NOW (10:00) -> past


def test_one_time_future_today_ok():
    cron, once, _ = sp.picks_to_cron({"kind": "once", "date": "2026-06-09", "hour": "11"}, now=NOW)
    assert once is True and cron == "0 11 9 6 *"


def test_codec_round_trip():
    token = "abc123"
    cid = sp.pick_cid("freq", token)
    field, tok = sp.parse_pick_cid(cid)
    assert field == "freq" and tok == token
```

- [ ] **Step 2: Run to verify it fails** — `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest tests/test_schedule_picker.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement the converter + codec**

```python
# webhook-handler/handlers/schedule_picker.py  (core; builders added in Task 2)
"""Pure date/time picker logic for schedules: UI picks -> (cron, run_once, label).
Reuses schedule_parse's cron grammar + label helpers. No I/O."""
from __future__ import annotations

from datetime import datetime

from handlers.schedule_parse import _DAY_NUM, _DAY_NAME, _fmt_time

# --- custom_id namespace (Discord) ---
PICK_PREFIX = "aiuisched:pick:"          # aiuisched:pick:<field>:<token>


class PastTimeError(ValueError):
    """Raised when a one-time schedule resolves to a moment already past."""


_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def pick_cid(field: str, token: str) -> str:
    return f"{PICK_PREFIX}{field}:{token}"


def parse_pick_cid(custom_id: str) -> tuple[str, str]:
    """`aiuisched:pick:<field>:<token>` -> (field, token)."""
    if not custom_id.startswith(PICK_PREFIX):
        raise ValueError(f"not a pick custom_id: {custom_id!r}")
    rest = custom_id[len(PICK_PREFIX):]
    field, _, token = rest.partition(":")
    return field, token


def picks_to_cron(picks: dict, *, now: datetime) -> tuple[str, bool, str]:
    """Convert accumulated UI picks into (cron_expr, run_once, human_label).
    Raises PastTimeError for a one-time datetime that is already past."""
    kind = picks.get("kind")
    if kind == "rep":
        freq = picks.get("freq")
        if freq == "hourly":
            return "0 * * * *", False, "every hour"
        if freq == "every30":
            return "*/30 * * * *", False, "every 30 minutes"
        hour = int(picks["hour"])
        label_time = _fmt_time(hour, 0)
        if freq == "daily":
            return f"0 {hour} * * *", False, f"every day at {label_time}"
        if freq == "weekdays":
            return f"0 {hour} * * 1-5", False, f"every weekday at {label_time}"
        if freq == "weekly":
            dow = _DAY_NUM[picks["weekday"].lower()]
            return (f"0 {hour} * * {dow}", False,
                    f"every {_DAY_NAME[dow]} at {label_time}")
        raise ValueError(f"unknown freq: {freq!r}")
    if kind == "once":
        hour = int(picks["hour"])
        y, m, d = (int(x) for x in picks["date"].split("-"))
        target = datetime(y, m, d, hour, 0)
        if target <= now:
            raise PastTimeError("one-time schedule is in the past")
        label = f"once on {_MONTHS[m - 1]} {d} at {_fmt_time(hour, 0)}"
        return f"0 {hour} {d} {m} *", True, label
    raise ValueError(f"unknown kind: {kind!r}")
```

- [ ] **Step 4: Run to verify it passes** — same command. Expected: all PASS.

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/schedule_picker.py webhook-handler/tests/test_schedule_picker.py
git commit -m "feat(schedules): pure picks->cron converter + pick custom_id codec"
```

> VERIFY: confirm `schedule_parse` exports `_DAY_NUM`, `_DAY_NAME`, `_fmt_time` (it does — they're module-level). `_DAY_NUM` maps sunday=0..saturday=6, matching cron dow.

---

## Task 2: Discord picker builders (cards + task modal)

**Files:**
- Modify: `webhook-handler/handlers/schedule_picker.py` (add builders + option lists)
- Test: `webhook-handler/tests/test_schedule_picker_builders.py`

Mirror `app_builder_panel.py` component shapes (`ACTION_ROW`, `BUTTON`, `SELECT_MENU=3`, `_button`, modal `TEXT_PARAGRAPH`). Discord: select menus live in their own action row; a message holds ≤5 rows.

- [ ] **Step 1: Write the failing test** — assert:
  - `build_kind_card(token)` → two buttons with custom_ids `pick_cid("kind", token)`-style carrying `rep`/`once` (use `aiuisched:pick:kind:<token>:rep`). 
  - `build_repeating_card(token, picks)` → a frequency select (custom_id `pick_cid("freq", token)`) and, when freq needs a time, an hourly time select (`pick_cid("hour", token)`); for weekly, a weekday select (`pick_cid("weekday", token)`); plus a "✅ Set the task" button (`pick_cid("settask", token)`) once required fields are present, and a "⌨️ Type it instead" button (`pick_cid("typeit", token)`).
  - `build_onetime_card(token, picks)` → quick-pick date buttons (`pick_cid("qdate", token)` carrying today/tomorrow/nextmon as a suffix), a "next 14 days" date select (`pick_cid("date", token)`), an hourly time select, + Set the task / Type it instead.
  - `build_task_modal(token)` → type-9 modal, custom_id `aiuisched:pick:taskmodal:<token>`, one paragraph input `what`.
  - Option lists: `FREQ_OPTIONS` (daily/weekdays/weekly/hourly/every30), `HOUR_OPTIONS` (24), `WEEKDAY_OPTIONS` (7), `next_14_day_options(now)` (14 dated options, value=`YYYY-MM-DD`).
  - Selects cap at 25 options (assert ≤25).

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement the builders** following the spec mockups. Keep each card ≤5 action rows. The "Set the task" button only appears when the required picks for the chosen freq are present (daily/weekdays/weekly need an hour; weekly also a weekday; hourly/every30 need nothing; once needs date + hour). Encode the kind/qdate choice as a trailing custom_id segment (`...:<token>:rep`). Use `next_14_day_options(now)` to build value=`YYYY-MM-DD`, label e.g. "Mon, Jun 15".

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/schedule_picker.py webhook-handler/tests/test_schedule_picker_builders.py
git commit -m "feat(schedules): Discord picker cards + task modal builders"
```

> NOTE: `next_14_day_options` takes `now` as a param (no `datetime.now()` inside) so it's deterministic/testable. The routing layer passes the real time.

---

## Task 3: run-once backend (tasks service)

**Files:**
- Create: `mcp-servers/tasks/migrations/0NN_schedule_run_once.sql` (use the next free number — `ls migrations/`, currently up to 019 from the outreach feature, so likely `020`)
- Modify: `mcp-servers/tasks/models.py` (`Schedule.run_once`)
- Modify: `mcp-servers/tasks/routes_schedules.py` (`CreateScheduleIn.run_once` + `Schedule(run_once=...)`)
- Modify: `mcp-servers/tasks/scheduler.py` (`_tick_once`)
- Test: `mcp-servers/tasks/tests/test_scheduler_run_once.py`

- [ ] **Step 0a: Migration** `migrations/020_schedule_run_once.sql` (idempotent — migrations run every boot):
```sql
-- 020: one-time schedules. NULL/false = repeating (existing behavior).
ALTER TABLE tasks.schedules ADD COLUMN IF NOT EXISTS run_once BOOLEAN NOT NULL DEFAULT FALSE;
```
Confirm `020` is the next free number first.

- [ ] **Step 0b: Commit migration**
```bash
git add mcp-servers/tasks/migrations/020_schedule_run_once.sql
git commit -m "feat(schedules): migration — run_once column"
```

- [ ] **Step 1: Write the failing test** (pure — patches the DB calls; verifies `_tick_once` flips `enabled=False` for run_once rows on fire). Mirror the style of `tests/test_scheduler_delivery.py`; import `scheduler` and drive `_tick_once` with a fake session whose `execute` records the `.values(...)` for run_once vs repeating rows. If faking the session is heavy, instead extract a tiny pure helper `fire_values(sched, now)` that returns the dict written pre-dispatch (`{last_run_at, last_run_status, **({enabled:False} if sched.run_once else {})}`) and unit-test THAT:

```python
# mcp-servers/tasks/tests/test_scheduler_run_once.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import scheduler


class _S:  # minimal stand-in for a Schedule row
    def __init__(self, run_once): self.run_once = run_once


def test_fire_values_disables_run_once():
    now = datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc)
    v = scheduler.fire_values(_S(run_once=True), now)
    assert v["enabled"] is False and v["last_run_at"] == now and v["last_run_status"] == "running"


def test_fire_values_keeps_repeating_enabled():
    now = datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc)
    v = scheduler.fire_values(_S(run_once=False), now)
    assert "enabled" not in v  # repeating rows stay enabled
```

- [ ] **Step 2: Run to verify it fails** — `cd mcp-servers/tasks; "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_scheduler_run_once.py -v`.

- [ ] **Step 3: Implement**
  - `models.py`: add `run_once = Column(Boolean, nullable=False, server_default="false", default=False)` to `Schedule`.
  - `routes_schedules.py`: add `run_once: bool = False` to `CreateScheduleIn`; pass `run_once=body.run_once` into `s.add(Schedule(...))`.
  - `scheduler.py`: add the pure helper and use it in `_tick_once`:
    ```python
    def fire_values(sched, now) -> dict:
        v = {"last_run_at": now, "last_run_status": "running"}
        if getattr(sched, "run_once", False):
            v["enabled"] = False   # one-time: fire exactly once
        return v
    ```
    In `_tick_once`, replace the inline `.values(last_run_at=now, last_run_status="running")` with `.values(**fire_values(sched, now))`.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Commit**
```bash
git add mcp-servers/tasks/models.py mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/scheduler.py mcp-servers/tasks/tests/test_scheduler_run_once.py
git commit -m "feat(schedules): run_once support — model, create route, fire-then-disable"
```

> VERIFY: read `scheduler._tick_once` (~line 333) to place `fire_values` exactly where the pre-dispatch update is. Confirm `Boolean` is imported in models.py (it is — `Schedule.enabled` uses it).

---

## Task 4: run_once threading (bot side) + client

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (`create_schedule` gains `run_once`)
- Modify: `webhook-handler/handlers/commands.py` (`run_schedule_create` gains `run_once`)
- Test: `webhook-handler/tests/test_create_schedule_run_once.py`

- [ ] **Step 1: Write the failing test** — assert `TasksClient.create_schedule(..., run_once=True)` includes `"run_once": True` in the POSTed body, and omits it (or sends False) when not set (keep the existing create test stable). Mirror `test_tasks_client_outreach.py`'s `_request`-mock style.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**
  - `clients/tasks.py` `create_schedule`: add `run_once: bool = False`; `if run_once: body["run_once"] = True` (only add when True → existing test payload unchanged).
  - `commands.py` `run_schedule_create`: add `run_once: bool = False` param; pass `run_once=run_once` to `create_schedule`.

- [ ] **Step 4: Run to verify it passes.** Then full suite: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest -q`.

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/clients/tasks.py webhook-handler/handlers/commands.py webhook-handler/tests/test_create_schedule_run_once.py
git commit -m "feat(schedules): thread run_once through create_schedule client + router"
```

---

## Task 5: Discord picker routing

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py`
- Test: `webhook-handler/tests/test_schedule_picker_routing.py`

Replace the `SCHED_NEW_ID` → text-modal behavior with `SCHED_NEW_ID` → **picker card**, accumulate picks in a `self._pending_picks: dict[str, dict]` map (mirror `self._pending_schedules`), and on the task-modal submit run `picks_to_cron` → the EXISTING confirm/create path with `run_once`.

- [ ] **Step 1: Write the failing test** (mirror `test_schedules_ux_interactions.py`):
  - Clicking `SCHED_NEW_ID` returns a message/card (the kind card), not the text modal.
  - Clicking the "Repeating" kind button updates the card to the repeating card; selecting freq=daily then hour=9 stores `_pending_picks[token]` and surfaces the "Set the task" button.
  - Submitting the task modal (`aiuisched:pick:taskmodal:<token>`) with `what="digest"` calls into the create path with `cron="0 9 * * *"`, `run_once=False`, `prompt="digest"` (assert via a mocked `router.run_schedule_create` OR the confirm-card path — match whichever the existing modal submit uses).
  - "⌨️ Type it instead" (`aiuisched:pick:typeit:<token>`) returns the existing `build_schedule_modal()` text modal (regression-safe fallback).
  - A one-time pick whose datetime is past → the bot posts the "already past" message (PastTimeError handled).

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement the routing.** In `_handle_message_component` / the component dispatcher:
  - `is_sched_new(custom_id)` → generate a token, `self._pending_picks[token] = {}`, return the kind card (`schedule_picker.build_kind_card(token)`). (This REPLACES the current `{"type": MODAL, "data": build_schedule_modal()}` for SCHED_NEW.)
  - For `custom_id.startswith(schedule_picker.PICK_PREFIX)`: `field, token = parse_pick_cid(custom_id)`. Update `self._pending_picks[token]` from the field + the interaction value (select value, or the trailing custom_id segment for kind/qdate buttons; resolve qdate today/tomorrow/nextmon to a `YYYY-MM-DD` using the current time). Re-render the appropriate card (`build_repeating_card`/`build_onetime_card`) via an UPDATE_MESSAGE. For `field == "typeit"` → return `{"type": MODAL, "data": build_schedule_modal()}`. For `field == "settask"` → return `{"type": MODAL, "data": schedule_picker.build_task_modal(token)}`.
  - Task-modal submit (`custom_id == aiuisched:pick:taskmodal:<token>`): read `what`; `picks = self._pending_picks.pop(token, {})`; `try: cron, run_once, label = picks_to_cron(picks, now=<now>)` `except PastTimeError: post "that time is already past"`. Then feed `(name=label-or-what, cron, prompt=what, run_once)` into the SAME downstream the text path uses — i.e. build a confirm card (`build_confirm_components`) storing `self._pending_schedules[token2] = {"name":..., "cron": cron, "prompt": what, "run_once": run_once}`, OR call `run_schedule_create(..., run_once=run_once)` directly if the existing flow does. **Read lines ~801-848 (`_pending_schedules`/confirm build) + `_handle_schedule_confirm` (~852-914) and reuse that exact path, only adding `run_once` to the stored pending dict and the final `run_schedule_create(..., run_once=...)` call.**

- [ ] **Step 4: Run to verify it passes.** Then full suite green.

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_schedule_picker_routing.py
git commit -m "feat(schedules): Discord picker routing (kind->picks->task modal->create)"
```

> The connector gate (does the prompt need gmail/drive?) already lives in the text path between parse and confirm. Route the picker's `(cron, run_once, prompt)` into that same gate so one-time gmail jobs still prompt to connect. If that adds too much branching, factor the post-`(cron,prompt)` logic into a shared helper both the text-modal and picker paths call — note it as DONE_WITH_CONCERNS if you split it.

---

## Task 6: Slack picker (native date/time pickers)

**Files:**
- Modify: `webhook-handler/handlers/slack_schedule_panel.py` (`build_schedule_modal`)
- Modify: `webhook-handler/handlers/slack_interactions.py` (`view_submission` for `SCHED_MODAL_ID`)
- Test: `webhook-handler/tests/test_slack_schedule_picker.py`

Replace the free-text "When?" input in the Slack create modal with native pickers. v1: all picker blocks are **always present** (Repeat `static_select`, `timepicker`, weekday `static_select`, `datepicker`); the converter uses only the relevant ones (true show/hide is phase 2).

- [ ] **Step 1: Write the failing test** — assert `build_schedule_modal()` now contains: the "what" input (unchanged), a Repeat `static_select` (options: one_time/daily/weekdays/weekly/hourly/every30), a `timepicker`, a weekday `static_select`, and a `datepicker` — each with stable block_id/action_id. Add `slack_picks_from_view(view)` that maps the submitted Block Kit state to a `picks` dict for `picks_to_cron`, and a `sample_view_state(...)` helper. Assert a repeating-weekly submission → `picks_to_cron` → `"0 9 * * 1"`, and a one-time submission → run_once cron.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** Add the four picker blocks to `build_schedule_modal`. Add `slack_picks_from_view(view)` translating: Repeat select value (`one_time`→kind=once else kind=rep+freq), `timepicker` `"HH:MM"`→hour, weekday select→weekday, `datepicker` `"YYYY-MM-DD"`→date. In `slack_interactions.py` `view_submission` for `SCHED_MODAL_ID`: build `picks` via `slack_picks_from_view`, `picks_to_cron(picks, now=<now>)` (catch `PastTimeError` → respond with an error in the modal response), then the existing create call with `run_once`. Keep the edit modal (`SCHED_EDITMODAL_PREFIX`) on the text path unchanged for v1.

- [ ] **Step 4: Run to verify it passes.** Full webhook-handler suite green.

- [ ] **Step 5: Commit**
```bash
git add webhook-handler/handlers/slack_schedule_panel.py webhook-handler/handlers/slack_interactions.py webhook-handler/tests/test_slack_schedule_picker.py
git commit -m "feat(schedules): Slack native date/time pickers in the create modal"
```

> Slack `view_submission` can return `{"response_action":"errors", ...}` to show a field error without closing the modal — use that for the past-time case so the user can fix it inline.

---

## Final verification (before merge — separate step)
- [ ] Full webhook-handler suite green: `cd webhook-handler; ./.venv/Scripts/python.exe -m pytest -q`
- [ ] Tasks pure tests green: `cd mcp-servers/tasks; "../../webhook-handler/.venv/Scripts/python.exe" -m pytest tests/test_scheduler_run_once.py tests/test_scheduler_delivery.py -v`
- [ ] @superpowers:verification-before-completion: state evidence (counts) before claiming done.
- [ ] Deploy is a SEPARATE step (per CLAUDE.md): tasks (migration 020 + scheduler + route) and webhook-handler (the bot pickers). Verify `/tasks/healthz`. The `run_once` column migration auto-applies on tasks boot.
- [ ] Manual smoke after deploy: create a one-time schedule 2 minutes out → confirm it fires once and then shows as paused/disabled (doesn't fire again).

## Notes for the implementer
- The riskiest task is **Task 5 (Discord multi-step routing)** — the pick accumulation. Keep `_pending_picks` keyed by a short token (mirror `_pending_schedules`); re-render the card on each pick; only the final task-modal resolves `picks_to_cron`. If a card exceeds 5 action rows, drop the least-needed select.
- Everything additive except the `SCHED_NEW` behavior swap (text modal → picker) and the Slack modal's "When?" field (text → pickers). The Discord text modal stays reachable via "⌨️ Type it instead" and the Slack edit modal is unchanged, so the fallback survives.
- `picks_to_cron` is the single source of truth for both platforms — keep all cron logic there.
