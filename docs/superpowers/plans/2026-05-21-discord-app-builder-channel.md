# Discord App Builder Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dedicated Discord `#app-builder` channel with a pinned panel of colored template buttons; clicking one opens a popup form to describe the app, which kicks off the existing build pipeline and posts the live URL in the channel — no slash commands typed.

**Architecture:** Discord buttons (message components) and modals arrive at the existing `POST /webhook/discord` interactions endpoint with the same Ed25519 signature. We add two interaction-type branches to `DiscordCommandHandler`, a small pure module for the panel/modal JSON, a thin `run_panel_build` entry on `CommandRouter` (sharing an extracted `_start_build` with the existing text path), and a one-shot setup script that creates the channel and posts the pinned panel. No gateway, no privileged intent, no new container, no new tables.

**Tech Stack:** Python 3, FastAPI, httpx, pytest + pytest-asyncio (`asyncio_mode = auto`), Discord HTTP API v10.

---

## File Structure

- **Create** `webhook-handler/handlers/app_builder_panel.py` — pure builders for the panel message JSON, the modal JSON, and the `custom_id` scheme. No I/O. Imported by the interaction handler and the setup script.
- **Modify** `webhook-handler/handlers/discord_commands.py` — dispatch `MESSAGE_COMPONENT` (button → modal) and `MODAL_SUBMIT` (form → build) in `handle_interaction`.
- **Modify** `webhook-handler/handlers/commands.py` — extract `_start_build` from the inline `aiuibuilder build` branch; add `run_panel_build`.
- **Create** `scripts/setup_app_builder_channel.py` — one-shot: fetch catalog, create/reuse channel, post + pin panel.
- **Create** `webhook-handler/tests/test_app_builder_panel.py` — pure builder + parser tests.
- **Create** `webhook-handler/tests/test_app_builder_interactions.py` — handler dispatch tests.
- **Create** `webhook-handler/tests/test_panel_build.py` — `run_panel_build` router tests.
- **Create** `webhook-handler/tests/test_setup_app_builder_script.py` — setup-script orchestration tests (helpers monkeypatched; no live network).

**All test commands run from the `webhook-handler/` directory.**

---

## Task 1: Pure panel/modal builders + custom_id scheme

**Files:**
- Create: `webhook-handler/handlers/app_builder_panel.py`
- Test: `webhook-handler/tests/test_app_builder_panel.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_app_builder_panel.py`:

```python
"""Pure builders for the App Builder channel panel + modal, and custom_id parsing."""
from handlers.app_builder_panel import (
    build_panel_payload, build_modal_payload,
    is_panel_button, is_panel_modal,
    template_key_from_button, template_key_from_modal,
    TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID,
    ACTION_ROW, TEXT_INPUT, STYLE_SECONDARY,
)

_TEMPLATES = [
    {"key": "portfolio", "label": "Portfolio", "emoji": "\U0001f3a8", "description": "..."},
    {"key": "landing", "label": "Landing page", "emoji": "\U0001f680", "description": "..."},
    {"key": "dashboard", "label": "Dashboard", "emoji": "\U0001f4ca", "description": "..."},
]


def test_panel_has_button_per_template_plus_blank():
    payload = build_panel_payload(_TEMPLATES)
    buttons = [c for row in payload["components"] for c in row["components"]]
    assert len(buttons) == len(_TEMPLATES) + 1
    ids = [b["custom_id"] for b in buttons]
    assert f"{TEMPLATE_PREFIX}portfolio" in ids
    assert TEMPLATE_PREFIX in ids  # blank button has the bare prefix
    blank = next(b for b in buttons if b["custom_id"] == TEMPLATE_PREFIX)
    assert blank["style"] == STYLE_SECONDARY


def test_panel_rows_within_discord_limits():
    many = [{"key": f"t{i}", "label": f"T{i}", "emoji": "x"} for i in range(30)]
    payload = build_panel_payload(many)
    rows = payload["components"]
    assert len(rows) <= 5
    for row in rows:
        assert row["type"] == ACTION_ROW
        assert len(row["components"]) <= 5
    total = sum(len(r["components"]) for r in rows)
    assert total <= 25


def test_panel_skips_keyless_rows():
    payload = build_panel_payload(
        [{"label": "no key", "emoji": "x"}, {"key": "ok", "label": "OK", "emoji": "y"}]
    )
    ids = [c["custom_id"] for row in payload["components"] for c in row["components"]]
    assert f"{TEMPLATE_PREFIX}ok" in ids
    assert TEMPLATE_PREFIX in ids  # blank still present


def test_modal_payload_shape():
    data = build_modal_payload("portfolio", "Portfolio")
    assert data["custom_id"] == f"{BUILD_PREFIX}portfolio"
    row = data["components"][0]
    assert row["type"] == ACTION_ROW
    inp = row["components"][0]
    assert inp["type"] == TEXT_INPUT
    assert inp["custom_id"] == DESCRIPTION_INPUT_ID
    assert inp["required"] is True


def test_modal_payload_blank_key():
    data = build_modal_payload(None)
    assert data["custom_id"] == BUILD_PREFIX  # empty key


def test_custom_id_parsers():
    assert is_panel_button(f"{TEMPLATE_PREFIX}portfolio")
    assert not is_panel_button("other:thing")
    assert template_key_from_button(f"{TEMPLATE_PREFIX}portfolio") == "portfolio"
    assert template_key_from_button(TEMPLATE_PREFIX) is None
    assert is_panel_modal(f"{BUILD_PREFIX}portfolio")
    assert template_key_from_modal(f"{BUILD_PREFIX}portfolio") == "portfolio"
    assert template_key_from_modal(BUILD_PREFIX) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app_builder_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.app_builder_panel'`.

