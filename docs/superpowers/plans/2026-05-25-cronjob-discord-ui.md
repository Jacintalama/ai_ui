# Cron Job Discord Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a button/select/modal-driven Discord panel for creating and managing scheduled agent prompts ("cron jobs"), living entirely in `webhook-handler` on top of the existing `/schedules` API.

**Architecture:** A new pure module `cronjob_panel.py` builds all Discord components and parses `cron:` custom_ids (mirroring `app_builder_panel.py`). `discord_commands.py` routes `cron:*` component clicks and modal submits; `commands.py` gains thin `run_cron_*` orchestration methods that call the tasks client and respond ephemerally. `clients/tasks.py` gains three schedule wrappers. A `setup_cronjob_channel.py` script posts a pinned panel to channel `1508420480283967509`. No `mcp-servers/tasks` (backend) changes.

**Tech Stack:** Python 3.11, FastAPI (webhook-handler), httpx async client, Discord Interactions HTTP API v10, pytest (+ pytest-asyncio for routing tests).

**Spec:** `docs/superpowers/specs/2026-05-25-cronjob-discord-ui-design.md`

**Conventions:**
- Run all commands from the repo root `C:\All\Work - Code\ai_ui` (or the webhook-handler container — see Task 11).
- Tests live in `webhook-handler/tests/`. Run with `python -m pytest` from `webhook-handler/`.
- Commit messages: NO AI co-author / `Co-Authored-By` trailer (project rule). Author is Ralph.
- Match the async-test/fixture style of the existing `webhook-handler/tests/` app-builder routing tests when writing the routing tests in Tasks 9–10.

---

## File Structure

**Create:**
- `webhook-handler/handlers/cronjob_panel.py` — pure component builders + cron-expr builder + custom_id parsers. One responsibility: translate between cron-job intent and Discord component dicts / custom_ids. No I/O.
- `webhook-handler/scripts/setup_cronjob_channel.py` — one-shot idempotent channel setup + pinned panel post.
- `webhook-handler/tests/test_cronjob_panel.py` — unit tests for the pure module.
- `webhook-handler/tests/test_cronjob_routing.py` — interaction routing + modal submit tests.

**Modify:**
- `webhook-handler/clients/tasks.py` — add `enable_schedule`, `disable_schedule`, `run_now_schedule`.
- `webhook-handler/handlers/commands.py` — add `run_cron_*` orchestration methods; update `_handle_help`.
- `webhook-handler/handlers/discord_commands.py` — add `CHANNEL_MESSAGE`/`UPDATE_MESSAGE` callback constants and `cron:*` routing branches in `_handle_message_component` + `_handle_modal_submit`.

---

## Task 1: Cron-expression builder + human description (pure)

**Files:**
- Create: `webhook-handler/handlers/cronjob_panel.py`
- Test: `webhook-handler/tests/test_cronjob_panel.py`

- [ ] **Step 1: Write the failing tests**

```python
# webhook-handler/tests/test_cronjob_panel.py
import pytest
from handlers import cronjob_panel as cp


def test_cron_from_choice_daily():
    assert cp.cron_from_choice("daily", hour=9) == "0 9 * * *"

def test_cron_from_choice_weekdays():
    assert cp.cron_from_choice("weekdays", hour=8) == "0 8 * * 1-5"

def test_cron_from_choice_weekly():
    assert cp.cron_from_choice("weekly", hour=18, dow="1") == "0 18 * * 1"

def test_cron_from_choice_hourly_ignores_hour():
    assert cp.cron_from_choice("hourly") == "0 * * * *"

def test_cron_from_choice_weekly_requires_dow():
    with pytest.raises(ValueError):
        cp.cron_from_choice("weekly", hour=9)

def test_cron_from_choice_daily_requires_hour():
    with pytest.raises(ValueError):
        cp.cron_from_choice("daily")

def test_describe_cron_daily():
    assert cp.describe_cron("0 9 * * *") == "daily at 09:00"

def test_describe_cron_weekdays():
    assert cp.describe_cron("0 8 * * 1-5") == "weekdays at 08:00"

def test_describe_cron_weekly():
    assert cp.describe_cron("0 18 * * 1") == "Mondays at 18:00"

def test_describe_cron_hourly():
    assert cp.describe_cron("0 * * * *") == "every hour"

def test_describe_cron_unknown_falls_back_to_raw():
    assert cp.describe_cron("*/7 13 5 * *") == "*/7 13 5 * *"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `webhook-handler/`): `python -m pytest tests/test_cronjob_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.cronjob_panel'` (or import error).

- [ ] **Step 3: Write minimal implementation**

```python
# webhook-handler/handlers/cronjob_panel.py
"""Pure builders + parsers for the Discord cron-job panel.

No I/O. Every function maps inputs to Discord component dicts or parses a
custom_id. Mirrors app_builder_panel.py. Tested in tests/test_cronjob_panel.py.
"""
from __future__ import annotations

_PREFIX = "cron"

_DOW_DESC = {
    "0": "Sundays", "1": "Mondays", "2": "Tuesdays", "3": "Wednesdays",
    "4": "Thursdays", "5": "Fridays", "6": "Saturdays",
}


def cron_from_choice(freq: str, hour: int | None = None, dow: str | None = None) -> str:
    """Build a 5-field cron expression from a friendly choice."""
    if freq == "hourly":
        return "0 * * * *"
    if hour is None:
        raise ValueError(f"hour required for freq={freq!r}")
    if freq == "daily":
        return f"0 {hour} * * *"
    if freq == "weekdays":
        return f"0 {hour} * * 1-5"
    if freq == "weekly":
        if dow is None:
            raise ValueError("dow required for weekly")
        return f"0 {hour} * * {dow}"
    raise ValueError(f"unknown freq={freq!r}")


def describe_cron(cron_expr: str) -> str:
    """Humanize a cron expression for confirmations / the schedule menu.

    Falls back to echoing the raw string for anything it can't humanize.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    minute, hour, dom, mon, dow = parts
    if minute == "0" and hour == "*" and dom == "*" and mon == "*" and dow == "*":
        return "every hour"
    if not (minute.isdigit() and hour.isdigit()):
        return cron_expr
    t = f"{int(hour):02d}:{int(minute):02d}"
    if dom == "*" and mon == "*":
        if dow == "*":
            return f"daily at {t}"
        if dow == "1-5":
            return f"weekdays at {t}"
        if dow in _DOW_DESC:
            return f"{_DOW_DESC[dow]} at {t}"
    return cron_expr
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cronjob_panel.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/cronjob_panel.py webhook-handler/tests/test_cronjob_panel.py
git commit -m "feat(cron): cron-expression builder and human-readable describe_cron"
```

---

## Task 2: custom_id encode/decode + predicates/extractors (pure)

