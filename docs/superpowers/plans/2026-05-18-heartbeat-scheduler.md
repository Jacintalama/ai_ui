# Heartbeat Scheduler v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a backend-only v1 of the open-claw heartbeat: cron-triggered agent runs, MD-file memory across runs, persona prefix, secret scrubbing. Manageable via a CLI; no UI yet.

**Architecture:** A new `tasks.schedules` table + a background coroutine in the `tasks` service that polls every minute and dispatches matching schedules through the existing `remote_executor` pipeline. Per-schedule `MEMORY.md` lives on the agent VM at `/agent/memory/<schedule-id>.md`, SCP'd into/out of each run's workdir. `secret_scrub.py` redacts patterns at three layers (agent-side post-run, orchestrator-side rsync-back, stream-level).

**Tech Stack:** FastAPI, SQLAlchemy, `croniter` (new dep), asyncio, pytest, bash.

**Spec:** `docs/superpowers/specs/2026-05-18-heartbeat-scheduler-design.md`

**Depends on:** Deploy hygiene plan should land first (we'll use the new deploy script to ship this).

---

### Task 1: Secret scrub module + tests

**Files:**
- Create: `mcp-servers/tasks/secret_scrub.py`
- Create: `mcp-servers/tasks/tests/test_secret_scrub.py`

- [ ] **Step 1: Write failing tests**

`mcp-servers/tasks/tests/test_secret_scrub.py`:

```python
from secret_scrub import scrub

def test_anthropic_key_redacted():
    txt = "key=sk-ant-abcDEF12345_xyz67890extra and tail"
    out = scrub(txt)
    assert "sk-ant-abc" not in out
    assert "<REDACTED_ANTHROPIC>" in out
    assert "tail" in out  # surrounding text preserved

def test_jwt_three_segments_redacted():
    jwt = "eyJabc123_def.eyJpayload456ghi.signaturepart789xyz"
    txt = f"Bearer {jwt} more"
    out = scrub(txt)
    assert "eyJabc" not in out
    assert "<REDACTED_JWT>" in out

def test_two_segment_string_not_redacted():
    # Looks like part of a JWT but isn't full — leave alone
    txt = "eyJabc123.eyJdef456"
    assert scrub(txt) == txt

def test_safe_prefix_alone_not_redacted():
    txt = "doc says use prefix sk-ant- when sharing"
    # "sk-ant-" alone (no key body) shouldn't trigger
    assert scrub(txt) == txt

def test_idempotent():
    txt = "key=sk-ant-realkey12345abcdef_xyz_more"
    once = scrub(txt)
    twice = scrub(once)
    assert once == twice

def test_google_key():
    txt = "GOOGLE_API_KEY=AIzaSyD-fake_key_payload_1234567890abcdef"
    out = scrub(txt)
    assert "AIza" not in out or "<REDACTED_GOOGLE>" in out

def test_duffel_key():
    txt = "DUFFEL_API_KEY=duffel_test_abcDEF1234567890_realtoken"
    out = scrub(txt)
    assert "duffel_test_abc" not in out
    assert "<REDACTED_DUFFEL>" in out

def test_github_token():
    txt = "GITHUB_TOKEN=ghp_abcDEF1234567890realtokenpayload_xyz123"
    out = scrub(txt)
    assert "<REDACTED_GITHUB>" in out

def test_slack_bot_token():
    txt = "x=xoxb-EXAMPLE-FAKE-FAKE-PLACEHOLDER"
    out = scrub(txt)
    assert "<REDACTED_SLACK>" in out
```

- [ ] **Step 2: Verify tests fail**

Run: `cd mcp-servers/tasks && pytest tests/test_secret_scrub.py -v`
Expected: ModuleNotFoundError on `secret_scrub`.

- [ ] **Step 3: Implement secret_scrub.py**

```python
"""Redact common credential patterns from any text touching disk or logs."""
import re

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED_ANTHROPIC>"),
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "<REDACTED_GOOGLE>"),
    (re.compile(r"duffel_test_[A-Za-z0-9_-]{20,}"), "<REDACTED_DUFFEL>"),
    (re.compile(r"duffel_live_[A-Za-z0-9_-]{20,}"), "<REDACTED_DUFFEL>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<REDACTED_JWT>"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "<REDACTED_GITHUB>"),
    (re.compile(r"xoxb-[A-Za-z0-9-]{30,}"), "<REDACTED_SLACK>"),
]


def scrub(text: str) -> str:
    """Replace every match of every pattern with its placeholder. Idempotent."""
    if not text:
        return text
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
```

- [ ] **Step 4: Verify all tests pass**

Run: `cd mcp-servers/tasks && pytest tests/test_secret_scrub.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/secret_scrub.py mcp-servers/tasks/tests/test_secret_scrub.py
git commit -m "feat(tasks): secret_scrub module with anthropic/google/jwt/duffel/github/slack patterns"
```

---

### Task 2: Database migration for schedules table

**Files:**
- Create: `mcp-servers/tasks/migrations/001_schedules.sql`
- Modify: `mcp-servers/tasks/db.py`
- Modify: `mcp-servers/tasks/models.py`

- [ ] **Step 1: Read existing db.py to understand init_db()**

Run: `cat mcp-servers/tasks/db.py | head -50`. Confirm how `init_db()` runs — there's likely a `Base.metadata.create_all()` call. Plan accordingly: either reuse SQLAlchemy ORM (preferred for consistency) or apply raw SQL.

- [ ] **Step 2: Add Schedule model**

In `mcp-servers/tasks/models.py`, after `ChatMessage`, append:

```python
class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = {"schema": "tasks"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    cron_expr = Column(Text, nullable=False)
    tz = Column(Text, nullable=False, default="Asia/Manila")
    persona = Column(Text, nullable=False, default="")
    prompt = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
```

Add `Boolean` to the SQLAlchemy import at top:
```python
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, Boolean
```

- [ ] **Step 3: Verify the table autocreate**

If `init_db()` uses `Base.metadata.create_all()`, no extra work needed — the Schedule class auto-creates. Otherwise add a raw SQL migration:

`mcp-servers/tasks/migrations/001_schedules.sql`:
```sql
CREATE TABLE IF NOT EXISTS tasks.schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_email TEXT NOT NULL,
  name TEXT NOT NULL,
  cron_expr TEXT NOT NULL,
  tz TEXT NOT NULL DEFAULT 'Asia/Manila',
  persona TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_run_at TIMESTAMPTZ NULL,
  last_run_status TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS schedules_enabled_idx ON tasks.schedules(enabled) WHERE enabled = TRUE;
```

And in `db.py`'s `init_db`, after the existing `create_all`, add a block that reads each `.sql` file in `migrations/` and executes it.

- [ ] **Step 4: Smoke import**

Run: `cd mcp-servers/tasks && python -c "from models import Schedule; print(Schedule.__table__)"`
Expected: prints the table definition with all columns.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/models.py mcp-servers/tasks/db.py mcp-servers/tasks/migrations/
git commit -m "feat(tasks): schedules table + Schedule ORM model"
```

---

### Task 3: Scheduler — tick loop + cron matching

**Files:**
- Create: `mcp-servers/tasks/scheduler.py`
- Create: `mcp-servers/tasks/tests/test_scheduler.py`
- Modify: `mcp-servers/tasks/requirements.txt`

- [ ] **Step 1: Add croniter dep**

Append to `mcp-servers/tasks/requirements.txt`:
```
croniter>=1.4,<2
```

- [ ] **Step 2: Write failing tests**

`mcp-servers/tasks/tests/test_scheduler.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from scheduler import cron_matches_now, should_fire

PH = ZoneInfo("Asia/Manila")

def test_cron_matches_at_20_00_PHT_not_at_20_00_UTC():
    pht_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=PH)
    assert cron_matches_now("0 20 * * *", "Asia/Manila", pht_8pm.astimezone(timezone.utc)) is True

    utc_8pm = datetime(2026, 5, 18, 20, 0, 0, tzinfo=timezone.utc)
    # In Manila that's 04:00 next day — does NOT match 0 20 * * *
    assert cron_matches_now("0 20 * * *", "Asia/Manila", utc_8pm) is False

