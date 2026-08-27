# Every User Gets Their Own Agents, and the Tool List Tells the Truth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scout and Triage stop being two shared agents and become templates every user gets their own private copy of, and the agent form shows which tools that person has actually connected.

**Architecture:** The two agent definitions move out of Ralph's account and into code. A new `tasks` router seeds a user's own copies the first time they open the Agents page, recording that it happened so a delete sticks. A second endpoint reports the tools available to the caller, computed from the real connection tables, and the form renders from it.

**Tech Stack:** Python 3.11, FastAPI, asyncpg/SQLAlchemy, pytest with `asyncio_mode = auto`, plain HTML/JS.

## Global Constraints

- Never add Claude, Anthropic, or any AI attribution to commits, PRs, code comments, or docs. Author is Ralph Benitez only.
- No em-dashes or en-dashes in anything a person reads, including UI copy and commit messages.
- Never log or store a minted token, and never put an exception's own text in a user-visible string.
- Seeding must FAIL OPEN. If it cannot run, the Agents page must still load and list whatever the user has. A broken seed must never be a broken page.
- Seeding must be idempotent and must happen at most once per user. A user who deletes both agents must not get them back.
- A user's copies are their own: they own them, can edit them, and can delete them permanently.
- Nothing may carry a wildcard (`principal_id = "*"`) access grant when this is done.
- Tool connection state is per user and read from the real tables. Never assume a tool is connected.

## Facts established on production, use these rather than re-deriving them

- 9 users: 5 admins, 4 regular. Only `ralphbenitez32@gmail.com` owns any agents.
- Only Ralph has Google connected. `public.gmail_tokens`, `public.calendar_tokens` and `public.gdrive_tokens` each hold exactly one row, keyed by column `user_email`.
- `tasks.user_connections` (ClickUp, Trello, GitHub, Notion, n8n) is EMPTY. Keyed `(email, provider)`.
- Sharing is off platform-wide: `user.permissions -> sharing.public_models` is `false`, so Open WebUI's create endpoint strips `access_grants` from anything submitted. The two wildcard grants were written directly by SQL.
- The web path into `tasks` is `/api/tasks/...`; the gateway validates the JWT and injects `X-User-Email`. `_resolve_caller` in `routes_schedules.py` is the pattern to copy.
- Routers are mounted twice in `main.py`: bare for operator calls carrying `X-Cron-Secret`, and under `prefix="/api/tasks"` for the web.
- Agent ids follow `agent-<slug>-<4 hex>`; the page retries once on a collision, which returns **401** with detail "already registered", not 409.

---

## File Structure

| Path | Responsibility |
|---|---|
| `mcp-servers/tasks/agent_templates.py` | NEW. The two template definitions, as data. The only place their text lives. |
| `mcp-servers/tasks/routes_agents.py` | NEW. `POST /agents/seed` and `GET /agents/tools`. |
| `mcp-servers/tasks/migrations/043_agent_seed.sql` | NEW. Records that a user has been seeded. |
| `mcp-servers/tasks/main.py` | MODIFY. Mount the new router, bare and under `/api/tasks`. |
| `mcp-servers/tasks/static/agents.html` | MODIFY. Seed on load; render tool tiles from the endpoint. |
| `mcp-servers/tasks/scripts/retire_platform_grants.py` | NEW. Drop the two wildcard grants and mark existing owners as seeded. |

---

### Task 1: The templates and the seed record

**Files:**
- Create: `mcp-servers/tasks/agent_templates.py`
- Create: `mcp-servers/tasks/migrations/043_agent_seed.sql`
- Test: `mcp-servers/tasks/tests/test_agent_templates.py`

**Interfaces:**
- Produces: `TEMPLATES: list[dict]`, each `{"slug": str, "name": str, "instructions": str, "tool_ids": list[str]}`.

The two texts are the ones live on production today. Copy them verbatim.

- [ ] **Step 1: Write the failing test**

