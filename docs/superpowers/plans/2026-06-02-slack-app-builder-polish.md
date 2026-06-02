# Slack App Builder Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Slack App Builder to full Discord parity — a template dropdown, a private per-user DM build space, and interactive Publish/Enhance/Unpublish/Status cards — reusing the shared `CommandRouter`/`TasksClient` logic and adding only a Slack Block Kit presentation + routing layer.

**Architecture:** Approach A from the spec. Business logic (`run_panel_build`, `run_panel_enhance`, `TasksClient`, `_resolve_email_for_ctx`) is reused unchanged. New code is confined to `clients/slack.py` (transport), `handlers/slack_app_builder_panel.py` (pure Block Kit builders + id parsers), `handlers/slack_interactions.py` (routing + DM build flow), and `handlers/slack_commands.py` (the `list` slash rendering). **No Discord handler or `commands.py` business logic changes.**

**Tech Stack:** Python 3.11 (container), FastAPI, httpx, Slack Web API + Block Kit, pytest + pytest-asyncio, unittest.mock (AsyncMock/MagicMock).

**Spec:** `docs/superpowers/specs/2026-06-02-slack-app-builder-polish-design.md`

**Conventions for every task:** run tests with `cd webhook-handler && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest <path> -v`. The full suite (`python -m pytest -q`, currently **390** passing) must stay green at the end of each task. Commit after each task. Plain-text labels only (no emoji/icons — user preference). Branch: `integrate-slack-pr4`.

---

## File Structure

- **`webhook-handler/clients/slack.py`** (modify) — transport only:
  - extend `post_message(channel, text, *, blocks=None, attachments=None, thread_ts=None)`
  - extend `post_to_response_url(..., blocks=None)`
  - add `open_dm(user_id) -> Optional[str]` (`conversations.open`)
  - add `post_ephemeral(channel, user, text, *, blocks=None) -> bool` (`chat.postEphemeral`)
- **`webhook-handler/handlers/slack_app_builder_panel.py`** (modify) — pure Block Kit, no I/O:
  - rewrite `build_panel_blocks` → `static_select` dropdown + Blank button
  - add card builders: `build_ready_attachment`, `build_published_attachment`, `build_apps_list_blocks`, `build_enhance_modal_view`, `enhance_text_from_view`
  - add prefixes + parsers: template select, publish, enhance (button + modal), unpublish, status
- **`webhook-handler/handlers/slack_interactions.py`** (modify) — routing + DM flow
- **`webhook-handler/handlers/slack_commands.py`** (modify) — `aiuibuilder list` Block Kit rendering
- **Tests** (modify/extend): `tests/test_slack_client_modal.py`, `tests/test_slack_panel.py`, `tests/test_slack_interactions.py`, `tests/test_slack_command_build_notify.py`

**Color constants** (module-level in `slack_app_builder_panel.py`): `COLOR_READY = "#36a64f"` (green), `COLOR_PUBLISHED = "#2eb67d"` (blue-green). Cards render as a single Slack *attachment* `{"color": ..., "blocks": [...]}` so the colored bar shows; interactive buttons inside attachment blocks remain clickable.

---

## Task 1: SlackClient.post_message supports blocks + attachments

**Files:**
- Modify: `webhook-handler/clients/slack.py` (`post_message`, ~lines 58-102)
- Test: `webhook-handler/tests/test_slack_client_modal.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_slack_client_modal.py
import respx, httpx, pytest
from clients.slack import SlackClient

@pytest.mark.asyncio
@respx.mock
async def test_post_message_includes_blocks_and_attachments():
    route = respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "ts": "1.2"}))
    c = SlackClient(bot_token="xoxb-t")
    ts = await c.post_message(channel="C1", text="hi",
                              blocks=[{"type": "section"}],
                              attachments=[{"color": "#36a64f", "blocks": []}])
    assert ts == "1.2"
    sent = route.calls.last.request
    import json
    body = json.loads(sent.content)
    assert body["blocks"] == [{"type": "section"}]
    assert body["attachments"][0]["color"] == "#36a64f"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webhook-handler && PYTHONUTF8=1 python -m pytest tests/test_slack_client_modal.py::test_post_message_includes_blocks_and_attachments -v`
Expected: FAIL (`post_message` has no `blocks`/`attachments` kwargs).

- [ ] **Step 3: Implement**

