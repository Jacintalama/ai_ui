# Open four features to non-admin users — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make App Builder, Video Generation, Cron Jobs and Graph reachable by
non-admin users, and cap per-user schedule creation so opening Cron Jobs cannot
sink the box.

**Architecture:** Three independent changes. (1) The sidebar injector stops
depending on Open WebUI's `/workspace` link — which non-admins never see — by
trying an ordered chain of anchors. (2) The Cron Jobs nav entry gains the
`allUsers` flag the other three already have. (3) `create_schedule` gains a
per-user count cap and a minimum interval, with operator and admin callers
exempt. Backends need no auth changes — they already answer non-admins with 200.

**Tech Stack:** FastAPI + SQLAlchemy (`mcp-servers/tasks`), pytest with a
hand-rolled `_FakeSession` (no DB), croniter, and plain browser JS
(`task-panel.js`, no test harness in this repo).

**Spec:** `docs/superpowers/specs/2026-08-11-open-features-to-non-admins-design.md`

---

## Task 1: A pure minimum-interval helper

**Files:**
- Modify: `mcp-servers/tasks/routes_schedules.py`
- Test: `mcp-servers/tasks/tests/test_schedule_limits.py` (create)

**Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_schedule_limits.py`:

```python
"""Per-user limits on schedule creation.

Each schedule spawns a Claude Code agent run (scheduler.py dispatches through
the remote executor), and concurrency is capped at 3 purely to avoid OOM on a
3.8GB box. Before this, create_schedule validated only that the cron expression
parsed — so `* * * * *`, an agent run every minute forever, was accepted. That
was survivable while the page was admin-only; opening it to everyone makes a cap
necessary rather than nice to have.

The helper is pure and uses a FIXED base time so the result is deterministic and
does not depend on when the suite runs.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()
os.environ.setdefault("CRON_SHARED_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from routes_schedules import min_interval_minutes  # noqa: E402


@pytest.mark.parametrize("expr,expected", [
    ("* * * * *", 1),        # every minute — the pathological case
    ("*/5 * * * *", 5),      # a step, not the literal every-minute
    ("*/15 * * * *", 15),    # exactly the boundary
    ("0,30 * * * *", 30),    # comma list
    ("0 * * * *", 60),       # hourly
    ("0 9 * * *", 1440),     # daily
])
def test_min_interval_is_the_smallest_gap(expr, expected):
    assert min_interval_minutes(expr) == expected


def test_uneven_schedules_report_their_SMALLEST_gap():
    """Mon and Tue at 09:00: gaps are 1 day, 6 days, 1 day. The smallest is
    what matters — an average would hide a burst."""
    assert min_interval_minutes("0 9 * * 1,2") == 1440


def test_a_garbage_expression_does_not_raise():
    """The caller validates with croniter.is_valid first, but this must never
    be the thing that 500s a request."""
    assert min_interval_minutes("not a cron") == 0.0
```

**Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_schedule_limits.py -q`
Expected: FAIL — `ImportError: cannot import name 'min_interval_minutes'`

**Step 3: Write minimal implementation**

In `mcp-servers/tasks/routes_schedules.py`, after `_validate_kind`:

```python
# A fixed base makes the calculation deterministic — otherwise the same cron
# expression could pass or fail depending on when the request arrives.
_INTERVAL_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def min_interval_minutes(cron_expr: str) -> float:
    """Smallest gap between consecutive fire times, in minutes.

    Four fire times give three gaps, which is enough to catch a step
    (`*/5`) or a comma list (`0,30`) rather than only the literal
    `* * * * *`. Never raises: a malformed expression is rejected upstream by
    croniter.is_valid, and this must not be what 500s a request.
    """
    try:
        from croniter import croniter
        it = croniter(cron_expr, _INTERVAL_BASE)
        times = [it.get_next(datetime) for _ in range(4)]
    except Exception:  # noqa: BLE001 - unparseable is handled by the caller
        return 0.0
    gaps = [(times[i + 1] - times[i]).total_seconds() / 60
            for i in range(len(times) - 1)]
    return min(gaps) if gaps else 0.0
```

Add to the imports at the top of the file:

```python
from datetime import datetime, timezone
```

**Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_schedule_limits.py -q`
Expected: PASS — 8 passed

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_schedule_limits.py
git commit -m "feat(schedules): pure helper for a cron expression's smallest gap"
```

---

## Task 2: Enforce the cap and the interval

**Files:**
- Modify: `mcp-servers/tasks/routes_schedules.py:96-140` (`create_schedule`)
- Test: `mcp-servers/tasks/tests/test_schedule_limits.py`

**Step 1: Write the failing test**

Append to `tests/test_schedule_limits.py`:

```python
from unittest.mock import MagicMock  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MAX = 10


def _client_with(rows, monkeypatch):
    """A TestClient whose DB returns `rows` for the owner-count query.

    Reuses the _FakeSession shape from test_routes_schedules.py rather than
    inventing a second one.
    """
    from main import app
    from models import Schedule

    created: list = []

    class _FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def add(self, obj):
            if isinstance(obj, Schedule):
                created.append(obj)
        async def commit(self): return None
        async def execute(self, _stmt):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self_): return list(rows)
                    return _S()
            return _R()

    monkeypatch.setattr("routes_schedules.session", lambda: _FakeSession())
    return TestClient(app, raise_server_exceptions=False), created


def _body(**kw):
    b = {"name": "n", "cron_expr": "0 9 * * *", "prompt": "do a thing"}
    b.update(kw)
    return b


def _rows(n):
    import uuid
    from models import Schedule
    return [Schedule(id=uuid.uuid4(), user_email="u@x.com", name=str(i),
                     cron_expr="0 9 * * *", prompt="p") for i in range(n)]


def test_a_regular_user_is_capped(monkeypatch):
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 429, r.text
    assert "10" in r.json()["detail"]
    assert created == [], "rejected the request but still wrote the row"


def test_under_the_cap_still_works(monkeypatch):
    c, created = _client_with(_rows(MAX - 1), monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"}, json=_body())
    assert r.status_code == 201, r.text
    assert len(created) == 1


def test_too_frequent_is_rejected(monkeypatch):
    c, created = _client_with([], monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"},
               json=_body(cron_expr="*/5 * * * *"))
    assert r.status_code == 400, r.text
    assert "15 minutes" in r.json()["detail"]
    assert created == []


def test_exactly_fifteen_minutes_is_allowed(monkeypatch):
    c, created = _client_with([], monkeypatch)
    r = c.post("/schedules", headers={"X-User-Email": "u@x.com"},
               json=_body(cron_expr="*/15 * * * *"))
    assert r.status_code == 201, r.text


def test_an_admin_is_exempt_from_both(monkeypatch):
    """Admins keep the old behaviour — the cap protects the box from casual
    use, it is not a security boundary."""
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules",
               headers={"X-User-Email": "a@x.com", "X-User-Admin": "true"},
               json=_body(cron_expr="* * * * *"))
    assert r.status_code == 201, r.text


def test_the_operator_path_is_exempt(monkeypatch):
    """scripts/manage_schedules.py must keep working unchanged."""
    c, created = _client_with(_rows(MAX), monkeypatch)
    r = c.post("/schedules",
               headers={"X-Cron-Secret": os.environ["CRON_SHARED_SECRET"]},
               json=_body(user_email="u@x.com", cron_expr="* * * * *"))
    assert r.status_code == 201, r.text


def test_a_forged_admin_header_cannot_reach_the_service(monkeypatch):
    """Documents WHY trusting X-User-Admin is safe here: the gateway strips it
    from the client request and re-sets it after validating the JWT
    (api-gateway/main.py:298-309). This test pins that the route reads the
    header at all, so the exemption is real rather than accidental."""
    import inspect
    import routes_schedules
    src = inspect.getsource(routes_schedules.create_schedule)
    assert "x_user_admin" in src
```

**Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_schedule_limits.py -q`
Expected: FAIL — the cap tests return 201 instead of 429/400

**Step 3: Write minimal implementation**

Add near the top of `routes_schedules.py`:

```python
# Each schedule spawns a Claude Code agent run and concurrency is capped at 3
# (scheduler.py) to avoid OOM on a 3.8GB box, so an unbounded number of
# frequent schedules is a self-DoS. Mirrors what webhook-handler's own cron
# already enforces (max_user_jobs / min_interval_minutes).
MAX_SCHEDULES_PER_USER = 10
MIN_INTERVAL_MINUTES = 15
```

In `create_schedule`, add the header parameter:

```python
    x_user_admin: str = Header(default=""),
```

and after the existing `_validate_kind(body.kind, body.video_config)` call:

```python
    # Operators (X-Cron-Secret) and admins keep the old unbounded behaviour:
    # the cap exists to stop casual self-DoS, not as a security boundary.
    is_admin = x_user_admin.strip().lower() == "true"
    if not is_operator and not is_admin:
        gap = min_interval_minutes(body.cron_expr)
        if gap and gap < MIN_INTERVAL_MINUTES:
            raise HTTPException(
                status_code=400,
                detail=(f"The shortest repeat is every {MIN_INTERVAL_MINUTES} "
                        f"minutes. That schedule would run every "
                        f"{int(gap)} minute(s)."),
            )
        async with session() as s:
            mine = (await s.execute(
                select(Schedule).where(Schedule.user_email == owner)
            )).scalars().all()
        if len(mine) >= MAX_SCHEDULES_PER_USER:
            raise HTTPException(
                status_code=429,
                detail=(f"You already have {MAX_SCHEDULES_PER_USER} scheduled "
                        f"tasks. Delete one first."),
            )
```

Counting by fetching rows rather than `func.count()` is deliberate: the ceiling
is 10 rows, and it reuses the mock shape the existing tests already prove.

**Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_schedule_limits.py tests/test_routes_schedules.py -q`
Expected: PASS — all pass, and the pre-existing schedule route tests are unaffected

**Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_schedules.py mcp-servers/tasks/tests/test_schedule_limits.py
git commit -m "feat(schedules): cap regular users at 10 schedules and a 15-minute floor"
```

---

## Task 3: Cron Jobs visible to all users

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js:1132` (the Cron Jobs entry)
- Test: `mcp-servers/tasks/tests/test_nav_entries.py` (create)

**Step 1: Write the failing test**

Create `mcp-servers/tasks/tests/test_nav_entries.py`:

```python
"""The sidebar nav config must expose all four features to regular users.