```python
"""The templates every user gets a copy of.

These are checked hard because they go out to every account on the platform
and, once someone owns their copy, editing the template here never reaches
them again.
"""
import re

import pytest

from agent_templates import TEMPLATES

# The page enforces a one word name so the agent can be called by name in a
# sentence. A template that cannot be saved through the form is a bug.
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,23}$")

KNOWN_TOOLS = {
    "server:mcp-proxy", "gmail", "calendar", "gdrive",
    "documents", "excel_creator", "executive_dashboard", "remember",
}


def test_there_are_two_templates():
    assert len(TEMPLATES) == 2


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_the_name_is_one_word_and_mentionable(t):
    assert NAME_RE.match(t["name"]), t["name"]


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_the_instructions_are_real_and_within_the_form_limit(t):
    assert t["instructions"].strip()
    assert len(t["instructions"]) <= 4000


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["slug"])
def test_every_tool_named_is_one_the_platform_has(t):
    unknown = set(t["tool_ids"]) - KNOWN_TOOLS
    assert not unknown, unknown


def test_the_slugs_are_distinct():
    slugs = [t["slug"] for t in TEMPLATES]
    assert len(set(slugs)) == len(slugs)


def test_no_template_carries_an_access_grant():
    """Nothing seeded may be shared. Each copy belongs to one person."""
    for t in TEMPLATES:
        assert "access_grants" not in t
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_templates.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_templates'`

- [ ] **Step 3: Write the templates**

```python
"""The agents every account starts with.

They used to be two rows in one person's account carrying a wildcard read
grant, so everybody saw the same two and only their owner could change them.
They are templates now: each user gets their own copy to edit or delete.

Editing the text here changes what NEW users get. It does not reach anyone
who already has a copy, because that copy is theirs.
"""

TEMPLATES = [
    {
        "slug": "scout",
        "name": "Scout",
        "instructions": (
            "You research questions carefully and answer with what you found, "
            "not with what you assume. Search the web when the answer depends "
            "on current facts. Say plainly when you could not find something, "
            "and never present a guess as a finding. Keep answers short and "
            "put the conclusion first."
        ),
        "tool_ids": ["server:mcp-proxy"],
    },
    {
        "slug": "triage",
        "name": "Triage",
        "instructions": (
            "You read the user's unread email and tell them what actually "
            "needs them. Group messages into: needs a reply today, can wait, "
            "and no action. Give one line per message saying who it is from "
            "and what they want. Do not quote whole emails."
        ),
        "tool_ids": ["gmail"],
    },
]
```

- [ ] **Step 4: Write the migration**

Create `mcp-servers/tasks/migrations/043_agent_seed.sql`:

```sql
-- 043: who has already been given their own copy of the starter agents.
--
-- One row per user, written after their copies are created. Its only job is
-- to make a DELETE stick: without it, the next page load would helpfully
-- recreate the agents the user just threw away, and they could never be rid
-- of them.
--
-- Keyed by email because that is the identity the web path carries
-- (X-User-Email, injected by the gateway) and the same key
-- tasks.user_connections uses.
--
-- No foreign key to public.user: Open WebUI owns that table, and a deleted
-- account should not block or cascade into this record.
--
-- Idempotent: db.py re-runs every migration on every startup.

CREATE TABLE IF NOT EXISTS tasks.agent_seed (
    user_email TEXT        PRIMARY KEY,
    seeded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 5: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_templates.py -q`
Expected: PASS, 10 passed

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/agent_templates.py mcp-servers/tasks/migrations/043_agent_seed.sql mcp-servers/tasks/tests/test_agent_templates.py
git commit -m "feat(agents): the starter agents become templates