Change the signature and payload assembly:

```python
async def post_message(
    self,
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
    *,
    blocks: Optional[list] = None,
    attachments: Optional[list] = None,
) -> Optional[str]:
    url = f"{self.base_url}/chat.postMessage"
    headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"}
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks is not None:
        payload["blocks"] = blocks
    if attachments is not None:
        payload["attachments"] = attachments
    # ... unchanged httpx POST + ok/error handling ...
```

- [ ] **Step 4: Run test to verify it passes** — Expected: PASS. Also run existing `test_slack_command_build_notify.py` to confirm text-only callers still work.

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/slack.py webhook-handler/tests/test_slack_client_modal.py
git commit -m "feat(slack): post_message supports Block Kit blocks + attachments"
```

---

## Task 2: SlackClient.open_dm

**Files:**
- Modify: `webhook-handler/clients/slack.py` (new method after `open_modal`)
- Test: `webhook-handler/tests/test_slack_client_modal.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
@respx.mock
async def test_open_dm_returns_channel_id():
    respx.post("https://slack.com/api/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": True, "channel": {"id": "D123"}}))
    c = SlackClient(bot_token="xoxb-t")
    assert await c.open_dm("U1") == "D123"

@pytest.mark.asyncio
@respx.mock
async def test_open_dm_none_on_error():
    respx.post("https://slack.com/api/conversations.open").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "cannot_dm_bot"}))
    c = SlackClient(bot_token="xoxb-t")
    assert await c.open_dm("U1") is None
```

- [ ] **Step 2: Run, expect FAIL** (`open_dm` undefined).

- [ ] **Step 3: Implement**

```python
async def open_dm(self, user_id: str) -> Optional[str]:
    """Open (or fetch) the DM channel with a user via conversations.open.
    Requires the `im:write` scope. Returns the DM channel id, or None on
    failure. Never raises."""
    if not user_id:
        return None
    url = f"{self.base_url}/conversations.open"
    headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, json={"users": user_id}, headers=headers)
            data = r.json()
        if data.get("ok"):
            return data.get("channel", {}).get("id")
        logger.error(f"Slack conversations.open error: {data.get('error')}")
        return None
    except Exception as e:
        logger.error(f"Error opening Slack DM: {e}")
        return None
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): open_dm (conversations.open) for private build spaces`

---

## Task 3: SlackClient.post_ephemeral + post_to_response_url blocks

**Files:**
- Modify: `webhook-handler/clients/slack.py`
- Test: `webhook-handler/tests/test_slack_client_modal.py`

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
@respx.mock
async def test_post_ephemeral_posts_to_channel_for_user():
    route = respx.post("https://slack.com/api/chat.postEphemeral").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    c = SlackClient(bot_token="xoxb-t")
    assert await c.post_ephemeral("C1", "U1", "only you") is True
    import json; body = json.loads(route.calls.last.request.content)
    assert body["channel"] == "C1" and body["user"] == "U1"

@pytest.mark.asyncio
@respx.mock
async def test_response_url_includes_blocks():
    route = respx.post("https://hooks.slack.com/x").mock(return_value=httpx.Response(200, text="ok"))
    c = SlackClient(bot_token="xoxb-t")
    await c.post_to_response_url("https://hooks.slack.com/x", "apps", blocks=[{"type": "section"}])
    import json; body = json.loads(route.calls.last.request.content)
    assert body["blocks"] == [{"type": "section"}]
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — add `post_ephemeral`:

```python
async def post_ephemeral(self, channel: str, user: str, text: str, *, blocks: Optional[list] = None) -> bool:
    url = f"{self.base_url}/chat.postEphemeral"
    headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"}
    payload = {"channel": channel, "user": user, "text": text}
    if blocks is not None:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            data = (await client.post(url, json=payload, headers=headers)).json()
        if not data.get("ok"):
            logger.error(f"Slack chat.postEphemeral error: {data.get('error')}")
        return bool(data.get("ok"))
    except Exception as e:
        logger.error(f"Error posting ephemeral: {e}")
        return False
```

and add `blocks` to `post_to_response_url` (include `payload["blocks"] = blocks` when not None).

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): post_ephemeral + blocks on response_url`

---

