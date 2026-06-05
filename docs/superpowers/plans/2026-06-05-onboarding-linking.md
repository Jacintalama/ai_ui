# Onboarding & Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Slack + Discord bots usable by non-technical first-timers — kill the "Ask Lukas" dead-end, notify Discord users when their link request is decided, and greet new users with a button-first welcome card.

**Architecture:** A new pure-builder module `handlers/onboarding.py` centralizes all onboarding copy + Block Kit / Discord components (unit-tested, no I/O). A small `open_dm`/`send_dm` capability is added to the Discord client so the approval handler can DM the requester. Call sites delegate to the new builders; behavior on the Slack DM/mention path gains a welcome card.

**Tech Stack:** Python 3, FastAPI webhook-handler, httpx, pytest (in `webhook-handler/.venv`). Discord = HTTP interactions; Slack = Events API + Block Kit.

**Test runner (use everywhere below):**
```bash
cd "C:/Users/Acer Philippines/OneDrive/Desktop/Lukas Project/ai_ui/webhook-handler" && ./.venv/Scripts/python.exe -m pytest <args>
```

**Spec:** `docs/superpowers/specs/2026-06-05-onboarding-linking-design.md`

---

## File structure

- **Create** `webhook-handler/handlers/onboarding.py` — all onboarding copy + component/block builders + the getting-started heuristic. One responsibility: "what onboarding/linking UI looks like."
- **Create** `webhook-handler/tests/test_onboarding.py` — unit tests for the pure builders.
- **Create** `webhook-handler/tests/test_discord_dm.py` — unit tests for the new DM client methods.
- **Modify** `webhook-handler/clients/discord.py` — add `open_dm`, `send_dm`.
- **Modify** `webhook-handler/handlers/discord_commands.py` — DM the user in `_handle_link_decision`; use the Link button on the not-linked path at :1024.
- **Modify** `webhook-handler/handlers/commands.py` — `_not_linked_text`/`_not_linked_msg` delegate to `onboarding`; add `_respond_not_linked`; lead `/aiui help` with the welcome card.
- **Modify** `webhook-handler/handlers/slack.py` — welcome card on getting-started messages; buttons footer otherwise.
- **Modify** `webhook-handler/tests/test_two_button_entry.py`, `test_slack_command_build_notify.py`, `test_slack_interactions.py`, `test_slack_schedule_interactions.py` — update mocks/assertions to the new copy.

Constants reused (already defined in `handlers/app_builder_panel.py`): `_button`, `ACTION_ROW`, `STYLE_SUCCESS`, `STYLE_PRIMARY`, `LINK_START_ID`, `PANEL_NEW_ID`, `SCHED_OPEN_ID`. Slack reuses `PANEL_NEW_ID`, `SCHED_OPEN_ID` (shared strings) with `slack_app_builder_panel._button`.

---

## Task 1: onboarding.py — Discord copy + link/welcome components

**Files:**
- Create: `webhook-handler/handlers/onboarding.py`
- Test: `webhook-handler/tests/test_onboarding.py`

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_onboarding.py
from handlers import onboarding as ob
from handlers.app_builder_panel import LINK_START_ID, PANEL_NEW_ID, SCHED_OPEN_ID


def test_not_linked_text_discord_is_friendly_and_self_service():
    txt = ob.not_linked_text_discord()
    assert "Lukas" not in txt
    assert "Link my account" in txt


def test_link_button_row_carries_link_start_id():
    row = ob.link_button_row()
    btn = row[0]["components"][0]
    assert btn["custom_id"] == LINK_START_ID
    assert "Link my account" in btn["label"]


def test_welcome_components_discord_has_build_and_schedule_buttons():
    row = ob.welcome_components_discord()[0]
    ids = [c["custom_id"] for c in row["components"]]
    assert PANEL_NEW_ID in ids
    assert SCHED_OPEN_ID in ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.onboarding'`

- [ ] **Step 3: Write minimal implementation**