def test_dedupe_within_same_minute():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    just_ran = datetime(2026, 5, 18, 12, 0, 5, tzinfo=timezone.utc)
    # last_run_at 25s ago, same minute → should NOT fire
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=just_ran, now=now, enabled=True) is False

def test_disabled_never_fires():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=False) is False

def test_enabled_first_run_fires_when_matched():
    now = datetime(2026, 5, 18, 12, 0, 30, tzinfo=timezone.utc)
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=None, now=now, enabled=True) is True

def test_enabled_last_run_old_enough_fires():
    now = datetime(2026, 5, 18, 12, 5, 30, tzinfo=timezone.utc)
    old = datetime(2026, 5, 18, 12, 4, 30, tzinfo=timezone.utc)  # 60s ago
    assert should_fire(cron_expr="* * * * *", tz="UTC",
                       last_run_at=old, now=now, enabled=True) is True
```

- [ ] **Step 3: Verify tests fail**

Run: `cd mcp-servers/tasks && pytest tests/test_scheduler.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement scheduler.py — pure functions first**

```python
"""Heartbeat scheduler: cron-triggered agent runs with per-schedule memory."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

logger = logging.getLogger("tasks.scheduler")


def cron_matches_now(cron_expr: str, tz: str, now_utc: datetime) -> bool:
    """True if `cron_expr` matches the current minute in `tz`."""
    local_now = now_utc.astimezone(ZoneInfo(tz))
    # Test if any prev_iter result is within the current minute
    iter_ = croniter(cron_expr, local_now)
    # get_prev gives most recent fire time at or before local_now
    prev = iter_.get_prev(datetime)
    return prev.replace(second=0, microsecond=0) == local_now.replace(second=0, microsecond=0)


def should_fire(
    *,
    cron_expr: str,
    tz: str,
    last_run_at: datetime | None,
    now: datetime,
    enabled: bool,
) -> bool:
    """Decide whether this schedule should fire now."""
    if not enabled:
        return False
    if not cron_matches_now(cron_expr, tz, now):
        return False
    if last_run_at is not None:
        # Dedupe — same minute already fired
        if (now - last_run_at).total_seconds() < 60:
            return False
    return True
```