**Files:**
- Modify: `webhook-handler/handlers/cronjob_panel.py`
- Test: `webhook-handler/tests/test_cronjob_panel.py`

custom_id grammar (all under the `cron:` prefix):
`cron:new`, `cron:list`, `cron:select`, `cron:freq:<freq>`, `cron:dow`,
`cron:hour:<freq>[:<dow>]`, `cron:create:<encoded_cron>`, `cron:customcron`,
`cron:runnow:<id>`, `cron:pause:<id>`, `cron:resume:<id>`, `cron:delete:<id>`,
`cron:delconfirm:<id>`, `cron:delcancel`.

- [ ] **Step 1: Write the failing tests** (append to `test_cronjob_panel.py`)

```python
def test_encode_decode_cron_roundtrip():
    for expr in ["0 9 * * *", "0 8 * * 1-5", "0 18 * * 1", "0 * * * *"]:
        assert cp.decode_cron(cp.encode_cron(expr)) == expr

def test_encode_cron_has_no_spaces():
    assert " " not in cp.encode_cron("0 9 * * *")

def test_is_cron_prefix():
    assert cp.is_cron("cron:new") is True
    assert cp.is_cron("aiuibuild:tpl:x") is False

def test_simple_predicates():
    assert cp.is_new("cron:new")
    assert cp.is_list("cron:list")
    assert cp.is_schedule_select("cron:select")
    assert not cp.is_new("cron:list")

def test_freq_from_button():
    assert cp.is_freq_button("cron:freq:daily")
    assert cp.freq_from_button("cron:freq:weekly") == "weekly"
    with pytest.raises(ValueError):
        cp.freq_from_button("cron:new")

def test_hour_context_from_select():
    assert cp.hour_context_from_select("cron:hour:daily") == ("daily", None)
    assert cp.hour_context_from_select("cron:hour:weekly:3") == ("weekly", "3")

def test_create_modal_cron_roundtrip():
    cid = cp.create_modal_id("0 9 * * 1")
    assert cid.startswith("cron:create:")
    assert cp.is_create_modal(cid)
    assert cp.cron_from_create_modal(cid) == "0 9 * * 1"

def test_action_id_extractors():
    assert cp.is_action("cron:runnow:abc", "runnow")
    assert cp.id_from_action("cron:runnow:abc-123", "runnow") == "abc-123"
    assert cp.id_from_action("cron:delete:xyz", "delete") == "xyz"
    with pytest.raises(ValueError):
        cp.id_from_action("cron:pause:1", "runnow")

def test_custom_id_length_under_discord_limit():
    # Longest custom_id is a delete-confirm on a 36-char UUID.
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert len(f"cron:delconfirm:{uuid}") < 100
    # And a create modal carrying a custom cron stays under the limit.
    assert len(cp.create_modal_id("*/5 0-23 * * 1-5")) < 100
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_panel.py -k "encode or predicate or freq or hour_context or create_modal or action or length" -v`
Expected: FAIL — attributes not defined.

- [ ] **Step 3: Implement** (append to `cronjob_panel.py`)

```python
# ── custom_id constants ──────────────────────────────────────────────
NEW = f"{_PREFIX}:new"
LIST = f"{_PREFIX}:list"
SELECT = f"{_PREFIX}:select"
DOW_SELECT = f"{_PREFIX}:dow"
CUSTOM_CRON_MODAL = f"{_PREFIX}:customcron"
DELCANCEL = f"{_PREFIX}:delcancel"


def encode_cron(cron_expr: str) -> str:
    """Pack a cron expression into a single custom_id token (spaces -> '_')."""
    return cron_expr.replace(" ", "_")


def decode_cron(token: str) -> str:
    return token.replace("_", " ")


def is_cron(custom_id: str) -> bool:
    return custom_id.split(":", 1)[0] == _PREFIX


def is_new(c: str) -> bool:
    return c == NEW


def is_list(c: str) -> bool:
    return c == LIST


def is_schedule_select(c: str) -> bool:
    return c == SELECT


def is_dow_select(c: str) -> bool:
    return c == DOW_SELECT


def is_freq_button(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:freq:")


def freq_from_button(c: str) -> str:
    prefix = f"{_PREFIX}:freq:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return c[len(prefix):]


def hour_select_id(freq: str, dow: str | None = None) -> str:
    return f"{_PREFIX}:hour:{freq}" + (f":{dow}" if dow else "")


def is_hour_select(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:hour:")


def hour_context_from_select(c: str) -> tuple[str, str | None]:
    prefix = f"{_PREFIX}:hour:"
    if not c.startswith(prefix):
        raise ValueError(c)
    bits = c[len(prefix):].split(":")
    return bits[0], (bits[1] if len(bits) > 1 else None)


def create_modal_id(cron_expr: str) -> str:
    return f"{_PREFIX}:create:{encode_cron(cron_expr)}"


def is_create_modal(c: str) -> bool:
    return c.startswith(f"{_PREFIX}:create:")


def is_custom_cron_modal(c: str) -> bool:
    return c == CUSTOM_CRON_MODAL


def cron_from_create_modal(c: str) -> str:
    prefix = f"{_PREFIX}:create:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return decode_cron(c[len(prefix):])


def action_id(verb: str, schedule_id: str) -> str:
    return f"{_PREFIX}:{verb}:{schedule_id}"


def is_action(c: str, verb: str) -> bool:
    return c.startswith(f"{_PREFIX}:{verb}:")


def id_from_action(c: str, verb: str) -> str:
    prefix = f"{_PREFIX}:{verb}:"
    if not c.startswith(prefix):
        raise ValueError(c)
    return c[len(prefix):]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_panel.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/cronjob_panel.py webhook-handler/tests/test_cronjob_panel.py
git commit -m "feat(cron): custom_id encode/decode and parser helpers"
```

---

## Task 3: Component builders — panel, frequency, day/hour selects (pure)

**Files:**
- Modify: `webhook-handler/handlers/cronjob_panel.py`
- Test: `webhook-handler/tests/test_cronjob_panel.py`

Discord component reference (match `app_builder_panel.py`): action row `{"type":1,"components":[...]}`; button `{"type":2,"style":N,"label":...,"custom_id":...}`; string-select `{"type":3,"custom_id":...,"placeholder":...,"options":[{"label","value","description"?}]}`. Button styles: 1 primary, 2 secondary, 3 success, 4 danger, 5 link.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_panel_payload_has_two_buttons():
    payload = cp.build_panel_payload()
    assert "content" in payload
    rows = payload["components"]
    buttons = [c for row in rows for c in row["components"]]
    ids = {b["custom_id"] for b in buttons}
    assert ids == {"cron:new", "cron:list"}