```python
# webhook-handler/handlers/onboarding.py
"""Pure builders for onboarding & linking UX: not-linked cards, the welcome
card, and the approval DM. No I/O — unit tested in tests/test_onboarding.py.

Copy here is the single source of truth for onboarding wording. It must never
contain a person's name or a raw OAuth scope instruction aimed at the end user.
"""
from __future__ import annotations

import re

from handlers.app_builder_panel import (
    ACTION_ROW,
    STYLE_SUCCESS,
    STYLE_PRIMARY,
    LINK_START_ID,
    PANEL_NEW_ID,
    SCHED_OPEN_ID,
    _button,
)

# --- Discord copy ---
WELCOME_TEXT_DISCORD = (
    "\U0001f44b Hi! I can **build you a website** or **run a task on a "
    "schedule** — no coding needed. Tap a button to start:"
)


def not_linked_text_discord() -> str:
    return (
        "\U0001f44b You're almost set up — tap **\U0001f517 Link my "
        "account** below to start building."
    )


def link_button_row() -> list[dict]:
    """One action row holding the existing self-service Link button."""
    return [{"type": ACTION_ROW, "components": [
        _button("\U0001f517 Link my account", LINK_START_ID, STYLE_PRIMARY),
    ]}]


def welcome_components_discord() -> list[dict]:
    """Welcome card buttons: Build an app + Schedule a task (existing entries)."""
    return [{"type": ACTION_ROW, "components": [
        _button("\U0001f680 Build an app", PANEL_NEW_ID, STYLE_SUCCESS),
        _button("⏰ Schedule a task", SCHED_OPEN_ID, STYLE_PRIMARY),
    ]}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/onboarding.py webhook-handler/tests/test_onboarding.py
git commit -m "feat(onboarding): Discord not-linked + welcome component builders"
```

---

## Task 2: onboarding.py — Slack copy, welcome blocks, getting-started heuristic

**Files:**
- Modify: `webhook-handler/handlers/onboarding.py`
- Test: `webhook-handler/tests/test_onboarding.py`

- [ ] **Step 1: Write the failing test (append)**

```python
# append to webhook-handler/tests/test_onboarding.py

def test_not_linked_text_slack_has_no_bare_scope_jargon_lead():
    txt = ob.not_linked_text_slack()
    assert "Lukas" not in txt
    # plain-language lead; the scope name may appear only as a parenthetical
    assert txt.lower().startswith("i can")
    assert "email access" in txt.lower()


def test_welcome_blocks_slack_have_two_action_buttons():
    blocks = ob.welcome_blocks_slack()
    actions = [b for b in blocks if b["type"] == "actions"][0]
    ids = [e["action_id"] for e in actions["elements"]]
    assert PANEL_NEW_ID in ids
    assert SCHED_OPEN_ID in ids


def test_buttons_footer_slack_is_an_actions_block():
    footer = ob.buttons_footer_slack()
    assert footer["type"] == "actions"
    assert len(footer["elements"]) == 2


import pytest


@pytest.mark.parametrize("text", [
    "hi", "Hello", "hey there", "help", "get started",
    "what can you do", "how do i start", "start",
])
def test_getting_started_matches_greetings_and_help(text):
    assert ob.looks_like_getting_started(text) is True


@pytest.mark.parametrize("text", [
    "summarize my unread emails every morning",
    "build me a booking site for my salon with stripe checkout",
    "why is my published app returning a 404 error",
])
def test_getting_started_ignores_real_requests(text):
    assert ob.looks_like_getting_started(text) is False
```

Add the import near the top of the test file if not already present:
```python
from handlers.app_builder_panel import LINK_START_ID, PANEL_NEW_ID, SCHED_OPEN_ID
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py -v`
Expected: FAIL — `AttributeError: module 'handlers.onboarding' has no attribute 'not_linked_text_slack'`

- [ ] **Step 3: Write minimal implementation (append to onboarding.py)**