## Task 4: Panel dropdown (replace button grid)

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py` (`build_panel_blocks`, `PANEL_TEXT`, constants)
- Test: `webhook-handler/tests/test_slack_panel.py`

- [ ] **Step 1: Failing test**

```python
from handlers.slack_app_builder_panel import (
    build_panel_blocks, TEMPLATE_SELECT_ACTION_ID, BLANK_ACTION_ID, TEMPLATE_PREFIX)

def test_panel_is_dropdown_with_all_templates_and_blank():
    tpls = [{"key": f"t{i}", "label": f"T{i}"} for i in range(30)]
    blocks = build_panel_blocks(tpls)
    selects = [e for b in blocks if b["type"] == "actions"
               for e in b["elements"] if e.get("type") == "static_select"]
    assert len(selects) == 1
    opts = selects[0]["options"]
    assert len(opts) == 30  # no truncation (static_select allows up to 100)
    assert selects[0]["action_id"] == TEMPLATE_SELECT_ACTION_ID
    assert all(o["value"].startswith(TEMPLATE_PREFIX) for o in opts)
    buttons = [e for b in blocks if b["type"] == "actions"
               for e in b["elements"] if e.get("type") == "button"]
    assert any(e["action_id"] == BLANK_ACTION_ID for e in buttons)
```

- [ ] **Step 2: Run, expect FAIL** (constants/dropdown not present). Note: the existing `test_slack_panel.py` button-grid tests will need updating — replace any assertion expecting per-template buttons with the dropdown assertions above (delete the obsolete grid test).

- [ ] **Step 3: Implement** — add constants and rewrite the builder:

```python
TEMPLATE_SELECT_ACTION_ID = "aiuibuild:tpl_select"
BLANK_ACTION_ID = TEMPLATE_PREFIX  # bare prefix == Blank
_SELECT_OPTION_MAX = 100
_OPT_TEXT_MAX = 75

PANEL_TEXT = (
    "*AIUI App Builder*\n"
    "Pick a template to start — a short form opens where you describe your app, "
    "and I'll build it in a private DM with you. Or choose Blank to start from scratch."
)

def build_panel_blocks(templates: list[dict]) -> list[dict]:
    """Header + a 'Pick a template' dropdown (one option per template) + a Blank
    button. static_select allows up to 100 options, so no template is dropped."""
    options = []
    for t in templates[:_SELECT_OPTION_MAX]:
        key = t.get("key")
        if not key:
            continue
        label = (t.get("label") or key)[:_OPT_TEXT_MAX]
        options.append({
            "text": {"type": "plain_text", "text": label},
            "value": f"{TEMPLATE_PREFIX}{key}",
        })
    select = {
        "type": "static_select",
        "action_id": TEMPLATE_SELECT_ACTION_ID,
        "placeholder": {"type": "plain_text", "text": "Pick a template…"},
        "options": options or [{"text": {"type": "plain_text", "text": "Blank"},
                                "value": TEMPLATE_PREFIX}],
    }
    blank = _button("Blank", BLANK_ACTION_ID)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": PANEL_TEXT}},
        {"type": "actions", "elements": [select, blank]},
    ]
```

Keep `_button`, `build_modal_view`, `description_from_view`, and the existing `is_panel_button`/`template_key_from_button`/`is_panel_modal`/`template_key_from_modal` (still used by Blank + modal). Remove the now-unused `_MAX_PER_ACTIONS_BLOCK`/`_MAX_BUTTONS` only if nothing references them.

- [ ] **Step 4: Run, expect PASS** (new test + updated existing panel tests).
- [ ] **Step 5: Commit** — `feat(slack): template dropdown panel (replaces button grid)`

---

## Task 5: Management action_id prefixes + parsers

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py`
- Test: `webhook-handler/tests/test_slack_panel.py`

- [ ] **Step 1: Failing test**

