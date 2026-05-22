# Selectable "Your apps" List → Per-Project Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Discord `/aiui aiuibuilder list` selectable — add a dropdown of the user's apps; picking one posts an ephemeral, state-aware action menu (Enhance / Publish|Unpublish / Open link / Status).

**Architecture:** Three files change in `webhook-handler`. Pure Discord component builders + id helpers go in `handlers/app_builder_panel.py` (no I/O, fully unit-testable). The interaction router `handlers/discord_commands.py` gains a string-select branch and a Status-button branch, both deferring to background router methods. `handlers/commands.py` gains `run_panel_menu`/`run_panel_status`, a new `CommandContext.respond_components` callback, and attaches the dropdown in the existing `list` path. Reuses the existing Publish/Enhance/Unpublish handlers unchanged.

**Tech Stack:** Python 3.11, FastAPI webhook-handler, Discord interactions API (component type 3 = string select), httpx tasks client, pytest + pytest-asyncio (already in the image).

**Spec:** `docs/superpowers/specs/2026-05-22-aiuibuilder-selectable-app-menu-design.md`

---

## Working environment (READ FIRST)

This feature lives **only on the production VPS**, uncommitted. We edit the VPS
files in place (the user chose "edit directly on the VPS"). The webhook-handler
service has **no bind mount** — its code is baked into the image at build — so the
live container only changes on `docker cp` + `docker restart`. Tests, however,
run in a **throwaway container** that *does* bind-mount the host source, so they
pick up edits immediately without touching the live container.

```bash
# Connection (run from the local machine; bash tool):
SSH="ssh -i ~/.ssh/aiui_vps -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=5 root@46.224.193.25"
SCP="scp -i ~/.ssh/aiui_vps -o BatchMode=yes -o ConnectTimeout=20"
VPS_WH=/root/proxy-server/webhook-handler          # webhook-handler root on the VPS
IMG=proxy-server-webhook-handler                    # image to run tests in

# Local scratch copies of the 3 source files already pulled here:
#   C:/Users/RYZENmsiPROddr4/AppData/Local/Temp/aiui-vps-appbuilder/
#     webhook-handler_handlers_app_builder_panel.py
#     webhook-handler_handlers_commands.py
#     webhook-handler_handlers_discord_commands.py
# Edit those with the Edit tool, then push each to the VPS:
$SCP <scratch>/webhook-handler_handlers_app_builder_panel.py  root@46.224.193.25:$VPS_WH/handlers/app_builder_panel.py
# (same pattern for commands.py and discord_commands.py)

# Create new test files + pytest.ini directly on the VPS (heredoc) OR author
# locally and scp into $VPS_WH/tests/ and $VPS_WH/pytest.ini.

# CANONICAL TEST COMMAND (throwaway container, bind-mounts live host source, auto-removed):
$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/ -v"

# DEPLOY (only in Task 7): copy the 3 source files into the live container + restart:
$SSH "cd /root/proxy-server && for f in handlers/app_builder_panel.py handlers/commands.py handlers/discord_commands.py; do docker cp webhook-handler/\$f webhook-handler:/app/\$f; done && docker restart webhook-handler"
```

**Notes:**
- `pytest.ini` sets `asyncio_mode = auto` so async tests need no `@pytest.mark.asyncio`. If a worker sees "async def functions are not natively supported," fall back to adding that decorator.
- Match existing emoji style in `app_builder_panel.py`: raw `✏️`/`ℹ️`, and `\U0001f7e2` (🟢 Publish), `\U0001f50c` (🔌 Unpublish), `\U0001f517` (🔗 Open) escapes.
- **Do NOT** `git add -A` on the VPS — the repo has unrelated uncommitted work. Stage only this feature's files (Task 7).
- Slugs are assumed ≤100 chars so the select `value` round-trips back to a real slug.
- No Discord slash-command re-registration is needed (the `list/status/open` commands are unchanged; component interactions are created at runtime).

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `webhook-handler/handlers/app_builder_panel.py` | Modify | Add `build_apps_select_components`, `build_project_menu_components`, ids/helpers (`APP_SELECT_ID`, `STATUS_PREFIX`, `is_app_select`, `is_status_button`, `slug_from_status_button`). Pure, no I/O. |
| `webhook-handler/handlers/commands.py` | Modify | Add `import os` + `PUBLIC_DOMAIN`; add `CommandContext.respond_components`; add `run_panel_menu`, `run_panel_status`, `_format_status_error`; attach dropdown in `_handle_aiuibuilder` `list`. |
| `webhook-handler/handlers/discord_commands.py` | Modify | Set `respond_components` in `_handle_application_command`; add select + status branches in `_handle_message_component` (new `_handle_app_select_component`, `_handle_status_component`); import the 3 new helpers. |
| `webhook-handler/tests/test_app_builder_panel.py` | Create | Pure builder + id-helper tests (sync). |
| `webhook-handler/tests/test_commands_panel_menu.py` | Create | `run_panel_menu`/`run_panel_status` + `list` dropdown tests (async, fake tasks client). |
| `webhook-handler/tests/test_discord_commands_appselect.py` | Create | Interaction-routing tests (async, fake Discord + fake router). |
| `webhook-handler/pytest.ini` | Create | `asyncio_mode = auto`. |