```python
# append to webhook-handler/handlers/onboarding.py
from handlers.slack_app_builder_panel import _button as _slack_button

# --- Slack copy ---
WELCOME_TEXT_SLACK = (
    ":wave: Hi! I can *build you a website* or *run a task on a schedule* "
    "— no coding needed. Tap a button to start:"
)


def not_linked_text_slack() -> str:
    return (
        "I can't see your email yet. Ask whoever set up this Slack workspace "
        "to turn on email access for the bot (the `users:read.email` "
        "permission), then try again."
    )


def _slack_welcome_action_elements() -> list[dict]:
    return [
        _slack_button("\U0001f680 Build an app", PANEL_NEW_ID, primary=True),
        _slack_button("⏰ Schedule a task", SCHED_OPEN_ID),
    ]


def welcome_blocks_slack() -> list[dict]:
    """Full welcome card: a section of copy + the two entry buttons."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": WELCOME_TEXT_SLACK}},
        {"type": "actions", "elements": _slack_welcome_action_elements()},
    ]


def buttons_footer_slack() -> dict:
    """Compact always-present footer (just the two buttons, no copy) appended
    under a normal AI answer so the entry points are always one tap away."""
    return {"type": "actions", "elements": _slack_welcome_action_elements()}


# --- shared heuristic ---
_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|help|start|get\s+started|getting\s+started|"
    r"how\s+do\s+i|how\s+to|what\s+can\s+you\s+do|what\s+do\s+you\s+do|"
    r"who\s+are\s+you|menu)\b",
    re.IGNORECASE,
)


def looks_like_getting_started(text: str) -> bool:
    """True for greetings/help/very-short messages (show the welcome card);
    False for substantive requests (answer normally + buttons footer)."""
    t = (text or "").strip()
    if not t:
        return True
    if len(t.split()) <= 2:
        return True
    return bool(_GREETING_RE.match(t))
```

Note: `_GREETING_RE` matches "what can you do" / "how do i start"; the >2-word guard is checked first only for very short messages, so "what can you do" (4 words) is matched by the regex, and "build me a booking site…" (many words, no greeting prefix) returns False.

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/onboarding.py webhook-handler/tests/test_onboarding.py
git commit -m "feat(onboarding): Slack not-linked copy, welcome blocks, getting-started heuristic"
```

---

## Task 3: onboarding.py — approval/rejection DM builder

**Files:**
- Modify: `webhook-handler/handlers/onboarding.py`
- Test: `webhook-handler/tests/test_onboarding.py`

- [ ] **Step 1: Write the failing test (append)**

```python
# append to webhook-handler/tests/test_onboarding.py

def test_approval_dm_approved_has_build_button():
    text, components = ob.approval_dm_discord(approved=True)
    assert "you're in" in text.lower()
    assert components is not None
    assert components[0]["components"][0]["custom_id"] == PANEL_NEW_ID


def test_approval_dm_rejected_is_polite_and_buttonless():
    text, components = ob.approval_dm_discord(approved=False)
    assert components is None
    assert "wasn't approved" in text.lower()
    assert "Lukas" not in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py::test_approval_dm_approved_has_build_button -v`
Expected: FAIL — `AttributeError: ... 'approval_dm_discord'`

- [ ] **Step 3: Write minimal implementation (append to onboarding.py)**

```python
# append to webhook-handler/handlers/onboarding.py
def approval_dm_discord(approved: bool) -> tuple[str, list[dict] | None]:
    """DM content sent to the requester when an admin decides their link request."""
    if approved:
        text = (
            "\U0001f389 You're in! Tap **\U0001f680 Build an app** to create "
            "your first one."
        )
        components = [{"type": ACTION_ROW, "components": [
            _button("\U0001f680 Build an app", PANEL_NEW_ID, STYLE_SUCCESS),
        ]}]
        return text, components
    text = (
        "Your access request wasn't approved this time. If you think that's a "
        "mistake, reach out to your team admin."
    )
    return text, None
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_onboarding.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/onboarding.py webhook-handler/tests/test_onboarding.py
git commit -m "feat(onboarding): approval/rejection DM builder"
```

---

## Task 4: Discord client — open_dm + send_dm

**Files:**
- Modify: `webhook-handler/clients/discord.py` (add methods to `DiscordClient`, after `post_channel_message` ~:140)
- Test: `webhook-handler/tests/test_discord_dm.py`

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_discord_dm.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clients.discord import DiscordClient


@pytest.fixture
def client():
    return DiscordClient(application_id="app1", bot_token="tok1")


@pytest.mark.asyncio
async def test_open_dm_returns_channel_id(client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "dm-123"}
    mock_http = AsyncMock()
    mock_http.post.return_value = resp
    with patch("clients.discord.httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value = mock_http
        dm_id = await client.open_dm("user-9")
    assert dm_id == "dm-123"
    # called the @me/channels endpoint with recipient_id
    args, kwargs = mock_http.post.call_args
    assert "/users/@me/channels" in args[0]
    assert kwargs["json"] == {"recipient_id": "user-9"}


@pytest.mark.asyncio
async def test_open_dm_returns_none_on_error(client):
    resp = MagicMock()
    resp.status_code = 403
    resp.text = "forbidden"
    mock_http = AsyncMock()
    mock_http.post.return_value = resp
    with patch("clients.discord.httpx.AsyncClient") as ac:
        ac.return_value.__aenter__.return_value = mock_http
        assert await client.open_dm("user-9") is None


@pytest.mark.asyncio
async def test_send_dm_opens_then_posts(client):
    with patch.object(client, "open_dm", AsyncMock(return_value="dm-1")), \
         patch.object(client, "post_channel_message", AsyncMock(return_value=True)) as pcm:
        ok = await client.send_dm("user-9", content="hello", components=[{"x": 1}])
    assert ok is True
    pcm.assert_awaited_once_with("dm-1", content="hello", components=[{"x": 1}])


@pytest.mark.asyncio
async def test_send_dm_fails_soft_when_dm_cannot_open(client):
    with patch.object(client, "open_dm", AsyncMock(return_value=None)):
        assert await client.send_dm("user-9", content="hi") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_discord_dm.py -v`