- [ ] **Step 3: Write the implementation**

Create `webhook-handler/handlers/app_builder_panel.py`:

```python
"""Pure builders for the Discord App Builder channel panel and modal.

No I/O. Imported by the interaction handler (handlers/discord_commands.py) and
the one-shot setup script (scripts/setup_app_builder_channel.py); unit tested in
tests/test_app_builder_panel.py.
"""
from __future__ import annotations

# Discord component types
ACTION_ROW = 1
BUTTON = 2
TEXT_INPUT = 4

# Discord button styles
STYLE_PRIMARY = 1    # blurple ("blue")
STYLE_SECONDARY = 2  # grey
STYLE_SUCCESS = 3    # green

# Text input styles
TEXT_PARAGRAPH = 2

# custom_id schemes
TEMPLATE_PREFIX = "aiuibuild:tpl:"   # button -> aiuibuild:tpl:<key>  ("" = Blank)
BUILD_PREFIX = "aiuibuild:build:"    # modal  -> aiuibuild:build:<key>
DESCRIPTION_INPUT_ID = "description"

_MAX_PER_ROW = 5
_MAX_ROWS = 5
_MAX_BUTTONS = _MAX_PER_ROW * _MAX_ROWS  # 25

PANEL_CONTENT = (
    "\U0001f680 **AIUI App Builder**\n"
    "Pick a template to start — a short form opens where you describe your app. "
    "Or hit **Blank** to build from scratch. I'll post the live link here when "
    "it's ready."
)


def _button(label: str, custom_id: str, style: int) -> dict:
    return {"type": BUTTON, "style": style, "label": label[:80], "custom_id": custom_id}


def build_panel_payload(templates: list[dict]) -> dict:
    """Pinned panel message: one green/blue button per template plus a grey Blank
    button, laid out 5 per row. Templates beyond the 24-button budget (room left
    for Blank) are dropped — the slash command still reaches them."""
    buttons: list[dict] = []
    for i, t in enumerate(templates[: _MAX_BUTTONS - 1]):
        key = t.get("key")
        if not key:
            continue  # tolerate a malformed row rather than crash
        emoji = (t.get("emoji") or "").strip()
        label = t.get("label", key)
        text = f"{emoji} {label}".strip()
        style = STYLE_SUCCESS if i % 2 == 0 else STYLE_PRIMARY
        buttons.append(_button(text, f"{TEMPLATE_PREFIX}{key}", style))
    buttons.append(_button("⬜ Blank", TEMPLATE_PREFIX, STYLE_SECONDARY))

    rows: list[dict] = []
    for start in range(0, len(buttons), _MAX_PER_ROW):
        rows.append({"type": ACTION_ROW, "components": buttons[start : start + _MAX_PER_ROW]})
    rows = rows[:_MAX_ROWS]
    return {"content": PANEL_CONTENT, "components": rows}


def build_modal_payload(template_key: str | None, template_label: str | None = None) -> dict:
    """Type-9 MODAL `data`: a single paragraph 'Describe your app' field. The
    custom_id carries the template key so the submit handler knows what to build."""
    key = template_key or ""
    what = template_label or template_key or "app"
    return {
        "title": f"Build: {what}"[:45],
        "custom_id": f"{BUILD_PREFIX}{key}",
        "components": [
            {
                "type": ACTION_ROW,
                "components": [
                    {
                        "type": TEXT_INPUT,
                        "custom_id": DESCRIPTION_INPUT_ID,
                        "label": "Describe your app",
                        "style": TEXT_PARAGRAPH,
                        "required": True,
                        "max_length": 4000,
                        "placeholder": "e.g. a portfolio site for Maya, a UX designer",
                    }
                ],
            }
        ],
    }


def is_panel_button(custom_id: str) -> bool:
    return custom_id.startswith(TEMPLATE_PREFIX)


def is_panel_modal(custom_id: str) -> bool:
    return custom_id.startswith(BUILD_PREFIX)


def template_key_from_button(custom_id: str) -> str | None:
    """Button custom_id -> template key. Bare prefix (Blank) -> None."""
    if not is_panel_button(custom_id):
        raise ValueError(f"not a panel button custom_id: {custom_id!r}")
    return custom_id[len(TEMPLATE_PREFIX):] or None


def template_key_from_modal(custom_id: str) -> str | None:
    """Modal custom_id -> template key. Bare prefix -> None."""
    if not is_panel_modal(custom_id):
        raise ValueError(f"not a panel modal custom_id: {custom_id!r}")
    return custom_id[len(BUILD_PREFIX):] or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app_builder_panel.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/app_builder_panel.py webhook-handler/tests/test_app_builder_panel.py
git commit -m "feat(discord): pure panel/modal builders for app-builder channel"
```

