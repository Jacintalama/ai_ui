# Discord `/aiui cronjob` and `/aiui aiuibuilder` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two Discord subcommands under the existing `/aiui` slash command — `cronjob` (list/create/delete user-scoped cron schedules in the tasks service) and `aiuibuilder` (list/status of user's App Builder projects).

**Architecture:** webhook-handler receives signed Discord interaction → maps the Discord user ID to an email via env-var dictionary → calls `tasks:8210` directly over the Docker network with `X-User-Email` only (NO cron secret, so `_resolve_caller` stays on the end-user code path and `_scoped_schedule` enforces 404-on-other-user). No api-gateway hop. Two new non-admin endpoints in `routes_projects.py` (using a new `current_user` FastAPI dep) expose project list/status to the caller's own projects.

**Tech Stack:** Python 3.11+, FastAPI, httpx, PyNaCl (Ed25519), respx (test mocks), pytest, Docker Compose, Discord Interactions API v10.

**Spec:** `docs/superpowers/specs/2026-05-19-discord-cronjob-aiuibuilder-design.md`

---

## File map

**Create:**
- `webhook-handler/clients/tasks.py` — HTTP client for tasks service
- `webhook-handler/tests/__init__.py`
- `webhook-handler/tests/conftest.py` — shared pytest fixtures
- `webhook-handler/tests/test_config_discord_map.py`
- `webhook-handler/tests/test_tasks_client.py`
- `webhook-handler/tests/test_command_router.py`
- `webhook-handler/tests/test_cronjob_handler.py`
- `webhook-handler/tests/test_aiuibuilder_handler.py`
- `mcp-servers/tasks/tests/test_routes_projects_list.py`
- `scripts/register_discord_commands.py`
- `scripts/discord_e2e_local.sh`

**Modify:**
- `webhook-handler/config.py` — add `discord_user_email_map` parsed setting
- `webhook-handler/requirements.txt` — add `pytest`, `pytest-asyncio`, `respx`
- `webhook-handler/handlers/commands.py` — add `_handle_cronjob`, `_handle_aiuibuilder`, update `parse_command`, update `_handle_help`, accept optional injectables in `__init__`
- `mcp-servers/tasks/auth.py` — add `CurrentUser` + `current_user`
- `mcp-servers/tasks/routes_projects.py` — add `list_my_projects`, `get_my_project_status`, response models
- `docker-compose.unified.yml` — add `DISCORD_USER_EMAIL_MAP` to webhook-handler `environment:` block (line ~131)

---

### Task 1: Bootstrap pytest in webhook-handler

The webhook-handler service has no test directory yet. Bootstrap one so the rest of the plan has somewhere to land.

**Files:**
- Create: `webhook-handler/tests/__init__.py`
- Create: `webhook-handler/tests/conftest.py`
- Modify: `webhook-handler/requirements.txt`

- [ ] **Step 1: Add dev dependencies**

Append to `webhook-handler/requirements.txt`:

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
respx>=0.20.0
```

- [ ] **Step 2: Create empty package marker**

Write `webhook-handler/tests/__init__.py` with no content.

- [ ] **Step 3: Create conftest.py**

```python
"""Shared fixtures for webhook-handler tests.

Pattern matches mcp-servers/tasks/tests: stub env vars BEFORE the app
is imported anywhere in this test session.
"""
import os
import sys

# Stub required env vars before any test imports webhook-handler modules.
os.environ.setdefault("DISCORD_PUBLIC_KEY", "00" * 32)
os.environ.setdefault("DISCORD_APPLICATION_ID", "1")
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("TASKS_URL", "http://tasks-test:8210")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture
def discord_id_to_email():
    """The default Discord-ID → email map used in tests."""
    return {"100": "alice@example.com", "200": "bob@example.com"}
```

- [ ] **Step 4: Verify pytest runs (no tests collected is OK)**

Run from `webhook-handler/`:
```bash
pip install -r requirements.txt
pytest tests/ -v
```

Expected: "no tests ran in X.XXs" — collection succeeds, no failures.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/tests/ webhook-handler/requirements.txt
git commit -m "test(webhook-handler): bootstrap pytest scaffold with conftest"
```

---

### Task 2: Parse `DISCORD_USER_EMAIL_MAP` env var with validation

**Files:**
- Modify: `webhook-handler/config.py`
- Create: `webhook-handler/tests/test_config_discord_map.py`

- [ ] **Step 1: Write failing test for empty/unset map**

Create `webhook-handler/tests/test_config_discord_map.py`:

```python
"""DISCORD_USER_EMAIL_MAP parsing — env-var-driven Discord ID -> email lookup."""
from config import parse_discord_user_email_map


def test_unset_returns_empty():
    assert parse_discord_user_email_map("") == {}


def test_single_pair():
    result = parse_discord_user_email_map("100:alice@x.com")
    assert result == {"100": "alice@x.com"}


def test_multiple_pairs():
    result = parse_discord_user_email_map("100:alice@x.com,200:bob@y.com")
    assert result == {"100": "alice@x.com", "200": "bob@y.com"}


def test_email_lowercased():
    result = parse_discord_user_email_map("100:ALICE@X.COM")
    assert result["100"] == "alice@x.com"


def test_non_numeric_discord_id_dropped(caplog):
    result = parse_discord_user_email_map("not_a_snowflake:alice@x.com,200:bob@x.com")
    assert "not_a_snowflake" not in result
    assert result == {"200": "bob@x.com"}


def test_duplicate_email_warns(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        parse_discord_user_email_map("100:same@x.com,200:same@x.com")
    assert any("duplicate" in r.message.lower() for r in caplog.records)


def test_malformed_entry_dropped():
    result = parse_discord_user_email_map("100:alice@x.com,bad-no-colon,200:bob@x.com")
    assert result == {"100": "alice@x.com", "200": "bob@x.com"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest webhook-handler/tests/test_config_discord_map.py -v
```

Expected: ImportError or AttributeError — `parse_discord_user_email_map` not defined.

- [ ] **Step 3: Add `parse_discord_user_email_map` and `discord_user_email_map` setting**

Modify `webhook-handler/config.py`. After the existing `from typing import Optional` line, add:

```python
import logging

logger = logging.getLogger(__name__)


def parse_discord_user_email_map(raw: str) -> dict[str, str]:
    """Parse DISCORD_USER_EMAIL_MAP env var.

    Format: comma-separated `<snowflake_id>:<email>` pairs.
    Drops entries with non-numeric IDs or missing colons (logs at DEBUG).
    Lowercases emails. Warns on duplicate emails (silent cross-user risk).
    Returns the count via logger.info, never the contents.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    seen_emails: dict[str, str] = {}  # email -> first discord_id that claimed it
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            logger.debug("DISCORD_USER_EMAIL_MAP: skipping malformed entry")
            continue
        did, _, email = entry.partition(":")
        did = did.strip()
        email = email.strip().lower()
        if not did.isdigit():
            logger.debug("DISCORD_USER_EMAIL_MAP: non-numeric ID dropped")
            continue
        if not email:
            continue
        if email in seen_emails:
            logger.warning(
                "DISCORD_USER_EMAIL_MAP: duplicate email — two Discord IDs "
                "claim the same account (silent cross-user impersonation risk)"
            )
        seen_emails[email] = did
        out[did] = email
    logger.info(f"DISCORD_USER_EMAIL_MAP: loaded {len(out)} entries")
    return out
```

