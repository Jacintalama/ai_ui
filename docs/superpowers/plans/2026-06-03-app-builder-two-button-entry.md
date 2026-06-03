# App Builder Two-Button Entry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the App Builder channel panel's template dropdown + Blank with two intent buttons — **🚀 Build an app** and **📂 My apps** — that move all interaction into the user's private space (Slack DM / Discord private thread), on both platforms.

**Architecture:** The pinned panel becomes a 2-button launcher. Clicking a button opens the user's private space and posts the relevant existing UI there: *Build an app* posts the existing template picker (dropdown + Blank); *My apps* posts the existing apps list. All downstream flows (template-select → modal → build; app actions) are unchanged — they just now originate in the private space. Discord uses its existing private-thread primitive (the `_handle_sched_open` pattern); Slack uses `open_dm` with the existing ephemeral fallback.

**Tech Stack:** Python (webhook-handler), pytest, Discord interactions API, Slack Block Kit / Web API.

**Spec:** `docs/superpowers/specs/2026-06-03-app-builder-two-button-entry-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `webhook-handler/handlers/app_builder_panel.py` | Discord component builders | Add `build_entry_components()` (2 buttons) + ids `PANEL_NEW_ID`/`PANEL_MYAPPS_ID`; extract `build_template_picker_components(templates)` from current `build_panel_payload`; `build_panel_payload` now returns the 2-button entry. |
| `webhook-handler/handlers/slack_app_builder_panel.py` | Slack Block Kit builders | Add 2-button entry blocks + ids; extract `build_template_picker_blocks(templates)`; `build_panel_blocks` now returns the 2-button entry. |
| `webhook-handler/handlers/discord_commands.py` | Discord interaction routing | Dispatch `PANEL_NEW_ID`→`_handle_build_new`, `PANEL_MYAPPS_ID`→`_handle_my_apps`. Both mirror `_handle_sched_open` (create/get private thread, post UI, ephemeral pointer). |
| `webhook-handler/handlers/slack_interactions.py` | Slack interaction routing | In `_handle_block_actions`, branch `PANEL_NEW_ID`→open DM + post picker; `PANEL_MYAPPS_ID`→resolve email + `list_projects` + open DM + post `build_apps_list_blocks`. Ephemeral fallback via existing helpers. |
| `webhook-handler/tests/test_app_builder_panel.py` | Discord builder tests | Add entry-panel + picker-extraction tests. |
| `webhook-handler/tests/test_slack_panel.py` | Slack builder tests | Add entry-panel + picker-extraction tests. |
| `webhook-handler/tests/test_two_button_entry.py` (new) | Handler routing tests (both platforms) | New behavior: button → private space + correct UI; empty apps; fallback. |

**Reference patterns to mirror (read before coding):**
- Discord thread + ephemeral pointer: `discord_commands.py:863` `_handle_sched_open` (uses `get_user_thread`/`create_private_thread`/`add_thread_member`/`post_channel_message`/`edit_original`, returns `DEFERRED_CHANNEL_MESSAGE` + `flags:64`).
- Discord apps dropdown: `app_builder_panel.py:288` `build_apps_select_components(projects)`.
- Slack DM + fallback: `slack_interactions.py:137` `_dm_context`, `:122` `_bail_if_not_linked`, `clients/slack.py:165` `open_dm`, `post_ephemeral`.
- Slack apps list: `slack_app_builder_panel.py:287` `build_apps_list_blocks`.
- Apps data source: `clients/tasks.py:176` `list_projects(email)`; templates: `list_templates(email)`.

---

## Task 1: Discord — split panel into 2-button entry + extracted picker

**Files:**
- Modify: `webhook-handler/handlers/app_builder_panel.py` (constants block ~33; `build_panel_payload` ~54-81)
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_app_builder_panel.py
from handlers.app_builder_panel import (
    build_panel_payload, build_template_picker_components,
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ID, TEMPLATE_PREFIX,
    is_panel_new, is_panel_myapps, ACTION_ROW, BUTTON, SELECT_MENU,
)

TEMPLATES = [{"key": "portfolio", "label": "Portfolio", "emoji": "🎨", "description": "A personal site"}]

def test_entry_panel_has_two_buttons():
    payload = build_panel_payload(TEMPLATES)
    buttons = [c for row in payload["components"] for c in row["components"] if c["type"] == BUTTON]
    ids = {b["custom_id"] for b in buttons}
    assert ids == {PANEL_NEW_ID, PANEL_MYAPPS_ID}
    # entry panel must NOT embed the template dropdown anymore
    assert not any(c["type"] == SELECT_MENU for row in payload["components"] for c in row["components"])

def test_template_picker_has_dropdown_and_blank():
    comps = build_template_picker_components(TEMPLATES)
    flat = [c for row in comps for c in row["components"]]
    assert any(c["type"] == SELECT_MENU and c["custom_id"] == TEMPLATE_SELECT_ID for c in flat)
    assert any(c["type"] == BUTTON and c["custom_id"] == TEMPLATE_PREFIX for c in flat)  # Blank

def test_panel_id_predicates():
    assert is_panel_new(PANEL_NEW_ID) and not is_panel_new("x")
    assert is_panel_myapps(PANEL_MYAPPS_ID) and not is_panel_myapps("x")
```