---

## Task 2: Extract `_start_build` and add `run_panel_build` on CommandRouter

**Files:**
- Modify: `webhook-handler/handlers/commands.py` (the `build` branch inside `_handle_aiuibuilder`, ~lines 1374-1427; add two methods after `_handle_aiuibuilder` ends, ~line 1489)
- Test: `webhook-handler/tests/test_panel_build.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_panel_build.py`:

```python
"""CommandRouter.run_panel_build — App Builder channel build entry."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


def _ctx(user_id, captured, *, notify=None):
    async def respond(msg):
        captured.append(msg)
    return CommandContext(
        user_id=user_id, user_name="t", channel_id="c",
        raw_text="", subcommand="aiuibuilder", arguments="",
        platform="discord", respond=respond, metadata={},
        notify_channel=notify,
    )


def _router(mapping, tasks_client):
    return CommandRouter(
        openwebui_client=MagicMock(), n8n_client=MagicMock(api_key=""),
        discord_user_email_map=mapping, tasks_client=tasks_client,
    )


@pytest.mark.asyncio
async def test_unmapped_user_rejected():
    captured = []
    await _router({}, MagicMock()).run_panel_build(_ctx("9", captured), "portfolio", "x")
    assert any("isn't linked" in m for m in captured)


@pytest.mark.asyncio
async def test_empty_description_rejected():
    captured = []
    tc = MagicMock(); tc.start_build = AsyncMock()
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "   ")
    assert any("describe" in m.lower() for m in captured)
    tc.start_build.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_starts_build():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "port-ab12", "task_id": "t1"})
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "a portfolio")
    tc.start_build.assert_awaited_once_with("a@x.com", "a portfolio", template_key="portfolio")
    assert any("Building `port-ab12`" in m for m in captured)


@pytest.mark.asyncio
async def test_blank_build_passes_none_template():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(return_value={"slug": "s", "task_id": "t1"})
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), None, "a blank app")
    tc.start_build.assert_awaited_once_with("a@x.com", "a blank app", template_key=None)


@pytest.mark.asyncio
async def test_build_error_surfaced():
    captured = []
    tc = MagicMock()
    tc.start_build = AsyncMock(side_effect=TasksAPIError(429, "busy"))
    await _router({"100": "a@x.com"}, tc).run_panel_build(_ctx("100", captured), "portfolio", "x")
    assert any("already running" in m.lower() for m in captured)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_panel_build.py -v`