---

## Task 0: Test harness on the VPS

**Files:**
- Create: `webhook-handler/pytest.ini`
- Create: `webhook-handler/tests/__init__.py` (empty), `webhook-handler/tests/test_smoke.py` (temporary)

- [ ] **Step 1: Create `pytest.ini` on the VPS**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: Create `tests/` with an empty `__init__.py` and a smoke test**

```python
# tests/test_smoke.py
def test_smoke():
    assert True
```

- [ ] **Step 3: Run the canonical test command — verify the harness works**

Run: `$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/ -v"`
Expected: `tests/test_smoke.py::test_smoke PASSED` (1 passed).

- [ ] **Step 4: Delete the smoke test, commit the harness**

```bash
$SSH "cd $VPS_WH && rm tests/test_smoke.py && cd /root/proxy-server && git add webhook-handler/pytest.ini webhook-handler/tests/__init__.py && git commit -m 'test(webhook-handler): add pytest harness for app builder panel'"
```

---

## Task 1: App-select id helpers + constants (pure)

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py` (append after the existing enhance-modal helpers, ~end of file)
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Write failing tests for the id helpers**

```python
# tests/test_app_builder_panel.py
from handlers import app_builder_panel as panel


def test_app_select_id_recognized():
    assert panel.is_app_select(panel.APP_SELECT_ID) is True
    assert panel.is_app_select("aiuibuild:publish:foo") is False


def test_status_button_roundtrip():
    cid = f"{panel.STATUS_PREFIX}my-coffee-shop"
    assert panel.is_status_button(cid) is True
    assert panel.slug_from_status_button(cid) == "my-coffee-shop"


def test_status_button_rejects_foreign_and_empty():
    assert panel.is_status_button("aiuibuild:publish:x") is False
    import pytest
    with pytest.raises(ValueError):
        panel.slug_from_status_button("aiuibuild:status:")  # empty slug
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/test_app_builder_panel.py -v"`
Expected: FAIL — `AttributeError: module 'handlers.app_builder_panel' has no attribute 'APP_SELECT_ID'`.

- [ ] **Step 3: Implement the ids + helpers**

Append to `app_builder_panel.py`:

```python
# --- Selectable "Your apps" list: dropdown + per-project menu ---
SELECT_MENU = 3  # Discord string-select component type

APP_SELECT_ID = "aiuibuild:appselect"  # the dropdown's custom_id (exact match)
STATUS_PREFIX = "aiuibuild:status:"     # status button -> aiuibuild:status:<slug>
_MAX_SELECT_OPTIONS = 25                 # Discord hard limit


def is_app_select(custom_id: str) -> bool:
    return custom_id == APP_SELECT_ID


def is_status_button(custom_id: str) -> bool:
    return custom_id.startswith(STATUS_PREFIX)


def slug_from_status_button(custom_id: str) -> str:
    return _slug_after(custom_id, STATUS_PREFIX)
```

- [ ] **Step 4: Push to VPS and run tests — verify they pass**

Run: push `app_builder_panel.py` (see preamble), then
`$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/test_app_builder_panel.py -v"`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py && git commit -m 'feat(app-builder): add app-select + status custom_id helpers'"
```

---

## Task 2: `build_apps_select_components` (pure)

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py`
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Write failing tests**