Expected: FAIL — `AttributeError: 'DiscordClient' object has no attribute 'open_dm'`

- [ ] **Step 3: Write minimal implementation (insert after `post_channel_message` in `clients/discord.py`)**

```python
    async def open_dm(self, user_id: str) -> str | None:
        """Open (or fetch) the bot↔user DM channel. Returns the DM channel id,
        or None on failure (never raises). Works when the user shares a server
        with the bot."""
        url = f"{DISCORD_API_BASE}/users/@me/channels"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bot {self.bot_token}"},
                    json={"recipient_id": user_id},
                )
                if response.status_code in (200, 201):
                    return response.json().get("id")
                logger.error(
                    f"Discord open_dm error: {response.status_code} {response.text}"
                )
                return None
        except Exception as e:
            logger.error(f"Error opening Discord DM: {e}")
            return None

    async def send_dm(self, user_id: str, content: str = "",
                      components: list | None = None) -> bool:
        """DM a user: open the DM channel then post. Best-effort — returns False
        (never raises) so a failed DM never breaks the caller's main action."""
        dm_id = await self.open_dm(user_id)
        if not dm_id:
            return False
        return await self.post_channel_message(
            dm_id, content=content, components=components
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_discord_dm.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/clients/discord.py webhook-handler/tests/test_discord_dm.py
git commit -m "feat(discord-client): open_dm + send_dm (best-effort user DM)"
```

---

## Task 5: Notify the user on link approve/reject