```python
from handlers.slack_app_builder_panel import (
    PUBLISH_PREFIX, ENHANCE_PREFIX, ENHANCE_MODAL_PREFIX, UNPUBLISH_PREFIX, STATUS_PREFIX,
    slug_from_action, is_action, slug_from_enhance_modal, is_enhance_modal)

def test_management_parsers_roundtrip():
    for pref in (PUBLISH_PREFIX, ENHANCE_PREFIX, UNPUBLISH_PREFIX, STATUS_PREFIX):
        aid = f"{pref}my-slug"
        assert is_action(aid, pref) is True
        assert slug_from_action(aid, pref) == "my-slug"
    assert is_action("aiuibuild:tpl:x", PUBLISH_PREFIX) is False
    cb = f"{ENHANCE_MODAL_PREFIX}my-slug"
    assert is_enhance_modal(cb) and slug_from_enhance_modal(cb) == "my-slug"
    import pytest
    with pytest.raises(ValueError):
        slug_from_action("nope", PUBLISH_PREFIX)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**

```python
PUBLISH_PREFIX = "aiuibuild:publish:"
ENHANCE_PREFIX = "aiuibuild:enhance:"
ENHANCE_MODAL_PREFIX = "aiuibuild:enhmodal:"
UNPUBLISH_PREFIX = "aiuibuild:unpublish:"
STATUS_PREFIX = "aiuibuild:status:"

def is_action(action_id: str, prefix: str) -> bool:
    return bool(action_id) and action_id.startswith(prefix)

def slug_from_action(action_id: str, prefix: str) -> str:
    if not is_action(action_id, prefix):
        raise ValueError(f"not a {prefix!r} action_id: {action_id!r}")
    return action_id[len(prefix):]

def is_enhance_modal(callback_id: str) -> bool:
    return bool(callback_id) and callback_id.startswith(ENHANCE_MODAL_PREFIX)

def slug_from_enhance_modal(callback_id: str) -> str:
    if not is_enhance_modal(callback_id):
        raise ValueError(f"not an enhance modal callback_id: {callback_id!r}")
    return callback_id[len(ENHANCE_MODAL_PREFIX):]
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): App Builder management action_id parsers`

---

## Task 6: Build-ready + published card attachments

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py`
- Test: `webhook-handler/tests/test_slack_panel.py`

- [ ] **Step 1: Failing test**

```python
from handlers.slack_app_builder_panel import (
    build_ready_attachment, build_published_attachment,
    PUBLISH_PREFIX, ENHANCE_PREFIX, UNPUBLISH_PREFIX, COLOR_READY)

def _btns(attachment):
    return [e for b in attachment["blocks"] if b["type"] == "actions" for e in b["elements"]]

def test_build_ready_attachment_has_publish_enhance_preview():
    att = build_ready_attachment("my-app", "https://x/preview")
    assert att["color"] == COLOR_READY
    btns = _btns(att)
    assert any(b.get("action_id") == f"{PUBLISH_PREFIX}my-app" for b in btns)
    assert any(b.get("action_id") == f"{ENHANCE_PREFIX}my-app" for b in btns)
    link = [b for b in btns if b.get("url")]
    assert link and link[0]["url"] == "https://x/preview" and "action_id" not in link[0]

def test_build_published_attachment_has_enhance_unpublish_open():
    att = build_published_attachment("my-app", "https://x/live")
    btns = _btns(att)
    assert any(b.get("action_id") == f"{UNPUBLISH_PREFIX}my-app" for b in btns)
    assert any(b.get("url") == "https://x/live" for b in btns)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**

```python
COLOR_READY = "#36a64f"
COLOR_PUBLISHED = "#2eb67d"

def _link_button(text: str, url: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": text[:_BUTTON_TEXT_MAX]}, "url": url}

def build_ready_attachment(slug: str, preview_url: str = "") -> dict:
    """Green build-ready card: Publish / Enhance + optional Open preview link."""
    elements = [
        _button("Publish", f"{PUBLISH_PREFIX}{slug}", primary=True),
        _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
    ]
    if preview_url:
        elements.append(_link_button("Open preview", preview_url))
    return {"color": COLOR_READY, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*Build ready: {slug}*\nYour app is ready to preview and publish."}},
        {"type": "actions", "elements": elements},
    ]}

def build_published_attachment(slug: str, public_url: str = "") -> dict:
    """Blue published card: Enhance / Unpublish + optional Open link."""
    elements = [
        _button("Enhance", f"{ENHANCE_PREFIX}{slug}"),
        _button("Unpublish", f"{UNPUBLISH_PREFIX}{slug}"),
    ]
    if public_url:
        elements.append(_link_button("Open", public_url))
    desc = f"*Published: {slug}*"
    if public_url:
        desc += f"\n{public_url}"
    return {"color": COLOR_PUBLISHED, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": desc}},
        {"type": "actions", "elements": elements},
    ]}
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): build-ready + published Block Kit cards`

---

## Task 7: App-list blocks (state-aware) + enhance modal

**Files:**
- Modify: `webhook-handler/handlers/slack_app_builder_panel.py`
- Test: `webhook-handler/tests/test_slack_panel.py`

- [ ] **Step 1: Failing test**

```python
from handlers.slack_app_builder_panel import (
    build_apps_list_blocks, build_enhance_modal_view, enhance_text_from_view,
    PUBLISH_PREFIX, UNPUBLISH_PREFIX, STATUS_PREFIX, ENHANCE_MODAL_PREFIX)