```python
def test_build_apps_select_shape():
    rows = panel.build_apps_select_components([
        {"slug": "shop", "name": "My Shop", "public_url": "https://x"},
        {"slug": "port", "name": "Portfolio", "public_url": None},
    ])
    assert len(rows) == 1
    select = rows[0]["components"][0]
    assert select["type"] == panel.SELECT_MENU
    assert select["custom_id"] == panel.APP_SELECT_ID
    assert [o["value"] for o in select["options"]] == ["shop", "port"]
    assert select["options"][0]["label"] == "My Shop"


def test_build_apps_select_description_reflects_publish_state():
    rows = panel.build_apps_select_components([
        {"slug": "shop", "name": "My Shop", "public_url": "https://x"},
        {"slug": "port", "name": "Portfolio", "public_url": None},
    ])
    opts = rows[0]["components"][0]["options"]
    assert opts[0]["description"] == "published"
    assert opts[1]["description"] == "not published"


def test_build_apps_select_caps_at_25():
    projects = [{"slug": f"a{i}", "name": f"A{i}", "public_url": None} for i in range(40)]
    rows = panel.build_apps_select_components(projects)
    assert len(rows[0]["components"][0]["options"]) == 25
```

- [ ] **Step 2: Run tests — verify they fail**

Run the test file. Expected: FAIL — `AttributeError: ... 'build_apps_select_components'`.

- [ ] **Step 3: Implement**

Append to `app_builder_panel.py`:

```python
def build_apps_select_components(projects: list[dict]) -> list[dict]:
    """One action row holding a string select of the user's apps. value=slug,
    description shows publish state. Caps at 25 options (Discord max). Caller must
    NOT pass an empty list (Discord rejects a 0-option select)."""
    options: list[dict] = []
    for p in projects[:_MAX_SELECT_OPTIONS]:
        slug = p.get("slug")
        if not slug:
            continue  # tolerate a malformed row rather than crash
        published = bool(p.get("public_url"))
        options.append({
            "label": (p.get("name") or slug)[:100],
            "value": slug[:100],
            "description": ("published" if published else "not published")[:100],
        })
    select = {
        "type": SELECT_MENU,
        "custom_id": APP_SELECT_ID,
        "placeholder": "Select an app to manage…",
        "min_values": 1,
        "max_values": 1,
        "options": options,
    }
    return [{"type": ACTION_ROW, "components": [select]}]
```

- [ ] **Step 4: Push + run tests — verify pass**

Expected: all `test_build_apps_select_*` pass.

- [ ] **Step 5: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py && git commit -m 'feat(app-builder): build apps dropdown component'"
```

---

## Task 3: `build_project_menu_components` (pure)

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py`
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Write failing tests**

```python
def _labels(rows):
    return [c.get("label") for c in rows[0]["components"]]


def test_project_menu_not_published():
    rows = panel.build_project_menu_components(
        "shop", published=False, public_url="", preview_url="https://prev/shop/")
    labels = _labels(rows)
    assert any("Enhance" in l for l in labels)
    assert any("Publish" in l for l in labels)
    assert any("Open preview" in l for l in labels)
    assert any("Status" in l for l in labels)
    assert not any("Unpublish" in l for l in labels)


def test_project_menu_published():
    rows = panel.build_project_menu_components(
        "shop", published=True, public_url="https://shop.live", preview_url="")
    labels = _labels(rows)
    assert any("Unpublish" in l for l in labels)
    assert any("Open live" in l for l in labels)
    assert not any("Publish" == (l or "").strip().split(" ")[-1] for l in labels if l and "Unpublish" not in l)


def test_project_menu_omits_link_when_url_missing():
    rows = panel.build_project_menu_components(
        "shop", published=False, public_url="", preview_url="")
    link_buttons = [c for c in rows[0]["components"] if c.get("style") == panel.STYLE_LINK]
    assert link_buttons == []


def test_project_menu_status_custom_id():
    rows = panel.build_project_menu_components("shop", published=True, public_url="https://x")
    status = [c for c in rows[0]["components"] if c.get("custom_id", "").startswith(panel.STATUS_PREFIX)]
    assert status and status[0]["custom_id"] == "aiuibuild:status:shop"
```

- [ ] **Step 2: Run — verify fail**

Expected: FAIL — `AttributeError: ... 'build_project_menu_components'`.

- [ ] **Step 3: Implement**

Append to `app_builder_panel.py`:

```python
def build_project_menu_components(
    slug: str, *, published: bool, public_url: str = "", preview_url: str = "",
) -> list[dict]:
    """State-aware action row for a selected app:
    Enhance + (Publish | Unpublish) + an Open link (only when its URL is set) + Status.
    Max 5 buttons per row; we emit at most 4."""
    buttons: list[dict] = [
        _button("✏️ Enhance", f"{ENHANCE_PREFIX}{slug}", STYLE_PRIMARY),
    ]
    if published:
        buttons.append(_button("\U0001f50c Unpublish", f"{UNPUBLISH_PREFIX}{slug}", STYLE_DANGER))
        if public_url:
            buttons.append({"type": BUTTON, "style": STYLE_LINK,
                            "label": "\U0001f517 Open live", "url": public_url})
    else:
        buttons.append(_button("\U0001f7e2 Publish", f"{PUBLISH_PREFIX}{slug}", STYLE_SUCCESS))
        if preview_url:
            buttons.append({"type": BUTTON, "style": STYLE_LINK,
                            "label": "\U0001f517 Open preview", "url": preview_url})
    buttons.append(_button("ℹ️ Status", f"{STATUS_PREFIX}{slug}", STYLE_SECONDARY))
    return [{"type": ACTION_ROW, "components": buttons}]
```

- [ ] **Step 4: Push + run tests — verify pass**

Expected: all `test_project_menu_*` pass; full file green.

- [ ] **Step 5: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py && git commit -m 'feat(app-builder): build state-aware per-project menu component'"
```

---

## Task 4: `CommandContext.respond_components` + `run_panel_menu`/`run_panel_status`

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (imports ~line 1-17; `CommandContext` ~line 26-44; new methods near the other `run_panel_*` ~line 1593)
- Test: `webhook-handler/tests/test_commands_panel_menu.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_commands_panel_menu.py
import pytest
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


class FakeTasks:
    def __init__(self, status=None, error=None):
        self._status = status or {}
        self._error = error
    async def get_project_status(self, email, slug):
        if self._error:
            raise self._error
        return {"slug": slug, **self._status}


def _router(tasks, email_map=None):
    return CommandRouter(
        None, None,
        discord_user_email_map=email_map or {"u1": "a@b.com"},
        tasks_client=tasks,
    )


def _ctx():
    sent = {"text": [], "comp": []}
    async def respond(msg): sent["text"].append(msg)
    async def respond_components(msg, components): sent["comp"].append((msg, components))
    ctx = CommandContext(
        user_id="u1", user_name="ralph", channel_id="c1", raw_text="", subcommand="aiuibuilder",
        arguments="", platform="discord", respond=respond, respond_components=respond_components,
    )
    return ctx, sent


async def test_run_panel_menu_published_uses_respond_components():
    tasks = FakeTasks(status={"name": "Shop", "role": "owner", "published": True,
                              "public_url": "https://shop.live"})
    ctx, sent = _ctx()
    await _router(tasks).run_panel_menu(ctx, "shop")
    assert len(sent["comp"]) == 1
    header, components = sent["comp"][0]
    assert "Shop" in header and "published" in header
    labels = [c.get("label") for c in components[0]["components"]]
    assert any("Unpublish" in l for l in labels)


async def test_run_panel_menu_not_linked():
    ctx, sent = _ctx()
    await _router(FakeTasks(), email_map={}).run_panel_menu(ctx, "shop")
    assert sent["comp"] == []
    assert any("isn't linked" in m for m in sent["text"])


async def test_run_panel_menu_404():
    tasks = FakeTasks(error=TasksAPIError(404, "nope"))
    ctx, sent = _ctx()
    await _router(tasks).run_panel_menu(ctx, "shop")
    assert any("not found" in m.lower() for m in sent["text"])
    assert sent["comp"] == []


async def test_run_panel_status_text():
    tasks = FakeTasks(status={"name": "Shop", "role": "owner", "published": False})
    ctx, sent = _ctx()
    await _router(tasks).run_panel_status(ctx, "shop")
    joined = "\n".join(sent["text"])
    assert "Shop" in joined and "Role: owner" in joined and "Published: no" in joined
```

- [ ] **Step 2: Run — verify fail**

Run: `$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/test_commands_panel_menu.py -v"`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'respond_components'` (and missing methods).

- [ ] **Step 3a: Add `import os` + `PUBLIC_DOMAIN`**