Pydantic v2 (which `pydantic-settings>=2.1.0` is) does NOT honour `class Config.fields`. Use a `Field(alias=...)` on the field instead. Add this import at the top of `config.py` if it's not already there:

```python
from pydantic import Field
```

In the `Settings` class, after `discord_alert_channel_id: str = ""`, add:

```python
    discord_user_email_map_raw: str = Field(default="", alias="DISCORD_USER_EMAIL_MAP")

    @property
    def discord_user_email_map(self) -> dict[str, str]:
        if not hasattr(self, "_discord_map_cache"):
            self._discord_map_cache = parse_discord_user_email_map(
                self.discord_user_email_map_raw
            )
        return self._discord_map_cache
```

Leave the existing `class Config: env_file = ".env"; case_sensitive = False` block untouched.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_config_discord_map.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/config.py webhook-handler/tests/test_config_discord_map.py
git commit -m "feat(webhook-handler): parse DISCORD_USER_EMAIL_MAP with validation"
```

---

### Task 3: Add `TASKS_URL` to settings + create `TasksClient`

**Files:**
- Modify: `webhook-handler/config.py`
- Create: `webhook-handler/clients/tasks.py`
- Create: `webhook-handler/tests/test_tasks_client.py`

- [ ] **Step 1: Write failing tests for TasksClient**

Create `webhook-handler/tests/test_tasks_client.py`:

```python
"""TasksClient — wraps tasks:8210 HTTP API for webhook-handler dispatchers."""
import pytest
import respx
from httpx import Response

from clients.tasks import TasksClient, TasksAPIError


BASE = "http://tasks-test:8210"


@pytest.fixture
def client():
    return TasksClient(base_url=BASE)


@pytest.mark.asyncio
async def test_list_schedules_sends_only_user_email(client):
    """Critical: TasksClient must NEVER send X-Cron-Secret. Sending both
    headers flips routes_schedules._resolve_caller to operator mode and
    list_schedules returns ALL users' schedules."""
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/schedules").mock(return_value=Response(200, json=[]))
        await client.list_schedules("alice@x.com")
        req = route.calls.last.request
        assert req.headers.get("x-user-email") == "alice@x.com"
        assert "x-cron-secret" not in {k.lower() for k in req.headers}


@pytest.mark.asyncio
async def test_list_schedules_returns_payload(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/schedules").mock(return_value=Response(200, json=[
            {"id": "s1", "name": "morning", "cron_expr": "0 8 * * *", "enabled": True},
        ]))
        result = await client.list_schedules("alice@x.com")
        assert len(result) == 1
        assert result[0]["id"] == "s1"


@pytest.mark.asyncio
async def test_create_schedule_201(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/schedules").mock(return_value=Response(201, json={"id": "new-id"}))
        result = await client.create_schedule(
            "alice@x.com", "test", "0 8 * * *", "summarize emails"
        )
        assert result["id"] == "new-id"


@pytest.mark.asyncio
async def test_create_schedule_400_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/schedules").mock(return_value=Response(400, json={"detail": "invalid cron_expr"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.create_schedule("alice@x.com", "test", "bad", "prompt")
        assert exc.value.status == 400
        assert "invalid cron_expr" in exc.value.message


@pytest.mark.asyncio
async def test_delete_schedule_404_raises(client):
    with respx.mock(base_url=BASE) as mock:
        mock.delete("/schedules/abc").mock(return_value=Response(404, json={"detail": "not found"}))
        with pytest.raises(TasksAPIError) as exc:
            await client.delete_schedule("alice@x.com", "abc")
        assert exc.value.status == 404


@pytest.mark.asyncio
async def test_connect_error_raises(client):
    with respx.mock(base_url=BASE) as mock:
        import httpx
        mock.get("/schedules").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(TasksAPIError) as exc:
            await client.list_schedules("alice@x.com")
        assert exc.value.status == 0  # network-level


@pytest.mark.asyncio
async def test_list_projects_endpoint(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/projects").mock(return_value=Response(200, json=[
            {"slug": "shopping-list", "name": "Shopping List", "role": "owner",
             "published": True, "public_url": "https://shopping-list.ai-ui.coolestdomain.win"}
        ]))
        result = await client.list_projects("alice@x.com")
        assert len(result) == 1
        assert result[0]["slug"] == "shopping-list"
```

Add `pytest-asyncio` mode to top of file or to a `pytest.ini`. Easier: prepend to the file:

```python
pytestmark = pytest.mark.asyncio
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest webhook-handler/tests/test_tasks_client.py -v
```

Expected: ImportError — `clients.tasks` doesn't exist.

- [ ] **Step 3: Add `tasks_url` to config**

In `webhook-handler/config.py`, after the existing `n8n_url` lines, add:

```python
    # Tasks service (user-scoped schedules + App Builder)
    tasks_url: str = "http://tasks:8210"