Expected: FAIL — `AttributeError: 'CommandRouter' object has no attribute 'run_panel_build'`.

- [ ] **Step 3a: Refactor the `build` branch to call `_start_build`**

In `webhook-handler/handlers/commands.py`, inside `_handle_aiuibuilder`, replace this block (the part from `if not description:` through the watcher wiring at the end of the `build` branch):

```python
            if not description:
                await ctx.respond(
                    'Usage: `aiuibuilder build [template] <description>` — e.g. '
                    '`aiuibuilder build portfolio a UX designer named Maya`. '
                    'See `aiuibuilder templates`.'
                )
                return
            try:
                result = await self._tasks_client.start_build(
                    email, description, template_key=template_key)
            except TasksAPIError as e:
                await ctx.respond(self._format_build_error(e))
                return
            slug = result["slug"]
            task_id = result["task_id"]
            tnote = f" (from the {label_by_key[template_key]} template)" if template_key else ""
            await ctx.respond(
                f"Building `{slug}`{tnote} … I'll post the link here when it's ready "
                "(usually a few minutes)."
            )
            if ctx.notify_channel is not None:
                watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
                self._background_tasks.add(watcher)
                watcher.add_done_callback(self._background_tasks.discard)
            return
```

with:

```python
            if not description:
                await ctx.respond(
                    'Usage: `aiuibuilder build [template] <description>` — e.g. '
                    '`aiuibuilder build portfolio a UX designer named Maya`. '
                    'See `aiuibuilder templates`.'
                )
                return
            await self._start_build(
                ctx, email, template_key, description,
                template_label=label_by_key.get(template_key) if template_key else None,
            )
            return
```

- [ ] **Step 3b: Add the two methods**

In `webhook-handler/handlers/commands.py`, immediately after the `_handle_aiuibuilder` method ends (just before `def _format_tasks_error`), add:

```python
    async def _start_build(
        self, ctx: CommandContext, email: str, template_key: str | None,
        description: str, *, template_label: str | None = None,
    ) -> None:
        """Start a one-shot build and wire the result watcher.

        Shared by the `/aiui aiuibuilder build` text path and the App Builder
        channel button/modal path. `description` must be non-empty (callers
        validate). `template_label`, when given, is named in the ack."""
        try:
            result = await self._tasks_client.start_build(
                email, description, template_key=template_key)
        except TasksAPIError as e:
            await ctx.respond(self._format_build_error(e))
            return
        slug = result["slug"]
        task_id = result["task_id"]
        tnote = f" (from the {template_label} template)" if template_label else ""
        await ctx.respond(
            f"Building `{slug}`{tnote} … I'll post the link here when it's ready "
            "(usually a few minutes)."
        )
        if ctx.notify_channel is not None:
            watcher = asyncio.create_task(self._watch_build(ctx, email, task_id, slug))
            self._background_tasks.add(watcher)
            watcher.add_done_callback(self._background_tasks.discard)

    async def run_panel_build(
        self, ctx: CommandContext, template_key: str | None, description: str,
    ) -> None:
        """App Builder channel entry (a button+modal submit). Resolves the
        caller's email, validates, then starts the build. The template key is
        explicit (from the clicked button), so — unlike the free-text `build`
        path — a Blank build whose first word matches a template key is never
        misread as a template build."""
        email = self._discord_user_email_map.get(ctx.user_id)
        if not email:
            await ctx.respond(
                "Your Discord account isn't linked. Ask Lukas to add you."
            )
            return
        description = (description or "").strip()
        if not description:
            await ctx.respond("Please describe the app you want to build.")
            return
        await self._start_build(ctx, email, template_key, description)
```

- [ ] **Step 4: Run new tests + regression**