def test_frequency_components_five_buttons():
    rows = cp.build_frequency_components()
    buttons = [c for row in rows for c in row["components"]]
    ids = [b["custom_id"] for b in buttons]
    assert ids == [
        "cron:freq:daily", "cron:freq:weekdays", "cron:freq:weekly",
        "cron:freq:hourly", "cron:freq:custom",
    ]

def test_dow_select_has_seven_options():
    rows = cp.build_dow_select()
    sel = rows[0]["components"][0]
    assert sel["type"] == 3
    assert sel["custom_id"] == "cron:dow"
    assert [o["value"] for o in sel["options"]] == ["1", "2", "3", "4", "5", "6", "0"]

def test_hour_select_24_options_and_context_in_custom_id():
    rows = cp.build_hour_select("daily")
    sel = rows[0]["components"][0]
    assert sel["custom_id"] == "cron:hour:daily"
    assert len(sel["options"]) == 24
    assert sel["options"][9]["value"] == "9"
    assert sel["options"][9]["label"] == "09:00"

def test_hour_select_weekly_carries_dow():
    rows = cp.build_hour_select("weekly", dow="1")
    assert rows[0]["components"][0]["custom_id"] == "cron:hour:weekly:1"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_panel.py -k "panel or frequency or dow_select or hour_select" -v`
Expected: FAIL — builders not defined.

- [ ] **Step 3: Implement** (append)

```python
_FREQS = [
    ("daily", "Daily", 1),
    ("weekdays", "Weekdays", 1),
    ("weekly", "Weekly", 1),
    ("hourly", "Hourly", 1),
    ("custom", "Custom…", 2),
]
_DOW_OPTIONS = [
    ("1", "Monday"), ("2", "Tuesday"), ("3", "Wednesday"), ("4", "Thursday"),
    ("5", "Friday"), ("6", "Saturday"), ("0", "Sunday"),
]


def build_panel_payload() -> dict:
    return {
        "content": (
            "⏰ **AIUI Cron Jobs**\n"
            "Schedule a prompt to run automatically.\n"
            "• **Schedule a task** — pick how often + what to do\n"
            "• **My schedules** — run now, pause/resume, or delete"
        ),
        "components": [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 3, "label": "⏰ Schedule a task", "custom_id": NEW},
                    {"type": 2, "style": 1, "label": "📋 My schedules", "custom_id": LIST},
                ],
            }
        ],
    }


def build_frequency_components() -> list[dict]:
    return [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": style, "label": label,
                 "custom_id": f"{_PREFIX}:freq:{key}"}
                for key, label, style in _FREQS
            ],
        }
    ]


def build_dow_select() -> list[dict]:
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 3,
                    "custom_id": DOW_SELECT,
                    "placeholder": "Which day?",
                    "options": [{"label": label, "value": val}
                                for val, label in _DOW_OPTIONS],
                }
            ],
        }
    ]


def build_hour_select(freq: str, dow: str | None = None) -> list[dict]:
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 3,
                    "custom_id": hour_select_id(freq, dow),
                    "placeholder": "At what time? (Asia/Manila)",
                    "options": [
                        {"label": f"{h:02d}:00", "value": str(h)} for h in range(24)
                    ],
                }
            ],
        }
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_panel.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/cronjob_panel.py webhook-handler/tests/test_cronjob_panel.py
git commit -m "feat(cron): panel, frequency, day and hour component builders"
```

---

## Task 4: Component builders — schedules select, per-schedule menu, delete-confirm, modals (pure)

**Files:**
- Modify: `webhook-handler/handlers/cronjob_panel.py`
- Test: `webhook-handler/tests/test_cronjob_panel.py`

A schedule dict (from the tasks API) looks like:
`{"id","user_email","name","cron_expr","tz","persona","prompt","enabled","last_run_at","last_run_status"}`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _sched(**kw):
    base = {"id": "s1", "name": "morning", "cron_expr": "0 9 * * *",
            "enabled": True, "last_run_status": None, "last_run_at": None}
    base.update(kw)
    return base

def test_schedules_select_caps_at_25():
    schedules = [_sched(id=str(i), name=f"job{i}") for i in range(40)]
    rows = cp.build_schedules_select(schedules)
    sel = rows[0]["components"][0]
    assert sel["custom_id"] == "cron:select"
    assert len(sel["options"]) == 25
    assert sel["options"][0]["value"] == "0"

def test_schedule_menu_enabled_shows_pause():
    rows = cp.build_schedule_menu(_sched(enabled=True))
    ids = [b["custom_id"] for row in rows for b in row["components"]]
    assert "cron:runnow:s1" in ids
    assert "cron:pause:s1" in ids
    assert "cron:resume:s1" not in ids
    assert "cron:delete:s1" in ids

def test_schedule_menu_disabled_shows_resume():
    rows = cp.build_schedule_menu(_sched(enabled=False))
    ids = [b["custom_id"] for row in rows for b in row["components"]]
    assert "cron:resume:s1" in ids
    assert "cron:pause:s1" not in ids

def test_schedule_menu_text_describes_cron():
    text = cp.format_schedule_line(_sched(cron_expr="0 9 * * *", name="morning"))
    assert "morning" in text
    assert "daily at 09:00" in text

def test_delete_confirm_buttons():
    rows = cp.build_delete_confirm("s1")
    ids = [b["custom_id"] for row in rows for b in row["components"]]
    assert ids == ["cron:delconfirm:s1", "cron:delcancel"]

def test_create_modal_carries_cron_and_two_inputs():
    modal = cp.build_create_modal("0 9 * * *")
    assert modal["custom_id"] == "cron:create:0_9_*_*_*"
    field_ids = [c["components"][0]["custom_id"] for c in modal["components"]]
    assert field_ids == ["name", "prompt"]

def test_custom_cron_modal_three_inputs():
    modal = cp.build_custom_cron_modal()
    assert modal["custom_id"] == "cron:customcron"
    field_ids = [c["components"][0]["custom_id"] for c in modal["components"]]
    assert field_ids == ["cron", "name", "prompt"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_panel.py -k "schedules_select or schedule_menu or delete_confirm or create_modal or custom_cron_modal or format_schedule" -v`
Expected: FAIL.

- [ ] **Step 3: Implement** (append)