In `commands.py` imports block (after `import logging`, ~line 9) add `import os`. After the `BUILD_*` constants (~line 23) add:

```python
# Public host for building preview links (matches the tasks service's
# AIUI_PUBLIC_DOMAIN default; the domain is otherwise hardcoded elsewhere here).
PUBLIC_DOMAIN = os.environ.get("AIUI_PUBLIC_DOMAIN", "ai-ui.coolestdomain.win")
```

- [ ] **Step 3b: Import the menu builders**

Under the existing `from clients.tasks import ...` line, the file does not import panel builders yet. Add near the top imports:

```python
from handlers.app_builder_panel import (
    build_apps_select_components,
    build_project_menu_components,
)
```

(No import cycle: `app_builder_panel` imports nothing from `commands`.)

- [ ] **Step 3c: Add the `respond_components` field to `CommandContext`**

After the `on_published` field (~line 44):

```python
    # (message, components) -> edit the interaction reply to include Discord
    # components (the apps dropdown or a per-project menu). Set by the Discord
    # layer; None on other platforms.
    respond_components: Optional[Callable[[str, list], Awaitable[None]]] = None
```

- [ ] **Step 3d: Add `run_panel_menu`, `run_panel_status`, `_format_status_error`**

Insert next to the other `run_panel_*` methods (after `run_panel_unpublish`, ~line 1593):

```python
    async def run_panel_menu(self, ctx: CommandContext, slug: str) -> None:
        """App Builder dropdown selection → post that app's ephemeral action menu.
        Fetches fresh status so the menu reflects current publish state."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond("Your Discord account isn't linked. Ask Lukas to add you.")
            return
        try:
            status = await self._tasks_client.get_project_status(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_status_error(e))
            return
        name = status.get("name", slug)
        published = bool(status.get("published"))
        public_url = (status.get("public_url") or "").strip()
        preview_url = f"https://{PUBLIC_DOMAIN}/tasks/preview-app/{slug}/"
        header = f"**{name}** (`{slug}`) — {'published' if published else 'not published'}"
        components = build_project_menu_components(
            slug, published=published, public_url=public_url, preview_url=preview_url,
        )
        if ctx.respond_components is not None:
            await ctx.respond_components(header, components)
        else:
            await ctx.respond(header)

    async def run_panel_status(self, ctx: CommandContext, slug: str) -> None:
        """App Builder Status button → post the app's status text (same shape as
        the `aiuibuilder status <slug>` text action)."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond("Your Discord account isn't linked. Ask Lukas to add you.")
            return
        try:
            status = await self._tasks_client.get_project_status(email, slug)
        except TasksAPIError as e:
            await ctx.respond(self._format_status_error(e))
            return
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

    @staticmethod
    def _format_status_error(e: TasksAPIError) -> str:
        if e.status == 404:
            return "Project not found or not yours."
        if e.status == 0:
            return "Tasks service unreachable, try again."
        return f"Tasks API error ({e.status})."
```

- [ ] **Step 4: Push + run tests — verify pass**

Run the test file. Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/commands.py webhook-handler/tests/test_commands_panel_menu.py && git commit -m 'feat(app-builder): run_panel_menu/status + respond_components context'"
```

---

## Task 5: Attach the dropdown in the `list` path

**Files:**
- Modify: `webhook-handler/handlers/commands.py` — `_handle_aiuibuilder`, `action == "list"` branch (~line 1429-1441)
- Test: `webhook-handler/tests/test_commands_panel_menu.py`

- [ ] **Step 1: Write failing test**

Add to `test_commands_panel_menu.py`:

```python
class FakeTasksList(FakeTasks):
    def __init__(self, projects):
        super().__init__()
        self._projects = projects
    async def list_projects(self, email):
        return self._projects


async def test_list_attaches_dropdown_when_projects_exist():
    tasks = FakeTasksList([
        {"slug": "shop", "name": "Shop", "role": "owner", "public_url": "https://x"},
    ])
    ctx, sent = _ctx()
    ctx.arguments = "list"
    await _router(tasks).._handle_aiuibuilder(ctx)  # see note below
    assert len(sent["comp"]) == 1
    reply, components = sent["comp"][0]
    assert "Your apps" in reply
    select = components[0]["components"][0]
    assert select["custom_id"] == "aiuibuild:appselect"