```

- [ ] **Step 4: Create `clients/tasks.py`**

```python
"""HTTP client for the tasks service (mcp-servers/tasks).

CRITICAL SECURITY: This client MUST send ONLY X-User-Email — never the
X-Cron-Secret header. The tasks routes_schedules._resolve_caller flips
to operator mode when the cron secret is present, after which list_schedules
returns all users' schedules. By withholding the secret we stay on the
end-user code path and per-row ownership is enforced server-side.
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TasksAPIError(Exception):
    """Raised when the tasks service returns a non-2xx or is unreachable.

    status = 0 means network-level failure (ConnectError, timeout).
    """
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"tasks API error {status}: {message}")


class TasksClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, user_email: str) -> dict[str, str]:
        # ONLY X-User-Email. Never X-Cron-Secret here.
        return {"X-User-Email": user_email}

    async def _request(
        self, method: str, path: str, user_email: str, **kwargs
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(user_email), **kwargs
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise TasksAPIError(0, f"tasks service unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise TasksAPIError(resp.status_code, str(detail))
        return resp

    async def list_schedules(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/schedules", user_email)
        return resp.json()

    async def create_schedule(
        self, user_email: str, name: str, cron: str, prompt: str,
        tz: str = "Asia/Manila",
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST", "/schedules", user_email,
            json={"name": name, "cron_expr": cron, "prompt": prompt, "tz": tz},
        )
        return resp.json()

    async def delete_schedule(self, user_email: str, schedule_id: str) -> bool:
        await self._request("DELETE", f"/schedules/{schedule_id}", user_email)
        return True

    async def list_projects(self, user_email: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/projects", user_email)
        return resp.json()

    async def get_project_status(
        self, user_email: str, slug: str,
    ) -> dict[str, Any]:
        resp = await self._request("GET", f"/api/projects/{slug}/status", user_email)
        return resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_tasks_client.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/clients/tasks.py webhook-handler/tests/test_tasks_client.py webhook-handler/config.py
git commit -m "feat(webhook-handler): add TasksClient sending only X-User-Email"
```

---

### Task 4: Extend `CommandRouter.parse_command` to recognise new subcommands

**Files:**
- Modify: `webhook-handler/handlers/commands.py:105-115`
- Create: `webhook-handler/tests/test_command_router.py`

- [ ] **Step 1: Write failing test**

Create `webhook-handler/tests/test_command_router.py`:

```python
"""parse_command must recognise cronjob and aiuibuilder as subcommands."""
from handlers.commands import CommandRouter


def test_cronjob_list():
    assert CommandRouter.parse_command("cronjob list") == ("cronjob", "list")


def test_cronjob_create_with_quoted_args():
    sub, args = CommandRouter.parse_command('cronjob create "0 8 * * *" "summarize emails"')
    assert sub == "cronjob"
    assert args == '''create "0 8 * * *" "summarize emails"'''


def test_aiuibuilder_list():
    assert CommandRouter.parse_command("aiuibuilder list") == ("aiuibuilder", "list")


def test_aiuibuilder_status_with_slug():
    assert CommandRouter.parse_command("aiuibuilder status my-app") == (
        "aiuibuilder", "status my-app"
    )


def test_unknown_still_falls_to_ask():
    """Existing behavior must not regress."""
    assert CommandRouter.parse_command("what is MCP")[0] == "ask"


def test_existing_status_subcommand_still_works():
    assert CommandRouter.parse_command("status")[0] == "status"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest webhook-handler/tests/test_command_router.py -v
```

Expected: tests for `cronjob` and `aiuibuilder` fail — they fall through to `("ask", ...)`.

- [ ] **Step 3: Add subcommands to `known_commands` set**

Edit `webhook-handler/handlers/commands.py` lines 105-110. Append two entries:

```python
        known_commands = {
            "ask", "workflow", "workflows", "status", "help",
            "report", "pr-review", "pr", "mcp", "diagnose", "analyze",
            "email", "sheets", "rebuild", "web-search",
            "health", "security", "deps", "license",
            "cronjob", "aiuibuilder",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_command_router.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_command_router.py
git commit -m "feat(webhook-handler): recognise cronjob and aiuibuilder subcommands"
```

---

### Task 5: Implement `_handle_cronjob` dispatcher

**Files:**
- Modify: `webhook-handler/handlers/commands.py`
- Create: `webhook-handler/tests/test_cronjob_handler.py`

- [ ] **Step 1: Write failing tests covering all paths**

Create `webhook-handler/tests/test_cronjob_handler.py`:

```python
"""_handle_cronjob — Discord-side dispatcher for /aiui cronjob.

Covers:
  - unmapped Discord user → friendly reject
  - empty/unknown action → usage hint
  - list with no schedules → "no schedules" message
  - list with schedules → formatted reply
  - create with missing args → usage hint
  - create with bad cron → propagates tasks 400
  - create success → reply with new id
  - delete 404 → "no such schedule"
  - tasks unreachable → "tasks service unreachable"
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured):
    """Build a CommandContext that captures the reply."""
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c",
        raw_text=f"cronjob {args}", subcommand="cronjob", arguments=args,
        platform="discord", respond=respond, metadata={},
    )


def _router(mapping, tasks_client):
    """Build a CommandRouter with mocked deps via the new ctor kwargs."""
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    router = _router({}, MagicMock())
    await router._handle_cronjob(_ctx("999", "list", captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_list_empty():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[])
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    assert any("no schedules" in m.lower() for m in captured)
    tc.list_schedules.assert_called_once_with("alice@x.com")


@pytest.mark.asyncio
async def test_list_with_schedules():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(return_value=[
        {"id": "s1", "name": "morning", "cron_expr": "0 8 * * *", "enabled": True},
        {"id": "s2", "name": "hourly", "cron_expr": "0 * * * *", "enabled": False},
    ])
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    reply = captured[-1]
    assert "s1" in reply and "morning" in reply
    assert "s2" in reply and "hourly" in reply


@pytest.mark.asyncio
async def test_create_missing_args_usage_hint():
    captured = []
    tc = MagicMock()
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "create", captured))
    assert any("Need" in m or "Usage" in m for m in captured)


@pytest.mark.asyncio
async def test_create_success():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(return_value={"id": "new-uuid"})
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", 'create "0 8 * * *" "summarize emails"', captured))
    tc.create_schedule.assert_called_once()
    args = tc.create_schedule.call_args
    assert args.args[0] == "alice@x.com"  # user_email
    # name, cron, prompt all forwarded
    assert "summarize" in str(args)


@pytest.mark.asyncio
async def test_create_invalid_cron_propagates():
    captured = []
    tc = MagicMock()
    tc.create_schedule = AsyncMock(side_effect=TasksAPIError(400, "invalid cron_expr"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", 'create "bad" "prompt"', captured))
    assert any("Invalid cron" in m for m in captured)


@pytest.mark.asyncio
async def test_delete_404():
    captured = []
    tc = MagicMock()
    tc.delete_schedule = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "delete missing-id", captured))
    assert any("No such schedule" in m for m in captured)