```python
_MAX_SELECT_OPTIONS = 25


def format_schedule_line(sched: dict) -> str:
    state = "🟢 on" if sched.get("enabled") else "⚪ off"
    desc = describe_cron(sched.get("cron_expr", ""))
    last = sched.get("last_run_status")
    last_str = f" · last: {last}" if last else ""
    return f"**{sched.get('name','(unnamed)')}** — {desc} [{state}]{last_str}"


def build_schedules_select(schedules: list[dict]) -> list[dict]:
    options = []
    for s in schedules[:_MAX_SELECT_OPTIONS]:
        label = (s.get("name") or s.get("id"))[:100]
        options.append({
            "label": label,
            "value": str(s["id"]),
            "description": describe_cron(s.get("cron_expr", ""))[:100],
        })
    return [{
        "type": 1,
        "components": [{
            "type": 3,
            "custom_id": SELECT,
            "placeholder": "Select a schedule to manage…",
            "options": options,
        }],
    }]


def build_schedule_menu(sched: dict) -> list[dict]:
    sid = str(sched["id"])
    toggle = (
        {"type": 2, "style": 2, "label": "⏸ Pause", "custom_id": action_id("pause", sid)}
        if sched.get("enabled")
        else {"type": 2, "style": 3, "label": "▶ Resume", "custom_id": action_id("resume", sid)}
    )
    return [{
        "type": 1,
        "components": [
            {"type": 2, "style": 1, "label": "▶️ Run now", "custom_id": action_id("runnow", sid)},
            toggle,
            {"type": 2, "style": 4, "label": "🗑 Delete", "custom_id": action_id("delete", sid)},
        ],
    }]


def build_delete_confirm(schedule_id: str) -> list[dict]:
    return [{
        "type": 1,
        "components": [
            {"type": 2, "style": 4, "label": "Confirm delete",
             "custom_id": action_id("delconfirm", schedule_id)},
            {"type": 2, "style": 2, "label": "Cancel", "custom_id": DELCANCEL},
        ],
    }]


def _text_input(custom_id: str, label: str, *, style: int, required: bool,
                placeholder: str = "", max_length: int | None = None) -> dict:
    comp = {"type": 4, "custom_id": custom_id, "label": label,
            "style": style, "required": required}
    if placeholder:
        comp["placeholder"] = placeholder
    if max_length:
        comp["max_length"] = max_length
    return {"type": 1, "components": [comp]}


def build_create_modal(cron_expr: str) -> dict:
    return {
        "title": "New scheduled task",
        "custom_id": create_modal_id(cron_expr),
        "components": [
            _text_input("name", "Name (optional)", style=1, required=False,
                        placeholder="morning-summary", max_length=80),
            _text_input("prompt", "What should I do?", style=2, required=True,
                        placeholder="Summarize my unread emails"),
        ],
    }


def build_custom_cron_modal() -> dict:
    return {
        "title": "Custom schedule",
        "custom_id": CUSTOM_CRON_MODAL,
        "components": [
            _text_input("cron", "Cron expression (min hour dom mon dow)", style=1,
                        required=True, placeholder="0 9 * * 1-5", max_length=60),
            _text_input("name", "Name (optional)", style=1, required=False,
                        max_length=80),
            _text_input("prompt", "What should I do?", style=2, required=True,
                        placeholder="Summarize my unread emails"),
        ],
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_panel.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/cronjob_panel.py webhook-handler/tests/test_cronjob_panel.py
git commit -m "feat(cron): schedules select, per-schedule menu, delete-confirm, and modals"
```

---

## Task 5: Tasks-client schedule wrappers (enable / disable / run-now)

**Files:**
- Modify: `webhook-handler/clients/tasks.py` (add after `delete_schedule`, ~line 72)
- Test: `webhook-handler/tests/test_tasks_client_schedules.py` (create)

The existing `_request(method, path, user_email, **kwargs)` raises `TasksAPIError` on non-2xx and returns the `httpx.Response`. The backend endpoints are `POST /schedules/{id}/enable|disable|run-now`.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_tasks_client_schedules.py
import pytest
from clients.tasks import TasksClient


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


@pytest.mark.asyncio
async def test_enable_disable_runnow_hit_expected_paths(monkeypatch):
    calls = []

    async def fake_request(self, method, path, user_email, **kwargs):
        calls.append((method, path, user_email))
        return _FakeResp({"ok": True})

    monkeypatch.setattr(TasksClient, "_request", fake_request, raising=True)
    c = TasksClient(base_url="http://tasks:8210")

    await c.enable_schedule("u@x.com", "s1")
    await c.disable_schedule("u@x.com", "s1")
    await c.run_now_schedule("u@x.com", "s1")

    assert calls == [
        ("POST", "/schedules/s1/enable", "u@x.com"),
        ("POST", "/schedules/s1/disable", "u@x.com"),
        ("POST", "/schedules/s1/run-now", "u@x.com"),
    ]
```

> Note: if `TasksClient.__init__` requires different args, match the existing test setup in `webhook-handler/tests/` for the tasks client.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_tasks_client_schedules.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'enable_schedule'`.

- [ ] **Step 3: Implement** (insert after `delete_schedule`)

```python
    async def enable_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/enable", user_email,
        )
        return resp.json()

    async def disable_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/disable", user_email,
        )
        return resp.json()

    async def run_now_schedule(self, user_email: str, schedule_id: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"/schedules/{schedule_id}/run-now", user_email,
        )
        return resp.json()
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_tasks_client_schedules.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client_schedules.py
git commit -m "feat(cron): tasks-client enable/disable/run-now schedule wrappers"
```

---

## Task 6: `run_cron_*` orchestration methods on the command router

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (add methods next to `run_panel_menu`/`run_panel_status`, ~line 1610–1660)
- Test: `webhook-handler/tests/test_cronjob_routing.py` (create; this task adds the router-method tests, Tasks 9–10 add interaction tests)

These methods receive a `CommandContext` (already carrying `user_id`, `respond`, and `respond_components`), resolve the user's email via `self._discord_user_email_map.get(ctx.user_id)`, call `self._tasks_client`, and reply through `ctx.respond` / `ctx.respond_components`. Wrap tasks calls in `try/except TasksAPIError` → `self._friendly_schedule_error(e)` (existing helper, ~line 1714). Reuse the existing unmapped-email message used by `_handle_cronjob` (~line 1281).

- [ ] **Step 1: Write the failing tests**