- [ ] **Step 5: Run tests, expect pass**

`pytest tests/test_scheduler.py -v` → 5 passed.

- [ ] **Step 6: Commit**

```
git add mcp-servers/tasks/scheduler.py mcp-servers/tasks/tests/test_scheduler.py mcp-servers/tasks/requirements.txt
git commit -m "feat(tasks): scheduler.py cron-matching + should_fire logic"
```

---

### Task 4: Scheduler — DB integration + tick_once + run dispatch

**Files:**
- Modify: `mcp-servers/tasks/scheduler.py`
- Modify: `mcp-servers/tasks/main.py`
- Modify: `mcp-servers/tasks/tests/test_scheduler.py` (add integration tests)

- [ ] **Step 1: Add `_tick_once` and `schedule_tick_loop` to scheduler.py**

Append to `mcp-servers/tasks/scheduler.py`:

```python
import uuid as _uuid
from db import session
from models import Schedule, TaskItem
from sqlalchemy import select, update
from secret_scrub import scrub

# Concurrency cap to prevent storm at startup if many schedules match
_RUN_SEMAPHORE = asyncio.Semaphore(3)


async def _create_task_from_schedule(sched: Schedule) -> TaskItem:
    """Build a TaskItem row from a schedule and persist it."""
    desc = f"{sched.persona}\n\n---\n\nTask: {sched.prompt}\n\n(MEMORY.md is at the top of your working dir — read it first.)"
    item = TaskItem(
        id=_uuid.uuid4(),
        meeting_id=_uuid.UUID("00000000-0000-0000-0000-000000000000"),  # placeholder; schedules aren't tied to a meeting
        action_type="BUILD",
        assignee_name=sched.user_email.split("@")[0],
        assignee_email=sched.user_email,
        description=desc,
        priority="NICE_TO_HAVE",
        status="pending",
        mode="ai",
    )
    async with session() as s:
        s.add(item)
        await s.commit()
    return item


async def _run_scheduled_task(sched: Schedule) -> str:
    """Dispatch to existing execution flow. Returns final status."""
    # Avoid storm: bound concurrent agent runs at 3
    async with _RUN_SEMAPHORE:
        item = await _create_task_from_schedule(sched)
        # Reuse routes_execution._run_execution. Inline import to avoid cycles.
        from routes_execution import _run_execution
        try:
            status = await _run_execution(str(item.id), user_jwt=None, schedule_id=str(sched.id))
        except Exception as exc:
            logger.exception("schedule %s run failed: %s", sched.id, scrub(str(exc)))
            status = "failed"
    return status


async def _tick_once() -> None:
    now = datetime.now(timezone.utc)
    async with session() as s:
        rows = (await s.execute(select(Schedule).where(Schedule.enabled.is_(True)))).scalars().all()
    fire = [r for r in rows if should_fire(
        cron_expr=r.cron_expr, tz=r.tz, last_run_at=r.last_run_at, now=now, enabled=r.enabled
    )]
    if not fire:
        return
    logger.info("tick: %d schedule(s) firing", len(fire))
    for sched in fire:
        # Mark last_run_at IMMEDIATELY (pre-run) for dedupe — even if the run crashes,
        # the next minute's tick won't re-fire the same schedule.
        async with session() as s:
            await s.execute(
                update(Schedule).where(Schedule.id == sched.id).values(
                    last_run_at=now, last_run_status="running",
                )
            )
            await s.commit()
        asyncio.create_task(_finalize_run(sched))


async def _finalize_run(sched: Schedule) -> None:
    status = await _run_scheduled_task(sched)
    async with session() as s:
        await s.execute(
            update(Schedule).where(Schedule.id == sched.id).values(last_run_status=status)
        )
        await s.commit()


async def schedule_tick_loop() -> None:
    logger.info("schedule_tick_loop started")
    while True:
        try:
            await _tick_once()
        except Exception:
            logger.exception("schedule_tick failed")
        await asyncio.sleep(60)
```