async def test_list_empty_no_dropdown():
    ctx, sent = _ctx()
    ctx.arguments = "list"
    await _router(FakeTasksList([]))._handle_aiuibuilder(ctx)
    assert sent["comp"] == []
    assert any("no projects yet" in m for m in sent["text"])
```

> Note: fix the stray `..` typo when authoring — call `await _router(tasks)._handle_aiuibuilder(ctx)`.

- [ ] **Step 2: Run — verify fail**

Expected: `test_list_attaches_dropdown_when_projects_exist` FAILS (no `comp` recorded — current code calls `ctx.respond`, not `respond_components`). `test_list_empty_no_dropdown` should already pass.

- [ ] **Step 3: Implement** — change the `list` branch tail (the part after `reply` is built):

```python
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
                if ctx.respond_components is not None:
                    await ctx.respond_components(reply, build_apps_select_components(projects))
                else:
                    await ctx.respond(reply)
```

- [ ] **Step 4: Push + run tests — verify pass**

Expected: both new tests pass; full `test_commands_panel_menu.py` green.

- [ ] **Step 5: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/commands.py webhook-handler/tests/test_commands_panel_menu.py && git commit -m 'feat(app-builder): attach apps dropdown to /aiuibuilder list'"
```

---

## Task 6: Discord interaction routing (select + status)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` — imports (~line 8-23); `_handle_application_command` (set `respond_components`, ~line 100-124); `_handle_message_component` (new branches, ~line 146-168); add `_handle_app_select_component`, `_handle_status_component`.
- Test: `webhook-handler/tests/test_discord_commands_appselect.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_discord_commands_appselect.py
import asyncio
from handlers.discord_commands import DiscordCommandHandler, DEFERRED_CHANNEL_MESSAGE, DEFERRED_UPDATE_MESSAGE


class FakeDiscord:
    async def edit_original(self, **kwargs): pass
    async def post_channel_message(self, *a, **k): pass


class FakeRouter:
    def __init__(self):
        self.calls = []
    async def run_panel_menu(self, ctx, slug): self.calls.append(("menu", slug))
    async def run_panel_status(self, ctx, slug): self.calls.append(("status", slug))


def _component_payload(custom_id, *, component_type=2, values=None):
    data = {"custom_id": custom_id, "component_type": component_type}
    if values is not None:
        data["values"] = values
    return {"type": 3, "data": data, "token": "tok", "channel_id": "c1",
            "member": {"user": {"id": "u1", "username": "ralph"}}}


async def test_select_returns_ephemeral_and_schedules_menu():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(
        _component_payload("aiuibuild:appselect", component_type=3, values=["shop"]))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
    await asyncio.sleep(0)
    assert ("menu", "shop") in router.calls


async def test_status_button_schedules_status():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(_component_payload("aiuibuild:status:shop"))
    assert resp == {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
    await asyncio.sleep(0)
    assert ("status", "shop") in router.calls


async def test_select_empty_values_is_noop():
    router = FakeRouter()
    h = DiscordCommandHandler(FakeDiscord(), router)
    resp = await h.handle_interaction(
        _component_payload("aiuibuild:appselect", component_type=3, values=[]))
    assert resp == {"type": DEFERRED_UPDATE_MESSAGE}
    await asyncio.sleep(0)
    assert router.calls == []
```

- [ ] **Step 2: Run — verify fail**

Run: `$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/test_discord_commands_appselect.py -v"`
Expected: FAIL — select id falls through to the no-op path (`DEFERRED_UPDATE_MESSAGE`), so `router.calls` stays empty.

- [ ] **Step 3a: Import the 3 helpers** — extend the `from handlers.app_builder_panel import (...)` block:

```python
    is_app_select,
    is_status_button, slug_from_status_button,
```

- [ ] **Step 3b: Set `respond_components` in `_handle_application_command`**

Right after the existing `async def respond(msg)` closure (~line 100-104), add:

```python
        async def respond_components(msg: str, components: list) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components,
            )
```

and pass `respond_components=respond_components` into the `CommandContext(...)` constructor (~line 108).

- [ ] **Step 3c: Add the two branches in `_handle_message_component`**

Just before the `if not is_panel_button(custom_id):` fallthrough (~line 163), add:

```python
        if is_app_select(custom_id):
            return await self._handle_app_select_component(payload)
        if is_status_button(custom_id):
            try:
                slug = slug_from_status_button(custom_id)
            except ValueError:
                logger.info(f"Ignoring malformed status custom_id: {custom_id}")
                return {"type": DEFERRED_UPDATE_MESSAGE}
            return await self._handle_panel_route(
                payload, lambda ctx: self.router.run_panel_status(ctx, slug))
```

- [ ] **Step 3d: Add `_handle_app_select_component` + a shared `_handle_panel_route` helper**

Add these methods to the class (mirrors `_handle_publish_component`):

```python
    async def _handle_app_select_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A dropdown selection from the 'Your apps' list → ephemeral per-project
        menu. Routes run_panel_menu in the background, ACK ephemeral-deferred."""
        data = payload.get("data", {})
        values = data.get("values") or []
        if not values:
            logger.info("Ignoring app-select with no values")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        slug = values[0]
        return await self._handle_panel_route(
            payload, lambda ctx: self.router.run_panel_menu(ctx, slug))

    async def _handle_panel_route(
        self, payload: dict[str, Any], run: Callable[[Any], Awaitable[None]],
    ) -> dict[str, Any]:
        """Build an ephemeral CommandContext from a component interaction, schedule
        `run(ctx)` in the background, and ACK ephemeral-deferred (flags=64)."""
        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        channel_id = payload.get("channel_id", "")

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        async def respond_components(msg: str, components: list) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg, components=components,
            )

        ctx = CommandContext(
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            channel_id=channel_id,
            raw_text="aiuibuilder menu",
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            respond_components=respond_components,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
        )
        asyncio.create_task(run(ctx))
        return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```

> `Callable`/`Awaitable` are already imported at the top of `discord_commands.py`.

- [ ] **Step 4: Push + run tests — verify pass**

Run the test file. Expected: 3 passed.

- [ ] **Step 5: Run the FULL suite — nothing regressed**

Run: `$SSH "docker run --rm -v $VPS_WH:/app -w /app $IMG python -m pytest tests/ -v"`
Expected: all tests across all 3 test files pass.

- [ ] **Step 6: Commit**

```bash
$SSH "cd /root/proxy-server && git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_discord_commands_appselect.py && git commit -m 'feat(app-builder): route app-select dropdown + status button'"
```

---

## Task 7: Deploy + manual verification in Discord

**Files:** none (deploy only).

- [ ] **Step 1: Deploy the 3 source files into the live container + restart**

```bash
$SSH "cd /root/proxy-server && for f in handlers/app_builder_panel.py handlers/commands.py handlers/discord_commands.py; do docker cp webhook-handler/\$f webhook-handler:/app/\$f; done && docker restart webhook-handler"
```

- [ ] **Step 2: Confirm the container came back healthy**

Run: `$SSH "docker ps --format '{{.Names}}\t{{.Status}}' | grep webhook-handler"`
Expected: `Up ... (healthy)` within ~30s. If unhealthy, check `$SSH "docker logs --tail 50 webhook-handler"` for an import error and fix before proceeding.

- [ ] **Step 3: Manual Discord verification** (ask the user to do this, or do it if you have Discord access)

In `#app-builder`:
1. Run `/aiui aiuibuilder list` → the text list now has a **"Select an app to manage…"** dropdown.
2. Pick an app → an **ephemeral** message appears (only you see it) with the header and the state-aware buttons (`Enhance` / `Publish`|`Unpublish` / `Open …` / `Status`).
3. Click **Status** → the status text appears.
4. Click **Enhance**/**Publish**/**Unpublish** → behaves exactly as from a build message (these reuse the existing handlers).

- [ ] **Step 4: Final confirmation commit is already done** (Tasks 0-6 each committed). Verify the branch:

```bash
$SSH "cd /root/proxy-server && git log --oneline -8 && git status --short webhook-handler/handlers webhook-handler/tests webhook-handler/pytest.ini"
```
Expected: the feature commits present; no uncommitted changes left under `webhook-handler/handlers`, `webhook-handler/tests`, or `pytest.ini` (other unrelated VPS changes may still be dirty — leave them).

---

## Follow-ups (out of scope, surface to user)
- Push these commits + the surrounding 19 app-build commits from the VPS to GitHub, and pull to local, so the App Builder feature is no longer VPS-only (see the 2026-05-22 sync note).
- A proper image rebuild (`docker compose build webhook-handler`) on next deploy so the changes survive container recreation (the `docker cp` only persists across `restart`, not `up --build`).