```python
# webhook-handler/tests/test_cronjob_routing.py
import pytest
from handlers.commands import CommandRouter, CommandContext


def _ctx(**kw):
    sent, comps = [], []
    async def respond(m): sent.append(m)
    async def respond_components(m, c): comps.append((m, c))
    base = dict(
        user_id="d1", user_name="ralph", channel_id="c1", raw_text="",
        subcommand="cronjob", arguments="", platform="discord",
        respond=respond, respond_components=respond_components,
    )
    base.update(kw)
    ctx = CommandContext(**base)
    return ctx, sent, comps


class _FakeTasks:
    def __init__(self): self.calls = []
    async def create_schedule(self, email, name, cron, prompt, **kw):
        self.calls.append(("create", email, name, cron, prompt)); return {"id": "s9"}
    async def list_schedules(self, email):
        self.calls.append(("list", email)); return [
            {"id": "s1", "name": "m", "cron_expr": "0 9 * * *", "enabled": True,
             "last_run_status": None}]
    async def run_now_schedule(self, email, sid):
        self.calls.append(("runnow", email, sid)); return {"ok": True}
    async def enable_schedule(self, email, sid):
        self.calls.append(("enable", email, sid)); return {"id": sid, "enabled": True}
    async def disable_schedule(self, email, sid):
        self.calls.append(("disable", email, sid)); return {"id": sid, "enabled": False}
    async def delete_schedule(self, email, sid):
        self.calls.append(("delete", email, sid)); return True


def _router(tasks):
    r = CommandRouter.__new__(CommandRouter)   # bypass heavy __init__
    r._tasks_client = tasks
    r._discord_user_email_map = {"d1": "u@x.com"}
    return r


@pytest.mark.asyncio
async def test_run_cron_create_calls_api_and_confirms():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_create(ctx, cron_expr="0 9 * * *", name="", prompt="do things")
    assert tasks.calls[0][0] == "create"
    assert "daily at 09:00" in sent[-1]

@pytest.mark.asyncio
async def test_run_cron_create_rejects_blank_prompt():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_create(ctx, cron_expr="0 9 * * *", name="", prompt="   ")
    assert tasks.calls == []          # never hit the API
    assert "prompt" in sent[-1].lower()

@pytest.mark.asyncio
async def test_run_cron_list_renders_select():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, _, comps = _ctx()
    await r.run_cron_list(ctx)
    assert comps                       # responded with components
    sel = comps[-1][1][0]["components"][0]
    assert sel["custom_id"] == "cron:select"

@pytest.mark.asyncio
async def test_run_cron_runnow_calls_api():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, sent, _ = _ctx()
    await r.run_cron_runnow(ctx, "s1")
    assert ("runnow", "u@x.com", "s1") in tasks.calls

@pytest.mark.asyncio
async def test_run_cron_pause_then_menu_reflects_state():
    tasks = _FakeTasks(); r = _router(tasks)
    ctx, _, comps = _ctx()
    await r.run_cron_pause(ctx, "s1")
    assert ("disable", "u@x.com", "s1") in tasks.calls
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_routing.py -v`
Expected: FAIL — `run_cron_*` not defined.

- [ ] **Step 3: Implement** (add to `CommandRouter` in `commands.py`)

```python
    def _cron_email_or_none(self, ctx: CommandContext) -> str | None:
        return self._discord_user_email_map.get(ctx.user_id)

    _CRON_NO_EMAIL = (
        "Your Discord account isn't linked to an AIUI user yet. "
        "Ask an admin to link it, then try again."
    )

    async def run_cron_create(self, ctx: CommandContext, *, cron_expr: str,
                              name: str, prompt: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        prompt = (prompt or "").strip()
        if not prompt:
            await ctx.respond("Please include a prompt — what should the job do?")
            return
        name = (name or "").strip() or f"discord-{ctx.user_name}-{cron_expr[:20]}"
        try:
            result = await self._tasks_client.create_schedule(
                email, name=name, cron=cron_expr, prompt=prompt,
            )
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))
            return
        from handlers import cronjob_panel as cp
        await ctx.respond(
            f"✅ Scheduled **{name}** — {cp.describe_cron(cron_expr)}\n"
            f"`{result.get('id','?')}` · {prompt[:200]}"
        )

    async def run_cron_list(self, ctx: CommandContext) -> None:
        from handlers import cronjob_panel as cp
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            schedules = await self._tasks_client.list_schedules(email)
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))
            return
        if not schedules:
            await ctx.respond("You have no schedules yet. Click **⏰ Schedule a task** to make one.")
            return
        if ctx.respond_components:
            await ctx.respond_components("**Your schedules** — pick one to manage:",
                                         cp.build_schedules_select(schedules))
        else:
            await ctx.respond("\n".join(cp.format_schedule_line(s) for s in schedules))

    async def _cron_menu_for(self, ctx, email, schedule_id, prefix=""):
        from handlers import cronjob_panel as cp
        schedules = await self._tasks_client.list_schedules(email)
        match = next((s for s in schedules if str(s["id"]) == str(schedule_id)), None)
        if not match:
            await ctx.respond("That schedule no longer exists.")
            return
        if ctx.respond_components:
            await ctx.respond_components(prefix + cp.format_schedule_line(match),
                                         cp.build_schedule_menu(match))
        else:
            await ctx.respond(prefix + cp.format_schedule_line(match))

    async def run_cron_menu(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            await self._cron_menu_for(ctx, email, schedule_id)
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))

    async def run_cron_runnow(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            await self._tasks_client.run_now_schedule(email, schedule_id)
            await ctx.respond("▶️ Triggered — it will run shortly.")
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))

    async def run_cron_pause(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            await self._tasks_client.disable_schedule(email, schedule_id)
            await self._cron_menu_for(ctx, email, schedule_id, prefix="⏸ Paused.\n")
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))

    async def run_cron_resume(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            await self._tasks_client.enable_schedule(email, schedule_id)
            await self._cron_menu_for(ctx, email, schedule_id, prefix="▶ Resumed.\n")
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))

    async def run_cron_delete(self, ctx: CommandContext, schedule_id: str) -> None:
        email = self._cron_email_or_none(ctx)
        if not email:
            await ctx.respond(self._CRON_NO_EMAIL)
            return
        try:
            await self._tasks_client.delete_schedule(email, schedule_id)
            await ctx.respond("🗑 Schedule deleted.")
        except TasksAPIError as e:
            await ctx.respond(self._friendly_schedule_error(e))
```

> If `TasksAPIError` isn't already imported at module top in `commands.py`, confirm the existing `_handle_cronjob` import and reuse it.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_routing.py -v`
Expected: PASS (router-method tests).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_cronjob_routing.py
git commit -m "feat(cron): run_cron_* orchestration methods on the command router"
```

---

## Task 7: discord_commands — add callback constants + helper for fresh ephemeral

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (constants block ~line 36–40; import block ~line 1–27)

The pinned panel is a public message. `cron:new` must create a **new ephemeral** message (callback type 4) with the frequency buttons — it must NOT edit the public panel. Subsequent clicks land on that ephemeral message, so they use **UPDATE_MESSAGE (7)** to swap components in place.

- [ ] **Step 1: Add the constants** (after `MODAL = 9`)

```python
CHANNEL_MESSAGE = 4        # CHANNEL_MESSAGE_WITH_SOURCE — new (ephemeral) message
UPDATE_MESSAGE = 7         # edit the message the component is attached to
EPHEMERAL = 64             # message flag
```

- [ ] **Step 2: Add the cronjob_panel import** (with the other handler imports near the top)

```python
from handlers import cronjob_panel as cron
```

- [ ] **Step 3: Add a tiny helper near `_handle_panel_route`**

```python
    @staticmethod
    def _ephemeral_components(content: str, components: list, *, update: bool) -> dict:
        """Synchronous component response. update=True edits the current (ephemeral)
        message (type 7); update=False posts a new ephemeral message (type 4)."""
        return {
            "type": UPDATE_MESSAGE if update else CHANNEL_MESSAGE,
            "data": {"content": content, "components": components, "flags": EPHEMERAL},
        }