@pytest.mark.asyncio
async def test_tasks_unreachable():
    captured = []
    tc = MagicMock()
    tc.list_schedules = AsyncMock(side_effect=TasksAPIError(0, "refused"))
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "list", captured))
    assert any("unreachable" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_unknown_action_usage():
    captured = []
    tc = MagicMock()
    router = _router({"100": "alice@x.com"}, tc)
    await router._handle_cronjob(_ctx("100", "frobnicate", captured))
    assert any("Usage" in m for m in captured)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest webhook-handler/tests/test_cronjob_handler.py -v
```

Expected: AttributeError — `_handle_cronjob` not defined.

- [ ] **Step 3: Implement `_handle_cronjob`**

In `webhook-handler/handlers/commands.py`, near the top add:

```python
import shlex
from clients.tasks import TasksClient, TasksAPIError
```

Update the `CommandRouter.__init__` signature to accept the two new collaborators as injectable kwargs with sensible production defaults. This avoids the construct-then-overwrite pattern in tests:

```python
    def __init__(
        self,
        openwebui_client: OpenWebUIClient,
        n8n_client: N8NClient,
        ai_model: str = "gpt-4-turbo",
        slack_client=None,
        github_client: Optional[GitHubClient] = None,
        mcp_client: Optional[MCPProxyClient] = None,
        loki_client=None,
        discord_user_email_map: Optional[dict[str, str]] = None,
        tasks_client: Optional[TasksClient] = None,
    ):
        # ... existing assignments ...
        # New collaborators — read from settings only when not injected.
        if discord_user_email_map is None or tasks_client is None:
            from config import settings
            self._discord_user_email_map = (
                dict(discord_user_email_map)
                if discord_user_email_map is not None
                else dict(settings.discord_user_email_map)
            )
            self._tasks_client = tasks_client or TasksClient(base_url=settings.tasks_url)
        else:
            self._discord_user_email_map = dict(discord_user_email_map)
            self._tasks_client = tasks_client
```

Tests then pass `discord_user_email_map={"100": "alice@x.com"}` and `tasks_client=MagicMock(...)` directly — no fragile attribute-override.

Add the dispatcher method on `CommandRouter`:

```python
    async def _handle_cronjob(self, ctx: CommandContext) -> None:
        """Discord → user-scoped cron schedule CRUD via tasks service."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond(
                "Your Discord account isn't linked. Ask Lukas to add you."
            )
            return

        try:
            tokens = shlex.split(ctx.arguments) if ctx.arguments else []
        except ValueError:
            await ctx.respond(
                'Couldn\'t parse args. Wrap cron and prompt in double quotes: '
                '`/aiui cronjob create "0 8 * * *" "summarize emails"`'
            )
            return

        action = tokens[0] if tokens else ""
        rest = tokens[1:]

        try:
            if action == "list":
                schedules = await self._tasks_client.list_schedules(email)
                if not schedules:
                    await ctx.respond("**Your schedules**\nno schedules yet. Create one with `/aiui cronjob create \"<cron>\" \"<prompt>\"`.")
                    return
                lines = ["**Your schedules**"]
                for s in schedules:
                    state = "on" if s.get("enabled") else "off"
                    lines.append(
                        f"`{s['id']}` `{s['cron_expr']}` — {s['name']} [{state}]"
                    )
                reply = "\n".join(lines)
                if len(reply) > 1990:
                    reply = reply[:1980] + "\n... +more"
                await ctx.respond(reply)

            elif action == "create":
                if len(rest) < 2:
                    await ctx.respond(
                        'Need 2 args: `create "<cron>" "<prompt>"`. '
                        'Example: `/aiui cronjob create "0 8 * * *" "summarize unread emails"`'
                    )
                    return
                cron_expr = rest[0]
                prompt = " ".join(rest[1:])
                name = f"discord-{ctx.user_name}-{cron_expr[:20]}"
                result = await self._tasks_client.create_schedule(
                    email, name=name, cron=cron_expr, prompt=prompt,
                )
                await ctx.respond(
                    f"Schedule created: `{result['id']}`\n"
                    f"`{cron_expr}` — {prompt[:200]}"
                )

            elif action == "delete":
                if not rest:
                    await ctx.respond("Need a schedule id: `delete <id>`")
                    return
                schedule_id = rest[0]
                await self._tasks_client.delete_schedule(email, schedule_id)
                await ctx.respond(f"Deleted `{schedule_id}`.")

            else:
                await ctx.respond(
                    "Usage: `/aiui cronjob <list|create|delete>`"
                )

        except TasksAPIError as e:
            await ctx.respond(self._format_tasks_error(e))

    def _format_tasks_error(self, e: TasksAPIError) -> str:
        """Map a TasksAPIError to a Discord-friendly reply.

        Never echoes the request body, secrets, or other users' identifiers.
        """
        if e.status == 0:
            return "Tasks service unreachable, try again."
        if e.status == 404:
            return f"No such schedule: not found"
        if e.status == 400:
            msg = e.message
            if "cron_expr" in msg:
                return f"Invalid cron: {msg}"
            if "interval" in msg.lower():
                return "Min interval is 5 min."
            if "max" in msg.lower() or "quota" in msg.lower():
                return f"You hit the max schedules limit."
            return f"Bad request: {msg[:200]}"
        if e.status == 401 or e.status == 403:
            return "Permission denied by tasks service."
        return f"Tasks API error ({e.status})."
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_cronjob_handler.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_cronjob_handler.py
git commit -m "feat(webhook-handler): _handle_cronjob — list/create/delete via tasks"
```

---

### Task 6: Implement `_handle_aiuibuilder` dispatcher

**Files:**
- Modify: `webhook-handler/handlers/commands.py`
- Create: `webhook-handler/tests/test_aiuibuilder_handler.py`

- [ ] **Step 1: Write failing tests**

Create `webhook-handler/tests/test_aiuibuilder_handler.py`:

```python
"""_handle_aiuibuilder — Discord-side dispatcher for /aiui aiuibuilder."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, args, captured):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="tester", channel_id="c",
        raw_text=f"aiuibuilder {args}", subcommand="aiuibuilder", arguments=args,
        platform="discord", respond=respond, metadata={},
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping,
        tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock())._handle_aiuibuilder(_ctx("999", "list", captured))
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_list_empty():
    captured = []
    tc = MagicMock()
    tc.list_projects = AsyncMock(return_value=[])
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    assert any("no projects" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_list_with_projects():
    captured = []
    tc = MagicMock()
    tc.list_projects = AsyncMock(return_value=[
        {"slug": "shopping", "name": "Shopping List", "role": "owner",
         "published": True, "public_url": "https://shopping.ai-ui.coolestdomain.win"},
        {"slug": "todo", "name": "Todo", "role": "editor",
         "published": False, "public_url": None},
    ])
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "list", captured))
    reply = captured[-1]
    assert "shopping" in reply and "todo" in reply
    assert "https://shopping.ai-ui.coolestdomain.win" in reply


@pytest.mark.asyncio
async def test_status_needs_slug():
    captured = []
    await _router({"100": "alice@x.com"}, MagicMock())._handle_aiuibuilder(_ctx("100", "status", captured))
    assert any("Usage" in m or "slug" in m for m in captured)


@pytest.mark.asyncio
async def test_status_404():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(side_effect=TasksAPIError(404, "not found"))
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "status missing", captured))
    assert any("not found" in m.lower() or "yours" in m.lower() for m in captured)


@pytest.mark.asyncio
async def test_open_returns_url():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "slug": "shopping", "name": "Shopping", "role": "owner",
        "published": True,
        "public_url": "https://shopping.ai-ui.coolestdomain.win",
    })
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "open shopping", captured))
    assert any("https://shopping.ai-ui.coolestdomain.win" in m for m in captured)


@pytest.mark.asyncio
async def test_open_not_published():
    captured = []
    tc = MagicMock()
    tc.get_project_status = AsyncMock(return_value={
        "slug": "shopping", "name": "Shopping", "role": "owner",
        "published": False, "public_url": None,
    })
    await _router({"100": "alice@x.com"}, tc)._handle_aiuibuilder(_ctx("100", "open shopping", captured))
    assert any("not published" in m.lower() for m in captured)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest webhook-handler/tests/test_aiuibuilder_handler.py -v