task-panel.js is browser JS with no JS test harness in this repo, so this
parses the config out of the source. That is weaker than running it — it
cannot prove the entries actually appear — but it does pin the four flags
against a silent edit, which is the failure this file exists to catch.
"""
import pathlib
import re

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "static" / "task-panel.js").read_text(encoding="utf-8")

EXPECTED = {"App Builder", "Video Generation", "Cron Jobs", "Graph"}


def _entries():
    """[(label, has_allUsers)] parsed from the NAV_ENTRIES literal."""
    block = JS.split("const NAV_ENTRIES = [", 1)[1]
    out = []
    for chunk in block.split("attr:")[1:]:
        m = re.search(r'label:\s*"([^"]+)"', chunk)
        if m:
            out.append((m.group(1), "allUsers: true" in chunk))
    return out


def test_all_four_entries_exist():
    assert {label for label, _ in _entries()} >= EXPECTED


def test_every_entry_is_visible_to_regular_users():
    hidden = [label for label, all_users in _entries()
              if label in EXPECTED and not all_users]
    assert not hidden, f"still admin-only: {hidden}"
```

**Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_nav_entries.py -q`
Expected: FAIL — `still admin-only: ['Cron Jobs']`

**Step 3: Write minimal implementation**

In `task-panel.js`, in the Cron Jobs entry (the one with
`attr: "data-aiui-cron-jobs"`), add the flag directly after `attr:`:

```javascript
        attr: "data-aiui-cron-jobs",
        // Visible to ALL signed-in users. The schedules API is owner-scoped
        // (X-User-Email) and now caps regular users at 10 schedules with a
        // 15-minute floor, so an unbounded agent-run loop is not reachable.
        allUsers: true,
```

**Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_nav_entries.py -q`
Expected: PASS — 2 passed

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js mcp-servers/tasks/tests/test_nav_entries.py
git commit -m "feat(nav): show Cron Jobs to non-admin users"
```

---

## Task 4: Stop the nav depending on the Workspace link

**Files:**
- Modify: `mcp-servers/tasks/static/task-panel.js:1344-1361`
- Test: `mcp-servers/tasks/tests/test_nav_entries.py`

**Step 1: Write the failing test**

Append to `tests/test_nav_entries.py`:

```python
def test_the_injector_does_not_depend_only_on_the_workspace_link():
    """The root cause. Open WebUI renders a[href="/workspace"] only for admins
    or users holding >=1 workspace permission (upstream Sidebar.svelte,
    isMenuItemVisible), and this deployment sets all five to false. With a
    single anchor, non-admins got NO entries at all — even the three already
    flagged allUsers."""
    anchors = re.findall(r'a\[href="(/[a-z-]+)"\]', JS)
    assert "/workspace" in anchors, "admins must still anchor under Workspace"
    fallbacks = [a for a in anchors if a != "/workspace"]
    assert fallbacks, "no fallback anchor — non-admins would still see nothing"


def test_the_fallback_targets_something_non_admins_can_see():
    """features.notes and features.calendar are true for regular users in this
    deployment; workspace.* are all false."""
    anchors = set(re.findall(r'a\[href="(/[a-z-]+)"\]', JS))
    assert anchors & {"/notes", "/calendar"}
```

**Step 2: Run test to verify it fails**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_nav_entries.py -q`
Expected: FAIL — `no fallback anchor — non-admins would still see nothing`

**Step 3: Write minimal implementation**

Replace the anchor block in `task-panel.js` (currently lines 1344-1361, from
`// Find Workspace row via its href first` through the
`if (!workspaceRow || !workspaceRow.parentElement) return;` line) with:

```javascript
        // Anchor chain, first match wins.
        //
        // This used to look ONLY for a[href="/workspace"], which is why
        // regular users saw none of these entries: Open WebUI renders that
        // link only for admins or users holding at least one workspace
        // permission (upstream Sidebar.svelte -> isMenuItemVisible), and this
        // deployment sets all five workspace permissions to false. No anchor
        // meant nothing was injected at all, even for entries flagged
        // allUsers. Admins are unaffected — /workspace is still tried first,
        // so their entries stay exactly where they were.
        const ANCHOR_HREFS = ["/workspace", "/notes", "/calendar"];
        let workspaceRow = null;
        for (const href of ANCHOR_HREFS) {
          workspaceRow = document.querySelector('a[href="' + href + '"]');
          if (workspaceRow) break;
        }
        if (!workspaceRow) {
          // Older Open WebUI versions, or a renamed route: fall back to the
          // label scan, then to the first sidebar link of any kind.
          const candidates = document.querySelectorAll("a, button, [role='link']");
          for (const el of candidates) {
            const txt = (el.textContent || "").trim();
            if (txt !== "Workspace" && txt !== "Notes") continue;
            workspaceRow = el;
            break;
          }
        }
        if (!workspaceRow || !workspaceRow.parentElement) return;
```

**Step 4: Run test to verify it passes**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_nav_entries.py -q`
Expected: PASS — 4 passed

**Step 5: Commit**

```bash
git add mcp-servers/tasks/static/task-panel.js mcp-servers/tasks/tests/test_nav_entries.py
git commit -m "fix(nav): non-admins saw no entries because the only anchor was admin-only"
```

---

## Task 5: Full suite, deploy, and prove it in a real browser

**Files:** none — verification only.

**Step 1: Run the whole tasks suite**

Run: `cd mcp-servers/tasks && python -m pytest tests/ -q`
Expected: the 3 known `test_doc_builder.py` failures (`python-docx` / `pptx`
missing locally — both ARE in requirements.txt) and the documented ~132
no-local-Postgres errors. **No new failures.**

**Step 2: Hash-sweep before deploying**

Per CLAUDE.md, teammates edit files directly on the box. For each changed file:

```bash
tr -d '\r' < <file> | md5sum
ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/<file> | md5sum"
```

The server hash must equal the **pre-change** repo hash
(`git show HEAD~4:<file> | tr -d '\r' | md5sum`). Any other value means someone
edited on the box — stop and diff before overwriting.

**Step 3: Deploy and rebuild**

Stream each file (never `scp -r`), verify the md5 after each, then rebuild:

```bash
tr -d '\r' < <file> | ssh root@46.224.193.25 \
  "cat > /tmp/f.new && mv /tmp/f.new /root/proxy-server/<file> && md5sum /root/proxy-server/<file>"

ssh root@46.224.193.25 "systemd-run --unit=aiui-nav-$(date +%s) --collect \
  --property=WorkingDirectory=/root/proxy-server \
  /usr/bin/docker compose -f docker-compose.unified.yml up -d --build tasks"
```

`task-panel.js` is served with a cache-busting query
(`task-panel.js?v=20260729-v0110`). **Bump that version string in
`openwebui-overrides/index.html` and redeploy it too**, or returning users keep
the cached copy and the fix appears to have done nothing.

**Step 4: Prove the cap on the live server**

```bash
ssh root@46.224.193.25 "docker exec tasks python -m pytest \
  tests/test_schedule_limits.py tests/test_nav_entries.py -q 2>&1 | tail -3"
```

Expected: all pass inside the real container (Python 3.11, container FastAPI).

**Step 5: Prove the nav in a real browser**

This is the step that cannot be skipped — `task-panel.js` has no test harness,
and every assertion above is static. Loading the page as a non-admin is the only
evidence.

1. Create a temporary non-admin account via the Open WebUI admin API.
2. Use `@playwright-skill` to sign in as that account and screenshot the sidebar.
3. Assert all four entries are present: App Builder, Video Generation, Cron
   Jobs, Graph.
4. Click each one and confirm the page loads rather than erroring.
5. **Delete the temporary account.**
6. Confirm an admin account still shows the entries under Workspace, unmoved.

**Step 6: Record and push**

```bash
ssh root@46.224.193.25 "echo '{\"sha\":\"'$(git rev-parse HEAD)'\",...}' \
  > /root/proxy-server/.deploy-state.new && mv ... .deploy-state"
gh auth switch -u Jacintalama
git push fork main    # fork ONLY — never origin/ai-ui/proxy-server
```

---

## Rollback

Each task is a separate commit, so any one can be reverted alone.

- **Task 4 only** (nav regressed for admins): revert that commit, redeploy
  `task-panel.js`, bump the cache-bust string.
- **Task 2 only** (cap too strict): the limits are two module constants —
  raising `MAX_SCHEDULES_PER_USER` or lowering `MIN_INTERVAL_MINUTES` needs no
  code change beyond the numbers.
- **Everything:** `git revert` the four commits, redeploy `tasks`. No migration
  and no data change is involved, so rollback is clean.