They were two rows in one account with a wildcard read grant, so everyone saw
the same two and only the owner could change them. As templates each user
gets a copy of their own."
```

---

### Task 2: Seed a user their own copies

**Files:**
- Create: `mcp-servers/tasks/routes_agents.py`
- Modify: `mcp-servers/tasks/main.py` (mount the router, both ways, beside `schedules_router`)
- Test: `mcp-servers/tasks/tests/test_agent_seed.py`

**Interfaces:**
- Consumes: `agent_templates.TEMPLATES`; `owui_token.mint_owui_token(user_id, ttl_seconds)`; the `_resolve_caller` pattern from `routes_schedules.py`.
- Produces: `POST /agents/seed` returning `{"seeded": bool, "created": int}`.

How it must behave:

1. Resolve the caller's email. No email means 400.
2. If `tasks.agent_seed` already has that email, return `{"seeded": False, "created": 0}` and do nothing. This is the whole point.
3. Otherwise resolve the Open WebUI user id for that email, mint a token for them, and create each template as that user by POSTing to Open WebUI's `/api/v1/models/create` with `{"id": ..., "name": ..., "base_model_id": ..., "meta": {"toolIds": [...]}, "params": {"system": ...}, "access_grants": [], "is_active": True}`.
4. Ids are `agent-<slug>-<4 lowercase hex>`. A duplicate comes back **401** with "already registered" in the detail; retry once with a fresh suffix, then give up on that template and carry on with the next.
5. Write the `agent_seed` row **after** the attempt, whether or not every template succeeded. A user who got one of two must not be pestered on every page load.
6. The base model is the platform default. Read it from the `AGENT_DEFAULT_MODEL` environment variable, falling back to `gpt-4o-mini`, which is what both live agents use.
7. Nothing here may raise to the caller. Any failure returns `{"seeded": False, "created": 0}` and logs.

- [ ] **Step 1: Write the failing test**

```python
"""Seeding a user their own copies of the starter agents.

The assertions about WHO the agents are created for exist because a review on
this codebase twice found identity mutations that passed a full suite.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

import routes_agents


async def test_a_new_user_gets_a_copy_of_every_template():
    created = []

    async def fake_create(token, body):
        created.append(body)
        return 200, {"id": body["id"]}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=fake_create):
        out = await routes_agents.seed_for_email("newbie@example.com")

    assert out["created"] == 2
    names = sorted(b["name"] for b in created)
    assert names == ["Scout", "Triage"]


async def test_the_copies_are_created_for_that_user_and_nobody_else():
    resolver = AsyncMock(return_value="uid-1")
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=resolver), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=AsyncMock(return_value=(200, {}))):
        await routes_agents.seed_for_email("newbie@example.com")

    resolver.assert_awaited_once_with("newbie@example.com")


async def test_nothing_seeded_carries_a_grant():
    """A copy belongs to one person. Sharing is what we are getting rid of."""
    created = []

    async def fake_create(token, body):
        created.append(body)
        return 200, {}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=fake_create):
        await routes_agents.seed_for_email("newbie@example.com")

    for body in created:
        assert body["access_grants"] == []


async def test_a_user_who_was_already_seeded_gets_nothing():
    create = AsyncMock()
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=True)), \
         patch.object(routes_agents, "_create_model", new=create):
        out = await routes_agents.seed_for_email("old@example.com")

    create.assert_not_awaited(), "it seeded somebody twice"
    assert out == {"seeded": False, "created": 0}


async def test_the_seed_is_recorded_even_when_a_template_fails():
    """Otherwise a user whose first copy failed is nagged forever."""
    mark = AsyncMock()

    async def half_fails(token, body):
        return (200, {}) if body["name"] == "Scout" else (500, "boom")

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=mark), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=half_fails):
        out = await routes_agents.seed_for_email("half@example.com")

    mark.assert_awaited_once()
    assert out["created"] == 1


async def test_a_duplicate_id_is_retried_once_with_a_new_suffix():
    seen = []

    async def collide(token, body):
        seen.append(body["id"])
        if len(seen) == 1:
            return 401, {"detail": "Model id already registered"}
        return 200, {}

    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_mark_seeded", new=AsyncMock()), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value="uid-1")), \
         patch.object(routes_agents, "mint_owui_token", lambda *a, **k: "tok"), \
         patch.object(routes_agents, "_create_model", new=collide):
        await routes_agents.seed_for_email("dupe@example.com")

    assert len(seen) >= 2, "it gave up instead of retrying"
    assert seen[0] != seen[1], "it retried with the same id"


async def test_seeding_never_raises_to_the_caller():
    with patch.object(routes_agents, "_already_seeded",
                      new=AsyncMock(side_effect=RuntimeError("db down"))):
        out = await routes_agents.seed_for_email("x@example.com")
    assert out == {"seeded": False, "created": 0}


async def test_an_unknown_user_is_not_seeded():
    create = AsyncMock()
    with patch.object(routes_agents, "_already_seeded", new=AsyncMock(return_value=False)), \
         patch.object(routes_agents, "_owui_user_id_for", new=AsyncMock(return_value=None)), \
         patch.object(routes_agents, "_create_model", new=create):
        out = await routes_agents.seed_for_email("ghost@example.com")
    create.assert_not_awaited()
    assert out["created"] == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_seed.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'routes_agents'`

- [ ] **Step 3: Implement the router**

Write `routes_agents.py` with: `router = APIRouter(prefix="/agents")`, the helpers `_already_seeded`, `_mark_seeded`, `_owui_user_id_for`, `_create_model` (each a module level seam the tests patch), `seed_for_email(email) -> dict`, and the route

```python
@router.post("/seed")
async def seed(x_cron_secret: str = Header(default=""),
               x_user_email: str = Header(default="")) -> dict:
```

which resolves the caller and delegates to `seed_for_email`. Reuse `agent_runner._owui_user_id_for` rather than writing a second resolver.

- [ ] **Step 4: Mount it**

In `mcp-servers/tasks/main.py`, beside the schedules mounts:

```python
app.include_router(agents_router)                        # /agents, operator path
app.include_router(agents_router, prefix="/api/tasks")   # /api/tasks/agents, web path
```

- [ ] **Step 5: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_seed.py -q`
Expected: PASS, 8 passed

- [ ] **Step 6: Prove the identity and the once-only guard bite**

Mutate `_owui_user_id_for(email)` to a hardcoded address and confirm `test_the_copies_are_created_for_that_user_and_nobody_else` fails. Then make `_already_seeded` always return False and confirm `test_a_user_who_was_already_seeded_gets_nothing` fails. Restore both. Report the observed failures.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_agent_seed.py
git commit -m "feat(agents): give each user their own copies, once

Recorded per user so a delete sticks. Seeding fails open: a page that cannot
seed still lists whatever the person already has."
```

---

### Task 3: Report the tools this person can actually use

**Files:**
- Modify: `mcp-servers/tasks/routes_agents.py`
- Test: `mcp-servers/tasks/tests/test_agent_tools_endpoint.py`

**Interfaces:**
- Produces: `GET /agents/tools` returning `{"tools": [{"id", "label", "connected", "connect_url"}]}`.

Where connection state really lives, verified on production:

| Tool id | Connected when | Connect at |
|---|---|---|
| `gmail` | a row in `public.gmail_tokens` with `user_email` = caller | `/tasks/static/connections.html` |
| `calendar` | a row in `public.calendar_tokens` | same |
| `gdrive` | a row in `public.gdrive_tokens` | same |
| `server:mcp-proxy` | any row in `tasks.user_connections` for that email | same |
| `documents`, `excel_creator`, `executive_dashboard`, `remember` | always, they need nothing | none |

The native list itself comes from `public.tool`, ordered by id, NOT from a hardcoded array, so a tool an admin installs later shows up on its own. Labels come from a map in this module, falling back to the tool's own `name` column.

- [ ] **Step 1: Write the failing test**

```python
"""What the form is allowed to offer this person.