Run: `python -m pytest tests/test_panel_build.py tests/test_aiuibuilder_build.py tests/test_aiuibuilder_handler.py -v`
Expected: PASS (new `run_panel_build` tests green; existing build/handler tests still green after the extraction).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_panel_build.py
git commit -m "feat(discord): run_panel_build entry; share _start_build with text path"
```

---

## Task 3: Handle button + modal interactions in DiscordCommandHandler

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py`
- Test: `webhook-handler/tests/test_app_builder_interactions.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_app_builder_interactions.py`:

```python
"""DiscordCommandHandler: button click -> modal, modal submit -> build."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import TEMPLATE_PREFIX, BUILD_PREFIX, DESCRIPTION_INPUT_ID


def _handler(router):
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.post_channel_message = AsyncMock(return_value=True)
    return DiscordCommandHandler(discord_client=discord, command_router=router)


@pytest.mark.asyncio
async def test_button_click_opens_modal():
    handler = _handler(MagicMock())
    payload = {
        "type": 3, "id": "i", "token": "t",
        "data": {"custom_id": f"{TEMPLATE_PREFIX}portfolio"},
        "member": {"user": {"id": "100", "username": "t"}},
        "channel_id": "c",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 9  # MODAL
    assert resp["data"]["custom_id"] == f"{BUILD_PREFIX}portfolio"


@pytest.mark.asyncio
async def test_unknown_component_is_noop():
    handler = _handler(MagicMock())
    resp = await handler.handle_interaction({"type": 3, "data": {"custom_id": "something:else"}})
    assert resp["type"] == 6  # DEFERRED_UPDATE_MESSAGE, never an error


@pytest.mark.asyncio
async def test_modal_submit_routes_build():
    captured = {}
    async def fake_run(ctx, template_key, description):
        captured.update(ctx=ctx, key=template_key, desc=description)
    router = MagicMock(); router.run_panel_build = fake_run
    handler = _handler(router)
    payload = {
        "type": 5, "id": "i", "token": "tok",
        "data": {
            "custom_id": f"{BUILD_PREFIX}portfolio",
            "components": [{"type": 1, "components": [
                {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": "a portfolio for Maya"}]}],
        },
        "member": {"user": {"id": "100", "username": "maya"}},
        "channel_id": "chan-1",
    }
    resp = await handler.handle_interaction(payload)
    assert resp["type"] == 5  # deferred ACK
    await asyncio.sleep(0)
    assert captured["key"] == "portfolio"
    assert captured["desc"] == "a portfolio for Maya"
    assert captured["ctx"].user_id == "100"
    assert captured["ctx"].notify_channel is not None


@pytest.mark.asyncio
async def test_modal_submit_blank_key():
    captured = {}
    async def fake_run(ctx, template_key, description):
        captured["key"] = template_key
    router = MagicMock(); router.run_panel_build = fake_run
    handler = _handler(router)
    payload = {
        "type": 5, "token": "tok",
        "data": {
            "custom_id": BUILD_PREFIX,
            "components": [{"type": 1, "components": [
                {"type": 4, "custom_id": DESCRIPTION_INPUT_ID, "value": "a blank app"}]}],
        },
        "member": {"user": {"id": "100", "username": "x"}},
        "channel_id": "c",
    }
    await handler.handle_interaction(payload)
    await asyncio.sleep(0)
    assert captured["key"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app_builder_interactions.py -v`
Expected: FAIL — `test_button_click_opens_modal` gets `{"type": 1}` (PONG fallback) instead of `{"type": 9}`.

- [ ] **Step 3a: Add constants + imports**

In `webhook-handler/handlers/discord_commands.py`, replace the existing constant block:

```python
# Discord interaction types
PING = 1
APPLICATION_COMMAND = 2

# Discord interaction callback types
PONG = 1
DEFERRED_CHANNEL_MESSAGE = 5
```

with:

```python
# Discord interaction types (payload["type"])
PING = 1
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3
MODAL_SUBMIT = 5  # NOTE: same number as DEFERRED_CHANNEL_MESSAGE below, but a
                  # different field (interaction type vs. callback type).

# Discord interaction callback (response) types
PONG = 1
DEFERRED_CHANNEL_MESSAGE = 5
DEFERRED_UPDATE_MESSAGE = 6
MODAL = 9
```

And add this import after the existing `from handlers.commands import ...` line:

```python
from handlers.app_builder_panel import (
    build_modal_payload,
    is_panel_button,
    is_panel_modal,
    template_key_from_button,
    template_key_from_modal,
    DESCRIPTION_INPUT_ID,
)
```

- [ ] **Step 3b: Dispatch the two new interaction types**

In `handle_interaction`, after the `APPLICATION_COMMAND` branch and before the final `logger.info(...)/return {"type": PONG}`, add:

```python
        # MESSAGE_COMPONENT — a button click (e.g. an App Builder template button)
        if interaction_type == MESSAGE_COMPONENT:
            return await self._handle_message_component(payload)

        # MODAL_SUBMIT — the "Describe your app" form was submitted
        if interaction_type == MODAL_SUBMIT:
            return await self._handle_modal_submit(payload)
```

- [ ] **Step 3c: Add the handler methods**

In `webhook-handler/handlers/discord_commands.py`, add these methods to `DiscordCommandHandler` (after `_handle_application_command`, before `_parse_options`):

```python
    async def _handle_message_component(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A button click. App Builder template buttons open a modal; any other
        component is a harmless no-op (never a 500)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if not is_panel_button(custom_id):
            logger.info(f"Ignoring unknown component custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}
        template_key = template_key_from_button(custom_id)
        logger.info(f"App Builder button clicked: template={template_key}")
        return {"type": MODAL, "data": build_modal_payload(template_key)}

    async def _handle_modal_submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """An App Builder modal submission. Extract the description, route to the
        build in the background, and ACK deferred — mirrors the slash-command
        deferred pattern (the watcher posts the link via the bot token later)."""
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")
        if not is_panel_modal(custom_id):
            logger.info(f"Ignoring unknown modal custom_id: {custom_id}")
            return {"type": DEFERRED_UPDATE_MESSAGE}

        interaction_token = payload.get("token", "")
        member = payload.get("member", {})
        user = member.get("user", payload.get("user", {}))
        user_id = user.get("id", "")
        user_name = user.get("username", "unknown")
        channel_id = payload.get("channel_id", "")

        template_key = template_key_from_modal(custom_id)
        description = self._extract_modal_value(data, DESCRIPTION_INPUT_ID)

        async def respond(msg: str) -> None:
            await self.discord.edit_original(
                interaction_token=interaction_token, content=msg,
            )

        async def notify_channel(msg: str) -> None:
            await self.discord.post_channel_message(channel_id, msg)

        ctx = CommandContext(
            user_id=user_id,
            user_name=user_name,
            channel_id=channel_id,
            raw_text=f"aiuibuilder build {template_key or ''} {description}".strip(),
            subcommand="aiuibuilder",
            arguments="",
            platform="discord",
            respond=respond,
            metadata={
                "interaction_id": payload.get("id", ""),
                "interaction_token": interaction_token,
                "guild_id": payload.get("guild_id", ""),
            },
            notify_channel=notify_channel if channel_id else None,
        )

        asyncio.create_task(self.router.run_panel_build(ctx, template_key, description))
        return {"type": DEFERRED_CHANNEL_MESSAGE}

    @staticmethod
    def _extract_modal_value(data: dict[str, Any], input_custom_id: str) -> str:
        """Pull a text-input value out of a modal-submit payload.
        data.components[*].components[*] -> {custom_id, value}."""
        for row in data.get("components", []):
            for comp in row.get("components", []):
                if comp.get("custom_id") == input_custom_id:
                    return (comp.get("value") or "").strip()
        return ""
```

- [ ] **Step 4: Run tests + the existing Discord handler tests**

Run: `python -m pytest tests/test_app_builder_interactions.py tests/test_discord_notify_wiring.py -v`
Expected: PASS (new dispatch tests + existing slash-command wiring unaffected).

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_app_builder_interactions.py
git commit -m "feat(discord): handle button->modal and modal-submit->build interactions"
```

---

## Task 4: One-shot channel setup script

**Files:**
- Create: `scripts/setup_app_builder_channel.py`
- Test: `webhook-handler/tests/test_setup_app_builder_script.py`

- [ ] **Step 1: Write the failing tests**

Create `webhook-handler/tests/test_setup_app_builder_script.py`:

```python
"""scripts/setup_app_builder_channel.py orchestration (helpers monkeypatched)."""
import os
import sys