- [ ] **Step 2: Run, verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_app_builder_panel.py -k "entry_panel or template_picker or panel_id" -q`
Expected: FAIL — `ImportError` (`build_template_picker_components`, `PANEL_NEW_ID`, … not defined).

- [ ] **Step 3: Implement**

In the custom_id schemes block (after `TEMPLATE_SELECT_ID`):
```python
PANEL_NEW_ID = "aiuibuild:new"        # entry button -> open private space + template picker
PANEL_MYAPPS_ID = "aiuibuild:myapps"  # entry button -> open private space + apps list
```
Rename the body of the current `build_panel_payload` into a new picker builder, and make `build_panel_payload` return the 2-button entry:
```python
def build_template_picker_components(templates: list[dict]) -> list[dict]:
    """The template dropdown + Blank button, posted into the private space."""
    options: list[dict] = []
    for t in templates[:_MAX_SELECT_OPTIONS]:
        key = t.get("key")
        if not key:
            continue
        emoji = (t.get("emoji") or "").strip()
        label = f"{emoji} {t.get('label', key)}".strip()
        opt = {"label": label[:100], "value": key[:100]}
        desc = (t.get("description") or "").strip()
        if desc:
            opt["description"] = desc[:100]
        options.append(opt)
    select = {
        "type": SELECT_MENU, "custom_id": TEMPLATE_SELECT_ID,
        "placeholder": "Pick a template…", "min_values": 1, "max_values": 1,
        "options": options,
    }
    blank = _button("⬜ Blank", TEMPLATE_PREFIX, STYLE_SECONDARY)
    return [
        {"type": ACTION_ROW, "components": [select]},
        {"type": ACTION_ROW, "components": [blank]},
    ]


def build_panel_payload(templates: list[dict]) -> dict:
    """Pinned entry panel: two intent buttons. The template picker and apps
    list now open in the user's private space (Slack DM / Discord thread)."""
    return {"content": PANEL_CONTENT, "components": [
        {"type": ACTION_ROW, "components": [
            _button("🚀 Build an app", PANEL_NEW_ID, STYLE_SUCCESS),
            _button("📂 My apps", PANEL_MYAPPS_ID, STYLE_PRIMARY),
        ]},
    ]}


def is_panel_new(custom_id: str) -> bool:
    return custom_id == PANEL_NEW_ID


def is_panel_myapps(custom_id: str) -> bool:
    return custom_id == PANEL_MYAPPS_ID