def test_apps_list_is_state_aware():
    apps = [{"slug": "draft1", "published": False}, {"slug": "live1", "published": True}]
    blocks = build_apps_list_blocks(apps)
    ids = [e.get("action_id", "") for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert f"{PUBLISH_PREFIX}draft1" in ids        # draft -> Publish
    assert f"{UNPUBLISH_PREFIX}live1" in ids        # published -> Unpublish
    assert f"{STATUS_PREFIX}draft1" in ids

def test_apps_list_empty():
    blocks = build_apps_list_blocks([])
    assert any("no apps" in (b.get("text", {}).get("text", "").lower())
               for b in blocks if b["type"] == "section")

def test_enhance_modal_carries_slug():
    v = build_enhance_modal_view("my-app")
    assert v["callback_id"] == f"{ENHANCE_MODAL_PREFIX}my-app"
    assert v["private_metadata"] == "my-app"
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — `build_apps_list_blocks` (one section + actions row per app, `_MAX_LIST_ROWS = 10`, state-aware buttons: published→[Status, Enhance, Unpublish], draft→[Status, Publish, Enhance]); empty → a "You have no apps yet…" section; overflow → a context block pointing to `/aiui aiuibuilder status <slug>`. Add `build_enhance_modal_view(slug)` (modal, `callback_id=f"{ENHANCE_MODAL_PREFIX}{slug}"`, `private_metadata=slug`, title `"Enhance: <slug>"[:_TITLE_MAX]`, one multiline input block id `enhance_block`/`enhance_input`) and `enhance_text_from_view(view)` (mirror `description_from_view`). Handle both `slug` and `published` keys defensively (`app.get("slug")`, `bool(app.get("published"))`).

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): app-list blocks + enhance modal builders`

---

## Task 8: Interactions — dropdown select opens the build modal

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_handle_block_actions`)
- Test: `webhook-handler/tests/test_slack_interactions.py`

- [ ] **Step 1: Failing test** — a `block_actions` payload whose action is the `static_select` (`action_id == TEMPLATE_SELECT_ACTION_ID`, `selected_option.value == f"{TEMPLATE_PREFIX}portfolio"`) calls `slack.open_modal` with a view whose `callback_id == f"{BUILD_PREFIX}portfolio"`. Also keep the existing Blank-button test (action_id == `TEMPLATE_PREFIX`).

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — in `_handle_block_actions`, read the first action; if `action_id == TEMPLATE_SELECT_ACTION_ID`, take `actions[0]["selected_option"]["value"]` as the template action value and derive the key via `template_key_from_button(value)`; else fall through to the existing `is_panel_button` path (Blank). Then `build_modal_view(key, None, channel_id)` + `open_modal`. (Dispatch the management buttons in Task 10+; for now an unknown action_id still no-ops.)

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): dropdown select opens the build modal`

---

## Task 9: Interactions — build runs in a private DM

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_handle_view_submission`)
- Test: `webhook-handler/tests/test_slack_interactions.py`

This is the core DM flow. **Wiring note (from spec review):** the DM-targeted `CommandContext` MUST set BOTH `notify_channel` (plain text) and `notify_channel_rich` (Block Kit card), or `_watch_build` never posts. `notify_channel_rich` is a **4-arg** callback `(msg, slug, url, email)`.

- [ ] **Step 1: Failing test**