```

- [ ] **Step 4: Verify nothing broke**

Run: `python -m pytest tests/test_cronjob_panel.py tests/test_cronjob_routing.py -v`
Expected: PASS (unchanged — no routing yet).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py
git commit -m "feat(cron): discord callback constants and ephemeral-components helper"
```

---

## Task 8: discord_commands — CREATE-flow routing (new → freq → dow/hour → modal → submit)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` — `_handle_message_component` (add `cron:*` branches near the top, before the app-builder `is_panel_button` fallthrough); `_handle_modal_submit` (add `cron:` branches before the `is_panel_modal` fallthrough).
- Test: `webhook-handler/tests/test_cronjob_routing.py` (append interaction tests)

- [ ] **Step 1: Write the failing tests** (append). Match the existing app-builder routing test for how the handler is constructed (mock router + mock discord client); the helper below assumes a `_handler(router)` like the existing tests.

```python
from handlers.discord_commands import (
    DiscordCommandHandler, MESSAGE_COMPONENT, MODAL_SUBMIT, MODAL,
    CHANNEL_MESSAGE, UPDATE_MESSAGE,
)

def _component_payload(custom_id, values=None):
    data = {"custom_id": custom_id}
    if values is not None:
        data["values"] = values
    return {"type": MESSAGE_COMPONENT, "data": data,
            "token": "tok", "id": "iid",
            "member": {"user": {"id": "d1", "username": "ralph"}},
            "channel_id": "c1"}

def _modal_payload(custom_id, fields):
    rows = [{"components": [{"custom_id": k, "value": v}]} for k, v in fields.items()]
    return {"type": MODAL_SUBMIT, "data": {"custom_id": custom_id, "components": rows},
            "token": "tok", "id": "iid",
            "member": {"user": {"id": "d1", "username": "ralph"}}, "channel_id": "c1"}


@pytest.mark.asyncio
async def test_cron_new_opens_fresh_ephemeral_with_frequency():
    handler = _handler(_StubRouter())          # see existing app-builder routing test
    resp = await handler._handle_message_component(_component_payload("cron:new"))
    assert resp["type"] == CHANNEL_MESSAGE
    ids = [b["custom_id"] for row in resp["data"]["components"] for b in row["components"]]
    assert "cron:freq:daily" in ids

@pytest.mark.asyncio
async def test_cron_freq_daily_updates_to_hour_select():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:freq:daily"))
    assert resp["type"] == UPDATE_MESSAGE
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:hour:daily"

@pytest.mark.asyncio
async def test_cron_freq_weekly_updates_to_dow_select():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:freq:weekly"))
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:dow"

@pytest.mark.asyncio
async def test_cron_dow_select_updates_to_hour_select_with_dow():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:dow", values=["1"]))
    assert resp["data"]["components"][0]["components"][0]["custom_id"] == "cron:hour:weekly:1"

@pytest.mark.asyncio
async def test_cron_freq_hourly_opens_modal():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:freq:hourly"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:create:0_*_*_*_*"

@pytest.mark.asyncio
async def test_cron_freq_custom_opens_custom_modal():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:freq:custom"))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:customcron"

@pytest.mark.asyncio
async def test_cron_hour_select_opens_create_modal_with_built_cron():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(
        _component_payload("cron:hour:weekly:1", values=["18"]))
    assert resp["type"] == MODAL
    assert resp["data"]["custom_id"] == "cron:create:0_18_*_*_1"

@pytest.mark.asyncio
async def test_cron_create_modal_submit_invokes_run_cron_create():
    router = _StubRouter()
    handler = _handler(router)
    resp = await handler._handle_modal_submit(
        _modal_payload("cron:create:0_9_*_*_*", {"name": "m", "prompt": "do x"}))
    assert resp["type"] in (5,)                # deferred ephemeral ACK
    assert router.created == [("0 9 * * *", "m", "do x")]

@pytest.mark.asyncio
async def test_cron_custom_modal_submit_uses_typed_cron():
    router = _StubRouter()
    handler = _handler(router)
    await handler._handle_modal_submit(
        _modal_payload("cron:customcron", {"cron": "*/30 * * * *", "name": "", "prompt": "p"}))
    assert router.created == [("*/30 * * * *", "", "p")]
```