```
Update `PANEL_CONTENT` to drop the "Pick a template" wording, e.g.:
```python
PANEL_CONTENT = (
    "\U0001f680 **AIUI App Builder**\n"
    "**🚀 Build an app** opens a private space just for you to build, preview, "
    "and publish. **📂 My apps** opens the ones you've already built."
)
```

- [ ] **Step 4: Run, verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_app_builder_panel.py -q`
Expected: PASS (including pre-existing tests; fix any that asserted the old dropdown-in-panel shape by pointing them at `build_template_picker_components`).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py
git commit -m "feat(discord): 2-button App Builder entry panel + extract template picker"
```

---

## Task 2: Discord — `_handle_build_new` (post template picker into private thread)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py` (imports ~27-61; dispatch ~289-296; add handler near `_handle_sched_open` ~863)
- Test: `webhook-handler/tests/test_two_button_entry.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/test_two_button_entry.py  (Discord section)
import asyncio, pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import PANEL_NEW_ID, TEMPLATE_SELECT_ID

def _payload(custom_id, user_id="U1"):
    return {"type": 3, "data": {"custom_id": custom_id},
            "member": {"user": {"id": user_id, "username": "maya"}},
            "channel_id": "C1", "token": "tok"}

@pytest.mark.asyncio
async def test_build_new_posts_template_picker_to_thread():
    discord = MagicMock()
    discord.create_private_thread = AsyncMock(return_value="THREAD1")
    discord.add_thread_member = AsyncMock()
    discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value=None)
    router.set_user_thread = AsyncMock()
    router._resolve_email_auto = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[{"key": "portfolio", "label": "Portfolio"}])
    h = DiscordCommandHandler(discord, router)
    resp = await h.handle_interaction(_payload(PANEL_NEW_ID))
    await asyncio.sleep(0)
    # posted a message containing the template select into the thread
    args = discord.post_channel_message.await_args
    assert args.args[0] == "THREAD1"
    comps = args.kwargs.get("components") or (args.args[2] if len(args.args) > 2 else [])
    flat = [c for row in comps for c in row["components"]]
    assert any(c.get("custom_id") == TEMPLATE_SELECT_ID for c in flat)
```

> VERIFIED method names (reviewer-checked): templates come from `self.router._tasks_client.list_templates(email)` — there is NO `router.list_templates`. The template catalog is generic, so the synthetic email from `_resolve_email_auto(user_id)` is fine here (not-linked is enforced later at build time, as today). Mirror `_handle_sched_open` (discord_commands.py:863) for the exact deferral/threading calls.

- [ ] **Step 2: Run, verify failure**

Run: `cd webhook-handler && python -m pytest tests/test_two_button_entry.py -k build_new -q`
Expected: FAIL — handler routes `PANEL_NEW_ID` to the old path (opens modal) or no-ops; `post_channel_message` not called with the picker.

- [ ] **Step 3: Implement**

Add import: `build_template_picker_components, is_panel_new, is_panel_myapps` from `app_builder_panel`.
In the component dispatch (before the final `is_panel_button` fallback, near line 289):
```python
if is_panel_new(custom_id):
    return await self._handle_build_new(payload)
if is_panel_myapps(custom_id):
    return await self._handle_my_apps(payload)
```
Add handler mirroring `_handle_sched_open` (open/create the user's private thread, post the picker, point them to it):
```python
async def _handle_build_new(self, payload: dict[str, Any]) -> dict[str, Any]:
    member = payload.get("member", {})
    user = member.get("user", payload.get("user", {}))
    user_id = user.get("id", "")
    user_name = user.get("username", "unknown")
    channel_id = payload.get("channel_id", "")
    interaction_token = payload.get("token", "")

    async def _do() -> None:
        try:
            email = await self.router._resolve_email_auto(user_id)  # synthetic ok; catalog is generic
            templates = await self.router._tasks_client.list_templates(email)
            thread_id = await self._get_or_make_thread(user_id, channel_id, user_name)
            if thread_id:
                await self.discord.post_channel_message(
                    thread_id, "Pick a template — or **Blank** to start from scratch:",
                    components=build_template_picker_components(templates))
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content=f"🚀 Your builder is ready in <#{thread_id}>")
            else:
                await self.discord.edit_original(
                    interaction_token=interaction_token,
                    content="Pick a template — or **Blank**:",
                    components=build_template_picker_components(templates))
        except Exception as exc:  # noqa: BLE001
            logger.error("_handle_build_new failed user=%s: %s", user_id, exc)
            await self.discord.edit_original(
                interaction_token=interaction_token,
                content="Couldn't open the builder — please try again.")

    asyncio.create_task(_do())
    return {"type": DEFERRED_CHANNEL_MESSAGE, "data": {"flags": 64}}
```
Extract the thread get-or-create used by `_handle_sched_open` into a shared helper `_get_or_make_thread(user_id, channel_id, user_name)` (returns thread_id or None) and reuse it in both handlers (DRY).

- [ ] **Step 4: Run, verify pass**

Run: `cd webhook-handler && python -m pytest tests/test_two_button_entry.py -k build_new -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_two_button_entry.py
git commit -m "feat(discord): Build an app button -> template picker in private thread"
```

---

## Task 3: Discord — `_handle_my_apps` (post apps dropdown into private thread)

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py`
- Test: `webhook-handler/tests/test_two_button_entry.py`

- [ ] **Step 1: Write failing tests** (apps present → dropdown in thread; no apps → empty-state text)

```python
@pytest.mark.asyncio
async def test_my_apps_posts_apps_dropdown_to_thread():
    discord = MagicMock(); discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(); discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value="T1"); router.set_user_thread = AsyncMock()
    router._resolve_email = AsyncMock(return_value="maya@x.com")  # REAL email (None = not linked)
    router._tasks_client = MagicMock()
    router._tasks_client.list_projects = AsyncMock(return_value=[{"slug": "shop-1", "name": "Shop"}])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload("aiuibuild:myapps")); await asyncio.sleep(0)
    assert discord.post_channel_message.await_args.args[0] == "T1"