```

Expected: AttributeError — `_handle_aiuibuilder` not defined.

- [ ] **Step 3: Implement `_handle_aiuibuilder`**

`shlex` and `TasksAPIError` are already imported at module top from Task 5 — do not re-import. Add the method on `CommandRouter`:

```python
    async def _handle_aiuibuilder(self, ctx: CommandContext) -> None:
        """Discord → App Builder project list / status / open URL."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond(
                "Your Discord account isn't linked. Ask Lukas to add you."
            )
            return

        try:
            tokens = shlex.split(ctx.arguments) if ctx.arguments else []
        except ValueError:
            await ctx.respond("Couldn't parse args. Try `aiuibuilder list`.")
            return

        action = tokens[0] if tokens else ""
        rest = tokens[1:]

        try:
            if action == "list":
                projects = await self._tasks_client.list_projects(email)
                if not projects:
                    await ctx.respond("**Your apps**\nno projects yet.")
                    return
                lines = ["**Your apps**"]
                for p in projects:
                    pub = p.get("public_url") or "(not published)"
                    lines.append(f"`{p['slug']}` — {p['name']} [{p['role']}] {pub}")
                reply = "\n".join(lines)
                if len(reply) > 1990:
                    reply = reply[:1980] + "\n... +more"
                await ctx.respond(reply)

            elif action == "status":
                if not rest:
                    await ctx.respond("Usage: `aiuibuilder status <slug>`")
                    return
                slug = rest[0]
                status = await self._tasks_client.get_project_status(email, slug)
                lines = [
                    f"**{status['name']}** (`{status['slug']}`)",
                    f"Role: {status['role']}",
                    f"Published: {'yes' if status.get('published') else 'no'}",
                ]
                if status.get("public_url"):
                    lines.append(f"URL: {status['public_url']}")
                if status.get("last_commit_at"):
                    lines.append(f"Last commit: {status['last_commit_at']}")
                await ctx.respond("\n".join(lines))

            elif action == "open":
                if not rest:
                    await ctx.respond("Usage: `aiuibuilder open <slug>`")
                    return
                slug = rest[0]
                status = await self._tasks_client.get_project_status(email, slug)
                if not status.get("published"):
                    await ctx.respond(
                        f"`{slug}` is not published yet. Publish it from the App Builder UI first."
                    )
                    return
                await ctx.respond(f"`{slug}` → {status['public_url']}")

            else:
                await ctx.respond("Usage: `/aiui aiuibuilder <list|status|open> [slug]`")

        except TasksAPIError as e:
            if e.status == 404:
                await ctx.respond("Project not found or not yours.")
            elif e.status == 0:
                await ctx.respond("Tasks service unreachable, try again.")
            else:
                await ctx.respond(f"Tasks API error ({e.status}).")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_aiuibuilder_handler.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_aiuibuilder_handler.py
git commit -m "feat(webhook-handler): _handle_aiuibuilder — list/status/open"
```

---

### Task 7: Wire dispatchers into `CommandRouter.execute` + update help text

**Files:**
- Modify: `webhook-handler/handlers/commands.py:117-155` (execute method) and `:338-360` (_handle_help)

- [ ] **Step 1: Write integration test that `execute()` routes new subcommands**

Append to `webhook-handler/tests/test_command_router.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter, CommandContext


def _bare_router():
    return CommandRouter(
        openwebui_client=MagicMock(),
        n8n_client=MagicMock(api_key=""),
        discord_user_email_map={},
        tasks_client=MagicMock(),
    )


@pytest.mark.asyncio
async def test_execute_routes_cronjob():
    """CommandRouter.execute must call _handle_cronjob, not fall to ask."""
    r = _bare_router()
    r._handle_cronjob = AsyncMock()
    async def respond(_): pass
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="cronjob list",
        subcommand="cronjob", arguments="list", platform="discord",
        respond=respond, metadata={},
    )
    await r.execute(ctx)
    r._handle_cronjob.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_execute_routes_aiuibuilder():
    r = _bare_router()
    r._handle_aiuibuilder = AsyncMock()
    async def respond(_): pass
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="aiuibuilder list",
        subcommand="aiuibuilder", arguments="list", platform="discord",
        respond=respond, metadata={},
    )
    await r.execute(ctx)
    r._handle_aiuibuilder.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_help_lists_new_commands():
    """Help text must advertise the two new subcommands.

    NOTE: must be `async def` + pytest.mark.asyncio. `asyncio.get_event_loop()`
    raises a hard RuntimeError on Python 3.12 and is deprecated on 3.11.
    """
    r = _bare_router()
    captured = []
    async def respond(m): captured.append(m)
    ctx = CommandContext(
        user_id="100", user_name="t", channel_id="c", raw_text="help",
        subcommand="help", arguments="", platform="discord",
        respond=respond, metadata={},
    )
    await r._handle_help(ctx)
    text = captured[0]
    assert "cronjob" in text
    assert "aiuibuilder" in text
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest webhook-handler/tests/test_command_router.py -v
```

Expected: the two `execute_routes_*` tests fail (no branch for cronjob/aiuibuilder), `help_lists_new_commands` fails.

- [ ] **Step 3: Add branches to `execute()`**

In `webhook-handler/handlers/commands.py` around line 117 (`execute` method), insert before the final `else:`:

```python
            elif ctx.subcommand == "cronjob":
                await self._handle_cronjob(ctx)
            elif ctx.subcommand == "aiuibuilder":
                await self._handle_aiuibuilder(ctx)
```

- [ ] **Step 4: Update `_handle_help` text**

In `_handle_help`, append two lines to the `help_text` string:

```
            "`/aiui cronjob <list|create|delete>` — Manage scheduled prompts\n"
            "`/aiui aiuibuilder <list|status|open>` — Manage your App Builder projects\n"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest webhook-handler/tests/test_command_router.py -v
```

Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_command_router.py
git commit -m "feat(webhook-handler): route cronjob/aiuibuilder + help text"
```

---

### Task 8: Add `current_user` dep in tasks/auth.py

**Files:**
- Modify: `mcp-servers/tasks/auth.py`
- Create: `mcp-servers/tasks/tests/test_auth_current_user.py`

- [ ] **Step 1: Write failing test**

Create `mcp-servers/tasks/tests/test_auth_current_user.py`:

```python
"""current_user — non-admin sibling of current_admin.

Used by list-my-* endpoints in routes_projects so non-admin Discord
users can fetch their own project list.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import Depends


def test_current_user_returns_email():
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    r = client.get("/whoami", headers={"X-User-Email": "ALICE@X.COM"})
    assert r.status_code == 200
    assert r.json() == {"email": "alice@x.com"}