`_StubRouter` records calls: implement `run_cron_create(ctx, *, cron_expr, name, prompt)` to append `(cron_expr, name, prompt)` to `self.created`, and stub the other `run_cron_*` to no-ops. `_handler(router)` builds a `DiscordCommandHandler` with that router + a fake discord client (mirror the existing app-builder routing test's construction).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_routing.py -k "cron_new or freq or dow_select or hour_select or modal_submit or custom_modal" -v`
Expected: FAIL — branches not present.

- [ ] **Step 3: Implement — `_handle_message_component` cron branches**

Add at the top of `_handle_message_component` (after `custom_id = data.get("custom_id", "")`), before the app-builder branches:

```python
        if cron.is_cron(custom_id):
            return await self._handle_cron_component(payload, custom_id)
```

Add the new method:

```python
    async def _handle_cron_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        values = data.get("values") or []

        if cron.is_new(custom_id):
            return self._ephemeral_components(
                "How often should it run?", cron.build_frequency_components(), update=False)

        if cron.is_freq_button(custom_id):
            freq = cron.freq_from_button(custom_id)
            if freq == "hourly":
                return {"type": MODAL, "data": cron.build_create_modal("0 * * * *")}
            if freq == "custom":
                return {"type": MODAL, "data": cron.build_custom_cron_modal()}
            if freq == "weekly":
                return self._ephemeral_components(
                    "Which day?", cron.build_dow_select(), update=True)
            return self._ephemeral_components(
                "At what time? (Asia/Manila)", cron.build_hour_select(freq), update=True)

        if cron.is_dow_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return self._ephemeral_components(
                "At what time? (Asia/Manila)",
                cron.build_hour_select("weekly", dow=values[0]), update=True)

        if cron.is_hour_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            freq, dow = cron.hour_context_from_select(custom_id)
            cron_expr = cron.cron_from_choice(freq, hour=int(values[0]), dow=dow)
            return {"type": MODAL, "data": cron.build_create_modal(cron_expr)}

        # Manage-flow branches are added in Task 9.
        return await self._handle_cron_manage_component(payload, custom_id)
```

For this task, add a temporary stub so imports resolve (Task 9 replaces it):

```python
    async def _handle_cron_manage_component(self, payload, custom_id):
        logger.info(f"Unhandled cron component (manage not yet wired): {custom_id}")
        return {"type": DEFERRED_UPDATE_MESSAGE}
```

- [ ] **Step 4: Implement — `_handle_modal_submit` cron branches**

Add at the top of `_handle_modal_submit` (after `custom_id = data.get("custom_id", "")`), before the app-builder modal branches:

```python
        if cron.is_create_modal(custom_id) or cron.is_custom_cron_modal(custom_id):
            return await self._handle_cron_modal_submit(payload, custom_id)
```

Add the handler (mirrors `_handle_panel_route`: build an ephemeral `CommandContext`, schedule the run in the background, ACK deferred-ephemeral):

```python
    async def _handle_cron_modal_submit(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        name = self._extract_modal_value(data, "name") or ""
        prompt = self._extract_modal_value(data, "prompt") or ""
        if cron.is_custom_cron_modal(custom_id):
            cron_expr = (self._extract_modal_value(data, "cron") or "").strip()
        else:
            cron_expr = cron.cron_from_create_modal(custom_id)

        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))

        async def respond(msg: str) -> None:
            await self.discord.edit_original(interaction_token=interaction_token, content=msg)

        ctx = CommandContext(
            user_id=user.get("id", ""), user_name=user.get("username", "unknown"),
            channel_id=payload.get("channel_id", ""), raw_text="cronjob create",
            subcommand="cronjob", arguments="", platform="discord",
            respond=respond,
        )
        asyncio.create_task(
            self.router.run_cron_create(ctx, cron_expr=cron_expr, name=name, prompt=prompt))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": EPHEMERAL}}
```

> Confirm `_extract_modal_value(data, field)` is the existing helper signature (it is used by the app-builder enhance modal). If it raises on a missing optional field, guard with a try/except or default.

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_routing.py -v`
Expected: PASS (create-flow tests; manage tests still pending Task 9).

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_cronjob_routing.py
git commit -m "feat(cron): discord create-flow routing (new/freq/dow/hour + modal submit)"
```

---

## Task 9: discord_commands — MANAGE-flow routing (list / select / runnow / pause / resume / delete)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` — replace the `_handle_cron_manage_component` stub with the real implementation.
- Test: `webhook-handler/tests/test_cronjob_routing.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
@pytest.mark.asyncio
async def test_cron_list_routes_to_run_cron_list():
    router = _StubRouter(); handler = _handler(router)
    resp = await handler._handle_message_component(_component_payload("cron:list"))
    assert resp["type"] == DEFERRED_CHANNEL_MESSAGE
    assert resp["data"]["flags"] == 64
    await _drain()                       # let the background task run
    assert router.listed is True

@pytest.mark.asyncio
async def test_cron_select_routes_to_menu():
    router = _StubRouter(); handler = _handler(router)
    await handler._handle_message_component(_component_payload("cron:select", values=["s1"]))
    await _drain()
    assert router.menued == "s1"

@pytest.mark.asyncio
async def test_cron_runnow_pause_resume_delete_route():
    for verb, attr in [("runnow", "ran"), ("pause", "paused"),
                       ("resume", "resumed"), ("delconfirm", "deleted")]:
        router = _StubRouter(); handler = _handler(router)
        await handler._handle_message_component(_component_payload(f"cron:{verb}:s1"))
        await _drain()
        assert getattr(router, attr) == "s1"

@pytest.mark.asyncio
async def test_cron_delete_shows_confirm_inline():
    handler = _handler(_StubRouter())
    resp = await handler._handle_message_component(_component_payload("cron:delete:s1"))
    assert resp["type"] == UPDATE_MESSAGE
    ids = [b["custom_id"] for row in resp["data"]["components"] for b in row["components"]]
    assert ids == ["cron:delconfirm:s1", "cron:delcancel"]
```

`_drain()` awaits pending tasks, e.g. `await asyncio.sleep(0)` a couple times, or gather `asyncio.all_tasks()` excluding current. Extend `_StubRouter` with `run_cron_list/run_cron_menu/run_cron_runnow/run_cron_pause/run_cron_resume/run_cron_delete` recording calls.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cronjob_routing.py -k "cron_list or cron_select or runnow_pause or delete_shows_confirm" -v`
Expected: FAIL.

- [ ] **Step 3: Implement — replace the `_handle_cron_manage_component` stub**

```python
    async def _handle_cron_manage_component(self, payload: dict[str, Any], custom_id: str) -> dict[str, Any]:
        data = payload.get("data", {})
        values = data.get("values") or []

        if cron.is_list(custom_id):
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_list(ctx),
                raw_text="cronjob list")

        if cron.is_schedule_select(custom_id):
            if not values:
                return {"type": DEFERRED_UPDATE_MESSAGE}
            sid = values[0]
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_menu(ctx, sid),
                raw_text=f"cronjob menu {sid}")

        if cron.is_action(custom_id, "runnow"):
            sid = cron.id_from_action(custom_id, "runnow")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_runnow(ctx, sid),
                raw_text="cronjob runnow")

        if cron.is_action(custom_id, "pause"):
            sid = cron.id_from_action(custom_id, "pause")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_pause(ctx, sid),
                raw_text="cronjob pause")

        if cron.is_action(custom_id, "resume"):
            sid = cron.id_from_action(custom_id, "resume")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_resume(ctx, sid),
                raw_text="cronjob resume")

        if cron.is_action(custom_id, "delete"):
            sid = cron.id_from_action(custom_id, "delete")
            return self._ephemeral_components(
                "Delete this schedule? This can't be undone.",
                cron.build_delete_confirm(sid), update=True)

        if cron.is_action(custom_id, "delconfirm"):
            sid = cron.id_from_action(custom_id, "delconfirm")
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_cron_delete(ctx, sid),
                raw_text="cronjob delete")

        if custom_id == cron.DELCANCEL:
            return self._ephemeral_components("Cancelled.", [], update=True)

        logger.info(f"Ignoring unknown cron custom_id: {custom_id}")
        return {"type": DEFERRED_UPDATE_MESSAGE}