@pytest.mark.asyncio
async def test_my_apps_empty_state():
    discord = MagicMock(); discord.create_private_thread = AsyncMock(return_value="T1")
    discord.add_thread_member = AsyncMock(); discord.post_channel_message = AsyncMock()
    discord.edit_original = AsyncMock()
    router = MagicMock()
    router.get_user_thread = AsyncMock(return_value="T1"); router.set_user_thread = AsyncMock()
    router._resolve_email = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    h = DiscordCommandHandler(discord, router)
    await h.handle_interaction(_payload("aiuibuild:myapps")); await asyncio.sleep(0)
    posted = " ".join(str(c.args) for c in discord.post_channel_message.await_args_list)
    assert "No apps yet" in posted
```

> VERIFIED (reviewer-checked): use `self.router._resolve_email(user_id)` (or `_resolve_email_for_ctx`) which returns **None when not linked** — do NOT use `_resolve_email_auto` here (it returns a synthetic email and can never express "not linked"). Apps come from `self.router._tasks_client.list_projects(email)` — there is NO `router.list_projects`.

- [ ] **Step 2: Run, verify failure** — `pytest tests/test_two_button_entry.py -k my_apps -q` → FAIL.

- [ ] **Step 3: Implement** `_handle_my_apps`: `email = await self.router._resolve_email(user_id)`; if `email is None` → `edit_original` with the existing not-linked text (`self.router._not_linked_text(...)` / `_not_linked_msg()`); else `projects = await self.router._tasks_client.list_projects(email)` → get/make thread → when projects: `post_channel_message(thread, "Your apps:", components=build_apps_select_components(projects))`; when empty: `post_channel_message(thread, "📂 No apps yet — hit 🚀 Build an app")` (custom text, since `build_apps_select_components([])` would be an empty select) → `edit_original` pointer. Reuse `_get_or_make_thread`.

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_two_button_entry.py -k my_apps -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(discord): My apps button -> apps list in private thread"
```

---

## Task 4: Slack — 2-button entry panel + extracted picker

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py` (`build_panel_blocks` ~107-140; constants ~14-21)
- Test: `webhook-handler/tests/test_slack_panel.py`

- [ ] **Step 1: Write failing tests** (entry blocks have two buttons with `aiuibuild:new`/`aiuibuild:myapps`; new `build_template_picker_blocks` has the static_select + Blank).

```python
from handlers.slack_app_builder_panel import (
    build_panel_blocks, build_template_picker_blocks,
    PANEL_NEW_ID, PANEL_MYAPPS_ID, TEMPLATE_SELECT_ACTION_ID,
)
T = [{"key": "portfolio", "label": "Portfolio"}]