**Files:**
- Modify: `webhook-handler/handlers/discord_commands.py:1166-1181` (`_handle_link_decision._do`)
- Test: `webhook-handler/tests/test_link_decision_notify.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_link_decision_notify.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.discord_commands import DiscordCommandHandler
from handlers.app_builder_panel import LINK_APPROVE_PREFIX, PANEL_NEW_ID


def _make_handler():
    router = MagicMock()
    router.approve_link = AsyncMock()
    router.reject_link = AsyncMock()
    discord = MagicMock()
    discord.edit_original = AsyncMock(return_value=True)
    discord.send_dm = AsyncMock(return_value=True)
    # __init__(self, discord_client, command_router) → self.discord, self.router
    h = DiscordCommandHandler(discord_client=discord, command_router=router)
    return h, router, discord


@pytest.mark.asyncio
async def test_approve_dms_user_with_build_button():
    h, router, discord = _make_handler()
    payload = {"token": "tok", "member": {"user": {"id": "admin1", "username": "ad"}}}
    custom_id = f"{LINK_APPROVE_PREFIX}user-42"
    await h._handle_link_decision(payload, custom_id, approve=True)
    await asyncio.sleep(0)  # let the detached _do() task run
    router.approve_link.assert_awaited()
    discord.send_dm.assert_awaited()
    args, kwargs = discord.send_dm.call_args
    assert args[0] == "user-42"
    sent_components = kwargs.get("components") or (args[2] if len(args) > 2 else None)
    assert sent_components[0]["components"][0]["custom_id"] == PANEL_NEW_ID


@pytest.mark.asyncio
async def test_reject_dms_user_without_button_and_does_not_raise_on_dm_failure():
    h, router, discord = _make_handler()
    discord.send_dm = AsyncMock(return_value=False)  # DM fails
    payload = {"token": "tok", "member": {"user": {"id": "admin1", "username": "ad"}}}
    from handlers.app_builder_panel import LINK_REJECT_PREFIX
    custom_id = f"{LINK_REJECT_PREFIX}user-42"
    await h._handle_link_decision(payload, custom_id, approve=False)
    await asyncio.sleep(0)
    router.reject_link.assert_awaited()
    discord.send_dm.assert_awaited()  # attempted, failure tolerated
```