```

> `_handle_panel_route` already builds the ephemeral `CommandContext` with `respond_components` wired to `edit_original`, schedules the background `run`, and ACKs deferred-ephemeral (flags=64) — exactly what the manage actions need.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_cronjob_routing.py -v`
Expected: PASS (all routing tests).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_cronjob_routing.py
git commit -m "feat(cron): discord manage-flow routing (list/select/runnow/pause/resume/delete)"
```

---

## Task 10: Channel setup script + help text

**Files:**
- Create: `webhook-handler/scripts/setup_cronjob_channel.py` (model on `webhook-handler/scripts/setup_app_builder_channel.py`)
- Modify: `webhook-handler/handlers/commands.py` — `_handle_help` (~line 409) to mention the panel.

- [ ] **Step 1: Read the model script**

Read `webhook-handler/scripts/setup_app_builder_channel.py` in full and copy its structure (httpx.Client, headers, find/create channel, post message, pin).

- [ ] **Step 2: Write `setup_cronjob_channel.py`**

Key differences from the app-builder script:
- No template fetch needed — the panel is static (`cronjob_panel.build_panel_payload()`).
- Channel target priority: `CRONJOB_CHANNEL_ID` env (default `1508420480283967509`); if unset/empty, find-or-create by `CRONJOB_CHANNEL_NAME` (default `cron-jobs`).
- Import the panel builder:

```python
import os, sys
sys.path.insert(0, "/app")  # container app root, matching the app-builder script
from handlers.cronjob_panel import build_panel_payload
import httpx

API = "https://discord.com/api/v10"

def main() -> int:
    token = os.environ["DISCORD_BOT_TOKEN"]
    guild = os.environ.get("DISCORD_GUILD_ID", "")
    channel_id = os.environ.get("CRONJOB_CHANNEL_ID", "1508420480283967509").strip()
    name = os.environ.get("CRONJOB_CHANNEL_NAME", "cron-jobs")
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as c:
        if not channel_id:
            channel_id = _find_or_create(c, guild, name, headers)
        payload = build_panel_payload()
        r = c.post(f"{API}/channels/{channel_id}/messages", headers=headers, json=payload)
        r.raise_for_status()
        msg_id = r.json()["id"]
        c.put(f"{API}/channels/{channel_id}/pins/{msg_id}", headers=headers)
        print(f"Posted + pinned cron panel {msg_id} in channel {channel_id}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Implement `_find_or_create(c, guild, name, headers)` by copying the app-builder script's `_find_channel` + `_create_channel` (text channel type 0, topic "Schedule prompts with AIUI").

- [ ] **Step 3: Smoke-test import locally** (no Discord calls)

Run (from `webhook-handler/`): `python -c "from handlers.cronjob_panel import build_panel_payload; print(build_panel_payload()['components'][0]['components'][0]['custom_id'])"`
Expected: prints `cron:new`.

- [ ] **Step 4: Update `_handle_help`**

Change the existing cronjob help line (~line 409) to point at the panel:

```python
            "`/aiui cronjob` — Schedule prompts. Use the **#cron-jobs** channel panel "
            "(⏰ Schedule a task) or `cronjob create \"<cron>\" \"<prompt>\"`\n"
```

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/scripts/setup_cronjob_channel.py webhook-handler/handlers/commands.py
git commit -m "feat(cron): channel setup script and help text"
```

---

## Task 11: Full suite, deploy (VPS-in-place), and manual verification

**Files:** none (verification + deploy)

- [ ] **Step 1: Run the whole webhook-handler suite locally**

Run (from `webhook-handler/`): `python -m pytest -q`
Expected: all green, including the existing app-builder tests (no regressions).

- [ ] **Step 2: Deploy to the VPS webhook-handler container** (see [[reference_vps_connection.md]])

```bash
# from repo root, with the VPS key
KEY=~/.ssh/aiui_vps; VPS=root@46.224.193.25
for f in handlers/cronjob_panel.py handlers/commands.py handlers/discord_commands.py \
         clients/tasks.py scripts/setup_cronjob_channel.py \
         tests/test_cronjob_panel.py tests/test_cronjob_routing.py \
         tests/test_tasks_client_schedules.py; do
  scp -i $KEY "webhook-handler/$f" "$VPS:/tmp/$(basename $f)"
done
# move into the repo working tree on the VPS, then docker cp into the container
ssh -i $KEY $VPS '
  cd /root/proxy-server/webhook-handler &&
  # place files (mkdir tests/scripts if needed), run tests inside the container, then:
  docker compose -f /root/proxy-server/docker-compose.unified.yml exec -T webhook-handler \
    python -m pytest -q
'
```

> Match the exact deploy commands used for the app-builder rollout (docker cp each file into the running `webhook-handler` container, then `docker restart webhook-handler`). Run the pytest suite **inside** the container before restarting.

- [ ] **Step 3: Post the pinned panel**

```bash
ssh -i $KEY $VPS 'docker compose -f /root/proxy-server/docker-compose.unified.yml exec \
  -e DISCORD_GUILD_ID=<guild> webhook-handler \
  python /app/scripts/setup_cronjob_channel.py'
```
Expected: "Posted + pinned cron panel … in channel 1508420480283967509".

- [ ] **Step 4: Manual click-through in Discord** (channel `1508420480283967509`)

Verify each path; all responses must be ephemeral (only you see them):
1. ⏰ Schedule a task → Daily → pick 09:00 → modal → enter prompt → ✅ confirmation "daily at 09:00".
2. ⏰ → Weekly → pick Monday → pick 18:00 → modal → ✅ "Mondays at 18:00".
3. ⏰ → Hourly → modal → ✅ "every hour".
4. ⏰ → Custom… → enter `*/30 * * * *` + prompt → ✅ (echoes raw cron).
5. 📋 My schedules → select one → Run now (▶️ Triggered), Pause (button flips to Resume), Resume, Delete → Confirm (🗑 deleted).
6. Confirm a bad custom cron (e.g. `99 99 * * *`) shows the friendly "Invalid cron" error.

- [ ] **Step 5: Commit on the VPS + confirm parity**

The code is already committed locally per task. On the VPS, commit the in-place edits on `feat/gdrive-gmail-connectors` (no AI co-author) and confirm `git log` matches local. If the VPS working tree was edited directly, ensure the same files/commits exist on both sides (see [[project_vps_uncommitted_work_2026-05-22]]).

- [ ] **Step 6: Final verification statement**

Use superpowers:verification-before-completion — paste the passing `pytest -q` output and the manual click-through results before declaring done.

---

## Notes / Risks

- **Async test runner:** routing tests need `pytest.mark.asyncio` — confirm `pytest-asyncio` is in `webhook-handler` test deps (the app-builder routing tests already rely on it; mirror their config in `pytest.ini`).
- **`_extract_modal_value` on optional fields:** the optional `name` field may be absent from the modal payload; guard the extraction so it returns `""` rather than raising.
- **UPDATE_MESSAGE on ephemeral:** editing an ephemeral message via type 7 is valid for component interactions; if Discord rejects re-sending `flags`, drop `flags` from the `_ephemeral_components(update=True)` data (the message stays ephemeral regardless).
- **No backend changes:** if any step seems to require editing `mcp-servers/tasks`, stop — that's out of scope per the spec; the `/schedules` API already exposes everything needed.