```python
import asyncio, pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack_interactions import SlackInteractionsHandler
from handlers.slack_app_builder_panel import BUILD_PREFIX, DESCRIPTION_BLOCK_ID, DESCRIPTION_INPUT_ID

def _submit(channel="C-panel", key="portfolio", desc="a todo app", user="U1"):
    return {"type": "view_submission", "user": {"id": user, "username": "maya"},
            "team": {"id": "T1"},
            "view": {"callback_id": f"{BUILD_PREFIX}{key}", "private_metadata": channel,
                     "state": {"values": {DESCRIPTION_BLOCK_ID: {DESCRIPTION_INPUT_ID: {"value": desc}}}}}}

@pytest.mark.asyncio
async def test_build_submit_opens_dm_and_runs_in_dm():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value="D9")
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    router = MagicMock(); router.run_panel_build = AsyncMock(return_value=None)
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    resp = await h.handle_interaction(_submit())
    assert resp == {}                              # modal closes
    await asyncio.sleep(0)
    slack.open_dm.assert_awaited_once_with("U1")
    slack.post_ephemeral.assert_awaited_once()     # "sent to your DMs" in #app-builder
    router.run_panel_build.assert_awaited_once()
    ctx = router.run_panel_build.call_args.args[0]
    assert ctx.channel_id == "D9"                  # build context targets the DM
    assert ctx.notify_channel is not None and ctx.notify_channel_rich is not None
    # notify_channel_rich renders the build-ready card into the DM
    await ctx.notify_channel_rich("ready", "todo-1", "https://x/p", "maya@x.com")
    kw = slack.post_message.call_args.kwargs
    assert kw["channel"] == "D9" and kw.get("attachments")

@pytest.mark.asyncio
async def test_build_submit_dm_open_fails_falls_back_to_ephemeral():
    slack = MagicMock()
    slack.open_dm = AsyncMock(return_value=None)   # DMs off
    slack.post_ephemeral = AsyncMock(return_value=True)
    slack.post_message = AsyncMock(return_value="ts")
    router = MagicMock(); router.run_panel_build = AsyncMock(return_value=None)
    h = SlackInteractionsHandler(slack_client=slack, command_router=router)
    await h.handle_interaction(_submit())
    await asyncio.sleep(0)
    # build still runs; delivery falls back to ephemeral in the origin channel
    router.run_panel_build.assert_awaited_once()
    ctx = router.run_panel_build.call_args.args[0]
    assert ctx.channel_id == "C-panel"
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `_handle_view_submission` — branch on callback type: build modal (`is_panel_modal`) vs enhance modal (`is_enhance_modal`, Task 12). For the build modal:

```python
template_key = template_key_from_modal(callback_id)
origin_channel = view.get("private_metadata", "") or ""
description = description_from_view(view)
user = payload.get("user", {}); user_id = user.get("id", "")
user_name = user.get("username") or user.get("name", "unknown")

async def _start() -> None:
    dm_id = await self.slack.open_dm(user_id)
    if dm_id:
        if origin_channel:
            await self.slack.post_ephemeral(origin_channel, user_id,
                "Starting your build — I've sent it to your DMs.")
        await self.slack.post_message(channel=dm_id, text=f"Building `{template_key or 'app'}`…")
        target = dm_id
    else:
        target = origin_channel  # fallback: keep it private-ish via ephemeral

    async def respond(msg: str) -> None:
        if dm_id:
            await self.slack.post_message(channel=dm_id, text=msg)
        elif origin_channel:
            await self.slack.post_ephemeral(origin_channel, user_id, msg)

    async def notify_channel(msg: str) -> None:
        await respond(msg)

    async def notify_channel_rich(msg: str, slug: str, url: str, owner: str) -> None:
        att = build_ready_attachment(slug, url)
        if dm_id:
            await self.slack.post_message(channel=dm_id, text=f"Build ready: {slug}", attachments=[att])
        elif origin_channel:
            await self.slack.post_ephemeral(origin_channel, user_id, f"Build ready: {slug}", blocks=att["blocks"])

    ctx = CommandContext(
        user_id=user_id, user_name=user_name, channel_id=target,
        raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
        subcommand="aiuibuilder", arguments="", platform="slack",
        respond=respond, metadata={"team_id": payload.get("team", {}).get("id", "")},
        notify_channel=notify_channel, notify_channel_rich=notify_channel_rich,
    )
    await self.router.run_panel_build(ctx, template_key, description)

asyncio.create_task(_start())
return {}
```

Add imports: `build_ready_attachment`, `is_enhance_modal`, `slug_from_enhance_modal`, `enhance_text_from_view`. (`open_dm` is opened inside the task so the modal still closes within 3s.)

- [ ] **Step 4: Run, expect PASS** (both tests).
- [ ] **Step 5: Commit** — `feat(slack): App Builder builds run in a private DM`

---

## Task 10: Interactions — Publish + Unpublish buttons

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_handle_block_actions`)
- Test: `webhook-handler/tests/test_slack_interactions.py`