import pytest

# Make the scripts/ dir importable (repo_root/scripts).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import setup_app_builder_channel as setup  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "APP_BUILDER_SETUP_EMAIL",
              "ADMIN_EMAILS", "TASKS_URL", "APP_BUILDER_CHANNEL_NAME"):
        monkeypatch.delenv(k, raising=False)


def test_missing_token_or_guild_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    assert setup.main() == 1


def test_missing_email_returns_1(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    assert setup.main() == 1


def test_happy_path_creates_and_pins(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    calls = {}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "portfolio", "label": "Portfolio", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: None)
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: calls.setdefault("created", "chan-1") or "chan-1")
    monkeypatch.setattr(setup, "_post_panel",
                        lambda c, p, h: calls.setdefault("posted", (c, p)) or "msg-1")
    monkeypatch.setattr(setup, "_pin",
                        lambda c, m, h: calls.setdefault("pinned", (c, m)))

    assert setup.main() == 0
    assert calls["created"] == "chan-1"
    assert calls["posted"][0] == "chan-1"
    assert "components" in calls["posted"][1]  # a real panel payload was posted
    assert calls["pinned"] == ("chan-1", "msg-1")


def test_reuses_existing_channel(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("APP_BUILDER_SETUP_EMAIL", "admin@x.com")

    created = {"n": 0}
    monkeypatch.setattr(setup, "_fetch_templates",
                        lambda url, email: [{"key": "landing", "label": "Landing", "emoji": "x"}])
    monkeypatch.setattr(setup, "_find_channel", lambda g, n, h: "existing-1")
    monkeypatch.setattr(setup, "_create_channel",
                        lambda g, n, h: created.__setitem__("n", created["n"] + 1) or "new")
    monkeypatch.setattr(setup, "_post_panel", lambda c, p, h: "msg-2")
    monkeypatch.setattr(setup, "_pin", lambda c, m, h: None)

    assert setup.main() == 0
    assert created["n"] == 0  # never created a second channel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_setup_app_builder_script.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'setup_app_builder_channel'`.

- [ ] **Step 3: Write the script**

Create `scripts/setup_app_builder_channel.py`:

```python
"""Create (or reuse) the Discord App Builder channel and post its button panel.

One-shot setup, modeled on scripts/register_discord_commands.py. Idempotent:
re-running reuses a channel with the same name and posts a fresh, re-pinned panel.

Usage:
    DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \\
    [TASKS_URL=http://tasks:8210] [APP_BUILDER_SETUP_EMAIL=admin@example.com] \\
    [APP_BUILDER_CHANNEL_NAME=app-builder] \\
    python scripts/setup_app_builder_channel.py

The bot must be in the guild with Manage Channels + Send Messages.
"""
import os
import sys

import httpx

# Import the pure panel builder from the webhook-handler package.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "webhook-handler"))
from handlers.app_builder_panel import build_panel_payload  # noqa: E402

DISCORD_API = "https://discord.com/api/v10"
TEXT_CHANNEL = 0  # Discord guild text-channel type


def _fetch_templates(tasks_url: str, email: str) -> list[dict]:
    url = f"{tasks_url.rstrip('/')}/api/aiuibuilder/templates"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers={"X-User-Email": email})
    r.raise_for_status()
    return r.json()


def _find_channel(guild_id: str, name: str, headers: dict) -> str | None:
    url = f"{DISCORD_API}/guilds/{guild_id}/channels"
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    for ch in r.json():
        if ch.get("type") == TEXT_CHANNEL and ch.get("name") == name:
            return ch["id"]
    return None


def _create_channel(guild_id: str, name: str, headers: dict) -> str:
    url = f"{DISCORD_API}/guilds/{guild_id}/channels"
    body = {"name": name, "type": TEXT_CHANNEL,
            "topic": "Build apps with AIUI — pick a template below."}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=body)
    r.raise_for_status()
    return r.json()["id"]


def _post_panel(channel_id: str, payload: dict, headers: dict) -> str:
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    with httpx.Client(timeout=30.0) as client:
        r = client.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def _pin(channel_id: str, message_id: str, headers: dict) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/pins/{message_id}"
    with httpx.Client(timeout=30.0) as client:
        r = client.put(url, headers=headers)
    if r.status_code not in (200, 204):
        print(f"WARN: pin returned {r.status_code} {r.text}", file=sys.stderr)


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    tasks_url = os.environ.get("TASKS_URL", "http://tasks:8210").strip()
    email = os.environ.get("APP_BUILDER_SETUP_EMAIL", "").strip()
    if not email:
        admins = os.environ.get("ADMIN_EMAILS", "").strip()
        email = admins.split(",")[0].strip() if admins else ""
    channel_name = os.environ.get("APP_BUILDER_CHANNEL_NAME", "app-builder").strip()

    if not token or not guild_id:
        print("ERROR: DISCORD_BOT_TOKEN and DISCORD_GUILD_ID must be set.", file=sys.stderr)
        return 1
    if not email:
        print("ERROR: set APP_BUILDER_SETUP_EMAIL (or ADMIN_EMAILS) to fetch the catalog.",
              file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    try:
        templates = _fetch_templates(tasks_url, email)
    except Exception as e:
        print(f"ERROR: could not fetch templates from {tasks_url}: {e}", file=sys.stderr)
        return 2
    if not templates:
        print("ERROR: template catalog is empty.", file=sys.stderr)
        return 2

    payload = build_panel_payload(templates)

    try:
        channel_id = _find_channel(guild_id, channel_name, headers)
        if channel_id:
            print(f"Reusing existing channel #{channel_name} ({channel_id})")
        else:
            channel_id = _create_channel(guild_id, channel_name, headers)
            print(f"Created channel #{channel_name} ({channel_id})")
        message_id = _post_panel(channel_id, payload, headers)
        _pin(channel_id, message_id, headers)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Discord API {e.response.status_code}: {e.response.text}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    print(f"OK — panel posted ({len(templates)} templates) and pinned.")
    print(f"Channel ID: {channel_id}  Message ID: {message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_setup_app_builder_script.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_app_builder_channel.py webhook-handler/tests/test_setup_app_builder_script.py
git commit -m "feat(discord): one-shot setup script for the app-builder channel + panel"
```

---

## Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire webhook-handler suite**

Run (from `webhook-handler/`): `python -m pytest -v`
Expected: PASS — all tests green, including pre-existing suites (no regressions from the `_start_build` extraction or the new interaction branches).

- [ ] **Step 2: If anything is red, fix it before proceeding**

Use the systematic-debugging skill. Do not edit tests to pass unless the test itself is wrong.

- [ ] **Step 3: Final commit (only if Step 2 required changes)**

```bash
git add -A
git commit -m "test(discord): green app-builder channel suite end to end"
```

---

## Going live (user's final step — provided at hand-off, not run by the plan)

After the updated `webhook-handler` is deployed (so the interactions endpoint handles buttons/modals), run once on the server where the bot + tasks service run:

```bash
DISCORD_GUILD_ID=<your-guild-id> \
APP_BUILDER_SETUP_EMAIL=<an-admin-email> \
python scripts/setup_app_builder_channel.py
```

Requirements: the bot is in the guild with **Manage Channels** + **Send Messages**; the interactions endpoint URL is already configured (same one the slash commands use). No new Discord slash-command registration is needed — the panel is buttons, not a command.

---

## Self-Review Notes

- **Spec coverage:** panel buttons (Task 1), modal (Tasks 1+3), button→modal + modal→build dispatch (Task 3), reuse of existing build backend via `run_panel_build`/`_start_build` (Task 2), data-driven catalog + idempotent channel creation + pinning (Task 4), full-suite green (Task 5), Open WebUI panel explicitly out of scope (not implemented). ✔
- **Type consistency:** `build_panel_payload`, `build_modal_payload`, `is_panel_button/modal`, `template_key_from_button/modal`, `DESCRIPTION_INPUT_ID`, `run_panel_build(ctx, template_key, description)`, `_start_build(ctx, email, template_key, description, *, template_label=None)`, `_extract_modal_value(data, input_custom_id)` — names match across all tasks and the imports in Task 3/Task 4. ✔
- **No placeholders:** every code/test step contains complete content. ✔