Today the form offers Gmail to all 9 users and only 1 of them has a Gmail
token, so 8 people can tick a box that silently does nothing.
"""
from unittest.mock import AsyncMock, patch

import routes_agents


async def test_a_tool_needing_no_connection_is_always_available():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["documents", "remember"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("nobody@example.com")

    by_id = {t["id"]: t for t in out["tools"]}
    assert by_id["documents"]["connected"] is True
    assert by_id["remember"]["connected"] is True


async def test_gmail_is_not_connected_without_a_token():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("nobody@example.com")

    gmail = out["tools"][0]
    assert gmail["connected"] is False
    assert gmail["connect_url"], "it offered no way to fix it"


async def test_gmail_is_connected_when_the_user_has_a_token():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value={"gmail"})):
        out = await routes_agents.tools_for_email("ralph@example.com")

    assert out["tools"][0]["connected"] is True


async def test_connection_state_is_read_for_the_asking_user():
    """One person's Gmail must never make it look connected for another."""
    probe = AsyncMock(return_value=set())
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["gmail"])), \
         patch.object(routes_agents, "_connected_providers", new=probe):
        await routes_agents.tools_for_email("asker@example.com")

    probe.assert_awaited_once_with("asker@example.com")


async def test_a_newly_installed_tool_appears_without_a_code_change():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=["brand_new_tool"])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value=set())):
        out = await routes_agents.tools_for_email("x@example.com")

    assert [t["id"] for t in out["tools"]] == ["brand_new_tool"]
    assert out["tools"][0]["label"], "it had no label to show"