- [ ] **Step 1: Failing test** — a `block_actions` with `action_id == f"{PUBLISH_PREFIX}my-app"` (from a DM message; payload `user.id=U1`) resolves email via `router._resolve_email_for_ctx` (AsyncMock → "u@x"), calls `tasks_client.publish_app("u@x", "my-app")`, opens the DM, and posts the published card. Same shape for Unpublish → `unpublish_app`.

(Provide the router/tasks_client via the handler. The handler reaches the tasks client through `self.router._tasks_client` — same instance the router uses — and email via `self.router._resolve_email_for_ctx(ctx)` with a minimal slack ctx, OR add a tiny helper. Use `self.router._tasks_client` and build a throwaway `CommandContext(platform="slack", user_id=..., ...)` to call `_resolve_email_for_ctx`.)

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — in `_handle_block_actions`, after the template/Blank branch, add dispatch:

```python
for prefix, handler in (
    (PUBLISH_PREFIX, self._do_publish),
    (UNPUBLISH_PREFIX, self._do_unpublish),
    (STATUS_PREFIX, self._do_status),
    (ENHANCE_PREFIX, self._do_open_enhance),
):
    if is_action(action_id, prefix):
        asyncio.create_task(handler(payload, slug_from_action(action_id, prefix)))
        return {}
```

Implement `_do_publish(payload, slug)`: resolve email (helper `_email_for(payload)`), `await self.router._tasks_client.publish_app(email, slug)`, then `dm = await self.slack.open_dm(user_id)` and post `build_published_attachment(slug, result.get("public_url",""))`. `_do_unpublish` similar → re-render `build_ready_attachment` (now unpublished/draft) or a "Unpublished `<slug>`." line. Wrap each in try/except → on `TasksAPIError`/Exception, DM a terse failure. Add a `_email_for(payload)` helper that builds a minimal slack `CommandContext` and calls `self.router._resolve_email_for_ctx`; if None, DM the scope-hint (`router._not_linked_text(ctx)`) and abort.

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): Publish/Unpublish buttons (private DM result)`

---

## Task 11: Interactions — Status button

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py`
- Test: `webhook-handler/tests/test_slack_interactions.py`

- [ ] **Step 1: Failing test** — `STATUS_PREFIX` action → `tasks_client.get_project_status(email, slug)` → posts a status summary to the DM (plain section: name, published yes/no, URL if any).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `_do_status(payload, slug)` — resolve email, `get_project_status`, format a terse Block Kit section (or text), post to DM. On error → terse DM message.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): Status button (private DM)`

---

## Task 12: Interactions — Enhance button + enhance modal submit

**Files:**
- Modify: `webhook-handler/handlers/slack_interactions.py` (`_do_open_enhance`, `_handle_view_submission` enhance branch)
- Test: `webhook-handler/tests/test_slack_interactions.py`

- [ ] **Step 1: Failing test** — (a) `ENHANCE_PREFIX` action opens the enhance modal via `open_modal` (view `callback_id == f"{ENHANCE_MODAL_PREFIX}slug"`); (b) submitting that modal resolves email, opens DM, and calls `router.run_panel_enhance(ctx, slug, prompt)` with a DM-targeted ctx (both `notify_channel` and `notify_channel_rich` set, rich renders `build_ready_attachment`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — `_do_open_enhance(payload, slug)` calls `self.slack.open_modal(trigger_id, build_enhance_modal_view(slug))`. In `_handle_view_submission`, add the `is_enhance_modal(callback_id)` branch: `slug = slug_from_enhance_modal(callback_id)`, `prompt = enhance_text_from_view(view)`, open DM, build the DM-targeted ctx (reuse the same closures as Task 9 — factor a `_dm_context(...)` helper to DRY the two flows), and `await self.router.run_panel_enhance(ctx, slug, prompt)`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): Enhance button + modal (private DM)`

---

## Task 13: Slash `/aiui aiuibuilder list` renders Block Kit

**Files:**
- Modify: `webhook-handler/handlers/slack_commands.py`
- Test: `webhook-handler/tests/test_slack_command_build_notify.py`