def test_current_user_no_admin_required():
    """Crucially, current_user must NOT require X-User-Admin=true."""
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    # No X-User-Admin header — must still succeed.
    r = client.get("/whoami", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200


def test_current_user_missing_email_401():
    from auth import current_user, CurrentUser
    app = FastAPI()

    @app.get("/whoami")
    def whoami(u: CurrentUser = Depends(current_user)):
        return {"email": u.email}

    client = TestClient(app)
    r = client.get("/whoami")
    assert r.status_code == 401
```

- [ ] **Step 2: Run to verify failure**

```bash
cd mcp-servers/tasks && pytest tests/test_auth_current_user.py -v
```

Expected: ImportError — `current_user` / `CurrentUser` not in auth.

- [ ] **Step 3: Add `CurrentUser` + `current_user` to auth.py**

Append to `mcp-servers/tasks/auth.py`:

```python
@dataclass(frozen=True)
class CurrentUser:
    email: str


def current_user(request: Request) -> CurrentUser:
    """FastAPI dep — like current_admin but no admin gate.

    Used by list-my-* endpoints that any authenticated user should reach.
    Email is lowercased to match the canonical form used in DB rows.
    """
    email = request.headers.get("x-user-email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    return CurrentUser(email=email)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_auth_current_user.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/auth.py mcp-servers/tasks/tests/test_auth_current_user.py
git commit -m "feat(tasks): add current_user dep for non-admin list-my-* endpoints"
```

---

### Task 9: Add `GET /api/projects` + `GET /api/projects/{slug}/status`

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py`
- Create: `mcp-servers/tasks/tests/test_routes_projects_list.py`

- [ ] **Step 1: Confirm reusable primitives exist**

Open `mcp-servers/tasks/routes_projects.py` and confirm these symbols exist and their signatures:

- `_user_can_see_project(s, slug, email) -> bool` — used in the per-slug status endpoint
- `_public_url_for(slug) -> str` — formats the slug into a public URL
- `_run_git(*args, cwd) -> tuple[int, str]` — used in version listing; reuse for `last_commit`

Also confirm `mcp-servers/tasks/models.py` exports `ProjectMember` (with columns `slug`, `user_email`, `role`) and `PublishedApp` (with `published`, `custom_domain`, `slug`). The list endpoint uses these directly via SQLAlchemy — DO NOT filesystem-scan `apps/` (that's an N+1 trap when a user owns 3 projects out of hundreds).

- [ ] **Step 2: Write failing tests**

Create `mcp-servers/tasks/tests/test_routes_projects_list.py`:

```python
"""GET /api/projects + GET /api/projects/{slug}/status — caller-scoped views."""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


def test_list_my_projects_requires_email():
    from main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects")
    assert r.status_code == 401


def test_list_my_projects_no_admin_required(monkeypatch):
    """Caller has only X-User-Email, no X-User-Admin — must still return 200."""
    from main import app
    import routes_projects

    async def fake_list(email):
        return [{"slug": "test", "name": "Test", "role": "viewer",
                 "published": False, "public_url": None}]
    monkeypatch.setattr(routes_projects, "_list_projects_for_email", fake_list, raising=False)

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects", headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert body[0]["slug"] == "test"


def test_status_404_for_other_users_project(monkeypatch):
    """Ownership leak prevention: cross-user status returns 404, not 403."""
    from main import app
    import routes_projects

    async def fake_can_see(s, slug, email):
        return False
    monkeypatch.setattr(routes_projects, "_user_can_see_project", fake_can_see)

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/projects/someone-elses-app/status",
                   headers={"X-User-Email": "alice@x.com"})
    assert r.status_code == 404
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest mcp-servers/tasks/tests/test_routes_projects_list.py -v
```

Expected: most fail (endpoints don't exist).

- [ ] **Step 4: Add response models + endpoints in routes_projects.py**

Near the existing pydantic models in `routes_projects.py`, add:

```python
class ProjectSummary(BaseModel):
    slug: str
    name: str
    role: str
    published: bool
    public_url: str | None = None


class ProjectStatus(ProjectSummary):
    last_commit_at: str | None = None
    last_commit_message: str | None = None
    custom_domain: str | None = None
```

Update the imports at the top:

```python
from auth import AdminUser, current_admin, CurrentUser, current_user
```

Add the helper using a single SQL query (no filesystem scan):

```python
async def _list_projects_for_email(email: str) -> list[dict]:
    """All projects where this user is a member, with publish state.

    Single query against ProjectMember + LEFT JOIN PublishedApp. Returns
    dicts in ProjectSummary shape. Does NOT scan the apps/ directory —
    project membership lives in the DB, the directory is just storage.
    """
    async with session() as s:
        # 1. All memberships for this email.
        member_rows = (await s.execute(
            select(ProjectMember.slug, ProjectMember.role)
            .where(ProjectMember.user_email == email)
        )).all()
        if not member_rows:
            return []
        slugs = [r.slug for r in member_rows]
        role_by_slug = {r.slug: r.role for r in member_rows}

        # 2. Publish state for those slugs in one query.
        pub_rows = (await s.execute(
            select(PublishedApp).where(PublishedApp.slug.in_(slugs))
        )).scalars().all()
        pub_by_slug = {p.slug: p for p in pub_rows}

    out: list[dict] = []
    for slug in slugs:
        pub = pub_by_slug.get(slug)
        published = bool(pub and pub.published)
        out.append({
            "slug": slug,
            "name": slug.replace("-", " ").title(),
            "role": role_by_slug[slug],
            "published": published,
            "public_url": _public_url_for(slug) if published else None,
        })
    return out


async def _last_commit_for(slug: str) -> tuple[str | None, str | None]:
    """Read last commit (ISO timestamp + subject) from the project's git repo.

    Reuses _run_git for consistency with existing version-list code.
    Returns (None, None) if the repo doesn't exist or git fails.
    """
    import os
    apps_dir = os.path.join(REPO_ROOT, slug)
    if not os.path.isdir(os.path.join(apps_dir, ".git")):
        return None, None
    rc, out = await _run_git("log", "-1", "--format=%cI%n%s", cwd=apps_dir)
    if rc != 0:
        return None, None
    parts = out.strip().split("\n", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0] if parts else None, None
```

Add the endpoints. CRITICAL: FastAPI matches routes in declaration order, and the existing per-slug routes like `@router.get("/{slug}/members")` will swallow `/` and `/{slug}/status` if declared first. Insert the new routes **immediately after the `router = APIRouter(...)` line** and **before any `/{slug}/...` route**:

```python
@router.get("", response_model=list[ProjectSummary])
async def list_my_projects(user: CurrentUser = Depends(current_user)) -> list[ProjectSummary]:
    """List projects where the caller is a member."""
    raw = await _list_projects_for_email(user.email)
    return [ProjectSummary(**r) for r in raw]


@router.get("/{slug}/status", response_model=ProjectStatus)
async def get_my_project_status(
    slug: str, user: CurrentUser = Depends(current_user),
) -> ProjectStatus:
    """Membership + publish status for one project, scoped to caller."""
    async with session() as s:
        if not await _user_can_see_project(s, slug, user.email):
            # 404 (not 403) so cross-user existence isn't leaked.
            raise HTTPException(status_code=404, detail="not found")
        # Inline the role + publish queries — both small.
        member = (await s.execute(
            select(ProjectMember)
            .where(ProjectMember.slug == slug, ProjectMember.user_email == user.email)
        )).scalar_one_or_none()
        role = member.role if member else "viewer"
        pub = (await s.execute(
            select(PublishedApp).where(PublishedApp.slug == slug)
        )).scalar_one_or_none()
    last_commit_at, last_commit_msg = await _last_commit_for(slug)
    published = bool(pub and pub.published)
    return ProjectStatus(
        slug=slug,
        name=slug.replace("-", " ").title(),
        role=role,
        published=published,
        public_url=_public_url_for(slug) if published else None,
        last_commit_at=last_commit_at,
        last_commit_message=last_commit_msg,
        custom_domain=getattr(pub, "custom_domain", None) if pub else None,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest mcp-servers/tasks/tests/test_routes_projects_list.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Verify existing tests still pass**

```bash
pytest mcp-servers/tasks/tests/ -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py mcp-servers/tasks/tests/test_routes_projects_list.py
git commit -m "feat(tasks): GET /api/projects + /{slug}/status for caller-scoped views"
```

---

### Task 10: Build `register_discord_commands.py`

**Files:**
- Create: `scripts/register_discord_commands.py`

- [ ] **Step 1: Write the script**

```python
"""Idempotently register the full /aiui subcommand tree with Discord.

Discord's PUT /applications/{app_id}/commands REPLACES all commands —
partial updates are not supported. This script re-PUTs all 19 subcommands
every run.

Usage:
    DISCORD_APPLICATION_ID=... DISCORD_BOT_TOKEN=... python scripts/register_discord_commands.py

If DISCORD_GUILD_ID is set, registers as a guild-scoped command (instant
update, for testing). Otherwise registers globally (up to 1 hour propagation).
"""
import os
import sys

import httpx


# Discord option types
SUB_COMMAND = 1
STRING = 3

# All 19 /aiui subcommands. Each is one Discord SUB_COMMAND.
SUBCOMMANDS = [
    ("ask",         "Ask the AI a question",                     [("question",  "What to ask",            True)]),
    ("pr-review",   "AI review of a GitHub PR",                  [("number",    "PR number",              True)]),
    ("mcp",         "Execute an MCP tool",                       [("args",      "server tool [json]",    True)]),
    ("workflow",    "Trigger an n8n workflow",                   [("name",      "Workflow name",          True)]),
    ("workflows",   "List active n8n workflows",                 []),
    ("report",      "End-of-day activity report",                []),
    ("status",      "Service health check",                      []),
    ("help",        "Show available commands",                   []),
    ("diagnose",    "AI diagnosis of recent errors",             [("container", "Container name (opt)",  False)]),
    ("analyze",     "AI analysis of a GitHub repo",              [("repo",      "owner/repo",             False)]),
    ("rebuild",     "Research + rebuild plan for repo",          [("repo",      "owner/repo",             False)]),
    ("email",       "Summarize recent emails",                   []),
    ("sheets",      "Generate report to Google Sheets",          [("type",      "daily or errors",        False)]),
    ("web-search",  "Search web + save to KB",                   [("query",     "Search query",           True)]),
    ("health",      "Code health assessment",                    [("repo",      "owner/repo",             False)]),
    ("security",    "Security audit",                            [("repo",      "owner/repo",             False)]),
    ("deps",        "Dependency report",                         [("repo",      "owner/repo",             False)]),
    ("license",     "License compliance",                        [("repo",      "owner/repo",             False)]),
    ("cronjob",     "Manage scheduled prompts",                  [("args",      'e.g. list | create "0 8 * * *" "summarize emails" | delete <id>', True)]),
    ("aiuibuilder", "Manage App Builder projects",               [("args",      "e.g. list | status <slug> | open <slug>", True)]),
]


def build_command_payload() -> dict:
    return {
        "name": "aiui",
        "description": "AIUI assistant commands",
        "options": [
            {
                "name": name,
                "description": desc,
                "type": SUB_COMMAND,
                "options": [
                    {"name": opt_name, "description": opt_desc, "type": STRING, "required": req}
                    for opt_name, opt_desc, req in opts
                ],
            }
            for name, desc, opts in SUBCOMMANDS
        ],
    }


def main() -> int:
    app_id = os.environ.get("DISCORD_APPLICATION_ID", "").strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()

    if not app_id or not token:
        print("ERROR: DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN must be set.",
              file=sys.stderr)
        return 1

    if guild_id:
        url = f"https://discord.com/api/v10/applications/{app_id}/guilds/{guild_id}/commands"
        scope = f"guild {guild_id}"
    else:
        url = f"https://discord.com/api/v10/applications/{app_id}/commands"
        scope = "GLOBAL (may take up to 1 hour to propagate)"

    payload = [build_command_payload()]  # PUT replaces the whole list
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    print(f"Registering /aiui with {len(SUBCOMMANDS)} subcommands ({scope})...")
    with httpx.Client(timeout=30.0) as client:
        r = client.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"OK — {r.status_code}")
        return 0
    print(f"ERROR — {r.status_code} {r.text}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Local syntax check**

```bash
python -c "import ast; ast.parse(open('scripts/register_discord_commands.py').read()); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add scripts/register_discord_commands.py
git commit -m "feat(scripts): register_discord_commands — idempotent /aiui PUT"
```

---

### Task 11: Layer-2 integration test script

**Files:**
- Create: `scripts/discord_e2e_local.sh`
- Create: `webhook-handler/tests/test_discord_e2e_local.py` (the real assertion lives here)

- [ ] **Step 1: Write the pytest integration test**

```python
"""Layer-2 integration: synthetic signed Discord interaction → webhook-handler
→ TasksClient call. Test keypair, not Discord's live public key.

CRITICAL: discord_commands.py:92 dispatches via asyncio.create_task(...) and
returns DEFERRED immediately. To assert the background task ran AND ran
against respx mocks, the test MUST:
  1. Use httpx.AsyncClient + ASGITransport (one event loop owned by the test),
     not fastapi.testclient.TestClient (which spins a sync thread + its own
     loop that exits when the response returns).
  2. Hold the respx.mock context open AND await a short sleep INSIDE that
     context, so the create_task fires before the mocks are torn down.
  3. Stub the Edd25519 public key + DISCORD_USER_EMAIL_MAP_RAW BEFORE the
     webhook-handler app is imported (env-stub-before-import pattern,
     same as mcp-servers/tasks/tests).
"""
import asyncio
import json
import os
import sys

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from nacl.signing import SigningKey


# Stub env BEFORE app import.
_SK = SigningKey.generate()
os.environ["DISCORD_PUBLIC_KEY"] = _SK.verify_key.encode().hex()
os.environ["DISCORD_USER_EMAIL_MAP"] = "100:e2e-test@local"
os.environ.setdefault("TASKS_URL", "http://tasks-test:8210")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_signed_cronjob_list_reaches_tasks():
    from config import settings
    # Bust the settings-side dict cache so it picks up the env we just set.
    if hasattr(settings, "_discord_map_cache"):
        del settings._discord_map_cache
    assert settings.discord_user_email_map.get("100") == "e2e-test@local"

    from main import app

    # Build the signed interaction payload.
    payload = {
        "type": 2,  # APPLICATION_COMMAND
        "id": "intx-1",
        "token": "intx-token",
        "data": {
            "name": "aiui",
            "options": [{
                "name": "cronjob",
                "type": 1,
                "options": [{"name": "args", "type": 3, "value": "list"}],
            }],
        },
        "member": {"user": {"id": "100", "username": "tester"}},
        "channel_id": "c1",
        "guild_id": "g1",
    }
    body = json.dumps(payload).encode()
    timestamp = "1234567890"
    sig = _SK.sign(timestamp.encode() + body).signature.hex()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with respx.mock(base_url=settings.tasks_url, assert_all_called=False) as mock:
            list_route = mock.get("/schedules").mock(return_value=Response(200, json=[]))

            r = await client.post(
                "/webhook/discord",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature-Ed25519": sig,
                    "X-Signature-Timestamp": timestamp,
                },
            )

            # DEFERRED ack returns immediately.
            assert r.status_code == 200, r.text
            assert r.json()["type"] == 5

            # The dispatcher runs via asyncio.create_task. Yield repeatedly
            # so the background task runs on this same event loop before
            # respx is torn down.
            for _ in range(20):
                await asyncio.sleep(0.01)
                if list_route.called:
                    break

            assert list_route.called, "TasksClient.list_schedules must have been called"
            req = list_route.calls.last.request
            assert req.headers.get("x-user-email") == "e2e-test@local"
            assert "x-cron-secret" not in {k.lower() for k in req.headers}
```

- [ ] **Step 2: Run the test**

```bash
pytest webhook-handler/tests/test_discord_e2e_local.py -v
```

Expected: PASS.

- [ ] **Step 3: Write `scripts/discord_e2e_local.sh` shell wrapper**

```bash
#!/usr/bin/env bash
# Layer-2 integration test for /aiui cronjob and /aiui aiuibuilder.
# Test keypair, not Discord's live public key. Safe to run locally + in CI.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/3] Running unit + integration tests..."
pytest webhook-handler/tests/ -v
pytest mcp-servers/tasks/tests/test_routes_projects_list.py -v
pytest mcp-servers/tasks/tests/test_auth_current_user.py -v

echo "[2/3] Running the signed-Discord-interaction integration test..."
pytest webhook-handler/tests/test_discord_e2e_local.py -v

echo "[3/3] All green. Layer 1 + Layer 2 pass."
```

`chmod +x scripts/discord_e2e_local.sh`

- [ ] **Step 4: Commit**

```bash
git add scripts/discord_e2e_local.sh webhook-handler/tests/test_discord_e2e_local.py
git commit -m "test(webhook-handler): Layer-2 signed-interaction integration"
```

---

### Task 12: Wire env var through docker-compose + deploy + Layer-3 smoke

**Files:**
- Modify: `docker-compose.unified.yml` (webhook-handler `environment:` block)

- [ ] **Step 1: Add `DISCORD_USER_EMAIL_MAP` to webhook-handler env in `docker-compose.unified.yml`**

The webhook-handler service block already has DISCORD_APPLICATION_ID / DISCORD_PUBLIC_KEY / DISCORD_BOT_TOKEN entries around line 128-130. Insert immediately after `DISCORD_ALERT_CHANNEL_ID`:

```yaml
      - DISCORD_USER_EMAIL_MAP=${DISCORD_USER_EMAIL_MAP:-}
```

Without this, even if `.env` has the variable, the container's process never sees it — docker-compose only forwards env vars listed in the service's `environment:` block.

- [ ] **Step 2: Commit the compose change**

```bash
git add docker-compose.unified.yml
git commit -m "ops(compose): wire DISCORD_USER_EMAIL_MAP into webhook-handler"
```

- [ ] **Step 3: Confirm Layer 1 + 2 green locally**

```bash
./scripts/discord_e2e_local.sh
```

Expected: all green.

- [ ] **Step 4: SCP changed files to Hetzner**

```bash
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
scp webhook-handler/clients/tasks.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
scp webhook-handler/handlers/commands.py root@46.224.193.25:/root/proxy-server/webhook-handler/handlers/commands.py
scp webhook-handler/requirements.txt root@46.224.193.25:/root/proxy-server/webhook-handler/requirements.txt
scp mcp-servers/tasks/auth.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/auth.py
scp mcp-servers/tasks/routes_projects.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/routes_projects.py
scp scripts/register_discord_commands.py root@46.224.193.25:/root/proxy-server/scripts/register_discord_commands.py
scp docker-compose.unified.yml root@46.224.193.25:/root/proxy-server/docker-compose.unified.yml
```

`webhook-handler/clients/__init__.py` already exists on the server — no need to SCP.

- [ ] **Step 5: Set `DISCORD_USER_EMAIL_MAP` on server (idempotent upsert)**

Don't blindly `>>` — that appends a duplicate line. Use a remove-then-add:

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && \
  grep -v ^DISCORD_USER_EMAIL_MAP= .env > .env.tmp && mv .env.tmp .env && \
  echo "DISCORD_USER_EMAIL_MAP=<LUKAS_ID>:lukas@email,<RALPH_ID>:ralphbenitez32@gmail.com,<JACINTA_ID>:alamajacintg04@gmail.com" >> .env'
```

Replace `<LUKAS_ID>`, `<RALPH_ID>`, `<JACINTA_ID>` with real Discord snowflake IDs (right-click profile → Copy User ID with developer mode on). Lukas's email goes in unquoted; Bash special chars in the value will break `>>` if any appear — none expected for these inputs.

- [ ] **Step 6: Rebuild services**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build webhook-handler tasks'
```

- [ ] **Step 7: Wait for healthy, then check logs**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml logs --tail=30 webhook-handler | grep -i discord'
```

Expected: `DISCORD_USER_EMAIL_MAP: loaded N entries`.

- [ ] **Step 8: Verify tasks reachability from webhook-handler**

```bash
ssh root@46.224.193.25 'docker exec proxy-server-webhook-handler-1 \
  curl -sf http://tasks:8210/healthz'
```

Expected: `OK` (or whatever `/healthz` returns). Confirms container-to-container DNS + port works before invoking via Discord.

- [ ] **Step 9: Register the slash commands**

Token may contain `=` in base64 padding. Use `sed` to strip everything up to the first `=` instead of `cut -d= -f2`:

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && \
  DISCORD_APPLICATION_ID="$(grep ^DISCORD_APPLICATION_ID= .env | sed "s/^[^=]*=//")" \
  DISCORD_BOT_TOKEN="$(grep ^DISCORD_BOT_TOKEN= .env | sed "s/^[^=]*=//")" \
  python3 scripts/register_discord_commands.py'
```

Expected: `OK — 200` or `201`.

- [ ] **Step 10: Manual Layer 3 from Discord**

Open Discord, in the configured guild:

1. Type `/aiui help` — confirm `cronjob` and `aiuibuilder` appear in the help text reply.
2. Type `/aiui cronjob list` — confirm reply (either "no schedules" or a list).
3. Type `/aiui cronjob create "*/5 * * * *" "ping"` — confirm reply with a UUID.
4. Type `/aiui cronjob delete <that-uuid>` — confirm "Deleted ...".
5. Type `/aiui aiuibuilder list` — confirm reply (either "no projects" or a list).

- [ ] **Step 11: Cleanup**

If Step 10 sub-step 3 created any test schedules that aren't useful, delete them via the `delete` subcommand.

- [ ] **Step 12: Report**

No code changes needed at this stage. Report success: "Discord /aiui cronjob + aiuibuilder live."

---

## Rollback

If Layer 3 fails:
1. Revert webhook-handler image: `docker compose -f docker-compose.unified.yml up -d --rollback webhook-handler` (or pin to previous tag).
2. Unset `DISCORD_USER_EMAIL_MAP` in `.env`.
3. If the slash command tree got mangled, re-run `scripts/register_discord_commands.py` from the previous git ref to restore the old shape.

## Verification checklist

- [ ] All unit tests green (`webhook-handler/tests/`)
- [ ] All tasks tests green (`mcp-servers/tasks/tests/`)
- [ ] Layer-2 integration test green (`test_discord_e2e_local.py`)
- [ ] webhook-handler container starts cleanly with new env var
- [ ] `/aiui help` reply lists `cronjob` and `aiuibuilder`
- [ ] `/aiui cronjob create ...` returns a UUID
- [ ] `/aiui cronjob list` shows the schedule
- [ ] `/aiui cronjob delete <id>` succeeds
- [ ] `/aiui aiuibuilder list` returns user's projects
- [ ] Unmapped Discord user sees "not linked" reply (test with a second account or temp-remove from map)