async def test_the_connected_apps_umbrella_follows_user_connections():
    with patch.object(routes_agents, "_installed_tool_ids",
                      new=AsyncMock(return_value=[])), \
         patch.object(routes_agents, "_connected_providers",
                      new=AsyncMock(return_value={"clickup"})):
        out = await routes_agents.tools_for_email("x@example.com")

    umbrella = [t for t in out["tools"] if t["id"] == "server:mcp-proxy"]
    assert umbrella and umbrella[0]["connected"] is True
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_endpoint.py -q`
Expected: FAIL, `AttributeError: module 'routes_agents' has no attribute 'tools_for_email'`

- [ ] **Step 3: Implement**

Add `_installed_tool_ids()`, `_connected_providers(email)` and `tools_for_email(email)` plus the route. `_connected_providers` returns a set drawn from the three token tables and `tasks.user_connections`, in ONE pass, and must be scoped to the passed email in every query.

- [ ] **Step 4: Run the tests**

Run: `cd mcp-servers/tasks && py -m pytest tests/test_agent_tools_endpoint.py tests/test_agent_seed.py -q`
Expected: PASS, 14 passed

- [ ] **Step 5: Prove the scoping bites**

Mutate `_connected_providers` to ignore its argument and return every connected provider on the platform. `test_connection_state_is_read_for_the_asking_user` must fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_agents.py mcp-servers/tasks/tests/test_agent_tools_endpoint.py
git commit -m "feat(agents): report the tools a person has actually connected

The form offered Gmail to everyone while one user in nine had a token."
```

---

### Task 4: Wire the page

**Files:**
- Modify: `mcp-servers/tasks/static/agents.html`
- Test: `mcp-servers/tasks/tests/browser/test_agents_tools_live.py`

Two changes.

**Seed on load.** Before listing, `POST /api/tasks/agents/seed` with the page's existing `authHeaders()` and `credentials: "include"` pattern (copy it from `cron.html`). Whatever it answers, and even if it fails outright, carry on and load the list. Then load.

**Render the tool tiles from the endpoint.** Replace the hardcoded `NATIVE_TOOLS` array with `GET /api/tasks/agents/tools`. For each tool render the existing tile. When `connected` is false: the input is `disabled`, the tile gets a `not-connected` class, and a `Connect` link to `connect_url` is shown inside it. If the endpoint fails, fall back to the current hardcoded list with everything enabled, so the form still works.

Keep the input ids exactly `tool-<id>` and keep `#use-my-apps`. Existing tests drive them by id.

- [ ] **Step 1: Write the failing test**

```python
"""The form must not offer a tool the person cannot use."""


def test_an_unconnected_tool_cannot_be_ticked(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    box = page.locator("#tool-gmail")
    assert box.is_disabled(), "it let them pick a tool they have not connected"


def test_an_unconnected_tool_offers_a_way_to_connect(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    tile = page.locator("label:has(#tool-gmail)")
    assert "Connect" in tile.inner_text()


def test_a_connected_tool_is_selectable(page_with_tools):
    page = page_with_tools
    page.locator("#new-agent").click()
    assert page.locator("#tool-documents").is_enabled()


def test_the_page_seeds_once_on_load(page_with_tools):
    seeds = [c for c in page_with_tools.sent if "/agents/seed" in c["url"]]
    assert len(seeds) == 1
```