- [ ] **Step 2: Wire `schedule_tick_loop` into main.py lifespan**

In `mcp-servers/tasks/main.py`, find the existing `@app.on_event("startup")` for the idle sweep. Add a sibling startup hook:

```python
@app.on_event("startup")
async def _start_schedule_ticker():
    """Heartbeat scheduler — wakes once per minute, fires due schedules."""
    from scheduler import schedule_tick_loop
    asyncio.create_task(schedule_tick_loop())
```

- [ ] **Step 3: Update routes_execution `_run_execution` to accept `schedule_id`**

Read `mcp-servers/tasks/routes_execution.py` and find the `_run_execution` function. Add an optional `schedule_id: str | None = None` parameter. Thread it down to `executor.run(..., schedule_id=schedule_id)`.

In `remote_executor.py`'s `run()` and `_stream()`, add the same param. When `schedule_id` is set, the SCP roundtrip for `/agent/memory/<schedule-id>.md` runs (next task).

- [ ] **Step 4: Sanity-import**

Run: `cd mcp-servers/tasks && python -c "from scheduler import schedule_tick_loop, _tick_once; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/scheduler.py mcp-servers/tasks/main.py mcp-servers/tasks/routes_execution.py mcp-servers/tasks/remote_executor.py
git commit -m "feat(tasks): tick loop + DB integration + schedule_id plumbed through executor"
```

---

### Task 5: MEMORY.md roundtrip

**Files:**
- Modify: `mcp-servers/tasks/remote_executor.py`

- [ ] **Step 1: Add memory-fetch helper**

In `remote_executor.py`, add a method on `RemoteExecutor`:

```python
async def _fetch_memory(self, host: str, user: str, key: str, schedule_id: str, slug: str) -> None:
    """SCP /agent/memory/<schedule_id>.md → /agent/work/<slug>/MEMORY.md.
    Creates an empty file if no memory exists yet."""
    src = f"{user}@{host}:/agent/memory/{schedule_id}.md"
    dst_dir = f"/agent/work/{shlex.quote(slug)}"
    # Ensure memory dir exists, then copy. If source missing, init empty.
    cmd = (
        f"mkdir -p /agent/memory && touch /agent/memory/{shlex.quote(schedule_id)}.md && "
        f"cp /agent/memory/{shlex.quote(schedule_id)}.md {dst_dir}/MEMORY.md"
    )
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-i", key, *self._SSH_OPTS, f"{user}@{host}", cmd,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    rc = await proc.wait()
    if rc != 0:
        err = (await proc.stderr.read()).decode() if proc.stderr else ""
        raise RuntimeError(f"memory fetch exit {rc}: {err[:200]}")


async def _push_memory(self, host: str, user: str, key: str, schedule_id: str, slug: str) -> None:
    """SCP /agent/work/<slug>/MEMORY.md → /agent/memory/<schedule_id>.md atomically.
    Applies secret-scrub before writing."""
    # Pull MEMORY.md contents from agent, scrub locally, push back as .tmp then mv
    from secret_scrub import scrub
    cat_proc = await asyncio.create_subprocess_exec(
        "ssh", "-i", key, *self._SSH_OPTS, f"{user}@{host}",
        f"cat /agent/work/{shlex.quote(slug)}/MEMORY.md",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    raw, _ = await cat_proc.communicate()
    if cat_proc.returncode != 0:
        return  # No memory written — fine, skip
    scrubbed = scrub(raw.decode("utf-8", errors="replace"))
    # Truncate at 50 KB by dropping oldest "## " sections
    if len(scrubbed.encode()) > 50_000:
        scrubbed = _truncate_memory(scrubbed, 50_000)
    # Push back via ssh+stdin
    push_proc = await asyncio.create_subprocess_exec(
        "ssh", "-i", key, *self._SSH_OPTS, f"{user}@{host}",
        f"cat > /agent/memory/{shlex.quote(schedule_id)}.md.tmp && "
        f"mv /agent/memory/{shlex.quote(schedule_id)}.md.tmp /agent/memory/{shlex.quote(schedule_id)}.md",
        stdin=asyncio.subprocess.PIPE,
    )
    await push_proc.communicate(scrubbed.encode())
```

And the module-level helper:

```python
def _truncate_memory(text: str, max_bytes: int) -> str:
    """Drop oldest `## ` sections until under max_bytes. Always keep title (lines before first `## `)."""
    parts = text.split("\n## ", 1)
    if len(parts) == 1:
        return text[:max_bytes]
    head = parts[0]
    sections = ("## " + parts[1]).split("\n## ")
    while sum(len(s.encode()) for s in sections) + len(head.encode()) > max_bytes and len(sections) > 1:
        sections.pop(0)  # drop oldest
    return head + "\n" + "\n## ".join(s.removeprefix("## ") if i == 0 else s for i, s in enumerate(sections))
```

(Truncation logic is best-effort; we accept minor inaccuracy because the cap is soft.)

- [ ] **Step 2: Wire in to `run()`**

In `RemoteExecutor.run`, add an optional `schedule_id: str | None = None` parameter. After `_push_state` succeeds and before `_stream`, if `schedule_id`: `await self._fetch_memory(...)`. After the loop, on `completed` outcome before yielding, also `await self._push_memory(...)`.

- [ ] **Step 3: Add tests for truncation**

In `tests/test_remote_executor.py` (existing file), append:

```python
from remote_executor import _truncate_memory

def test_truncate_keeps_newest():
    head = "# Memory\n"
    section = "## 2026-05-{day:02d} entry\nbody{day}\n"
    big = head + "\n".join(section.format(day=d) for d in range(1, 30))
    out = _truncate_memory(big, 500)
    assert "# Memory" in out
    assert "day29" in out or "entry29" in out or "2026-05-29" in out
    assert len(out.encode()) <= 600  # some slack for the head