def test_slack_entry_panel_two_buttons():
    blocks = build_panel_blocks(T)
    ids = {e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]}
    assert {PANEL_NEW_ID, PANEL_MYAPPS_ID} <= ids
    # no static_select in the pinned entry panel
    assert not any(e.get("type") == "static_select"
                   for b in blocks if b["type"] == "actions" for e in b["elements"])

def test_slack_template_picker_blocks_have_select():
    blocks = build_template_picker_blocks(T)
    assert any(e.get("action_id") == TEMPLATE_SELECT_ACTION_ID
               for b in blocks if b["type"] in ("actions", "section")
               for e in (b.get("elements") or []))
```

- [ ] **Step 2: Run, verify failure** — `pytest tests/test_slack_panel.py -k "entry_panel or picker_blocks" -q` → FAIL (ImportError).

- [ ] **Step 3: Implement** — add `PANEL_NEW_ID = "aiuibuild:new"`, `PANEL_MYAPPS_ID = "aiuibuild:myapps"`; move the current dropdown+Blank block-building into `build_template_picker_blocks(templates)`; `build_panel_blocks` returns header + an `actions` block with two `_button` elements (`🚀 Build an app`→PANEL_NEW_ID, `📂 My apps`→PANEL_MYAPPS_ID). Update `PANEL_CONTENT`/header text to drop "Pick a template".

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_slack_panel.py -q` (fix pre-existing tests that asserted the dropdown-in-panel shape → point at `build_template_picker_blocks`).

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(slack): 2-button App Builder entry panel + extract template picker"
```

---

## Task 5: Slack — `new` handler (open DM + post template picker)

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_handle_block_actions` ~59-104; imports ~29)
- Test: `webhook-handler/tests/test_two_button_entry.py`

- [ ] **Step 1: Write failing test**

```python
# Slack section of tests/test_two_button_entry.py
from handlers.slack_interactions import SlackInteractionsHandler
from handlers.slack_app_builder_panel import PANEL_NEW_ID, TEMPLATE_SELECT_ACTION_ID

def _slack_action(action_id, user="U1", channel="C-app"):
    return {"type": "block_actions", "user": {"id": user, "username": "maya"},
            "trigger_id": "t", "channel": {"id": channel},
            "actions": [{"action_id": action_id}]}

@pytest.mark.asyncio
async def test_slack_build_new_posts_picker_to_dm():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D1"); slack.post_message = AsyncMock()
    slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock()
    router._tasks_client.list_templates = AsyncMock(return_value=[{"key": "portfolio", "label": "P"}])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action(PANEL_NEW_ID)); await asyncio.sleep(0)
    slack.open_dm.assert_awaited_once_with("U1")
    # picker blocks posted to the DM
    posted = slack.post_message.await_args
    assert posted.kwargs.get("channel") == "D1"
```

- [ ] **Step 2: Run, verify failure** — FAIL (action_id falls through to "unknown action").

- [ ] **Step 3: Implement** — in `_handle_block_actions`, before the unknown-action log:
```python
if action_id == PANEL_NEW_ID:
    user_id = (payload.get("user") or {}).get("id", "")
    origin = (payload.get("channel") or {}).get("id", "")
    async def _do():
        email = await self.router._resolve_email_for_ctx(self._slack_ctx(user_id))  # synthetic-free; catalog generic, "" ok
        templates = await self.router._tasks_client.list_templates(email or "")
        dm = await self.slack.open_dm(user_id)
        blocks = build_template_picker_blocks(templates)
        if dm:
            await self.slack.post_message(channel=dm, text="Pick a template", blocks=blocks)
            await self.slack.post_ephemeral(origin, user_id, "📩 Sent to your DM.")
        elif origin:
            await self.slack.post_ephemeral(origin, user_id, "Pick a template", blocks=blocks)
    task = asyncio.create_task(_do()); self.router._background_tasks.add(task)
    task.add_done_callback(self.router._background_tasks.discard)
    return {}
```
Import `PANEL_NEW_ID, PANEL_MYAPPS_ID, build_template_picker_blocks`. Confirm `post_message`/`post_ephemeral` accept `blocks=` (they do in this codebase — see `notify_channel_rich`).

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(slack): Build an app button -> template picker in DM"
```

---

## Task 6: Slack — `myapps` handler (open DM + post apps list)

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py`
- Test: `webhook-handler/tests/test_two_button_entry.py`