Build `page_with_tools` on the existing `page` fixture in `test_agents_page.py`, adding routes for `/api/tasks/agents/seed` and `/api/tasks/agents/tools`, where `tools` answers with `gmail` unconnected and `documents` connected.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/test_agents_tools_live.py -q`
Expected: FAIL, the checkbox is enabled.

- [ ] **Step 3: Implement both changes in `agents.html`**

- [ ] **Step 4: Run every agents test**

Run: `cd mcp-servers/tasks && py -m pytest tests/browser/ -q -p no:randomly`
Expected: PASS. The browser suite was 204 before this task.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/agents.html mcp-servers/tasks/tests/browser/test_agents_tools_live.py
git commit -m "feat(agents): the form offers only what you have connected

An unconnected tool is shown greyed with a link to connect it, rather than
hidden, so nothing disappears without explanation."
```

---

### Task 5: Retire the two wildcard grants

**Files:**
- Create: `mcp-servers/tasks/scripts/retire_platform_grants.py`

The script must, in one pass and idempotently:

1. Delete every `access_grant` row where `principal_id = '*'` **and** the resource is a model with a non-null `base_model_id`. Base models keep their wildcard grants: that is how everyone gets `gpt-4o-mini`, and removing those would break the platform for all 9 users. This filter is the whole safety of the script.
2. Insert an `agent_seed` row for every user who already owns at least one derived model, so nobody who has agents is handed duplicates.
3. Print what it did and what it left alone, and change nothing else.

- [ ] **Step 1: Write it, with the count of base model grants printed BEFORE and AFTER as proof they were untouched**
- [ ] **Step 2: Dry run it on production with a `--dry-run` flag first and read the output**
- [ ] **Step 3: Run it for real, then confirm: 0 wildcard grants on derived models, base model grants unchanged at 133, and an `agent_seed` row for `ralphbenitez32@gmail.com`**
- [ ] **Step 4: Commit**

---

### Task 6: Verify on production

- [ ] **Step 1: Deploy** following the repo's process: hash sweep, copy, `sed -i 's/\r$//'`, rebuild, confirm migration 043 applied.
- [ ] **Step 2:** Open the Agents page as Ralph. Expect the same two agents, no "Shared with everyone" badge, and no duplicates.
- [ ] **Step 3:** Act as a user who has never had agents. Expect two agents appear, owned by them.
- [ ] **Step 4:** As that user, confirm Gmail is greyed with a Connect link and Documents is selectable, since they have no Google tokens.
- [ ] **Step 5:** Delete both agents as that user, reload, and confirm they stay gone.
- [ ] **Step 6:** Confirm the 4 existing schedules still run and nothing else moved.

---

## Self-Review

**Spec coverage.** Templates, Task 1. Per-user copies owned by the user, Task 2. Delete sticks, Task 1's table plus Task 2's guard, proved in Task 6 step 5. Tools reflecting real connections, Task 3. Greyed with a Connect link, Task 4. Wildcard grants gone, Task 5. Every user including admins, Task 2 seeds on any authenticated caller with no role check.

**Placeholders.** None. Every code step carries its code; every test step its assertions.

**Type consistency.** `seed_for_email(email) -> {"seeded": bool, "created": int}` and `tools_for_email(email) -> {"tools": [...]}` are defined in Tasks 2 and 3 and consumed with those shapes in Task 4. `TEMPLATES` entries use `slug`, `name`, `instructions`, `tool_ids` throughout.

**One risk called out.** Task 5 deletes grant rows on production. Its filter on `base_model_id IS NOT NULL` is the only thing standing between it and removing every user's access to every base model. That is why it gets a dry run first and a before-and-after count.