```

- [ ] **Step 4: Verify tests**

Run: `cd mcp-servers/tasks && pytest tests/test_remote_executor.py -v -k memory`
Expected: pass.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/remote_executor.py mcp-servers/tasks/tests/test_remote_executor.py
git commit -m "feat(tasks): MEMORY.md roundtrip with scrub + 50KB truncation"
```

---

### Task 6: Stream-level scrubbing in remote_executor

**Files:**
- Modify: `mcp-servers/tasks/remote_executor.py`

- [ ] **Step 1: Wrap `yield line` in `_stream` with scrub**

In `_stream`, find every `yield buf.decode(...)` and `yield <line>`. Wrap with `scrub()`:

```python
from secret_scrub import scrub
# ...
yield scrub(line.decode("utf-8", errors="replace"))
```

(Apply to both the chunked-read yield path and the final-buffer yield. Note: line_outcome() parsing must run on the SCRUBBED text, or alternatively unscrub for parser purposes — but since outcome sentinels are `COMPLETED:` / `FAILED:` etc. which never match a credential pattern, scrub-then-parse is safe.)

- [ ] **Step 2: Test scrubbing in stream**

Add test in `tests/test_remote_executor.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_stream_scrubs_credentials_in_output():
    fake_lines = [
        b"setting up...\n",
        b"DEBUG api_key=sk-ant-realkey12345abcdef_xyz_longer\n",
        b"COMPLETED: build done\n",
    ]
    # Mock the subprocess stdout
    # ... (full mock setup mirrors existing tests in this file)
```

(Use existing mock patterns from the file rather than re-deriving.)

- [ ] **Step 3: Verify**

Run: `pytest tests/test_remote_executor.py::test_stream_scrubs_credentials_in_output -v`
Expected: pass.

- [ ] **Step 4: Commit**

```
git add mcp-servers/tasks/remote_executor.py mcp-servers/tasks/tests/test_remote_executor.py
git commit -m "feat(tasks): scrub credentials in remote_executor stream"
```

---

### Task 7: routes_schedules — HTTP CRUD endpoints

**Files:**
- Create: `mcp-servers/tasks/routes_schedules.py`
- Create: `mcp-servers/tasks/tests/test_routes_schedules.py`
- Modify: `mcp-servers/tasks/main.py`

- [ ] **Step 1: Write failing tests**

`tests/test_routes_schedules.py`:

```python
import pytest, os
from fastapi.testclient import TestClient

CRON_SECRET = "test-secret"
os.environ["CRON_SHARED_SECRET"] = CRON_SECRET

def test_list_requires_secret():
    from main import app
    with TestClient(app) as c:
        r = c.get("/schedules")
        assert r.status_code == 403

def test_create_then_list():
    from main import app
    with TestClient(app) as c:
        r = c.post("/schedules",
                   headers={"X-Cron-Secret": CRON_SECRET},
                   json={
                       "user_email": "x@y.com", "name": "test-sched",
                       "cron_expr": "*/5 * * * *", "persona": "test", "prompt": "say hi",
                   })
        assert r.status_code == 201
        sched_id = r.json()["id"]

        r = c.get("/schedules", headers={"X-Cron-Secret": CRON_SECRET})
        assert r.status_code == 200
        assert any(s["id"] == sched_id for s in r.json())
```

- [ ] **Step 2: Implement**