- [ ] **Step 1: Failing test** — `handle_command({"command":"/aiui","text":"aiuibuilder list","user_id":"U1","response_url":"https://hooks/x",...})` results (after `await asyncio.sleep(0)`) in `tasks_client.list_projects` being called and `post_to_response_url` invoked with `blocks` (the app-list). The list path is intercepted in the Slack layer (so it renders Block Kit) rather than going through `router.execute`'s text path.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — in `handle_command`, after parsing: if `subcommand == "aiuibuilder"` and `arguments.strip().split()[:1] == ["list"]`, branch to a background task `_render_list(user_id, response_url)` that resolves email (`router._resolve_email_for_ctx` with a slack ctx), `list_projects(email)`, builds `build_apps_list_blocks`, and posts via `post_to_response_url(response_url, "Your apps", response_type="ephemeral", blocks=...)`. Everything else keeps the existing `router.execute` path unchanged. (Buttons in the list reuse the Task 10–12 handlers, which deliver to the DM.)
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat(slack): /aiui aiuibuilder list renders an interactive app list`

---

## Task 14: Full-suite green gate + panel re-post script check

**Files:**
- Test: full `webhook-handler` suite
- Check: `scripts/setup_slack_app_builder_channel.py` still imports cleanly (it imports `build_panel_blocks`, `PANEL_TEXT`)

- [ ] **Step 1:** Run `cd webhook-handler && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest -q`. Expected: all green (≥ 390 + the new tests). Fix any regressions (esp. obsolete panel-grid assertions).
- [ ] **Step 2:** Confirm `python -c "import scripts.setup_slack_app_builder_channel"` style import path still resolves the new `build_panel_blocks` (the setup script posts the new dropdown panel). No code change expected; verify only.
- [ ] **Step 3: Commit** (if any fixups) — `test(slack): green gate for App Builder polish`

---

## Task 15: Deploy + operator setup (manual, gated)

Per CLAUDE.md (webhook-handler is **not** covered by the orchestrator; manual deploy).

- [ ] **Step 1: Add the scope** — api.slack.com/apps → AIUI → OAuth & Permissions → add bot scope **`im:write`** → **Reinstall to Workspace** (bot token usually unchanged; if Slack issues a new one, update `SLACK_BOT_TOKEN` in the server `.env`).
- [ ] **Step 2: Deploy** — from repo root:
```bash
git archive --format=tar.gz -o /tmp/wh.tar.gz HEAD webhook-handler
scp /tmp/wh.tar.gz root@46.224.193.25:/root/proxy-server/wh.tar.gz
ssh root@46.224.193.25 "cd /root/proxy-server && tar xzf wh.tar.gz && rm -f wh.tar.gz && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```
- [ ] **Step 3: Re-post the panel** (new dropdown layout) — copy + run the setup script in-container (same method used previously):
```bash
scp scripts/setup_slack_app_builder_channel.py root@46.224.193.25:/tmp/setup_slack.py
ssh root@46.224.193.25 'docker cp /tmp/setup_slack.py webhook-handler:/app/setup_slack_app_builder_channel.py && docker exec -e APP_BUILDER_SETUP_EMAIL=aiui.teams@gmail.com webhook-handler python /app/setup_slack_app_builder_channel.py && docker exec webhook-handler rm -f /app/setup_slack_app_builder_channel.py'
```
- [ ] **Step 4: Verify** — container `Up (healthy)`, no import errors in logs; then live in Slack: dropdown build → DM card → Publish/Enhance; `/aiui aiuibuilder list`; `/aiui mcp <server> <tool>` (MCP confirm). Confirm `#app-builder` stays clean (only the ephemeral "sent to your DMs").

---

## Notes for the implementer

- **DRY the two DM flows:** Tasks 9 and 12 both build a DM-targeted `CommandContext`. Factor a private `_dm_context(self, payload, *, dm_id, origin_channel, subcommand, raw_text)` returning the ctx with the shared `respond`/`notify_channel`/`notify_channel_rich` closures. Write it during Task 9; reuse in Task 12.
- **Do not touch** `handlers/discord_commands.py`, `handlers/app_builder_panel.py`, or `CommandRouter` business logic. If a shared helper is genuinely needed, prefer reading the existing one over editing it.
- **Email/scope errors** always degrade to a clear DM/ephemeral message — never an unhandled raise (interactions must return fast and clean).
- **Run the full suite** at the end of every task; keep Discord tests untouched and green.