- [ ] **Step 1: Write failing tests** (apps present → `build_apps_list_blocks` posted to DM; empty → empty-state text; not-linked → existing not-linked path).

```python
@pytest.mark.asyncio
async def test_slack_my_apps_posts_list_to_dm():
    slack = MagicMock(); slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock(); slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(
        return_value=[{"slug": "shop", "name": "Shop"}])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action("aiuibuild:myapps")); await asyncio.sleep(0)
    assert slack.post_message.await_args.kwargs.get("channel") == "D1"

@pytest.mark.asyncio
async def test_slack_my_apps_empty_state():
    slack = MagicMock(); slack.open_dm = AsyncMock(return_value="D1")
    slack.post_message = AsyncMock(); slack.post_ephemeral = AsyncMock()
    router = MagicMock()
    router._resolve_email_for_ctx = AsyncMock(return_value="maya@x.com")
    router._tasks_client = MagicMock(); router._tasks_client.list_projects = AsyncMock(return_value=[])
    router._background_tasks = set()
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_slack_action("aiuibuild:myapps")); await asyncio.sleep(0)
    txt = " ".join(str(c.kwargs) for c in slack.post_message.await_args_list)
    assert "No apps yet" in txt
```

> VERIFIED (reviewer-checked): mirror the existing `_render_list` at `slack_commands.py:73-105` almost verbatim — it already does resolve-email → `_tasks_client.list_projects(email)` → `build_apps_list_blocks(apps)` with not-linked + fetch-error branches. The ONLY change is the destination: post to the DM (`open_dm` + `post_message(blocks=)`) instead of `post_to_response_url`. Use `_bail_if_not_linked(user_id)` for the not-linked path.

- [ ] **Step 2: Run, verify failure** — FAIL.

- [ ] **Step 3: Implement** `PANEL_MYAPPS_ID` branch (background task; add it to `self.router._background_tasks`): `email = await self._bail_if_not_linked(user_id)` (returns None + posts not-linked DM when unlinked → return); else `projects = await self.router._tasks_client.list_projects(email)` → `dm = await self.slack.open_dm(user_id)` → when projects: `post_message(channel=dm, text="Your apps", blocks=build_apps_list_blocks(projects))`; when empty: `post_message(channel=dm, text="📂 No apps yet — hit 🚀 Build an app")` (custom text, not the builder's default) → ephemeral "📩 Sent to your DM" in origin. If `open_dm` is None → `post_ephemeral(origin, user_id, …, blocks=…)` fallback.

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(slack): My apps button -> apps list in DM"
```

---

## Task 7: Full-suite regression + panel re-pin note

**Files:**
- Test: entire `webhook-handler/tests/`

- [ ] **Step 1: Run the full suite**

Run: `cd webhook-handler && python -m pytest tests/ -q`
Expected: all PASS. Fix any pre-existing panel tests that still assert the old dropdown-in-pinned-panel shape (repoint to the picker builders).

- [ ] **Step 2: Sanity-check the live panels need re-pinning**

The pinned message is produced by `build_panel_payload`/`build_panel_blocks`. After deploy, the existing pinned panels must be re-posted/re-pinned (via the setup scripts `scripts/setup_app_builder_channel.py` / `setup_slack_app_builder_channel.py`) so users see the 2 buttons. Document this in the deploy step — no code change here.

- [ ] **Step 3: Commit (if any test fixes)**

```bash
git commit -am "test: align App Builder panel tests with 2-button entry"
```

---

## Deploy notes (after merge)
- Deploy `webhook-handler` (the panel builders + handlers live there).
- **Re-pin the entry panel** on both Slack `#app-builder` and Discord via the setup scripts so the live pinned message shows the 2 buttons (old pinned dropdown won't auto-update).
- Slack private-DM builds still require the `im:write` scope (tracked separately).