```python
"""CRUD for tasks.schedules — protected by X-Cron-Secret header."""
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete

from db import session
from models import Schedule

router = APIRouter(prefix="/schedules")
CRON_SECRET = os.environ.get("CRON_SHARED_SECRET", "")


def _require_secret(x_cron_secret: str) -> None:
    if not CRON_SECRET or x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=403, detail="Bad or missing X-Cron-Secret")


class CreateScheduleIn(BaseModel):
    user_email: str
    name: str
    cron_expr: str
    tz: str = "Asia/Manila"
    persona: str = ""
    prompt: str = Field(min_length=1)
    enabled: bool = True


@router.get("")
async def list_schedules(x_cron_secret: str = Header(default="")) -> list[dict[str, Any]]:
    _require_secret(x_cron_secret)
    async with session() as s:
        rows = (await s.execute(select(Schedule))).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
async def create_schedule(body: CreateScheduleIn, x_cron_secret: str = Header(default="")) -> dict[str, Any]:
    _require_secret(x_cron_secret)
    # Validate cron expr
    from croniter import croniter
    if not croniter.is_valid(body.cron_expr):
        raise HTTPException(status_code=400, detail="invalid cron_expr")

    sid = uuid.uuid4()
    async with session() as s:
        s.add(Schedule(
            id=sid, user_email=body.user_email, name=body.name,
            cron_expr=body.cron_expr, tz=body.tz, persona=body.persona,
            prompt=body.prompt, enabled=body.enabled,
        ))
        await s.commit()
    return {"id": str(sid)}


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, x_cron_secret: str = Header(default="")) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(delete(Schedule).where(Schedule.id == uuid.UUID(schedule_id)))
        await s.commit()
    return {"status": "deleted"}


@router.post("/{schedule_id}/enable")
async def enable_schedule(schedule_id: str, x_cron_secret: str = Header(default="")) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=True))
        await s.commit()
    return {"status": "enabled"}


@router.post("/{schedule_id}/disable")
async def disable_schedule(schedule_id: str, x_cron_secret: str = Header(default="")) -> dict[str, str]:
    _require_secret(x_cron_secret)
    async with session() as s:
        await s.execute(update(Schedule).where(Schedule.id == uuid.UUID(schedule_id)).values(enabled=False))
        await s.commit()
    return {"status": "disabled"}


@router.post("/{schedule_id}/run-now")
async def run_now(schedule_id: str, x_cron_secret: str = Header(default="")) -> dict[str, str]:
    """Bypass cron and fire this schedule immediately."""
    _require_secret(x_cron_secret)
    async with session() as s:
        sched = (await s.execute(select(Schedule).where(Schedule.id == uuid.UUID(schedule_id)))).scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="not found")
    from scheduler import _finalize_run
    import asyncio
    asyncio.create_task(_finalize_run(sched))
    return {"status": "dispatched"}


def _serialize(sch: Schedule) -> dict[str, Any]:
    return {
        "id": str(sch.id), "user_email": sch.user_email, "name": sch.name,
        "cron_expr": sch.cron_expr, "tz": sch.tz, "persona": sch.persona,
        "prompt": sch.prompt, "enabled": sch.enabled,
        "last_run_at": sch.last_run_at.isoformat() if sch.last_run_at else None,
        "last_run_status": sch.last_run_status,
    }
```

- [ ] **Step 3: Register the router in main.py**

```python
from routes_schedules import router as schedules_router
app.include_router(schedules_router)
```

- [ ] **Step 4: Tests pass**

Run: `pytest tests/test_routes_schedules.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```
git add mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_routes_schedules.py mcp-servers/tasks/main.py
git commit -m "feat(tasks): routes_schedules CRUD + run-now endpoint"
```

---

### Task 8: CLI `scripts/manage_schedules.py`

**Files:**
- Create: `scripts/manage_schedules.py`

- [ ] **Step 1: Write the CLI**

```python
#!/usr/bin/env python3
"""Manage tasks.schedules via HTTP. Env: TASKS_URL (required), CRON_SHARED_SECRET (required)."""
import argparse, json, os, sys
import urllib.request
import urllib.error

URL = os.environ.get("TASKS_URL", "http://46.224.193.25/tasks")
SECRET = os.environ.get("CRON_SHARED_SECRET", "")