The behavior asserted (DMs the requester on both approve and reject; tolerates DM failure) is what matters.

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_link_decision_notify.py -v`
Expected: FAIL — `send_dm` not awaited (no notification yet).

- [ ] **Step 3: Write minimal implementation**

In `webhook-handler/handlers/discord_commands.py`, add the import near the other handler imports:
```python
from handlers import onboarding
```
Then update `_handle_link_decision._do` (currently :1166-1176) to DM the requester after updating the admin message:
```python
        async def _do() -> None:
            try:
                if approve:
                    await self.router.approve_link(discord_id, decided_by=admin.get("username", ""))
                    text = f"✅ Approved <@{discord_id}>"
                else:
                    await self.router.reject_link(discord_id)
                    text = f"✖ Rejected <@{discord_id}>"
                await self.discord.edit_original(
                    interaction_token=interaction_token, content=text, components=[],
                )
                # Notify the requester (best-effort — never block the admin action).
                dm_text, dm_components = onboarding.approval_dm_discord(approve)
                await self.discord.send_dm(
                    discord_id, content=dm_text, components=dm_components,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("link decision failed id=%s: %s", discord_id, exc)
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_link_decision_notify.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_link_decision_notify.py
git commit -m "feat(linking): DM the user when their link request is approved/rejected"
```

---

## Task 6: Unify the not-linked copy + show the Link button on Discord

**Files:**
- Modify: `webhook-handler/handlers/commands.py` — `_not_linked_text` (:1777), `_not_linked_msg` (:1785); add `_respond_not_linked`; swap call sites :1366, :1542, :1796, :1841
- Modify: `webhook-handler/handlers/discord_commands.py:1024` — attach Link button on the not-linked response
- Test: `webhook-handler/tests/test_not_linked_card.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_not_linked_card.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter
from handlers.app_builder_panel import LINK_START_ID


def _ctx(platform, with_components):
    ctx = MagicMock()
    ctx.platform = platform
    ctx.respond = AsyncMock()
    ctx.respond_components = AsyncMock() if with_components else None
    return ctx


def _router():
    # Build the router with whatever minimal deps it needs; only the not-linked
    # helpers are exercised here.
    return CommandRouter.__new__(CommandRouter)


@pytest.mark.asyncio
async def test_discord_not_linked_renders_link_button():
    r = _router()
    ctx = _ctx("discord", with_components=True)
    await r._respond_not_linked(ctx)
    ctx.respond_components.assert_awaited()
    text, components = ctx.respond_components.call_args.args[:2]
    assert "Lukas" not in text
    assert components[0]["components"][0]["custom_id"] == LINK_START_ID


@pytest.mark.asyncio
async def test_discord_not_linked_falls_back_to_text_without_components():
    r = _router()
    ctx = _ctx("discord", with_components=False)
    await r._respond_not_linked(ctx)
    ctx.respond.assert_awaited()
    assert "Lukas" not in ctx.respond.call_args.args[0]


@pytest.mark.asyncio
async def test_slack_not_linked_is_plain_language():
    r = _router()
    ctx = _ctx("slack", with_components=False)
    await r._respond_not_linked(ctx)
    ctx.respond.assert_awaited()
    msg = ctx.respond.call_args.args[0]
    assert "Lukas" not in msg
    assert "email access" in msg.lower()
```

(`CommandRouter` is the real class — `commands.py:93`. `_respond_not_linked` is added in Step 3.)

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_not_linked_card.py -v`
Expected: FAIL — `_respond_not_linked` does not exist.

- [ ] **Step 3: Write minimal implementation**

In `webhook-handler/handlers/commands.py`, add the import near the top:
```python
from handlers import onboarding
```
Replace the two helper bodies (:1776-1787) so copy comes from `onboarding`:
```python
    @staticmethod
    def _not_linked_text(ctx: CommandContext) -> str:
        """The 'no email' message, worded for the caller's platform."""
        if ctx.platform == "slack":
            return onboarding.not_linked_text_slack()
        return onboarding.not_linked_text_discord()

    @staticmethod
    def _not_linked_msg() -> str:
        return onboarding.not_linked_text_discord()

    async def _respond_not_linked(self, ctx: CommandContext) -> None:
        """Friendly, self-service not-linked response. On Discord, render the
        Link button inline when the context supports components; otherwise send
        plain text. On Slack, send the plain-language wording (auto-read; no
        button to offer)."""
        if ctx.platform != "slack" and ctx.respond_components is not None:
            await ctx.respond_components(
                onboarding.not_linked_text_discord(), onboarding.link_button_row(),
            )
            return
        await ctx.respond(self._not_linked_text(ctx))
```
Swap the four call sites to use the new helper:
- :1366 `await ctx.respond(self._not_linked_text(ctx))` → `await self._respond_not_linked(ctx)`
- :1542 `await ctx.respond(self._not_linked_text(ctx))` → `await self._respond_not_linked(ctx)`
- :1796 `await ctx.respond(self._not_linked_msg())` → `await self._respond_not_linked(ctx)`
- :1841 `await ctx.respond(self._not_linked_msg())` → `await self._respond_not_linked(ctx)`

In `webhook-handler/handlers/discord_commands.py:1024`, the not-linked content currently is:
```python
                        content=self.router._not_linked_msg(),
```
Change that response to include the Link button. Locate the enclosing return/edit (it builds a response with `content=`). Add `components=onboarding.link_button_row()` to that same response dict / `edit_original` call. Concretely, if it is an `edit_original(...)` call, add the `components=` kwarg; if it returns an interaction dict, set `"components": onboarding.link_button_row()` alongside `"content"`. Use the friendlier text too:
```python
                        content=onboarding.not_linked_text_discord(),
                        components=onboarding.link_button_row(),
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_not_linked_card.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/handlers/discord_commands.py webhook-handler/tests/test_not_linked_card.py
git commit -m "feat(linking): unified self-service not-linked card (kill 'Ask Lukas')"
```

---

## Task 7: Slack welcome card on getting-started messages

**Files:**
- Modify: `webhook-handler/handlers/slack.py` — `_handle_mention` (:64), `_handle_direct_message` (:110)
- Test: `webhook-handler/tests/test_slack_welcome.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_slack_welcome.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.slack import SlackWebhookHandler
from handlers.app_builder_panel import PANEL_NEW_ID


def _handler():
    ow = MagicMock()
    ow.chat_completion = AsyncMock(return_value="some AI answer")
    slack = MagicMock()
    slack.post_message = AsyncMock(return_value="ts1")
    slack.format_ai_response = MagicMock(side_effect=lambda x: x)
    return SlackWebhookHandler(ow, slack), ow, slack


@pytest.mark.asyncio
async def test_dm_greeting_posts_welcome_card_not_ai():
    h, ow, slack = _handler()
    await h._handle_direct_message({"text": "hi", "channel": "D1", "user": "U1"})
    ow.chat_completion.assert_not_awaited()
    blocks = slack.post_message.call_args.kwargs["blocks"]
    action_ids = [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert PANEL_NEW_ID in action_ids


@pytest.mark.asyncio
async def test_dm_real_question_answers_with_buttons_footer():
    h, ow, slack = _handler()
    await h._handle_direct_message(
        {"text": "why is my published app returning a 404", "channel": "D1", "user": "U1"}
    )
    ow.chat_completion.assert_awaited()
    blocks = slack.post_message.call_args.kwargs["blocks"]
    assert any(b["type"] == "actions" for b in blocks)  # footer present
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_slack_welcome.py -v`
Expected: FAIL — current handler never sends `blocks` / always calls `chat_completion`.

- [ ] **Step 3: Write minimal implementation**

In `webhook-handler/handlers/slack.py`, add at top:
```python
from handlers import onboarding
```
Replace `_handle_direct_message` body (from the `logger.info(...DM...)` line onward, :128) so it branches on the heuristic:
```python
        logger.info(f"Slack DM from {user}: {text[:100]}")

        if onboarding.looks_like_getting_started(text):
            await self.slack.post_message(
                channel=channel,
                text="Welcome — here's how to start.",
                blocks=onboarding.welcome_blocks_slack(),
            )
            return {"success": True, "message": "Welcome card sent"}

        system_prompt = self.ai_system_prompt or (
            "You are a helpful AI assistant responding to direct messages in Slack. "
            "Be concise and helpful."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        analysis = await self.openwebui.chat_completion(messages=messages, model=self.ai_model)
        if not analysis:
            return {"success": False, "error": "Failed to get AI response"}

        response_text = self.slack.format_ai_response(analysis)
        answer_block = {"type": "section", "text": {"type": "mrkdwn", "text": response_text}}
        await self.slack.post_message(
            channel=channel,
            text=response_text,
            blocks=[answer_block, onboarding.buttons_footer_slack()],
        )
        return {"success": True, "message": "DM handled, response sent"}
```
Apply the same getting-started branch + footer to `_handle_mention` (:90-103): if `looks_like_getting_started(clean_text)`, post `welcome_blocks_slack()` in-thread and return; otherwise post the AI answer with `blocks=[answer_block, onboarding.buttons_footer_slack()]` plus the existing `thread_ts`.

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_slack_welcome.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/slack.py webhook-handler/tests/test_slack_welcome.py
git commit -m "feat(slack): welcome card on greetings + buttons footer on answers"
```

---

## Task 8: Lead /aiui help with the welcome + buttons (Discord)

**Files:**
- Modify: `webhook-handler/handlers/commands.py` — `_handle_help` (:395-420)
- Test: `webhook-handler/tests/test_help_welcome.py` (create)

Current code (commands.py:395-420): `_handle_help` builds an inline `help_text` string (the long dev-command list) and ends with `await ctx.respond(help_text)`. We extract a static `_help_text()`, demote dev commands, and render with the welcome buttons on Discord.

- [ ] **Step 1: Write the failing test**

```python
# webhook-handler/tests/test_help_welcome.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from handlers.commands import CommandRouter
from handlers.app_builder_panel import PANEL_NEW_ID


def test_help_text_leads_with_build_and_schedule_not_dev_jargon():
    text = CommandRouter._help_text()
    head = text[:400].lower()
    assert "build an app" in head
    assert "schedule" in head
    # dev commands are demoted, not in the first 400 chars
    assert "owasp" not in head
    assert "pr-review" not in head


@pytest.mark.asyncio
async def test_handle_help_renders_welcome_buttons_on_discord():
    r = CommandRouter.__new__(CommandRouter)
    ctx = MagicMock()
    ctx.platform = "discord"
    ctx.respond = AsyncMock()
    ctx.respond_components = AsyncMock()
    await r._handle_help(ctx)
    ctx.respond_components.assert_awaited()
    _text, components = ctx.respond_components.call_args.args[:2]
    ids = [c["custom_id"] for c in components[0]["components"]]
    assert PANEL_NEW_ID in ids
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_help_welcome.py -v`
Expected: FAIL — `_help_text` missing / dev commands at top / no buttons.

- [ ] **Step 3: Implement**

Add a static `_help_text()` to `CommandRouter` and rewrite `_handle_help` to use it and render buttons on Discord:
```python
    @staticmethod
    def _help_text() -> str:
        return (
            "**Here's what I can do**\n"
            "• \U0001f680 **Build an app** — describe a website and I'll build it.\n"
            "• ⏰ **Schedule a task** — run something on a repeat (e.g. "
            "*summarize my emails every morning*).\n"
            "• \U0001f4ac **Ask a question** — just type `/aiui ask <your question>`.\n"
            "\nTip: look for the **AIUI App Builder** panel and tap a button — "
            "no commands needed.\n"
            "\n_Advanced:_ `/aiui aiuibuilder`, `/aiui mcp`, `/aiui pr-review`, "
            "`/aiui analyze`, `/aiui security`, `/aiui web-search` "
            "(for technical users)."
        )

    async def _handle_help(self, ctx: CommandContext) -> None:
        text = self._help_text()
        if ctx.platform != "slack" and ctx.respond_components is not None:
            await ctx.respond_components(text, onboarding.welcome_components_discord())
            return
        await ctx.respond(text)
```
(`onboarding` is already imported in Task 6. The old inline `help_text` block and its `await ctx.respond(help_text)` are removed.)

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_help_welcome.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add webhook-handler/handlers/commands.py webhook-handler/tests/test_help_welcome.py
git commit -m "feat(help): /aiui help leads with Build/Schedule/Ask + buttons, demotes dev commands"
```

---

## Task 9: Update existing tests + full suite + final commit

**Files:**
- Modify: `webhook-handler/tests/test_two_button_entry.py` (:101, :318, :342), `test_slack_command_build_notify.py` (:30), `test_slack_interactions.py` (:301), `test_slack_schedule_interactions.py` (:45)

- [ ] **Step 1: Run the full suite to see what the new copy broke**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: a handful of failures in the four files above (they assert old "Ask Lukas" / mock the helpers and check response text/flow).

- [ ] **Step 2: Update each failing assertion to the new behavior**

For tests that mock `_not_linked_text`/`_not_linked_msg` with a fixed string and assert it appears in the response: keep the mock, but where a Discord path now calls `_respond_not_linked` (which uses `respond_components`), update the assertion to check `respond_components` was called with the Link button (`custom_id == LINK_START_ID`) instead of `respond(text)`. For Slack paths, assert the plain-language string (no "Lukas"). Make the minimal change per test; do not weaken coverage.

- [ ] **Step 3: Re-run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 4: Final commit**

```bash
git add webhook-handler/tests/
git commit -m "test: update onboarding/linking tests for unified not-linked + welcome"
```

---

## Notes for the implementer
- **Discord pinned panel:** the spec mentions rewording it to be self-explanatory. The current `PANEL_CONTENT` (`app_builder_panel.py:44`) already explains the front door clearly ("Hit Build an app and I'll open a private space…"), so we leave it unchanged to avoid churn. Discord's welcome surfaces are the existing pinned panel + the improved `/aiui help` (Task 8). If you disagree on review, a one-line copy tweak to `PANEL_CONTENT` is the only change needed.
- **No backend/DB changes.** Everything is in `webhook-handler`. No deploy of `mcp-servers/tasks` needed.
- **Deploy (after merge):** `webhook-handler` is NOT covered by the orchestrator script — deploy manually per `CLAUDE.md` (one `scp` per changed file, then `docker compose -f docker-compose.unified.yml up -d --build webhook-handler`). Changed runtime files: `handlers/onboarding.py`, `clients/discord.py`, `handlers/discord_commands.py`, `handlers/commands.py`, `handlers/slack.py`.
- **Manual smoke after deploy:** DM the Slack bot "hi" → welcome card with two buttons; ask it a real question → answer + buttons footer. On Discord, trigger a not-linked path → friendly text + Link button; approve a link request → requester gets a DM.
- If a class/method name in a test stub doesn't match the real code (e.g. `CommandRouter`, `DiscordInteractionsHandler` constructor), fix the stub to match — the asserted behavior is what matters, not the stub shape.