def _req(method: str, path: str, body: dict | None = None) -> dict | list:
    if not SECRET:
        sys.exit("CRON_SHARED_SECRET env var required")
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        URL + path, data=data, method=method,
        headers={"X-Cron-Secret": SECRET, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{e.code}: {e.read().decode()}")

def cmd_list(args):
    print(json.dumps(_req("GET", "/schedules"), indent=2))

def cmd_create(args):
    body = {
        "user_email": args.user, "name": args.name,
        "cron_expr": args.cron, "tz": args.tz,
        "persona": args.persona, "prompt": args.prompt,
        "enabled": not args.disabled,
    }
    print(json.dumps(_req("POST", "/schedules", body), indent=2))

def cmd_delete(args):  print(_req("DELETE", f"/schedules/{args.id}"))
def cmd_enable(args):  print(_req("POST",   f"/schedules/{args.id}/enable"))
def cmd_disable(args): print(_req("POST",   f"/schedules/{args.id}/disable"))
def cmd_run_now(args): print(_req("POST",   f"/schedules/{args.id}/run-now"))

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    c = sub.add_parser("create")
    c.add_argument("--user", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--cron", required=True, help="5-field cron expr, e.g. '0 20 * * *'")
    c.add_argument("--tz", default="Asia/Manila")
    c.add_argument("--persona", default="")
    c.add_argument("--prompt", required=True)
    c.add_argument("--disabled", action="store_true")
    c.set_defaults(func=cmd_create)
    for name, fn in [("delete", cmd_delete), ("enable", cmd_enable), ("disable", cmd_disable), ("run-now", cmd_run_now)]:
        s = sub.add_parser(name)
        s.add_argument("id")
        s.set_defaults(func=fn)
    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: chmod + smoke parse**

```
chmod +x scripts/manage_schedules.py
python3 scripts/manage_schedules.py --help
```

Expected: usage output.

- [ ] **Step 3: Commit**

```
git add scripts/manage_schedules.py
git commit -m "feat: scripts/manage_schedules.py CLI for schedule CRUD"
```

---

### Task 9: Deploy + live e2e

> The "no red marks remain" verification step.

- [ ] **Step 1: Local full test suite passes**

```
cd mcp-servers/tasks && pytest -v
```

Expected: all green. Note any pre-existing failures (not introduced by this work) — call them out separately.

- [ ] **Step 2: Deploy with the new script**

```
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

Expected: rebuilds `tasks` service, smoke passes, `.deploy-state` updated.

- [ ] **Step 3: Create a 1-minute-from-now schedule**

```
TASKS_URL=http://46.224.193.25/tasks CRON_SHARED_SECRET=<secret> \
  python3 scripts/manage_schedules.py create \
    --user alamajacintg04@gmail.com --name heartbeat-smoke \
    --cron "$(date -d '+1 min' +'%-M %-H * * *')" \
    --tz Asia/Manila \
    --persona "You are a test bot. Be terse." \
    --prompt "Write a single line to MEMORY.md saying 'ran-at-<current ISO timestamp>'. Output COMPLETED when done."
```

- [ ] **Step 4: Wait + verify**

```
sleep 90
TASKS_URL=... CRON_SHARED_SECRET=... python3 scripts/manage_schedules.py list | jq '.[] | select(.name=="heartbeat-smoke")'
```

Expected: `last_run_status == "completed"`, `last_run_at` ≈ now.

- [ ] **Step 5: Verify memory persisted on agent VM**

```
ssh claude-agent@<agent-vm> cat /agent/memory/<schedule-id>.md
```

Expected: contains the `ran-at-<ts>` line.

- [ ] **Step 6: Secret-scrub e2e check**

Update the schedule's prompt to include a fake key:
```
python3 scripts/manage_schedules.py run-now <id>
```
(with a new schedule whose prompt contains `sk-ant-faketestkey12345abcdef_xyz_payload`)

Wait, then:
```
ssh claude-agent@<agent-vm> cat /agent/memory/<schedule-id>.md
```
Expected: contains `<REDACTED_ANTHROPIC>`, NOT the raw key.

```
psql ... -c "SELECT log FROM tasks.executions WHERE ..." | grep -c sk-ant-
```
Expected: 0 (zero matches in stored execution logs).

- [ ] **Step 7: Clean up the smoke schedule**

```
python3 scripts/manage_schedules.py delete <id>
```

- [ ] **Step 8: Update memory file**

Edit `C:\Users\alama\.claude\projects\C--Users-alama-Desktop-Lukas-Work-IO\memory\project_open_claw_heartbeat.md`: mark v1 shipped with date 2026-05-18. List what's deferred to v2 (UI, NL→cron, etc.). Note the live smoke task ID.
